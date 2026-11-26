"""Auto-skill batches must not leak their event loop's HTTP connections.

The queue worker drains each batch through a short-lived ``asyncio.run`` loop
(``skills/auto/queue.py``). langchain-openai caches its default ``httpx.AsyncClient``
per process, keyed only on ``(base_url, timeout, socket_options)``
(``langchain_openai.chat_models._client_utils._cached_async_httpx_client``), so a model
call made on that temporary loop pools the loop's connections into a client the
Gateway loop reuses afterwards. Once ``asyncio.run`` closes the temporary loop those
connections are dead, and the next chat that draws one from the pool dies with
``RuntimeError: Event loop is closed`` — the failure that made unrelated conversations
look broken seconds after a successful skill synthesis.

The batch therefore owns its client (``new_isolated_http_client``), handed down as
``http_async_client`` so langchain-openai skips its cache entirely, and closes it
before the loop closes. These tests pin every link of that chain, plus the hazard
itself so a future refactor cannot silently re-enter the shared cache.
"""

import asyncio

import httpx
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_openai.chat_models import _client_utils

from deerflow.config.app_config import AppConfig
from deerflow.config.auto_skill_config import AutoSkillConfig
from deerflow.config.model_config import ModelConfig
from deerflow.models import factory as model_factory
from deerflow.models.factory import create_chat_model
from deerflow.skills.auto.queue import AutoSkillQueue, AutoSkillRequest
from deerflow.utils import oneshot_llm
from deerflow.utils.oneshot_llm import new_isolated_http_client, run_oneshot_llm

_SHARED_CACHE = _client_utils._cached_async_httpx_client


@pytest.fixture(autouse=True)
def _clean_shared_client_cache():
    """The cache under test is process-global; never let a case leak into another."""
    _SHARED_CACHE.cache_clear()
    yield
    _SHARED_CACHE.cache_clear()


@pytest.fixture
def app_config():
    """A minimal config whose only model is OpenAI-compatible over an unused port.

    Built directly rather than mutated from the example file: ``get_model_config``
    reads a name index derived at validation time, so assigning ``models`` afterwards
    would leave the index stale.
    """
    return AppConfig(
        models=[
            ModelConfig(
                name="iso-model",
                use="langchain_openai:ChatOpenAI",
                model="iso-model",
                base_url="http://127.0.0.1:9/compatible-mode/v1",
                api_key="test-key-not-used",
            )
        ],
        sandbox={"use": "deerflow.sandbox.local:LocalSandboxProvider"},
    )


class _NoHttpClientModel(BaseChatModel):
    """A chat model whose schema has no ``http_async_client`` field."""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError

    @property
    def _llm_type(self) -> str:
        return "no-http-client"


def _request() -> AutoSkillRequest:
    return AutoSkillRequest(trajectory=object(), user_id="user-1", thread_id="thread-1", run_id="run-1", trace_id=None)


class _FakeAppConfig:
    def __init__(self, auto_skill: AutoSkillConfig) -> None:
        self.auto_skill = auto_skill


# ── factory ──────────────────────────────────────────────────────────────────


def test_the_factory_hands_a_caller_owned_client_to_the_model(app_config):
    async def _case():
        client = new_isolated_http_client()
        try:
            model = create_chat_model(name="iso-model", app_config=app_config, http_async_client=client)
            assert model.http_async_client is client
        finally:
            await client.aclose()

    asyncio.run(_case())


def test_the_factory_drops_the_client_for_a_class_without_the_field(monkeypatch, app_config):
    monkeypatch.setattr(model_factory, "resolve_class", lambda *_args, **_kwargs: _NoHttpClientModel)

    async def _case():
        client = new_isolated_http_client()
        try:
            model = create_chat_model(name="iso-model", app_config=app_config, http_async_client=client)
            assert isinstance(model, _NoHttpClientModel)
            assert getattr(model, "http_async_client", None) is None
        finally:
            await client.aclose()

    asyncio.run(_case())


def test_an_isolated_client_never_enters_the_shared_cache(app_config):
    """The whole point: with ``http_async_client`` set, the lru_cache stays untouched."""

    async def _case():
        client = new_isolated_http_client()
        try:
            create_chat_model(name="iso-model", app_config=app_config, http_async_client=client)
        finally:
            await client.aclose()

    asyncio.run(_case())
    assert _SHARED_CACHE.cache_info().currsize == 0


def test_without_isolation_a_temporary_loop_leaves_a_live_client_behind(app_config):
    """Characterisation of the hazard the batch client exists to avoid.

    A model built on a temporary loop without ``http_async_client`` lands in the
    process-global cache; after ``asyncio.run`` closes that loop the cached client is
    still open and still reachable, and a later loop builds no new client at all —
    it receives the one whose connections belong to the dead loop.
    """
    holder: dict[str, object] = {}

    async def _temp_loop():
        holder["model"] = create_chat_model(name="iso-model", app_config=app_config)

    asyncio.run(_temp_loop())

    assert _SHARED_CACHE.cache_info().currsize == 1
    # langchain hands the cached client to the OpenAI SDK, so the ChatOpenAI field
    # stays None; the live object is reachable through the SDK client.
    cached = holder["model"].root_async_client._client
    assert cached is not None
    assert cached.is_closed is False  # live client, dead loop: the poisoning window

    async def _later_loop():
        holder["later"] = create_chat_model(name="iso-model", app_config=app_config)

    asyncio.run(_later_loop())
    assert holder["later"].root_async_client._client is cached  # cross-loop reuse, unchanged today


def test_the_gateway_loop_still_shares_one_client_across_builds(app_config):
    """Isolation is opt-in: ordinary callers keep connection reuse."""

    async def _case():
        first = create_chat_model(name="iso-model", app_config=app_config)
        second = create_chat_model(name="iso-model", app_config=app_config)
        assert first.root_async_client._client is second.root_async_client._client
        assert _SHARED_CACHE.cache_info().currsize == 1

    asyncio.run(_case())


# ── one-shot helper ──────────────────────────────────────────────────────────


def test_oneshot_llm_forwards_the_client_to_the_factory(monkeypatch):
    seen: dict[str, object] = {}

    class _StubModel:
        async def ainvoke(self, messages, config=None):
            return AIMessage(content="ok")

    def _recorder(**kwargs):
        seen.update(kwargs)
        return _StubModel()

    monkeypatch.setattr(oneshot_llm, "create_chat_model", _recorder)

    async def _case():
        client = new_isolated_http_client()
        try:
            assert await run_oneshot_llm(system_instruction="s", user_content="u", run_name="r", app_config=object(), http_async_client=client) == "ok"
        finally:
            await client.aclose()

    asyncio.run(_case())
    assert seen["http_async_client"] is not None
    assert isinstance(seen["http_async_client"], httpx.AsyncClient)


def test_oneshot_llm_without_a_client_passes_none_through(monkeypatch):
    seen: dict[str, object] = {}

    class _StubModel:
        async def ainvoke(self, messages, config=None):
            return AIMessage(content="ok")

    def _recorder(**kwargs):
        seen.update(kwargs)
        return _StubModel()

    monkeypatch.setattr(oneshot_llm, "create_chat_model", _recorder)

    async def _case():
        await run_oneshot_llm(system_instruction="s", user_content="u", run_name="r", app_config=object())

    asyncio.run(_case())
    assert seen.get("http_async_client") is None  # Gateway-loop callers keep the shared cache


# ── the batch ────────────────────────────────────────────────────────────────


def test_a_batch_passes_one_client_and_closes_it_before_the_loop_dies(app_config):
    """Queue → synthesizer → factory, with the shared cache untouched throughout."""
    observed: dict[str, object] = {}

    async def _recording_synthesizer(**kwargs):
        client = kwargs["http_async_client"]
        observed["client"] = client
        observed["open_during_batch"] = not client.is_closed
        # A real model build inside the batch: this is the call that used to poison
        # the process-global pool.
        observed["model"] = create_chat_model(name="iso-model", app_config=app_config, http_async_client=client)
        return object()

    queue = AutoSkillQueue(
        synthesizer=_recording_synthesizer,
        app_config_resolver=lambda: _FakeAppConfig(auto_skill=AutoSkillConfig(enabled=True)),
    )

    asyncio.run(queue._process_batch([_request()]))

    client = observed["client"]
    assert isinstance(client, httpx.AsyncClient)
    assert observed["open_during_batch"] is True
    assert observed["model"].http_async_client is client
    assert client.is_closed is True  # closed before asyncio.run closed the loop
    assert _SHARED_CACHE.cache_info().currsize == 0


def test_a_batch_closes_its_client_even_when_synthesis_raises(app_config):
    observed: dict[str, object] = {}

    async def _exploding_synthesizer(**kwargs):
        observed["client"] = kwargs["http_async_client"]
        raise RuntimeError("synthesis exploded")

    queue = AutoSkillQueue(
        synthesizer=_exploding_synthesizer,
        app_config_resolver=lambda: _FakeAppConfig(auto_skill=AutoSkillConfig(enabled=True)),
    )

    asyncio.run(queue._process_batch([_request()]))

    assert observed["client"].is_closed is True


def test_a_disabled_batch_creates_no_client(monkeypatch):
    created: list[object] = []
    real = oneshot_llm.new_isolated_http_client

    def _spy():
        client = real()
        created.append(client)
        return client

    monkeypatch.setattr("deerflow.skills.auto.queue.new_isolated_http_client", _spy)
    queue = AutoSkillQueue(
        synthesizer=None,
        app_config_resolver=lambda: _FakeAppConfig(auto_skill=AutoSkillConfig(enabled=False)),
    )

    asyncio.run(queue._process_batch([_request()]))

    assert created == []
