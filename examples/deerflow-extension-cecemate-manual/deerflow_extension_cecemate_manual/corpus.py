"""Validated immutable startup snapshot of packaged manual evidence."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType


def _text(value, name, maximum=100000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Invalid corpus {name}")
    return value


def _terms(value, name):
    if not isinstance(value, list) or len(value) > 1000:
        raise ValueError(f"Invalid corpus {name}")
    return tuple(_text(v, name, 1000) for v in value)


@dataclass(frozen=True)
class Entry:
    id: str
    module: str
    title: str
    aliases: tuple[str, ...]
    scenarios: tuple[str, ...]
    status: str
    chapter: str
    content: str
    source_lines: tuple[int, int]


@dataclass(frozen=True)
class Manifest:
    title: str
    version: str
    date: str
    source_sha256: str
    entry_count: int


@dataclass(frozen=True)
class Corpus:
    entries: tuple[Entry, ...]
    manifest: Manifest
    aliases: Mapping[str, tuple[str, ...]]

    @classmethod
    def load(cls):
        root = files("deerflow_extension_cecemate_manual").joinpath("data")
        raw = root.joinpath("entries.json").read_bytes()
        manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
        if "entries_sha256" in manifest and manifest["entries_sha256"] != hashlib.sha256(raw).hexdigest():
            raise ValueError("Corpus entries checksum mismatch")
        return cls.from_data(json.loads(raw), manifest, json.loads(root.joinpath("aliases.json").read_text(encoding="utf-8")))

    @classmethod
    def from_data(cls, entries, manifest, aliases):
        if not isinstance(entries, list) or not entries or len(entries) > 10000 or not isinstance(manifest, dict) or not isinstance(aliases, dict):
            raise ValueError("Invalid corpus envelope")
        try:
            meta = Manifest(
                *(_text(manifest[k], k, limit) for k, limit in [("title", 200), ("version", 50), ("date", 50), ("source_sha256", 64)]), entry_count=manifest["entry_count"]
            )
            if not re.fullmatch(r"[a-fA-F0-9]{64}", meta.source_sha256) or type(meta.entry_count) is not int or meta.entry_count != len(entries):
                raise ValueError("Invalid corpus manifest checksum or count")
            result = []
            ids = set()
            for row in entries:
                if not isinstance(row, dict):
                    raise ValueError("Invalid corpus entry")
                values = {k: _text(row[k], k, limit) for k, limit in [("id", 256), ("module", 300), ("title", 300), ("chapter", 1500), ("content", 100000)]}
                lines = row["source_lines"]
                if not isinstance(lines, list) or len(lines) != 2 or any(type(n) is not int or n < 1 for n in lines) or lines[0] > lines[1]:
                    raise ValueError("Invalid corpus source_lines")
                if row["status"] not in ("active", "retired") or values["id"] in ids:
                    raise ValueError("Invalid corpus status or duplicate ID")
                ids.add(values["id"])
                result.append(
                    Entry(**values, aliases=_terms(row["aliases"], "aliases"), scenarios=_terms(row["scenarios"], "scenarios"), status=row["status"], source_lines=tuple(lines))
                )
            expansions = {_text(k, "alias", 1000): _terms(v, "alias terms") for k, v in aliases.items()}
            return cls(tuple(result), meta, MappingProxyType(expansions))
        except (KeyError, TypeError) as exc:
            raise ValueError("Missing or invalid corpus field") from exc
