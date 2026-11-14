"""Stage one's skeleton is only useful if every node is grounded in real code.

These tests pin the validator's honesty rules: ghost nodes disappear, half-real
nodes keep only real symbols, duplicate ids stay distinct, and node explanations
persist on the skeleton instead of being regenerated on every open.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine import build_index
from engine.skeleton import (
    SkeletonError, delete_skeleton, list_skeletons, load_skeleton, save_skeleton,
    skeleton_record, validate_skeleton,
)

PYRIGHT = HERE / "node_modules" / "pyright" / "langserver.index.js"
WEBAPP = HERE / "spike" / "webapp"

results: list[bool] = []


def check(label: str, passed: bool) -> bool:
    results.append(passed)
    print(f"  {'ok  ' if passed else 'FAIL'} {label}")
    return passed


def raw_good(idx) -> dict:
    real = sorted(idx.symbols)
    a, b, c, d = real[0], real[1], real[2], real[3]
    return {
        "title": "主流程",
        "overview": "入口到数据的共享管线。",
        "main": [
            {"id": "entry", "title": "入口", "summary": "接请求。",
             "phase": "入口", "symbolIds": [a, b]},
            {"id": "core", "title": "核心", "summary": "做业务。",
             "phase": "处理", "symbolIds": [c]},
            {"id": "data", "title": "数据", "summary": "落库。",
             "phase": "数据", "symbolIds": [d]},
        ],
        "support": [
            {"id": "log", "title": "日志", "summary": "记录事件。",
             "symbolIds": [a]},
        ],
    }


def run(idx) -> None:
    print("=== a grounded skeleton passes ===")
    sk = validate_skeleton(raw_good(idx), idx, "整体", "track")
    check("main nodes kept", len(sk.main) == 3)
    check("support node kept", len(sk.support) == 1)
    check("files derived from symbols", all(n["files"] for n in sk.main))
    check("links exist for consecutive main nodes", len(sk.links) == 2)
    check("track id attached", sk.track_id == "track")

    print("\n=== ghost nodes are dropped, half-real nodes keep real symbols ===")
    raw = raw_good(idx)
    raw["main"].append({"id": "ghost", "title": "不存在的节点", "summary": "假",
                        "symbolIds": ["nowhere.py::made_up"]})
    raw["main"][0]["symbolIds"] = [sorted(idx.symbols)[0], "fake::fn"]
    sk = validate_skeleton(raw, idx, "", "track")
    check("ghost node gone", all(n["id"] != "ghost" for n in sk.main))
    check("half-real node kept", sk.main[0]["id"] == "entry")
    check("fake symbol gone", "fake::fn" not in sk.main[0]["symbolIds"])

    print("\n=== duplicate ids remain distinct ===")
    raw = raw_good(idx)
    raw["main"] = [
        {"id": "same", "title": "一", "summary": "a",
         "symbolIds": [sorted(idx.symbols)[0]]},
        {"id": "same", "title": "二", "summary": "b",
         "symbolIds": [sorted(idx.symbols)[1]]},
    ]
    sk = validate_skeleton(raw, idx, "", "track")
    check("both nodes kept", len(sk.main) == 2)
    check("ids unique", len({n["id"] for n in sk.main}) == 2)

    print("\n=== no groundable main node is an error, not an empty picture ===")
    raw = raw_good(idx)
    raw["main"] = [{"id": "ghost", "title": "假", "summary": "假",
                    "symbolIds": ["x::y"]}]
    try:
        validate_skeleton(raw, idx, "", "track")
        check("empty skeleton refused", False)
    except SkeletonError:
        check("empty skeleton refused", True)

    print("\n=== node detail persists and is counted ===")
    raw = raw_good(idx)
    sk = validate_skeleton(raw, idx, "", "track")
    sk.main[0]["detail"] = "## 节点定位\n这是入口。"
    sk.main[0]["detailCreatedAt"] = "2026-01-01T00:00:00+00:00"
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        saved = save_skeleton(root, sk)
        loaded = load_skeleton(root, saved.id)
        check("saved skeleton reloads", loaded is not None)
        check("detail survived", bool(loaded and loaded.main[0]["detail"]))
        check("list sees it", len(list_skeletons(root)) == 1)
        record = skeleton_record(loaded, idx)
        check("detail count is one", record["detailCount"] == 1)
        check("staleness is fresh", record["staleness"]["fresh"] is True)
        check("delete works", delete_skeleton(root, saved.id))
        check("gone after delete", load_skeleton(root, saved.id) is None)


async def main() -> int:
    idx = await build_index(WEBAPP, PYRIGHT, max_call_hierarchy=60)
    print(f"fixture: {len(idx.symbols)} symbols\n")
    run(idx)
    passed = sum(results)
    print(f"\nRESULT: {'PASS' if passed == len(results) else 'FAIL'} ({passed}/{len(results)})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
