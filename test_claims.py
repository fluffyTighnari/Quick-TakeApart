"""The validator is the gate against invented structure; test the gate, not the happy path."""

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


def check(label: str, outcome: bool) -> bool:
    print(f"  {'ok  ' if outcome else 'FAIL'} {label}")
    return outcome


async def run() -> int:
    idx = await build_index(FIXTURE, PYRIGHT, max_call_hierarchy=50)
    results: list[bool] = []

    print("=== mined claims must all verify ===")
    mined = claims_from_edges(idx, [s.id for s in idx.callable_symbols()])
    v = verify(mined, idx)
    print(f"  mined {len(mined)}, {v.summary()}")
    results.append(check("every mined claim verifies", v.ok))
    if not v.ok:
        for r in v.rejected[:5]:
            print(f"    rejected: {r.reason}")

    print("\n=== invented claims must be rejected ===")
    real_edge = ("shop/service.py::OrderService.place", "shop/pricing.py::total")
    fake_edges = [
        # plausible-sounding but non-existent call
        (("shop/service.py::OrderService.place", "shop/repo.py::InMemoryOrderRepo.delete"),
         "reversed/nonexistent callee"),
        # reversed direction of a real edge
        (("shop/pricing.py::total", "shop/service.py::OrderService.place"),
         "reversed real edge"),
        # same-file neighbours that never call each other
        (("shop/pricing.py::_line", "shop/repo.py::InMemoryOrderRepo.save"),
         "unrelated symbols"),
    ]
    for (subj, obj), why in fake_edges:
        claim = Claim("calls", subj, obj, "x.py", 1)
        ver = verify([claim], idx)
        results.append(check(f"rejected: {why}", len(ver.accepted) == 0))

    print("\n=== claims about nonexistent symbols must be rejected ===")
    ghost = Claim("calls", "shop/ghost.py::Ghost.run", real_edge[1], "ghost.py", 1)
    ver = verify([ghost], idx)
    results.append(check("rejected: unknown subject symbol", len(ver.accepted) == 0))

    print("\n=== anchor lines outside the subject must be rejected ===")
    place = idx.symbols[real_edge[0]]
    bad_anchor = Claim("calls", real_edge[0], real_edge[1],
                       place.relpath, place.range.end_line + 50)
    ver = verify([bad_anchor], idx)
    results.append(check("rejected: anchor outside subject range", len(ver.accepted) == 0))

    print("\n=== a real claim with a good anchor must pass ===")
    site = next(e for e in idx.edges
                if e.caller_id == real_edge[0] and e.callee_id == real_edge[1])
    good = Claim("calls", real_edge[0], real_edge[1],
                 place.relpath, site.site.start_line + 1)
    ver = verify([good], idx)
    results.append(check("accepted: real edge with correct anchor", len(ver.accepted) == 1))

    print("\n=== unresolved calls must be reported, not silently dropped ===")
    unresolved_claims = [c for c in mined if c.kind == "unresolved"]
    names = sorted({c.object for c in unresolved_claims})
    results.append(check(f"captured {len(names)} external targets: {names[:6]}",
                         len(unresolved_claims) > 0))

    print("\n=== boundary claims require a real connecting edge ===")
    b_real = Claim("boundary", "shop/service.py::OrderService.place",
                   "shop/pricing.py::total", "x.py", 1)
    b_fake = Claim("boundary", "shop/pricing.py::_line",
                   "shop/api.py::OrderApi.validate", "x.py", 1)
    results.append(check("accepted: boundary with real edge",
                         len(verify([b_real], idx).accepted) == 1))
    results.append(check("rejected: boundary with no edge",
                         len(verify([b_fake], idx).accepted) == 0))

    passed = all(results)
    print(f"\nRESULT: {'PASS' if passed else 'FAIL'} ({sum(results)}/{len(results)})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
