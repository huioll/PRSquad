"""FastAPI 入口：webhook 接收、手动审查接口、健康检查。

两条入口最终都汇到同一个 _run_review()：
- POST /v1/review        手动传 diff，适合本地演示和调试
- POST /v1/webhook/github 接收 GitHub 的 PR 事件
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse

from .config import get_settings
from .github import GitHubClient
from .graph import build_graph
from .llm import build_llm
from .schemas import ConsolidatedReview, PullRequestEvent, ReviewRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("prsquad")

app = FastAPI(title="PRSquad", version="0.1.0", description="多智能体 PR 代码审查服务")

_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
def root():
    """根路径返回单页演示界面（贴 diff → 看结果）。"""
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/health")
def health():
    """健康检查：顺带告诉你当前用的是假模型还是真模型。"""
    s = get_settings()
    return {
        "status": "ok",
        "llm_provider": s.llm_provider,
        "model": s.openai_model if s.llm_provider == "openai" else "stub",
        "github_posting_enabled": s.post_comments and s.github_token is not None,
    }


@app.post("/v1/review", response_model=ConsolidatedReview)
async def manual_review(req: ReviewRequest) -> ConsolidatedReview:
    """手动触发一次审查（无需 webhook），演示和调试用这个。"""
    return await _run_review(req.owner, req.repo, req.pr_number, "(手动触发)", inline_diff=req.diff)


@app.post("/v1/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
):
    """GitHub pull_request webhook 接收端。配置了 secret 时会校验 HMAC 签名。"""
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    # 只处理 pull_request 事件
    if x_github_event != "pull_request":
        return {"ignored": True, "event": x_github_event}

    event = PullRequestEvent.model_validate_json(body)
    # 只处理"新建、更新、重新打开"这三种动作，避免评论、打标签等事件误触发
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
    """两条入口共用的主流程：拿 diff → 跑图 → 可选回帖 → 返回结果。"""
    s = get_settings()
    gh = GitHubClient(s.github_token, s.github_api_base)

    # 优先用请求里直接传的 diff（本地演示），否则去 GitHub 拉
    diff = inline_diff if inline_diff is not None else await gh.fetch_pr_diff(owner, repo, pr_number)

    # 建图并执行。第三个参数 reports=[] 是给累加 reducer 一个初始值
    graph = build_graph(build_llm())
    final_state = await graph.ainvoke({"diff": diff, "pr_title": pr_title, "reports": []})
    markdown = final_state.get("markdown", "")
    reports = final_state.get("reports", [])

    # 只有显式开启 post_comments 且有 token 时，才真的往 GitHub 发评论
    posted = False
    if s.post_comments and s.github_token:
        try:
            await gh.post_review_comment(owner, repo, pr_number, markdown)
            posted = True
        except Exception:  # pragma: no cover
            log.exception("向 PR %s/%s#%d 发送评论失败", owner, repo, pr_number)

    return ConsolidatedReview(
        pr_number=pr_number,
        repo=f"{owner}/{repo}",
        reports=reports,
        markdown=markdown,
        posted_to_github=posted,
    )


def _verify_signature(body: bytes, header: str | None) -> None:
    """校验 GitHub 的 HMAC-SHA256 签名，防止有人伪造 webhook 请求。"""
    s = get_settings()
    if not s.webhook_secret:
        return  # 演示模式：没配 secret 就跳过校验
    if not header or not header.startswith("sha256="):
        raise HTTPException(401, "缺少签名或签名格式不正确")
    expected = "sha256=" + hmac.new(s.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    # 用 compare_digest 而不是 ==，避免时序攻击
    if not hmac.compare_digest(expected, header):
        raise HTTPException(401, "签名校验失败")
