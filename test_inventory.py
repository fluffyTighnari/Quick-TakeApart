"""The model should not receive the whole index for a narrow slice question.

This test builds a synthetic 300-symbol project and checks that the scoped
inventory keeps the seed + its neighbours, stays deterministic, and is much
smaller than the broad inventory. It also guards the compact stage-one format.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine.model import Edge, Index, Range, Symbol
from engine.plan import build_inventory, build_scoped_inventory

results: list[bool] = []


def check(label: str, passed: bool) -> bool:
    results.append(passed)
    print(f"  {'ok  ' if passed else 'FAIL'} {label}")
    return passed


def build_fake_index() -> Index:
    symbols: dict[str, Symbol] = {}
    edges: list[Edge] = []
    for i in range(300):
        file = f"pkg/mod{i % 12}.py"
        sid = f"{file}::func_{i}"
        r = Range(i % 80, 0, i % 80 + 3, 8)
        symbols[sid] = Symbol(
            id=sid, name=f"func_{i}", qualname=f"func_{i}", relpath=file,
            kind="function", range=r, body_range=r, signature=f"func_{i}(x)",
        )
        if i:
            prev = f"pkg/mod{(i - 1) % 12}.py::func_{i - 1}"
            edges.append(Edge(caller_id=sid, callee_id=prev, site=r, kind="call"))
    return Index(root="/tmp/fake", revision="rev", symbols=symbols, edges=edges)


def run(idx: Index) -> None:
    full = build_inventory(idx)
    compact = build_inventory(idx, compact=True, symbol_budget=900)
    broad = build_scoped_inventory(idx, "整体逻辑")
    focused = build_scoped_inventory(
        idx, "func_42", {"kind": "symbol", "symbolId": "pkg/mod6.py::func_42"})

    check("full inventory has most symbols", "func_299" in full)
    check("compact stage-one inventory drops line ranges", "lines " not in compact)
    check("compact is smaller than full", len(compact) < len(full))
    check("broad scoped inventory is much smaller", len(broad) < len(full) * 0.5)
    check("focused inventory is much smaller", len(focused) < len(full) * 0.4)
    check("focused keeps the seed", "pkg/mod6.py::func_42" in focused)
    check("focused keeps a neighbour", "pkg/mod5.py::func_41" in focused)
    check("focused is deterministic", focused == build_scoped_inventory(
        idx, "func_42", {"kind": "symbol", "symbolId": "pkg/mod6.py::func_42"}))
    check("saving is at least 60% on focused", len(focused) < len(full) * 0.4)


def main() -> int:
    idx = build_fake_index()
    run(idx)
    passed = sum(results)
    print(f"\nRESULT: {'PASS' if passed == len(results) else 'FAIL'} ({passed}/{len(results)})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
