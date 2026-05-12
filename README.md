# PRSquad 🧐🛡️🧪📚

> Multi-agent AI code reviewer for GitHub pull requests. Built with **LangGraph**, **FastAPI**, and **Pydantic**. **No RAG** — pure agentic orchestration with tool use.

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
