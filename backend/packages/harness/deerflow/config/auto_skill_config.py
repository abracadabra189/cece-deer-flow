from pydantic import BaseModel, Field, ValidationInfo, field_validator

from deerflow.config._boolean_guards import reject_boolean

#: Skill names must stay hyphen-case to satisfy ``SkillStorage.validate_skill_name``.
_NAME_PREFIX_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
#: The prefix shares the 64-character skill-name budget with the scenario slug and
#: the ``-v{n}`` suffix, so it is capped well below that to leave room for both.
_MAX_NAME_PREFIX_CHARS = 32


class AutoSkillConfig(BaseModel):
    """Configuration for post-run automatic skill synthesis.

    When enabled, the lead agent's ``after_agent`` hook captures the completed
    run's trajectory (query, matched skills, tool calls with results, final
    answer) and hands it to a debounced background worker. The worker asks a
    model to distil that trajectory into a reusable ``SKILL.md`` covering the
    data-fetching logic, the reasoning logic and the answer format, then writes
    it through the same validation and security-scan pipeline the agent-driven
    ``skill_manage`` tool uses. Generated skills are versioned per scenario so a
    later run of the same scenario produces a new version rather than mutating
    the previous one.

    Synthesis is best effort and never blocks or fails a run: a skipped,
    rejected or errored synthesis is logged and dropped.
    """

    enabled: bool = Field(
        default=False,
        description="Whether completed runs are distilled into versioned custom skills.",
    )
    model_name: str | None = Field(
        default=None,
        description="Model used for skill synthesis. Defaults to the primary chat model.",
    )
    name_prefix: str = Field(
        default="auto",
        description=f"Hyphen-case prefix for generated skill names: {{prefix}}-{{scenario}}-v{{n}}. At most {_MAX_NAME_PREFIX_CHARS} characters.",
    )
    min_tool_calls: int = Field(
        default=1,
        description="Runs with fewer successful tool calls are skipped: there is no data-fetching path worth capturing.",
    )
    max_trajectory_chars: int = Field(
        default=24000,
        description="Total character budget for the trajectory handed to the synthesis model.",
    )
    max_tool_result_chars: int = Field(
        default=2000,
        description="Per-tool-result character budget applied before the total trajectory budget.",
    )
    debounce_seconds: float = Field(
        default=20.0,
        description="Quiet period before a queued trajectory is synthesized, so rapid turns in one thread batch together.",
    )
    max_versions: int = Field(
        default=5,
        description="Versions kept per scenario; older generated versions are pruned.",
    )
    queue_max_size: int = Field(
        default=64,
        description="Bounded pending-trajectory queue. A full queue drops the new trajectory rather than applying backpressure to the run.",
    )
    shutdown_flush_timeout_seconds: float = Field(
        default=30.0,
        description="Bound on draining queued trajectories during graceful Gateway shutdown.",
    )

    @field_validator("name_prefix")
    @classmethod
    def _validate_name_prefix(cls, value: str) -> str:
        import re

        normalized = value.strip().lower()
        if not re.fullmatch(_NAME_PREFIX_PATTERN, normalized):
            raise ValueError(f"auto_skill.name_prefix must be hyphen-case ({_NAME_PREFIX_PATTERN}), got {value!r}")
        if len(normalized) > _MAX_NAME_PREFIX_CHARS:
            raise ValueError(f"auto_skill.name_prefix must be at most {_MAX_NAME_PREFIX_CHARS} characters, got {len(normalized)}")
        return normalized

    @field_validator("min_tool_calls", mode="before")
    @classmethod
    def _reject_boolean_min_tool_calls(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")

    @field_validator("max_trajectory_chars", "max_tool_result_chars", "max_versions", "queue_max_size", mode="before")
    @classmethod
    def _reject_boolean_integers(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")

    @field_validator("min_tool_calls")
    @classmethod
    def _validate_min_tool_calls(cls, value: int) -> int:
        if value < 0:
            raise ValueError("auto_skill.min_tool_calls must be non-negative")
        return value

    @field_validator("max_trajectory_chars", "max_tool_result_chars")
    @classmethod
    def _validate_positive_chars(cls, value: int) -> int:
        if value < 1:
            raise ValueError("auto_skill character budgets must be positive integers")
        return value

    @field_validator("max_versions", "queue_max_size")
    @classmethod
    def _validate_at_least_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("auto_skill.max_versions and queue_max_size must be at least 1")
        return value

    @field_validator("debounce_seconds", "shutdown_flush_timeout_seconds", mode="before")
    @classmethod
    def _reject_boolean_seconds(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="a number of seconds")

    @field_validator("debounce_seconds", "shutdown_flush_timeout_seconds")
    @classmethod
    def _validate_non_negative_seconds(cls, value: float) -> float:
        if value < 0:
            raise ValueError("auto_skill timing values must be non-negative")
        return value
