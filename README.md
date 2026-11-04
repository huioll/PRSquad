# PRSquad

一个多智能体（multi-agent）代码审查服务：给一份 PR diff，四个专职 agent 并行审各自的领域，
最后汇合成一份 Markdown 报告，可选用 GitHub API 发回到 PR 评论区。

技术栈 **LangGraph + FastAPI + Pydantic**，全部逻辑是显式编排，没有 RAG，也没有隐藏的框架魔法。

> **来源声明**：本项目基于开源项目 [TushGH/PRSquad](https://github.com/TushGH/PRSquad)（MIT）二次开发。
> 上游代码结构、agent 分工、提示词框架沿用原项目；下文「改动」一节逐条列出我做了什么、为什么做。
> 原始 LICENSE 与版权声明保留。

---

## 改动

上游是一个能跑但不好演示的东西：只能打 OpenAI 官方端点、只能通过 Swagger 贴 JSON、
注释和提示词全是英文。我按「能演示、能讲清楚、能验证效果」三个目标动了几处。

| 改动 | 上游的问题 | 现在 |
|---|---|---|
| **接国产模型** | `AsyncOpenAI()` 没传 `base_url`，DeepSeek / 通义 / Moonshot 都调不通 | 新增 `PRSQUAD_OPENAI_BASE_URL` 配置项，填兼容端点即可切换 |
| **单页演示界面** | 只能开 `/docs` 手工构造 JSON，没法演示 | `/` 返回一个手写页面：左边贴 diff，右边出渲染好的报告，零前端依赖 |
| **全量中文** | 注释、提示词、输出全英文 | 注释与系统提示词改中文；`_detect_role()` 的关键词匹配改双语，否则中文提示词下角色识别会失效 |
| **输出章节定序** | 四个 agent 并发返回，汇聚出的数组次序由框架内部决定（实测为 docs → reviewer → security → tests），不是「先结论后补充」的阅读顺序 | `synthesizer` 按 `_ORDER` 重排为 reviewer → security → tests → docs 再渲染 |
| **离线单测** | 无测试 | 补 6 个测试，用 `StubLLM` 全程离线，不读密钥、不发请求，1 秒内跑完 |
| **评估集** | 无任何效果度量，改提示词全靠感觉 | 自建 20 份样本 + 62 条标注 + 跑批脚本，见下文「评估」 |

`_detect_role()` 那一条值得单独说：它是按提示词里的关键词判断「我是哪个 agent」的。
改成中文提示词后关键词全部失配，四个 agent 同时退化成同一个角色，
**而且不报错**——四份报告长得都像模像样，只是内容全是同一份。属于典型的静默错误，
后来补了断言锁住这个行为。

---

## 架构

```
                  ┌──────────────┐
GitHub PR ──────▶ │  /v1/webhook │── 校验 HMAC 签名
                  └──────┬───────┘
                         ▼
               ┌───────────────────┐
               │     LangGraph     │        ┌────────────┐
               │  并行 fan-out /   │───┬──▶ │  reviewer  │──┐
               │      fan-in       │   ├──▶ │  security  │──┤
               │                   │   ├──▶ │   tests    │──┤
               │                   │   └──▶ │    docs    │──┘
               └───────────────────┘                          │
                                                              ▼
                                                    ┌──────────────────┐
                                                    │   synthesizer    │
                                                    │ 拼接 / 定序（无模型）│
                                                    └────────┬─────────┘
                                                             ▼
                                              Markdown 报告 ──▶ GitHub Issue Comment
```

四个 agent 是真并发的（`add_edge(START, agent)` 各连一条，再各连一条到 `synthesize`），
不是串行调用四次。

并发带来一个经典问题：四个节点要往同一份 state 里写自己的报告，
普通 dict 更新会互相覆盖。这里用的是 LangGraph 的 **additive reducer**：

```python
reports: Annotated[list[AgentReport], add]
```

`add` 表示「增量追加」而不是「覆盖」。节点只返回自己那一份，框架负责合并。
这是全项目唯一一个真正需要理解框架的地方，其余都是普通异步 Python。

另外，`synthesizer` 这一步**不调用模型**，只做字符串拼接和排序——五个节点里只有四个花钱。
它也不做跨 agent 去重（比如 reviewer 和 security 可能报同一处问题），
因为去重需要判断「这两句话说的是不是同一件事」，属于语义问题，纯字符串做不到。
真要做就得在这里再加一次模型调用，把成本从 4 次提到 5 次，暂时没做，记在局限里。

另外每个 agent 节点外面包了 `try/except`：单个 agent 抛异常会降级成一条 error 报告，
而不是让整次审查失败——四个里坏一个，另外三个的结果照常返回。

---

## 本地运行

```bash
pip install -e ".[openai,dev]"      # openai 是可选依赖，不装只能用假模型
python -m uvicorn prsquad.main:app --port 8001
```

- <http://127.0.0.1:8001/> 是演示界面
- <http://127.0.0.1:8001/docs> 是 Swagger
- `pytest -q` 应输出 `6 passed`，全部离线，无需密钥

接真实模型：复制 `.env.example` 为 `.env`，填

```ini
PRSQUAD_LLM_PROVIDER=openai
PRSQUAD_OPENAI_API_KEY=sk-...
PRSQUAD_OPENAI_BASE_URL=https://api.deepseek.com/v1
PRSQUAD_OPENAI_MODEL=deepseek-chat
```

配置在进程启动时读取（`lru_cache`），改完要重启服务，热重载不会重新读 env。

想真往 GitHub 发评论，再加 `PRSQUAD_GITHUB_TOKEN` 并把 `PRSQUAD_POST_COMMENTS` 设为 `true`，
Webhook 地址填 `https://<公网地址>/v1/webhook/github`，事件选 **Pull requests**。

---

## 评估

改提示词、调温度、换模型，到底变好还是变差？没有度量就只能靠感觉。所以自建了一套。

### 方法

`eval/cases/` 下 20 份人工构造的 diff，覆盖 28 类缺陷（SQL 拼接、命令注入、硬编码密钥、
`pickle.load`、弱哈希、路径穿越、竞态……），每份配一个 `*.expected.json`，
写明「这处代码有什么问题、属于哪一类、严重程度如何」。

`eval/run_eval.py` 逐份调用完整流水线，把模型输出的每个条目和标注做匹配。
匹配不看措辞，看 `(问题类型, 文件名)` 是否命中，类型走一张别名表——
模型说「SQL injection」、标注写 `sql_injection`，算同一条。
匹配严格按单条 item 做，只有在这份样本一条都没命中时，才退一步看 summary 里有没有提到
（本次 62 条里靠这个兜底命中的只有 1 条）。

匹配是**一对一**的：一条标注最多认领一条输出，一条输出也只能被一条标注认领。
认领不上的那些不白算——单独记为「重复提出」，既不算命中，也不算误判。

三个口径必须分开：

- **缺陷层**（critical / high / major / medium / low）：声称「这里有 bug」，说错了就是误报
- **建议层**（suggestion / nit）：只是改进建议，本来就不该按误报算
- **重复提出**：确实指出了真问题，但同一个问题别的 agent 已经报过

### 结果

| 指标 | 数值 |
|---|---|
| 标注问题数 | 62（初始 36 + 人工复核补充 26） |
| 召回 | 61 / 62 = **98.4%**（其中 1 条靠 summary 兜底） |
| 20 份样本全部命中的 | 19 / 20 |
| 模型输出条目 | 115 条：独立 72 + 重复 43 |
| 缺陷层误报 | 3 / 43 = **7.0%** |
| 建议层未匹配 | 9 / 29 = 31.0% |
| 重复提出 | 43 / 115 = **37.4%** |
| 平均耗时 | 5.4 秒 / 份（deepseek-chat） |

两个数字比想象中难看，但都是真的：

- **缺陷层误报 7.0%**，不是 2.5%。分母是「独立缺陷条目 43 条」，
  不是「全部缺陷声明 79 条」——后者把 36 条重复也算进分母，等于让同一处问题被两个 agent
  各报一次来稀释误报率。
- **重复提出 37.4%**。同一处问题经常被 reviewer 和 security 各报一次，报告里就出现两条。
  这是多 agent 并行的固有代价，也是产品最该改的地方（见「已知局限」）。

### 手工复核

第一次跑完有 46 条「未匹配」，逐条看了一遍，结论记在 `eval/adjudication.md`
（每条都附了代码行号和证据）：

| 判定 | 条数 | 处理 |
|---|---|---|
| 真实缺陷，我漏标了 | 26 | 补进标注（36 → 62） |
| 同一缺陷换了个说法 | 5 | 补匹配别名 |
| 同一缺陷被两个 agent 各报一次 | 3 | 记为重复 |
| 误报 / 非缺陷 | 12 | 保留原判 |
| **合计** | **46** | |

复核后重算，未匹配正好剩 12 条，和判定表里「保留原判」的 12 条一一对上——
说明 46 条每一处都归了类，没有含糊过去的。

其中一条是硬伤：`013` 的代码用的是
`conn.execute("SELECT * FROM users WHERE id = ?", (uid,))`，标准参数化查询，
模型却描述成「f-string 拼接导致 SQL 注入」。它不是没看懂代码，是没看代码。
这类错误比漏报更危险，所以留作误差案例，没有为了好看去改标注。

另外拒绝了两条「补标注」：`001` 的 IDOR 判给了一个 helper 函数，而归属校验本该在调用方做；
`011` 的函数当时刚被替换成 `NotImplementedError`，还没写完。这两条模型判错了，就该算误报。

### 一次匹配口径的纠错

这一节值得单独写，因为它比数字本身更能说明问题。

最早的匹配是「一条标注命中，把所有能匹配上的输出全标成命中」。表面上没问题，直到核对
`013` 时发现：那条**幻觉**（说参数化查询是 f-string 拼接）居然算作命中。
原因是它在文中举例写了 `select * from users where id = ?`，
而「数据过度暴露」的别名里有个光秃秃的 `select *`，就这么蹭上了。

顺着查下去是两类系统性偏差：

- **一条输出能同时认领多条标注**：security 报「敏感数据入日志」，
  同时被 `sensitive-log` 和 `excessive-data-exposure` 认领，一个发现兑两次召回
- **一条标注能认领多条输出**：reviewer 和 security 各报一次同一问题，两条都算 TP，
  误报率被稀释

改法：认领先到先得、一对一；多出来的记 `duplicate`；`select *` 这种过宽的别名
改成必须与「返回 / 暴露 / 客户端」同时出现。

改完之后指标变成：

| 口径 | 召回 | 缺陷层误报 | 结论 |
|---|---|---|---|
| 一对多（旧） | 98.4% | 2.5%（2/79） | TP 里混着重复条目和一条幻觉，虚高 |
| 一对一（新） | 98.4% | 7.0%（3/43） | 还是同一批模型输出，只是不再自我美化 |

召回没变，说明模型该发现的一个没少；变的是误报——之前那 2.5% 是靠分母灌水灌出来的。
**评估脚本自己骗自己，比模型出错更难发现，因为数字看起来更漂亮。**


### 命令

```bash
python eval/build_cases.py                  # 重新生成样本
python eval/run_eval.py --stub --limit 2    # 假模型冒烟，验证管线通不通，不花钱
python eval/run_eval.py                     # 正式跑，报告写到 eval/reports/
python eval/run_eval.py --rematch eval/reports/run-xxx.json   # 改完标注离线重算，不调模型
python eval/run_eval.py --rerender eval/reports/run-xxx.json  # 只重排报告格式
```

`--stub` 也有用：StubLLM 输出固定内容，跑一遍应该 **0% 命中**。
如果它莫名其妙命中了，说明匹配逻辑有 bug，在把「假阳性」算到模型头上。

`--rematch` 是后加出来的：调标注是高频操作，每次都重跑模型既慢又费钱，
所以让脚本从上次落盘的 json 里读回全量条目，离线重新匹配。改一轮标注从 2 分钟降到 1 秒。

标注本身也有讲究。`expected.json` 是生成出来的文件，直接手改它，
下次跑 `build_cases.py` 就全没了。所以复核补充的 26 条不写在 json 里，
而是集中写进脚本的一张 `ADJUDICATED` 表（第 696 行），生成时再合并进去。
标注只有一个数据源，改标注 = 改脚本，不会被覆盖。

---

## 已知局限

写在前面，不藏：

1. **98.4% 不代表真实水平。** 样本是我自己埋的教科书级漏洞，难度偏低，召回已经接近饱和——
   这组样本现在已经区分不出模型好坏，下一步应该换真实 PR 做评测。
2. **diff 超过 8000 字符会被截断**（`_base.py` 里 `diff[:8_000]`）。大 PR 后半段的代码
   模型根本没看到，会漏问题，而且它不知道自己漏了。正确做法是按文件切分后分批审。
3. **没有行级定位。** 报告只说是哪个文件、哪段代码，不能像真实 review 那样挂在具体行上。
   这需要解析 unified diff 拿 hunk 偏移，工作量不小，暂时没做。
4. **不做跨 agent 去重，重复率 37.4%。** 同一处问题常被 reviewer 和 security 各报一次，
   115 条输出里有 43 条是重复的。判断「两句话是不是同一件事」属于语义问题，拼接层解决不了；
   真要做就得在 synthesizer 加一次模型调用，把成本从 4 次提到 5 次。这是当前最该改的一处。
5. **样本和标注都是我一人做的**，复核时也带着自己的判断偏好，客观上存在确认偏差。
6. **没有生产级防护**：无鉴权、无速率限制、无并发队列，只适合本地演示。

---

## 目录结构

```
.
├── prsquad/
│   ├── main.py             FastAPI 应用：webhook + 手动审查两个入口
│   ├── graph.py            LangGraph 连线（fan-out → synthesize）
│   ├── llm.py              LLMClient 协议 + StubLLM + OpenAILLM
│   ├── github.py           GitHub REST 客户端（取 diff、发评论）
│   ├── schemas.py          Pydantic 请求/响应模型
│   ├── config.py           环境变量配置
│   ├── static/index.html   单页演示界面
│   └── agents/
│       ├── _base.py        共享的 agent 节点工厂
│       ├── prompts.py      四个 agent 的系统提示词
│       ├── state.py        共享 GraphState（含 list reducer）
│       └── synthesizer.py  fan-in 汇总
├── eval/
│   ├── build_cases.py      生成 20 份样本与标注
│   ├── run_eval.py         跑批、匹配、报告
│   ├── cases/              样本（* .diff + *.expected.json）
│   ├── reports/            历次报告（不入库）
│   └── adjudication.md     46 条未匹配的逐条判定
├── tests/                  离线测试，全部基于 StubLLM
├── .env.example            配置样例（.env 不入库）
├── .github/workflows/      CI
├── Dockerfile
├── docker-compose.yml
└── LICENSE
```

---

## License

MIT。上游版权声明见 `LICENSE`。
