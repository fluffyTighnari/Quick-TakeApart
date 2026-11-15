"""Stage one: the system's parts and how they stand to each other.

Two things separate this from drawing a box diagram by hand:

  * every module must resolve to real symbols. A "user module" that cannot be
    traced to actual definitions is imagination, and imagination is exactly what
    makes an architecture picture useless — anyone can draw a plausible one.
  * the shape is not fixed. Hierarchies, event flows, plugins, pipelines and
    hexagonal layouts are all representable. Forcing every codebase into
    layers-and-arrows produces pictures that are confident and wrong.

So the model chooses the modules and the edges; the index decides whether they
exist. Mermaid carries the shape because it expresses arbitrary graphs in plain
text, and a syntax error is detectable rather than silently misrendered.

Edges are typed because "A calls B" and "A is composed of B" describe very
different architectures. Collapsing them loses the thing the reader came for.
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Any, Literal

from .model import Index
from .store import check_staleness

EdgeKind = Literal["calls", "uses", "owns", "emits", "reads"]
EDGE_KINDS: tuple[EdgeKind, ...] = ("calls", "uses", "owns", "emits", "reads")

# Mermaid arrow styles per relation. Type is carried visually, not just in text.
ARROW = {
    "calls": "-->",
    "uses": "-.->",
    "owns": "==>",
    "emits": "..>>",
    "reads": "---",
}

MAX_MODULES = 14


class ArchError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class ArchNode:
    id: str              # stable slug used in the diagram
    label: str
    relation: str        # what it is: small group of parallel parts / a layer / a service
    symbol_ids: list[str]
    note: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class ArchEdge:
    source: str
    target: str
    kind: EdgeKind
    label: str = ""


@dataclasses.dataclass
class Architecture:
    title: str
    overview: str
    shape: str           # the layout the model chose, in words
    nodes: list[ArchNode]
    edges: list[ArchEdge]
    rejected_nodes: list[str]
    rejected_symbols: list[str]
    mermaid: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "overview": self.overview,
            "shape": self.shape,
            "nodes": [
                {"id": n.id, "label": n.label, "relation": n.relation,
                 "symbolIds": n.symbol_ids, "note": n.note}
                for n in self.nodes
            ],
            "edges": [
                {"source": e.source, "target": e.target,
                 "kind": e.kind, "label": e.label}
                for e in self.edges
            ],
            "mermaid": self.mermaid,
            "rejected": {
                "modules": self.rejected_nodes,
                "symbols": self.rejected_symbols,
            },
        }


ARCH_TOOL: dict[str, Any] = {
    "name": "emit_architecture",
    "description": (
        "Emit the system's modules and the relations between them. Every module "
        "must list real symbol ids copied from the inventory. Also return a Mermaid "
        "diagram matching the modules. Never invent ids."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "overview": {
                "type": "string",
                "description": "Two or three sentences: what this system is, and how its parts relate.",
            },
            "shape": {
                "type": "string",
                "description": (
                    "The layout you chose and why, e.g. 'four parallel zones', "
                    "'a pipeline with three stages', 'event-driven with one hub'. "
                    "Do not default to layers if the code is not layered."
                ),
            },
            "modules": {
                "type": "array",
                "minItems": 2,
                "maxItems": MAX_MODULES,
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Short ASCII slug, used in the diagram: users_api, db_layer.",
                        },
                        "label": {"type": "string", "description": "Human name, in the user's language."},
                        "relation": {
                            "type": "string",
                            "description": "How this part stands to the others: parallel / layer / entry / shared.",
                        },
                        "symbolIds": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Real symbol ids from the inventory that make up this module.",
                        },
                        "note": {"type": "string"},
                    },
                    "required": ["id", "label", "relation", "symbolIds"],
                    "additionalProperties": False,
                },
            },
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "description": "A module id."},
                        "target": {"type": "string", "description": "A module id."},
                        "kind": {"type": "string", "enum": list(EDGE_KINDS)},
                        "label": {"type": "string"},
                    },
                    "required": ["source", "target", "kind"],
                    "additionalProperties": False,
                },
            },
            "mermaid": {
                "type": "string",
                "description": (
                    "A Mermaid graph using the module ids as node ids. Use the arrow "
                    "style you think fits. Keep it renderable: no styling directives."
                ),
            },
        },
        "required": ["title", "overview", "shape", "modules", "edges", "mermaid"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You are describing the architecture of a codebase to someone who has never seen it.

You are given an inventory of symbols extracted by a language server. It is ground truth:
those symbols exist and those calls happen. You decide how the system divides into parts;
you never decide what exists.

Your job has two halves.

1. Divide the system into modules. A module is a group of definitions that belong
   together for a reason a reader would recognise — one responsibility, one boundary.
   It is not a directory. One module may span files; one file may hold several modules.

2. Say how the modules stand to each other. Choose edges that describe the real
   relation, not a generic arrow:

   calls — one module invokes the other during a request
   uses  — one depends on the other without calling it in the main flow
   owns  — one contains or constructs the other
   emits — one produces events or values the other consumes
   reads — one reads data the other writes

Rules that matter:

1. Every module must list real symbol ids, copied verbatim from the inventory. A module
   with no resolvable symbols is discarded along with its edges.
2. Do not force the code into layers. If the parts are parallel, say so. If it is a
   pipeline, a hub, or a plugin tree, draw that. A picture that fits the code is worth
   more than one that fits a template.
3. Prefer 4 to 8 modules. Fewer than three has not divided anything; more than a dozen
   is a file listing with boxes around it.
4. The Mermaid diagram must agree with the modules and edges you listed: same ids, same
   relations. Use plain `graph TD`/`graph LR` and the module ids as node names.
5. If the inventory is too thin to support a real architecture — for instance a flat
   script — say so in `overview` and return the modules it does support. Do not pad.
6. Write `title`, `label`s, `overview`, and `shape` in the same language as the question."""


def build_inventory(idx: Index, *, symbol_budget: int = 900) -> str:
    """Compact deterministic render of the index, for prompt caching."""
    names = {sid: s.qualname for sid, s in idx.symbols.items()}
    out_edges: dict[str, list[str]] = {}
    in_edges: dict[str, list[str]] = {}
    for e in idx.edges:
        out_edges.setdefault(e.caller_id, []).append(e.callee_id)
        in_edges.setdefault(e.callee_id, []).append(e.caller_id)

    callables = sorted(idx.callable_symbols(),
                       key=lambda s: (s.relpath, s.range.start_line, s.qualname))
    total = len(callables)
    kept = callables[:symbol_budget]

    lines = [f"PROJECT: {idx.root}",
             f"SYMBOLS: {total} callable definitions"
             + (f" (showing first {len(kept)})" if total > len(kept) else ""),
             "",
             "Format: <id> | <signature> | calls: <callees> | called by: <callers>",
             ""]

    current = None
    for sym in kept:
        if sym.relpath != current:
            current = sym.relpath
            lines.append(f"--- {current}")
        callees = sorted({names.get(c, c) for c in out_edges.get(sym.id, ())})
        callers = sorted({names.get(c, c) for c in in_edges.get(sym.id, ())})
        lines.append(
            f"{sym.id} | {sym.signature or sym.qualname}"
            f" | calls: {', '.join(callees[:8]) or '-'}"
            f" | called by: {', '.join(callers[:6]) or '-'}"
        )

    if idx.unresolved_calls:
        tally: dict[str, int] = {}
        for _, name, _ in idx.unresolved_calls:
            tally[name] = tally.get(name, 0) + 1
        top = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[:30]
        lines += ["", "--- calls leaving the project: " + ", ".join(f"{n}x{c}" for n, c in top)]

    return "\n".join(lines)


def _slug(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
    if not cleaned or not cleaned[0].isalpha():
        # Mermaid ids must be ASCII-ish, but module labels are often Chinese.
        # A deterministic hash keeps them distinct instead of collapsing to "g".
        import hashlib
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
        cleaned = f"{fallback}_{digest}"
    return cleaned[:32]


def render_mermaid(nodes: list[ArchNode], edges: list[ArchEdge], *,
                   direction: str = "TD") -> str:
    """Build the diagram from the validated graph, not from the model's string.

    The model's own Mermaid is a suggestion. Rendering from the validated nodes
    and edges guarantees the picture cannot show a module that was rejected.
    """
    lines = [f"graph {direction}"]
    for n in nodes:
        label = n.label.replace('"', "'")
        lines.append(f'    {n.id}["{label}"]')
    for e in edges:
        arrow = ARROW.get(e.kind, "-->")
        if e.label:
            lines.append(f'    {e.source} {arrow}|"{e.label}"| {e.target}')
        else:
            lines.append(f"    {e.source} {arrow} {e.target}")
    return "\n".join(lines)


def validate_architecture(raw: Any, idx: Index) -> Architecture:
    """Drop anything the index cannot prove, then rebuild the diagram from what survives."""
    title = str(raw.get("title") or "架构").strip()
    overview = str(raw.get("overview") or "").strip()
    shape = str(raw.get("shape") or "").strip()

    rejected_symbols: list[str] = []
    rejected_nodes: list[str] = []
    nodes: list[ArchNode] = []
    seen_ids: set[str] = set()

    for n_raw in (raw.get("modules") or [])[:MAX_MODULES]:
        raw_id = str(n_raw.get("id") or "").strip()
        node_id = _slug(raw_id, "m")
        # duplicate ids in a graph silently overwrite each other
        if node_id in seen_ids:
            node_id = _slug(raw_id + "_2", "m")
        if node_id in seen_ids:
            rejected_nodes.append(raw_id)
            continue

        kept: list[str] = []
        for sid in n_raw.get("symbolIds") or []:
            sid = str(sid).strip()
            if not sid:
                continue
            if sid in idx.symbols:
                if sid not in kept:
                    kept.append(sid)
            else:
                rejected_symbols.append(sid)

        if not kept:
            rejected_nodes.append(raw_id or str(n_raw.get("label") or "?"))
            continue

        seen_ids.add(node_id)
        nodes.append(ArchNode(
            id=node_id,
            label=str(n_raw.get("label") or raw_id or node_id).strip(),
            relation=str(n_raw.get("relation") or "").strip(),
            symbol_ids=kept,
            note=str(n_raw.get("note") or "").strip(),
        ))

    valid_ids = {n.id for n in nodes}
    edges: list[ArchEdge] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for e_raw in raw.get("edges") or []:
        src = _slug(str(e_raw.get("source") or ""), "m")
        dst = _slug(str(e_raw.get("target") or ""), "m")
        kind = e_raw.get("kind")
        if kind not in EDGE_KINDS:
            continue
        # an edge to a module that was dropped would point at nothing
        if src not in valid_ids or dst not in valid_ids or src == dst:
            continue
        key = (src, dst, kind)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append(ArchEdge(src, dst, kind, str(e_raw.get("label") or "").strip()))

    arch = Architecture(title, overview, shape, nodes, edges,
                        rejected_nodes, rejected_symbols)
    arch.mermaid = render_mermaid(nodes, edges)
    return arch





def request_architecture(idx: Index, focus: str = "", *,
                         inventory: str | None = None,
                         key: str | None = None,
                         base_url: str | None = None,
                         model: str | None = None,
                         max_tokens: int = 8000) -> Architecture:
    from .llm import LlmError, call_tool
    inv = inventory if inventory is not None else build_inventory(idx)
    question = focus.strip() or "整体架构是怎样的"
    try:
        raw = call_tool(
            system_text=SYSTEM_PROMPT,
            inventory=inv,
            user_text=f"关注点: {question}\n\n描述这个系统的架构。",
            tool=ARCH_TOOL,
            max_tokens=max_tokens,
        )
    except LlmError as exc:
        raise ArchError(str(exc)) from exc
    return validate_architecture(raw, idx)


# --- local fallback -----------------------------------------------------

GROUP_HINTS = [
    ("入口 / 路由", re.compile(r"(api|route|router|handler|endpoint|view|controller|server|dispatch)", re.I)),
    ("业务逻辑", re.compile(r"(service|logic|usecase|domain|manager|processor|worker)", re.I)),
    ("数据访问", re.compile(r"(repo|repository|dao|db|database|store|model|schema|orm)", re.I)),
    ("观测", re.compile(r"(log|logger|metric|telemetry|trace|monitor|audit)", re.I)),
]


def heuristic_architecture(idx: Index) -> Architecture:
    """No model: group by name convention, and say that is what happened."""
    groups: dict[str, list[str]] = {}
    for sym in sorted(idx.callable_symbols(), key=lambda s: s.id):
        name = f"{sym.relpath} {sym.qualname}"
        bucket = next((label for label, rx in GROUP_HINTS if rx.search(name)), "其他")
        groups.setdefault(bucket, []).append(sym.id)

    nodes: list[ArchNode] = []
    for label in [l for l, _ in GROUP_HINTS] + ["其他"]:
        ids = groups.get(label, [])
        if not ids:
            continue
        nodes.append(ArchNode(_slug(label, "g"), label, "按命名推测", ids[:24]))

    edges: list[ArchEdge] = []
    node_of = {sid: n.id for n in nodes for sid in n.symbol_ids}
    seen: set[tuple[str, str]] = set()
    for e in idx.edges:
        a, b = node_of.get(e.caller_id), node_of.get(e.callee_id)
        if a and b and a != b and (a, b) not in seen:
            seen.add((a, b))
            edges.append(ArchEdge(a, b, "calls"))

    arch = Architecture(
        title="架构（本地推测）",
        overview=("这份划分来自文件名与命名的启发式匹配，不是模型判断。"
                  "它足以看出大致形状，但模块边界未经语义验证。"),
        shape="按命名约定的分组",
        nodes=nodes, edges=edges,
        rejected_nodes=[], rejected_symbols=[],
    )
    arch.mermaid = render_mermaid(nodes, edges)
    return arch


def architecture_or_fallback(idx: Index, focus: str = "", **kwargs) -> tuple[Architecture, str]:
    """Return (architecture, source) where source is 'model' or 'heuristic'."""
    try:
        return request_architecture(idx, focus, **kwargs), "model"
    except ArchError as exc:
        arch = heuristic_architecture(idx)
        arch.overview += f"\n\n_模型不可用（{exc}）。_"
        return arch, "heuristic"
