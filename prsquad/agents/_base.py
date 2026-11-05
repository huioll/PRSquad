"""Agent 节点的共享工厂。

四个 agent 的流程完全一样，只有提示词不同，所以这里用工厂函数生成节点，
避免把同一段逻辑复制四遍。这就是"四个 agent 其实是同一段代码"的原因。

一个节点内部可能是「多次模型调用」：diff 超过单批预算时会被 diffsplit 切成
若干批，节点逐批调用再把结果合并成一份报告。小 diff 只有一批，行为与
单次调用完全相同。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from ..diffsplit import split_diff
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
      1. 把 diff 切成若干批（小 PR 只有一批）
      2. 逐批调用模型，期望每批都返回 JSON
      3. 把多批结果合并，包成一份 AgentReport 作为 state 增量返回
    """

    async def node(state: GraphState) -> dict[str, Any]:
        batches = split_diff(state.get("diff") or "") or [""]
        total = len(batches)
        payloads: list[dict[str, Any]] = []
        errors: list[str] = []

        for index, batch in enumerate(batches, start=1):
            user = _build_user_prompt(state, batch, index, total)
            try:
                raw = await llm.complete(system_prompt, user)
                payloads.append(_safe_json(raw))
            except Exception as e:
                # 单批失败不拖垮整份报告，其余批次仍在下面合并。
                log.exception("Agent %s 第 %d/%d 批执行失败", name, index, total)
                errors.append(f"第{index}批：{e}")

        # 一批都没成功：照样返回一份报告，只是带上 error，让汇总层能显示出来。
        # 这样另外三个 agent 的成果依然能返回给用户。
        if not payloads:
            return {
                "reports": [
                    AgentReport(
                        agent=name,  # type: ignore[arg-type]
                        summary=f"{name} 执行失败",
                        payload={},
                        error="; ".join(errors),
                    )
                ]
            }

        merged = _merge_payloads(payloads)
        summary = str(merged.get("summary") or f"{name} 没有给出总结")
        report = AgentReport(
            agent=name,  # type: ignore[arg-type]
            summary=summary,
            payload=merged,
        )
        # 注意这里只返回增量：只新增一份报告，其他字段保持原样。
        return {"reports": [report]}

    node.__name__ = f"agent_{name}"
    return node


def _build_user_prompt(
    state: GraphState, batch: str, index: int = 1, total: int = 1
) -> str:
    """拼出这一批的 user 提示词。

    多批时明确告诉模型「你只看到了一部分」，否则它会对没展示的文件下结论。
    """
    title = state.get("pr_title") or "(未命名 PR)"
    scope = (
        ""
        if total == 1
        else f"（本次改动较大，已拆成 {total} 批，这是第 {index} 批；请不要对未出现的文件下结论）"
    )
    return (
        f"PR 标题：{title}{scope}\n\n"
        f"以下是统一 diff 格式的代码变更：\n```diff\n{batch}\n```\n\n"
        f"请只返回一个 JSON 对象，不要包含任何额外说明文字。"
    )


def _merge_payloads(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """把多批的 JSON 结果合并成一份。

    各 agent 的 payload 除 summary 外都是数组（comments / findings /
    suggestions / drafts），直接首尾相接。summary 只保留第一批的，并在前缀
    标注批次数——全部拼接会把报告开头撑得很长。
    """
    merged: dict[str, Any] = {}
    for payload in payloads:
        for key, value in payload.items():
            if key == "summary":
                continue
            if isinstance(value, list):
                merged.setdefault(key, []).extend(value)
            elif key not in merged:
                merged[key] = value

    summaries = [str(p.get("summary") or "").strip() for p in payloads]
    summaries = [s for s in summaries if s]
    if not summaries:
        merged["summary"] = "未给出总结"
    elif len(summaries) == 1:
        merged["summary"] = summaries[0]
    else:
        merged["summary"] = f"（改动分 {len(payloads)} 批审查）{summaries[0]}"

    return merged


def _safe_json(raw: str) -> dict[str, Any]:
    """容错解析：模型不一定老实返回纯 JSON，可能带代码围栏或一段解释。"""
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"summary": str(parsed)}
    except json.JSONDecodeError:
        # 解析失败就把原文塞进 summary，保证流程不中断。
        return {"summary": raw[:500]}
