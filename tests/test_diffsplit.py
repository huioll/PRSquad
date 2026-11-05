"""diffsplit 的单元测试：切文件块、按预算装批、超预算截断。"""
from __future__ import annotations

from prsquad.diffsplit import _TRUNCATED_MARK, pack, split_diff, split_files


def _block(name: str, added: int) -> str:
    """造一个合法的文件块，新增 added 行。"""
    head = (
        f"diff --git a/{name} b/{name}\n"
        f"--- a/{name}\n"
        f"+++ b/{name}\n"
        f"@@ -1,1 +1,{added} @@\n"
    )
    return head + "".join(f"+line_{i} = {i}\n" for i in range(added))


def test_empty_diff_returns_no_block():
    assert split_files("") == []
    assert split_files("   \n\n") == []
    assert split_diff("") == []


def test_split_files_yields_one_block_per_file():
    diff = _block("a.py", 3) + _block("b.py", 5) + _block("c.py", 7)
    blocks = split_files(diff)

    # 回归：第一版把初始的空 current 也收进了 blocks，块数比文件数多 1
    assert len(blocks) == 3
    assert all(b.startswith("diff --git ") for b in blocks)
    assert all(b.strip() for b in blocks)
    assert "".join(blocks) == diff  # 一个字符都不丢


def test_split_files_keeps_unknown_text_as_single_block():
    # 手写补丁片段：没有 diff --git 头，整段算一块
    raw = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"
    blocks = split_files(raw)
    assert blocks == [raw]


def test_pack_does_not_shrink_content():
    blocks = [_block("a.py", 5), _block("b.py", 5)]
    diff = "".join(blocks)
    batches = pack(blocks, budget=10_000)

    assert len(batches) == 1
    assert sum(len(b) for b in batches) == len(diff)


def test_pack_respects_budget_and_keeps_file_whole():
    blocks = [_block(f"f{i}.py", 20) for i in range(6)]
    budget = 700
    batches = pack(blocks, budget=budget)

    assert len(batches) > 1
    assert all(len(b) <= budget for b in batches)
    # 每个文件块完整落在某一个批次里，没有被切成两半
    for block in blocks:
        assert sum(block in b for b in batches) == 1


def test_oversized_block_gets_its_own_batch_and_truncation_mark():
    huge = _block("huge.py", 400)
    small = _block("small.py", 2)
    budget = 500

    batches = pack([small, huge], budget=budget)

    assert len(batches) == 2
    assert batches[0] == small  # 攒着的小块先落盘，没被大文件挤掉
    assert batches[1].startswith(huge[:budget])
    assert batches[1].endswith(_TRUNCATED_MARK)
    assert len(batches[1]) == budget + len(_TRUNCATED_MARK)


def test_split_diff_budget_changes_batch_count():
    diff = "".join(_block(f"f{i}.py", 30) for i in range(8))

    one_shot = split_diff(diff, budget=100_000)
    packed = split_diff(diff, budget=800)

    assert len(one_shot) == 1
    assert len(packed) > 1
    assert sum(len(b) for b in packed) == len(diff)
