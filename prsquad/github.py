"""GitHub API 的薄封装：只需要两个能力——拉 PR 的 diff、往 PR 发一条评论。"""
from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, token: str | None, api_base: str = "https://api.github.com"):
        self._token = token
        self._api_base = api_base.rstrip("/")

    def _headers(self) -> dict[str, str]:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def fetch_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """返回该 PR 的 unified diff 文本。没有 token 时返回空字符串（演示模式）。"""
        if not self._token:
            log.info("没有配置 github token —— 返回空 diff（演示模式）")
            return ""
        url = f"{self._api_base}/repos/{owner}/{repo}/pulls/{pr_number}"
        async with httpx.AsyncClient(timeout=20.0) as c:
            # 注意 Accept 换成 v3.diff，GitHub 才会直接返回 diff 而不是 JSON
            resp = await c.get(url, headers={**self._headers(), "Accept": "application/vnd.github.v3.diff"})
            resp.raise_for_status()
            return resp.text

    async def post_review_comment(
        self, owner: str, repo: str, pr_number: int, body: str
    ) -> dict[str, Any]:
        """往 PR 发一条普通评论。返回 GitHub 的响应体。"""
        if not self._token:
            log.info("跳过发评论（没有 github token）。正文长度=%d", len(body))
            return {"posted": False, "reason": "no_token"}
        # 注意：PR 的评论走的是 issues 接口，不是 pulls 接口，这是个常见坑
        url = f"{self._api_base}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        async with httpx.AsyncClient(timeout=20.0) as c:
            resp = await c.post(url, headers=self._headers(), json={"body": body})
            resp.raise_for_status()
            return resp.json()
