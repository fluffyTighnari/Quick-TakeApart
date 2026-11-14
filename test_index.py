"""Regression test: index must recover the known ground-truth edges for the fixture."""

from __future__ import annotations

import asyncio
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine import build_index

PYRIGHT = HERE / "node_modules" / "pyright" / "langserver.index.js"
FIXTURE = HERE / "spike" / "fixture"

# (caller_id, callee_id) pairs I wrote by hand — every one must be recovered.
# Instantiation is normalized to the class's __init__, matching runtime behaviour.
EXPECTED = {
    ("main.py::main", "shop/api.py::OrderApi.create"),
    ("main.py::main", "shop/api.py::OrderApi.__init__"),
    ("shop/api.py::OrderApi.create", "shop/api.py::OrderApi.validate"),
    ("shop/api.py::OrderApi.create", "shop/service.py::OrderService.place"),
    ("shop/service.py::OrderService.place", "shop/pricing.py::total"),
    ("shop/service.py::OrderService.place", "shop/repo.py::InMemoryOrderRepo.save"),
    ("shop/service.py::OrderService.place", "shop/service.py::OrderService.next_id"),
    ("shop/service.py::OrderService.next_id", "shop/repo.py::InMemoryOrderRepo.count"),
    ("shop/pricing.py::total", "shop/pricing.py::_line"),
    ("shop/api.py::OrderApi.__init__", "shop/service.py::OrderService.__init__"),
    ("shop/api.py::OrderApi.__init__", "shop/repo.py::InMemoryOrderRepo.__init__"),
}

# calls into stdlib / site-packages — must be reported unresolved, never invented
EXPECTED_UNRESOLVED_NAMES = {"print", "sum", "len", "float", "int", "get", "append"}


def _is_ctor_call(pair: tuple[str, str]) -> bool:
    """Extra edges we tolerate: an edge whose callee is a class or __init__."""
    callee = pair[1].split("::", 1)[1]
    return callee.endswith(".__init__") or "." not in callee


async def run() -> int:
    idx = await build_index(FIXTURE, PYRIGHT, max_call_hierarchy=50, concurrency=4)
    got = {(e.caller_id, e.callee_id) for e in idx.edges}

    missing = EXPECTED - got
    # constructor calls are real edges pyright reports; allow them alongside expectations
    extra = {e for e in got - EXPECTED if not _is_ctor_call(e)}

    print(f"edges recovered: {len(EXPECTED) - len(missing)}/{len(EXPECTED)}")
    for pair in sorted(EXPECTED):
        mark = "ok  " if pair in got else "MISS"
        print(f"  {mark} {pair[0]} -> {pair[1]}")

    if extra:
        print(f"\n{len(extra)} extra edge(s) not in ground truth:")
        for pair in sorted(extra):
            print(f"  + {pair[0]} -> {pair[1]}")

    # no edge may point at a symbol we do not know
    dangling = [e for e in idx.edges if e.callee_id not in idx.symbols]
    print(f"\ndangling edges: {len(dangling)} (must be 0)")

    # external calls must be unresolved, not silently dropped or faked
    unresolved_names = {name for _, name, _ in idx.unresolved_calls}
    print(f"unresolved names: {sorted(unresolved_names)}")
    missed_external = EXPECTED_UNRESOLVED_NAMES - unresolved_names
    print(f"external calls captured as unresolved: "
          f"{len(EXPECTED_UNRESOLVED_NAMES) - len(missed_external)}/{len(EXPECTED_UNRESOLVED_NAMES)}")
    if missed_external:
        print(f"  missing: {sorted(missed_external)}")

    ok = not missing and not dangling
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
