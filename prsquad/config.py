"""应用配置：全部通过环境变量或 .env 文件注入。

所有字段都有安全默认值，所以不配置任何密钥也能启动——这就是"演示模式"。
"""
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行时配置。

    环境变量统一加 ``PRSQUAD_`` 前缀，例如 ``PRSQUAD_GITHUB_TOKEN``。
    也可以写在项目根目录的 .env 文件里。
    """

    model_config = SettingsConfigDict(env_prefix="PRSQUAD_", env_file=".env", extra="ignore")

    # 模型
    # stub = 假模型（不花钱、不联网）；openai = 真实模型
    llm_provider: Literal["stub", "openai"] = "stub"
    openai_api_key: str | None = None
    # 只填这一项就能切到任何"兼容 OpenAI 协议"的服务，例如：
    #   DeepSeek  https://api.deepseek.com/v1
    #   通义千问  https://dashscope.aliyuncs.com/compatible-mode/v1
    #   Moonshot  https://api.moonshot.cn/v1
    # 留空则打 OpenAI 官方端点。
    openai_base_url: str | None = None
    openai_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0

    # GitHub
    github_token: str | None = None
    github_api_base: str = "https://api.github.com"
    post_comments: bool = False  # 默认关闭，避免本地调试时往别人的 PR 里刷评论

    # Webhook 签名校验（留空则跳过校验，方便本地测试）
    webhook_secret: str | None = None

    # 服务
    host: str = "0.0.0.0"
    port: int = 8001


_settings: Settings | None = None


def get_settings() -> Settings:
    """单例：整个进程只读一次环境变量。"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
