"""Global storage for auto-generated skills.

Two properties drive every decision here.

**Shared visibility.** A skill learned from one user's run must be matchable by
every other user, so it cannot live in ``users/{uid}/skills/custom/``. It is
written under the global integrations root instead::

    {base_dir}/integrations/skills/auto-skill/{name}/SKILL.md

That root is the only location that is simultaneously (a) scanned
unconditionally by every user's ``UserScopedSkillStorage._iter_skill_files`` —
unlike the global ``skills/custom/`` legacy root, which shadow-mount semantics
hide from any user who owns a custom skill — (b) writable at runtime, unlike the
repo's ``skills/public/`` which the production compose mounts read-only, and
(c) enabled by default for every user, because ``is_skill_enabled`` and
``get_skill_enabled_state`` both default true for the integrations category.

The trade-off, accepted deliberately: these packages surface in the UI as
read-only managed integration skills, the same tier as the official Lark pack.
A user who wants a private variant creates a same-named custom skill, which
shadows the global one because CUSTOM is scanned after INTEGRATION.

**Latest-only visibility with a recoverable history.** Updating a scenario moves
the outgoing package to a backup store outside every scanned root::

    {base_dir}/auto-skill-backup/{name}/v{n}/SKILL.md

so exactly one package per scenario is ever discoverable, while every superseded
version stays restorable. The visible name is stable (``{prefix}-{slug}``, no
version suffix); the version lives in frontmatter ``metadata.version`` and in the
backup directory name, so matching, ``skill_context`` references and any user
bookmark survive an update.

Publication follows the Lark installer's discipline: cross-process lock, private
dot-prefixed staging directory, validation of the exact bytes, sandbox-readable
permissions, then a single atomic rename — with backup/restore around the rename
so a failed publication cannot lose the previous version. Atomic rename also
guarantees a new inode, which is what the projection's metadata-digest freshness
check relies on to repair every user's sandbox view lazily on next acquire.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from deerflow.config.paths import get_paths
from deerflow.skills.auto.naming import normalize_prefix
from deerflow.skills.frontmatter import split_skill_markdown
from deerflow.skills.parser import parse_skill_file
from deerflow.skills.permissions import make_skill_tree_sandbox_readable
from deerflow.skills.storage.skill_storage import SkillStorage
from deerflow.skills.types import SKILL_MD_FILE, SkillCategory
from deerflow.utils.file_lock import retry_until_locked

logger = logging.getLogger(__name__)

#: Provider namespace under the global integrations root.
PROVIDER_DIR_NAME = "auto-skill"
#: Backup store directory name, directly under the runtime base dir.
BACKUP_DIR_NAME = "auto-skill-backup"
#: Cross-process lock file guarding publication.
_LOCK_FILE_NAME = ".auto-skill.write.lock"
#: Prefix for private staging directories; the leading dot keeps skill discovery
#: from ever walking into a half-written package.
_STAGING_PREFIX = ".staging-auto-skill-"
#: Backup sub-directory prefix for swept legacy per-user packages.
_LEGACY_BACKUP_PREFIX = "legacy-"

try:  # pragma: no cover - platform dependent
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]
try:  # pragma: no cover - Windows only
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None  # type: ignore[assignment]

_process_locks: dict[Path, threading.RLock] = {}
_process_locks_guard = threading.Lock()


class AutoSkillStoreError(RuntimeError):
    """A store operation could not be completed."""


@dataclass(frozen=True, slots=True)
class StoredSkill:
    """The currently visible package for one scenario."""

    name: str
    version: int
    content: str
    path: Path


@dataclass(frozen=True, slots=True)
class WriteResult:
    """Outcome of one publication."""

    skill: StoredSkill
    #: Version moved into the backup store, or ``None`` for a first write.
    backed_up_version: int | None
    pruned: tuple[int, ...] = ()

    @property
    def name(self) -> str:
        return self.skill.name

    @property
    def version(self) -> int:
        return self.skill.version

    @property
    def content(self) -> str:
        return self.skill.content


# ── paths ────────────────────────────────────────────────────────────────────


def auto_skill_root() -> Path:
    """Global directory holding every visible auto-generated skill package."""
    return get_paths().integration_skills_dir() / PROVIDER_DIR_NAME


def auto_skill_backup_root() -> Path:
    """Backup store. Deliberately outside every root skill discovery walks."""
    return get_paths().base_dir / BACKUP_DIR_NAME


def skill_dir(name: str) -> Path:
    return auto_skill_root() / name


def skill_file(name: str) -> Path:
    return skill_dir(name) / SKILL_MD_FILE


def backup_dir(name: str) -> Path:
    return auto_skill_backup_root() / name


# ── reading ──────────────────────────────────────────────────────────────────


def parse_version(content: str) -> int:
    """Read ``metadata.version`` from frontmatter, returning 0 when absent."""
    parts, _error = split_skill_markdown(content)
    if parts is None:
        return 0
    metadata = parts.metadata.get("metadata")
    if not isinstance(metadata, dict):
        return 0
    raw = metadata.get("version")
    try:
        version = int(str(raw).strip())
    except (TypeError, ValueError):
        return 0
    return version if version >= 1 else 0


def read_current(name: str) -> StoredSkill | None:
    """Return the visible package for ``name``, or ``None`` when absent."""
    path = skill_file(name)
    try:
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, ValueError):
        return None
    return StoredSkill(name=name, version=parse_version(content), content=content, path=path)


def current_version(name: str) -> int:
    """Version of the visible package, or 0 when there is none."""
    stored = read_current(name)
    return stored.version if stored is not None else 0


def list_current_names() -> list[str]:
    """Visible package names, sorted. Dot-directories are never packages."""
    root = auto_skill_root()
    if not root.is_dir():
        return []
    names: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if (entry / SKILL_MD_FILE).is_file():
            names.append(entry.name)
    return names


def list_backup_versions(name: str) -> list[int]:
    """Backup versions for a scenario, ascending. Legacy entries are excluded."""
    root = backup_dir(name)
    if not root.is_dir():
        return []
    versions: list[int] = []
    for entry in root.iterdir():
        if not entry.is_dir() or not entry.name.startswith("v"):
            continue
        try:
            version = int(entry.name[1:])
        except ValueError:
            continue
        if (entry / SKILL_MD_FILE).is_file():
            versions.append(version)
    return sorted(versions)


def list_current_summaries() -> list[tuple[str, int, str]]:
    """Return ``(name, version, description)`` for every visible package.

    Used to show the synthesis model which scenarios already exist, so a run that
    did not happen to load its scenario's skill still resolves to that scenario
    instead of minting a near-duplicate under a different slug. Unreadable or
    unparseable packages are skipped rather than raising.
    """
    summaries: list[tuple[str, int, str]] = []
    for name in list_current_names():
        stored = read_current(name)
        if stored is None:
            continue
        description = ""
        parts, _error = split_skill_markdown(stored.content)
        if parts is not None:
            raw = parts.metadata.get("description")
            description = raw.strip() if isinstance(raw, str) else ""
        summaries.append((name, stored.version, description))
    return summaries


# ── locking ──────────────────────────────────────────────────────────────────


def _lock_for(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _process_locks_guard:
        return _process_locks.setdefault(resolved, threading.RLock())


@contextmanager
def auto_skill_write_lock(*, timeout: float | None = 60.0) -> Iterator[None]:
    """Serialize publication in-process and across Gateway workers.

    One lock for the whole provider directory rather than per skill: updates are
    rare, short, and off the request path, so the coarser lock removes any chance
    of two workers interleaving a backup and a rename for different scenarios
    while keeping the reasoning trivial.
    """
    root = auto_skill_root()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root.parent / _LOCK_FILE_NAME
    process_lock = _lock_for(lock_path)
    deadline = None if timeout is None else time.monotonic() + timeout
    while not process_lock.acquire(timeout=0.05):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("auto-skill write lock timeout")
    try:
        with lock_path.open("a", encoding="utf-8") as lock_file:

            def acquire_region() -> None:
                if fcntl is not None:
                    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                elif msvcrt is not None:  # pragma: no cover - Windows
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)

            retry_until_locked(
                acquire_region,
                interval=0.02,
                deadline=deadline,
                sleep=time.sleep,
                monotonic=time.monotonic,
                timeout_message="auto-skill write lock timeout",
            )
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
                elif msvcrt is not None:  # pragma: no cover - Windows
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        process_lock.release()


# ── writing ──────────────────────────────────────────────────────────────────


def _validate_candidate(name: str, staged_file: Path) -> None:
    """Parse the exact staged bytes the way runtime discovery will."""
    SkillStorage.validate_skill_name(name)
    relative_path = Path(PROVIDER_DIR_NAME) / name
    skill = parse_skill_file(staged_file, SkillCategory.INTEGRATION, relative_path)
    if skill is None:
        raise ValueError(f"generated SKILL.md for '{name}' did not parse as a valid skill package")
    if skill.name != name:
        raise ValueError(f"frontmatter name {skill.name!r} does not match target {name!r}")


def _publish_tree(staged: Path, target: Path) -> None:
    """Atomically place ``staged`` at ``target`` on the same filesystem."""
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged, target)


def write_skill(name: str, *, render: Callable[[int], str], prune_keep: int | None = None) -> WriteResult:
    """Publish one scenario package, backing up whatever it replaces.

    ``render`` receives the authoritative next version and returns the complete
    ``SKILL.md`` text. Taking a callback rather than pre-rendered content keeps
    version selection inside the lock, so two workers learning the same scenario
    cannot both compute ``v2`` and lose one update.

    Publication order is: stage → validate → permissions → move the current
    package into the backup store → rename staging into place. A failure after
    the backup move restores it, so a failed update never leaves the scenario
    without a visible skill.
    """
    with auto_skill_write_lock():
        target = skill_dir(name)
        staged_parent = auto_skill_root().parent / f"{_STAGING_PREFIX}{os.getpid()}-{uuid.uuid4().hex[:12]}"
        staged = staged_parent / name
        backed_up: Path | None = None
        previous_version = 0

        try:
            existing = read_current(name)
            previous_version = existing.version if existing is not None else 0
            next_version = previous_version + 1

            content = render(next_version)
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"render produced no content for '{name}'")

            staged.mkdir(parents=True, exist_ok=True)
            staged_file = staged / SKILL_MD_FILE
            # newline="" so the validated bytes are exactly the published bytes.
            staged_file.write_text(content, encoding="utf-8", newline="")
            _validate_candidate(name, staged_file)
            make_skill_tree_sandbox_readable(staged)

            if existing is not None and previous_version >= 1:
                backed_up = backup_dir(name) / f"v{previous_version}"
                backed_up.parent.mkdir(parents=True, exist_ok=True)
                if backed_up.exists():
                    shutil.rmtree(backed_up)
                shutil.move(str(target), str(backed_up))
                backed_up_version: int | None = previous_version
            else:
                backed_up_version = None

            if target.exists():
                # Only reachable when the previous package had no parseable
                # version; retire it under a synthetic name rather than drop it.
                retire = backup_dir(name) / f"{_LEGACY_BACKUP_PREFIX}unversioned-{uuid.uuid4().hex[:8]}"
                retire.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(retire))

            _publish_tree(staged, target)
            staged = Path()  # ownership transferred; nothing to clean up
        except BaseException:
            if backed_up is not None and not target.exists() and backed_up.exists():
                try:
                    shutil.move(str(backed_up), str(target))
                    backed_up = None
                except OSError:
                    logger.error("auto-skill publication failed and the backup could not be restored for %s", name, exc_info=True)
            raise
        finally:
            if staged != Path():
                shutil.rmtree(staged_parent, ignore_errors=True)
            elif staged_parent.exists():
                shutil.rmtree(staged_parent, ignore_errors=True)

        published = read_current(name)
        if published is None:  # pragma: no cover - publication just succeeded
            raise AutoSkillStoreError(f"'{name}' is not readable after publication")

        pruned: tuple[int, ...] = ()
        if prune_keep is not None:
            try:
                pruned = tuple(prune_backups(name, keep=prune_keep))
            except OSError:
                logger.warning("auto-skill backup retention failed for %s", name, exc_info=True)

        logger.info("auto-skill published %s v%d (backed_up=%s, pruned=%s)", name, published.version, backed_up_version, list(pruned))
        return WriteResult(skill=published, backed_up_version=backed_up_version, pruned=pruned)


def prune_backups(name: str, *, keep: int) -> list[int]:
    """Delete all but the newest ``keep`` backups; returns removed versions."""
    if keep < 0:
        raise ValueError("keep must be non-negative")
    versions = list_backup_versions(name)
    if keep == 0:
        removed = versions
    else:
        removed = versions[:-keep] if len(versions) > keep else []
    for version in removed:
        shutil.rmtree(backup_dir(name) / f"v{version}", ignore_errors=True)
    return removed


def restore_backup(name: str, version: int) -> bool:
    """Roll the visible package back to a backup, preserving both versions.

    The restore is itself a version bump: the version being rolled off moves into
    the backup store, so an operator can undo the undo.
    """
    source = backup_dir(name) / f"v{version}" / SKILL_MD_FILE
    if not source.is_file():
        return False
    content = source.read_text(encoding="utf-8-sig")

    def _render(next_version: int) -> str:
        parts, error = split_skill_markdown(content)
        if parts is None:
            raise ValueError(f"backup v{version} of '{name}' has no parseable frontmatter: {error}")
        metadata = dict(parts.metadata.get("metadata") or {})
        metadata["version"] = str(next_version)
        metadata["restored-from"] = f"v{version}"
        rebuilt = ["---", f"name: {name}"]
        description = parts.metadata.get("description")
        if description is not None:
            import json

            rebuilt.append(f"description: {json.dumps(str(description), ensure_ascii=False)}")
        rebuilt.append("metadata:")
        for key, value in metadata.items():
            import json

            rebuilt.append(f"  {key}: {json.dumps(str(value), ensure_ascii=False)}")
        rebuilt.append("---")
        return "\n".join(rebuilt) + "\n" + parts.body

    write_skill(name, render=_render)
    return True


# ── legacy migration ─────────────────────────────────────────────────────────


def migrate_legacy_user_skills(user_id: str, *, prefix: str = "auto") -> dict[str, list[str]]:
    """One-shot migration of per-user versioned packages left by earlier releases.

    Earlier releases wrote ``{prefix}-{slug}-v{n}`` into each user's custom root,
    so several versions of one scenario were visible at once. This groups them by
    scenario and, for each group:

    - publishes the **highest** version globally under the stable name, but only
      when no global package exists yet — an existing global package is newer by
      definition (it was learned after the migration boundary) and must not be
      clobbered by an older per-user copy;
    - archives every version of the group into the backup store;
    - deletes the per-user packages through the storage API, which owns the
      projection lock.

    Only packages whose frontmatter carries ``metadata.author: auto-skill`` are
    touched; an operator's hand-written skill matching the name pattern is left
    alone, as is anything unreadable. Idempotent: a second run finds nothing.

    Returns ``{"promoted": [...], "archived": [...], "skipped": [...]}``.
    """
    import re

    from deerflow.skills.storage import get_or_new_user_skill_storage

    pattern = re.compile(rf"^(?P<prefix>{re.escape(prefix)})-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)-v(?P<version>\d+)$")
    report: dict[str, list[str]] = {"promoted": [], "archived": [], "skipped": []}

    try:
        storage = get_or_new_user_skill_storage(user_id)
        skills = storage.load_skills()
    except Exception:
        logger.warning("auto-skill migration could not read skills for user %s", user_id, exc_info=True)
        return report

    groups: dict[str, list[tuple[int, object, str]]] = {}
    for skill in skills:
        if skill.category != SkillCategory.CUSTOM:
            continue
        match = pattern.fullmatch(skill.name)
        if match is None:
            continue
        try:
            content = skill.skill_file.read_text(encoding="utf-8-sig")
        except OSError:
            report["skipped"].append(skill.name)
            continue
        if not _is_auto_generated(content):
            report["skipped"].append(skill.name)
            continue
        groups.setdefault(match.group("slug"), []).append((int(match.group("version")), skill, content))

    for slug, entries in sorted(groups.items()):
        entries.sort(key=lambda item: item[0])
        stable_name = f"{normalize_prefix(prefix)}-{slug}"

        if read_current(stable_name) is None:
            highest_version, _skill, highest_content = entries[-1]

            def _render(next_version: int, _body: str = highest_content, _from: str = f"legacy v{highest_version}") -> str:
                return _rebase_frontmatter(_body, name=stable_name, version=next_version, migrated_from=_from)

            try:
                write_skill(stable_name, render=_render)
                report["promoted"].append(stable_name)
            except (OSError, ValueError) as exc:
                logger.warning("auto-skill migration could not promote %s: %s", stable_name, exc)
                report["skipped"].extend(s.name for _v, s, _c in entries)
                continue

        for version, skill, _content in entries:
            archive = backup_dir(stable_name) / f"{_LEGACY_BACKUP_PREFIX}{user_id}-v{version}"
            try:
                archive.parent.mkdir(parents=True, exist_ok=True)
                if archive.exists():
                    shutil.rmtree(archive)
                shutil.copytree(skill.skill_dir, archive)
                storage.delete_custom_skill(skill.name, history_meta={"action": "delete", "author": PROVIDER_DIR_NAME, "reason": "migrated to global auto-skill store"})
                report["archived"].append(skill.name)
            except OSError:
                logger.warning("auto-skill migration could not archive %s", skill.name, exc_info=True)
                report["skipped"].append(skill.name)

    if report["promoted"] or report["archived"]:
        logger.info("auto-skill migration for user %s: promoted=%s archived=%s skipped=%s", user_id, report["promoted"], report["archived"], report["skipped"])
    return report


def _rebase_frontmatter(content: str, *, name: str, version: int, migrated_from: str) -> str:
    """Rewrite a legacy package's frontmatter for its new stable name and version.

    The body is carried over verbatim: it was already scanned when first written,
    and re-rendering it would lose whatever the original synthesis produced.
    """
    import json as _json

    parts, error = split_skill_markdown(content)
    if parts is None:
        raise ValueError(f"legacy package has no parseable frontmatter: {error}")

    metadata = dict(parts.metadata.get("metadata") or {})
    metadata["author"] = PROVIDER_DIR_NAME
    metadata["version"] = str(version)
    metadata["migrated-from"] = migrated_from
    if "generated-at" not in metadata:
        metadata["generated-at"] = datetime.now(UTC).isoformat(timespec="seconds")

    lines = ["---", f"name: {name}"]
    description = parts.metadata.get("description")
    if description is not None:
        lines.append(f"description: {_json.dumps(str(description), ensure_ascii=False)}")
    lines.append("metadata:")
    for key, value in metadata.items():
        lines.append(f"  {key}: {_json.dumps(str(value), ensure_ascii=False)}")
    lines.append("---")
    return "\n".join(lines) + "\n" + parts.body


def _is_auto_generated(content: str) -> bool:
    parts, _error = split_skill_markdown(content)
    if parts is None:
        return False
    metadata = parts.metadata.get("metadata")
    return isinstance(metadata, dict) and metadata.get("author") == PROVIDER_DIR_NAME


def sweep_legacy_user_skills(user_id: str, *, prefix: str, slug: str) -> list[str]:
    """Retire per-user ``{prefix}-{slug}-v{n}`` packages left by earlier releases.

    Earlier versions of this feature wrote versioned packages into each user's
    custom root. Now that a scenario has one global, stable-named package, those
    copies would sit beside it as duplicates. They are archived into the same
    backup store (grouped under the scenario, prefixed ``legacy-`` so version
    listing and retention ignore them) and then deleted through the storage API,
    which owns the projection lock.

    Only packages whose frontmatter still carries ``metadata.author: auto-skill``
    are touched; an operator's hand-written skill that happens to match the name
    pattern is left alone, and so is anything unreadable.
    """
    import re

    from deerflow.skills.storage import get_or_new_user_skill_storage

    pattern = re.compile(rf"^{re.escape(prefix)}-{re.escape(slug)}-v(\d+)$")
    try:
        storage = get_or_new_user_skill_storage(user_id)
        skills = storage.load_skills()
    except Exception:
        logger.warning("auto-skill legacy sweep could not read skills for user %s", user_id, exc_info=True)
        return []

    swept: list[str] = []
    for skill in skills:
        if skill.category != SkillCategory.CUSTOM or not pattern.fullmatch(skill.name):
            continue
        try:
            content = skill.skill_file.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        if not _is_auto_generated(content):
            logger.info("auto-skill legacy sweep skipped %s: not marked as auto-generated", skill.name)
            continue

        archive = backup_dir(f"{prefix}-{slug}") / f"{_LEGACY_BACKUP_PREFIX}{user_id}-{skill.name}"
        try:
            archive.parent.mkdir(parents=True, exist_ok=True)
            if archive.exists():
                shutil.rmtree(archive)
            shutil.copytree(skill.skill_dir, archive)
            storage.delete_custom_skill(skill.name, history_meta={"action": "delete", "author": PROVIDER_DIR_NAME, "reason": "migrated to global auto-skill store"})
        except OSError:
            logger.warning("auto-skill legacy sweep failed for %s", skill.name, exc_info=True)
            continue
        swept.append(skill.name)

    if swept:
        logger.info("auto-skill legacy sweep retired %s for user %s", sorted(swept), user_id)
    return sorted(swept)
