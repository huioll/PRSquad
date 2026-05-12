"""GitHub API helpers. Thin wrapper — we only need to read PR diff and post a comment."""
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
        """Return the unified-diff text for a PR. Empty string if no token / failure."""
        if not self._token:
            log.info("No github token — returning empty diff (demo mode)")
            return ""
        url = f"{self._api_base}/repos/{owner}/{repo}/pulls/{pr_number}"
        async with httpx.AsyncClient(timeout=20.0) as c:
            resp = await c.get(url, headers={**self._headers(), "Accept": "application/vnd.github.v3.diff"})
            resp.raise_for_status()
            return resp.text

    async def post_review_comment(
        self, owner: str, repo: str, pr_number: int, body: str
    ) -> dict[str, Any]:
        """Post a single issue comment to the PR. Returns the GitHub response dict."""
        if not self._token:
            log.info("Comment skipped (no github token). Body length=%d", len(body))
            return {"posted": False, "reason": "no_token"}
        url = f"{self._api_base}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        async with httpx.AsyncClient(timeout=20.0) as c:
            resp = await c.post(url, headers=self._headers(), json={"body": body})
            resp.raise_for_status()
            return resp.json()
