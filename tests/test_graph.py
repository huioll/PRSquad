"""End-to-end test of the multi-agent graph using the StubLLM."""
from __future__ import annotations

import pytest

from prsquad.graph import build_graph
from prsquad.llm import StubLLM


@pytest.mark.asyncio
async def test_graph_produces_one_report_per_agent():
    graph = build_graph(StubLLM())
    state = await graph.ainvoke({
        "diff": "diff --git a/foo.py b/foo.py\n+def x(): pass\n",
        "pr_title": "test pr",
        "reports": [],
    })
    agents = sorted(r.agent for r in state["reports"])
    assert agents == ["docs", "reviewer", "security", "tests"]


@pytest.mark.asyncio
async def test_graph_renders_markdown_with_section_per_agent():
    graph = build_graph(StubLLM())
    state = await graph.ainvoke({
        "diff": "(empty)",
        "pr_title": "demo",
        "reports": [],
    })
    md = state["markdown"]
    for header in ("Reviewer", "Security", "Tests", "Docs"):
        assert header in md, f"missing section: {header}"
    assert "PRSquad" in md
