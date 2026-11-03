"""评估跑批脚本：跑一批标注好的 diff，算出命中率和误报率。

用法：
    # 先不花钱验证管线通不通（假模型，结果一定很差，只用来排查脚本）
    python eval/run_eval.py --stub --limit 2

    # 正式跑（用 .env 里配的真实模型，20 份大约 2~3 分钟）
    python eval/run_eval.py

    # 只跑指定的几份
    python eval/run_eval.py --only 001,005,012

产出：
    eval/reports/run-<时间>.md   人看的报告（含漏报/误报明细）
    eval/reports/run-<时间>.json 机读结果（两次跑之间可对比，用来证明「优化后提升了」）

指标口径（重要，面试被追问时要能解释）：
    命中率 recall   = 被发现的期望问题数 / 期望问题总数
    样本全中率      = 期望问题全部被发现的样本数 / 样本总数
    误报率 fp_rate  = 既没命中、也不属于重复提出的条目数 / 有效条目数
                      有效条目 = 全部条目 - 重复提出（同一处问题被两个 agent 各报一次）
    问题条目        = 只统计 comments（代码质量）和 findings（安全），
                      因为 suggestions/drafts 是「补充建议」不是「报错」，
                      把它们算进误报会虚高。可用 --kinds 调整。
    标注与条目的匹配严格一对一：一条标注只认领一条输出，剩下的记为重复提出。
    注意：误报数会偏高——模型可能报了真实存在但我没埋的问题。
          报告最后一节会把每条误报列出来，需要人工判定「真误报」还是「漏标」。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # 允许不安装本项目也能直接跑
    sys.path.insert(0, str(ROOT))

CASES_DIR = Path(__file__).parent / "cases"
REPORTS_DIR = Path(__file__).parent / "reports"

# ---------------------------------------------------------------------------
# 问题类型 → 匹配用的关键词
#
# 模型输出是自然语言，同一种问题会有很多说法（「命令注入」「shell=True」
# 「os.system 拼接」）。所以每种类型配一组别名，命中任意一个就算识别到。
# 字符串 = 子串匹配；元组 = 这些子串必须同时出现（用来降低误匹配）。
# 这里的键必须和 cases/*.expected.json 里的 type 一致。
# ---------------------------------------------------------------------------
Alias = str | tuple[str, ...]

TAXONOMY: dict[str, list[Alias]] = {
    "sql-injection": [
        "sql注入", "sql 注入", "sql-injection", "sql injection",
        "拼接 sql", "拼接sql", "拼进 sql", "sql 语句拼接", "注入点",
        # 复核 017 时补的：模型只提到 ORDER BY 子句被拼接
        "order by", "拼进 order by",
    ],
    "command-injection": [
        "命令注入", "command injection", "command-injection",
        "shell=true", "os.system", "任意命令", "命令执行",
    ],
    "hardcoded-secret": [
        "硬编码", "hardcoded", "hard-code", "写死", "明文密码", "明文密钥",
        "凭据", "密钥泄露",
        # 复核 003 时补的：模型说的是「命令行中包含明文口令」
        "明文口令",
    ],
    "weak-hash": ["md5", "sha1", "弱哈希", "弱加密", "不安全哈希", "哈希算法"],
    "weak-random": [
        "random.randint", "伪随机", "可预测", "弱随机", "随机数生成",
        ("random", "验证码"),
    ],
    "path-traversal": [
        "路径遍历", "path traversal", "目录遍历", "目录穿越", "../",
        "绝对路径拼接", "未校验文件名",
    ],
    "ssrf": [
        "ssrf", "服务端请求伪造", "内网地址", "任意url", "任意 url",
        "未校验url", "未校验 url", "白名单",
    ],
    "xss": ["xss", "跨站脚本", "未转义", "innerhtml", "直接插入html", "储值型"],
    "unsafe-deserialization": [
        "反序列化", "pickle", "yaml.load", "yaml.loader", "不安全加载",
        "任意代码执行",
    ],
    "div-zero": [
        "除零", "zero division", "zerodivisionerror", "除以0", "除以 0",
        "除数为 0", "除数为0", "分母", "total 为 0",
    ],
    "none-check": [
        "none", "空值", "未判空", "判空", "attributeerror", "可能为 none",
        "返回 none", "不存在时", "空指针",
    ],
    "resource-leak": [
        "未关闭", "没有关闭", "资源泄漏", "资源泄露", "未释放", "句柄",
        "putconn", "连接池耗尽", "抽干", "泄漏",
        # 复核 015 时补的：模型说的是「连接不会归还」
        "归还", "耗尽",
        # 复核 015 时补的第二种写法：「cursor 不会被关闭」
        "不会被关闭",
    ],
    "n-plus-one": [
        "n+1", ("循环", "查询"), ("逐条", "查询"), "批量查询", "懒加载",
        ("for", "query"),
    ],
    "race-condition": [
        "竞态", "race condition", "并发冲突", "超卖", "先读后写", "先查后改",
        ("并发", "锁"), ("并发", "覆盖"),
    ],
    "broken-access-control": [
        "越权", "idor", "未校验归属", "未校验是否属于", "任意用户",
        "水平权限", ("owner", "校验"), ("归属", "校验"), "未校验权限",
        # 复核 005 时补的：模型说「没有任何鉴权，任意调用者都能枚举」
        "鉴权", "任意调用者",
    ],
    "auth-bypass": [
        "认证绕过", "绕过认证", "跳过校验", "token 为空", "token为空",
        "未校验凭证", "不校验令牌", "无需认证", "鉴权绕过",
        # 复核 009 时补的：模型把「前缀匹配就算通过」也说成鉴权问题
        "过于宽松", "startswith", "无法验证身份",
        "前缀",
    ],
    "log-injection": [
        "日志注入", "log injection", "换行注入", "伪造日志", "伪造审计",
        # 复核 014 时补的：「伪造或篡改审计记录」这类写法
        "审计记录", "伪造", "换行符",
    ],
    "sensitive-log": [
        "敏感信息", "明文密码", "打印密码", "记录密码", "日志泄露",
        ("日志", "密码"), ("日志", "token"), ("日志", "手机号"),
    ],
    "error-handling": [
        "吞掉异常", "静默失败", "裸 except", "bare except", "except: pass",
        "捕获所有异常", "忽略异常", "过宽的异常", "异常被吞", "静默返回",
        # 复核 006 时补的：模型说「会静默吞掉文件不存在、权限……所有错误」
        "静默吞掉",
        # 复核 003 时补的：备份脚本没检查子进程返回码
        "返回码", "掩盖失败",
    ],
    "boundary": [
        "边界", "范围校验", "负数", "未校验正负", "上限", "越界",
        "非法参数", "参数校验",
    ],
    "debug-enabled": ["debug=true", "debug 模式", "开启 debug", "调试模式", "生产环境"],
    "cors-wildcard": ["cors", "跨域", "allow_origins", "通配符", "任意源"],
    "unrestricted-upload": [
        "文件类型", "类型校验", "后缀", "上传任意", "大小限制", "大小上限",
        "文件大小", "扩展名", "可执行文件", "未校验文件",
    ],
    # --- 以下五类是人工复核 43 条未匹配项时新增的 ---------------------------
    # 原分类只覆盖了「OWASP 式漏洞」，漏掉了时序攻击、分页逻辑错误这类
    # 同样能写进缺陷清单的问题。加类型必须同时加注释里的期望项，否则永远漏报。
    "timing-attack": [
        "时序", "恒定时间", "常量时间", "compare_digest", "侧信道",
    ],
    "logic-error": [
        "分页", "offset", "偏移量", "跳过第一页", "page * 20", "page*20",
        ("分页", "错"), ("offset", "错"),
    ],
    # 「select *」单独作别名太宽：模型举例写参数化查询时也会出现 select *，
    # 一条说「SQL 拼接」的幻觉能靠它蹭到「数据过度暴露」的命中。改成组合条件。
    "excessive-data-exposure": [
        ("select *", "返回"), ("select *", "暴露"), ("select *", "客户端"),
        ("select *", "字段"), ("select *", "泄露"),
        "所有列", "全部字段", "敏感字段", "过度返回",
        "返回全部", "不应返回",
        # 复核 020 时补的：返回体里带了服务器绝对路径
        "绝对路径",
    ],
    "insecure-transport": [
        "明文传输", "未启用 tls", "未启用tls", "starttls", "smtp_ssl",
        "25 端口", "25端口", "窃听",
    ],
    "robustness": [
        "filenotfounderror", "makedirs", "目录不存在", "导致 500",
        "返回 500", "直接 500", "抛 500",
    ],
    # 复核 007/019 时新增：不是安全漏洞，而是「这段代码根本跑不对」。
    # 原来的分类只覆盖 OWASP 式问题和健壮性，这类实现错误无处归类。
    "functional-bug": [
        "content-type", "截断", "乱码", "文本片段",
        "app.run", "flask", "启动方式", "无法启动", "不存在该方法",
    ],
}

# 报告里怎么称呼这些类型
TYPE_LABEL: dict[str, str] = {
    "sql-injection": "SQL 注入",
    "command-injection": "命令注入",
    "hardcoded-secret": "硬编码密钥",
    "weak-hash": "弱哈希",
    "weak-random": "弱随机数",
    "path-traversal": "路径遍历",
    "ssrf": "SSRF",
    "xss": "XSS",
    "unsafe-deserialization": "不安全反序列化",
    "div-zero": "除零",
    "none-check": "缺空值判断",
    "resource-leak": "资源泄漏",
    "n-plus-one": "N+1 查询",
    "race-condition": "竞态条件",
    "broken-access-control": "越权访问",
    "auth-bypass": "认证绕过",
    "log-injection": "日志注入",
    "sensitive-log": "敏感信息入日志",
    "error-handling": "异常处理不当",
    "boundary": "边界校验缺失",
    "debug-enabled": "生产开启 debug",
    "cors-wildcard": "CORS 通配",
    "unrestricted-upload": "上传限制缺失",
    "timing-attack": "时序攻击",
    "logic-error": "逻辑错误",
    "excessive-data-exposure": "过度暴露数据",
    "insecure-transport": "明文传输",
    "robustness": "健壮性缺陷",
    "functional-bug": "功能实现错误",
}

KIND_LABEL = {
    "comments": "代码质量",
    "findings": "安全",
    "suggestions": "测试",
    "drafts": "文档",
}

# 这些 severity 表示「建议」而不是「声称有缺陷」。
# 一条 nit/suggestion 说「建议加个 docstring」，它不是错误判断，
# 把它算进误报会把误报率抬高一大截，所以单独统计。
ADVICE_SEVERITIES = {"", "nit", "suggestion", "style", "info", "trivial"}


def _severity_of(item: dict[str, Any]) -> str:
    """取条目自报的严重度，统一成小写。取不到就当作「未声明」。"""
    raw = item.get("severity") or item.get("level") or ""
    return str(raw).strip().lower()


def _is_advice(severity: str) -> bool:
    return severity in ADVICE_SEVERITIES

# 文件名识别：用来判断某条意见说的是不是「期望的那个文件」
FILE_RE = re.compile(
    r"[A-Za-z0-9_./\\-]+\.(?:py|js|ts|tsx|jsx|sh|go|java|rb|php|json|ya?ml|sql|html|vue)"
)


def _norm(text: str) -> str:
    """统一大小写和全角半角，避免「ＳＱＬ 注入」这类写法漏匹配。"""
    return unicodedata.normalize("NFKC", text).lower()


def _alias_hit(alias: Alias, text: str) -> bool:
    if isinstance(alias, tuple):
        return all(a in text for a in alias)
    return alias in text


def _mentions_other_file(text: str, expected_file: str) -> bool:
    """意见里提到了别的文件名 → 说明说的是另一处代码，不算命中。

    模型经常不写文件名（只写「第 12 行」），这种情况下不做限制，
    否则会大量漏判。
    """
    found = FILE_RE.findall(text)
    if not found:
        return False
    target = Path(expected_file).name.lower()
    return not any(target in f.lower() for f in found)


def match_issue(text: str, issue: dict[str, Any]) -> bool:
    """判断一段模型输出是否命中某个期望问题。"""
    aliases = TAXONOMY.get(issue.get("type", ""), [])
    if not aliases or not any(_alias_hit(a, text) for a in aliases):
        return False
    expected_file = issue.get("file")
    if expected_file and _mentions_other_file(text, expected_file):
        return False
    return True


# ---------------------------------------------------------------------------
# 跑单个样本
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# 打分：把「模型输出的候选条目」和「人工标注」对起来
#
# 单独抽成函数，是为了让 --rematch 能拿历史 json 离线重算：
# 改标注、改别名都不用再花钱调模型，也不会因为模型输出随机性导致两次不可比。
# ---------------------------------------------------------------------------
def score_items(
    items: list[dict[str, Any]],
    summaries: list[dict[str, str]],
    expected: dict[str, Any],
) -> dict[str, Any]:
    """就地标记 items 的 hit / duplicate_of，返回命中明细与条目级统计。

    匹配是**一对一**的：一条标注最多认领一条模型输出，一条输出也只能被一条标注认领。

    早先的实现是「一条标注命中，把所有能匹配上的输出全标成命中」。
    这会让同一处问题被 reviewer 和 security 各报一次时算两次 TP——
    误报率被系统性低估，召回也被注水（`013` 里那条 SQL 拼接的幻觉，
    就是靠举例时顺带写了 `select *` 蹭到了「数据过度暴露」的命中）。

    认领不上的匹配不让它白算：单独记为「重复提出」（duplicate），
    既不算命中，也不算误判——它确实指出了真问题，只是别处已经说过了。
    """
    for it in items:
        it["hit"] = False
        it.pop("duplicate_of", None)

    issues = expected.get("issues", [])
    hits: list[dict[str, Any]] = []
    claimed: set[int] = set()
    for issue in issues:
        matched_by = [
            idx for idx, it in enumerate(items) if match_issue(it["text"], issue)
        ]
        # 标注在 expected.json 里的顺序就是优先级，先到先得
        owner = next((i for i in matched_by if i not in claimed), None)
        if owner is not None:
            items[owner]["hit"] = True
            claimed.add(owner)
        for idx in matched_by:
            if idx not in claimed:
                items[idx]["duplicate_of"] = issue.get("type")

        # 兜底：条目里没写、但 summary 里提到了，也算发现（只算召回，不算条目命中）
        via_summary: list[str] = []
        if not matched_by:
            via_summary = sorted(
                {s["agent"] for s in summaries if match_issue(s["text"], issue)}
            )

        hits.append(
            {
                "type": issue.get("type"),
                "file": issue.get("file"),
                "note": issue.get("note", ""),
                "hit": bool(matched_by or via_summary),
                "via_summary": bool(via_summary) and not matched_by,
                "matched_agents": sorted({items[i]["agent"] for i in matched_by})
                or via_summary,
            }
        )

    tp = sum(1 for it in items if it["hit"])
    dup = [it for it in items if not it["hit"] and it.get("duplicate_of")]
    fp_items = [it for it in items if not it["hit"] and not it.get("duplicate_of")]

    # 按「缺陷声明 / 建议」分层：一条 nit 不算错误判断，不该进误报率
    defect = [it for it in items if not _is_advice(it.get("severity", ""))]
    advice = [it for it in items if _is_advice(it.get("severity", ""))]

    def _count(group: list[dict[str, Any]], kind: str) -> int:
        if kind == "hit":
            return sum(1 for it in group if it["hit"])
        if kind == "dup":
            return sum(1 for it in group if not it["hit"] and it.get("duplicate_of"))
        return sum(1 for it in group if not it["hit"] and not it.get("duplicate_of"))

    # 按 agent 拆条目，用来回答「哪个角色最爱凑数」
    agent_stats: dict[str, dict[str, int]] = {}
    for it in items:
        slot = agent_stats.setdefault(it["agent"], {"total": 0, "tp": 0, "dup": 0})
        slot["total"] += 1
        if it["hit"]:
            slot["tp"] += 1
        elif it.get("duplicate_of"):
            slot["dup"] += 1

    return {
        "hits": hits,
        "items_tp": tp,
        "items_fp": len(fp_items),
        "items_dup": len(dup),
        "fp_items": fp_items,
        "dup_items": dup,
        "by_agent": agent_stats,
        "items_defect_total": len(defect),
        "items_defect_tp": _count(defect, "hit"),
        "items_defect_fp": _count(defect, "fp"),
        "items_defect_dup": _count(defect, "dup"),
        "items_advice_total": len(advice),
        "items_advice_fp": _count(advice, "fp"),
        "items_advice_dup": _count(advice, "dup"),
    }


async def run_case(
    case_id: str,
    diff: str,
    expected: dict[str, Any],
    *,
    run_review,
    kinds: tuple[str, ...],
    timeout: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    error: str | None = None
    reports: list[Any] = []

    try:
        review = await asyncio.wait_for(
            run_review(
                owner="eval",
                repo=f"case-{case_id}",
                pr_number=int(case_id),
                pr_title=expected.get("title", ""),
                inline_diff=diff,
            ),
            timeout=timeout,
        )
        reports = list(review.reports)
    except (asyncio.TimeoutError, TimeoutError):
        error = f"超时（>{timeout:.0f}s）"
    except Exception as exc:  # noqa: BLE001 —— 单份失败不影响整批
        error = f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - started

    # 把每个 agent 的每条结构化产出摊平成「候选条目」
    # 注意：这里只取条目本身的文本，不拼 summary。否则 summary 里提一句
    # 「存在 SQL 注入和硬编码密钥」，同一份报告下的所有条目都会被判成命中，
    # 命中率会虚高、误报会被掩盖。summary 只作为「条目里没写」时的兜底。
    items: list[dict[str, Any]] = []
    summaries: list[dict[str, str]] = []
    for report in reports:
        payload = getattr(report, "payload", {}) or {}
        summaries.append(
            {
                "agent": getattr(report, "agent", "?"),
                "text": _norm(getattr(report, "summary", "") or ""),
            }
        )
        for kind in kinds:
            for raw_item in payload.get(kind, []) or []:
                if not isinstance(raw_item, dict):
                    raw_item = {"message": str(raw_item)}
                items.append(
                    {
                        "agent": getattr(report, "agent", "?"),
                        "kind": kind,
                        "item": raw_item,
                        "severity": _severity_of(raw_item),
                        "text": _norm(json.dumps(raw_item, ensure_ascii=False)),
                        "hit": False,
                    }
                )

    scored = score_items(items, summaries, expected)
    agent_errors = [getattr(r, "agent", "?") for r in reports if getattr(r, "error", None)]

    return {
        "id": case_id,
        "title": expected.get("title", ""),
        "elapsed": elapsed,
        "error": error,
        "agent_errors": agent_errors,
        "expected_total": len(expected.get("issues", [])),
        "expected_hit": sum(1 for h in scored["hits"] if h["hit"]),
        "expected_via_summary": sum(1 for h in scored["hits"] if h.get("via_summary")),
        "items_total": len(items),
        "items_tp": scored["items_tp"],
        "items_fp": scored["items_fp"],
        "items_dup": scored["items_dup"],
        "items_defect_total": scored["items_defect_total"],
        "items_defect_tp": scored["items_defect_tp"],
        "items_defect_fp": scored["items_defect_fp"],
        "items_defect_dup": scored["items_defect_dup"],
        "items_advice_total": scored["items_advice_total"],
        "items_advice_fp": scored["items_advice_fp"],
        "items_advice_dup": scored["items_advice_dup"],
        "hits": scored["hits"],
        "fp_items": scored["fp_items"],
        "dup_items": scored["dup_items"],
        "by_agent": scored["by_agent"],
        "reports": len(reports),
        # 下面两项是为了 --rematch：有了原始条目就能离线重算，不必再调模型
        "items": items,
        "summaries": summaries,
    }


def apply_score(result: dict[str, Any], expected: dict[str, Any]) -> None:
    """用（可能已经改过的）标注重算一份已有结果的指标，原地修改。

    --rematch 的核心：条目的原始文本都在 json 里，所以改标注、改别名之后
    不必再调一次模型 —— 模型输出不变，指标变化就能干净地归因到标注修正上。
    """
    items = result.get("items")
    if items is None:  # 老格式的 json 只存了未匹配项
        items = result.get("fp_items", [])
    scored = score_items(items, result.get("summaries", []), expected)

    result.update(
        {
            "expected_total": len(expected.get("issues", [])),
            "expected_hit": sum(1 for h in scored["hits"] if h["hit"]),
            "expected_via_summary": sum(
                1 for h in scored["hits"] if h.get("via_summary")
            ),
            "items_total": len(items),
            "items_tp": scored["items_tp"],
            "items_fp": scored["items_fp"],
            "items_dup": scored["items_dup"],
            "items_defect_total": scored["items_defect_total"],
            "items_defect_tp": scored["items_defect_tp"],
            "items_defect_fp": scored["items_defect_fp"],
            "items_defect_dup": scored["items_defect_dup"],
            "items_advice_total": scored["items_advice_total"],
            "items_advice_fp": scored["items_advice_fp"],
            "items_advice_dup": scored["items_advice_dup"],
            "hits": scored["hits"],
            "fp_items": scored["fp_items"],
            "dup_items": scored["dup_items"],
            "by_agent": scored["by_agent"],
        }
    )


# ---------------------------------------------------------------------------
# 汇总与报告
# ---------------------------------------------------------------------------
def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    exp_total = sum(r["expected_total"] for r in results)
    exp_hit = sum(r["expected_hit"] for r in results)
    items = sum(r["items_total"] for r in results)
    tp = sum(r["items_tp"] for r in results)
    fp = sum(r["items_fp"] for r in results)
    dup = sum(r.get("items_dup", 0) for r in results)
    # 分层：只对「声称有缺陷」的条目算误报率；nit/suggestion 归建议，单独统计
    d_total = sum(r.get("items_defect_total", 0) for r in results)
    d_tp = sum(r.get("items_defect_tp", 0) for r in results)
    d_fp = sum(r.get("items_defect_fp", 0) for r in results)
    d_dup = sum(r.get("items_defect_dup", 0) for r in results)
    a_total = sum(r.get("items_advice_total", 0) for r in results)
    a_fp = sum(r.get("items_advice_fp", 0) for r in results)
    a_dup = sum(r.get("items_advice_dup", 0) for r in results)
    ok_cases = sum(1 for r in results if r["expected_total"] and r["expected_hit"] == r["expected_total"])
    scored = [r for r in results if r["expected_total"]]
    elapsed = [r["elapsed"] for r in results if not r["error"]]

    # 按问题类型统计召回
    by_type: dict[str, dict[str, int]] = {}
    for r in results:
        for h in r["hits"]:
            slot = by_type.setdefault(str(h["type"]), {"total": 0, "hit": 0})
            slot["total"] += 1
            slot["hit"] += 1 if h["hit"] else 0

    # 按 agent 统计条目数与误报，用来看哪个角色最爱「凑数」
    by_agent: dict[str, dict[str, int]] = {}
    for r in results:
        for agent, stat in r["by_agent"].items():
            slot = by_agent.setdefault(agent, {"total": 0, "tp": 0, "dup": 0})
            slot["total"] += stat["total"]
            slot["tp"] += stat["tp"]
            slot["dup"] += stat.get("dup", 0)

    return {
        "cases": len(results),
        "scored_cases": len(scored),
        "cases_all_hit": ok_cases,
        "expected_total": exp_total,
        "expected_hit": exp_hit,
        "expected_via_summary": sum(r["expected_via_summary"] for r in results),
        "recall": exp_hit / exp_total if exp_total else 0.0,
        "case_recall": ok_cases / len(scored) if scored else 0.0,
        "items_total": items,
        "items_tp": tp,
        "items_fp": fp,
        "items_dup": dup,
        # 分母只算「有效条目」：重复提出既不是命中，也不是误判，不该进分母
        "fp_rate": fp / (items - dup) if items - dup else 0.0,
        "dup_rate": dup / items if items else 0.0,
        "items_defect_total": d_total,
        "items_defect_tp": d_tp,
        "items_defect_fp": d_fp,
        "items_defect_dup": d_dup,
        "fp_rate_defect": d_fp / (d_total - d_dup) if d_total - d_dup else 0.0,
        "items_advice_total": a_total,
        "items_advice_fp": a_fp,
        "items_advice_dup": a_dup,
        "fp_rate_advice": a_fp / (a_total - a_dup) if a_total - a_dup else 0.0,
        "avg_elapsed": sum(elapsed) / len(elapsed) if elapsed else 0.0,
        "failed_cases": sum(1 for r in results if r["error"]),
        "agent_errors": sum(len(r["agent_errors"]) for r in results),
        "by_type": by_type,
        "by_agent": by_agent,
    }


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def render_markdown(
    summary: dict[str, Any], results: list[dict[str, Any]], meta: dict[str, str]
) -> str:
    lines: list[str] = []
    add = lines.append

    add("# PRSquad 评估报告")
    add("")
    for key, value in meta.items():
        add(f"- {key}：{value}")
    add("")

    add("## 总体")
    add("")
    add("| 指标 | 数值 |")
    add("|---|---|")
    add(f"| 样本数 | {summary['cases']} |")
    add(f"| 期望问题总数 | {summary['expected_total']} |")
    add(f"| 命中数 | {summary['expected_hit']}（{_pct(summary['recall'])}） |")
    add(
        f"| 其中「只在 summary 提到、条目没写」 | {summary['expected_via_summary']} |"
    )
    add(f"| 样本全中 | {summary['cases_all_hit']}/{summary['scored_cases']}（{_pct(summary['case_recall'])}） |")
    add(f"| 问题条目数 | {summary['items_total']} |")
    add(
        f"| 命中 / 未匹配 / 重复提出 | {summary['items_tp']} / "
        f"{summary['items_fp']} / {summary['items_dup']} |"
    )
    add(
        f"| 全条目未匹配率（旧口径，误报率上界） | {_pct(summary['fp_rate'])} |"
    )
    add("")
    add("### 分层口径")
    add("")
    add("nit / suggestion 只是「建议」，不是「声称这里有问题」，混在一起算会虚高误报。")
    add("所以下面把条目拆成两层，**误报率只看缺陷层**。")
    add("")
    add("「重复提出」指同一处问题被两个 agent 各报一次。它确实指出了真问题，")
    add("但不是新的发现，也不算误判，所以单列，不进误报率的分母。")
    add("")
    add("| 层 | 条目 | 命中 | 未匹配 | 重复 | 误报率 |")
    add("|---|---|---|---|---|---|")
    add(
        f"| 缺陷声明（critical/high/major/medium/low） | {summary['items_defect_total']} | "
        f"{summary['items_defect_tp']} | {summary['items_defect_fp']} | "
        f"{summary['items_defect_dup']} | "
        f"**{_pct(summary['fp_rate_defect'])}** |"
    )
    add(
        f"| 建议（nit/suggestion） | {summary['items_advice_total']} | "
        f"{summary['items_advice_total'] - summary['items_advice_fp'] - summary['items_advice_dup']} | "
        f"{summary['items_advice_fp']} | {summary['items_advice_dup']} | "
        f"{_pct(summary['fp_rate_advice'])} |"
    )
    add("")
    add(f"- 平均耗时：{summary['avg_elapsed']:.1f} 秒 / 份")
    add(f"- 整份失败 / 单 agent 出错：{summary['failed_cases']} / {summary['agent_errors']}")
    add("")

    add("## 按问题类型")
    add("")
    add("| 类型 | 期望 | 命中 | 召回 |")
    add("|---|---|---|---|")
    for type_name, stat in sorted(
        summary["by_type"].items(), key=lambda kv: (kv[1]["hit"] / kv[1]["total"], kv[0])
    ):
        label = TYPE_LABEL.get(type_name, type_name)
        add(f"| {label} | {stat['total']} | {stat['hit']} | {_pct(stat['hit'] / stat['total'])} |")
    add("")
    add("提示：表是按召回率从低到高排的，最上面几行就是模型最菜的类别。")
    add("")

    add("## 按 agent（哪个角色最爱凑数）")
    add("")
    add("同一处问题被两个角色都报出来时，只有一条算独立发现，另一条记重复。")
    add("所以「对上标注」会比「命中」大——它统计的是这个角色有没有说到点子上，")
    add("而不是谁抢到了那条标注。")
    add("")
    add("| 角色 | 条目 | 对上标注 | 其中重复 | 未匹配 |")
    add("|---|---|---|---|---|")
    for agent, stat in sorted(
        summary["by_agent"].items(), key=lambda kv: -(kv[1]["total"] - kv[1]["tp"])
    ):
        dup = stat.get("dup", 0)
        add(
            f"| {KIND_LABEL.get(agent, agent)} | {stat['total']} | {stat['tp'] + dup} | "
            f"{dup} | {stat['total'] - stat['tp'] - dup} |"
        )
    add("")

    add("## 逐样本")
    add("")
    add("| 样本 | 标题 | 期望 | 命中 | 条目 | 未匹配 | 重复 | 耗时 | 备注 |")
    add("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        note = r["error"] or (f"agent 出错：{','.join(r['agent_errors'])}" if r["agent_errors"] else "")
        add(
            f"| {r['id']} | {r['title']} | {r['expected_total']} | {r['expected_hit']} | "
            f"{r['items_total']} | {r['items_fp']} | {r.get('items_dup', 0)} | "
            f"{r['elapsed']:.1f}s | {note} |"
        )
    add("")

    add("## 漏报明细")
    add("")
    missed = [(r["id"], h) for r in results for h in r["hits"] if not h["hit"]]
    if not missed:
        add("无。")
    else:
        add("| 样本 | 类型 | 文件 | 埋的问题 |")
        add("|---|---|---|---|")
        for case_id, h in missed:
            add(
                f"| {case_id} | {TYPE_LABEL.get(str(h['type']), h['type'])} | "
                f"{h['file']} | {h['note']} |"
            )
    add("")

    add("## 未匹配条目（需人工判定）")
    add("")
    add("这些条目没有被任何期望问题匹配上。**不要直接当成误报**——")
    add("模型可能发现了真实存在、但我没有标注的问题。逐条判断后，")
    add("要么标成真误报，要么补进 `*.expected.json`（说明是我漏标了）。")
    add("")
    for r in results:
        if not r["fp_items"]:
            continue
        add(f"### 样本 {r['id']}：{r['title']}")
        add("")
        for it in r["fp_items"]:
            body = json.dumps(it["item"], ensure_ascii=False)
            if len(body) > 220:
                body = body[:220] + "…"
            add(f"- [{KIND_LABEL.get(it['kind'], it['kind'])} / {it['agent']}] {body}")
        add("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def load_cases(only: list[str] | None, limit: int | None) -> list[tuple[str, str, dict[str, Any]]]:
    cases: list[tuple[str, str, dict[str, Any]]] = []
    for diff_path in sorted(CASES_DIR.glob("*.diff")):
        case_id = diff_path.stem
        if only and case_id not in only:
            continue
        expected_path = CASES_DIR / f"{case_id}.expected.json"
        if not expected_path.exists():
            print(f"[跳过] {case_id}：缺少 {expected_path.name}")
            continue
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        cases.append((case_id, diff_path.read_text(encoding="utf-8"), expected))
    if limit:
        cases = cases[:limit]
    return cases


async def main_async(args: argparse.Namespace) -> int:
    # 只重排报告，不重新调用模型：调格式改完用它刷一遍，省钱也省时间
    if args.rerender:
        src = Path(args.rerender)
        data = json.loads(src.read_text(encoding="utf-8"))
        results = data["results"]
        summary = summarize(results)
        md_path = src.with_suffix(".md")
        md_path.write_text(
            render_markdown(summary, results, data.get("meta", {})),
            encoding="utf-8",
            newline="\n",
        )
        print(f"已按 {src.name} 重排报告：{md_path}")
        return 0

    # 只按新标注离线重算，不调模型：改标注/改别名都走这条，省钱且可复现
    if args.rematch:
        src = Path(args.rematch)
        data = json.loads(src.read_text(encoding="utf-8"))
        results = data["results"]
        for r in results:
            expected_path = CASES_DIR / f"{r['id']}.expected.json"
            if not expected_path.exists():
                print(f"[跳过] {r['id']}：缺少 {expected_path.name}")
                continue
            if r.get("items") is None:
                print(f"[警告] {r['id']}：json 里没有全量条目，只能用未匹配项重算")
            apply_score(r, json.loads(expected_path.read_text(encoding="utf-8")))

        summary = summarize(results)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        meta = dict(data.get("meta", {}))
        meta["复核时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta["复核基线"] = src.name
        meta["说明"] = "标注修正后离线重算，模型输出未变"

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        md_path = REPORTS_DIR / f"run-{stamp}.md"
        json_path = REPORTS_DIR / f"run-{stamp}.json"
        md_path.write_text(
            render_markdown(summary, results, meta), encoding="utf-8", newline="\n"
        )
        json_path.write_text(
            json.dumps(
                {"meta": meta, "summary": summary, "results": results},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(
            f"重算完成：命中率 {_pct(summary['recall'])}"
            f"（{summary['expected_hit']}/{summary['expected_total']}）"
            f" | 缺陷条目误报率 {_pct(summary['fp_rate_defect'])}"
            f"（{summary['items_defect_fp']}/{summary['items_defect_total'] - summary['items_defect_dup']}）"
            f" | 重复提出 {summary['items_dup']} 条"
        )
        print(f"报告：{md_path}")
        print(f"机读：{json_path}")
        return 0

    # --stub 时强制走假模型，必须在 Settings 第一次实例化之前设置
    if args.stub:
        os.environ["PRSQUAD_LLM_PROVIDER"] = "stub"
    from prsquad import config as prsquad_config

    prsquad_config._settings = None  # 丢掉可能已被读到的旧配置
    from prsquad.config import get_settings
    from prsquad.main import _run_review

    # main.py 里开了 root INFO 日志，会把每次 HTTP 请求都打出来，压掉
    import logging

    for noisy in ("httpx", "httpx2", "httpcore", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    settings = get_settings()
    provider = settings.llm_provider
    model = settings.openai_model if provider == "openai" else "stub"

    cases = load_cases(
        [c.strip() for c in args.only.split(",")] if args.only else None, args.limit
    )
    if not cases:
        print(f"{CASES_DIR} 下没有可用的样本。先跑：python eval/build_cases.py")
        return 1

    kinds = tuple(k.strip() for k in args.kinds.split(",") if k.strip())
    unknown = [k for k in kinds if k not in KIND_LABEL]
    if unknown:
        print(f"--kinds 里有未知取值：{unknown}，可选 {list(KIND_LABEL)}")
        return 1

    print(f"模型：{provider} / {model}")
    print(f"样本：{len(cases)} 份，统计条目类型：{', '.join(kinds)}")
    print("-" * 78)

    results: list[dict[str, Any]] = []
    for index, (case_id, diff, expected) in enumerate(cases, start=1):
        result = await run_case(
            case_id,
            diff,
            expected,
            run_review=_run_review,
            kinds=kinds,
            timeout=args.timeout,
        )
        results.append(result)
        status = "ERR" if result["error"] else "ok "
        print(
            f"[{status}] {index:2d}/{len(cases)} {case_id} {result['title'][:14]:<16}"
            f" 命中 {result['expected_hit']}/{result['expected_total']}"
            f"  条目 {result['items_total']:2d}（未匹配 {result['items_fp']:2d}"
            f" / 重复 {result.get('items_dup', 0):2d}）"
            f"  {result['elapsed']:5.1f}s"
            + (f"  {result['error']}" if result["error"] else ""),
            flush=True,
        )
        if args.sleep:
            await asyncio.sleep(args.sleep)

    summary = summarize(results)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    print("-" * 78)
    print(
        f"命中率 {_pct(summary['recall'])}（{summary['expected_hit']}/{summary['expected_total']}）"
        f" | 样本全中 {summary['cases_all_hit']}/{summary['scored_cases']}"
        f" | 缺陷条目误报率 {_pct(summary['fp_rate_defect'])}"
        f"（{summary['items_defect_fp']}/{summary['items_defect_total'] - summary['items_defect_dup']}）"
        f" | 重复提出 {summary['items_dup']} 条"
        f" | 平均 {summary['avg_elapsed']:.1f}s"
    )

    if args.no_save:
        return 0

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "模型": f"{provider} / {model}",
        "样本来源": "eval/cases（人工埋坑，synthetic）",
    }
    md_path = REPORTS_DIR / f"run-{stamp}.md"
    json_path = REPORTS_DIR / f"run-{stamp}.json"

    md_path.write_text(
        render_markdown(summary, results, meta), encoding="utf-8", newline="\n"
    )
    json_path.write_text(
        json.dumps(
            {"meta": meta, "summary": summary, "results": results},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"报告：{md_path}")
    print(f"机读：{json_path}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="PRSquad 评估跑批")
    parser.add_argument("--stub", action="store_true", help="强制用假模型（零成本，只验证脚本）")
    parser.add_argument("--only", default=None, help="只跑指定样本，逗号分隔，如 001,005")
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 份")
    parser.add_argument("--timeout", type=float, default=180.0, help="单份超时秒数")
    parser.add_argument("--sleep", type=float, default=0.0, help="每份之间的间隔秒数，规避限流")
    parser.add_argument(
        "--kinds",
        default="comments,findings",
        help="哪些产出算「问题条目」，默认 comments,findings",
    )
    parser.add_argument("--no-save", action="store_true", help="不写报告文件，只看终端输出")
    parser.add_argument(
        "--rerender",
        default=None,
        metavar="JSON",
        help="不跑模型，只按已有的 run-*.json 重新生成 .md 报告",
    )
    parser.add_argument(
        "--rematch",
        default=None,
        metavar="JSON",
        help="不跑模型，按当前 expected.json / TAXONOMY 重新匹配并出报告（复核标注时用）",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
