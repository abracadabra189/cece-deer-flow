"""Debounced background worker for automatic skill synthesis.

Synthesis costs one model call plus two security scans per trajectory, so it
must never sit on a run's critical path. This module keeps it off that path
using the same shape the memory backend uses: the ``after_agent`` hook does only
cheap in-memory work and hands a captured payload to a process-local queue, and
a daemon timer thread drains the queue after a quiet period.

Design notes:

- **Batching never drops trajectories.** Debouncing delays the batch; every
  submitted request in the window is synthesized. A run is a distinct learning
  opportunity, so coalescing them into one skill would lose scenarios.
- **Bounded latency.** The timer arms on the first submit of a batch and is
  *not* rearmed by later submits, so continuous traffic cannot starve
  processing the way a trailing-edge debounce would.
- **Bounded memory.** ``queue_max_size`` rejects new submissions when full
  rather than evicting queued work, and logs, so a stalled model cannot grow
  the queue without bound.
- **Identity travels as data.** The worker thread inherits no ContextVars, so
  ``user_id`` / ``thread_id`` / ``run_id`` / ``trace_id`` are captured by the
  producer and carried on the request.
- **Best effort.** A process crash loses pending trajectories, exactly like the
  memory queue; ``flush`` exists so graceful shutdown can drain them.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from deerflow.config.app_config import AppConfig, get_app_config
from deerflow.config.auto_skill_config import AutoSkillConfig
from deerflow.skills.auto.trajectory import RunTrajectory
from deerflow.trace_context import ensure_trace_context

logger = logging.getLogger(__name__)

Synthesizer = Callable[..., Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class AutoSkillRequest:
    """One completed run handed to the synthesis worker.

    Every field is plain data captured while the request context was still
    alive, because the worker thread cannot read ContextVars.
    """

    trajectory: RunTrajectory
    user_id: str
    thread_id: str | None
    run_id: str | None
    trace_id: str | None


def _default_synthesizer(**kwargs: Any) -> Awaitable[Any]:
    from deerflow.skills.auto.synthesizer import synthesize_skill

    return synthesize_skill(**kwargs)


class AutoSkillQueue:
    """Process-local, debounce-batched queue of pending skill syntheses."""

    def __init__(
        self,
        *,
        synthesizer: Synthesizer | None = None,
        timer_factory: Callable[[float, Callable[[], None]], Any] | None = None,
        app_config_resolver: Callable[[], AppConfig] | None = None,
    ) -> None:
        self._synthesizer = synthesizer or _default_synthesizer
        self._timer_factory = timer_factory or threading.Timer
        self._app_config_resolver = app_config_resolver or get_app_config
        self._lock = threading.Lock()
        self._pending: list[AutoSkillRequest] = []
        self._timer: Any | None = None
        self._stopped = False
        self._submitted_total = 0
        self._dropped_total = 0
        self._synthesized_total = 0

    # ── observability ────────────────────────────────────────────────────────

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "pending": len(self._pending),
                "submitted": self._submitted_total,
                "dropped": self._dropped_total,
                "synthesized": self._synthesized_total,
            }

    # ── producer side ────────────────────────────────────────────────────────

    def submit(self, request: AutoSkillRequest, *, debounce_seconds: float, queue_max_size: int) -> bool:
        """Queue one trajectory, arming the drain timer when the batch opens.

        Returns ``False`` when the queue is stopped or full. Never raises, and
        never blocks on model or filesystem work.
        """
        with self._lock:
            if self._stopped:
                return False
            if len(self._pending) >= max(1, queue_max_size):
                self._dropped_total += 1
                logger.warning(
                    "auto-skill queue is full (%d pending); dropping trajectory for thread=%s run=%s",
                    len(self._pending),
                    request.thread_id,
                    request.run_id,
                )
                return False
            opens_batch = self._timer is None
            self._pending.append(request)
            self._submitted_total += 1
            if opens_batch:
                self._arm_timer(max(0.0, float(debounce_seconds)))
        return True

    def _arm_timer(self, delay_seconds: float) -> None:
        """Arm the drain timer. Caller holds ``_lock``."""
        timer = self._timer_factory(delay_seconds, self._on_timer)
        # threading.Timer subclasses Thread; a daemon timer must never hold the
        # interpreter open at shutdown. Injected fakes may not support the
        # attribute, which is not worth failing a submission over.
        try:
            timer.daemon = True
        except (AttributeError, RuntimeError, ValueError):
            logger.debug("auto-skill timer does not accept a daemon flag", exc_info=True)
        self._timer = timer
        timer.start()

    # ── worker side ──────────────────────────────────────────────────────────

    def _on_timer(self) -> None:
        with self._lock:
            batch = self._pending
            self._pending = []
            self._timer = None
        if batch:
            self._run_batch(batch)

    def _run_batch(self, batch: list[AutoSkillRequest]) -> None:
        """Run one batch on the caller's thread with a fresh event loop.

        A fresh ``asyncio.run`` per batch gives the synthesis model call and the
        scanners their own loop-bound resources, which is the property the memory
        backend relies on to keep a shared async HTTP pool from crossing loops.
        """
        try:
            asyncio.run(self._process_batch(batch))
        except Exception:
            logger.warning("auto-skill batch failed", exc_info=True)

    async def _process_batch(self, batch: list[AutoSkillRequest]) -> None:
        app_config = await asyncio.to_thread(self._app_config_resolver)
        config: AutoSkillConfig = app_config.auto_skill
        if not config.enabled:
            # Disabled between enqueue and drain: honour the newer decision.
            logger.info("auto-skill disabled before drain; dropping %d queued trajectory(ies)", len(batch))
            return

        for request in batch:
            with ensure_trace_context(request.trace_id):
                try:
                    result = await self._synthesizer(
                        trajectory=request.trajectory,
                        user_id=request.user_id,
                        thread_id=request.thread_id,
                        run_id=request.run_id,
                        config=config,
                        app_config=app_config,
                    )
                except Exception:
                    logger.warning(
                        "auto-skill synthesis raised for thread=%s run=%s",
                        request.thread_id,
                        request.run_id,
                        exc_info=True,
                    )
                    continue
                if result is not None:
                    with self._lock:
                        self._synthesized_total += 1

    # ── drain / shutdown ─────────────────────────────────────────────────────

    def flush(self, *, timeout: float | None = None) -> int:
        """Drain pending trajectories synchronously; returns the count handed off.

        Must be called off the event loop (``await asyncio.to_thread(queue.flush,
        timeout=...)``) because it runs its own loop. When ``timeout`` is given
        and the drain does not finish in time, the remaining work continues on a
        daemon thread and is reported as undrained.
        """
        with self._lock:
            if self._timer is not None:
                try:
                    self._timer.cancel()
                except Exception:
                    logger.debug("auto-skill timer cancel failed", exc_info=True)
                self._timer = None
            batch = self._pending
            self._pending = []

        if not batch:
            return 0

        if timeout is None:
            self._run_batch(batch)
            return len(batch)

        worker = threading.Thread(target=self._run_batch, args=(batch,), name="auto-skill-flush", daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            logger.warning("auto-skill shutdown flush timed out after %.1fs with %d trajectory(ies) in flight", timeout, len(batch))
            return 0
        return len(batch)

    def shutdown(self) -> None:
        """Stop accepting submissions and cancel a pending timer."""
        with self._lock:
            self._stopped = True
            if self._timer is not None:
                try:
                    self._timer.cancel()
                except Exception:
                    logger.debug("auto-skill timer cancel failed", exc_info=True)
                self._timer = None


# ── process singleton ────────────────────────────────────────────────────────

_auto_skill_queue: AutoSkillQueue | None = None
_auto_skill_queue_lock = threading.Lock()


def get_auto_skill_queue() -> AutoSkillQueue:
    """Return the process-wide auto-skill queue, constructing it on first use."""
    global _auto_skill_queue
    with _auto_skill_queue_lock:
        if _auto_skill_queue is None:
            _auto_skill_queue = AutoSkillQueue()
        return _auto_skill_queue


def reset_auto_skill_queue() -> None:
    """Drop the process singleton. Tests and config re-injection use this."""
    global _auto_skill_queue
    with _auto_skill_queue_lock:
        if _auto_skill_queue is not None:
            _auto_skill_queue.shutdown()
        _auto_skill_queue = None
