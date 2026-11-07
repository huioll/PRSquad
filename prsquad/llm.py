"""LLM 抽象层。

设计要点：调用方（各个 agent 节点）不直接依赖任何一家的 SDK，而是只依赖
:class:`LLMClient` 这个协议（Protocol）。目前有两个实现：

- :class:`StubLLM`  —— 确定性的假模型，返回固定模板，用于单元测试和演示模式（零成本、零密钥）
- :class:`OpenAILLM` —— 真实模型调用，延迟导入，所以不装 openai 包也能跑起来

要接新的大模型厂商，只要再写一个实现同样 ``complete()`` 方法的类即可。
"""
from __future__ import annotations

import json
import logging
from typing import Protocol

log = logging.getLogger(__name__)


class LLMClient(Protocol):
    """LLM 客户端协议：任何实现了这个方法的对象都能当模型用。"""

    async def complete(self, system: str, user: str) -> str:
        """给定 system 提示词和 user 输入，返回模型原始输出文本。"""
        ...


class StubLLM:
    """确定性的离线假模型。

    它不读 diff、不做任何分析，只根据 system 提示词判断当前是哪个角色，
    然后返回一份预先写死的、格式正确的 JSON。

    作用：让整条 agent 流水线可以在没有 API Key、没有网络的情况下跑通和测试。
    注意：演示时看到的审查意见是固定模板，和真实代码内容无关。
    """

    def __init__(self) -> None:
        self._templates: dict[str, dict] = {
            "reviewer": {
                "summary": "整体看起来比较扎实，只有几处命名上的小问题和一处可能的性能改进空间。",
                "comments": [
                    {"file": "<未知>", "severity": "nit", "message": "变量 'x' 可以取一个更能表达意图的名字。"},
                    {"file": "<未知>", "severity": "suggestion",
                     "message": "可以考虑把内层循环抽成独立函数，提升可读性。"},
                ],
            },
            "security": {
                "summary": "未发现严重问题。有一处中危：不可信输入未经处理就拼接进了日志。",
                "findings": [
                    {"severity": "medium", "rule": "log-injection",
                     "message": "用户可控的数据未经转义就写入日志语句，存在日志注入风险。"}
                ],
            },
            "tests": {
                "summary": "有两处边界条件值得补充用例。",
                "suggestions": [
                    {"target": "正常路径", "case": "验证输入列表为空时的返回值是否正确"},
                    {"target": "异常路径", "case": "断言输入为负数时抛出非法参数异常"},
                ],
            },
            "docs": {
                "summary": "有三个公开函数缺少 docstring。",
                "drafts": [
                    {"symbol": "do_thing", "doc": "执行该操作，并返回新的状态对象。"},
                ],
            },
        }

    async def complete(self, system: str, user: str) -> str:
        role = _detect_role(system)
        return json.dumps(self._templates.get(role, {"summary": "(假模型) 没有匹配到该角色的模板", "role": role}),
                          ensure_ascii=False)


class OpenAILLM:
    """真实模型实现。延迟导入 openai 包，因此安装本项目时不需要它。

    虽然类名叫 OpenAI，但只要对方服务兼容 OpenAI 的 /chat/completions 协议
    （DeepSeek、通义、Moonshot、本地 vLLM / Ollama 都算），改 ``base_url`` 就能用。
    这就是"面向协议、不面向厂商"的好处。
    """

    def __init__(self, api_key: str, model: str, timeout: float, base_url: str | None = None):
        from openai import AsyncOpenAI  # type: ignore

        # base_url 为 None 时 SDK 自动用官方端点，所以这里可以直接透传。
        self._client = AsyncOpenAI(api_key=api_key, timeout=timeout, base_url=base_url)
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
    """把系统提示词映射到四个标准角色之一，供 StubLLM 挑模板。

    同时匹配中英文关键词，因为提示词已中文化。判断顺序不能乱：
    security 必须先于 tests 判断，否则含"安全测试"字样的提示词会被误判。
    """
    lower = system_prompt.lower()
    if "安全" in system_prompt or "security" in lower or "auditor" in lower:
        return "security"
    if "测试" in system_prompt or "test" in lower:
        return "tests"
    if "文档" in system_prompt or "docstring" in lower or "documentation" in lower:
        return "docs"
    return "reviewer"


def build_llm() -> LLMClient:
    """根据配置挑一个实现：默认走假模型，配置了 openai 就用真模型。"""
    from .config import get_settings  # 放在函数内：模块加载时导入会成环

    s = get_settings()
    if s.llm_provider == "openai":
        if not s.openai_api_key:
            log.warning("配置了 openai 但没有填 api key —— 回退到假模型")
            return StubLLM()
        return OpenAILLM(
            api_key=s.openai_api_key,
            model=s.openai_model,
            timeout=s.llm_timeout_seconds,
            base_url=s.openai_base_url,
        )
    return StubLLM()
