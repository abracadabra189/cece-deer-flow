"""Scenario slug and stable skill naming for auto-generated skills."""

import pytest

from deerflow.skills.auto.naming import (
    MAX_SKILL_NAME_CHARS,
    AutoSkillNamingError,
    deterministic_slug,
    next_skill_version,
    normalize_prefix,
    normalize_slug,
    parse_generated_version,
    resolve_skill_name,
    scenario_slug,
)
from deerflow.skills.storage.skill_storage import SkillStorage


class TestNormalizeSlug:
    def test_lowercases_and_collapses_separators(self):
        assert normalize_slug("PEVC Funding  Lookup!", max_chars=48) == "pevc-funding-lookup"

    def test_trims_leading_and_trailing_hyphens(self):
        assert normalize_slug("--funding--", max_chars=48) == "funding"

    def test_fits_max_chars_without_trailing_hyphen(self):
        slug = normalize_slug("alpha-beta-gamma-delta", max_chars=11)
        assert len(slug) <= 11
        assert not slug.endswith("-")

    @pytest.mark.parametrize("proposed", ["", "   ", "---", "中文场景名称", None, 42, {"a": 1}])
    def test_returns_empty_for_unusable_proposals(self, proposed):
        assert normalize_slug(proposed, max_chars=48) == ""


class TestDeterministicSlug:
    def test_is_stable_for_identical_queries(self):
        assert deterministic_slug("查一下 A 公司的融资历史") == deterministic_slug("查一下 A 公司的融资历史")

    def test_ignores_surrounding_whitespace_and_case(self):
        """Trivially different phrasings of one question map to one scenario."""
        assert deterministic_slug("  Query   Funding ") == deterministic_slug("query funding")

    def test_differs_for_different_queries(self):
        assert deterministic_slug("查融资") != deterministic_slug("查工商")

    def test_is_valid_hyphen_case(self):
        slug = deterministic_slug("查一下 A 公司的融资历史")
        assert normalize_slug(slug, max_chars=64) == slug


class TestScenarioSlug:
    def test_prefers_the_model_proposal(self):
        assert scenario_slug("pevc-funding-lookup", query="查融资", max_chars=48) == "pevc-funding-lookup"

    def test_normalizes_a_messy_proposal(self):
        assert scenario_slug("PEVC 融资 Lookup!!", query="查融资", max_chars=48) == "pevc-lookup"

    def test_falls_back_to_query_hash_for_cjk_only_proposal(self):
        """A purely Chinese proposal must still yield a stable valid slug."""
        slug = scenario_slug("融资查询场景", query="查一下 A 公司的融资历史", max_chars=48)
        assert slug == deterministic_slug("查一下 A 公司的融资历史")
        assert normalize_slug(slug, max_chars=64) == slug

    def test_falls_back_for_empty_proposal(self):
        assert scenario_slug("", query="查融资", max_chars=48) == deterministic_slug("查融资")

    def test_the_same_scenario_always_resolves_to_the_same_slug(self):
        """Stability is what makes 'one visible skill per scenario' work."""
        first = scenario_slug("industry fund lookup", query="查基金", max_chars=48)
        second = scenario_slug("Industry  Fund   Lookup", query="查基金", max_chars=48)
        assert first == second


class TestNormalizePrefix:
    @pytest.mark.parametrize("value", ["auto", "AUTO", "  auto  ", "auto-skill", "learned2"])
    def test_accepts_and_normalizes_hyphen_case(self, value):
        assert normalize_prefix(value) == value.strip().lower()

    @pytest.mark.parametrize("value", ["", "   ", "!!!", "自动", None, 42])
    def test_rejects_unusable_prefixes(self, value):
        with pytest.raises(AutoSkillNamingError):
            normalize_prefix(value)


class TestResolveSkillName:
    def test_builds_the_stable_name_without_a_version_suffix(self):
        """The visible name must not churn across updates."""
        assert resolve_skill_name(prefix="auto", slug="pevc-funding") == "auto-pevc-funding"
        assert "-v" not in resolve_skill_name(prefix="auto", slug="pevc-funding")

    def test_result_always_satisfies_the_storage_contract(self):
        name = resolve_skill_name(prefix="auto", slug="x" * 200)
        assert len(name) <= MAX_SKILL_NAME_CHARS
        # The same validator the write path applies.
        assert SkillStorage.validate_skill_name(name) == name

    def test_slug_absorbs_overflow_from_a_long_prefix(self):
        name = resolve_skill_name(prefix="generated-scenario-skill", slug="a-very-long-scenario-slug-here")
        assert len(name) <= MAX_SKILL_NAME_CHARS
        assert name.startswith("generated-scenario-skill-")

    def test_rejects_an_empty_slug(self):
        with pytest.raises(AutoSkillNamingError):
            resolve_skill_name(prefix="auto", slug="")

    def test_rejects_an_unusable_prefix(self):
        with pytest.raises(AutoSkillNamingError):
            resolve_skill_name(prefix="!!!", slug="s")

    def test_rejects_when_no_slug_room_remains(self):
        long_prefix = "-".join(["segment"] * 12)
        with pytest.raises(AutoSkillNamingError):
            resolve_skill_name(prefix=long_prefix, slug="s")

    def test_the_same_scenario_always_yields_the_same_name(self):
        first = resolve_skill_name(prefix="auto", slug=scenario_slug("industry-fund", query="查基金"))
        second = resolve_skill_name(prefix="auto", slug=scenario_slug("industry-fund", query="查基金"))
        assert first == second


class TestLegacyVersionedNames:
    """Earlier releases used ``{prefix}-{slug}-v{n}``; the sweep still must read them."""

    def test_first_version_is_one(self):
        assert next_skill_version([], prefix="auto", slug="funding") == 1

    def test_increments_past_the_highest_existing_version(self):
        names = ["auto-funding-v1", "auto-funding-v3", "auto-funding-v2"]
        assert next_skill_version(names, prefix="auto", slug="funding") == 4

    def test_ignores_other_scenarios_and_other_prefixes(self):
        names = ["auto-other-v9", "manual-funding-v9", "deep-research", "auto-funding-v2"]
        assert next_skill_version(names, prefix="auto", slug="funding") == 3

    def test_ignores_prefix_matches_that_are_not_a_version_suffix(self):
        assert next_skill_version(["auto-funding-v2-beta", "auto-funding-vx"], prefix="auto", slug="funding") == 1

    def test_does_not_match_the_stable_name(self):
        """A stable-named package is not a legacy version and must not be swept."""
        assert parse_generated_version("auto-funding", prefix="auto", slug="funding") is None

    def test_tolerates_non_iterable_and_non_string_input(self):
        assert next_skill_version(None, prefix="auto", slug="funding") == 1
        assert next_skill_version([None, 42, "auto-funding-v1"], prefix="auto", slug="funding") == 2

    def test_parse_generated_version_round_trips(self):
        assert parse_generated_version("auto-funding-v5", prefix="auto", slug="funding") == 5
        assert parse_generated_version("auto-funding-v5", prefix="auto", slug="other") is None
        assert parse_generated_version(None, prefix="auto", slug="funding") is None
