"""Middleware that distils a finished run into a reusable skill.

Producer half of the auto-skill feature. It runs in ``after_agent`` — the point
where the answer has already been streamed to the user — and does only cheap
in-memory work: walk the messages, bound every field, and hand the result to the
debounced queue in :mod:`deerflow.skills.auto.queue`. The model call, the
security scans and the disk write all happen later on a worker thread, so this
hook adds no latency to a run and cannot fail one.

Registered on the lead chain only (``build_middlewares``), never on the subagent
runtime base: a subagent's trajectory is a fragment of the lead's, and learning
from fragments would produce skills that describe partial work.

Gating keeps the feature from generating noise:

- ``auto_skill.enabled`` is off by default;
- a run with no genuine user query or no visible final answer is skipped, since
  neither yields a reproducible scenario;
- runs with fewer successful tool calls than ``min_tool_calls`` are skipped —
  with no data-fetching path there is nothing worth capturing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.config import get_config
from langgraph.runtime import Runtime

from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.skills.auto.queue import AutoSkillQueue, AutoSkillRequest, get_auto_skill_queue
from deerflow.skills.auto.trajectory import RunTrajectory, extract_run_trajectory
from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY, resolve_trace_id

if TYPE_CHECKING:
    from deerflow.config.auto_skill_config import AutoSkillConfig

logger = logging.getLogger(__name__)


class AutoSkillMiddlewareState(AgentState):
    """Compatible with the ``ThreadState`` schema."""

    pass


class AutoSkillMiddleware(AgentMiddleware[AutoSkillMiddlewareState]):
    """Queue the completed run's trajectory for background skill synthesis."""

    state_schema = AutoSkillMiddlewareState

    def __init__(
        self,
        *,
        config: AutoSkillConfig,
        agent_name: str | None = None,
        queue: AutoSkillQueue | None = None,
    ) -> None:
        """Initialize the middleware.

        Args:
            config: Resolved ``auto_skill`` configuration snapshot for this build.
            agent_name: Custom agent the run belonged to, for log attribution.
            queue: Explicit queue; defaults to the process-wide singleton. Tests
                inject their own to observe submissions without a timer thread.
        """
        super().__init__()
        self._config = config
        self._agent_name = agent_name
        self._queue = queue

    def _resolve_queue(self) -> AutoSkillQueue:
        return self._queue if self._queue is not None else get_auto_skill_queue()

    def _resolve_request(self, state: AutoSkillMiddlewareState, runtime: Runtime) -> AutoSkillRequest | None:
        """Build one synthesis request without touching the model or the disk."""
        if not self._config.enabled:
            return None

        runtime_context = runtime.context if isinstance(runtime.context, dict) else {}

        # thread_id: runtime context first, then LangGraph's configurable, the
        # same fallback order MemoryMiddleware uses for standalone server callers.
        thread_id = runtime_context.get("thread_id")
        if thread_id is None:
            try:
                config_data = get_config()
            except Exception:
                config_data = None
            if isinstance(config_data, dict):
                thread_id = config_data.get("configurable", {}).get("thread_id")

        trajectory = extract_run_trajectory(state, max_tool_result_chars=self._config.max_tool_result_chars)
        if trajectory is None:
            return None

        if not self._is_worth_learning(trajectory, thread_id=thread_id):
            return None

        run_id = runtime_context.get("run_id")
        return AutoSkillRequest(
            trajectory=trajectory,
            # Captured here, while the request context is alive: the worker thread
            # inherits no ContextVars.
            user_id=resolve_runtime_user_id(runtime),
            thread_id=thread_id if isinstance(thread_id, str) else None,
            run_id=run_id if isinstance(run_id, str) else None,
            trace_id=resolve_trace_id(runtime_context.get(DEERFLOW_TRACE_METADATA_KEY)),
        )

    def _is_worth_learning(self, trajectory: RunTrajectory, *, thread_id: Any) -> bool:
        """Apply the min-tool-call gate, logging why a run was skipped."""
        if trajectory.successful_tool_calls >= self._config.min_tool_calls:
            return True
        logger.debug(
            "auto-skill skipped thread=%s agent=%s: %d successful tool call(s) below min_tool_calls=%d",
            thread_id,
            self._agent_name,
            trajectory.successful_tool_calls,
            self._config.min_tool_calls,
        )
        return False

    def _submit(self, state: AutoSkillMiddlewareState, runtime: Runtime) -> None:
        """Extract and enqueue, swallowing every failure.

        Skill learning is purely additive: a corrupt checkpoint, a full queue or
        a programming error here has zero user value, while propagating would
        fail a run whose answer was already delivered. Failures are logged with
        their traceback so they stay visible.
        """
        try:
            request = self._resolve_request(state, runtime)
            if request is None:
                return
            self._resolve_queue().submit(
                request,
                debounce_seconds=self._config.debounce_seconds,
                queue_max_size=self._config.queue_max_size,
            )
        except Exception:
            logger.warning("auto-skill enqueue failed; the run continues without skill synthesis", exc_info=True)

    @override
    def after_agent(self, state: AutoSkillMiddlewareState, runtime: Runtime) -> dict | None:
        """Queue the trajectory for synthesis after the agent completes."""
        self._submit(state, runtime)
        return None

    @override
    async def aafter_agent(self, state: AutoSkillMiddlewareState, runtime: Runtime) -> dict | None:
        """Async path: identical, because submission never blocks."""
        self._submit(state, runtime)
        return None
