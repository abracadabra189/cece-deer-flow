"""Output filename helpers for CeCeMate artifacts."""

from __future__ import annotations

import re

WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def output_stem(meta: dict) -> str:
    """Use the model-provided title as the human-readable filename."""
    raw = str(meta.get("filename") or meta.get("title") or "文档")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", raw).strip(" .")
    name = re.sub(r"\s+", " ", name)
    if not name or name.upper() in WINDOWS_RESERVED:
        name = "文档"
    return name[:80]
