"""Registration and the host's actual source-evidence contract."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deerflow.knowledge import format_result, sources_from_messages
from deerflow.knowledge.providers import validate_provider

from deerflow_extension_cecemate_manual import install
from deerflow_extension_cecemate_manual.corpus import Corpus
from deerflow_extension_cecemate_manual.provider import CecemateManualProvider


class Registry:
    def __init__(self, supported=True):
        self.supported = supported
        self.providers = []

    def knowledge_provider(self, name, provider):
        self.providers.append((name, provider))
        return self.supported


def test_install_loads_once_and_search_never_reads(monkeypatch):
    original = Corpus.load
    calls = []

    def load():
        calls.append(True)
        return original()

    monkeypatch.setattr(Corpus, "load", load)
    registry = Registry()
    install(registry, {})
    assert calls == [True]
    name, provider = registry.providers[0]
    assert name == "cecemate-manual"
    assert provider.capabilities.operations == {"search", "sources"}
    validate_provider(provider)

    def no_io(*args, **kwargs):
        raise AssertionError("request-time file IO")

    monkeypatch.setattr(Path, "open", no_io)
    monkeypatch.setattr(Corpus, "load", no_io)
    for _ in range(2):
        result = asyncio.run(provider.search("产业链上下游企业分布区域评分"))
        assert result.hits
        for hit in result.hits:
            assert hit.content == hit.source.excerpt
            assert corpus_version(provider) in hit.source.title
            assert hit.source.url is None and hit.source.page is None
        text, artifact = format_result(result)
        sources = sources_from_messages([dict(type="tool", content=text, artifact=artifact)])
        assert len(sources) == len(result.hits)
        assert [source.excerpt for source in sources] == [hit.content for hit in result.hits]


def corpus_version(provider):
    return provider.corpus.manifest.version


def test_unsupported_registration():
    with pytest.raises(RuntimeError, match="knowledge provider"):
        install(Registry(False), {})


def test_invalid_config_precedes_load(monkeypatch):
    def no_load():
        raise AssertionError("invalid settings must fail before IO")

    monkeypatch.setattr(Corpus, "load", no_load)
    with pytest.raises(ValueError):
        install(Registry(), {"max_hits": 20})


def test_empty_unknown_and_oversized_query():
    provider = CecemateManualProvider(Corpus.load())
    assert asyncio.run(provider.search("  ")).hits == []
    assert asyncio.run(provider.search("火星种植香蕉xyz987")).hits == []
    with pytest.raises(ValueError, match="query"):
        asyncio.run(provider.search("x" * 10000))


def test_generic_host_tool_returns_replayable_evidence_and_honors_disabled_scope():
    from deerflow.config.app_config import AppConfig
    from deerflow.extensions import EXTENSION_SNAPSHOT_CONTEXT_KEY
    from deerflow.extensions.loader import ExtensionSpec, load_extensions
    from deerflow.knowledge.tools import execute_knowledge_search

    config = AppConfig.model_validate(
        {
            "models": [],
            "sandbox": {"use": "example.remote:Sandbox"},
            "knowledge_base": {"enabled": True, "scope_selection_enabled": False},
            "tools": [{"name": "knowledge_search", "group": "knowledge", "use": "deerflow.knowledge.tools:knowledge_search_tool", "provider": "cecemate-manual"}],
        }
    )
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_cecemate_manual:install", required=True)])
    assert diagnostics == []
    runtime = SimpleNamespace(context={"app_config": config, "user_id": "offline-reader", EXTENSION_SNAPSHOT_CONTEXT_KEY: loaded})

    async def verify():
        text, artifact = await execute_knowledge_search("产业评分有哪些维度？", runtime)
        assert artifact
        sources = sources_from_messages([{"type": "tool", "content": text, "artifact": artifact}])
        assert sources
        for term in ("产业规模", "优质企业", "创新能力", "融资能力", "成长能力"):
            assert term in text
        runtime.context["__knowledge_scope_execution"] = {"version": 1, "mode": "disabled"}
        text, artifact = await execute_knowledge_search("产业评分", runtime)
        assert artifact is None and "disabled" in text

    asyncio.run(verify())


@pytest.mark.parametrize(
    "query",
    [
        "平台是做什么服务形式",
        "产业链上下游企业分布区域评分",
        "区域龙头扩张科技企业",
        "挖掘潜客商机",
        "企业股东穿透风险资质知识产权哪里查",
        "企业上下游招中标",
        "政策研报资讯检索",
        "产业评分有哪些维度？",
    ],
)
def test_actual_questions_replay_exact_evidence_with_host_default_budgets(query):
    provider = CecemateManualProvider(Corpus.load())
    result = asyncio.run(provider.search(query))
    text, artifact = format_result(result)
    replay = sources_from_messages([dict(type="tool", content=text, artifact=artifact)])
    assert result.hits
    assert [source.excerpt for source in replay] == [hit.content for hit in result.hits]
    for hit in result.hits:
        assert provider.corpus.manifest.version in hit.source.title
        assert any(hit.content in entry.content for entry in provider.corpus.entries)
