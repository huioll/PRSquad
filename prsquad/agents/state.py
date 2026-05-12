"""Shared LangGraph state definition.

Each agent node reads the diff + writes its AgentReport into ``state.reports``.
Using a single TypedDict-ish state keeps the graph simple and lets LangGraph fan-out / fan-in
work cleanly via additive list reducers.
"""
from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict

from ..schemas import AgentReport


class GraphState(TypedDict, total=False):
    """State threaded through the multi-agent graph."""
    diff: str
    pr_title: str
    # Annotated with `add` so concurrent nodes can each append a report safely.
    reports: Annotated[list[AgentReport], add]
    # Filled by the synthesizer fan-in node at the end of the graph.
    markdown: str
