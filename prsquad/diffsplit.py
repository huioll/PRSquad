"""按文件切分 diff，解决 _base.py 里 diff[:8000] 硬截断导致大 PR 审不全的问题。

只负责两件事：把 diff 拆成文件块，再把文件块打包成若干个不超过预算的批次。
不碰图、不碰 agent、不调模型——单独一个文件，可以单独测。

用法::

    from .diffsplit import split_diff
    for batch in split_diff(diff):        # 每批 <= 8000 字符
        await llm.complete(system_prompt, batch)
"""
from __future__ import annotations

DEFAULT_BUDGET = 8_000

# 单批内容超出预算、又只有一个文件时，只能截断。加这句话是为了让模型知道
# 「你没看到全部」，而不是像原来那样安静地以为这就是全文。
_TRUNCATED_MARK = "\n... （该文件单个体积超过预算，剩余部分未包含在上述内容中）\n"


def split_files(diff: str) -> list[str]:
    """按 `diff --git` 切成文件块，返回每个文件的完整 diff 片段。

    解析失败（比如不是标准 unified diff）时，整份 diff 当作一个块返回，
    不抛异常——调用方不需要为格式问题写兜底。
    """
    if not diff.strip():
        return []

    blocks: list[list[str]] = []
    current: list[str] = []
    for line in diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            # 只收已经有内容的 current，否则开头会多出一个空块
            if current:
                blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(current)

    # 没有 diff --git 头（比如手写的补丁片段），整体算一块
    return ["".join(b) for b in blocks]


def pack(blocks: list[str], budget: int = DEFAULT_BUDGET) -> list[str]:
    """把文件块装进若干批次，每批字符数不超过 budget。

    规则：
      - 不切碎文件块，保持一个文件的改动完整地被同一个 agent 看到
      - 单个文件块本身超过 budget 时，独占一批并截断，同时插入提示语
    """
    batches: list[str] = []
    buf: list[str] = []
    size = 0

    for block in blocks:
        if len(block) > budget:
            # 先把攒着的批次落盘，再让这个超大文件独占一批
            if buf:
                batches.append("".join(buf))
                buf, size = [], 0
            batches.append(block[:budget] + _TRUNCATED_MARK)
            continue

        if buf and size + len(block) > budget:
            batches.append("".join(buf))
            buf, size = [], 0

        buf.append(block)
        size += len(block)

    if buf:
        batches.append("".join(buf))
    return batches


def split_diff(diff: str, budget: int = DEFAULT_BUDGET) -> list[str]:
    """对外入口：diff -> 若干批次，每批不超过 budget 字符。

    返回空列表表示没有可审的内容。
    """
    return pack(split_files(diff), budget=budget)
