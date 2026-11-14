"""The view validator is what stands between the model's judgement and invented
structure. Test the gate with hand-built bad output (no API needed)."""

from __future__ import annotations

import asyncio
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine import build_index
from engine.plan import build_inventory, heuristic_views, validate_views

PYRIGHT = HERE / "node_modules" / "pyright" / "langserver.index.js"
WEBAPP = HERE / "spike" / "webapp"


def check(label: str, passed: bool) -> bool:
    print(f"  {'ok  ' if passed else 'FAIL'} {label}")
    return passed


def run_gate(idx) -> int:
    results: list[bool] = []
    real = sorted(idx.symbols)
    a, b, c = real[0], real[1], real[2]

    print("=== a truthful view passes untouched ===")
    good = {
        "title": "t", "summary": "s",
        "views": [{"kind": "path", "title": "flow",
                   "nodes": [{"symbolId": a, "depth": 0},
                             {"symbolId": b, "depth": 1}]}],
    }
    bundle = validate_views(good, idx, "q")
    results.append(check("both nodes kept", bundle.views[0].symbol_ids == [a, b]))
    results.append(check("no rejections", bundle.rejected == []))

    print("\n=== invented symbols are dropped, not repaired ===")
    ghost = {
        "title": "t", "summary": "s",
        "views": [{"kind": "path", "title": "flow",
                   "nodes": [{"symbolId": a},
                             {"symbolId": "app/ghost.py::magic"},
                             {"symbolId": "not_a_symbol"}]}],
    }
    bundle = validate_views(ghost, idx, "q")
    results.append(check("kept the real one", bundle.views[0].symbol_ids == [a]))
    results.append(check("reported both ghosts", len(bundle.rejected) == 2))

    print("\n=== duplicate symbols collapse within one view ===")
    dup = {
        "title": "t", "summary": "s",
        "views": [{"kind": "crosscut", "title": "x",
                   "nodes": [{"symbolId": a, "group": "g1"},
                             {"symbolId": a, "group": "g2"}]}],
    }
    bundle = validate_views(dup, idx, "q")
    results.append(check("appeared once", bundle.views[0].symbol_ids == [a]))

    print("\n=== the same symbol may appear in different views ===")
    # this is legitimate: a path and a crosscut are different readings
    multi = {
        "title": "t", "summary": "s",
        "views": [
            {"kind": "path", "title": "flow", "nodes": [{"symbolId": a}]},
            {"kind": "crosscut", "title": "concern",
             "nodes": [{"symbolId": a, "group": "logging"}]},
        ],
    }
    bundle = validate_views(multi, idx, "q")
    results.append(check("kept in both views", len(bundle.views) == 2))
    results.append(check("role_map records both",
                         len(bundle.role_map()[a]) == 2))

    print("\n=== unknown view kinds are rejected ===")
    junk = {
        "title": "t", "summary": "s",
        "views": [
            {"kind": "nonsense", "title": "x", "nodes": [{"symbolId": a}]},
            {"kind": "zones", "title": "ok", "nodes": [{"symbolId": b, "group": "r"}]},
        ],
    }
    bundle = validate_views(junk, idx, "q")
    results.append(check("only valid kind survives", len(bundle.views) == 1))
    results.append(check("kind is zones", bundle.views[0].kind == "zones"))
    results.append(check("reported the bad kind",
                         any("nonsense" in r for r in bundle.rejected)))

    print("\n=== empty views are dropped ===")
    empty = {
        "title": "t", "summary": "s",
        "views": [{"kind": "path", "title": "e", "nodes": []},
                  {"kind": "path", "title": "ok", "nodes": [{"symbolId": c}]}],
    }
    bundle = validate_views(empty, idx, "q")
    results.append(check("only the non-empty view", len(bundle.views) == 1))
    results.append(check("it is the right one", bundle.views[0].symbol_ids == [c]))

    print("\n=== depth is clamped, not trusted ===")
    deep = {
        "title": "t", "summary": "s",
        "views": [{"kind": "calltree", "title": "d",
                   "nodes": [{"symbolId": a, "depth": 999},
                             {"symbolId": b, "depth": -5},
                             {"symbolId": c, "depth": "junk"}]}],
    }
    bundle = validate_views(deep, idx, "q")
    depths = [n.depth for n in bundle.views[0].nodes]
    results.append(check(f"clamped to 0..12: {depths}",
                         all(0 <= d <= 12 for d in depths)))

    print("\n=== view count is capped ===")
    many = {
        "title": "t", "summary": "s",
        "views": [
            {"kind": "path", "title": f"v{i}",
             "nodes": [{"symbolId": real[i % len(real)]}]}
            for i in range(8)
        ],
    }
    bundle = validate_views(many, idx, "q")
    results.append(check(f"at most 3 kept (got {len(bundle.views)})",
                         1 <= len(bundle.views) <= 3))

    print("\n=== heuristic fallback never invents either ===")
    hv = heuristic_views(idx, "trace http requests")
    unknown = [s for s in (sid for v in hv.views for sid in v.symbol_ids)
               if s not in idx.symbols]
    results.append(check("all fallback symbols exist", unknown == []))

    passed = sum(results)
    print(f"\nRESULT: {'PASS' if passed == len(results) else 'FAIL'} ({passed}/{len(results)})")
    return 0 if passed == len(results) else 1


async def main() -> int:
    idx = await build_index(WEBAPP, PYRIGHT, max_call_hierarchy=60)
    print(f"fixture: {len(idx.symbols)} symbols, {len(idx.edges)} edges")
    print(f"inventory: {len(build_inventory(idx))} chars\n")
    return run_gate(idx)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
