"""Designing a plan by talking about it.

The distinction this module exists to enforce: conversation is the *means*, the
plan is the *product*. A chat that produces a paragraph of explanation has
failed, however pleasant it read. So the model is never asked to "explain" or
"advise" — it is asked to emit operations against the current plan, or to say
plainly that it needs something before it can.

Operations are applied server-side to the existing plan, then validated by the
same rules that guard direct edits (no dangling references, no cycles). The
model therefore cannot produce a plan that could not be saved by hand.

Two things the model may do besides editing:

  * `add_step` with a `new_flow` — propose a flow to generate when nothing in the
    library covers what the user asked about. It is marked as needing generation
    rather than silently inventing a flow id, because a reference to a flow that
    does not exist is a broken plan.
  * nothing at all, and put a question in `reply` — when the request is genuinely
    ambiguous, asking beats guessing. This is the only path where the turn
    produces no plan change, and it must be justified in `reply`.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Literal

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

from .model import Index
from .plans import PlanItem, SavedPlan, PlanStoreError, find_cycle, validate_plan
from .store import SavedFlow

OpKind = Literal["add_step", "remove_step", "update_step", "reorder",
                 "set_intent", "set_depth"]
OP_KINDS: tuple[OpKind, ...] = (
    "add_step", "remove_step", "update_step", "reorder", "set_intent",
    "set_depth")

DEFAULT_MODEL = "deepseek-v4.1-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com/anthropic"
DEFAULT_KEY_ENV = "ANTHROPIC_API_KEY"

MAX_OPS = 8


class ChatError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class StepDraft:
    """A step the model wants, before it is bound to a real flow."""

    id: str
    flow_id: str
    goal: str = ""
    after: tuple[str, ...] = ()
    skippable: str = ""
    granularity: str = ""


@dataclasses.dataclass
class PlanOp:
    kind: OpKind
    # add_step
    step: StepDraft | None = None
    # the flow the model wants generated, when nothing in the library fits
    needs_flow: str = ""
    # remove_step / update_step / reorder
    step_id: str = ""
    field: str = ""
    value: str = ""
    order: tuple[str, ...] = ()
    # set_intent
    intent: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class FlowRequest:
    """A flow the model wants generated, with enough context to bind it back.

    A bare description is not enough: once the flow exists, something has to
    decide which step it belongs to. Carrying the step id and goal means the
    binding can be completed without asking the user to re-explain.
    """

    query: str
    step_id: str = ""
    goal: str = ""
    after: tuple[str, ...] = ()
    granularity: str = ""
    skippable: str = ""

    def to_dict(self) -> dict:
        return {
            "query": self.query, "stepId": self.step_id, "goal": self.goal,
            "after": list(self.after), "granularity": self.granularity,
            "skippable": self.skippable,
        }


@dataclasses.dataclass
class ChatTurn:
    reply: str
    ops: list[PlanOp]
    needs_generation: list[FlowRequest]
    rejected_ops: list[str]

    def to_dict(self) -> dict:
        return {
            "reply": self.reply,
            "ops": [
                {"kind": o.kind,
                 "stepId": o.step_id or (o.step.id if o.step else ""),
                 "goal": (o.step.goal if o.step else ""),
                 "flowId": (o.step.flow_id if o.step else o.needs_flow),
                 "field": o.field, "value": o.value,
                 "order": list(o.order), "intent": o.intent}
                for o in self.ops
            ],
            "rejected": self.rejected_ops,
            "needsGeneration": [r.to_dict() for r in self.needs_generation],
        }


PLAN_CHAT_TOOL: dict[str, Any] = {
    "name": "revise_plan",
    "description": (
        "Revise the reading plan in response to what the user said. Emit operations "
        "against the current plan. If the request is ambiguous, emit no operations and "
        "ask in `reply` instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reply": {
                "type": "string",
                "description": (
                    "One or two sentences to the user, in their language. Say what you "
                    "changed, or what you need to know. Never a lecture."
                ),
            },
            "ops": {
                "type": "array",
                "maxItems": MAX_OPS,
                "description": "Changes to apply. Empty only when you are asking a question.",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(OP_KINDS)},
                        "stepId": {
                            "type": "string",
                            "description": "Target step for remove/update. For add, choose a fresh short id.",
                        },
                        "flowId": {
                            "type": "string",
                            "description": "For add_step: an existing saved flow id from the library.",
                        },
                        "newFlowQuery": {
                            "type": "string",
                            "description": (
                                "For add_step when no saved flow fits: describe the flow that "
                                "should be generated, e.g. 'auth 模块的登录校验链路'. "
                                "Leave empty if you supplied flowId."
                            ),
                        },
                        "goal": {"type": "string", "description": "What this step answers."},
                        "after": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Step ids this step depends on.",
                        },
                        "skippable": {"type": "string"},
                        "granularity": {
                            "type": "string",
                            "enum": ["", "粗看", "结构", "细读", "只追链路"],
                        },
                        "field": {
                            "type": "string",
                            "enum": ["goal", "after", "skippable", "granularity", "flowId"],
                            "description": "Which field of an existing step to change.",
                        },
                        "value": {"type": "string", "description": "New value for `field`."},
                        "order": {
                            "type": "array", "items": {"type": "string"},
                            "description": "Full step id order for a reorder.",
                        },
                        "intent": {"type": "string", "description": "New plan purpose."},
                        "depth": {
                            "type": "string",
                            "enum": ["粗看", "结构", "细读", "只追链路"],
                            "description": "New depth contract for the whole track.",
                        },
                    },
                    "required": ["kind"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["reply", "ops"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You help someone design a reading plan for a codebase, by talking with them.

A plan is an ordered list of steps. Each step references a **saved flow** — a frozen
result of an earlier question, like "how does the http path work" or "where is logging
wired". You are given the current plan and the library of saved flows.

Your output is a set of operations on that plan, not advice and not an explanation.
Every turn should either change the plan or ask a question that unblocks the next change.

Rules that matter:

1. Prefer `flowId` from the library. If nothing in it covers what the user asked about,
   use `newFlowQuery` and describe the flow that should be generated — do not invent a
   flow id, and do not quietly substitute a saved flow that answers a different question.
2. When the user's request is ambiguous in a way that changes the plan — unclear
   granularity, unclear where to start, unclear scope — emit no ops and ask in `reply`.
   One question, not a list. This is the only case where no plan change is correct.
3. Steps depend on each other through `after`, not through their order in the list.
   Use dependencies when a step genuinely cannot be read before another.
4. Mark `skippable` when part of a step is real code the user does not need — logging,
   metrics, glue. This is one of the most useful things a plan can say.
5. `granularity` is 粗看 (skim for structure), 结构 (modules and main links), 细读
   (read the code), or 只追链路 (follow one path and skip side channels). Say which,
   because the user asked for a specific depth. If the user names a depth in this
   message, it overrides TRACK DEPTH CONTRACT in the context. Emit a `set_depth` op
   with the new depth so the track contract is updated too.
6. Keep the plan short enough to be followed. If the user is adding a tenth step to a
   plan that already reads as a list of everything, say so in `reply` and suggest which
   steps collapse.
7. Write `reply` and all goal text in the user's language. Be terse — the plan carries
   the content, the reply only says what changed."""


def build_context(plan: SavedPlan | None, flows: list[SavedFlow],
                  library_size: int = 40, depth: str = "") -> str:
    """The plan and its library, rendered deterministically for caching."""
    lines: list[str] = []

    if plan is None:
        lines.append("CURRENT PLAN: (none yet — this will be the first)")
    else:
        lines.append(f"CURRENT PLAN: {plan.name}")
        if plan.intent:
            lines.append(f"PURPOSE: {plan.intent}")
        lines.append(f"STEPS: {len(plan.items)}")
        for item in plan.items:
            bits = [f"- id={item.id}", f"flow={item.flow_id}", f"goal={item.goal or '—'}"]
            if item.after:
                bits.append("after=" + ",".join(item.after))
            if item.granularity:
                bits.append(f"granularity={item.granularity}")
            if item.skippable:
                bits.append(f"skippable={item.skippable}")
            lines.append("  " + "  ".join(bits))
        cycle = find_cycle(plan)
        if cycle:
            lines.append(f"  (WARNING: current plan has a dependency cycle: {', '.join(cycle)})")

    if depth:
        lines.append(f"TRACK DEPTH CONTRACT: {depth}")
    lines.append("")
    lines.append(f"SAVED FLOW LIBRARY ({len(flows)} flows, most recent first):")
    if not flows:
        lines.append("  (empty — every step will need a new flow)")
    for flow in flows[:library_size]:
        ids = sorted({n.get("symbolId") for v in flow.views
                      for n in (v.get("nodes") or []) if n.get("symbolId")})
        kinds = sorted({v.get("kind", "?") for v in flow.views})
        segments = getattr(flow, "segments", None) or []
        span = 0
        for segment in segments:
            try:
                span += max(0, int(segment.get("endLine") or 0)
                            - int(segment.get("startLine") or 0) + 1)
            except (TypeError, ValueError):
                pass
        stale = "" if flow.revision else ""
        lines.append(
            f"  - id={flow.id}  name={flow.name or flow.title}"
            f"  shapes={','.join(kinds)}  symbols={len(ids)}"
            f"  segments={len(segments)}  lines={span}{stale}"
        )
    if len(flows) > library_size:
        lines.append(f"  … and {len(flows) - library_size} older flows")

    return "\n".join(lines)


def parse_turn(raw: Any, plan: SavedPlan | None,
               flow_ids: set[str]) -> ChatTurn:
    """Read the model's operations, dropping anything structurally unusable."""
    reply = str(raw.get("reply") or "").strip()
    rejected: list[str] = []
    ops: list[PlanOp] = []
    needs: list[FlowRequest] = []

    existing = {i.id for i in (plan.items if plan else [])}

    for o_raw in (raw.get("ops") or [])[:MAX_OPS]:
        kind = o_raw.get("kind")
        if kind not in OP_KINDS:
            rejected.append(f"unknown op: {kind}")
            continue

        if kind == "add_step":
            step_id = str(o_raw.get("stepId") or "").strip()
            if not step_id:
                step_id = f"s{len(existing) + len(ops) + 1}"
            flow_id = str(o_raw.get("flowId") or "").strip()
            new_flow = str(o_raw.get("newFlowQuery") or "").strip()

            if flow_id and flow_id not in flow_ids:
                # the model cited a flow that is not in the library
                rejected.append(f"add_step: unknown flow {flow_id}")
                continue
            if not flow_id and not new_flow:
                rejected.append("add_step: neither an existing flow nor a query")
                continue

            after = tuple(str(a) for a in (o_raw.get("after") or []))
            step = StepDraft(
                id=step_id,
                flow_id=flow_id,
                goal=str(o_raw.get("goal") or "").strip(),
                after=after,
                skippable=str(o_raw.get("skippable") or "").strip(),
                granularity=str(o_raw.get("granularity") or "").strip(),
            )
            ops.append(PlanOp(kind="add_step", step=step,
                              needs_flow="" if flow_id else new_flow))
            if not flow_id:
                # carry the step's context so the flow can be bound back once made
                needs.append(FlowRequest(
                    query=new_flow,
                    step_id=step_id,
                    goal=step.goal,
                    after=step.after,
                    granularity=step.granularity,
                    skippable=step.skippable,
                ))
            continue

        if kind == "set_depth":
            value = str(o_raw.get("depth") or o_raw.get("value") or "").strip()
            if value not in ("粗看", "结构", "细读", "只追链路"):
                rejected.append(f"set_depth: bad depth {value}")
                continue
            ops.append(PlanOp(kind="set_depth", value=value))
            continue

        if kind in ("remove_step", "update_step"):
            step_id = str(o_raw.get("stepId") or "").strip()
            if step_id not in existing:
                rejected.append(f"{kind}: no such step {step_id}")
                continue
            if kind == "remove_step":
                ops.append(PlanOp(kind="remove_step", step_id=step_id))
            else:
                field = str(o_raw.get("field") or "").strip()
                if field not in ("goal", "after", "skippable", "granularity", "flowId"):
                    rejected.append(f"update_step: bad field {field}")
                    continue
                value = str(o_raw.get("value") or "").strip()
                if field == "flowId" and value not in flow_ids:
                    rejected.append(f"update_step: unknown flow {value}")
                    continue
                ops.append(PlanOp(kind="update_step", step_id=step_id,
                                  field=field, value=value))
            continue

        if kind == "reorder":
            order = tuple(str(s) for s in (o_raw.get("order") or []))
            if set(order) != existing:
                rejected.append("reorder: order must list exactly the current steps")
                continue
            ops.append(PlanOp(kind="reorder", order=order))
            continue

        if kind == "set_intent":
            intent = str(o_raw.get("intent") or "").strip()
            if not intent:
                rejected.append("set_intent: empty")
                continue
            ops.append(PlanOp(kind="set_intent", intent=intent))

    return ChatTurn(reply=reply, ops=ops, needs_generation=needs,
                    rejected_ops=rejected)


def apply_turn(plan: SavedPlan, turn: ChatTurn) -> tuple[SavedPlan, list[str]]:
    """Apply operations to a copy of the plan. Returns (plan, notes).

    Notes record what actually changed, so the UI can show the effect of a turn
    rather than a paragraph about it.
    """
    items = [dataclasses.replace(i, after=list(i.after)) for i in plan.items]
    by_id = {i.id: i for i in items}
    notes: list[str] = []
    intent = plan.intent

    for op in turn.ops:
        if op.kind == "set_intent":
            intent = op.intent
            notes.append(f"用途改为「{op.intent}」")

        elif op.kind == "set_depth":
            notes.append(f"粒度契约改为「{op.value}」")

        elif op.kind == "add_step" and op.step:
            if op.step.id in by_id:
                notes.append(f"跳过重复步骤 {op.step.id}")
                continue
            if not op.step.flow_id:
                # a step whose flow must be generated first: keep it out of the
                # plan until the flow exists, otherwise the plan has a dead ref
                notes.append(f"待生成流：{op.needs_flow}")
                continue
            item = PlanItem(
                id=op.step.id, flow_id=op.step.flow_id, goal=op.step.goal,
                after=[a for a in op.step.after if a in by_id],
                skippable=op.step.skippable, granularity=op.step.granularity,
            )
            items.append(item)
            by_id[item.id] = item
            notes.append(f"新增一步「{item.goal or item.id}」")

        elif op.kind == "remove_step":
            if op.step_id not in by_id:
                continue
            dropped = by_id.pop(op.step_id)
            items = [i for i in items if i.id != op.step_id]
            for other in items:
                other.after = [a for a in other.after if a != op.step_id]
            notes.append(f"删除「{dropped.goal or dropped.id}」")

        elif op.kind == "update_step":
            item = by_id.get(op.step_id)
            if item is None:
                continue
            if op.field == "goal":
                item.goal = op.value
            elif op.field == "skippable":
                item.skippable = op.value
            elif op.field == "granularity":
                item.granularity = op.value
            elif op.field == "flowId":
                item.flow_id = op.value
            elif op.field == "after":
                item.after = [a.strip() for a in op.value.split(",") if a.strip() in by_id]
            notes.append(f"修改「{item.goal or item.id}」的 {op.field}")

        elif op.kind == "reorder":
            wanted = {sid: n for n, sid in enumerate(op.order)}
            items.sort(key=lambda i: wanted.get(i.id, 999))
            notes.append("重排了步骤顺序")

    updated = SavedPlan(
        id=plan.id, name=plan.name, intent=intent, items=items,
        created_at=plan.created_at, updated_at=plan.updated_at,
    )
    return updated, notes


def load_credentials() -> tuple[str, str, str]:
    from .settings import resolve_credentials
    key, base, model = resolve_credentials()
    if not key:
        raise ChatError(
            "no API key: open API settings in the top bar, or set "
            f"{DEFAULT_KEY_ENV} / QTA_API_KEY"
        )
    return key, base, model


def request_turn(message: str, plan: SavedPlan | None, flows: list[SavedFlow], *,
                 depth: str = "",
                 key: str | None = None, base_url: str | None = None,
                 model: str | None = None, max_tokens: int = 4000) -> ChatTurn:
    if key is None or base_url is None or model is None:
        k, b, m = load_credentials()
        key = key or k
        base_url = base_url or b
        model = model or m

    context = build_context(plan, flows, depth=depth)
    system = [
        {"type": "text", "text": SYSTEM_PROMPT},
        # the plan and library are the stable part; cache them across turns
        {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
    ]

    if anthropic is None:
        raise ChatError("the anthropic package is not installed: pip install anthropic")

    client = anthropic.Anthropic(api_key=key, base_url=base_url)
    try:
        resp = client.messages.create(
            model=model, max_tokens=max_tokens,
            thinking={"type": "disabled"},
            system=system,
            tools=[PLAN_CHAT_TOOL],
            tool_choice={"type": "tool", "name": "revise_plan"},
            messages=[{"role": "user", "content": message}],
        )
    except Exception as exc:
        raise ChatError(f"model call failed: {exc}") from exc

    raw = next((b.input for b in resp.content if b.type == "tool_use"), None)
    if raw is None:
        text = next((b.text for b in resp.content if b.type == "text"), "")
        raise ChatError(f"model returned no operations; text: {text[:160]}")

    return parse_turn(raw, plan, {f.id for f in flows})


def validate_result(plan: SavedPlan, flows: list[SavedFlow]) -> None:
    """The same gate a direct edit passes. A conversation cannot bypass it."""
    validate_plan(plan, {f.id: f for f in flows})


# --- closing the loop: generate the missing flow, then bind it --------------

@dataclasses.dataclass
class BindResult:
    """What happened when a pending request was turned into a real step."""

    step_id: str
    flow_id: str = ""
    flow_name: str = ""
    note: str = ""
    rejected: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.flow_id) and not self.rejected

    def to_dict(self) -> dict:
        return {
            "stepId": self.step_id, "flowId": self.flow_id,
            "flowName": self.flow_name, "note": self.note,
            "rejected": self.rejected,
        }


def bind_generated_flow(request: FlowRequest, flow: SavedFlow,
                        plan: SavedPlan | None) -> BindResult:
    """Attach a freshly generated flow to the step that was waiting for it.

    Three things are checked, and only these. Everything else — whether the flow
    is *good*, whether it answers the question well — is the reader's call. This
    function only refuses bindings that are structurally broken or obviously
    off-target:

      * the flow has symbols at all (an empty flow cannot be a step)
      * the flow has a readable view (no views means nothing to read)
      * the step id is free (silently rebinding an occupied id loses a step)

    A flow that merely answers a *neighbouring* question cannot be detected here.
    Generation is visible to the user right after binding, so the honest move is
    to bind and let them judge, not to guess at coverage from symbol counts.
    """
    step_id = request.step_id or "s1"
    flow_name = flow.name or flow.title

    nodes = [n for v in flow.views for n in (v.get("nodes") or [])]
    symbols = {n.get("symbolId") for n in nodes if n.get("symbolId")}
    if not symbols:
        return BindResult(step_id, rejected="生成的流没有任何符号，无法作为一步")

    readable = any((v.get("nodes") or []) for v in flow.views)
    if not readable:
        return BindResult(step_id, rejected="生成的流没有可读的视图，无法作为一步")

    if plan is not None and any(i.id == step_id for i in plan.items):
        return BindResult(step_id, rejected=f"计划里已经存在步骤 {step_id}")

    return BindResult(
        step_id=step_id, flow_id=flow.id, flow_name=flow_name,
        note=f"生成并绑定「{flow_name}」到 {step_id}",
    )
