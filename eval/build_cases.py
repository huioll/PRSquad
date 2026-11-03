"""评估样本生成器。

把下面 CASES 里的内容物化成 eval/cases/ 下的真实文件：
    001.diff            统一 diff 格式的代码变更
    001.expected.json   人工标注的「应该被发现的期望问题」

设计说明：
- 样本全部是**故意埋坑**的（source=synthetic），每个文件都清楚自己埋了什么，
  所以能算出确定的召回率，不依赖别人的标注。
- 也可以直接手工放 .diff / .expected.json 到 cases/ 目录，脚本不会覆盖已有文件，
  除非显式加 --force。

用法：
    python eval/build_cases.py            # 只补齐缺失的样本
    python eval/build_cases.py --force    # 全部重写（会覆盖你手工改过的标注）
"""
from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

CASES_DIR = Path(__file__).parent / "cases"

# 每份样本：id / 标题 / 语言 / diff 正文 / 期望发现的问题
# 问题类型的取值见 run_eval.py 里的 TAXONOMY，两边必须一致。
CASES: list[dict] = [
    {
        "id": "001",
        "title": "用户登录接口改造",
        "language": "python",
        "diff": """
            diff --git a/api/auth.py b/api/auth.py
            --- a/api/auth.py
            +++ b/api/auth.py
            @@ -1,12 +1,26 @@
             import hashlib
            +import sqlite3
             
            +API_KEY = "sk-live-9f2c7b1e4a"
             
            -def login(conn, username, password):
            -    sql = "SELECT id, pwd FROM users WHERE name = ?"
            -    row = conn.execute(sql, (username,)).fetchone()
            -    return row
            +def login(conn, username, password):
            +    sql = f"SELECT id, pwd FROM users WHERE name = '{username}'"
            +    row = conn.execute(sql).fetchone()
            +    if row and row[1] == hashlib.sha256(password.encode()).hexdigest():
            +        return {"user_id": row[0], "api_key": API_KEY}
            +    return None
            +
            +
            +def fetch_profile(conn, user_id):
            +    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        """,
        "issues": [
            {"type": "sql-injection", "file": "api/auth.py", "severity": "critical",
             "note": "用户名用 f-string 直接拼进 SQL，可注入 ' OR '1'='1"},
            {"type": "hardcoded-secret", "file": "api/auth.py", "severity": "high",
             "note": "API_KEY 明文写死在源码里"},
        ],
    },
    {
        "id": "002",
        "title": "报表下载接口",
        "language": "python",
        "diff": """
            diff --git a/api/download.py b/api/download.py
            --- a/api/download.py
            +++ b/api/download.py
            @@ -1,14 +1,22 @@
             import os
             from fastapi import APIRouter
             from fastapi.responses import FileResponse
             
             router = APIRouter()
             BASE = "/srv/reports"
             
            -@router.get("/reports/{name}")
            -def get_report(name: str):
            -    return {"error": "not implemented"}
            +@router.get("/reports")
            +def get_report(name: str):
            +    path = os.path.join(BASE, name)
            +    f = open(path, "rb")
            +    data = f.read()
            +    return FileResponse(path)
        """,
        "issues": [
            {"type": "path-traversal", "file": "api/download.py", "severity": "critical",
             "note": "name 直接拼路径，传 ../../etc/passwd 可读任意文件"},
            {"type": "resource-leak", "file": "api/download.py", "severity": "medium",
             "note": "open() 的文件句柄从未关闭，也没有 with"},
        ],
    },
    {
        "id": "003",
        "title": "数据库备份脚本",
        "language": "python",
        "diff": """
            diff --git a/scripts/backup.py b/scripts/backup.py
            --- a/scripts/backup.py
            +++ b/scripts/backup.py
            @@ -1,10 +1,16 @@
             import os
            +import subprocess
            +import sys
             
            +DB_PASSWORD = "P@ssw0rd2024"
             
            -def backup(target: str) -> None:
            -    raise NotImplementedError
            +def backup(target: str) -> None:
            +    cmd = "mysqldump -uroot -p%s mydb > /backup/%s.sql" % (DB_PASSWORD, target)
            +    subprocess.call(cmd, shell=True)
            +    print("backup done:", target)
        """,
        "issues": [
            {"type": "command-injection", "file": "scripts/backup.py", "severity": "critical",
             "note": "target 拼进 shell 命令且 shell=True，可执行任意命令"},
            {"type": "hardcoded-secret", "file": "scripts/backup.py", "severity": "high",
             "note": "数据库密码明文硬编码"},
        ],
    },
    {
        "id": "004",
        "title": "密码哈希与校验",
        "language": "python",
        "diff": """
            diff --git a/core/password.py b/core/password.py
            --- a/core/password.py
            +++ b/core/password.py
            @@ -1,12 +1,20 @@
            +import hashlib
            +import logging
            +
            +log = logging.getLogger(__name__)
            +
             
             def hash_password(raw: str) -> str:
            -    raise NotImplementedError
            +    return hashlib.md5(raw.encode()).hexdigest()
             
             
             def verify(raw: str, stored: str) -> bool:
            -    raise NotImplementedError
            +    ok = hash_password(raw) == stored
            +    log.info("verify raw=%s stored=%s ok=%s", raw, stored, ok)
            +    return ok
        """,
        "issues": [
            {"type": "weak-hash", "file": "core/password.py", "severity": "high",
             "note": "MD5 无盐哈希存密码，可被彩虹表快速破解"},
            {"type": "sensitive-log", "file": "core/password.py", "severity": "high",
             "note": "明文密码和哈希都写进了日志"},
        ],
    },
    {
        "id": "005",
        "title": "统计接口新增付费率",
        "language": "python",
        "diff": """
            diff --git a/api/stats.py b/api/stats.py
            --- a/api/stats.py
            +++ b/api/stats.py
            @@ -1,12 +1,24 @@
             from fastapi import APIRouter
            +from db import get_conn
             
             router = APIRouter()
             
             
            -@router.get("/stats/ratio")
            -def ratio():
            -    return {"value": 0}
            +@router.get("/stats/ratio")
            +def ratio():
            +    conn = get_conn()
            +    total = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            +    paid = conn.execute("SELECT COUNT(*) FROM orders WHERE paid = 1").fetchone()[0]
            +    return {"value": paid / total}
            +
            +
            +@router.get("/users/{uid}/email")
            +def user_email(uid: int):
            +    conn = get_conn()
            +    row = conn.execute("SELECT email FROM users WHERE id = ?", (uid,)).fetchone()
            +    return {"email": row.email}
        """,
        "issues": [
            {"type": "div-zero", "file": "api/stats.py", "severity": "high",
             "note": "订单表为空时 total=0，paid/total 抛 ZeroDivisionError"},
            {"type": "none-check", "file": "api/stats.py", "severity": "major",
             "note": "uid 不存在时 fetchone() 返回 None，row.email 直接 AttributeError"},
        ],
    },
    {
        "id": "006",
        "title": "配置与插件加载",
        "language": "python",
        "diff": """
            diff --git a/config/loader.py b/config/loader.py
            --- a/config/loader.py
            +++ b/config/loader.py
            @@ -1,12 +1,20 @@
            +import yaml
            +
             
             def load(path: str) -> dict:
            -    raise NotImplementedError
            +    with open(path, "r", encoding="utf-8") as f:
            +        return yaml.load(f, Loader=yaml.Loader)
             
             
             def load_plugins(path: str) -> list:
            -    raise NotImplementedError
            +    try:
            +        with open(path, "rb") as f:
            +            import pickle
            +            return pickle.load(f)
            +    except Exception:
            +        return []
        """,
        "issues": [
            {"type": "unsafe-deserialization", "file": "config/loader.py", "severity": "critical",
             "note": "yaml.Loader 和 pickle.load 都能执行任意代码"},
            {"type": "error-handling", "file": "config/loader.py", "severity": "medium",
             "note": "except Exception 吞掉异常并静默返回空列表，故障不可见"},
        ],
    },
    {
        "id": "007",
        "title": "图片代理接口",
        "language": "python",
        "diff": """
            diff --git a/api/proxy.py b/api/proxy.py
            --- a/api/proxy.py
            +++ b/api/proxy.py
            @@ -1,10 +1,18 @@
            +import httpx
            +from fastapi import APIRouter
            +
            +router = APIRouter()
             
            -@router.get("/fetch")
            -def fetch():
            -    return {}
            +
            +@router.get("/fetch")
            +async def fetch(url: str):
            +    async with httpx.AsyncClient(timeout=10.0) as c:
            +        r = await c.get(url)
            +        return {"status": r.status_code, "body": r.text[:2000]}
        """,
        "issues": [
            {"type": "ssrf", "file": "api/proxy.py", "severity": "high",
             "note": "url 完全由请求方控制，可打到 169.254.169.254 等内网地址"},
        ],
    },
    {
        "id": "008",
        "title": "前端评论渲染",
        "language": "javascript",
        "diff": """
            diff --git a/web/comment.js b/web/comment.js
            --- a/web/comment.js
            +++ b/web/comment.js
            @@ -1,8 +1,16 @@
             export function renderComment(container, comment) {
            -  container.textContent = comment.body;
            +  const html = `
            +    <div class="comment">
            +      <span class="user">${comment.user}</span>
            +      <div class="body">${comment.body}</div>
            +    </div>`;
            +  container.innerHTML = html;
             }
        """,
        "issues": [
            {"type": "xss", "file": "web/comment.js", "severity": "high",
             "note": "用户内容未转义直接 innerHTML，存储型 XSS"},
        ],
    },
    {
        "id": "009",
        "title": "订单查询接口鉴权",
        "language": "python",
        "diff": """
            diff --git a/api/orders.py b/api/orders.py
            --- a/api/orders.py
            +++ b/api/orders.py
            @@ -1,14 +1,26 @@
             from fastapi import APIRouter, Header
             from db import get_conn
             
             router = APIRouter()
             
             
            -@router.get("/orders/{oid}")
            -def get_order(oid: int):
            -    return {}
            +def check_token(token: str | None) -> bool:
            +    if not token:
            +        return True
            +    return token.startswith("tk_")
            +
            +
            +@router.get("/orders/{oid}")
            +def get_order(oid: int, authorization: str | None = Header(default=None)):
            +    if not check_token(authorization):
            +        return {"error": "unauthorized"}
            +    conn = get_conn()
            +    row = conn.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
            +    return dict(row)
        """,
        "issues": [
            {"type": "auth-bypass", "file": "api/orders.py", "severity": "critical",
             "note": "token 为空时 check_token 返回 True，不传凭证即可通过"},
            {"type": "broken-access-control", "file": "api/orders.py", "severity": "critical",
             "note": "只按 id 查订单，未校验订单是否属于当前用户"},
        ],
    },
    {
        "id": "010",
        "title": "动态流分页",
        "language": "python",
        "diff": """
            diff --git a/api/feed.py b/api/feed.py
            --- a/api/feed.py
            +++ b/api/feed.py
            @@ -1,12 +1,22 @@
             from fastapi import APIRouter, Request
             from models import Post, User
             from db import session
             
             router = APIRouter()
             
             
            -@router.get("/feed")
            -def feed():
            -    return []
            +@router.get("/feed")
            +def feed(request: Request):
            +    page = int(request.query_params.get("page", 1))
            +    posts = session.query(Post).offset(page * 20).limit(20).all()
            +    out = []
            +    for p in posts:
            +        author = session.query(User).filter(User.id == p.author_id).first()
            +        out.append({"id": p.id, "title": p.title, "author": author.name})
            +    return out
        """,
        "issues": [
            {"type": "n-plus-one", "file": "api/feed.py", "severity": "major",
             "note": "循环里逐条查作者，20 条动态发 21 次查询"},
            {"type": "boundary", "file": "api/feed.py", "severity": "medium",
             "note": "page 未做范围校验，传负数或超大值会得到异常 offset"},
        ],
    },
    {
        "id": "011",
        "title": "任务重试逻辑",
        "language": "python",
        "diff": """
            diff --git a/worker/retry.py b/worker/retry.py
            --- a/worker/retry.py
            +++ b/worker/retry.py
            @@ -1,12 +1,22 @@
             import logging
            +from db import new_session
             
             log = logging.getLogger(__name__)
             
             
             def run_job(job_id: int) -> bool:
            -    raise NotImplementedError
            +    session = new_session()
            +    try:
            +        job = session.get(job_id)
            +        job.attempts += 1
            +        session.commit()
            +        return True
            +    except:
            +        pass
        """,
        "issues": [
            {"type": "error-handling", "file": "worker/retry.py", "severity": "major",
             "note": "裸 except + pass，失败被完全吞掉，调用方永远拿不到 False"},
            {"type": "resource-leak", "file": "worker/retry.py", "severity": "medium",
             "note": "session 从未 close，连接会逐步耗尽"},
        ],
    },
    {
        "id": "012",
        "title": "库存扣减",
        "language": "python",
        "diff": """
            diff --git a/api/stock.py b/api/stock.py
            --- a/api/stock.py
            +++ b/api/stock.py
            @@ -1,12 +1,24 @@
             from fastapi import APIRouter
             from db import get_conn
             
             router = APIRouter()
             
             
            -@router.post("/stock/deduct")
            -def deduct(sku: str, qty: int):
            -    return {}
            +@router.post("/stock/deduct")
            +def deduct(sku: str, qty: int):
            +    conn = get_conn()
            +    row = conn.execute("SELECT stock FROM items WHERE sku = ?", (sku,)).fetchone()
            +    current = row[0]
            +    if current >= qty:
            +        conn.execute("UPDATE items SET stock = ? WHERE sku = ?", (current - qty, sku))
            +        conn.commit()
            +        return {"ok": True}
            +    return {"ok": False}
        """,
        "issues": [
            {"type": "race-condition", "file": "api/stock.py", "severity": "critical",
             "note": "先读后写不在同一事务/锁内，并发请求会超卖"},
            {"type": "boundary", "file": "api/stock.py", "severity": "high",
             "note": "qty 未校验正负，传负数等于反向加库存"},
        ],
    },
    {
        "id": "013",
        "title": "用户资料查询",
        "language": "python",
        "diff": """
            diff --git a/api/profile.py b/api/profile.py
            --- a/api/profile.py
            +++ b/api/profile.py
            @@ -1,12 +1,20 @@
            +import logging
             from fastapi import APIRouter
             from db import get_conn
             
            +log = logging.getLogger(__name__)
             router = APIRouter()
             
             
            -@router.get("/profile/{uid}")
            -def profile(uid: int):
            -    return {}
            +@router.get("/profile/{uid}")
            +def profile(uid: int):
            +    conn = get_conn()
            +    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
            +    log.info("profile fetch uid=%s payload=%s", uid, dict(row))
            +    return dict(row)
        """,
        "issues": [
            {"type": "broken-access-control", "file": "api/profile.py", "severity": "high",
             "note": "任意 uid 都能查，未校验是否是当前登录用户"},
            {"type": "sensitive-log", "file": "api/profile.py", "severity": "medium",
             "note": "整个用户记录（含手机号、邮箱）打进日志"},
        ],
    },
    {
        "id": "014",
        "title": "审计日志写入",
        "language": "python",
        "diff": """
            diff --git a/core/audit.py b/core/audit.py
            --- a/core/audit.py
            +++ b/core/audit.py
            @@ -1,10 +1,16 @@
             import logging
             
             log = logging.getLogger("audit")
             
             
             def record(action: str, detail: str) -> None:
            -    raise NotImplementedError
            +    line = "action=%s detail=%s" % (action, detail)
            +    with open("/var/log/app/audit.log", "a", encoding="utf-8") as f:
            +        f.write(line + "\\n")
            +    log.info(line)
        """,
        "issues": [
            {"type": "log-injection", "file": "core/audit.py", "severity": "medium",
             "note": "detail 含换行符时可伪造整条审计记录"},
        ],
    },
    {
        "id": "015",
        "title": "连接池查询封装",
        "language": "python",
        "diff": """
            diff --git a/db/pool.py b/db/pool.py
            --- a/db/pool.py
            +++ b/db/pool.py
            @@ -1,12 +1,20 @@
             import psycopg2.pool
             
             pool = psycopg2.pool.SimpleConnectionPool(1, 20, dsn="dbname=app")
             
             
             def query(sql: str, params=None):
            -    raise NotImplementedError
            +    conn = pool.getconn()
            +    cur = conn.cursor()
            +    cur.execute(sql, params or ())
            +    rows = cur.fetchall()
            +    cur.close()
            +    return rows
        """,
        "issues": [
            {"type": "resource-leak", "file": "db/pool.py", "severity": "high",
             "note": "getconn() 后从未 putconn()，池子会被抽干"},
        ],
    },
    {
        "id": "016",
        "title": "邮箱验证码重置",
        "language": "python",
        "diff": """
            diff --git a/api/reset.py b/api/reset.py
            --- a/api/reset.py
            +++ b/api/reset.py
            @@ -1,12 +1,20 @@
            +import random
            +import smtplib
            +
            +SMTP_PASSWORD = "mailpass2024"
            +
             
             def make_code() -> str:
            -    raise NotImplementedError
            +    return str(random.randint(100000, 999999))
             
             
             def send_code(email: str, code: str) -> None:
            -    raise NotImplementedError
            +    with smtplib.SMTP("smtp.example.com", 25) as s:
            +        s.login("noreply@example.com", SMTP_PASSWORD)
            +        s.sendmail("noreply@example.com", email, f"code: {code}")
        """,
        "issues": [
            {"type": "weak-random", "file": "api/reset.py", "severity": "high",
             "note": "random 是伪随机，种子可预测，验证码可被算出来"},
            {"type": "hardcoded-secret", "file": "api/reset.py", "severity": "high",
             "note": "SMTP 密码硬编码在源码里"},
        ],
    },
    {
        "id": "017",
        "title": "文档搜索",
        "language": "python",
        "diff": """
            diff --git a/api/search.py b/api/search.py
            --- a/api/search.py
            +++ b/api/search.py
            @@ -1,12 +1,20 @@
             from fastapi import APIRouter, Request
             from db import get_conn
             
             router = APIRouter()
             
             
            -@router.get("/search")
            -def search(q: str):
            -    return []
            +@router.get("/search")
            +def search(request: Request):
            +    q = request.query_params.get("q", "")
            +    order = request.query_params.get("sort", "id")
            +    offset = int(request.query_params.get("offset", 0))
            +    sql = f"SELECT id, title FROM docs WHERE title LIKE '%{q}%' ORDER BY {order} LIMIT 20 OFFSET {offset}"
            +    return [dict(r) for r in get_conn().execute(sql).fetchall()]
        """,
        "issues": [
            {"type": "sql-injection", "file": "api/search.py", "severity": "critical",
             "note": "q 和 order 都直接拼进 SQL，order 还可用于注入任意语句"},
            {"type": "boundary", "file": "api/search.py", "severity": "medium",
             "note": "offset 未校验，负数会导致数据库报错"},
        ],
    },
    {
        "id": "018",
        "title": "配置缓存读取",
        "language": "python",
        "diff": """
            diff --git a/core/cache.py b/core/cache.py
            --- a/core/cache.py
            +++ b/core/cache.py
            @@ -1,12 +1,20 @@
             from redis import Redis
             
             r = Redis(host="localhost", port=6379)
             
             
             def get_config(key: str) -> dict:
            -    raise NotImplementedError
            +    raw = r.get(key)
            +    parts = raw.decode().split("=")
            +    return {parts[0]: parts[1]}
             
             
             def hit_rate(hits: int, total: int) -> float:
            -    raise NotImplementedError
            +    return hits / total
        """,
        "issues": [
            {"type": "none-check", "file": "core/cache.py", "severity": "high",
             "note": "key 不存在时 raw 为 None，raw.decode() 直接崩"},
            {"type": "div-zero", "file": "core/cache.py", "severity": "medium",
             "note": "total 为 0 时抛 ZeroDivisionError"},
        ],
    },
    {
        "id": "019",
        "title": "服务启动配置",
        "language": "python",
        "diff": """
            diff --git a/main.py b/main.py
            --- a/main.py
            +++ b/main.py
            @@ -1,12 +1,20 @@
             from fastapi import FastAPI
            +from fastapi.middleware.cors import CORSMiddleware
             from api import router
             
             app = FastAPI()
            +app.add_middleware(
            +    CORSMiddleware,
            +    allow_origins=["*"],
            +    allow_credentials=True,
            +    allow_methods=["*"],
            +    allow_headers=["*"],
            +)
             app.include_router(router)
             
             
             if __name__ == "__main__":
            -    app.run()
            +    app.run(host="0.0.0.0", port=8000, debug=True)
        """,
        "issues": [
            {"type": "cors-wildcard", "file": "main.py", "severity": "high",
             "note": "allow_origins=* 且 allow_credentials=True，任意站点都能带凭证请求"},
            {"type": "debug-enabled", "file": "main.py", "severity": "high",
             "note": "生产入口开启 debug，异常页会泄露源码和变量"},
        ],
    },
    {
        "id": "020",
        "title": "附件上传",
        "language": "python",
        "diff": """
            diff --git a/api/upload.py b/api/upload.py
            --- a/api/upload.py
            +++ b/api/upload.py
            @@ -1,12 +1,22 @@
            +import os
            +import shutil
            +from fastapi import APIRouter, UploadFile
            +
            +router = APIRouter()
            +UPLOAD_DIR = "/srv/uploads"
             
            -@router.post("/upload")
            -def upload(file: UploadFile):
            -    return {}
            +
            +@router.post("/upload")
            +def upload(file: UploadFile):
            +    dest = os.path.join(UPLOAD_DIR, file.filename)
            +    with open(dest, "wb") as out:
            +        shutil.copyfileobj(file.file, out)
            +    return {"saved": dest}
        """,
        "issues": [
            {"type": "unrestricted-upload", "file": "api/upload.py", "severity": "high",
             "note": "不校验类型和大小，可传 .py/.php 等可执行文件"},
            {"type": "path-traversal", "file": "api/upload.py", "severity": "critical",
             "note": "filename 可含 ../，能把文件写到上传目录之外"},
        ],
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="生成评估样本文件")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的文件（会丢失手工修改）")
    args = parser.parse_args()

    CASES_DIR.mkdir(parents=True, exist_ok=True)
    written = skipped = 0

    for case in CASES:
        diff_path = CASES_DIR / f"{case['id']}.diff"
        expected_path = CASES_DIR / f"{case['id']}.expected.json"

        if diff_path.exists() and not args.force:
            skipped += 1
            continue

        body = textwrap.dedent(case["diff"]).strip("\n") + "\n"
        # newline="\n" 是必须的：Windows 默认会把 \n 转成 \r\n，diff 里出现 CR
        # 会让按行切分的逻辑多出隐藏字符。
        diff_path.write_text(body, encoding="utf-8", newline="\n")

        payload = {
            "id": case["id"],
            "title": case["title"],
            "language": case["language"],
            "source": "synthetic",
            "issues": case["issues"],
        }
        expected_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        written += 1

    total_issues = sum(len(c["issues"]) for c in CASES)
    print(f"生成 {written} 份，跳过 {skipped} 份 → {CASES_DIR}")
    print(f"样本共 {len(CASES)} 份，标注了 {total_issues} 个期望问题")


if __name__ == "__main__":
    main()
