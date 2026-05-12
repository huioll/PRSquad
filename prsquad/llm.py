"""LLM abstraction.

We intentionally don't depend on any single SDK (LangChain wrappers, etc.) at the call site —
agents talk to an :class:`LLMClient` protocol. The two impls today are a deterministic stub
(used by tests + demo mode) and an OpenAI client (lazy import).

Adding Walmart Element GenAI later is a 30-line file that implements the same protocol.
"""
from __future__ import annotations

import json
import logging
from typing import Protocol

log = logging.getLogger(__name__)


class LLMClient(Protocol):
    async def complete(self, system: str, user: str) -> str:
        """Return raw model output for the given system + user prompts."""
        ...


class StubLLM:
    """Deterministic, offline LLM. Returns canned-but-shaped JSON for each agent role.

    Lets the whole agent graph be tested + demoed with zero secrets.
    """

    def __init__(self) -> None:
        self._templates: dict[str, dict] = {
            "reviewer": {
                "summary": "Looks solid overall. A few naming nits and one possible perf win.",
                "comments": [
                    {"file": "<unknown>", "severity": "nit", "message": "Variable 'x' could be more descriptive."},
                    {"file": "<unknown>", "severity": "suggestion",
                     "message": "Consider extracting the inner loop into its own function for readability."},
                ],
            },
            "security": {
                "summary": "No critical findings. One medium: untrusted input concatenated into a log line.",
                "findings": [
                    {"severity": "medium", "rule": "log-injection",
                     "message": "User-controlled data flows into a log statement without sanitization."}
                ],
            },
            "tests": {
                "summary": "Two missing edge cases worth covering.",
                "suggestions": [
                    {"target": "happy path", "case": "verify return value when input list is empty"},
                    {"target": "error path", "case": "assert IllegalArgumentException on negative input"},
                ],
            },
            "docs": {
                "summary": "Three public functions are missing docstrings.",
                "drafts": [
                    {"symbol": "do_thing", "doc": "Performs the thing. Returns the new state."},
                ],
            },
        }

    async def complete(self, system: str, user: str) -> str:
        role = _detect_role(system)
        return json.dumps(self._templates.get(role, {"summary": "(stub) no template for role", "role": role}))


class OpenAILLM:
    """OpenAI-backed implementation. Imported lazily so it's not required at install time."""

    def __init__(self, api_key: str, model: str, timeout: float):
        from openai import AsyncOpenAI  # type: ignore  # noqa: PLC0415

        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout)
        self._model = model

    async def complete(self, system: str, user: str) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        return resp.choices[0].message.content or "{}"


def _detect_role(system_prompt: str) -> str:
    """Map a system prompt to one of the canonical agent roles for the StubLLM."""
    lower = system_prompt.lower()
    if "security" in lower:
        return "security"
    if "test" in lower:
        return "tests"
    if "docstring" in lower or "documentation" in lower:
        return "docs"
    return "reviewer"


def build_llm() -> LLMClient:
    """Factory that picks the right impl based on settings."""
    from .config import get_settings  # noqa: PLC0415  (avoid circular import at module load)

    s = get_settings()
    if s.llm_provider == "openai":
        if not s.openai_api_key:
            log.warning("openai provider selected but no api key — falling back to stub")
            return StubLLM()
        return OpenAILLM(s.openai_api_key, s.openai_model, s.llm_timeout_seconds)
    return StubLLM()
