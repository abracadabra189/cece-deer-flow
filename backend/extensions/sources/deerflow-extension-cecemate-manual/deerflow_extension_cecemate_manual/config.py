"""Strict, bounded operator configuration; no request-controlled paths."""

from collections.abc import Mapping
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Settings:
    max_hits: int = 6
    max_total_chars: int = 4800
    max_excerpt_chars: int = 800
    max_query_chars: int = 512

    def __post_init__(self):
        limits = {"max_hits": 6, "max_total_chars": 4800, "max_excerpt_chars": 800, "max_query_chars": 2048}
        for name, upper in limits.items():
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError(f"{name} must be an integer between 1 and {upper}")

    @classmethod
    def from_config(cls, config):
        if not isinstance(config, Mapping) or set(config) - {f.name for f in fields(cls)}:
            raise ValueError("Unknown or invalid cecemate-manual configuration")
        return cls(**config)
