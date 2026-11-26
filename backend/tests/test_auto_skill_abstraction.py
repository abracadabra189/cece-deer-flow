"""Auto-skill abstraction: entities are normalized, detected and redacted deterministically."""

import pytest

from deerflow.skills.auto.abstraction import (
    ENTITY_PLACEHOLDER,
    MAX_ENTITIES,
    MAX_ENTITY_CHARS,
    collect_entities,
    find_leaked_entities,
    leaked_fields,
    redact_entities,
    redact_surfaces,
)


class TestCollectEntities:
    def test_accepts_a_list_of_strings(self):
        assert collect_entities(["宁德时代", "300750"]) == ("宁德时代", "300750")

    def test_accepts_one_separated_string(self):
        assert collect_entities("宁德时代, 300750、2024-06-30") == ("宁德时代", "300750", "2024-06-30")

    def test_deduplicates_case_insensitively_keeping_the_first_spelling(self):
        assert collect_entities(["CATL", "catl", "Catl"]) == ("CATL",)

    def test_strips_surrounding_whitespace(self):
        assert collect_entities(["  宁德时代  "]) == ("宁德时代",)

    @pytest.mark.parametrize("raw", [None, 42, {"a": 1}, object()])
    def test_non_string_containers_yield_nothing(self, raw):
        assert collect_entities(raw) == ()

    def test_drops_non_string_items_inside_a_list(self):
        assert collect_entities(["宁德时代", None, 300750, ["nested"]]) == ("宁德时代",)

    def test_drops_single_character_entries(self):
        """One-character "entities" match everywhere and would gut the text."""
        assert collect_entities(["A", "3", "宁德时代"]) == ("宁德时代",)

    def test_drops_over_long_entries(self):
        assert collect_entities(["x" * (MAX_ENTITY_CHARS + 1), "宁德时代"]) == ("宁德时代",)

    def test_caps_the_declared_total(self):
        collected = collect_entities([f"entity-{index}" for index in range(MAX_ENTITIES + 25)])
        assert len(collected) == MAX_ENTITIES
        assert collected[0] == "entity-0"


class TestFindLeakedEntities:
    def test_reports_entities_present_in_the_text(self):
        text = "调用工具查询 宁德时代 的股东结构。"
        assert find_leaked_entities(text, ("宁德时代", "比亚迪")) == ("宁德时代",)

    def test_matching_is_case_insensitive(self):
        assert find_leaked_entities("Query CATL shareholders", ("catl",)) == ("catl",)

    def test_preserves_declaration_order(self):
        text = "比亚迪 与 宁德时代"
        assert find_leaked_entities(text, ("宁德时代", "比亚迪")) == ("宁德时代", "比亚迪")

    @pytest.mark.parametrize("text", ["", None, 42])
    def test_empty_or_invalid_text_leaks_nothing(self, text):
        assert find_leaked_entities(text, ("宁德时代",)) == ()

    def test_no_entities_means_no_leak(self):
        assert find_leaked_entities("宁德时代", ()) == ()


class TestLeakedFields:
    def test_maps_each_field_to_its_own_leaks(self):
        surfaces = {
            "description": "查询 宁德时代 的股东结构",
            "reasoning": "按持股比例排序",
            "answer_format": "表格：股东名称、持股比例（例如 宁德时代）",
        }
        assert leaked_fields(surfaces, ("宁德时代",)) == {
            "description": ("宁德时代",),
            "answer_format": ("宁德时代",),
        }

    def test_clean_surfaces_produce_an_empty_mapping(self):
        assert leaked_fields({"description": "查询目标公司的股东结构"}, ("宁德时代",)) == {}


class TestRedactEntities:
    def test_replaces_the_entity_with_the_placeholder(self):
        assert redact_entities("查询 宁德时代 的股东", ("宁德时代",)) == f"查询 {ENTITY_PLACEHOLDER} 的股东"

    def test_redacts_every_occurrence(self):
        assert redact_entities("宁德时代 与 宁德时代", ("宁德时代",)) == f"{ENTITY_PLACEHOLDER} 与 {ENTITY_PLACEHOLDER}"

    def test_redaction_is_case_insensitive(self):
        assert redact_entities("CATL and catl", ("catl",)) == f"{ENTITY_PLACEHOLDER} and {ENTITY_PLACEHOLDER}"

    def test_the_longest_entity_wins_an_overlapping_match(self):
        """A short entity must not split a longer one and leave a fragment behind."""
        redacted = redact_entities("宁德时代新能源科技股份有限公司", ("宁德时代", "宁德时代新能源科技股份有限公司"))
        assert redacted == ENTITY_PLACEHOLDER
        assert "新能源" not in redacted

    def test_adjacent_placeholders_collapse_into_one(self):
        redacted = redact_entities("宁德时代 300750", ("宁德时代", "300750"))
        assert redacted == ENTITY_PLACEHOLDER

    def test_text_without_entities_is_unchanged(self):
        assert redact_entities("按报告期排序", ("宁德时代",)) == "按报告期排序"

    def test_no_entities_returns_the_text_verbatim(self):
        assert redact_entities("宁德时代", ()) == "宁德时代"

    @pytest.mark.parametrize("text", ["", None])
    def test_empty_text_is_safe(self, text):
        assert redact_entities(text, ("宁德时代",)) == ""


class TestRedactSurfaces:
    def test_only_returns_non_empty_fields(self):
        surfaces = {"description": "查询 宁德时代", "caveats": ""}
        assert redact_surfaces(surfaces, ("宁德时代",)) == {"description": f"查询 {ENTITY_PLACEHOLDER}"}

    def test_redacts_every_listed_field(self):
        surfaces = {"description": "宁德时代 股东", "reasoning": "宁德时代 持股"}
        redacted = redact_surfaces(surfaces, ("宁德时代",))
        assert "宁德时代" not in redacted["description"]
        assert "宁德时代" not in redacted["reasoning"]
