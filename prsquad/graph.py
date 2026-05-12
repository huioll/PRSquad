"""LangGraph wiring: parallel fan-out across 4 specialist agents, then synthesize."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .agents._base import make_agent_node
from .agents.prompts import DOCS, REVIEWER, SECURITY, TESTS
from .agents.state import GraphState
from .agents.synthesizer import synthesize
from .llm import LLMClient


def build_graph(llm: LLMClient):
    """Construct and compile the multi-agent review graph.

    Topology:

    ::

        START ──┬──▶ reviewer ──┐
                ├──▶ security ──┤
                ├──▶ tests    ──┼──▶ synthesizer ──▶ END
                └──▶ docs     ──┘

    Fan-out is achieved by adding parallel edges from START. The state's
    ``reports`` field uses an additive reducer so concurrent appends don't clobber each other.
    """
    g = StateGraph(GraphState)

    g.add_node("reviewer", make_agent_node(name="reviewer", system_prompt=REVIEWER, llm=llm))
    g.add_node("security", make_agent_node(name="security", system_prompt=SECURITY, llm=llm))
    g.add_node("tests", make_agent_node(name="tests", system_prompt=TESTS, llm=llm))
    g.add_node("docs", make_agent_node(name="docs", system_prompt=DOCS, llm=llm))
    g.add_node("synthesize", synthesize)

    for agent in ("reviewer", "security", "tests", "docs"):
        g.add_edge(START, agent)
        g.add_edge(agent, "synthesize")
    g.add_edge("synthesize", END)

    return g.compile()
