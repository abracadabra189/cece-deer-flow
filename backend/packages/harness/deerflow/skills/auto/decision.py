"""Deterministic verification of the synthesizer model's ``update`` claim.

An auto-skill is shared by every user, so "improve the existing skill" is the one
decision that must not be taken on the model's word alone. Left unverified, a run
that simply re-asked the same question about a different company would rewrite the
package with a new example, churn a version, spend a moderation scan and push the
previous version into the backup store — for zero new knowledge.

The rule this module enforces:

- an ``update`` must name at least one **substantive** reason
  (:data:`SUBSTANTIVE_UPDATE_REASONS`) — a tool the skill does not define, a
  different data-fetch/reasoning flow, an improved answer format, an extra answer
  dimension the user asked for, a corrected definition, or a new failure fallback;
- reasons that only describe *this run's data* (:data:`NON_SUBSTANTIVE_UPDATE_REASONS`
  — a different example, different values, prettier wording) never justify a
  rewrite on their own, and the decision degrades to ``no_change``;
- ``new_tool`` additionally needs evidence: :func:`find_novel_tools` reports the
  tools this run called that do not appear anywhere in the matched skill's text.
  A ``new_tool`` claim with no novel tool is dropped, because the platform can
  check that one itself and the model cannot.

Unknown reason tokens are dropped rather than trusted: the vocabulary is the
contract, and a free-form string is not evidence.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Reasons that carry reusable knowledge beyond this run's data.
SUBSTANTIVE_UPDATE_REASONS: tuple[str, ...] = (
    "new_tool",
    "new_flow",
    "answer_format",
    "new_dimension",
    "correction",
    "fallback",
)
#: Reasons that describe only this run's subject/values/wording.
NON_SUBSTANTIVE_UPDATE_REASONS: tuple[str, ...] = (
    "examples_only",
    "data_values",
    "wording",
)

_SUBSTANTIVE = frozenset(SUBSTANTIVE_UPDATE_REASONS)
_NON_SUBSTANTIVE = frozenset(NON_SUBSTANTIVE_UPDATE_REASONS)
_KNOWN = _SUBSTANTIVE | _NON_SUBSTANTIVE
_REASON_SPLIT_RE = re.compile(r"[,，;；、\s]+")


@dataclass(frozen=True, slots=True)
class VerifiedUpdate:
    """Outcome of verifying one declared ``update``."""

    #: ``"update"`` when a substantive reason survived, else ``"no_change"``.
    decision: str
    #: Surviving substantive reasons, in declaration order.
    reasons: tuple[str, ...]
    #: Reasons dropped for being unknown, non-substantive, or unevidenced.
    dropped: tuple[str, ...]
    #: Human-readable explanation for the log line; empty when nothing changed.
    note: str

    @property
    def is_update(self) -> bool:
        return self.decision == "update"


def normalize_reasons(raw: object) -> tuple[str, ...]:
    """Flatten and dedupe a model-declared reason list, keeping unknown tokens.

    Unknown tokens are preserved here so :func:`verify_update` can report them as
    dropped evidence rather than silently ignoring a vocabulary drift.
    """
    if isinstance(raw, str):
        candidates: list[str] = [part for part in _REASON_SPLIT_RE.split(raw.strip())]
    elif isinstance(raw, (list, tuple, set, frozenset)):
        candidates = [item.strip() for item in raw if isinstance(item, str)]
    else:
        return ()

    reasons: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        token = candidate.strip().lower().replace(" ", "_")
        if not token or token in seen:
            continue
        seen.add(token)
        reasons.append(token)
    return tuple(reasons)


def find_novel_tools(tool_names: Iterable[str], existing_contents: Iterable[str]) -> tuple[str, ...]:
    """Tools this run called that the matched skill's text never mentions.

    The synthesis prompt requires tool names to be reproduced verbatim, so a plain
    substring check over the published body is the same join the model is asked to
    make — and unlike the model's claim it cannot be invented. With no matched
    skill there is nothing to compare against, so every tool counts as novel.
    """
    contents = tuple(content for content in existing_contents if isinstance(content, str) and content)
    novel: list[str] = []
    seen: set[str] = set()
    for name in tool_names:
        if not isinstance(name, str):
            continue
        tool = name.strip()
        if not tool or tool in seen:
            continue
        seen.add(tool)
        if not any(tool in content for content in contents):
            novel.append(tool)
    return tuple(novel)


def verify_update(reasons: Iterable[str], *, novel_tools: Iterable[str] = (), strict: bool = True) -> VerifiedUpdate:
    """Verify a declared ``update`` against the reason vocabulary and the evidence.

    ``strict`` is set when the model itself declared ``update``: with no reasons at
    all there is no evidence of new knowledge, so the decision degrades. A
    ``create`` that the store reconciles to an update (the scenario already exists
    under a stable name) passes ``strict=False`` — the model asserted an uncovered
    scenario rather than an improvement, and the create vocabulary carries no
    reasons, so an absent list is not a failed check. Reasons that *are* declared
    are verified either way.
    """
    declared = tuple(reasons)
    novel = tuple(novel_tools)
    kept: list[str] = []
    dropped: list[str] = []

    for reason in declared:
        if reason not in _KNOWN:
            dropped.append(reason)
            continue
        if reason == "new_tool" and not novel:
            # The platform checked: every tool this run called is already in the
            # skill's text, so there is no new tool to record.
            dropped.append(reason)
            continue
        if reason in _SUBSTANTIVE:
            kept.append(reason)
        else:
            dropped.append(reason)

    if kept:
        return VerifiedUpdate(decision="update", reasons=tuple(kept), dropped=tuple(dropped), note="")

    if not declared and not strict:
        return VerifiedUpdate(decision="update", reasons=(), dropped=(), note="no reasons declared for a reconciled create")

    if not declared:
        return VerifiedUpdate(decision="no_change", reasons=(), dropped=(), note="update declared without any reason")

    if dropped and not any(reason in _NON_SUBSTANTIVE for reason in dropped):
        note = f"update reasons lacked evidence: {', '.join(dropped)}"
    else:
        note = f"only this run's data changed ({', '.join(dropped)})"
    return VerifiedUpdate(decision="no_change", reasons=(), dropped=tuple(dropped), note=note)
