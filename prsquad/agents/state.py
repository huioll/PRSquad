"""LangGraph 的共享状态定义。

这是整个多智能体流程的核心数据结构：所有节点都读写同一个 state。
每个 agent 节点读取 diff、把自己的审查结果写进 ``state.reports``。

关键点在于 ``reports`` 字段上的 ``Annotated[..., add]``——它让四个并行节点
可以各自追加，而不是互相覆盖。
"""
from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict

from ..schemas import AgentReport


class GraphState(TypedDict, total=False):
    """贯穿整张图的共享状态（可以理解成一块公共黑板）。
    total=False 表示所有字段都是可选的，图在运行过程中逐步把字段填满。
    """
    diff: str   #原始代码
    pr_title: str   #拉取请求标题
    # 用 `add` 标注后，LangGraph 合并不是覆盖而是拼接：
    # 四个节点同时返回 {"reports": [...]} 时，四份结果都会保留下来。
    # 如果去掉 Annotated，最终只剩最后完成的那一份。
    reports: Annotated[list[AgentReport], add]
    # 由最后的汇总节点（synthesizer）填入的 Markdown 文本。
    markdown: str   #Markdown文本
