"""Shared helper for one-shot, non-graph LLM text requests.

Several Gateway routes (input polishing, follow-up suggestions, and title-style
rewrites) do the same thing: build a chat model from config, attach Langfuse
trace metadata, invoke it once with a system + user message pair, and pull the
plain text back out of the response. Centralizing that sequence here keeps the
tracing-metadata fields and invocation shape from drifting between routers — a
fix to one (e.g. a new Langfuse field) now applies to all callers instead of
silently regressing in whichever copy was forgotten.

Response-text *cleaning* (think-block / code-fence stripping, JSON parsing) is
intentionally left to each caller because their post-processing differs; this
helper stops at the extracted raw text.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.tracing import inject_langfuse_metadata
from deerflow.utils.assembly_io import run_assembly
from deerflow.utils.llm_text import extract_response_text


def new_isolated_http_client() -> httpx.AsyncClient:
    """A caller-owned async HTTP client for model calls made off the Gateway loop.

    langchain-openai caches its default ``httpx.AsyncClient`` per process, keyed only
    on ``(base_url, timeout, socket_options)``. A model call made on a short-lived
    loop (the auto-skill batch worker's ``asyncio.run``) would otherwise leave that
    loop's pooled connections inside the shared client, and the next request on
    another loop reuses a connection whose asyncio primitives belong to a closed
    loop: ``RuntimeError: Event loop is closed``. Callers on such a loop pass this
    client through ``http_async_client`` — which makes langchain-openai skip its
    cache entirely — and ``aclose()`` it before their loop closes.

    The client carries no timeout of its own: the OpenAI SDK stamps a per-request
    timeout, and a client-level default would cap streaming responses.
    """
    return httpx.AsyncClient(timeout=httpx.Timeout(None))


@dataclass(frozen=True)
class OneshotLLMResult:
    """Text plus the raw response message for callers that need metadata.

    ``message`` preserves ``response_metadata``/``additional_kwargs`` (e.g.
    provider termination signals) that the plain-text return path drops.
    """

    text: str
    message: AIMessage


def _resolve_environment() -> str | None:
    return os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT")


async def run_oneshot_llm_detailed(
    *,
    system_instruction: str,
    user_content: str,
    run_name: str,
    app_config: AppConfig,
    model_name: str | None = None,
    thread_id: str | None = None,
    model_overrides: dict[str, Any] | None = None,
    http_async_client: httpx.AsyncClient | None = None,
) -> OneshotLLMResult:
    """Run a single non-graph system+user LLM turn and return text + message.

    Args:
        system_instruction: System message content.
        user_content: Human message content.
        run_name: LangChain ``run_name`` and Langfuse ``assistant_id`` for the call.
        app_config: Application config used to build the model.
        model_name: Optional model override; ``None`` uses the default model.
        thread_id: Optional thread id, forwarded to Langfuse for tracing only.
        model_overrides: Optional per-call sampling overrides forwarded to
            ``create_chat_model`` (e.g. ``{"max_tokens": 128}``). Provider
            transforms may still drop a key (Codex removes ``max_tokens``).
        http_async_client: Optional caller-owned HTTP client; see
            :func:`new_isolated_http_client`. Callers on a short-lived event loop
            must supply one and close it before that loop closes.

    Returns:
        The extracted plain text plus the raw :class:`AIMessage`.
    """
    model_kwargs: dict[str, Any] = {"model_overrides": model_overrides} if model_overrides is not None else {}
    if http_async_client is not None:
        # Only present when a caller owns a client: the ordinary Gateway-loop path
        # keeps langchain-openai's shared default client and its connection reuse.
        model_kwargs["http_async_client"] = http_async_client
    model = await run_assembly(
        create_chat_model,
        name=model_name,
        thinking_enabled=False,
        app_config=app_config,
        **model_kwargs,
    )
    invoke_config: dict = {"run_name": run_name}
    inject_langfuse_metadata(
        invoke_config,
        thread_id=thread_id,
        user_id=get_effective_user_id(),
        assistant_id=run_name,
        model_name=model_name,
        environment=_resolve_environment(),
    )
    response = await model.ainvoke(
        [
            SystemMessage(content=system_instruction),
            HumanMessage(content=user_content),
        ],
        config=invoke_config,
    )
    return OneshotLLMResult(text=extract_response_text(response.content), message=response)


async def run_oneshot_llm(
    *,
    system_instruction: str,
    user_content: str,
    run_name: str,
    app_config: AppConfig,
    model_name: str | None = None,
    thread_id: str | None = None,
    model_overrides: dict[str, Any] | None = None,
    http_async_client: httpx.AsyncClient | None = None,
) -> str:
    """Run a single non-graph system+user LLM turn and return the raw text.

    Args:
        system_instruction: System message content.
        user_content: Human message content.
        run_name: LangChain ``run_name`` and Langfuse ``assistant_id`` for the call.
        app_config: Application config used to build the model.
        model_name: Optional model override; ``None`` uses the default model.
        thread_id: Optional thread id, forwarded to Langfuse for tracing only.
        model_overrides: Optional per-call sampling overrides (see
            :func:`run_oneshot_llm_detailed`).
        http_async_client: Optional caller-owned HTTP client (see
            :func:`new_isolated_http_client`).

    Returns:
        The extracted plain-text content of the model response (uncleaned).
    """
    result = await run_oneshot_llm_detailed(
        system_instruction=system_instruction,
        user_content=user_content,
        run_name=run_name,
        app_config=app_config,
        model_name=model_name,
        thread_id=thread_id,
        model_overrides=model_overrides,
        http_async_client=http_async_client,
    )
    return result.text
