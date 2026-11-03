"""数据模型：GitHub webhook 载荷（只取用到的字段）+ 本服务对外返回的结构。

这里用 Pydantic 定义，好处是 FastAPI 会自动做请求校验、自动生成接口文档。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PullRequestRef(BaseModel):
    number: int
    title: str
    body: str | None = None


class RepoRef(BaseModel):
    full_name: str  # 形如 "owner/repo"

    @property
    def owner(self) -> str:
        return self.full_name.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.full_name.split("/", 1)[1]


class PullRequestEvent(BaseModel):
    """GitHub pull_request webhook 中我们实际用到的字段子集。"""
    action: str  # opened、synchronize、reopened 等
    pull_request: PullRequestRef
    repository: RepoRef


class ReviewRequest(BaseModel):
    """手动触发审查的请求体（不需要 webhook）。"""
    owner: str
    repo: str
    pr_number: int
    diff: str | None = Field(
        default=None,
        description="可选：直接传入 diff 文本。不传则去 GitHub 拉取。",
    )


class AgentReport(BaseModel):
    """单个 agent 的产出。agent 字段只能取这四个值，与图里的节点名对应。"""
    agent: Literal["reviewer", "security", "tests", "docs"]
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ConsolidatedReview(BaseModel):
    """返回给调用方（或发到 PR 上）的完整结果。"""
    pr_number: int
    repo: str
    reports: list[AgentReport]
    markdown: str
    posted_to_github: bool = False
