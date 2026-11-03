# PRSquad 🧐🛡️🧪📚

> Multi-agent AI code reviewer for GitHub pull requests. Built with **LangGraph**, **FastAPI**, and **Pydantic**. **No RAG** — pure agentic orchestration with tool use.

---

## 本仓库相对上游的改动

本项目基于 [TushGH/PRSquad](https://github.com/TushGH/PRSquad) 二次开发（MIT）。原版是英文注释、只能打 OpenAI 官方端点、没有界面。这里只做了两件最小的事：

| 改动 | 上游的问题 | 现在 |
|---|---|---|
| **接国产模型** | `AsyncOpenAI()` 没传 `base_url`，DeepSeek 用不了 | 新增 `PRSQUAD_OPENAI_BASE_URL` 配置项，填上 DeepSeek / 通义 / Moonshot 的兼容端点即可 |
| **演示界面** | 只能在 Swagger 里贴 JSON，没法演示 | 根路径 `/` 返回单页界面：左侧贴 diff，右侧出渲染后的报告，无任何前端依赖 |

代码结构、提示词流程、四个 agent 的分工都和上游一致，方便对照着读。

```bash
pip install -e ".[openai,dev]"   # openai 是可选依赖，不装就只能用假模型
python -m uvicorn prsquad.main:app --port 8001
```

打开 <http://127.0.0.1:8001/> 即是界面，`/docs` 是接口文档。`pytest -q` 应输出 6 passed，全部离线运行、无需密钥。

## 评估结果

`eval/` 是一套自建评估：20 份人工埋坑的 diff（62 个标注问题，其中 26 条为人工复核后补充）+ 跑批脚本 + 离线重匹配。

| 指标 | 数值 |
|---|---|
| 期望问题数 | 62（原始 36 + 复核补充 26） |
| 召回 | 61/62 = **98.4%** |
| 样本全中 | 18/20 |
| 缺陷条目误报率 | 2/79 = **2.5%** |
| 建议条目（nit/suggestion） | 36 条，其中 9 条未匹配 |
| 平均耗时 | 5.4 秒 / 份 |

```bash
python eval/build_cases.py                  # 生成样本（可手改 cases/*.expected.json）
python eval/run_eval.py --stub --limit 2    # 假模型验证管线，不花钱
python eval/run_eval.py                     # 正式跑，报告写到 eval/reports/
python eval/run_eval.py --rematch eval/reports/run-xxx.json   # 改标注后离线重算，不调模型
python eval/run_eval.py --rerender eval/reports/run-xxx.json  # 只重排报告
```

复核过程记在 `eval/adjudication.md`，46 条未匹配逐条给了证据行和判定：

- **26 条**是真实缺陷但我漏标 → 补进标注
- **5 条**是同一缺陷换说法 → 补匹配别名
- **11 条**确认是误报/非缺陷 → 保留，含一条硬伤：`013` 的代码用的是 `?` 参数化查询，模型却说成 f-string 拼接，属于幻觉
- 未匹配条目从 46 降到 13，缺陷层只剩 2 条

三点必须说明白：

- **98% 不代表真实水平。** 样本是我自己埋的教科书级漏洞（SQL 拼接、`pickle.load`、`shell=True`），
  难度偏低，召回已经接近饱和——**这组样本已经无法区分模型好坏**，下一步得换真实 PR。
- **唯一漏报是 `013` 的越权访问**：同一类型在 `005`、`012` 里都被抓到了，唯独这份漏了。
  说明模型对上下文措辞敏感，比"全漏"更值得研究。
- **误报率只统计缺陷层。** `suggestion` / `nit` 是建议不是缺陷声明，混在一起算会把误报率抬高一倍以上
  （全条目口径下是 11.3%），这个分层本身就是评估设计的一部分。


---

## What it does

When a PR is opened (or you POST to `/v1/review`), four specialist agents run **in parallel** against the diff:

| Agent | Role |
|---|---|
| 🧐 **Reviewer** | Anti-patterns, naming, readability, suggested refactors |
| 🛡️ **Security Auditor** | OWASP-class issues — injection, secret leakage, log injection, weak crypto |
| 🧪 **Test Suggester** | Untested branches, edge cases, async/concurrency gaps |
| 📚 **Doc Writer** | Drafts docstrings for added/changed public symbols |

A fifth **Synthesizer** node fans-in their JSON outputs into a single Markdown PR comment and posts it back to GitHub.

---

## Architecture

```
                ┌──────────────┐
GitHub PR  ─▶   │  /v1/webhook │── parse + verify HMAC
                └──────┬───────┘
                       ▼
              ┌────────────────┐
              │   LangGraph    │      ┌──────────┐
              │ (parallel fan- │  ┌──▶│ reviewer │──┐
              │  out / fan-in) │──┼──▶│ security │──┼──▶ synthesizer ──▶ Markdown
              │                │  ├──▶│  tests   │──┤                       │
              │                │  └──▶│   docs   │──┘                       ▼
              └────────────────┘                              GitHub Issue Comment API
```

State uses an **additive list reducer** (`Annotated[list, add]`) so the four parallel nodes can each append their report without clobbering one another — a clean LangGraph pattern worth knowing.

---

## Run it

### Demo mode (zero secrets needed)

```bash
docker compose up --build

# Trigger a review by hand — uses the deterministic StubLLM, no API costs
curl -X POST http://localhost:8001/v1/review \
  -H 'Content-Type: application/json' \
  -d '{
    "owner": "octocat",
    "repo": "demo",
    "pr_number": 42,
    "diff": "diff --git a/foo.py b/foo.py\n+def x(): pass\n"
  }' | jq -r .markdown
```

### Real mode (OpenAI + GitHub posting)

```bash
export PRSQUAD_LLM_PROVIDER=openai
export PRSQUAD_OPENAI_API_KEY=sk-...
export PRSQUAD_GITHUB_TOKEN=ghp_...
export PRSQUAD_POST_COMMENTS=true
export PRSQUAD_WEBHOOK_SECRET=$(openssl rand -hex 32)
docker compose up --build
```

Then in your GitHub repo settings:
- Webhook URL: `https://<your-public-host>/v1/webhook/github`
- Content type: `application/json`
- Secret: same as `PRSQUAD_WEBHOOK_SECRET`
- Events: **Pull requests**

---

## Repo layout

```
.
├── prsquad/
│   ├── main.py             ← FastAPI app, webhook + manual review endpoints
│   ├── graph.py            ← LangGraph wiring (fan-out → synthesize → end)
│   ├── llm.py              ← LLMClient protocol + StubLLM + OpenAILLM
│   ├── github.py           ← thin GitHub REST client (fetch diff, post comment)
│   ├── schemas.py          ← Pydantic webhook payloads + response models
│   ├── config.py           ← env-driven Settings
│   └── agents/
│       ├── _base.py        ← shared "make_agent_node" factory (DRY)
│       ├── prompts.py      ← all system prompts in one place
│       ├── state.py        ← shared GraphState TypedDict
│       └── synthesizer.py  ← fan-in markdown renderer
├── tests/                  ← graph + API tests, all run against StubLLM
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

---

## Why this matters (resume signal)

- **Agentic AI without RAG** — recruiters often ask "what *else* have you done besides RAG?". This is the answer.
- **Multi-agent orchestration** — the parallel fan-out + reducer pattern is a real LangGraph idiom, not a chain.
- **Production-shaped**: webhook signature verification, env-driven config, swappable LLM provider, honest fallback when secrets aren't set.
- **Testable**: 6 unit tests run in <2s with no network, no secrets — because of the StubLLM.

---

## What I'd add for v2

- **Per-file inline comments** via the GitHub Reviews API (positioning needs unified-diff parsing).
- **LangSmith tracing** for cost & latency observability per agent.
- **Cost-aware LLM routing** — cheap model for first pass, expensive only when severity is high.
- **Walmart Element GenAI** provider next to OpenAI (a 30-line file implementing `LLMClient`).
- **Persistent run history** in SQLite/Postgres so a "redo with different model" button is possible.

---

## License

MIT.
