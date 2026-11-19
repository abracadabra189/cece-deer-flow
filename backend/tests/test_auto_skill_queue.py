"""Debounced auto-skill queue: batching, bounds, drain and failure isolation."""

import threading
from dataclasses import dataclass

import pytest

from deerflow.config.auto_skill_config import AutoSkillConfig
from deerflow.skills.auto.queue import AutoSkillQueue, AutoSkillRequest, get_auto_skill_queue, reset_auto_skill_queue
from deerflow.skills.auto.trajectory import RunTrajectory, ToolStep


class FakeTimer:
    """Manually fired stand-in for ``threading.Timer``."""

    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        # Mirrors threading.Timer, which is a Thread subclass defaulting to False.
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        self.callback()


class TimerFactory:
    def __init__(self) -> None:
        self.timers: list[FakeTimer] = []

    def __call__(self, delay: float, callback) -> FakeTimer:
        timer = FakeTimer(delay, callback)
        self.timers.append(timer)
        return timer

    @property
    def armed(self) -> list[FakeTimer]:
        return [timer for timer in self.timers if timer.started and not timer.cancelled]


@dataclass
class FakeAppConfig:
    auto_skill: AutoSkillConfig


def _request(*, thread_id: str = "thread-1", run_id: str = "run-1", trace_id: str = "trace-1", user_id: str = "user-1") -> AutoSkillRequest:
    return AutoSkillRequest(
        trajectory=RunTrajectory(
            query="查一下 A 公司的融资历史",
            skill_names=(),
            tool_steps=(ToolStep(tool_name="finance_query", args_summary="{}", result_summary="{}", status="success"),),
            final_answer="结论",
            todo_texts=(),
        ),
        user_id=user_id,
        thread_id=thread_id,
        run_id=run_id,
        trace_id=trace_id,
    )


class RecordingSynthesizer:
    def __init__(self, *, result: object = object(), raises: bool = False) -> None:
        self.calls: list[dict] = []
        self._result = result
        self._raises = raises

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise RuntimeError("synthesis exploded")
        return self._result


def _queue(*, synthesizer=None, config: AutoSkillConfig | None = None) -> tuple[AutoSkillQueue, TimerFactory, RecordingSynthesizer]:
    timers = TimerFactory()
    synth = synthesizer or RecordingSynthesizer()
    resolved_config = config or AutoSkillConfig(enabled=True)
    queue = AutoSkillQueue(
        synthesizer=synth,
        timer_factory=timers,
        app_config_resolver=lambda: FakeAppConfig(auto_skill=resolved_config),
    )
    return queue, timers, synth


class TestBatching:
    def test_first_submit_arms_exactly_one_timer(self):
        queue, timers, _ = _queue()

        assert queue.submit(_request(), debounce_seconds=20.0, queue_max_size=64) is True

        assert len(timers.timers) == 1
        assert timers.timers[0].delay == 20.0
        assert timers.timers[0].daemon is True
        assert queue.pending_count == 1

    def test_later_submits_join_the_batch_without_rearming(self):
        """Bounded latency: continuous traffic cannot starve the drain."""
        queue, timers, _ = _queue()

        for index in range(5):
            queue.submit(_request(run_id=f"run-{index}"), debounce_seconds=20.0, queue_max_size=64)

        assert len(timers.timers) == 1
        assert queue.pending_count == 5

    def test_firing_the_timer_synthesizes_every_queued_trajectory(self):
        """Batching delays work; it never coalesces distinct scenarios away."""
        queue, timers, synth = _queue()
        for index in range(3):
            queue.submit(_request(run_id=f"run-{index}"), debounce_seconds=20.0, queue_max_size=64)

        timers.timers[0].fire()

        assert len(synth.calls) == 3
        assert [call["run_id"] for call in synth.calls] == ["run-0", "run-1", "run-2"]
        assert queue.pending_count == 0
        assert queue.stats["synthesized"] == 3

    def test_a_new_batch_arms_a_new_timer_after_the_first_drains(self):
        queue, timers, synth = _queue()
        queue.submit(_request(run_id="run-0"), debounce_seconds=20.0, queue_max_size=64)
        timers.timers[0].fire()

        queue.submit(_request(run_id="run-1"), debounce_seconds=20.0, queue_max_size=64)

        assert len(timers.timers) == 2
        assert len(synth.calls) == 1
        timers.timers[1].fire()
        assert len(synth.calls) == 2

    def test_firing_an_already_drained_queue_adds_no_work(self):
        queue, timers, synth = _queue()
        queue.submit(_request(), debounce_seconds=20.0, queue_max_size=8)
        queue.flush()
        drained_calls = len(synth.calls)

        # The cancelled timer must not reprocess what flush already drained.
        timers.timers[0].fire()

        assert len(synth.calls) == drained_calls
        assert queue.pending_count == 0


class TestIdentityAndConfigPropagation:
    def test_carries_captured_identity_to_the_synthesizer(self):
        """The worker thread inherits no ContextVars, so identity must be data."""
        queue, timers, synth = _queue()
        queue.submit(_request(user_id="user-9", thread_id="thread-9", run_id="run-9", trace_id="trace-9"), debounce_seconds=1.0, queue_max_size=8)

        timers.timers[0].fire()

        call = synth.calls[0]
        assert call["user_id"] == "user-9"
        assert call["thread_id"] == "thread-9"
        assert call["run_id"] == "run-9"
        assert isinstance(call["trajectory"], RunTrajectory)
        assert isinstance(call["config"], AutoSkillConfig)
        assert isinstance(call["app_config"], FakeAppConfig)

    def test_binds_the_captured_trace_id_during_synthesis(self):
        from deerflow.trace_context import get_current_trace_id

        observed: list[str | None] = []

        async def _synth(**kwargs):
            observed.append(get_current_trace_id())
            return object()

        queue, timers, _ = _queue(synthesizer=_synth)
        queue.submit(_request(trace_id="trace-bound"), debounce_seconds=1.0, queue_max_size=8)

        timers.timers[0].fire()

        assert observed == ["trace-bound"]

    def test_config_disabled_between_enqueue_and_drain_drops_the_batch(self):
        """A mid-flight disable must be honoured by the newer decision."""
        timers = TimerFactory()
        synth = RecordingSynthesizer()
        queue = AutoSkillQueue(
            synthesizer=synth,
            timer_factory=timers,
            app_config_resolver=lambda: FakeAppConfig(auto_skill=AutoSkillConfig(enabled=False)),
        )
        queue.submit(_request(), debounce_seconds=1.0, queue_max_size=8)

        timers.timers[0].fire()

        assert synth.calls == []
        assert queue.pending_count == 0


class TestBounds:
    def test_a_full_queue_rejects_the_new_submission(self):
        """Queued work is never evicted; a stalled model cannot grow the queue."""
        queue, timers, _ = _queue()

        assert queue.submit(_request(run_id="run-0"), debounce_seconds=20.0, queue_max_size=2) is True
        assert queue.submit(_request(run_id="run-1"), debounce_seconds=20.0, queue_max_size=2) is True
        assert queue.submit(_request(run_id="run-2"), debounce_seconds=20.0, queue_max_size=2) is False

        assert queue.pending_count == 2
        assert queue.stats["dropped"] == 1

        timers.timers[0].fire()
        assert queue.stats["synthesized"] == 2

    def test_queue_max_size_one_is_honoured(self):
        queue, _, _ = _queue()

        assert queue.submit(_request(), debounce_seconds=1.0, queue_max_size=1) is True
        assert queue.submit(_request(), debounce_seconds=1.0, queue_max_size=1) is False

    def test_a_stopped_queue_rejects_submissions(self):
        queue, timers, synth = _queue()
        queue.shutdown()

        assert queue.submit(_request(), debounce_seconds=1.0, queue_max_size=8) is False
        assert synth.calls == []
        assert timers.armed == []

    def test_shutdown_cancels_a_pending_timer(self):
        queue, timers, _ = _queue()
        queue.submit(_request(), debounce_seconds=20.0, queue_max_size=8)

        queue.shutdown()

        assert timers.timers[0].cancelled is True


class TestFailureIsolation:
    def test_one_failing_synthesis_does_not_stop_the_batch(self):
        calls: list[str] = []

        async def _synth(**kwargs):
            calls.append(kwargs["run_id"])
            if kwargs["run_id"] == "run-1":
                raise RuntimeError("provider exploded")
            return object()

        queue, timers, _ = _queue(synthesizer=_synth)
        for index in range(3):
            queue.submit(_request(run_id=f"run-{index}"), debounce_seconds=1.0, queue_max_size=8)

        timers.timers[0].fire()

        assert calls == ["run-0", "run-1", "run-2"]
        assert queue.stats["synthesized"] == 2

    def test_a_none_result_is_not_counted_as_synthesized(self):
        queue, timers, synth = _queue(synthesizer=RecordingSynthesizer(result=None))
        queue.submit(_request(), debounce_seconds=1.0, queue_max_size=8)

        timers.timers[0].fire()

        assert len(synth.calls) == 1
        assert queue.stats["synthesized"] == 0

    def test_a_broken_app_config_resolver_does_not_escape_the_worker(self):
        def _explode():
            raise RuntimeError("config unreadable")

        timers = TimerFactory()
        synth = RecordingSynthesizer()
        queue = AutoSkillQueue(synthesizer=synth, timer_factory=timers, app_config_resolver=_explode)
        queue.submit(_request(), debounce_seconds=1.0, queue_max_size=8)

        # _run_batch swallows: a worker thread exception must not surface anywhere.
        timers.timers[0].fire()

        assert synth.calls == []


class TestFlush:
    def test_flush_drains_pending_and_cancels_the_timer(self):
        queue, timers, synth = _queue()
        queue.submit(_request(run_id="run-0"), debounce_seconds=20.0, queue_max_size=8)
        queue.submit(_request(run_id="run-1"), debounce_seconds=20.0, queue_max_size=8)

        drained = queue.flush()

        assert drained == 2
        assert len(synth.calls) == 2
        assert queue.pending_count == 0
        assert timers.timers[0].cancelled is True

    def test_flush_with_nothing_pending_is_a_no_op(self):
        queue, _, synth = _queue()

        assert queue.flush() == 0
        assert synth.calls == []

    def test_bounded_flush_reports_zero_when_it_cannot_finish(self, monkeypatch):
        release = threading.Event()

        def _blocking_batch(batch):
            release.wait(5)

        queue, _, _ = _queue()
        monkeypatch.setattr(queue, "_run_batch", _blocking_batch)
        queue.submit(_request(), debounce_seconds=20.0, queue_max_size=8)

        assert queue.flush(timeout=0.05) == 0

        release.set()

    def test_bounded_flush_reports_the_count_when_it_finishes(self):
        queue, _, synth = _queue()
        queue.submit(_request(), debounce_seconds=20.0, queue_max_size=8)

        assert queue.flush(timeout=10.0) == 1
        assert len(synth.calls) == 1


class TestSingleton:
    def test_returns_one_process_wide_instance(self):
        reset_auto_skill_queue()
        try:
            first = get_auto_skill_queue()
            assert get_auto_skill_queue() is first
        finally:
            reset_auto_skill_queue()

    def test_reset_stops_the_previous_instance(self):
        reset_auto_skill_queue()
        try:
            first = get_auto_skill_queue()
            reset_auto_skill_queue()
            second = get_auto_skill_queue()

            assert second is not first
            assert first.submit(_request(), debounce_seconds=1.0, queue_max_size=8) is False
        finally:
            reset_auto_skill_queue()

    def test_the_default_synthesizer_resolves_lazily(self):
        """The real synthesizer is imported per call so config reloads are picked up."""
        from deerflow.skills.auto.queue import _default_synthesizer

        with pytest.raises(TypeError):
            # Missing kwargs proves the real synthesize_skill was reached.
            _default_synthesizer()
