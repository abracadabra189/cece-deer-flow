"""AutoSkillConfig validation, hot-reload boundary and lead-chain wiring."""

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.auto_skill_config import AutoSkillConfig
from deerflow.config.reload_boundary import STARTUP_ONLY_FIELDS


def _app_config(**auto_skill) -> AppConfig:
    return AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [],
            "memory": {"enabled": False},
            "summarization": {"enabled": False},
            "auto_skill": dict(auto_skill),
        }
    )


class TestDefaults:
    def test_is_disabled_by_default(self):
        """A learning feature that writes to disk must be opt-in."""
        assert AutoSkillConfig().enabled is False
        assert _app_config().auto_skill.enabled is False

    def test_default_bounds(self):
        config = AutoSkillConfig()
        assert config.name_prefix == "auto"
        assert config.model_name is None
        assert config.min_tool_calls == 1
        assert config.max_trajectory_chars == 24000
        assert config.max_tool_result_chars == 2000
        assert config.debounce_seconds == 20.0
        assert config.max_versions == 5
        assert config.queue_max_size == 64

    def test_parses_from_app_config(self):
        config = _app_config(enabled=True, name_prefix="learned", max_versions=3)
        assert config.auto_skill.enabled is True
        assert config.auto_skill.name_prefix == "learned"
        assert config.auto_skill.max_versions == 3


class TestNamePrefix:
    @pytest.mark.parametrize("value", ["auto", "AUTO", "  auto  ", "auto-skill", "learned2"])
    def test_accepts_and_normalizes_hyphen_case(self, value):
        assert AutoSkillConfig(name_prefix=value).name_prefix == value.strip().lower()

    @pytest.mark.parametrize("value", ["", "   ", "auto_skill", "Auto Skill", "-auto-", "自动", "auto!", "a" * 200])
    def test_rejects_prefixes_that_cannot_form_a_skill_name(self, value):
        """The prefix becomes part of a directory name and must stay hyphen-case."""
        with pytest.raises(ValueError):
            AutoSkillConfig(name_prefix=value)

    def test_prefix_length_leaves_room_for_slug_and_version(self):
        """The prefix shares the 64-char skill-name budget with slug and -v{n}."""
        assert AutoSkillConfig(name_prefix="a" * 32).name_prefix == "a" * 32
        with pytest.raises(ValueError):
            AutoSkillConfig(name_prefix="a" * 33)


class TestNumericBounds:
    @pytest.mark.parametrize("field", ["min_tool_calls"])
    @pytest.mark.parametrize("value", [-1, -100])
    def test_rejects_negative_counts(self, field, value):
        with pytest.raises(ValueError):
            AutoSkillConfig(**{field: value})

    @pytest.mark.parametrize("field", ["max_trajectory_chars", "max_tool_result_chars"])
    @pytest.mark.parametrize("value", [0, -1])
    def test_rejects_non_positive_char_budgets(self, field, value):
        with pytest.raises(ValueError):
            AutoSkillConfig(**{field: value})

    @pytest.mark.parametrize("field", ["max_versions", "queue_max_size"])
    @pytest.mark.parametrize("value", [0, -1])
    def test_rejects_below_one(self, field, value):
        with pytest.raises(ValueError):
            AutoSkillConfig(**{field: value})

    @pytest.mark.parametrize("field", ["min_tool_calls", "max_trajectory_chars", "max_versions", "queue_max_size"])
    def test_rejects_booleans_disguised_as_integers(self, field):
        """Pydantic would coerce True to 1; a flag is never a valid count."""
        with pytest.raises(ValueError):
            AutoSkillConfig(**{field: True})

    @pytest.mark.parametrize("field", ["debounce_seconds", "shutdown_flush_timeout_seconds"])
    @pytest.mark.parametrize("value", [-0.5, -1])
    def test_rejects_negative_durations(self, field, value):
        with pytest.raises(ValueError):
            AutoSkillConfig(**{field: value})

    def test_accepts_zero_debounce_for_immediate_drain(self):
        assert AutoSkillConfig(debounce_seconds=0.0).debounce_seconds == 0.0


class TestReloadBoundary:
    def test_toggling_does_not_require_a_restart(self):
        """The middleware is appended per agent assembly, so a toggle applies on the next run."""
        assert "auto_skill" not in STARTUP_ONLY_FIELDS


class TestLeadChainWiring:
    def _lead_chain(self, **auto_skill):
        from deerflow.agents.lead_agent.agent import build_middlewares
        from deerflow.extensions import get_agent_build_extensions

        app_config = _app_config(**auto_skill)
        return build_middlewares({}, None, app_config=app_config, memory_enabled=False, available_skills=set(), extensions=get_agent_build_extensions())

    def _subagent_chain(self, **auto_skill):
        from deerflow.agents.middlewares.tool_error_handling_middleware import build_subagent_runtime_middlewares
        from deerflow.extensions import get_agent_build_extensions

        app_config = _app_config(**auto_skill)
        return build_subagent_runtime_middlewares(app_config=app_config, available_skills=set(), extensions=get_agent_build_extensions())

    def test_enabled_adds_the_middleware_to_the_lead_chain(self, tmp_path, monkeypatch):
        from deerflow.agents.middlewares.auto_skill_middleware import AutoSkillMiddleware

        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "runtime"))
        chain = self._lead_chain(enabled=True)

        assert sum(isinstance(mw, AutoSkillMiddleware) for mw in chain) == 1

    def test_disabled_by_default_keeps_it_out_of_the_chain(self, tmp_path, monkeypatch):
        from deerflow.agents.middlewares.auto_skill_middleware import AutoSkillMiddleware

        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "runtime"))
        chain = self._lead_chain()

        assert not any(isinstance(mw, AutoSkillMiddleware) for mw in chain)

    def test_receives_the_resolved_config_snapshot(self, tmp_path, monkeypatch):
        from deerflow.agents.middlewares.auto_skill_middleware import AutoSkillMiddleware

        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "runtime"))
        chain = self._lead_chain(enabled=True, name_prefix="learned", min_tool_calls=4)
        middleware = next(mw for mw in chain if isinstance(mw, AutoSkillMiddleware))

        assert middleware._config.name_prefix == "learned"
        assert middleware._config.min_tool_calls == 4

    def test_is_never_installed_on_the_subagent_chain(self, tmp_path, monkeypatch):
        """A subagent trajectory is a fragment of the lead's; learning from it would encode partial work."""
        from deerflow.agents.middlewares.auto_skill_middleware import AutoSkillMiddleware

        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "runtime"))
        chain = self._subagent_chain(enabled=True)

        assert not any(isinstance(mw, AutoSkillMiddleware) for mw in chain)

    def test_sits_before_the_clarification_tail(self, tmp_path, monkeypatch):
        """ClarificationMiddleware must stay last so it can intercept ask_clarification."""
        from deerflow.agents.middlewares.auto_skill_middleware import AutoSkillMiddleware

        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "runtime"))
        chain = self._lead_chain(enabled=True)
        auto_index = next(i for i, mw in enumerate(chain) if isinstance(mw, AutoSkillMiddleware))
        clarification_index = next(i for i, mw in enumerate(chain) if type(mw).__name__ == "ClarificationMiddleware")

        assert auto_index < clarification_index
