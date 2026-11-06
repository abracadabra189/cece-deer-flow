"""AutoSkillMiddleware gating and non-blocking enqueue contract."""

import asyncio

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.auto_skill_middleware import AutoSkillMiddleware
from deerflow.config.auto_skill_config import AutoSkillConfig
from deerflow.skills.auto.queue import AutoSkillRequest


class RecordingQueue:
    """Stand-in that records submissions without arming a timer thread."""

    def __init__(self, *, accept: bool = True) -> None:
        self.requests: list[AutoSkillRequest] = []
        self.calls: list[dict] = []
        self._accept = accept

    def submit(self, request: AutoSkillRequest, *, debounce_seconds: float, queue_max_size: int) -> bool:
        self.requests.append(request)
        self.calls.append({"debounce_seconds": debounce_seconds, "queue_max_size": queue_max_size})
        return self._accept


def _state(*, tool_calls: int = 2, answer: str = "结论") -> dict:
    messages: list = [HumanMessage(content="查一下 A 公司的融资历史")]
    for index in range(tool_calls):
        messages.append(AIMessage(content="", tool_calls=[{"name": f"tool_{index}", "id": f"c{index}", "args": {"i": index}}]))
        messages.append(ToolMessage(content=f"result-{index}", tool_call_id=f"c{index}", name=f"tool_{index}"))
    messages.append(AIMessage(content=answer))
    return {"messages": messages}


def _runtime(**context) -> Runtime:
    return Runtime(context={"thread_id": "thread-1", "user_id": "user-1", "run_id": "run-1", **context})


class TestGating:
    def test_disabled_config_never_submits(self):
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=False), queue=queue)

        assert middleware.after_agent(_state(), _runtime()) is None
        assert queue.requests == []

    def test_enabled_config_submits_one_request(self):
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=queue)

        assert middleware.after_agent(_state(), _runtime()) is None

        assert len(queue.requests) == 1
        request = queue.requests[0]
        assert request.user_id == "user-1"
        assert request.thread_id == "thread-1"
        assert request.run_id == "run-1"
        assert request.trajectory.query == "查一下 A 公司的融资历史"

    def test_passes_configured_bounds_to_the_queue(self):
        queue = RecordingQueue()
        config = AutoSkillConfig(enabled=True, debounce_seconds=7.5, queue_max_size=9)
        middleware = AutoSkillMiddleware(config=config, queue=queue)

        middleware.after_agent(_state(), _runtime())

        assert queue.calls == [{"debounce_seconds": 7.5, "queue_max_size": 9}]

    def test_min_tool_calls_gate_skips_shallow_runs(self):
        """A run that fetched nothing has no data path worth capturing."""
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True, min_tool_calls=2), queue=queue)

        middleware.after_agent(_state(tool_calls=1), _runtime())

        assert queue.requests == []

    def test_min_tool_calls_zero_accepts_a_tool_free_run(self):
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True, min_tool_calls=0), queue=queue)

        middleware.after_agent(_state(tool_calls=0), _runtime())

        assert len(queue.requests) == 1

    def test_errored_tool_calls_do_not_satisfy_the_gate(self):
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True, min_tool_calls=1), queue=queue)
        state = {
            "messages": [
                HumanMessage(content="查询"),
                AIMessage(content="", tool_calls=[{"name": "t", "id": "c1", "args": {}}]),
                ToolMessage(content="boom", tool_call_id="c1", name="t", status="error"),
                AIMessage(content="失败了"),
            ]
        }

        middleware.after_agent(state, _runtime())

        assert queue.requests == []

    def test_skips_a_run_without_a_final_answer(self):
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=queue)

        middleware.after_agent({"messages": [HumanMessage(content="查询")]}, _runtime())

        assert queue.requests == []

    def test_skips_empty_state(self):
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=queue)

        assert middleware.after_agent({"messages": []}, _runtime()) is None
        assert queue.requests == []


class TestIdentityCapture:
    def test_captures_a_trace_id_for_the_worker_thread(self):
        """The Timer thread inherits no ContextVars, so identity must be data."""
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=queue)

        middleware.after_agent(_state(), _runtime())

        assert queue.requests[0].trace_id

    def test_propagates_an_inbound_trace_id(self):
        from deerflow.trace_context import DEERFLOW_TRACE_METADATA_KEY

        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=queue)

        middleware.after_agent(_state(), _runtime(**{DEERFLOW_TRACE_METADATA_KEY: "trace-inbound"}))

        assert queue.requests[0].trace_id == "trace-inbound"

    def test_defaults_user_id_when_runtime_carries_none(self):
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=queue)

        middleware.after_agent(_state(), Runtime(context={"thread_id": "thread-1"}))

        assert queue.requests[0].user_id

    def test_thread_id_falls_back_to_langgraph_configurable(self, monkeypatch):
        """Standalone LangGraph Server callers carry the id in configurable only."""
        from deerflow.agents.middlewares import auto_skill_middleware as module

        monkeypatch.setattr(module, "get_config", lambda: {"configurable": {"thread_id": "thread-from-config"}})
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=queue)

        middleware.after_agent(_state(), Runtime(context={"user_id": "user-1"}))

        assert queue.requests[0].thread_id == "thread-from-config"

    def test_survives_a_missing_langgraph_config(self, monkeypatch):
        from deerflow.agents.middlewares import auto_skill_middleware as module

        def _raise():
            raise RuntimeError("no active graph config")

        monkeypatch.setattr(module, "get_config", _raise)
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=queue)

        middleware.after_agent(_state(), Runtime(context={"user_id": "user-1"}))

        assert len(queue.requests) == 1
        assert queue.requests[0].thread_id is None


class TestAsyncPath:
    def test_aafter_agent_submits_identically(self):
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=queue)

        result = asyncio.run(middleware.aafter_agent(_state(), _runtime()))

        assert result is None
        assert len(queue.requests) == 1
        assert queue.requests[0].thread_id == "thread-1"

    def test_aafter_agent_respects_the_disabled_gate(self):
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=False), queue=queue)

        asyncio.run(middleware.aafter_agent(_state(), _runtime()))

        assert queue.requests == []


class TestNeverBreaksARun:
    """Skill learning is purely additive: no failure may reach the run."""

    def test_a_queue_failure_does_not_propagate(self):
        class ExplodingQueue:
            def submit(self, *args, **kwargs):
                raise RuntimeError("queue exploded")

        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=ExplodingQueue())

        assert middleware.after_agent(_state(), _runtime()) is None

    def test_an_async_queue_failure_does_not_propagate(self):
        class ExplodingQueue:
            def submit(self, *args, **kwargs):
                raise RuntimeError("queue exploded")

        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=ExplodingQueue())

        assert asyncio.run(middleware.aafter_agent(_state(), _runtime())) is None

    def test_a_trajectory_extraction_failure_is_swallowed(self, monkeypatch):
        from deerflow.agents.middlewares import auto_skill_middleware as module

        def _explode(*args, **kwargs):
            raise RuntimeError("corrupt checkpoint")

        monkeypatch.setattr(module, "extract_run_trajectory", _explode)
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=queue)

        assert middleware.after_agent(_state(), _runtime()) is None
        assert queue.requests == []

    def test_an_identity_resolution_failure_is_swallowed(self, monkeypatch):
        from deerflow.agents.middlewares import auto_skill_middleware as module

        def _explode(*args, **kwargs):
            raise RuntimeError("no request context")

        monkeypatch.setattr(module, "resolve_runtime_user_id", _explode)
        queue = RecordingQueue()
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True), queue=queue)

        assert middleware.after_agent(_state(), _runtime()) is None
        assert queue.requests == []

    def test_uses_the_process_singleton_when_no_queue_is_injected(self, monkeypatch):
        from deerflow.agents.middlewares import auto_skill_middleware as module

        sentinel = RecordingQueue()
        monkeypatch.setattr(module, "get_auto_skill_queue", lambda: sentinel)
        middleware = AutoSkillMiddleware(config=AutoSkillConfig(enabled=True))

        middleware.after_agent(_state(), _runtime())

        assert len(sentinel.requests) == 1
