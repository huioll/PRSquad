# 未匹配条目人工复核记录

> 复核对象：`eval/reports/run-20261103-164852.json`，46 条未匹配条目。
> 判定规则：**能否在 diff 的新增行里指到具体哪一行、且该行确实是缺陷**。
> 指得到 → 补标注；同一缺陷换了说法 → 补匹配别名；指不到或只是风格/优化建议 → 保留为误报。

## 结论汇总

| 判定 | 条数 | 处理 |
|---|---|---|
| 真问题·漏标 | 26 | 补 `expected.json`（共新增 26 条标注，标注总数 36 → 62） |
| 真问题·同义转述 | 5 | 补 `TAXONOMY` 别名，不新增标注 |
| 误报 / 非缺陷 | 11 | 保留为未匹配，计入误报统计 |
| 其中的严重误报 | 1 | `013` 的「SQL 注入」为模型幻觉，见下 |

## 逐条记录

| 样本 | 条目摘要 | 角色·严重度 | 证据行 | 判定 | 动作 |
|---|---|---|---|---|---|
| 001 | 密码比较建议 `compare_digest`、确认加盐 | reviewer·suggestion | `auth.py:+17` `row[1] == hashlib.sha256(...)` | 真问题·漏标 | 补 `timing-attack` / `weak-hash` |
| 001 | `import sqlite3` 未使用 | reviewer·nit | `auth.py:+6` | 非缺陷（风格） | 保留 FP |
| 001 | 无盐 SHA-256 易被彩虹表破解 | security·high | `auth.py:+17` | 真问题·漏标 | 补 `weak-hash` |
| 001 | `fetch_profile` 未校验 id 归属（IDOR） | security·high | `auth.py:+22~23` | 有争议：helper 层，鉴权职责多在调用方 | 保留 FP（记录理由） |
| 002 | 文件不存在时 `open` 抛异常返回 500 | reviewer·suggestion | `download.py:+18` | 真问题·漏标 | 补 `robustness` |
| 003 | `subprocess.call` 返回码未检查，失败仍打印 done | reviewer·major | `backup.py:+15` | 真问题·漏标 | 补 `error-handling` |
| 003 | 导入 `sys` 未使用 | reviewer·nit | `backup.py:+7` | 非缺陷（风格） | 保留 FP |
| 003 | 命令行含明文口令、print 未转义 | security·medium | `backup.py:+14` | 真问题·同义（已标注硬编码口令） | 加别名「明文口令」 |
| 004 | `==` 比较哈希存在时序侧信道 | reviewer·suggestion | `password.py:+18` | 真问题·漏标 | 补 `timing-attack` |
| 004 | 同上（security 角色重复提出） | security·medium | `password.py:+18` | 同上条目 | 计入 `timing-attack` |
| 004 | 日志拼接用户可控 raw，可伪造日志 | security·low | `password.py:+19` | 真问题·漏标 | 补 `log-injection` |
| 005 | `get_conn()` 未关闭/归还，两个接口都漏 | reviewer·major | `stats.py:+16`、`+24` | 真问题·漏标 | 补 `resource-leak` |
| 005 | `/users/{uid}/email` 无鉴权，可枚举邮箱 | reviewer·major | `stats.py:+22` | 真问题·漏标 | 补 `broken-access-control` |
| 005 | 两次 COUNT 可合并为一次 | reviewer·suggestion | `stats.py:+17~18` | 优化建议，非缺陷 | 保留 FP |
| 005 | 同上无鉴权（security 角色重复提出） | security·high | `stats.py:+22` | 同上条目 | 计入 `broken-access-control` |
| 006 | `except Exception` 静默吞掉所有错误 | reviewer·suggestion | `loader.py:+20` | 真问题·已有标注未匹配 | 加别名「静默吞掉」 |
| 007 | 未校验 Content-Type，`r.text` 截断图片 | reviewer·major | `proxy.py:+18` | 真问题·漏标（功能实现错误） | 补 `functional-bug` |
| 007 | `httpx` 异常未捕获，超时直返 500 | reviewer·suggestion | `proxy.py:+17` | 真问题·漏标 | 补 `robustness` |
| 007 | 每次请求新建 `AsyncClient` | reviewer·suggestion | `proxy.py:+16` | 优化建议，非缺陷 | 保留 FP |
| 007 | 未限制响应体大小 | reviewer·nit | `proxy.py:+18` | 优化建议，与 SSRF 场景弱相关 | 保留 FP |
| 009 | `row` 为 None 时 `dict(row)` 抛 TypeError | reviewer·suggestion | `orders.py:+26` | 真问题·漏标 | 补 `none-check` |
| 009 | `conn` 未关闭 | reviewer·suggestion | `orders.py:+24` | 真问题·漏标 | 补 `resource-leak` |
| 009 | 仅判断 `tk_` 前缀即放行，可伪造 | security·medium | `orders.py:+17` | 真问题·同义（已有 auth-bypass 标注） | 加别名「前缀」 |
| 010 | `offset` 用 `page * 20`，page=1 跳过前 20 条 | reviewer·major | `feed.py:+17` | 真问题·漏标 | 补 `logic-error` |
| 010 | `author` 可能为 None，`author.name` 抛错 | reviewer·suggestion | `feed.py:+22` | 真问题·漏标 | 补 `none-check` |
| 011 | 无重试上限、commit 本身可能失败 | reviewer·suggestion | `retry.py:+16~18` | 有争议：函数刚替换 `NotImplementedError`，属功能未写完 | 保留 FP（记录理由） |
| 012 | `row` 为 None 时 `row[0]` 抛 TypeError | reviewer·major | `stock.py:+18` | 真问题·漏标 | 补 `none-check` |
| 012 | `conn` 异常时未关闭/回滚 | reviewer·suggestion | `stock.py:+16` | 真问题·漏标 | 补 `resource-leak` |
| 012 | 扣减库存接口无任何鉴权 | security·medium | `stock.py:+14` | 真问题·漏标 | 补 `broken-access-control` |
| 013 | **声称 SQL 用 f-string 拼接，存在注入** | reviewer·major | `profile.py:+19` 实际为 `WHERE id = ?` 参数化 | **误报（幻觉）** | 保留 FP，作为误差案例 |
| 013 | `dict(None)` 抛 TypeError | reviewer·major | `profile.py:+19~21` | 真问题·漏标 | 补 `none-check` |
| 013 | `SELECT *` 返回全部字段（含手机号） | reviewer·suggestion | `profile.py:+19` | 真问题·漏标 | 补 `excessive-data-exposure` |
| 013 | `conn` 未关闭 | reviewer·suggestion | `profile.py:+18` | 真问题·漏标 | 补 `resource-leak` |
| 013 | 日志拼接 uid 与整行记录，可注入换行 | security·medium | `profile.py:+20` | 真问题·漏标 | 补 `log-injection` |
| 014 | 日志路径硬编码 `/var/log/app`，非 root 或目录不存在即失败 | reviewer·suggestion | `audit.py:+13` | 真问题·漏标 | 补 `robustness` |
| 014 | 每次调用 open/close，高频场景开销大 | reviewer·nit | `audit.py:+13` | 优化建议，非缺陷 | 保留 FP |
| 014 | 同上路径问题 + 无轮转（security 视角） | security·low | `audit.py:+13` | 与 `robustness` 同类 | 计入 `robustness` |
| 015 | 异常时 cursor 不关闭、连接需 rollback | reviewer·suggestion | `pool.py:+14~16` | 真问题·已有标注未匹配 | 加别名「不会被关闭」 |
| 016 | `sendmail` 未设置邮件头 | reviewer·suggestion | `reset.py:+20` | 非缺陷（投递质量建议） | 保留 FP |
| 017 | `order` 直接拼进 ORDER BY | reviewer·major | `search.py:+19` | 真问题·已标注 sql-injection 未匹配 | 加别名「order by」 |
| 017 | `offset` 直接 `int()`，非数字返 500 | reviewer·suggestion | `search.py:+18` | 真问题·漏标 | 补 `robustness` |
| 017 | 丢失 FastAPI 参数声明与自动文档 | reviewer·suggestion | `search.py:+15` | 风格建议 | 保留 FP |
| 018 | 配置值统一按字符串返回 | reviewer·suggestion | `cache.py:+13` | 设计选择，非缺陷 | 保留 FP |
| 019 | `app.run()` 是 Flask 用法，FastAPI 无此方法 | reviewer·suggestion | `main.py:+21` | 真问题·漏标（启动即 AttributeError） | 补 `functional-bug` |
| 020 | `UPLOAD_DIR` 未 `makedirs`，首次上传 FileNotFoundError | reviewer·major | `upload.py:+19` | 真问题·漏标 | 补 `robustness` |
| 020 | 返回 `saved` 暴露服务器绝对路径 | reviewer·suggestion | `upload.py:+21` | 真问题·漏标 | 补 `excessive-data-exposure` |

## 三条值得单独说明

**1. `013` 的 SQL 注入是硬幻觉。** 代码是 `conn.execute("SELECT * FROM users WHERE id = ?", (uid,))`，标准参数化查询。模型却描述成 f-string 拼接。这类"看着像真的、但代码里根本没有"的误报，比漏报危险得多——审查工具如果经常这样，用户会彻底不信任它。

**2. 有两条我判定为"不补标注"，理由要记住。**
- `001` 的 IDOR：`fetch_profile` 是 helper，鉴权可能在上层路由做。**在 helper 层要求归属校验并不成立**，补进来等于用宽松标准抬高分。
- `011` 的"无重试上限"：这个函数刚把 `NotImplementedError` 替换掉，属于功能没写完，不算 review 缺陷。

这两条体现了标注的一条底线：**判断"是不是缺陷"要看上下文职责，不能只看代码长得像不像有漏洞。**

**3. 26 条补标注里，7 条属于同一个模式：`get_conn()` 用完不关。**
它们分散在 `005/009/012/013` 四份样本里。模型每次都发现了——这说明它对"资源未释放"这类模式很敏感，而这类问题在真实代码里恰恰最常见。
