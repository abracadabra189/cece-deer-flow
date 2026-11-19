"""Distil one completed run into the facts an auto-generated skill needs.

Extraction is pure in-memory message walking so it is cheap enough to run
inside ``after_agent`` before handing the payload to the background queue. It
reuses the platform's existing message helpers rather than re-deriving
provenance rules:

- the query comes from the latest *genuine* user message, preferring the
  server-owned ``original_user_content`` copy so sanitization wrappers and
  upload preambles do not become part of the learned scenario;
- tool calls are correlated with their results by ``tool_call_id`` in two
  passes, the same shape ``extract_skills`` uses;
- matched skills come from the durable ``skill_context`` channel plus the
  ``skill_usage`` / ``skill_usages`` stamps, so both automatic loads and slash
  activations are captured.

Every field is bounded. An unbounded trajectory would make the synthesis prompt
grow with the run, which is exactly the cost this feature must not add.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from deerflow.agents.middlewares.message_utils import latest_genuine_user_message
from deerflow.agents.middlewares.model_response import has_tool_call_intent, has_visible_content
from deerflow.agents.middlewares.skill_usage import SKILL_USAGE_KEY, SKILL_USAGES_KEY
from deerflow.utils.messages import get_original_user_content_text, message_content_to_text

logger = logging.getLogger(__name__)

#: Character budget for the user query inside a rendered trajectory.
_QUERY_CHAR_BUDGET = 2000
#: Character budget for the final answer inside a rendered trajectory.
_ANSWER_CHAR_BUDGET = 6000
#: Character budget for one tool call's arguments.
_ARGS_CHAR_BUDGET = 800
#: Most recent tool steps retained when a run made many calls.
_MAX_TOOL_STEPS = 40
#: Most recent todo entries retained.
_MAX_TODOS = 30

_TRUNCATION_MARKER = "\n…[truncated]"


@dataclass(frozen=True, slots=True)
class ToolStep:
    """One tool call paired with its result."""

    tool_name: str
    args_summary: str
    result_summary: str
    status: str


@dataclass(frozen=True, slots=True)
class RunTrajectory:
    """A completed run reduced to what a reusable skill needs to describe."""

    query: str
    skill_names: tuple[str, ...]
    tool_steps: tuple[ToolStep, ...]
    final_answer: str
    todo_texts: tuple[str, ...]

    @property
    def successful_tool_calls(self) -> int:
        """Tool steps whose result did not report an error status."""
        return sum(1 for step in self.tool_steps if step.status != "error")


def _truncate(text: str, limit: int) -> str:
    """Bound ``text`` to ``limit`` characters, marking the cut."""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + _TRUNCATION_MARKER


def _compact_json(value: Any, limit: int) -> str:
    """Serialize tool arguments compactly and bound the result."""
    if value is None:
        return ""
    try:
        rendered = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError):
        rendered = repr(value)
    return _truncate(rendered, limit)


def _resolve_query(messages: list[Any]) -> str:
    """Return the user request this run answered, without framework wrappers."""
    message = latest_genuine_user_message(messages)
    if message is None:
        return ""
    additional_kwargs = getattr(message, "additional_kwargs", None)
    original = get_original_user_content_text(message.content, additional_kwargs if isinstance(additional_kwargs, dict) else None)
    text = original or message_content_to_text(message.content)
    return _truncate(text.strip(), _QUERY_CHAR_BUDGET)


def _resolve_final_answer(messages: list[Any]) -> str:
    """Return the last assistant turn that produced user-visible text."""
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        if has_tool_call_intent(message) or not has_visible_content(message):
            continue
        return _truncate(message_content_to_text(message.content).strip(), _ANSWER_CHAR_BUDGET)
    return ""


def _extract_tool_steps(messages: list[Any], *, max_tool_result_chars: int) -> tuple[ToolStep, ...]:
    """Correlate tool calls with their results, keeping the most recent steps."""
    calls_by_id: dict[str, tuple[str, Any]] = {}
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for tool_call in getattr(message, "tool_calls", None) or []:
            if not isinstance(tool_call, dict):
                continue
            name = tool_call.get("name")
            call_id = tool_call.get("id")
            if not isinstance(name, str) or not name or not isinstance(call_id, str) or not call_id:
                continue
            calls_by_id[call_id] = (name, tool_call.get("args"))

    steps: list[ToolStep] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        call_id = getattr(message, "tool_call_id", None)
        if not isinstance(call_id, str) or call_id not in calls_by_id:
            continue
        name, args = calls_by_id[call_id]
        status = getattr(message, "status", None) or "success"
        steps.append(
            ToolStep(
                tool_name=name,
                args_summary=_compact_json(args, _ARGS_CHAR_BUDGET),
                result_summary=_truncate(message_content_to_text(message.content).strip(), max_tool_result_chars),
                status=str(status),
            )
        )

    if len(steps) > _MAX_TOOL_STEPS:
        steps = steps[-_MAX_TOOL_STEPS:]
    return tuple(steps)


def _extract_skill_names(state: Any, messages: list[Any]) -> tuple[str, ...]:
    """Collect every skill this run activated, from state and message stamps."""
    names: list[str] = []
    seen: set[str] = set()

    def _add(candidate: Any) -> None:
        if isinstance(candidate, str):
            name = candidate.strip()
        elif isinstance(candidate, dict):
            raw = candidate.get("name")
            name = raw.strip() if isinstance(raw, str) else ""
        else:
            return
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    for entry in (state.get("skill_context") or []) if hasattr(state, "get") else []:
        _add(entry)

    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        additional_kwargs = getattr(message, "additional_kwargs", None)
        if not isinstance(additional_kwargs, dict):
            continue
        _add(additional_kwargs.get(SKILL_USAGE_KEY))
        usages = additional_kwargs.get(SKILL_USAGES_KEY)
        if isinstance(usages, list):
            for usage in usages:
                _add(usage)

    return tuple(names)


def _extract_todo_texts(state: Any) -> tuple[str, ...]:
    """Return plan-mode todo contents, most recent state first."""
    if not hasattr(state, "get"):
        return ()
    todos = state.get("todos")
    if not isinstance(todos, list):
        return ()
    texts: list[str] = []
    for todo in todos[-_MAX_TODOS:]:
        if isinstance(todo, dict):
            content = todo.get("content")
            if isinstance(content, str) and content.strip():
                texts.append(content.strip())
        elif isinstance(todo, str) and todo.strip():
            texts.append(todo.strip())
    return tuple(texts)


def extract_run_trajectory(state: Any, *, max_tool_result_chars: int = 2000) -> RunTrajectory | None:
    """Build a :class:`RunTrajectory` from graph state, or ``None`` when unusable.

    Returns ``None`` — never raises — when there is no genuine user query or no
    visible final answer, because a skill synthesized from either absence would
    describe nothing reproducible.
    """
    try:
        messages = list(state.get("messages") or []) if hasattr(state, "get") else []
        if not messages:
            return None
        query = _resolve_query(messages)
        if not query:
            return None
        final_answer = _resolve_final_answer(messages)
        if not final_answer:
            return None
        return RunTrajectory(
            query=query,
            skill_names=_extract_skill_names(state, messages),
            tool_steps=_extract_tool_steps(messages, max_tool_result_chars=max_tool_result_chars),
            final_answer=final_answer,
            todo_texts=_extract_todo_texts(state),
        )
    except Exception:
        # Best effort by contract: a malformed checkpoint must never fail a run.
        logger.warning("auto-skill trajectory extraction failed; skipping synthesis", exc_info=True)
        return None


def render_trajectory(trajectory: RunTrajectory, *, max_chars: int) -> str:
    """Render a trajectory as the synthesis prompt's evidence section.

    The total is bounded by ``max_chars``; when the render overflows, the oldest
    tool steps are dropped first so the query and the final answer — the two
    facts that define the scenario and its expected output — always survive.
    """
    steps = list(trajectory.tool_steps)

    def _render(included_steps: list[ToolStep]) -> str:
        sections: list[str] = []
        sections.append(f"## 用户原始请求\n{trajectory.query}")
        if trajectory.skill_names:
            sections.append("## 本次命中的技能\n" + "\n".join(f"- {name}" for name in trajectory.skill_names))
        else:
            sections.append("## 本次命中的技能\n（无：本次未匹配到已有技能）")
        if trajectory.todo_texts:
            sections.append("## 执行计划\n" + "\n".join(f"{index}. {text}" for index, text in enumerate(trajectory.todo_texts, start=1)))
        if included_steps:
            rendered_steps: list[str] = []
            for index, step in enumerate(included_steps, start=1):
                rendered_steps.append(f"### 步骤 {index}: {step.tool_name}（状态: {step.status}）\n入参: {step.args_summary or '（无）'}\n返回摘要: {step.result_summary or '（空）'}")
            sections.append("## 取数与执行轨迹\n" + "\n\n".join(rendered_steps))
        else:
            sections.append("## 取数与执行轨迹\n（无工具调用）")
        sections.append(f"## 最终回答\n{trajectory.final_answer}")
        return "\n\n".join(sections)

    rendered = _render(steps)
    while len(rendered) > max_chars and steps:
        # Drop from the front: the earliest calls are usually exploratory.
        steps.pop(0)
        rendered = _render(steps)

    if len(rendered) > max_chars:
        rendered = _truncate(rendered, max_chars)
    return rendered
