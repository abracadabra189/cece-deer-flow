"""Auto-skill synthesis: decision routing, SKILL.md rendering, scan gates, global publish."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from deerflow.config.auto_skill_config import AutoSkillConfig
from deerflow.skills.auto import store as store_module
from deerflow.skills.auto import synthesizer as synthesizer_module
from deerflow.skills.auto.store import StoredSkill, WriteResult
from deerflow.skills.auto.synthesizer import (
    AUTO_SKILL_AUTHOR,
    SynthesizedSkill,
    _extract_json_object,
    render_skill_markdown,
    resolve_matched_auto_skills,
    synthesize_skill,
)
from deerflow.skills.auto.trajectory import RunTrajectory, ToolStep
from deerflow.skills.frontmatter import split_skill_markdown
from deerflow.skills.security_static_scanner import StaticScanBlockedError
from deerflow.skills.types import SKILL_MD_FILE

_SKILL_NAME = "auto-pevc-funding-lookup"


@dataclass
class ScanDecision:
    decision: str = "allow"
    reason: str = ""


class FakeStore:
    """Records store interactions; patches only the functions the synthesizer calls."""

    def __init__(self, *, existing: dict[str, StoredSkill] | None = None) -> None:
        self.existing: dict[str, StoredSkill] = dict(existing or {})
        self.writes: list[tuple[str, int]] = []
        self.sweeps: list[tuple[str, str, str]] = []
        self.sweep_result: list[str] = []
        self.write_raises: Exception | None = None
        self.sweep_raises: Exception | None = None

    # -- patched onto the real store module --
    def read_current(self, name: str) -> StoredSkill | None:
        return self.existing.get(name)

    def current_version(self, name: str) -> int:
        stored = self.existing.get(name)
        return stored.version if stored is not None else 0

    def write_skill(self, name: str, *, render, prune_keep=None) -> WriteResult:
        if self.write_raises is not None:
            raise self.write_raises
        version = self.current_version(name) + 1
        content = render(version)
        backed_up = version - 1 if version > 1 else None
        self.writes.append((name, version))
        self.existing[name] = StoredSkill(name=name, version=version, content=content, path=Path(name) / SKILL_MD_FILE)
        return WriteResult(skill=self.existing[name], backed_up_version=backed_up, pruned=())

    def sweep_legacy_user_skills(self, user_id: str, *, prefix: str, slug: str) -> list[str]:
        if self.sweep_raises is not None:
            raise self.sweep_raises
        self.sweeps.append((user_id, prefix, slug))
        return list(self.sweep_result)

    def list_current_summaries(self) -> list[tuple[str, int, str]]:
        summaries = []
        for name, stored in self.existing.items():
            parts, _error = split_skill_markdown(stored.content)
            description = ""
            if parts is not None:
                raw = parts.metadata.get("description")
                description = raw.strip() if isinstance(raw, str) else ""
            summaries.append((name, stored.version, description))
        return summaries


def _trajectory(*, skill_names: tuple[str, ...] = ()) -> RunTrajectory:
    return RunTrajectory(
        query="查一下 A 公司的融资历史",
        skill_names=skill_names,
        tool_steps=(
            ToolStep(tool_name="search_enterprise_by_name", args_summary='{"query": "A"}', result_summary='{"企业名称": "A股份有限公司"}', status="success"),
            ToolStep(tool_name="get_enterprise_VCPE_financing", args_summary='{"company_name": "A股份有限公司"}', result_summary='{"总数": 3}', status="success"),
        ),
        final_answer="A 公司共完成 3 轮融资，最近一轮为 B 轮。",
        todo_texts=("解析主体", "查询融资"),
    )


_GOOD_PAYLOAD = {
    "decision": "create",
    "reason": "没有已有技能覆盖该场景",
    "scenario": "PEVC 融资历史查询",
    "scenario_slug": "pevc-funding-lookup",
    "description": "查询目标公司的融资历史。当用户询问融资、轮次、投资方时使用。触发词：融资、轮次、投资机构。",
    "when_to_use": "适用于一级市场融资信息查询。",
    "data_fetching": "1. 调用 `search_enterprise_by_name` 解析工商全称。\n2. 调用 `get_enterprise_VCPE_financing` 取融资事件。",
    "reasoning": "按轮次时间排序，识别最近一轮与累计金额。",
    "answer_format": "## 融资概览\n- 轮次表格\n## 结论",
    "caveats": "同名公司需先消歧。",
}


def _existing_content(name: str = _SKILL_NAME, version: int = 1) -> str:
    return f'---\nname: {name}\ndescription: "旧版描述"\nmetadata:\n  author: "{AUTO_SKILL_AUTHOR}"\n  version: "{version}"\n---\n\n# {name}\n\n## 取数逻辑\n\n1. 旧版步骤\n'


@pytest.fixture
def patched(monkeypatch):
    """Wire the synthesizer to fakes; returns a handle for assertions."""

    class Handle:
        store = FakeStore()
        payload: Any = dict(_GOOD_PAYLOAD)
        raw_text: str | None = None
        scan_decision = ScanDecision()
        static_raises: Exception | None = None
        llm_raises: Exception | None = None
        refreshed_global: int = 0
        published: list[str | None] = []
        static_calls: list[str] = []
        moderation_calls: list[dict] = []
        prompts: list[str] = []

    handle = Handle()

    async def _fake_oneshot(**kwargs):
        handle.prompts.append(kwargs["user_content"])
        if handle.llm_raises is not None:
            raise handle.llm_raises
        if handle.raw_text is not None:
            return handle.raw_text
        return json.dumps(handle.payload, ensure_ascii=False)

    def _fake_static_scan(skill_dir, *, skill_name=None, **kwargs):
        handle.static_calls.append(skill_name)
        if handle.static_raises is not None:
            raise handle.static_raises
        return []

    async def _fake_moderation(content, **kwargs):
        handle.moderation_calls.append({"location": kwargs.get("location"), "executable": kwargs.get("executable")})
        return handle.scan_decision

    async def _fake_refresh_global():
        handle.refreshed_global += 1

    def _fake_publish(*, user_id=None):
        handle.published.append(user_id)
        return "gen-1"

    monkeypatch.setattr(synthesizer_module, "run_oneshot_llm", _fake_oneshot)
    monkeypatch.setattr(synthesizer_module, "enforce_static_scan", _fake_static_scan)
    monkeypatch.setattr(synthesizer_module, "scan_skill_content", _fake_moderation)
    monkeypatch.setattr(synthesizer_module, "refresh_skills_system_prompt_cache_async", _fake_refresh_global)
    monkeypatch.setattr(synthesizer_module, "publish_skills_cache_reset", _fake_publish)
    for fn in ("read_current", "current_version", "write_skill", "sweep_legacy_user_skills", "list_current_summaries"):
        monkeypatch.setattr(store_module, fn, getattr(handle.store, fn))
    return handle


def _synthesize(handle, *, config: AutoSkillConfig | None = None, trajectory: RunTrajectory | None = None) -> SynthesizedSkill | None:
    return asyncio.run(
        synthesize_skill(
            trajectory=trajectory or _trajectory(),
            user_id="user-1",
            thread_id="thread-1",
            run_id="run-1",
            config=config or AutoSkillConfig(enabled=True),
            app_config=object(),
        )
    )


class TestExtractJsonObject:
    def test_parses_a_bare_object(self):
        assert _extract_json_object('{"a": 1}') == {"a": 1}

    def test_strips_a_json_code_fence(self):
        assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}

    def test_finds_an_object_wrapped_in_prose(self):
        parsed = _extract_json_object('结果如下：\n{"scenario": "x", "nested": {"k": "v"}}\n以上。')
        assert parsed == {"scenario": "x", "nested": {"k": "v"}}

    def test_handles_braces_inside_string_values(self):
        assert _extract_json_object('{"answer_format": "使用 {占位符} 模板"}') == {"answer_format": "使用 {占位符} 模板"}

    @pytest.mark.parametrize("text", ["", "   ", "not json", '{"unterminated": ', None, 42, "[1,2,3]"])
    def test_returns_none_for_unparseable_input(self, text):
        assert _extract_json_object(text) is None


class TestRenderSkillMarkdown:
    def _render(self, **overrides) -> str:
        kwargs = {
            "name": _SKILL_NAME,
            "scenario": "PEVC 融资历史查询",
            "description": "查询融资历史。",
            "when_to_use": "适用场景说明",
            "data_fetching": "1. 调用工具",
            "reasoning": "排序并汇总",
            "answer_format": "## 概览",
            "caveats": "注意消歧",
            "version": 1,
            "thread_id": "thread-1",
            "run_id": "run-1",
        }
        kwargs.update(overrides)
        return render_skill_markdown(**kwargs)

    def test_frontmatter_parses_and_name_matches(self):
        parts, error = split_skill_markdown(self._render())
        assert error is None
        assert parts.metadata["name"] == _SKILL_NAME

    def test_passes_the_real_storage_validator(self):
        from deerflow.skills.storage.skill_storage import SkillStorage

        content = self._render()
        assert SkillStorage.validate_skill_name(_SKILL_NAME) == _SKILL_NAME
        SkillStorage.validate_skill_markdown_content(_SKILL_NAME, content)

    def test_marks_the_auto_skill_author_and_version(self):
        parts, _ = split_skill_markdown(self._render(version=3))
        assert parts.metadata["metadata"]["author"] == AUTO_SKILL_AUTHOR
        assert parts.metadata["metadata"]["version"] == "3"
        assert parts.metadata["metadata"]["source-thread"] == "thread-1"
        assert parts.metadata["metadata"]["source-run"] == "run-1"

    @pytest.mark.parametrize(
        "description",
        ['contains: a colon and "quotes"', "has # hash and 'singles'", "multiline\nvalue", "中文标点：，。", "backslash \\ and\ttab"],
    )
    def test_description_cannot_break_the_frontmatter(self, description):
        parts, error = split_skill_markdown(self._render(description=description))
        assert error is None
        # render strips surrounding whitespace; interior characters must survive verbatim.
        assert parts.metadata["description"] == description.strip()

    def test_renders_every_body_section(self):
        content = self._render()
        for heading in ("## 适用场景", "## 取数逻辑", "## 推理逻辑", "## 回答格式", "## 注意事项"):
            assert heading in content

    def test_omits_the_caveats_section_when_empty(self):
        assert "## 注意事项" not in self._render(caveats="")

    def test_a_model_supplied_frontmatter_delimiter_cannot_forge_metadata(self):
        content = self._render(data_fetching="---\nname: evil\n---\n真实步骤")
        parts, error = split_skill_markdown(content)
        assert error is None
        assert parts.metadata["name"] == _SKILL_NAME
        assert "name: evil" in parts.body


class TestSectionNormalization:
    def test_drops_a_leading_heading_the_template_already_provides(self):
        from deerflow.skills.auto.synthesizer import _section

        assert _section("## 适用场景\n- 第一条") == "- 第一条"
        assert _section("# 取数步骤\n\n1. 调用工具") == "1. 调用工具"

    def test_preserves_deeper_subheadings_inside_the_body(self):
        from deerflow.skills.auto.synthesizer import _section

        assert _section("## 取数步骤\n\n### 第一步\n调用 A") == "### 第一步\n调用 A"

    def test_a_heading_only_section_becomes_empty(self):
        from deerflow.skills.auto.synthesizer import _section

        assert _section("## 注意事项") == ""


class TestMatchedSkillResolution:
    def test_returns_only_skills_that_still_exist_in_the_global_store(self, patched):
        patched.store.existing[_SKILL_NAME] = StoredSkill(name=_SKILL_NAME, version=2, content=_existing_content(version=2), path=Path("p"))

        matched = resolve_matched_auto_skills(_trajectory(skill_names=(_SKILL_NAME, "auto-retired")))

        assert [s.name for s in matched] == [_SKILL_NAME]
        assert matched[0].version == 2

    def test_deduplicates_repeated_names(self, patched):
        patched.store.existing[_SKILL_NAME] = StoredSkill(name=_SKILL_NAME, version=1, content=_existing_content(), path=Path("p"))

        matched = resolve_matched_auto_skills(_trajectory(skill_names=(_SKILL_NAME, _SKILL_NAME)))

        assert len(matched) == 1

    def test_empty_when_nothing_matched(self, patched):
        assert resolve_matched_auto_skills(_trajectory()) == []


class TestScenarioIndex:
    """A run that never loaded its scenario's skill must still resolve to it.

    ``skill_context`` is often empty — the model frequently goes straight to the
    tools — so without the index the synthesizer would not know the scenario
    exists and would mint a near-duplicate under a different slug.
    """

    def test_existing_scenarios_are_listed_with_their_descriptions(self, patched):
        patched.store.existing[_SKILL_NAME] = StoredSkill(name=_SKILL_NAME, version=2, content=_existing_content(version=2), path=Path("p"))

        _synthesize(patched)

        prompt = patched.prompts[0]
        assert "## 平台已有的自动技能清单" in prompt
        assert f"`{_SKILL_NAME}`（v2）" in prompt
        assert "旧版描述" in prompt
        assert "必须复用该技能名对应的 scenario_slug" in prompt

    def test_the_index_is_omitted_when_nothing_exists_yet(self, patched):
        _synthesize(patched)

        assert "## 平台已有的自动技能清单" not in patched.prompts[0]

    def test_index_descriptions_are_bounded(self, patched):
        long_content = _existing_content().replace('description: "旧版描述"', 'description: "' + "长" * 5000 + '"')
        patched.store.existing[_SKILL_NAME] = StoredSkill(name=_SKILL_NAME, version=1, content=long_content, path=Path("p"))

        _synthesize(patched)

        assert "…" in patched.prompts[0]
        assert "长" * 5000 not in patched.prompts[0]

    def test_a_create_decision_for_an_existing_name_is_recorded_as_an_update(self, patched):
        """The model may say create for a scenario that already exists; the audit trail must not lie."""
        patched.store.existing[_SKILL_NAME] = StoredSkill(name=_SKILL_NAME, version=1, content=_existing_content(), path=Path("p"))
        patched.payload = {**_GOOD_PAYLOAD, "decision": "create"}

        result = _synthesize(patched)

        assert result is not None
        assert result.decision == "update"
        assert result.version == 2
        assert result.backed_up_version == 1

    def test_a_create_decision_for_a_new_name_stays_a_create(self, patched):
        result = _synthesize(patched)

        assert result is not None
        assert result.decision == "create"
        assert result.backed_up_version is None


class TestJsonRecovery:
    def test_prose_then_valid_json_recovers_on_the_retry(self, patched):
        """A reasoning model occasionally answers in prose; one retry is cheap insurance."""
        attempts = {"n": 0}

        async def _flaky(**kwargs):
            attempts["n"] += 1
            patched.prompts.append(kwargs["user_content"])
            if attempts["n"] == 1:
                return "好的，我来分析一下这个场景。"
            return json.dumps(_GOOD_PAYLOAD, ensure_ascii=False)

        import deerflow.skills.auto.synthesizer as mod

        original = mod.run_oneshot_llm
        mod.run_oneshot_llm = _flaky
        try:
            result = _synthesize(patched)
        finally:
            mod.run_oneshot_llm = original

        assert attempts["n"] == 2
        assert result is not None
        assert result.decision == "create"
        assert len(patched.prompts) == 2

    def test_two_unparseable_responses_are_dropped(self, patched):
        patched.raw_text = "我无法完成这个任务。"

        result = _synthesize(patched)

        assert result is None
        assert patched.store.writes == []
        assert len(patched.prompts) == 2, "exactly one retry, no unbounded loop"

    def test_the_retry_carries_a_stricter_output_instruction(self, patched):
        instructions: list[str] = []

        async def _always_prose(**kwargs):
            instructions.append(kwargs["system_instruction"])
            patched.prompts.append(kwargs["user_content"])
            return "抱歉，我无法输出 JSON。"

        import deerflow.skills.auto.synthesizer as mod

        original = mod.run_oneshot_llm
        mod.run_oneshot_llm = _always_prose
        try:
            assert _synthesize(patched) is None
        finally:
            mod.run_oneshot_llm = original

        assert len(instructions) == 2
        assert instructions[0] == instructions[1].split("\n\n【重要】")[0]
        assert "【重要】" in instructions[1]
        assert "只输出一个合法 JSON 对象" in instructions[1]


class TestDecisionRouting:
    def test_create_publishes_version_one(self, patched):
        result = _synthesize(patched)

        assert result is not None
        assert result.decision == "create"
        assert result.name == _SKILL_NAME
        assert result.version == 1
        assert result.backed_up_version is None
        assert patched.store.writes == [(_SKILL_NAME, 1)]

    def test_update_publishes_the_next_version_and_backs_up(self, patched):
        """Requirement 2: a hit skill that needs improving is replaced, not duplicated."""
        patched.store.existing[_SKILL_NAME] = StoredSkill(name=_SKILL_NAME, version=1, content=_existing_content(), path=Path("p"))
        patched.payload = {**_GOOD_PAYLOAD, "decision": "update", "reason": "本次发现了新的失败兜底路径"}

        result = _synthesize(patched, trajectory=_trajectory(skill_names=(_SKILL_NAME,)))

        assert result is not None
        assert result.decision == "update"
        assert result.version == 2
        assert result.backed_up_version == 1
        assert patched.store.writes == [(_SKILL_NAME, 2)]
        # The visible name is stable, so only one package exists for the scenario.
        assert [n for n in patched.store.existing if n.startswith("auto-pevc")] == [_SKILL_NAME]

    def test_no_change_writes_nothing(self, patched):
        """A run that merely followed the existing skill must not churn versions."""
        patched.store.existing[_SKILL_NAME] = StoredSkill(name=_SKILL_NAME, version=3, content=_existing_content(version=3), path=Path("p"))
        patched.payload = {"decision": "no_change", "reason": "已有技能已完整覆盖本次路径"}

        result = _synthesize(patched, trajectory=_trajectory(skill_names=(_SKILL_NAME,)))

        assert result is None
        assert patched.store.writes == []
        assert patched.store.existing[_SKILL_NAME].version == 3
        # No publish, so no needless cache churn across workers.
        assert patched.refreshed_global == 0
        assert patched.published == []

    def test_no_change_skips_the_security_scans(self, patched):
        patched.payload = {"decision": "no_change", "reason": "covered"}

        _synthesize(patched)

        assert patched.static_calls == []
        assert patched.moderation_calls == []

    def test_an_unknown_decision_falls_back_to_create(self, patched):
        patched.payload = {**_GOOD_PAYLOAD, "decision": "maybe?"}

        result = _synthesize(patched)

        assert result is not None
        assert result.decision == "create"

    def test_a_missing_decision_defaults_to_create(self, patched):
        payload = {k: v for k, v in _GOOD_PAYLOAD.items() if k != "decision"}
        patched.payload = payload

        result = _synthesize(patched)

        assert result is not None
        assert result.decision == "create"

    def test_decision_is_case_insensitive(self, patched):
        patched.payload = {**_GOOD_PAYLOAD, "decision": "UPDATE"}
        patched.store.existing[_SKILL_NAME] = StoredSkill(name=_SKILL_NAME, version=1, content=_existing_content(), path=Path("p"))

        result = _synthesize(patched)

        assert result is not None
        assert result.decision == "update"


class TestExistingSkillIsFedToTheModel:
    def test_the_matched_skill_content_reaches_the_prompt(self, patched):
        patched.store.existing[_SKILL_NAME] = StoredSkill(name=_SKILL_NAME, version=2, content=_existing_content(version=2), path=Path("p"))

        _synthesize(patched, trajectory=_trajectory(skill_names=(_SKILL_NAME,)))

        assert len(patched.prompts) == 1
        assert "## 当前已有技能" in patched.prompts[0]
        assert f"已有技能：{_SKILL_NAME}（v2）" in patched.prompts[0]
        assert "旧版步骤" in patched.prompts[0]

    def test_an_unmatched_run_says_so_explicitly(self, patched):
        _synthesize(patched)

        assert "（无：本次运行未命中任何自动生成的技能）" in patched.prompts[0]

    def test_a_retired_skill_content_is_not_echoed(self, patched):
        """skill_context can name a package that no longer exists; stale content would mislead.

        The name still appears in the trajectory's matched-skill list — that is a
        factual record of the run — but nothing is offered to the model as the
        "current skill" to improve.
        """
        patched.store.existing["auto-live"] = StoredSkill(name="auto-live", version=1, content=_existing_content("auto-live"), path=Path("p"))

        _synthesize(patched, trajectory=_trajectory(skill_names=("auto-gone", "auto-live")))

        prompt = patched.prompts[0]
        assert "已有技能：auto-live" in prompt
        assert "已有技能：auto-gone" not in prompt

    def test_existing_skill_content_is_bounded(self, patched):
        patched.store.existing[_SKILL_NAME] = StoredSkill(name=_SKILL_NAME, version=1, content="旧" * 60000, path=Path("p"))

        _synthesize(patched, trajectory=_trajectory(skill_names=(_SKILL_NAME,)))

        assert "…[truncated]" in patched.prompts[0]
        assert "旧" * 60000 not in patched.prompts[0]


class TestGlobalPublication:
    def test_cache_invalidation_is_global_not_user_scoped(self, patched):
        """A shared package must retire every user's cache, not just the writer's."""
        _synthesize(patched)

        assert patched.refreshed_global == 1
        assert patched.published == [None]

    def test_writes_through_the_security_pipeline(self, patched):
        _synthesize(patched)

        assert patched.static_calls == [_SKILL_NAME]
        assert patched.moderation_calls == [{"location": f"auto-skill/{_SKILL_NAME}/{SKILL_MD_FILE}", "executable": False}]

    def test_legacy_sweep_runs_for_the_writing_user(self, patched):
        patched.store.sweep_result = ["auto-pevc-funding-lookup-v1"]

        result = _synthesize(patched)

        assert patched.store.sweeps == [("user-1", "auto", "pevc-funding-lookup")]
        assert result.swept == ("auto-pevc-funding-lookup-v1",)
        # Retiring legacy packages changes the visible set, so caches reset again.
        assert patched.refreshed_global == 2

    def test_a_legacy_sweep_failure_does_not_undo_the_publication(self, patched):
        patched.store.sweep_raises = OSError("delete failed")

        result = _synthesize(patched)

        assert result is not None
        assert result.swept == ()
        assert patched.store.writes == [(_SKILL_NAME, 1)]

    def test_retention_is_passed_through_to_the_store(self, patched, monkeypatch):
        recorded: dict = {}
        real_write = store_module.write_skill

        def _capture(name, *, render, prune_keep=None):
            recorded["prune_keep"] = prune_keep
            return real_write(name, render=render, prune_keep=prune_keep)

        monkeypatch.setattr(store_module, "write_skill", _capture)

        _synthesize(patched, config=AutoSkillConfig(enabled=True, max_versions=3))

        assert recorded["prune_keep"] == 3


class TestRejection:
    def test_a_block_decision_prevents_the_write(self, patched):
        patched.scan_decision = ScanDecision(decision="block", reason="malicious instruction")

        assert _synthesize(patched) is None
        assert patched.store.writes == []
        assert patched.refreshed_global == 0

    def test_a_critical_static_finding_prevents_the_write(self, patched):
        patched.static_raises = StaticScanBlockedError([], skill_name=_SKILL_NAME, message="critical")

        assert _synthesize(patched) is None
        assert patched.store.writes == []

    def test_unparseable_model_output_is_dropped(self, patched):
        patched.raw_text = "我不确定该怎么回答。"

        assert _synthesize(patched) is None
        assert patched.store.writes == []

    def test_a_missing_description_is_dropped(self, patched):
        """The description drives skill matching; without it the skill is useless."""
        patched.payload = {**_GOOD_PAYLOAD, "description": "   "}

        assert _synthesize(patched) is None
        assert patched.store.writes == []

    def test_a_model_failure_is_swallowed(self, patched):
        patched.llm_raises = RuntimeError("provider 503")

        assert _synthesize(patched) is None
        assert patched.store.writes == []

    def test_a_store_failure_is_swallowed(self, patched):
        patched.store.write_raises = OSError("disk full")

        assert _synthesize(patched) is None

    def test_a_cjk_only_slug_falls_back_to_the_query_hash(self, patched):
        """A Chinese scenario name must still yield a stable, valid package name."""
        patched.payload = {**_GOOD_PAYLOAD, "scenario_slug": "融资查询"}

        result = _synthesize(patched)

        assert result is not None
        assert result.name.startswith("auto-q")

    def test_a_cache_publish_failure_keeps_the_durable_write(self, patched, monkeypatch):
        from deerflow.agents.lead_agent.prompt import SkillCacheResetPublishError

        def _fail_publish(*, user_id=None):
            raise SkillCacheResetPublishError("marker unwritable")

        monkeypatch.setattr(synthesizer_module, "publish_skills_cache_reset", _fail_publish)

        result = _synthesize(patched)

        assert result is not None
        assert patched.store.writes == [(_SKILL_NAME, 1)]
