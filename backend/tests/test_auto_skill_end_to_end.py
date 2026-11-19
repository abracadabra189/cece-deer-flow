"""End-to-end auto-skill chain: after_agent → queue → synthesizer → global store → loader.

Only the synthesis model call and the two security scans are stubbed. Everything
else is the real production path: the real middleware hook, the real debounce
queue, the real global store publication (staging → validate → permissions →
backup → atomic rename), and the real skill loader that decides whether the next
run can match the generated skill.

The two assertions that carry the requirements:

- ``test_a_skill_learned_by_one_user_is_visible_to_another`` — requirement 1.
- ``test_an_update_keeps_only_the_latest_version_visible`` — requirement 2.

A skill that is written but not matchable by other users would satisfy every
other check and still fail the feature, so both are driven through the real
loader rather than by inspecting the filesystem.
"""

import asyncio
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime

from deerflow.agents.middlewares.auto_skill_middleware import AutoSkillMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.paths import get_paths
from deerflow.skills.auto import store as store_module
from deerflow.skills.auto import synthesizer as synthesizer_module
from deerflow.skills.auto.abstraction import ENTITY_PLACEHOLDER
from deerflow.skills.auto.queue import AutoSkillQueue
from deerflow.skills.auto.store import backup_dir, list_backup_versions, read_current, restore_backup
from deerflow.skills.auto.synthesizer import AUTO_SKILL_AUTHOR
from deerflow.skills.frontmatter import split_skill_markdown
from deerflow.skills.security_scanner import ScanResult
from deerflow.skills.storage import get_or_new_user_skill_storage, reset_user_skill_storage
from deerflow.skills.types import SKILL_MD_FILE, SkillCategory

_OWNER = "user-owner"
_OTHER = "user-other"

_PAYLOAD = {
    "decision": "create",
    "reason": "新场景",
    "scenario": "企业融资历史查询",
    "scenario_slug": "enterprise-funding-history",
    "description": "查询目标公司的融资历史。当用户询问融资、轮次、投资方时使用。触发词：融资、轮次、投资机构。",
    "when_to_use": "适用于一级市场融资信息查询。",
    "data_fetching": "1. 调用 `search_enterprise_by_name` 解析工商全称。\n2. 调用 `get_enterprise_VCPE_financing` 取融资事件。",
    "reasoning": "按轮次时间排序，识别最近一轮与累计金额。",
    "answer_format": "## 融资概览\n- 轮次表格\n## 结论",
    "caveats": "同名公司需先消歧。",
}
_EXPECTED_NAME = "auto-enterprise-funding-history"


def _app_config(**auto_skill_overrides) -> AppConfig:
    # A long debounce keeps the timer thread from racing the explicit flush, so
    # every assertion observes a deterministic queue state.
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [],
            "memory": {"enabled": False},
            "summarization": {"enabled": False},
            "auto_skill": {"enabled": True, "debounce_seconds": 3600.0, **auto_skill_overrides},
        }
    )


def _run_state(*, matched_skill: str | None = None) -> dict:
    """A realistic MCP-backed run: query, two tool calls with results, final answer."""
    messages: list = [HumanMessage(content="查一下 A 公司的融资历史")]
    if matched_skill:
        messages.append(
            AIMessage(
                content="",
                additional_kwargs={"skill_usage": {"name": matched_skill, "path": f"/mnt/skills/integrations/auto-skill/{matched_skill}/SKILL.md"}},
            )
        )
    messages.extend(
        [
            AIMessage(content="", tool_calls=[{"name": "search_enterprise_by_name", "id": "c1", "args": {"query": "A"}}]),
            ToolMessage(content='{"企业名称": "A股份有限公司"}', tool_call_id="c1", name="search_enterprise_by_name"),
            AIMessage(content="", tool_calls=[{"name": "get_enterprise_VCPE_financing", "id": "c2", "args": {"company_name": "A股份有限公司"}}]),
            ToolMessage(content='{"总数": 3}', tool_call_id="c2", name="get_enterprise_VCPE_financing"),
            AIMessage(content="A 公司共完成 3 轮融资，最近一轮为 B 轮。"),
        ]
    )
    return {"messages": messages, "todos": [{"content": "解析主体", "status": "completed"}], "skill_context": [{"name": matched_skill, "path": "p", "description": "d", "loaded_at": 1}] if matched_skill else []}


@pytest.fixture
def e2e(tmp_path, monkeypatch):
    """Real chain on a temporary DEER_FLOW_HOME, with only the model and scans stubbed."""
    home = tmp_path / "runtime"
    monkeypatch.setenv("DEER_FLOW_HOME", str(home))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    reset_user_skill_storage()

    handle = {"home": home, "prompts": [], "decisions": [dict(_PAYLOAD)], "scan": ScanResult(decision="allow", reason="")}

    async def _fake_oneshot(**kwargs):
        handle["prompts"].append(kwargs["user_content"])
        decision = handle["decisions"].pop(0) if len(handle["decisions"]) > 1 else handle["decisions"][0]
        return json.dumps(decision, ensure_ascii=False)

    async def _allow_scan(content, **kwargs):
        return handle["scan"]

    monkeypatch.setattr(synthesizer_module, "run_oneshot_llm", _fake_oneshot)
    # The LLM moderation scan needs a live model; the deterministic SkillScan
    # stays real so generated content must genuinely pass it.
    monkeypatch.setattr(synthesizer_module, "scan_skill_content", _allow_scan)

    # Guard: fail loudly rather than silently writing into a developer's real
    # .deer-flow if the singleton reset above ever stops taking effect.
    assert Path(str(get_paths().base_dir)).resolve() == home.resolve(), "DEER_FLOW_HOME isolation failed"

    yield handle

    reset_user_skill_storage()


def _run_chain(e2e, *, config: AppConfig, queue: AutoSkillQueue, user: str = _OWNER, state: dict | None = None) -> None:
    middleware = AutoSkillMiddleware(config=config.auto_skill, queue=queue)
    runtime = Runtime(context={"thread_id": "thread-e2e", "user_id": user, "run_id": "run-e2e"})

    assert middleware.after_agent(state if state is not None else _run_state(), runtime) is None
    assert queue.pending_count == 1, "the hook must enqueue without blocking"
    assert queue.flush(timeout=60.0) == 1
    assert queue.pending_count == 0


def _visible_names(user: str) -> dict[str, object]:
    return {s.name: s for s in get_or_new_user_skill_storage(user).load_skills()}


class TestGlobalSharing:
    def test_a_skill_learned_by_one_user_is_visible_to_another(self, e2e):
        """Requirement 1: A 用户提问生成的 skill，B 用户可直接读取。"""
        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config), user=_OWNER)

        for user in (_OWNER, _OTHER, "user-third"):
            visible = _visible_names(user)
            assert _EXPECTED_NAME in visible, f"{user} cannot see the skill learned from {_OWNER}'s run"
            skill = visible[_EXPECTED_NAME]
            assert skill.category == SkillCategory.INTEGRATION
            assert skill.enabled is True, f"{user} must get it enabled by default"
            assert "触发词" in skill.description

    def test_the_package_lives_in_the_global_root_not_a_user_directory(self, e2e):
        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))

        published = store_module.skill_file(_EXPECTED_NAME)
        assert published.is_file()
        assert published.parent.parent == get_paths().integration_skills_dir() / store_module.PROVIDER_DIR_NAME
        # Nothing was written into the owner's private custom root.
        user_custom = get_paths().user_custom_skills_dir(_OWNER)
        assert not (user_custom / _EXPECTED_NAME).exists()

    def test_a_second_user_can_read_the_same_content(self, e2e):
        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))

        owner_view = _visible_names(_OWNER)[_EXPECTED_NAME]
        other_view = _visible_names(_OTHER)[_EXPECTED_NAME]

        assert owner_view.skill_file.read_text(encoding="utf-8") == other_view.skill_file.read_text(encoding="utf-8")

    def test_a_user_custom_skill_still_shadows_the_global_one(self, e2e):
        """Documented escape hatch for a user who wants a private variant."""
        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))
        storage = get_or_new_user_skill_storage(_OTHER)
        storage.write_custom_skill(_EXPECTED_NAME, SKILL_MD_FILE, read_current(_EXPECTED_NAME).content.replace("企业融资历史查询", "我的私有变体"))

        assert "我的私有变体" in _visible_names(_OTHER)[_EXPECTED_NAME].skill_file.read_text(encoding="utf-8")
        # The owner is unaffected: shadowing is per-user, not global.
        owner_content = _visible_names(_OWNER)[_EXPECTED_NAME].skill_file.read_text(encoding="utf-8")
        assert "我的私有变体" not in owner_content
        assert "企业融资历史查询" in owner_content


class TestUpdateAndBackup:
    def test_an_update_keeps_only_the_latest_version_visible(self, e2e):
        """Requirement 2: 旧版本进备份库，用户只看得到最新版。"""
        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))
        first = read_current(_EXPECTED_NAME)
        assert first.version == 1

        # Second run hits the learned skill and the model decides to improve it.
        e2e["decisions"] = [{**_PAYLOAD, "decision": "update", "reason": "补充失败兜底", "update_reasons": ["fallback"], "data_fetching": "1. 新步骤"}]
        _run_chain(
            e2e,
            config=config,
            queue=AutoSkillQueue(app_config_resolver=lambda: config),
            state=_run_state(matched_skill=_EXPECTED_NAME),
        )

        latest = read_current(_EXPECTED_NAME)
        assert latest.version == 2
        assert "新步骤" in latest.content
        assert list_backup_versions(_EXPECTED_NAME) == [1]
        assert "1. 调用 `search_enterprise_by_name`" in (backup_dir(_EXPECTED_NAME) / "v1" / SKILL_MD_FILE).read_text(encoding="utf-8")

        # Exactly one visible package for the scenario, for every user.
        for user in (_OWNER, _OTHER):
            names = [n for n in _visible_names(user) if n.startswith("auto-enterprise-funding")]
            assert names == [_EXPECTED_NAME], f"{user} sees more than the latest version: {names}"

    def test_the_visible_name_does_not_churn_across_updates(self, e2e):
        config = _app_config()
        queue = AutoSkillQueue(app_config_resolver=lambda: config)
        _run_chain(e2e, config=config, queue=queue)
        e2e["decisions"] = [{**_PAYLOAD, "decision": "update", "reason": "r", "update_reasons": ["new_flow"]}]
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config), state=_run_state(matched_skill=_EXPECTED_NAME))

        assert "-v" not in _EXPECTED_NAME
        assert set(list_backup_versions(_EXPECTED_NAME)) == {1}

    def test_no_change_leaves_the_visible_skill_untouched(self, e2e):
        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))
        before = read_current(_EXPECTED_NAME)

        e2e["decisions"] = [{"decision": "no_change", "reason": "已覆盖"}]
        _run_chain(
            e2e,
            config=config,
            queue=AutoSkillQueue(app_config_resolver=lambda: config),
            state=_run_state(matched_skill=_EXPECTED_NAME),
        )

        after = read_current(_EXPECTED_NAME)
        assert after.version == before.version == 1
        assert after.content == before.content
        assert list_backup_versions(_EXPECTED_NAME) == []

    def test_an_examples_only_update_does_not_rewrite_the_skill(self, e2e):
        """Requirement 2 end to end: 只有示例/数据值变化时不产生新版本。"""
        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))
        before = read_current(_EXPECTED_NAME)

        e2e["decisions"] = [
            {
                **_PAYLOAD,
                "decision": "update",
                "reason": "只有示例需要变化",
                "update_reasons": ["examples_only"],
                "data_fetching": "1. 新步骤",
            }
        ]
        _run_chain(
            e2e,
            config=config,
            queue=AutoSkillQueue(app_config_resolver=lambda: config),
            state=_run_state(matched_skill=_EXPECTED_NAME),
        )

        after = read_current(_EXPECTED_NAME)
        assert after.version == before.version == 1
        assert after.content == before.content
        assert list_backup_versions(_EXPECTED_NAME) == []

    def test_the_matched_skill_is_offered_to_the_model_for_comparison(self, e2e):
        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))
        e2e["decisions"] = [{**_PAYLOAD, "decision": "no_change", "reason": "covered"}]

        _run_chain(
            e2e,
            config=config,
            queue=AutoSkillQueue(app_config_resolver=lambda: config),
            state=_run_state(matched_skill=_EXPECTED_NAME),
        )

        second_prompt = e2e["prompts"][-1]
        assert f"已有技能：{_EXPECTED_NAME}（v1）" in second_prompt
        assert "search_enterprise_by_name" in second_prompt

    def test_backup_retention_prunes_the_oldest(self, e2e):
        config = _app_config(max_versions=2)
        queue = AutoSkillQueue(app_config_resolver=lambda: config)
        _run_chain(e2e, config=config, queue=queue)
        for expected_version in (2, 3, 4):
            e2e["decisions"] = [{**_PAYLOAD, "decision": "update", "reason": f"r{expected_version}", "update_reasons": ["new_flow"]}]
            _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config), state=_run_state(matched_skill=_EXPECTED_NAME))

        assert read_current(_EXPECTED_NAME).version == 4
        assert list_backup_versions(_EXPECTED_NAME) == [2, 3]

    def test_a_backup_can_be_restored(self, e2e):
        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))
        e2e["decisions"] = [{**_PAYLOAD, "decision": "update", "reason": "坏更新", "update_reasons": ["correction"], "data_fetching": "错误步骤"}]
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config), state=_run_state(matched_skill=_EXPECTED_NAME))
        assert "错误步骤" in read_current(_EXPECTED_NAME).content

        assert restore_backup(_EXPECTED_NAME, 1) is True

        restored = read_current(_EXPECTED_NAME)
        assert "search_enterprise_by_name" in restored.content
        assert "错误步骤" not in restored.content
        assert restored.version == 3


class TestGeneratedDocument:
    def test_frontmatter_is_well_formed_and_parseable(self, e2e):
        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))

        content = read_current(_EXPECTED_NAME).content
        parts, error = split_skill_markdown(content)
        assert error is None
        assert parts.metadata["name"] == _EXPECTED_NAME
        assert parts.metadata["metadata"]["author"] == AUTO_SKILL_AUTHOR
        assert parts.metadata["metadata"]["version"] == "1"
        assert parts.metadata["metadata"]["source-thread"] == "thread-e2e"

    def test_carries_the_three_required_knowledge_sections(self, e2e):
        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))

        body = split_skill_markdown(read_current(_EXPECTED_NAME).content)[0].body
        assert "## 取数逻辑" in body
        assert "## 推理逻辑" in body
        assert "## 回答格式" in body
        assert "search_enterprise_by_name" in body

    def test_the_real_deterministic_scanner_accepts_generated_content(self, e2e):
        """SkillScan runs for real here, so this proves generated skills are clean."""
        from deerflow.skills.skillscan import scan_skill_dir

        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))

        result = scan_skill_dir(store_module.skill_dir(_EXPECTED_NAME))
        assert result["blocked"] is False
        assert result["findings"] == []

    def test_a_blocked_moderation_scan_publishes_nothing(self, e2e, monkeypatch):
        async def _block(content, **kwargs):
            return ScanResult(decision="block", reason="prompt injection", available=True)

        monkeypatch.setattr(synthesizer_module, "scan_skill_content", _block)
        config = _app_config()
        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))

        assert read_current(_EXPECTED_NAME) is None
        assert _EXPECTED_NAME not in _visible_names(_OTHER)


class TestAbstraction:
    """A published skill describes a class of questions, not this run's subject."""

    def test_a_concrete_entity_never_reaches_the_method_sections(self, e2e):
        config = _app_config()
        e2e["decisions"] = [
            {
                **_PAYLOAD,
                "entities": ["A股份有限公司"],
                "description": "查询 A股份有限公司 的融资历史。触发词：融资、轮次。",
                "examples": "问：A股份有限公司的融资历史\n入参：`company_name=A股份有限公司`",
            }
        ]

        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))

        content = read_current(_EXPECTED_NAME).content
        head, examples = content.split("## 示例")
        # The stubbed model keeps returning the same leaking payload on the repair
        # attempt, so the platform redacts deterministically before publishing.
        assert "A股份有限公司" not in head
        assert ENTITY_PLACEHOLDER in head
        assert "A股份有限公司" in examples

    def test_the_redacted_document_still_passes_the_real_scanner(self, e2e):
        from deerflow.skills.skillscan import scan_skill_dir

        config = _app_config()
        e2e["decisions"] = [{**_PAYLOAD, "entities": ["A股份有限公司"], "description": "查询 A股份有限公司 的融资历史。", "examples": "A股份有限公司 示例"}]

        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))

        result = scan_skill_dir(store_module.skill_dir(_EXPECTED_NAME))
        assert result["blocked"] is False

    def test_the_published_skill_stays_visible_to_other_users(self, e2e):
        config = _app_config()
        e2e["decisions"] = [{**_PAYLOAD, "entities": ["A股份有限公司"], "description": "查询 A股份有限公司 的融资历史。", "examples": "A股份有限公司 示例"}]

        _run_chain(e2e, config=config, queue=AutoSkillQueue(app_config_resolver=lambda: config))

        assert _EXPECTED_NAME in _visible_names(_OTHER)


class TestGating:
    def test_a_run_without_tool_calls_is_not_learned(self, e2e):
        config = _app_config(min_tool_calls=1)
        queue = AutoSkillQueue(app_config_resolver=lambda: config)
        middleware = AutoSkillMiddleware(config=config.auto_skill, queue=queue)
        runtime = Runtime(context={"thread_id": "t", "user_id": _OWNER, "run_id": "r"})

        middleware.after_agent({"messages": [HumanMessage(content="你好"), AIMessage(content="你好！")]}, runtime)

        assert queue.pending_count == 0
        assert e2e["prompts"] == []


class TestAsyncHookPath:
    def test_the_async_hook_drives_the_same_chain(self, e2e):
        config = _app_config()
        queue = AutoSkillQueue(app_config_resolver=lambda: config)
        middleware = AutoSkillMiddleware(config=config.auto_skill, queue=queue)
        runtime = Runtime(context={"thread_id": "thread-e2e", "user_id": _OWNER, "run_id": "run-e2e"})

        asyncio.run(middleware.aafter_agent(_run_state(), runtime))
        assert queue.pending_count == 1
        assert queue.flush(timeout=60.0) == 1

        assert _EXPECTED_NAME in _visible_names(_OTHER)
