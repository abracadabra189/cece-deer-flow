"""Auto-skill update verification: an update needs a substantive, evidenced reason."""

import pytest

from deerflow.skills.auto.decision import (
    NON_SUBSTANTIVE_UPDATE_REASONS,
    SUBSTANTIVE_UPDATE_REASONS,
    find_novel_tools,
    normalize_reasons,
    verify_update,
)


class TestNormalizeReasons:
    def test_accepts_a_list(self):
        assert normalize_reasons(["new_tool", "answer_format"]) == ("new_tool", "answer_format")

    def test_accepts_one_separated_string(self):
        assert normalize_reasons("new_tool, answer_format、fallback") == ("new_tool", "answer_format", "fallback")

    def test_lowercases_and_underscores(self):
        assert normalize_reasons(["New Tool", "ANSWER_FORMAT"]) == ("new_tool", "answer_format")

    def test_deduplicates_keeping_first_order(self):
        assert normalize_reasons(["new_flow", "NEW_FLOW", "new_flow"]) == ("new_flow",)

    def test_drops_non_string_items(self):
        assert normalize_reasons(["new_flow", None, 3, {"a": 1}]) == ("new_flow",)

    @pytest.mark.parametrize("raw", [None, 42, object()])
    def test_non_string_input_yields_nothing(self, raw):
        assert normalize_reasons(raw) == ()

    def test_keeps_unknown_tokens_so_the_caller_can_report_them(self):
        assert normalize_reasons(["brand_new_reason"]) == ("brand_new_reason",)


class TestFindNovelTools:
    def test_reports_tools_absent_from_the_skill_text(self):
        contents = ["## 取数逻辑\n1. 调用 `search_enterprise_by_name` 解析主体"]
        assert find_novel_tools(["search_enterprise_by_name", "get_enterprise_shareholders"], contents) == ("get_enterprise_shareholders",)

    def test_no_novel_tools_when_the_skill_mentions_them_all(self):
        contents = ["调用 `a` 与 `b`"]
        assert find_novel_tools(["a", "b"], contents) == ()

    def test_every_tool_is_novel_without_a_matched_skill(self):
        assert find_novel_tools(["a", "b"], []) == ("a", "b")

    def test_deduplicates_and_preserves_call_order(self):
        assert find_novel_tools(["b", "a", "b"], [""]) == ("b", "a")

    def test_ignores_blank_and_non_string_names(self):
        assert find_novel_tools(["a", "", None, 7], [""]) == ("a",)

    def test_skips_empty_contents(self):
        assert find_novel_tools(["a"], ["", None, "a"]) == ()


class TestVerifyUpdate:
    @pytest.mark.parametrize("reason", SUBSTANTIVE_UPDATE_REASONS)
    def test_every_substantive_reason_keeps_the_update(self, reason):
        verified = verify_update([reason], novel_tools=("new_tool_name",))
        assert verified.is_update
        assert verified.reasons == (reason,)

    def test_new_tool_without_evidence_is_dropped(self):
        """The platform checks the tool diff itself; the model cannot invent one."""
        verified = verify_update(["new_tool"], novel_tools=())
        assert verified.decision == "no_change"
        assert verified.dropped == ("new_tool",)
        assert "lacked evidence" in verified.note

    def test_new_tool_with_evidence_survives(self):
        verified = verify_update(["new_tool"], novel_tools=("get_enterprise_shareholders",))
        assert verified.is_update
        assert verified.reasons == ("new_tool",)

    @pytest.mark.parametrize("reason", NON_SUBSTANTIVE_UPDATE_REASONS)
    def test_a_data_only_reason_degrades_to_no_change(self, reason):
        """Requirement: only the example/values/wording differ → do not rewrite."""
        verified = verify_update([reason])
        assert verified.decision == "no_change"
        assert "only this run's data changed" in verified.note

    def test_a_substantive_reason_wins_over_a_data_only_one(self):
        verified = verify_update(["examples_only", "new_dimension"])
        assert verified.is_update
        assert verified.reasons == ("new_dimension",)
        assert verified.dropped == ("examples_only",)

    def test_unknown_reasons_are_dropped_not_trusted(self):
        verified = verify_update(["totally_made_up"])
        assert verified.decision == "no_change"
        assert verified.dropped == ("totally_made_up",)

    def test_no_reasons_is_no_change_when_strict(self):
        verified = verify_update([])
        assert verified.decision == "no_change"
        assert "without any reason" in verified.note

    def test_no_reasons_survives_for_a_reconciled_create(self):
        """A declared create carries no reason vocabulary, so absence is not a failed check."""
        verified = verify_update([], strict=False)
        assert verified.is_update
        assert verified.reasons == ()

    def test_declared_reasons_are_verified_even_for_a_reconciled_create(self):
        verified = verify_update(["data_values"], strict=False)
        assert verified.decision == "no_change"

    def test_reason_order_is_preserved(self):
        verified = verify_update(["answer_format", "correction"], novel_tools=("x",))
        assert verified.reasons == ("answer_format", "correction")
