"""Global auto-skill store: shared visibility, backup-on-update, atomic publication.

The load-bearing assertion is ``test_a_skill_written_once_is_visible_to_every_user``:
requirement 1 is that a skill learned from user A's run is matchable by user B,
which only holds if the write lands in a root every user's storage scans
unconditionally. Per-user ``custom/`` does not qualify; the global integrations
root does.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from deerflow.config.paths import get_paths
from deerflow.skills import auto as auto_package
from deerflow.skills.auto import store as store_module
from deerflow.skills.auto.store import (
    PROVIDER_DIR_NAME,
    StoredSkill,
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
    skill_file,
    sweep_legacy_user_skills,
    write_skill,
)
from deerflow.skills.frontmatter import split_skill_markdown
from deerflow.skills.storage import get_or_new_user_skill_storage, reset_user_skill_storage
from deerflow.skills.types import SKILL_MD_FILE, SkillCategory

#: Marker identifying the store's private staging directories.
_STAGING_MARKER = ".staging-auto-skill"


def _frontmatter(name: str, version: int, body: str = "正文") -> str:
    return f'---\nname: {name}\ndescription: "场景 {name} 的描述，含触发词：查询、分析。"\nmetadata:\n  author: "auto-skill"\n  version: "{version}"\n---\n\n# {name}\n\n{body}\n'


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated DEER_FLOW_HOME with the Paths singleton reset (see end-to-end suite)."""
    home = tmp_path / "runtime"
    monkeypatch.setenv("DEER_FLOW_HOME", str(home))
    monkeypatch.setattr("deerflow.config.paths._paths", None)
    reset_user_skill_storage()
    yield home
    reset_user_skill_storage()


class TestLayout:
    def test_root_lives_under_the_global_integrations_root(self, env):
        """The integrations root is the only always-scanned, writable, global location."""
        assert auto_skill_root() == get_paths().integration_skills_dir() / PROVIDER_DIR_NAME
        assert auto_skill_root().parent == get_paths().integration_skills_dir()

    def test_backup_root_is_outside_every_scanned_root(self, env):
        """Backups must never be discoverable as skills, so they live outside the trees."""
        backup = auto_skill_backup_root()
        assert backup == get_paths().base_dir / "auto-skill-backup"
        assert get_paths().integration_skills_dir() not in backup.parents
        assert not str(backup).startswith(str(get_paths().integration_skills_dir()))

    def test_skill_file_path(self, env):
        assert skill_file("auto-demo") == auto_skill_root() / "auto-demo" / SKILL_MD_FILE


class TestReadCurrent:
    def test_absent_skill_reads_as_none(self, env):
        assert read_current("auto-missing") is None
        assert current_version("auto-missing") == 0

    def test_reads_back_content_and_version(self, env):
        written = write_skill("auto-demo", render=lambda version: _frontmatter("auto-demo", version))

        assert written.version == 1
        stored = read_current("auto-demo")
        assert isinstance(stored, StoredSkill)
        assert stored.name == "auto-demo"
        assert stored.version == 1
        assert stored.content == written.content
        assert stored.path == skill_file("auto-demo")

    def test_list_current_names_ignores_dot_dirs_and_stray_files(self, env):
        write_skill("auto-a", render=lambda v: _frontmatter("auto-a", v))
        write_skill("auto-b", render=lambda v: _frontmatter("auto-b", v))
        root = auto_skill_root()
        (root / ".staging-leftover").mkdir(parents=True, exist_ok=True)
        (root / ".staging-leftover" / "ghost" / SKILL_MD_FILE).parent.mkdir(parents=True, exist_ok=True)
        (root / ".staging-leftover" / "ghost" / SKILL_MD_FILE).write_text(_frontmatter("ghost", 1), encoding="utf-8")
        (root / "loose.txt").write_text("not a skill", encoding="utf-8")

        assert sorted(list_current_names()) == ["auto-a", "auto-b"]

    def test_list_current_summaries_exposes_names_versions_and_descriptions(self, env):
        """The synthesizer needs this to avoid minting duplicate scenarios."""
        write_skill("auto-a", render=lambda v: _frontmatter("auto-a", v))
        write_skill("auto-b", render=lambda v: _frontmatter("auto-b", v))
        write_skill("auto-b", render=lambda v: _frontmatter("auto-b", v))

        summaries = dict((name, (version, description)) for name, version, description in list_current_summaries())

        assert sorted(summaries) == ["auto-a", "auto-b"]
        assert summaries["auto-a"][0] == 1
        assert summaries["auto-b"][0] == 2
        assert "触发词" in summaries["auto-a"][1]

    def test_list_current_summaries_is_empty_when_nothing_is_published(self, env):
        assert list_current_summaries() == []


class TestGlobalVisibility:
    def test_a_skill_written_once_is_visible_to_every_user(self, env):
        """Requirement 1: user A's learned skill is matchable by user B."""
        write_skill("auto-shared-scenario", render=lambda v: _frontmatter("auto-shared-scenario", v))

        for user in ("user-a", "user-b", "user-c"):
            storage = get_or_new_user_skill_storage(user)
            loaded = {s.name: s for s in storage.load_skills()}
            assert "auto-shared-scenario" in loaded, f"{user} cannot see the shared skill"
            skill = loaded["auto-shared-scenario"]
            assert skill.category == SkillCategory.INTEGRATION
            assert skill.enabled is True, f"{user} must get it enabled by default"

    def test_a_second_user_sees_an_update_made_after_their_first_scan(self, env):
        """The integrations tree is rescanned per load_skills call, so updates propagate."""
        write_skill("auto-evolving", render=lambda v: _frontmatter("auto-evolving", v, body="第一版"))
        user_b = get_or_new_user_skill_storage("user-b")
        first = {s.name: s for s in user_b.load_skills()}["auto-evolving"]
        assert "第一版" in first.skill_file.read_text(encoding="utf-8")

        write_skill("auto-evolving", render=lambda v: _frontmatter("auto-evolving", v, body="第二版"))
        second = {s.name: s for s in user_b.load_skills()}["auto-evolving"]

        assert "第二版" in second.skill_file.read_text(encoding="utf-8")

    def test_a_user_custom_skill_shadows_the_global_one(self, env):
        """Documented escape hatch: same-named custom skill wins (CUSTOM is scanned last)."""
        write_skill("auto-shared", render=lambda v: _frontmatter("auto-shared", v, body="全局版"))
        storage = get_or_new_user_skill_storage("user-a")
        storage.write_custom_skill("auto-shared", SKILL_MD_FILE, _frontmatter("auto-shared", 1, body="用户私有版"))

        loaded = {s.name: s for s in storage.load_skills()}
        assert loaded["auto-shared"].category == SkillCategory.CUSTOM
        assert "用户私有版" in loaded["auto-shared"].skill_file.read_text(encoding="utf-8")


class TestVersioningAndBackup:
    def test_first_write_is_version_one_with_no_backup(self, env):
        result = write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))

        assert result.version == 1
        assert result.backed_up_version is None
        assert list_backup_versions("auto-demo") == []

    def test_update_backs_up_the_previous_version(self, env):
        """Requirement 2: the old version moves to the backup store, not into the visible tree."""
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v, body="第一版内容"))
        result = write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v, body="第二版内容"))

        assert result.version == 2
        assert result.backed_up_version == 1
        assert list_backup_versions("auto-demo") == [1]

        backed_up = backup_dir("auto-demo") / "v1" / SKILL_MD_FILE
        assert backed_up.exists()
        assert "第一版内容" in backed_up.read_text(encoding="utf-8")
        assert "第二版内容" in read_current("auto-demo").content

    def test_only_the_latest_version_is_visible(self, env):
        for _ in range(4):
            write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))

        assert current_version("auto-demo") == 4
        assert list_backup_versions("auto-demo") == [1, 2, 3]
        # Exactly one visible package for the scenario.
        assert [name for name in list_current_names() if name.startswith("auto-demo")] == ["auto-demo"]
        storage = get_or_new_user_skill_storage("user-a")
        visible = [s.name for s in storage.load_skills() if s.name.startswith("auto-demo")]
        assert visible == ["auto-demo"]

    def test_render_receives_the_authoritative_version(self, env):
        """The store owns the version under the lock, so there is no read-then-write race."""
        seen: list[int] = []

        def render(version: int) -> str:
            seen.append(version)
            return _frontmatter("auto-demo", version)

        write_skill("auto-demo", render=render)
        write_skill("auto-demo", render=render)
        write_skill("auto-demo", render=render)

        assert seen == [1, 2, 3]

    def test_prune_backups_keeps_the_newest(self, env):
        for _ in range(6):
            write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))
        assert list_backup_versions("auto-demo") == [1, 2, 3, 4, 5]

        removed = prune_backups("auto-demo", keep=2)

        assert removed == [1, 2, 3]
        assert list_backup_versions("auto-demo") == [4, 5]
        # The visible skill is untouched by retention.
        assert current_version("auto-demo") == 6

    def test_prune_is_a_no_op_within_retention(self, env):
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))

        assert prune_backups("auto-demo", keep=5) == []
        assert list_backup_versions("auto-demo") == [1]

    def test_restore_backup_rolls_the_visible_skill_back(self, env):
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v, body="第一版"))
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v, body="第二版"))

        assert restore_backup("auto-demo", 1) is True

        restored = read_current("auto-demo")
        assert "第一版" in restored.content
        # Restoring is itself a version bump, so the bad version stays recoverable.
        assert restored.version == 3
        assert sorted(list_backup_versions("auto-demo")) == [1, 2]

    def test_restore_of_an_unknown_version_is_false(self, env):
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))
        assert restore_backup("auto-demo", 99) is False


class TestAtomicPublication:
    def test_no_staging_directory_survives_a_successful_write(self, env):
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))

        leftovers = [p.name for p in auto_skill_root().parent.iterdir() if p.name.startswith(".staging-auto-skill")]
        assert leftovers == []

    def test_a_failed_render_leaves_the_previous_version_intact(self, env):
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v, body="好版本"))

        def _bad_render(version: int) -> str:
            raise RuntimeError("model returned garbage")

        with pytest.raises(RuntimeError):
            write_skill("auto-demo", render=_bad_render)

        assert "好版本" in read_current("auto-demo").content
        assert current_version("auto-demo") == 1
        assert list_backup_versions("auto-demo") == []

    def test_invalid_frontmatter_is_rejected_before_publication(self, env):
        """parse_skill_file must accept the bytes, or nothing is published."""
        with pytest.raises(ValueError):
            write_skill("auto-demo", render=lambda v: "no frontmatter at all")

        assert read_current("auto-demo") is None
        assert not skill_file("auto-demo").exists()

    def test_a_frontmatter_name_mismatch_is_rejected(self, env):
        with pytest.raises(ValueError):
            write_skill("auto-demo", render=lambda v: _frontmatter("auto-other", v))

        assert read_current("auto-demo") is None

    def test_a_failed_replace_restores_the_previous_package(self, env, monkeypatch):
        """If publication fails after the old package was moved aside, it must come back."""
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v, body="原有内容"))

        # The store publishes with os.replace; shutil.move uses os.rename, so
        # patching only os.replace fails publication while sparing the backup.
        real_replace = os.replace

        def _fail_replace(src, dst, *args, **kwargs):
            if _STAGING_MARKER in str(src) and Path(dst).name == "auto-demo":
                raise OSError("simulated publication failure")
            return real_replace(src, dst, *args, **kwargs)

        monkeypatch.setattr(store_module.os, "replace", _fail_replace)

        with pytest.raises(OSError):
            write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v, body="新内容"))

        restored = read_current("auto-demo")
        assert restored is not None, "the previous package must be restored after a failed publication"
        assert "原有内容" in restored.content
        assert restored.version == 1
        # The aborted update must not leave a phantom backup behind.
        assert list_backup_versions("auto-demo") == []

    def test_concurrent_writers_serialize_and_each_version_survives(self, env):
        """Two workers learning the same scenario must not interleave into a lost update."""
        errors: list[BaseException] = []
        barrier = threading.Barrier(4)

        def worker() -> None:
            try:
                barrier.wait(timeout=10)
                write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert errors == []
        # Four serialized writers produce v1..v4: no lost update, no duplicate version.
        assert current_version("auto-demo") == 4
        assert list_backup_versions("auto-demo") == [1, 2, 3]

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not enforced on Windows")
    def test_published_files_are_sandbox_readable_not_writable(self, env):
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))

        mode = os.stat(skill_file("auto-demo")).st_mode & 0o777
        assert mode & 0o022 == 0, f"group/other write bits must be stripped, got {oct(mode)}"
        assert mode & 0o444 == 0o444


class TestLegacySweep:
    """Older releases wrote per-user ``{prefix}-{slug}-v{n}`` packages; those must not
    sit beside the new single global skill for the same scenario."""

    def _seed_legacy(self, user_id: str, name: str, *, author: str = "auto-skill") -> None:
        storage = get_or_new_user_skill_storage(user_id)
        body = _frontmatter(name, 1)
        if author != "auto-skill":
            body = body.replace('author: "auto-skill"', f'author: "{author}"')
        storage.write_custom_skill(name, SKILL_MD_FILE, body)

    def test_moves_legacy_versioned_packages_into_the_backup_store(self, env):
        self._seed_legacy("user-a", "auto-demo-v1")
        self._seed_legacy("user-a", "auto-demo-v2")
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))

        swept = sweep_legacy_user_skills("user-a", prefix="auto", slug="demo")

        assert sorted(swept) == ["auto-demo-v1", "auto-demo-v2"]
        storage = get_or_new_user_skill_storage("user-a")
        remaining = {s.name for s in storage.load_skills()}
        assert "auto-demo-v1" not in remaining
        assert "auto-demo-v2" not in remaining
        # The global skill is still visible to that user.
        assert "auto-demo" in remaining

    def test_never_sweeps_a_package_it_cannot_verify_as_auto_generated(self, env):
        self._seed_legacy("user-a", "auto-demo-v1", author="human-operator")
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))

        assert sweep_legacy_user_skills("user-a", prefix="auto", slug="demo") == []
        remaining = {s.name for s in get_or_new_user_skill_storage("user-a").load_skills()}
        assert "auto-demo-v1" in remaining

    def test_sweep_is_idempotent(self, env):
        self._seed_legacy("user-a", "auto-demo-v1")
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))

        assert sweep_legacy_user_skills("user-a", prefix="auto", slug="demo") == ["auto-demo-v1"]
        assert sweep_legacy_user_skills("user-a", prefix="auto", slug="demo") == []

    def test_sweep_leaves_other_scenarios_alone(self, env):
        self._seed_legacy("user-a", "auto-demo-v1")
        self._seed_legacy("user-a", "auto-other-v1")
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v))

        sweep_legacy_user_skills("user-a", prefix="auto", slug="demo")

        remaining = {s.name for s in get_or_new_user_skill_storage("user-a").load_skills()}
        assert "auto-other-v1" in remaining

    def test_sweep_tolerates_an_unknown_user(self, env):
        assert sweep_legacy_user_skills("never-seen", prefix="auto", slug="demo") == []


class TestLegacyMigration:
    """One-shot bulk migration of per-user versioned packages from earlier releases."""

    def _seed_legacy(self, user_id: str, name: str, *, body: str = "旧内容", author: str = "auto-skill") -> None:
        storage = get_or_new_user_skill_storage(user_id)
        content = _frontmatter(name, 1, body=body)
        if author != "auto-skill":
            content = content.replace('author: "auto-skill"', f'author: "{author}"')
        storage.write_custom_skill(name, SKILL_MD_FILE, content)

    def test_promotes_the_highest_version_under_the_stable_name(self, env):
        self._seed_legacy("user-a", "auto-demo-v1", body="第一版")
        self._seed_legacy("user-a", "auto-demo-v2", body="第二版")
        self._seed_legacy("user-a", "auto-demo-v3", body="第三版")

        report = migrate_legacy_user_skills("user-a", prefix="auto")

        assert report["promoted"] == ["auto-demo"]
        assert sorted(report["archived"]) == ["auto-demo-v1", "auto-demo-v2", "auto-demo-v3"]
        promoted = read_current("auto-demo")
        assert promoted is not None
        assert "第三版" in promoted.content, "the highest version must win"
        assert "第一版" not in promoted.content
        assert promoted.version == 1

    def test_the_promoted_package_is_visible_to_every_user(self, env):
        self._seed_legacy("user-a", "auto-demo-v1")

        migrate_legacy_user_skills("user-a", prefix="auto")

        for user in ("user-a", "user-b"):
            names = {s.name for s in get_or_new_user_skill_storage(user).load_skills()}
            assert "auto-demo" in names, f"{user} must see the promoted skill"
            assert "auto-demo-v1" not in names

    def test_never_clobbers_an_existing_global_package(self, env):
        """A global package post-dates the migration boundary, so it is newer by definition."""
        write_skill("auto-demo", render=lambda v: _frontmatter("auto-demo", v, body="全局最新版"))
        self._seed_legacy("user-a", "auto-demo-v1", body="陈旧的本地版")

        report = migrate_legacy_user_skills("user-a", prefix="auto")

        assert report["promoted"] == []
        assert report["archived"] == ["auto-demo-v1"]
        assert "全局最新版" in read_current("auto-demo").content
        assert read_current("auto-demo").version == 1

    def test_archives_every_legacy_version_for_recovery(self, env):
        self._seed_legacy("user-a", "auto-demo-v1")
        self._seed_legacy("user-a", "auto-demo-v2")

        migrate_legacy_user_skills("user-a", prefix="auto")

        archives = sorted(p.name for p in backup_dir("auto-demo").iterdir() if p.is_dir())
        assert archives == ["legacy-user-a-v1", "legacy-user-a-v2"]
        for archive in archives:
            assert (backup_dir("auto-demo") / archive / "auto-demo" / SKILL_MD_FILE).is_file() or (backup_dir("auto-demo") / archive / SKILL_MD_FILE).is_file()

    def test_separates_distinct_scenarios(self, env):
        self._seed_legacy("user-a", "auto-demo-v1")
        self._seed_legacy("user-a", "auto-other-scenario-v1")
        self._seed_legacy("user-a", "auto-other-scenario-v2")

        report = migrate_legacy_user_skills("user-a", prefix="auto")

        assert sorted(report["promoted"]) == ["auto-demo", "auto-other-scenario"]
        assert read_current("auto-demo") is not None
        assert read_current("auto-other-scenario") is not None

    def test_skips_packages_not_marked_as_auto_generated(self, env):
        self._seed_legacy("user-a", "auto-demo-v1", author="human-operator")

        report = migrate_legacy_user_skills("user-a", prefix="auto")

        assert report["promoted"] == []
        assert report["archived"] == []
        assert report["skipped"] == ["auto-demo-v1"]
        names = {s.name for s in get_or_new_user_skill_storage("user-a").load_skills()}
        assert "auto-demo-v1" in names, "an operator's skill must survive"

    def test_leaves_unrelated_custom_skills_alone(self, env):
        storage = get_or_new_user_skill_storage("user-a")
        storage.write_custom_skill("my-handwritten-skill", SKILL_MD_FILE, _frontmatter("my-handwritten-skill", 1))
        self._seed_legacy("user-a", "auto-demo-v1")

        migrate_legacy_user_skills("user-a", prefix="auto")

        names = {s.name for s in storage.load_skills()}
        assert "my-handwritten-skill" in names
        assert "auto-demo-v1" not in names

    def test_is_idempotent(self, env):
        self._seed_legacy("user-a", "auto-demo-v1")

        first = migrate_legacy_user_skills("user-a", prefix="auto")
        second = migrate_legacy_user_skills("user-a", prefix="auto")

        assert first["promoted"] == ["auto-demo"]
        assert second == {"promoted": [], "archived": [], "skipped": []}

    def test_tolerates_an_unknown_user(self, env):
        report = migrate_legacy_user_skills("never-seen", prefix="auto")
        assert report == {"promoted": [], "archived": [], "skipped": []}

    def test_the_promoted_package_keeps_its_description(self, env):
        """The description drives matching, so migration must not drop it."""
        self._seed_legacy("user-a", "auto-demo-v1")

        migrate_legacy_user_skills("user-a", prefix="auto")

        parts, error = split_skill_markdown(read_current("auto-demo").content)
        assert error is None
        assert "触发词" in parts.metadata["description"]
        assert parts.metadata["name"] == "auto-demo"
        assert parts.metadata["metadata"]["migrated-from"] == "legacy v1"


class TestModuleSurface:
    def test_the_package_exports_the_store_api(self):
        for symbol in ("auto_skill_root", "read_current", "write_skill", "list_backup_versions", "prune_backups", "restore_backup", "sweep_legacy_user_skills"):
            assert hasattr(auto_package, symbol), symbol

    def test_store_module_is_importable_without_a_runtime_home(self, monkeypatch, tmp_path):
        """Path helpers resolve lazily so importing never touches the filesystem."""
        monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "other"))
        monkeypatch.setattr("deerflow.config.paths._paths", None)
        assert store_module.PROVIDER_DIR_NAME == "auto-skill"
