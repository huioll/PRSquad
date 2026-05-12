"""Shared helpers for agent nodes — keeps them DRY (one input contract, one output contract)."""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from ..llm import LLMClient
from ..schemas import AgentReport
from .state import GraphState

log = logging.getLogger(__name__)


def make_agent_node(
    *,
    name: str,
    system_prompt: str,
    llm: LLMClient,
) -> Callable[[GraphState], Awaitable[dict[str, Any]]]:
    """Return a LangGraph-compatible async node function for the named agent.

    Each node:
      1. Builds a user prompt from the diff + PR title.
      2. Calls the LLM expecting JSON output.
      3. Wraps the result in an :class:`AgentReport` and returns a state delta.
    """

    async def node(state: GraphState) -> dict[str, Any]:
        user = _build_user_prompt(state)
        try:
            raw = await llm.complete(system_prompt, user)
            payload = _safe_json(raw)
            summary = str(payload.get("summary") or f"{name} produced no summary")
            report = AgentReport(agent=name, summary=summary, payload=payload)  # type: ignore[arg-type]
        except Exception as e:  # pragma: no cover — defensive guard
            log.exception("Agent %s failed", name)
            report = AgentReport(agent=name, summary=f"{name} failed: {e}", payload={}, error=str(e))  # type: ignore[arg-type]
        return {"reports": [report]}

    node.__name__ = f"agent_{name}"
    return node


def _build_user_prompt(state: GraphState) -> str:
    diff = state.get("diff") or "(no diff available — running in demo mode)"
    title = state.get("pr_title") or "(untitled PR)"
    # Cap diff size to keep prompt costs sane; real impl would use token-aware chunking.
    truncated = diff[:8_000]
    return (
        f"Pull request title: {title}\n\n"
        f"Unified diff (truncated to 8 KB):\n```diff\n{truncated}\n```\n\n"
        f"Respond with a JSON object."
    )


def _safe_json(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"summary": str(parsed)}
    except json.JSONDecodeError:
        return {"summary": raw[:500]}
