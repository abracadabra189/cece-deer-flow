"""describe_skill — deferred skill metadata retrieval at runtime.

Builds the ``describe_skill`` tool as a closure over a :class:`SkillCatalog`.
The tool returns structured metadata (description, allowed tools, file location)
so the LLM can decide whether to ``read_file`` the full SKILL.md.

Shares query forms, ``Command`` + ``ToolMessage`` return shape, and fail-safe
degradation with ``build_tool_search_tool`` from ``tool_search.py``. Skill
queries intentionally rank literal intent terms rather than matching regexes.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId
from langgraph.types import Command

if TYPE_CHECKING:
    from langchain.tools import BaseTool

from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.skills.catalog import SkillCatalog
from deerflow.skills.types import SkillCategory

logger = logging.getLogger(__name__)

#: Learned skills rendered in the priority ``<auto_skill_index>`` block. Bounded
#: so a large store cannot grow the prompt without limit; anything beyond the cap
#: stays reachable through ``describe_skill`` and the ordinary ``<skill_index>``.
AUTO_INDEX_MAX_ENTRIES = 20
#: Per-entry description bound in that block.
AUTO_INDEX_DESCRIPTION_BUDGET = 200


# ── Setup ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SkillSearchSetup:
    """Result of assembling skill search for one agent build.

    Mirrors ``DeferredToolSetup`` from ``tool_search.py``.

    - **Empty** ``(None, frozenset())``: no skills available or skill search
      disabled.  The agent falls back to the legacy full-metadata prompt.
    - **Populated**: ``describe_skill_tool`` is appended to the agent's tools,
      ``skill_names`` are rendered in ``<skill_index>`` instead of full metadata.
    """

    describe_skill_tool: BaseTool | None
    skill_names: frozenset[str]


def build_describe_skill_tool(
    catalog: SkillCatalog,
    *,
    container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
    skill_authorization=None,
) -> BaseTool:
    """Build the ``describe_skill`` tool as a closure over *catalog*.

    The returned tool carries both a sync function and a coroutine: sync
    invocation (``invoke``, e.g. tests and sync chains) gates matches with the
    provider's synchronous ``authorize()``, while async invocation (``ainvoke``,
    the path async agent execution takes) awaits ``aauthorize()`` on the event
    loop — loop-affine custom providers must never see the sync API. No graph
    state mutation is needed (unlike ``tool_search`` which promotes deferred
    tools).

    *skill_authorization* (a ``ResolvedSkillAuthorization`` from
    ``deerflow.authz.skill_filter``) gates describe results on the action-scoped
    ``skill:activate`` decision: the catalog holds the Layer 1 visibility set
    (action-agnostic), so an action-aware provider may list a skill the model
    must still not be able to load. Denied skills are omitted from the output
    (indistinguishable from a non-match, so the reason is not leaked) with the
    provider's configured fail-closed / fail-open policy on errors. ``None``
    (authorization disabled) describes everything in the catalog.
    """

    def _log_omissions(omitted: int) -> None:
        if omitted:
            logger.info("describe_skill: omitted %d skill(s) denied by the skill:activate policy", omitted)

    def _filter_activation_denied(matched: list) -> list:
        if skill_authorization is None:
            return matched
        from deerflow.authz.skill_filter import skill_activation_allowed

        kept = [s for s in matched if skill_activation_allowed(skill_authorization, s.name)]
        _log_omissions(len(matched) - len(kept))
        return kept

    async def _afilter_activation_denied(matched: list) -> list:
        if skill_authorization is None:
            return matched
        from deerflow.authz.skill_filter import skill_activation_allowed_async

        kept = []
        for s in matched:
            if await skill_activation_allowed_async(skill_authorization, s.name):
                kept.append(s)
        _log_omissions(len(matched) - len(kept))
        return kept

    def _command(matched: list, name: str, tool_call_id: str) -> Command:
        if not matched:
            content = f"No skills matched: {name}"
        else:
            content = _render_skill_metadata(matched, container_base_path)
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=content,
                        tool_call_id=tool_call_id,
                        name="describe_skill",
                    )
                ],
            }
        )

    def describe_skill(
        name: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        """Fetch usage metadata for installed skills so you can decide whether to load them.

        Skills appear by name in <skill_index> in the system prompt.  Until
        fetched, only the name is known.  This tool matches a query against
        installed skills and returns their full metadata — description, allowed
        tools, and file location — so you can decide whether to load the
        SKILL.md via read_file.

        Query forms:
          - "select:data-analysis,deep-research" -- fetch these exact skills (no cap)
          - "chart visualization" -- keyword search, best matches (up to 5)
          - "+podcast gen" -- require "podcast" in the name, rank by remaining terms (up to 5)
        """
        return _command(_filter_activation_denied(catalog.search(name)), name, tool_call_id)

    async def adescribe_skill(
        name: str,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> Command:
        return _command(await _afilter_activation_denied(catalog.search(name)), name, tool_call_id)

    from langchain_core.tools import StructuredTool

    return StructuredTool.from_function(
        func=describe_skill,
        coroutine=adescribe_skill,
        name="describe_skill",
        description=describe_skill.__doc__,
        parse_docstring=False,
    )


def build_skill_search_setup(
    skills: list,
    *,
    enabled: bool,
    container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
    skill_authorization=None,
) -> SkillSearchSetup:
    """Build the skill search setup from a filtered skill list.

    Mirrors ``build_deferred_tool_setup`` from ``tool_search.py``.

    Returns an empty setup when *enabled* is ``False`` or *skills* is empty.
    *skill_authorization* is forwarded to the describe tool (see
    ``build_describe_skill_tool``).
    """
    if not enabled or not skills:
        return SkillSearchSetup(None, frozenset())

    catalog = SkillCatalog(tuple(skills))
    return SkillSearchSetup(
        describe_skill_tool=build_describe_skill_tool(
            catalog,
            container_base_path=container_base_path,
            skill_authorization=skill_authorization,
        ),
        skill_names=catalog.names,
    )


# ── Rendering ────────────────────────────────────────────────────────────────


def _render_skill_metadata(skills: list, container_base_path: str) -> str:
    """Render structured metadata for a list of matched skills."""
    blocks: list[str] = []
    for s in skills:
        mutability = "[custom, editable]" if s.category == SkillCategory.CUSTOM else "[built-in]"
        # allowed-tools is compatibility metadata copied from other agent
        # frameworks; it never filters, grants, or denies tools in DeerFlow.
        # "(not declared)" only means the field was omitted; "(empty
        # declaration)" only means it was declared empty. Agent
        # assembly/execution authorization owns the actual permission ceiling.
        tools_line = "(not declared)" if s.allowed_tools is None else (", ".join(s.allowed_tools) or "(empty declaration)")
        location = s.get_container_file_path(container_base_path)
        # name/description/allowed-tools come from untrusted ``.skill`` frontmatter;
        # escape so a value cannot forge a framework tag in the describe_skill output.
        name = html.escape(s.name, quote=False)
        description = html.escape(s.description, quote=False)
        tools = html.escape(tools_line, quote=False)
        loc = html.escape(location, quote=False)
        blocks.append(f"## Skill: {name}\n- Description: {description} {mutability}\n- Allowed tools (compatibility metadata, not enforced): {tools}\n- Location: {loc}")
    return "\n\n".join(blocks)


# ── Prompt rendering ─────────────────────────────────────────────────────────


def _render_auto_skill_index(entries: Iterable[tuple[str, str]]) -> str:
    """Render bounded ``- name: description`` lines for the learned skills.

    Both values come from a generated ``SKILL.md``'s frontmatter, so they are
    escaped like every other skill metadata render site: a description must not be
    able to close ``<auto_skill_index>`` and forge a framework block.
    """
    materialized = tuple(entries)
    lines: list[str] = []
    for name, description in materialized[:AUTO_INDEX_MAX_ENTRIES]:
        esc_name = html.escape(name, quote=False)
        clipped = " ".join((description or "").split())
        if len(clipped) > AUTO_INDEX_DESCRIPTION_BUDGET:
            clipped = clipped[:AUTO_INDEX_DESCRIPTION_BUDGET] + "…"
        lines.append(f"- {esc_name}: {html.escape(clipped, quote=False)}" if clipped else f"- {esc_name}")
    if len(materialized) > AUTO_INDEX_MAX_ENTRIES:
        lines.append(f"- … {len(materialized) - AUTO_INDEX_MAX_ENTRIES} more (use describe_skill to find them)")
    return "\n".join(lines)


def get_skill_index_prompt_section(
    *,
    skill_names: frozenset[str] = frozenset(),
    container_base_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
    skill_evolution_section: str = "",
    auto_skill_entries: Iterable[tuple[str, str]] = (),
) -> str:
    """Generate ``<skill_system>`` with a name-only ``<skill_index>``.

    Mirrors ``get_deferred_tools_prompt_section`` from ``tool_search.py``.
    The agent knows what exists and can use ``describe_skill`` to load metadata.

    *auto_skill_entries* are the platform-learned skills in this build as
    ``(name, description)`` pairs. They are rendered first, in their own
    ``<auto_skill_index>`` with descriptions, and the discovery instructions tell
    the model to check them before deciding whether any other skill is needed.
    Descriptions matter here: a learned skill's name is an English slug, so a
    request in another language would have nothing to match on.

    Returns empty string when there are no skills.
    """
    auto_entries = tuple(auto_skill_entries or ())
    auto_names = {name for name, _ in auto_entries}
    other_names = frozenset(name for name in skill_names if name not in auto_names)
    if not auto_entries and not other_names:
        return ""

    evolution = f"\n{skill_evolution_section}" if skill_evolution_section else ""

    verification_order = ""
    auto_block = ""
    if auto_entries:
        verification_order = """
**Skill Verification Order — check the learned skills first:**
1. <auto_skill_index> lists scenarios this platform already learned from real runs. If the current request belongs to one of them, call describe_skill(name), then read_file the returned location and follow that skill.
2. Only then decide whether another skill is still needed. Load one only when the matched learned skill does not cover this request — never load extra skills "just in case".
3. When nothing in <auto_skill_index> matches, use the ordinary discovery flow below.
"""
        auto_block = f"""
<auto_skill_index>
{_render_auto_skill_index(auto_entries)}
</auto_skill_index>
"""

    names = ", ".join(html.escape(name, quote=False) for name in sorted(other_names))
    skill_index = (
        f"""
<skill_index>
{names}
</skill_index>
"""
        if other_names
        else ""
    )

    return f"""<skill_system>
You have access to skills that provide optimized workflows for specific tasks.
{verification_order}
**Skill Discovery:**
1. Check <skill_index> for a skill name that matches your task
2. Call describe_skill(name) to fetch its description and capabilities
3. If the skill matches, call read_file on the returned location to load full instructions
4. Follow the skill's instructions precisely

**Explicit Slash Skill Activation:**
- If the user starts a request with `/<skill-name>`, that skill was explicitly requested.
- The runtime injects the activated skill content; do not call `read_file` for that SKILL.md again unless the injected skill references supporting resources you need.

**Allowed tools:** A skill's `allowed-tools` metadata is compatibility information for other agent frameworks. It never restricts or grants tools here; your tools are controlled by DeerFlow's Agent configuration and authorization.
{evolution}
{auto_block}{skill_index}
Skills are located at: {container_base_path}
</skill_system>"""
