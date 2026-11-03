"""LangGraph 的连线：四个专职 agent 并行扇出，最后汇总。

这是整个项目里最能体现"框架价值"的文件——并行执行和等待汇合，
全靠下面那几行 add_edge，不需要自己写 asyncio.gather。
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .agents._base import make_agent_node
from .agents.prompts import DOCS, REVIEWER, SECURITY, TESTS
from .agents.state import GraphState
from .agents.synthesizer import synthesize
from .llm import LLMClient


def build_graph(llm: LLMClient):
    """构建并编译这张多智能体审查图。

    拓扑结构::

        START ──┬──▶ reviewer ──┐
                ├──▶ security ──┤
                ├──▶ tests    ──┼──▶ synthesize ──▶ END
                └──▶ docs     ──┘

    并行（扇出）是通过"从 START 同时连出多条边"实现的；
    汇合（扇入）则是"多条边同时指向 synthesize"——LangGraph 会等四条边全部完成。
    汇总节点依赖 state 里的 reports 字段，而该字段用了累加 reducer，保证并发追加不丢失。
    """
    g = StateGraph(GraphState)

    # 四个节点用的是同一个工厂函数，只是提示词和名字不同。
    g.add_node("reviewer", make_agent_node(name="reviewer", system_prompt=REVIEWER, llm=llm))
    g.add_node("security", make_agent_node(name="security", system_prompt=SECURITY, llm=llm))
    g.add_node("tests", make_agent_node(name="tests", system_prompt=TESTS, llm=llm))
    g.add_node("docs", make_agent_node(name="docs", system_prompt=DOCS, llm=llm))
    g.add_node("synthesize", synthesize)

    for agent in ("reviewer", "security", "tests", "docs"):
        g.add_edge(START, agent)        # 扇出：起点连到每个 agent，它们会并行跑
        g.add_edge(agent, "synthesize")  # 扇入：每个 agent 完成后都汇到汇总节点
    g.add_edge("synthesize", END)

    return g.compile()# 编译并返回图
