"""Schemas: GitHub webhook payloads (subset) + our public API responses."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PullRequestRef(BaseModel):
    number: int
    title: str
    body: str | None = None


class RepoRef(BaseModel):
    full_name: str  # "owner/repo"

    @property
    def owner(self) -> str:
        return self.full_name.split("/", 1)[0]

    @property
    def name(self) -> str:
        return self.full_name.split("/", 1)[1]


class PullRequestEvent(BaseModel):
    """Subset of GitHub's pull_request webhook payload we actually use."""
    action: str  # opened, synchronize, reopened, ...
    pull_request: PullRequestRef
    repository: RepoRef


class ReviewRequest(BaseModel):
    """Manual trigger for ad-hoc reviews (no webhook needed)."""
    owner: str
    repo: str
    pr_number: int
    diff: str | None = Field(
        default=None,
        description="Optional inline diff. If omitted, fetched from GitHub.",
    )


class AgentReport(BaseModel):
    """One agent's contribution to the consolidated review."""
    agent: Literal["reviewer", "security", "tests", "docs"]
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ConsolidatedReview(BaseModel):
    """Full output returned to the API caller / posted to the PR."""
    pr_number: int
    repo: str
    reports: list[AgentReport]
    markdown: str
    posted_to_github: bool = False
