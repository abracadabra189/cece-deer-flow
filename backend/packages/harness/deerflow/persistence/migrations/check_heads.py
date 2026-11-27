"""Verify that DeerFlow's Alembic revision graph has one deployable head."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory

_MIGRATIONS_DIR = Path(__file__).resolve().parent


def get_migration_heads() -> tuple[str, ...]:
    """Return the graph heads declared by the checked-in revision files."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return tuple(ScriptDirectory.from_config(config).get_heads())


def main() -> int:
    """Exit nonzero when the migration graph would make Gateway startup fail."""
    heads = get_migration_heads()
    if len(heads) == 1:
        print(f"Alembic migration head: {heads[0]}")
        return 0

    rendered = ", ".join(heads) if heads else "(none)"
    print(
        f"Expected exactly one Alembic migration head, found {len(heads)}: {rendered}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
