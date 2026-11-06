"""Automatic skill synthesis from completed run trajectories.

The package turns one finished lead-agent run into a reusable, versioned custom
skill:

- :mod:`~deerflow.skills.auto.trajectory` distils the run's messages and state
  channels into a bounded :class:`RunTrajectory` (query, matched skills, tool
  calls with results, final answer).
- :mod:`~deerflow.skills.auto.naming` derives the hyphen-case scenario slug and
  the next version number from the skills already on disk.
- :mod:`~deerflow.skills.auto.synthesizer` asks a model to write the
  ``SKILL.md`` body and persists it through the same validation, static-scan,
  LLM-moderation, history and cache-reset pipeline the agent-driven
  ``skill_manage`` tool uses.
- :mod:`~deerflow.skills.auto.queue` holds the debounced background worker that
  keeps synthesis off the run's critical path.
- :class:`~deerflow.agents.middlewares.auto_skill_middleware.AutoSkillMiddleware`
  is the ``after_agent`` producer.

Synthesis is best effort: nothing here may raise into a run. Every entry point
catches, logs and drops.
"""

from deerflow.skills.auto.naming import AutoSkillNamingError, next_skill_version, resolve_skill_name, scenario_slug
from deerflow.skills.auto.queue import AutoSkillQueue, AutoSkillRequest, get_auto_skill_queue, reset_auto_skill_queue
from deerflow.skills.auto.store import (
    PROVIDER_DIR_NAME,
    StoredSkill,
    WriteResult,
    auto_skill_backup_root,
    auto_skill_root,
    backup_dir,
    current_version,
    list_backup_versions,
    list_current_names,
    list_current_summaries,
    migrate_legacy_user_skills,
    prune_backups,
    read_current,
    restore_backup,
    skill_dir,
    skill_file,
    sweep_legacy_user_skills,
    write_skill,
)
from deerflow.skills.auto.synthesizer import SynthesizedSkill, synthesize_skill
from deerflow.skills.auto.trajectory import RunTrajectory, ToolStep, extract_run_trajectory, render_trajectory

__all__ = [
    "AutoSkillNamingError",
    "AutoSkillQueue",
    "AutoSkillRequest",
    "PROVIDER_DIR_NAME",
    "RunTrajectory",
    "StoredSkill",
    "SynthesizedSkill",
    "ToolStep",
    "WriteResult",
    "auto_skill_backup_root",
    "auto_skill_root",
    "backup_dir",
    "current_version",
    "extract_run_trajectory",
    "get_auto_skill_queue",
    "list_backup_versions",
    "list_current_names",
    "list_current_summaries",
    "migrate_legacy_user_skills",
    "next_skill_version",
    "prune_backups",
    "read_current",
    "render_trajectory",
    "reset_auto_skill_queue",
    "resolve_skill_name",
    "restore_backup",
    "scenario_slug",
    "skill_dir",
    "skill_file",
    "sweep_legacy_user_skills",
    "synthesize_skill",
    "write_skill",
]
