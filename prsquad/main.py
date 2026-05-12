"""FastAPI entrypoint: webhook + manual review endpoints + health/metrics."""
from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import FastAPI, Header, HTTPException, Request

from .config import get_settings
from .github import GitHubClient
from .graph import build_graph
from .llm import build_llm
from .schemas import ConsolidatedReview, PullRequestEvent, ReviewRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("prsquad")

app = FastAPI(title="PRSquad", version="0.1.0", description="Multi-agent code reviewer for GitHub PRs.")


@app.get("/health")
def health():
    s = get_settings()
    return {
        "status": "ok",
        "llm_provider": s.llm_provider,
        "github_posting_enabled": s.post_comments and s.github_token is not None,
    }


@app.post("/v1/review", response_model=ConsolidatedReview)
async def manual_review(req: ReviewRequest) -> ConsolidatedReview:
    """Trigger a review by hand (no webhook required). Useful for demos."""
    return await _run_review(req.owner, req.repo, req.pr_number, "(manual)", inline_diff=req.diff)


@app.post("/v1/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
):
    """GitHub `pull_request` webhook receiver. Verifies HMAC if a secret is configured."""
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    if x_github_event != "pull_request":
        return {"ignored": True, "event": x_github_event}

    event = PullRequestEvent.model_validate_json(body)
    if event.action not in {"opened", "synchronize", "reopened"}:
        return {"ignored": True, "action": event.action}

    review = await _run_review(
        event.repository.owner,
        event.repository.name,
        event.pull_request.number,
        event.pull_request.title,
    )
    return {"ok": True, "posted": review.posted_to_github, "reports": len(review.reports)}


async def _run_review(
    owner: str,
    repo: str,
    pr_number: int,
    pr_title: str,
    inline_diff: str | None = None,
) -> ConsolidatedReview:
    s = get_settings()
    gh = GitHubClient(s.github_token, s.github_api_base)

    diff = inline_diff if inline_diff is not None else await gh.fetch_pr_diff(owner, repo, pr_number)

    graph = build_graph(build_llm())
    final_state = await graph.ainvoke({"diff": diff, "pr_title": pr_title, "reports": []})
    markdown = final_state.get("markdown", "")
    reports = final_state.get("reports", [])

    posted = False
    if s.post_comments and s.github_token:
        try:
            await gh.post_review_comment(owner, repo, pr_number, markdown)
            posted = True
        except Exception:  # pragma: no cover
            log.exception("Failed to post comment to PR %s/%s#%d", owner, repo, pr_number)

    return ConsolidatedReview(
        pr_number=pr_number,
        repo=f"{owner}/{repo}",
        reports=reports,
        markdown=markdown,
        posted_to_github=posted,
    )


def _verify_signature(body: bytes, header: str | None) -> None:
    s = get_settings()
    if not s.webhook_secret:
        return  # demo mode — no verification
    if not header or not header.startswith("sha256="):
        raise HTTPException(401, "missing or malformed signature")
    expected = "sha256=" + hmac.new(s.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, header):
        raise HTTPException(401, "invalid signature")
