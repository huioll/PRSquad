"""Agent 节点的共享工厂。

四个 agent 的流程完全一样，只有提示词不同，所以这里用工厂函数生成节点，
避免把同一段逻辑复制四遍。这就是"四个 agent 其实是同一段代码"的原因。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from ..llm import LLMClient
from ..schemas import AgentReport
from .state import GraphState

log = logging.getLogger(__name__)


def make_agent_node(
    name: str,
    system_prompt: str,
    llm: LLMClient,
) -> Callable[[GraphState], Awaitable[dict[str, Any]]]:
    """生成一个符合 LangGraph 要求的节点函数。

    每个节点的固定动作：
      1. 从 state 取出 diff，拼成 user 提示词
      2. 调用模型，期望模型返回 JSON
      3. 把结果包成 AgentReport，作为 state 增量返回
    """

    async def node(state: GraphState) -> dict[str, Any]:
        user = _build_user_prompt(state)
        try:
            raw = await llm.complete(system_prompt, user)
            payload = _safe_json(raw)
            summary = str(payload.get("summary") or f"{name} 没有给出总结")
            report = AgentReport(agent=name, summary=summary, payload=payload)  # type: ignore[arg-type]
        except Exception as e:  # pragma: no cover —— 防御性兜底
            # 单个 agent 出错不拖垮整条流程：包装成一份"错误报告"继续往下走。
            # 这样另外三个 agent 的成果依然能返回给用户。
            log.exception("Agent %s 执行失败", name)
            report = AgentReport(agent=name, summary=f"{name} 执行失败：{e}", payload={}, error=str(e))  # type: ignore[arg-type]
        # 注意这里只返回增量：只新增一份报告，其他字段保持原样。
        return {"reports": [report]}

    node.__name__ = f"agent_{name}"
    return node


def _build_user_prompt(state: GraphState) -> str:
    diff = state.get("diff") or "(没有 diff —— 当前是演示模式)"
    title = state.get("pr_title") or "(未命名 PR)"
    # 按字符粗暴截断到 8000，控制 token 成本。
    # 局限：大 PR 的后半部分代码不会被审到。想更进一步可以按文件切分，
    # 但那会让这个文件复杂不少，当前版本先保持简单。
    truncated = diff[:8_000]
    return (
        f"PR 标题：{title}\n\n"
        f"以下是被截断到 8KB 的统一 diff 格式代码变更：\n```diff\n{truncated}\n```\n\n"
        f"请只返回一个 JSON 对象，不要包含任何额外说明文字。"
    )


def _safe_json(raw: str) -> dict[str, Any]:
    """容错解析：模型不一定老实返回纯 JSON，可能带代码围栏或一段解释。"""
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"summary": str(parsed)}
    except json.JSONDecodeError:
        # 解析失败就把原文塞进 summary，保证流程不中断。
        return {"summary": raw[:500]}
