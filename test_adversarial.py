"""Adversarial test: the validator must block plausible but invented structure.

Every case here is something a model would happily write after skimming files.
If any of these pass verification, the whole "grounded explanation" claim fails.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine import build_index
from engine.claims import Claim, claims_from_edges, verify

PYRIGHT = HERE / "node_modules" / "pyright" / "langserver.index.js"
FIXTURE = HERE / "spike" / "fixture"

API = "shop/api.py::OrderApi"


async def run() -> int:
    idx = await build_index(FIXTURE, PYRIGHT, max_call_hierarchy=50)
    results: list[bool] = []

    def check(label: str, passed: bool) -> None:
        results.append(passed)
        print(f"  {'ok  ' if passed else 'FAIL'} {label}")

    print("=== mined claims (should all verify) ===")
    mined = claims_from_edges(idx, [s.id for s in idx.callable_symbols()])
    v = verify(mined, idx)
    print(f"  {len(mined)} mined -> {v.summary()}")
    check("all mined claims verify", v.ok)

    print("\n=== hallucinations a model would produce ===")

    cases: list[tuple[str, Claim]] = [
        ("invented method the class never had",
         Claim("calls", "shop/service.py::OrderService.place",
               "shop/repo.py::InMemoryOrderRepo.delete", "x.py", 1)),

        ("skips a hop: validate does not call total",
         Claim("calls", f"{API}.validate", "shop/pricing.py::total", "x.py", 1)),

        ("backwards call: create is called by main, not the reverse",
         Claim("calls", f"{API}.create", "main.py::main", "x.py", 1)),

        ("claims a caller relationship that is reversed",
         Claim("called_by", "shop/service.py::OrderService.place",
               f"{API}.validate", "x.py", 1)),

        ("invents an external call (only get/sum/print leave this module)",
         Claim("unresolved", "shop/pricing.py::total", "open", "x.py", 1)),

        ("invents a whole file/symbol",
         Claim("calls", "shop/ghost.py::Ghost.run", "shop/pricing.py::total", "x.py", 1)),

        # the subtle one: a real callee, but the anchor points nowhere near the call
        ("real edge with an anchor outside the caller body",
         Claim("calls", "shop/service.py::OrderService.place",
               "shop/pricing.py::_line", "x.py", 1)),

        ("invariant claim with no text",
         Claim("holds", "shop/pricing.py::total", "", "x.py", 9, text="")),
    ]

    for label, claim in cases:
        outcome = verify([claim], idx)
        check(f"blocked — {label}", len(outcome.accepted) == 0)

    print("\n=== a genuinely correct claim must still pass ===")
    real = next(e for e in idx.edges
                if e.caller_id == "shop/service.py::OrderService.place"
                and e.callee_id == "shop/pricing.py::total")
    src = idx.symbols["shop/service.py::OrderService.place"]
    good = Claim("calls", src.id, "shop/pricing.py::total", src.relpath,
                 real.site.start_line + 1)
    check("accepted — real edge, correct anchor",
          len(verify([good], idx).accepted) == 1)

    total = len(results)
    passed = sum(results)
    print(f"\nRESULT: {'PASS' if passed == total else 'FAIL'} ({passed}/{total})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
