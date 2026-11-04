"""汇总节点：把四份 agent 报告拼成一条适合发到 PR 的 Markdown 评论。

注意：这个节点完全没有调用模型，只是纯字符串拼接。
只有当需要"挑重点、去重、排序"时，才值得在这里引入一次模型调用——当前版本没做。
"""
from __future__ import annotations

from typing import Any

from .state import GraphState

_HEADER = "🤖 **PRSquad 代码审查** —— 多智能体自动审查结果\n\n"

# agent 的内部标识（英文，被 schema 锁定）到展示名称的映射。
_DISPLAY = {"reviewer": "代码质量", "security": "安全", "tests": "测试", "docs": "文档"}

# 渲染时的固定顺序：先看结论性的（质量、安全），再看补全性的（测试、文档）。
# 不加这个的话，渲染顺序就跟着 state 里 reports 数组的原始次序走。实测 langgraph
# 1.2.19 下这个次序是 docs → reviewer → security → tests（跨进程稳定，且与完成
# 时间无关），等于报告以「文档」开头，读起来别扭。
# 注意这是渲染层单方面的保证：图本身不做重排，接口返回的 reports 数组仍是原序。
_ORDER = ("reviewer", "security", "tests", "docs")


def synthesize(state: GraphState) -> dict[str, Any]:
    """把每个 agent 的报告渲染成一段 Markdown。"""
    reports = state.get("reports", [])
    by_agent = {r.agent: r for r in reports}

    parts = [_HEADER]
    # 固定顺序渲染；万一以后加了新角色，排在标准顺序之后，不会丢
    for agent in list(_ORDER) + [a for a in by_agent if a not in _ORDER]:
        report = by_agent.get(agent)
        if report is None:
            continue
        parts.append(_render_section(report.agent, report.summary, report.payload, report.error))
    parts.append("\n---\n*由 PRSquad 生成 —— 多智能体并行审查*")
    return {"markdown": "".join(parts)}


def _render_section(agent: str, summary: str, payload: dict, error: str | None) -> str:
    icons = {"reviewer": "🧐", "security": "🛡️", "tests": "🧪", "docs": "📚"}
    icon = icons.get(agent, "•")
    title = _DISPLAY.get(agent, agent)
    out = [f"\n### {icon} {title}\n", f"{summary}\n"]
    if error:
        out.append(f"\n> ⚠️ 该 agent 执行出错：`{error}`\n")
        return "".join(out)

    # 按不同 agent 的 JSON 结构分别渲染。
    if comments := payload.get("comments"):
        out.append("\n**问题列表**\n")
        for c in comments:
            out.append(f"- _{c.get('severity','?')}_  `{c.get('file','?')}` —— {c.get('message','')}\n")
    if findings := payload.get("findings"):
        out.append("\n**漏洞发现**\n")
        for f in findings:
            out.append(f"- _{f.get('severity','?')}_  **{f.get('rule','?')}** —— {f.get('message','')}\n")
    if suggestions := payload.get("suggestions"):
        out.append("\n**建议补充的用例**\n")
        for s in suggestions:
            out.append(f"- {s.get('target','?')}：{s.get('case','')}\n")
    if drafts := payload.get("drafts"):
        out.append("\n**起草的 docstring**\n")
        for d in drafts:
            out.append(f"- `{d.get('symbol','?')}`：{d.get('doc','')}\n")
    return "".join(out)
