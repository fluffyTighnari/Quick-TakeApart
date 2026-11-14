"""Stage one has one job the index must police: a module that cannot be traced to
real symbols is imagination, and imagination is what makes architecture pictures
worthless. Test the gate, and test that the diagram is rebuilt from what survives
rather than taken from the model's string.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine import build_index
from engine.arch import render_mermaid, validate_architecture

PYRIGHT = HERE / "node_modules" / "pyright" / "langserver.index.js"
WEBAPP = HERE / "spike" / "webapp"

results: list[bool] = []


def check(label: str, passed: bool) -> bool:
    results.append(passed)
    print(f"  {'ok  ' if passed else 'FAIL'} {label}")
    return passed


def run(idx) -> None:
    real = sorted(idx.symbols)
    a, b, c, d = real[0], real[1], real[2], real[3]

    print("=== a truthful architecture passes ===")
    good = {
        "title": "t", "overview": "o", "shape": "两个平行区",
        "modules": [
            {"id": "api", "label": "入口", "relation": "parallel", "symbolIds": [a, b]},
            {"id": "core", "label": "核心", "relation": "parallel", "symbolIds": [c]},
        ],
        "edges": [{"source": "api", "target": "core", "kind": "calls"}],
        "mermaid": "graph TD\n api-->core",
    }
    arch = validate_architecture(good, idx)
    check("both modules kept", len(arch.nodes) == 2)
    check("symbols kept", set(arch.nodes[0].symbol_ids) == {a, b})
    check("edge kept", len(arch.edges) == 1)
    check("no rejections", not arch.rejected_nodes and not arch.rejected_symbols)

    print("\n=== a module with no real symbols is dropped ===")
    ghost_mod = dict(good)
    ghost_mod["modules"] = good["modules"] + [
        {"id": "ghost", "label": "不存在的模块", "relation": "x",
         "symbolIds": ["nowhere.py::made_up"]},
    ]
    arch = validate_architecture(ghost_mod, idx)
    check("ghost module dropped", all(n.id != "ghost" for n in arch.nodes))
    check("its bad symbol reported", "nowhere.py::made_up" in arch.rejected_symbols)
    check("module counted as rejected", "ghost" in arch.rejected_nodes)

    print("\n=== a half-real module keeps only the real symbols ===")
    half = dict(good)
    half["modules"] = [
        {"id": "mixed", "label": "半真", "relation": "r",
         "symbolIds": [a, "fake::fn", b]},
    ]
    half["edges"] = []
    arch = validate_architecture(half, idx)
    check("real symbols kept", set(arch.nodes[0].symbol_ids) == {a, b})
    check("fake reported", "fake::fn" in arch.rejected_symbols)

    print("\n=== edges to dropped modules are removed ===")
    dangling = dict(good)
    dangling["modules"] = [
        {"id": "real", "label": "真", "relation": "r", "symbolIds": [a]},
        {"id": "ghost", "label": "假", "relation": "r", "symbolIds": ["x::y"]},
    ]
    dangling["edges"] = [
        {"source": "real", "target": "ghost", "kind": "calls"},
        {"source": "ghost", "target": "real", "kind": "calls"},
    ]
    arch = validate_architecture(dangling, idx)
    check("only one module survives", len(arch.nodes) == 1)
    check("no edge points at nothing", all(
        e.source in {n.id for n in arch.nodes} and e.target in {n.id for n in arch.nodes}
        for e in arch.edges))
    check("both dead edges gone", len(arch.edges) == 0)

    print("\n=== the diagram is rebuilt, not trusted ===")
    lying = dict(good)
    lying["mermaid"] = "graph TD\n ghost-->real\n totally_made_up-->x"
    arch = validate_architecture(lying, idx)
    check("model's mermaid ignored", "totally_made_up" not in arch.mermaid)
    check("only real node ids in the graph",
          all(n.id in arch.mermaid for n in arch.nodes))
    check("ghost id absent from graph", "ghost" not in arch.mermaid)

    print("\n=== bad edge kinds and self loops are refused ===")
    bad = dict(good)
    bad["edges"] = [
        {"source": "api", "target": "core", "kind": "teleports"},
        {"source": "api", "target": "api", "kind": "calls"},
    ]
    arch = validate_architecture(bad, idx)
    check("unknown kind dropped", all(e.kind in
          ("calls", "uses", "owns", "emits", "reads") for e in arch.edges))
    check("self loop dropped", all(e.source != e.target for e in arch.edges))

    print("\n=== duplicate module ids do not silently overwrite ===")
    dup = dict(good)
    dup["modules"] = [
        {"id": "same", "label": "一", "relation": "r", "symbolIds": [a]},
        {"id": "same", "label": "二", "relation": "r", "symbolIds": [b]},
    ]
    dup["edges"] = []
    arch = validate_architecture(dup, idx)
    check("both kept with distinct ids", len(arch.nodes) == 2)
    check("ids are unique", len({n.id for n in arch.nodes}) == 2)

    print("\n=== mermaid output is shaped by relation ===")
    nodes = [
        __import__("engine.arch", fromlist=["ArchNode"]).ArchNode("a", "A", "r", [a]),
        __import__("engine.arch", fromlist=["ArchNode"]).ArchNode("b", "B", "r", [b]),
    ]
    from engine.arch import ArchEdge
    graph = render_mermaid(nodes, [
        ArchEdge("a", "b", "calls"),
        ArchEdge("b", "a", "owns"),
    ])
    check("calls arrow used", "-->" in graph and "==>" in graph)
    check("graph header present", graph.startswith("graph "))

    print("\n=== a flat script is not padded into fake layers ===")
    # the validator cannot invent modules: if the model returns one, one survives
    one = dict(good)
    one["modules"] = [{"id": "all", "label": "全部", "relation": "flat",
                       "symbolIds": real[:5]}]
    one["edges"] = []
    arch = validate_architecture(one, idx)
    check("one module passes through", len(arch.nodes) == 1)
    check("no invented modules added", len(arch.nodes) == 1)


async def main() -> int:
    idx = await build_index(WEBAPP, PYRIGHT, max_call_hierarchy=60)
    print(f"fixture: {len(idx.symbols)} symbols\n")
    run(idx)
    passed = sum(results)
    print(f"\nRESULT: {'PASS' if passed == len(results) else 'FAIL'} ({passed}/{len(results)})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
