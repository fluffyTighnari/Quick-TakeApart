"""Plans: an ordered list of references to frozen flows.

The difference from a flow is the whole point of stage two. A flow answers "what
happens when X". A plan answers "in what order should I read, and what can I
safely skip". It owns no explanation of its own — every step points at a flow
that was already frozen.

That indirection is what makes stage two stable. If plan items were queries, the
plan would drift every time it was opened. Because they are references to frozen
artifacts, a step renders identically forever (until the flow itself decays,
which the flow reports).

Two invariants are enforced here rather than left to the UI:

  * every referenced flow must exist — a dangling reference is a broken plan
  * dependencies must be acyclic — a reading path that requires itself is not a
    path, and the reader can never start

A third is reported but not enforced: a flow whose symbols have rotted makes the
step degraded. It is still listed, because the reader should decide whether the
rot matters for what they need.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import secrets
import re
from datetime import datetime, timezone

from .store import SavedFlow, list_flows, load_flow

PLAN_DIR = ".qta/plans"
FORMAT_VERSION = 1


class PlanStoreError(RuntimeError):
    pass


@dataclasses.dataclass
class PlanItem:
    """One step. `flow_id` is a reference, never a fresh query."""

    id: str
    flow_id: str
    goal: str = ""
    after: list[str] = dataclasses.field(default_factory=list)
    skippable: str = ""     # what inside this step can be skipped
    granularity: str = ""   # 粗看 / 细读

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "flowId": self.flow_id,
            "goal": self.goal,
            "after": list(self.after),
            "skippable": self.skippable,
            "granularity": self.granularity,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "PlanItem":
        return cls(
            id=str(raw.get("id") or ""),
            flow_id=str(raw.get("flowId") or ""),
            goal=str(raw.get("goal") or ""),
            after=[str(a) for a in (raw.get("after") or [])],
            skippable=str(raw.get("skippable") or ""),
            granularity=str(raw.get("granularity") or ""),
        )


@dataclasses.dataclass
class SavedPlan:
    id: str
    name: str
    intent: str            # what this plan is for: "改这个 bug" / "整体了解"
    items: list[PlanItem]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "intent": self.intent,
            "items": [i.to_dict() for i in self.items],
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "SavedPlan":
        return cls(
            id=str(raw.get("id") or ""),
            name=str(raw.get("name") or ""),
            intent=str(raw.get("intent") or ""),
            items=[PlanItem.from_dict(i) for i in (raw.get("items") or [])],
            created_at=str(raw.get("createdAt") or ""),
            updated_at=str(raw.get("updatedAt") or ""),
        )


@dataclasses.dataclass
class PlanHealth:
    """What is wrong with a plan, as of the current flows."""

    dangling: list[str]        # item ids whose flow is gone
    rotted: list[str]          # item ids whose flow reports missing symbols
    unreadable: bool           # nothing can be read start to finish

    def to_dict(self) -> dict:
        return {
            "dangling": self.dangling,
            "rotted": self.rotted,
            "unreadable": self.unreadable,
        }


def _plans_dir(root: pathlib.Path) -> pathlib.Path:
    return root / PLAN_DIR


def _slug(text: str, limit: int = 24) -> str:
    cleaned = re.sub(r"[^\w一-鿿-]+", "-", text, flags=re.UNICODE).strip("-")
    return cleaned[:limit] or "plan"


def _new_id(name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{_slug(name, 16)}-{secrets.token_hex(2)}"


def _safe_id(plan_id: str) -> bool:
    return bool(plan_id) and not any(c in plan_id for c in ("/", "\\", ".."))


def topological_order(plan: SavedPlan) -> list[str]:
    """Item ids reachable in order, dependencies first.

    Kahn's algorithm. Ties are broken by the order items appear in the plan, so
    the author's sequence is respected where dependencies allow it.
    """
    by_id = {i.id: i for i in plan.items}
    indeg = {i.id: 0 for i in plan.items}
    children: dict[str, list[str]] = {i.id: [] for i in plan.items}

    for item in plan.items:
        for dep in item.after:
            if dep in by_id:
                indeg[item.id] += 1
                children[dep].append(item.id)

    # keep declaration order among ready nodes
    position = {item.id: n for n, item in enumerate(plan.items)}
    ready = sorted((i for i, d in indeg.items() if d == 0), key=position.get)
    out: list[str] = []

    while ready:
        node = ready.pop(0)
        out.append(node)
        for child in children[node]:
            indeg[child] -= 1
            if indeg[child] == 0:
                ready.append(child)
                ready.sort(key=position.get)

    return out


def find_cycle(plan: SavedPlan) -> list[str] | None:
    """Return the item ids stuck in a cycle, or None."""
    order = topological_order(plan)
    if len(order) == len(plan.items):
        return None
    placed = set(order)
    return [i.id for i in plan.items if i.id not in placed]


def validate_plan(plan: SavedPlan, flows: dict[str, SavedFlow]) -> None:
    """Refuse to persist a plan that cannot be read."""
    if not plan.items:
        raise PlanStoreError("a plan with no steps is not a plan")

    seen: set[str] = set()
    for item in plan.items:
        if not item.id:
            raise PlanStoreError("every step needs an id")
        if item.id in seen:
            raise PlanStoreError(f"duplicate step id: {item.id}")
        seen.add(item.id)
        if not item.flow_id:
            raise PlanStoreError(f"step {item.id} references no flow")
        if item.flow_id not in flows:
            raise PlanStoreError(
                f"step {item.id} references a flow that does not exist: {item.flow_id}")

    ids = {i.id for i in plan.items}
    for item in plan.items:
        for dep in item.after:
            if dep not in ids:
                raise PlanStoreError(
                    f"step {item.id} depends on unknown step: {dep}")

    cycle = find_cycle(plan)
    if cycle:
        raise PlanStoreError(
            "dependencies form a cycle: " + " -> ".join(cycle))
    else:
        pass


def plan_health(plan: SavedPlan, flows: dict[str, SavedFlow], idx=None) -> PlanHealth:
    from .store import check_staleness  # local import keeps the module graph flat

    dangling: list[str] = []
    rotted: list[str] = []
    readable = 0

    for item in plan.items:
        flow = flows.get(item.flow_id)
        if flow is None:
            dangling.append(item.id)
            continue
        if idx is not None:
            st = check_staleness(flow, idx)
            if not st.usable:
                rotted.append(item.id)
                continue
        readable += 1

    return PlanHealth(
        dangling=dangling,
        rotted=rotted,
        unreadable=readable == 0 and bool(plan.items),
    )


def save_plan(root: pathlib.Path, payload: dict, *, plan_id: str | None = None,
              name: str | None = None,
              flows: dict[str, SavedFlow] | None = None) -> SavedPlan:
    """Create or replace a plan. Validation runs against the flows on disk."""
    known = flows if flows is not None else {f.id: f for f in list_flows(root)}

    items = [PlanItem.from_dict(i) for i in (payload.get("items") or [])]
    for n, item in enumerate(items):
        if not item.id:
            item.id = f"s{n + 1}"

    title = name or str(payload.get("name") or payload.get("intent") or "未命名计划")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if plan_id:
        existing = load_plan(root, plan_id)
        if existing is None:
            raise PlanStoreError(f"plan not found: {plan_id}")
        plan = SavedPlan(
            id=existing.id,
            name=title.strip(),
            intent=str(payload.get("intent") or existing.intent),
            items=items,
            created_at=existing.created_at,
            updated_at=now,
        )
    else:
        plan = SavedPlan(
            id=_new_id(title),
            name=title.strip(),
            intent=str(payload.get("intent") or ""),
            items=items,
            created_at=now,
            updated_at=now,
        )

    validate_plan(plan, known)

    directory = _plans_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{plan.id}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"version": FORMAT_VERSION, "plan": plan.to_dict()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    tmp.replace(target)
    return plan


def load_plan(root: pathlib.Path, plan_id: str) -> SavedPlan | None:
    if not _safe_id(plan_id):
        return None
    path = _plans_dir(root) / f"{plan_id}.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        body = raw.get("plan") if isinstance(raw, dict) else None
        return SavedPlan.from_dict(body) if isinstance(body, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def list_plans(root: pathlib.Path) -> list[SavedPlan]:
    directory = _plans_dir(root)
    if not directory.is_dir():
        return []
    out: list[SavedPlan] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        plan = load_plan(root, path.stem)
        if plan is not None:
            out.append(plan)
    return out


def delete_plan(root: pathlib.Path, plan_id: str) -> bool:
    if not _safe_id(plan_id):
        return False
    path = _plans_dir(root) / f"{plan_id}.json"
    if not path.is_file():
        return False
    path.unlink()
    return True


def plans_with_health(root: pathlib.Path, idx=None) -> list[dict]:
    flows = {f.id: f for f in list_flows(root)}
    flow_records = {}
    from .store import check_staleness
    for fid, flow in flows.items():
        rec = flow.to_dict()
        rec.pop("fingerprints", None)
        rec["staleness"] = (check_staleness(flow, idx).to_dict()
                            if idx is not None else None)
        flow_records[fid] = rec

    out: list[dict] = []
    for plan in list_plans(root):
        record = plan.to_dict()
        health = plan_health(plan, flows, idx)
        record["health"] = health.to_dict()
        record["order"] = topological_order(plan)
        # inline each referenced flow so the client can render a step without
        # another round trip
        record["flows"] = {
            item.flow_id: flow_records.get(item.flow_id)
            for item in plan.items
            if item.flow_id in flow_records
        }
        out.append(record)
    return out
