"""Conversation designs a plan; it must not be able to sneak past the gate.

Two properties decide whether this layer is trustworthy:

  1. an operation the plan rules forbid (dangling flow, cycle) is refused even
     when it arrives through chat
  2. a turn that changes nothing is legitimate only when it asks a question —
     otherwise the conversation has produced prose instead of a plan
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine import build_index
from engine.plans import SavedPlan, PlanItem, PlanStoreError, find_cycle, validate_plan
from engine.plans_chat import (FlowRequest, apply_turn, bind_generated_flow,
                               build_context, parse_turn, validate_result)
from engine.store import save_flow

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
                   "nodes": [{"symbolId": s, "depth": i}
                             for i, s in enumerate(ids)]}],
    }


def run(idx, root: pathlib.Path) -> None:
    real = sorted(idx.symbols)
    fa = save_flow(root, idx, flow_payload(real[:2], "流A"), name="流A")
    fb = save_flow(root, idx, flow_payload(real[2:4], "流B"), name="流B")
    library = {fa.id, fb.id}

    base_plan = SavedPlan(
        id="p1", name="了解请求链路", intent="整体了解",
        items=[PlanItem("s1", fa.id, goal="先看 A")],
        created_at="", updated_at="",
    )

    print("=== a turn that adds a step ===")
    turn = parse_turn({
        "reply": "加了一步 B。",
        "ops": [{"kind": "add_step", "stepId": "s2", "flowId": fb.id,
                 "goal": "然后看 B", "after": ["s1"],
                 "granularity": "细读", "skippable": "日志"}],
    }, base_plan, library)
    check("one op parsed", len(turn.ops) == 1)
    check("no rejections", turn.rejected_ops == [])

    updated, notes = apply_turn(base_plan, turn)
    check("step added", len(updated.items) == 2)
    new_step = updated.items[1]
    check("goal kept", new_step.goal == "然后看 B")
    check("dependency kept", new_step.after == ["s1"])
    check("granularity kept", new_step.granularity == "细读")
    check("skippable kept", new_step.skippable == "日志")
    check("a note records the change", any("新增" in n for n in notes))
    check("result still satisfies plan rules",
          _valid(updated, {fa.id: fa, fb.id: fb}))

    print("\n=== chat cannot reference a flow that is not in the library ===")
    turn = parse_turn({
        "reply": "x",
        "ops": [{"kind": "add_step", "stepId": "s9",
                 "flowId": "ghost-flow", "goal": "不存在"}],
    }, base_plan, library)
    check("op rejected", len(turn.ops) == 0)
    check("reason names the flow", any("ghost-flow" in r for r in turn.rejected_ops))

    print("\n=== chat cannot create a dependency cycle ===")
    two_step = SavedPlan("p2", "n", "", [
        PlanItem("a", fa.id, after=["b"]),
        PlanItem("b", fb.id, after=["a"]),
    ], "", "")
    turn = parse_turn({"reply": "x", "ops": []}, two_step, library)
    applied, _ = apply_turn(two_step, turn)
    check("cycle detected if chat produced one", find_cycle(applied) is not None)
    try:
        validate_result(applied, list(_flows(fa, fb)))
        check("validate_result refuses the cycle", False)
    except PlanStoreError as exc:
        check("validate_result refuses the cycle", "cycle" in str(exc))

    print("\n=== a step needing a generated flow is held back, not faked ===")
    turn = parse_turn({
        "reply": "需要先给 auth 生成一条流。",
        "ops": [{"kind": "add_step", "stepId": "s3",
                 "newFlowQuery": "auth 模块的登录校验链路",
                 "goal": "看认证怎么走"}],
    }, base_plan, library)
    check("op parsed", len(turn.ops) == 1)
    check("flagged for generation",
          len(turn.needs_generation) == 1
          and turn.needs_generation[0].query == "auth 模块的登录校验链路")
    req = turn.needs_generation[0]
    check("request carries the step it belongs to", req.step_id == "s3")
    check("request carries the goal", req.goal == "看认证怎么走")
    applied, notes = apply_turn(base_plan, turn)
    check("no dead reference added", len(applied.items) == 1)
    check("the gap is reported", any("待生成" in n for n in notes))

    print("\n=== remove, update, reorder, set_intent ===")
    two = SavedPlan("p3", "n", "", [
        PlanItem("a", fa.id, goal="A"),
        PlanItem("b", fb.id, goal="B", after=["a"]),
    ], "", "")

    turn = parse_turn({"reply": "x", "ops": [
        {"kind": "update_step", "stepId": "b", "field": "goal", "value": "改过的 B"},
        {"kind": "set_intent", "intent": "改一个 bug"},
    ]}, two, library)
    applied, notes = apply_turn(two, turn)
    check("goal updated", applied.items[1].goal == "改过的 B")
    check("intent updated", applied.intent == "改一个 bug")

    turn = parse_turn({"reply": "x", "ops": [
        {"kind": "remove_step", "stepId": "a"}]}, two, library)
    applied, notes = apply_turn(two, turn)
    check("step removed", [i.id for i in applied.items] == ["b"])
    check("dependents cleaned up", applied.items[0].after == [])

    turn = parse_turn({"reply": "x", "ops": [
        {"kind": "reorder", "order": ["b", "a"]}]}, two, library)
    applied, _ = apply_turn(two, turn)
    check("order applied", [i.id for i in applied.items] == ["b", "a"])

    print("\n=== a partial reorder is refused ===")
    turn = parse_turn({"reply": "x", "ops": [
        {"kind": "reorder", "order": ["a"]}]}, two, library)
    check("must list every step", len(turn.ops) == 0)
    check("reason given", any("exactly" in r for r in turn.rejected_ops))

    print("\n=== unknown steps and fields are refused ===")
    turn = parse_turn({"reply": "x", "ops": [
        {"kind": "remove_step", "stepId": "nope"},
        {"kind": "update_step", "stepId": "a", "field": "colour", "value": "red"},
        {"kind": "teleport"},
    ]}, two, library)
    check("all three refused", len(turn.ops) == 0)
    check("three reasons", len(turn.rejected_ops) == 3)

    print("\n=== asking without changing anything is allowed ===")
    turn = parse_turn({
        "reply": "你想先看整体，还是先钻某个模块？",
        "ops": [],
    }, two, library)
    check("zero ops accepted", len(turn.ops) == 0)
    check("reply carries the question", "？" in turn.reply)
    applied, notes = apply_turn(two, turn)
    check("plan unchanged", [i.id for i in applied.items] == ["a", "b"])
    check("no notes", notes == [])

    print("\n=== context is deterministic (safe to cache) ===")
    ctx1 = build_context(two, list(_flows(fa, fb)))
    ctx2 = build_context(two, list(_flows(fa, fb)))
    check("same bytes twice", ctx1 == ctx2)
    check("mentions the plan", "CURRENT PLAN" in ctx1)
    check("lists the library", "SAVED FLOW LIBRARY" in ctx1)
    check("includes step ids", "id=a" in ctx1)

    print("\n=== a generated flow binds back to the step that waited for it ===")
    req = FlowRequest(query="auth 链路", step_id="s3", goal="看认证", after=("s1",))
    made = save_flow(root, idx, flow_payload(real[4:6], "生成的 auth 流"),
                     name="生成的 auth 流")
    bind = bind_generated_flow(req, made, base_plan)
    check("bound", bind.ok)
    check("kept the requested step id", bind.step_id == "s3")
    check("records the flow", bind.flow_id == made.id)
    check("note names the step", "s3" in bind.note)

    occupied = SavedPlan("p9", "n", "", [
        PlanItem("s1", fa.id), PlanItem("s3", fb.id)], "", "")
    clash = bind_generated_flow(req, made, occupied)
    check("refuses to overwrite an occupied step", not clash.ok)
    check("says why", "已经存在" in clash.rejected)

    print("\n=== a structurally useless flow is refused ===")
    from engine.store import SavedFlow
    empty = SavedFlow("empty", "空的", "", "", "", [], "", "", {})
    r = bind_generated_flow(req, empty, base_plan)
    check("empty flow refused", not r.ok)
    check("reason given", "没有任何符号" in r.rejected)

    viewless = SavedFlow("noview", "无视图", "", "", "", [
        {"kind": "path", "title": "t", "nodes": []}], "", "", {})
    check("view without nodes refused", not bind_generated_flow(req, viewless, base_plan).ok)

    print("\n=== binding needs no re-asking: the request carries its own context ===")
    turn2 = parse_turn({
        "reply": "需要一条认证的流。",
        "ops": [{"kind": "add_step", "stepId": "s5",
                 "newFlowQuery": "auth 链路", "goal": "看认证",
                 "after": ["s1"], "granularity": "细读"}],
    }, base_plan, library)
    check("one pending request", len(turn2.needs_generation) == 1)
    pending = turn2.needs_generation[0]
    produced = save_flow(root, idx, flow_payload(real[6:9], "另一条 auth 流"),
                         name="另一条 auth 流")
    bind2 = bind_generated_flow(pending, produced, base_plan)
    check("bound from the model's request", bind2.ok)
    check("step id came from the model", bind2.step_id == "s5")

    print("\n=== adding a duplicate step id is ignored, not duplicated ===")
    turn = parse_turn({
        "reply": "x",
        "ops": [{"kind": "add_step", "stepId": "a", "flowId": fb.id, "goal": "dup"}],
    }, two, library)
    applied, notes = apply_turn(two, turn)
    check("only two steps", len(applied.items) == 2)
    check("noted as skipped", any("重复" in n for n in notes))


def _flows(*flows):
    return flows


def _valid(plan, flows) -> bool:
    try:
        validate_plan(plan, flows)
        return True
    except PlanStoreError:
        return False


async def main() -> int:
    idx = await build_index(WEBAPP, PYRIGHT, max_call_hierarchy=60)
    print(f"fixture: {len(idx.symbols)} symbols\n")

    import shutil, tempfile
    sandbox = pathlib.Path(tempfile.mkdtemp(prefix="qta-chat-"))
    try:
        run(idx, sandbox)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    passed = sum(results)
    print(f"\nRESULT: {'PASS' if passed == len(results) else 'FAIL'} ({passed}/{len(results)})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
