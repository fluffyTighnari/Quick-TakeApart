"""A plan is only worth building on top of frozen flows if it is stable.

Three invariants decide that, and all three are enforced in the store rather
than trusted to the UI:

  * no dangling references — every step points at a flow that exists
  * no dependency cycles — a path that requires itself cannot be started
  * decay is reported, not hidden — a step whose flow rotted says so
"""

from __future__ import annotations

import asyncio
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine import build_index
from engine.plans import (PlanStoreError, delete_plan, find_cycle, list_plans,
                          load_plan, plan_health, save_plan, topological_order)
from engine.store import delete_flow, list_flows, save_flow

PYRIGHT = HERE / "node_modules" / "pyright" / "langserver.index.js"
WEBAPP = HERE / "spike" / "webapp"

results: list[bool] = []


def check(label: str, passed: bool) -> bool:
    results.append(passed)
    print(f"  {'ok  ' if passed else 'FAIL'} {label}")
    return passed


def flow_payload(ids: list[str], title: str) -> dict:
    return {
        "query": title, "title": title, "summary": "",
        "views": [{"kind": "path", "title": title,
                   "nodes": [{"symbolId": s, "depth": i} for i, s in enumerate(ids)]}],
    }


def run(root: pathlib.Path, idx) -> None:
    real = sorted(idx.symbols)
    chain_a = [s for s in real if "users" in s][:2] or real[:2]
    chain_b = [s for s in real if "orders" in s][:2] or real[2:4]

    print("\n=== flows to reference ===")
    fa = save_flow(root, idx, flow_payload(chain_a, "A"), name="流A")
    fb = save_flow(root, idx, flow_payload(chain_b, "B"), name="流B")
    check("two flows saved", fa.id != fb.id)

    print("\n=== save a plan whose steps reference those flows ===")
    plan = save_plan(root, {
        "name": "了解请求链路", "intent": "整体了解",
        "items": [
            {"id": "s1", "flowId": fa.id, "goal": "先看 A",
             "granularity": "粗看", "skippable": "日志相关"},
            {"id": "s2", "flowId": fb.id, "goal": "再看 B", "after": ["s1"]},
        ],
    })
    check("plan saved", bool(plan.id))
    check("both steps kept", len(plan.items) == 2)

    reloaded = load_plan(root, plan.id)
    check("loads back", reloaded is not None)
    check("references preserved",
          [i.flow_id for i in reloaded.items] == [fa.id, fb.id])
    check("dependency preserved", reloaded.items[1].after == ["s1"])
    check("granularity preserved", reloaded.items[0].granularity == "粗看")
    check("skippable preserved", reloaded.items[0].skippable == "日志相关")

    print("\n=== order follows dependencies ===")
    # declare s2 first, but s1 must still come first because s2 depends on it
    if len(reloaded.items) >= 2:
        reloaded.items[0], reloaded.items[1] = reloaded.items[1], reloaded.items[0]
        order = topological_order(reloaded)
        check(f"dependency first ({order})", order.index("s1") < order.index("s2"))
        check("all steps present", len(order) == 2)

    print("\n=== a dangling flow reference is refused ===")
    try:
        save_plan(root, {"name": "坏的", "items": [
            {"id": "s1", "flowId": "does-not-exist"}]})
        check("refused dangling reference", False)
    except PlanStoreError as exc:
        check("refused dangling reference", "does not exist" in str(exc))

    print("\n=== a dependency on a missing step is refused ===")
    try:
        save_plan(root, {"name": "坏的", "items": [
            {"id": "s1", "flowId": fa.id, "after": ["ghost"]}]})
        check("refused unknown dependency", False)
    except PlanStoreError as exc:
        check("refused unknown dependency", "unknown step" in str(exc))

    print("\n=== a dependency cycle is refused ===")
    for label, items in [
        ("two-node cycle", [
            {"id": "a", "flowId": fa.id, "after": ["b"]},
            {"id": "b", "flowId": fb.id, "after": ["a"]},
        ]),
        ("self loop", [{"id": "a", "flowId": fa.id, "after": ["a"]}]),
        ("three-node cycle", [
            {"id": "a", "flowId": fa.id, "after": ["c"]},
            {"id": "b", "flowId": fb.id, "after": ["a"]},
            {"id": "c", "flowId": fa.id, "after": ["b"]},
        ]),
    ]:
        try:
            save_plan(root, {"name": label, "items": items})
            check(f"refused {label}", False)
        except PlanStoreError as exc:
            check(f"refused {label}", "cycle" in str(exc))

    print("\n=== an empty plan is refused ===")
    try:
        save_plan(root, {"name": "空的", "items": []})
        check("refused empty plan", False)
    except PlanStoreError:
        check("refused empty plan", True)

    print("\n=== cycle detection directly ===")
    from engine.plans import PlanItem, SavedPlan
    cyc = SavedPlan("x", "x", "", [
        PlanItem("a", fa.id, after=["b"]),
        PlanItem("b", fb.id, after=["a"]),
    ], "", "")
    found = find_cycle(cyc)
    check(f"names the cycle ({found})", found is not None and set(found) == {"a", "b"})
    acyclic = SavedPlan("y", "y", "", [
        PlanItem("a", fa.id), PlanItem("b", fb.id, after=["a"]),
    ], "", "")
    check("acyclic returns None", find_cycle(acyclic) is None)

    print("\n=== rewriting a plan keeps its identity ===")
    updated = save_plan(root, {"name": "改了名", "items": [
        {"id": "s1", "flowId": fb.id, "goal": "换成 B"}]}, plan_id=plan.id)
    check("same id", updated.id == plan.id)
    check("createdAt preserved", updated.created_at == plan.created_at)
    check("name changed", updated.name == "改了名")
    check("step replaced", updated.items[0].flow_id == fb.id)

    print("\n=== health: dangling reference after the flow is deleted ===")
    delete_flow(root, fb.id)
    flows_now = {f.id: f for f in list_flows(root)}
    health = plan_health(load_plan(root, plan.id), flows_now)
    check("step marked dangling", health.dangling == ["s1"])

    print("\n=== health: readable while at least one step survives ===")
    plan2 = save_plan(root, {"name": "两条", "items": [
        {"id": "s1", "flowId": fa.id},
        {"id": "s2", "flowId": fa.id}]})
    flows_now = {f.id: f for f in list_flows(root)}
    h2 = plan_health(load_plan(root, plan2.id), flows_now)
    check("no dangling", h2.dangling == [])
    check("still readable", not h2.unreadable)

    print("\n=== listing and deletion ===")
    listed = list_plans(root)
    check(f"lists plans ({len(listed)})", len(listed) >= 2)
    check("delete works", delete_plan(root, plan2.id))
    check("delete is not repeatable", not delete_plan(root, plan2.id))
    check("traversal refused", load_plan(root, "../../etc/passwd") is None)


async def main() -> int:
    idx = await build_index(WEBAPP, PYRIGHT, max_call_hierarchy=60)
    print(f"fixture: {len(idx.symbols)} symbols")

    sandbox = pathlib.Path(tempfile.mkdtemp(prefix="qta-plans-"))
    try:
        run(sandbox, idx)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    passed = sum(results)
    print(f"\nRESULT: {'PASS' if passed == len(results) else 'FAIL'} ({passed}/{len(results)})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
