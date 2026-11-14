"""Turn a question into a set of *views*, letting the model pick the shape.

A reading plan is not always a list. "Trace the HTTP path" wants a linear flow;
"where does logging happen" wants scattered points grouped by purpose; "how is
this organised" wants regions. Forcing all three into one section list is what
made earlier versions feel muddled — the reader got a flat list where they
needed a shape.

So a view carries a `kind` and a list of nodes with `group` and `depth`. The two
extra fields are enough to express every shape without a discriminated union in
the schema:

    path       depth is the call depth; nodes read top to bottom as one flow
    crosscut   group is the purpose bucket; depth is unused
    zones      group is the region; depth is unused
    calltree   depth restores nesting; group is unused

The model chooses which kinds to emit and may emit up to three. The frontend
dispatches on `kind` — that is the "render by architecture" half of the design.

The division of labour is unchanged and is the thing worth protecting:

    the index decides what exists   (symbols and calls come from the LSP)
    the model decides what matters  (shape, grouping, emphasis)
    the validator decides what ships (unknown ids are dropped, not repaired)
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from typing import Any, Literal

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

from .model import Index

ViewKind = Literal["path", "crosscut", "zones", "calltree"]
VIEW_KINDS: tuple[ViewKind, ...] = ("path", "crosscut", "zones", "calltree")

DEFAULT_MODEL = "deepseek-v4.1-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com/anthropic"
DEFAULT_KEY_ENV = "ANTHROPIC_API_KEY"

MAX_VIEWS = 3
MAX_DEPTH = 12


class PlanError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class ViewNode:
    symbol_id: str
    group: str = ""
    depth: int = 0
    note: str = ""


@dataclasses.dataclass
class View:
    kind: ViewKind
    title: str
    nodes: list[ViewNode]
    rationale: str = ""

    @property
    def symbol_ids(self) -> list[str]:
        seen: list[str] = []
        for n in self.nodes:
            if n.symbol_id not in seen:
                seen.append(n.symbol_id)
        return seen

    @property
    def groups(self) -> list[str]:
        out: list[str] = []
        for n in self.nodes:
            if n.group and n.group not in out:
                out.append(n.group)
        return out


@dataclasses.dataclass
class ViewBundle:
    query: str
    title: str
    summary: str
    views: list[View]
    rejected: list[str]

    def role_map(self) -> dict[str, list[str]]:
        """symbol id -> the view titles it appears in."""
        out: dict[str, list[str]] = {}
        for v in self.views:
            for sid in v.symbol_ids:
                out.setdefault(sid, []).append(v.title)
        return out

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "title": self.title,
            "summary": self.summary,
            "views": [
                {
                    "kind": v.kind,
                    "title": v.title,
                    "rationale": v.rationale,
                    "nodes": [
                        {"symbolId": n.symbol_id, "group": n.group,
                         "depth": n.depth, "note": n.note}
                        for n in v.nodes
                    ],
                }
                for v in self.views
            ],
            "rejected": self.rejected,
        }


# --- the tool -----------------------------------------------------------

VIEW_TOOL: dict[str, Any] = {
    "name": "emit_views",
    "description": (
        "Emit one or more views that answer the question. Each view has a kind that "
        "decides its layout, and a list of nodes. Every node's symbolId must be copied "
        "verbatim from the inventory. Never invent ids."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Plan title, in the user's language."},
            "summary": {
                "type": "string",
                "description": "Two or three sentences: what the answer is, and why these view shapes fit.",
            },
            "views": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_VIEWS,
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": list(VIEW_KINDS),
                            "description": (
                                "path = a single linear flow read top to bottom. "
                                "crosscut = scattered points bucketed by purpose. "
                                "zones = architecture regions. "
                                "calltree = nesting, use depth."
                            ),
                        },
                        "title": {"type": "string", "description": "Short label for this view."},
                        "rationale": {
                            "type": "string",
                            "description": "One line: why this shape fits the question.",
                        },
                        "nodes": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "symbolId": {
                                        "type": "string",
                                        "description": "Copied exactly from the inventory.",
                                    },
                                    "group": {
                                        "type": "string",
                                        "description": "Bucket or region name. Used by crosscut and zones.",
                                    },
                                    "depth": {
                                        "type": "integer",
                                        "description": "Nesting level from 0. Used by path and calltree.",
                                    },
                                    "note": {
                                        "type": "string",
                                        "description": "Optional short remark shown next to the node.",
                                    },
                                },
                                "required": ["symbolId"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["kind", "title", "nodes"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "summary", "views"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You decide how a person should read an unfamiliar codebase to answer their question.

You get an inventory of symbols extracted by a language server. It is ground truth:
those symbols exist and the listed calls really happen. You choose what matters and
what shape the answer should take; you never decide what exists.

Four view shapes are available. Choose whichever actually answers the question — you may
combine up to three, and two views that show genuinely different things beat two views
that repeat each other.

- `path` — one linear flow, read top to bottom. Use `depth` for how deep in the call
  chain each node sits. Best for "what happens when X", "trace a request end to end".
- `crosscut` — scattered points bucketed by purpose. Use `group` for the bucket.
  Best for "where is X used", "where does logging/db/metrics happen" — anything that has
  no single entry point and is spread through the code.
- `zones` — architecture regions. Use `group` for the region. Best for "how is this
  organised", "what are the moving parts".
- `calltree` — nesting via `depth`, for showing what calls what underneath one root.

How to decide: if the question names a flow, prefer `path`. If it names a concern that
cuts across layers (logging, metrics, the database, auth), prefer `crosscut` — a `path`
would lie, because those calls are not on one chain. If it asks about structure, prefer
`zones`.

Rules that matter:

1. Copy symbol ids verbatim. An invented id is discarded and counted against you.
2. A symbol may appear in more than one view when the views really are different readings.
   Do not repeat the same grouping twice under different titles.
3. Keep each view decisive. A `path` with 40 steps has stopped being a path. If a flow is
   long, show the trunk and say in the node `note` what was left out.
4. If the inventory cannot answer the question, say so plainly in `summary` and return the
   closest true view. Never pad with unrelated symbols to look complete. If the inventory
   is missing edges you can see are needed (e.g. routing via a dict the language server
   cannot follow), say that in `summary` rather than inventing the edge.
5. Write `title`, view titles, node notes, and `summary` in the same language as the question.
6. Nodes must be symbols from the inventory — not files, not modules, not made-up helpers."""


def build_inventory(idx: Index, *, symbol_budget: int = 1200,
                    skip_prefixes: tuple[str, ...] = (),
                    compact: bool = False) -> str:
    """Render the index as a compact deterministic block, so it can be cached.

    Determinism matters twice: identical bytes across calls let the prompt cache
    hit, and stable ordering keeps the same question producing the same view.

    `compact=True` drops line ranges. It is for whole-project shape calls (the
    skeleton) that choose components and symbols but do not emit segment ranges.
    Slice calls should use `build_scoped_inventory` instead: they need line
    ranges but normally only care about a few hundred symbols around the question.
    """
    def skip(sid: str) -> bool:
        return sid.startswith(skip_prefixes) if skip_prefixes else False

    names = {sid: s.qualname for sid, s in idx.symbols.items()}
    out_edges: dict[str, list[str]] = {}
    in_edges: dict[str, list[str]] = {}
    for e in idx.edges:
        out_edges.setdefault(e.caller_id, []).append(e.callee_id)
        in_edges.setdefault(e.callee_id, []).append(e.caller_id)

    callables = sorted(
        (s for s in idx.callable_symbols() if not skip(s.id)),
        key=lambda s: (s.relpath, s.range.start_line, s.qualname),
    )
    total = len(callables)
    kept = callables[:symbol_budget]

    lines: list[str] = []
    lines.append(f"PROJECT: {idx.root}")
    lines.append(f"SYMBOLS: {total} callable definitions"
                 + (f" (showing first {len(kept)}, ordered by file)" if total > len(kept) else ""))
    lines.append("")
    if compact:
        lines.append("Format: <id> | <signature> | calls: <callees> | called by: <callers>")
    else:
        lines.append("Format: <id> | <signature> | lines <start>-<end> | calls: <callees> | called by: <callers>")
    lines.append("Unresolved calls are listed at the end — they mark the project's outer boundary.")
    lines.append("")

    current_file = None
    for sym in kept:
        if sym.relpath != current_file:
            current_file = sym.relpath
            lines.append(f"--- {current_file}")
        callees = sorted({names.get(c, c) for c in out_edges.get(sym.id, ())})
        callers = sorted({names.get(c, c) for c in in_edges.get(sym.id, ())})
        sig = sym.signature or sym.qualname
        location = "" if compact else (
            f" | lines {sym.body_range.start_line + 1}-{sym.body_range.end_line + 1}"
        )
        lines.append(
            f"{sym.id} | {sig}{location}"
            f" | calls: {', '.join(callees[:8]) or '-'}"
            f" | called by: {', '.join(callers[:6]) or '-'}"
        )

    if idx.unresolved_calls:
        tally: dict[str, int] = {}
        for _, name, _ in idx.unresolved_calls:
            tally[name] = tally.get(name, 0) + 1
        top = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[:40]
        lines.append("")
        lines.append("--- calls leaving the project (unresolved): "
                     "the boundary worth mentioning for http / db / logging questions")
        lines.append(", ".join(f"{n}x{c}" for n, c in top))

    return "\n".join(lines)


_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}|[\u4e00-\u9fff]{2,}")
_STOP_TERMS = {
    "the", "and", "for", "with", "from", "this", "that", "what", "how",
    "code", "logic", "flow", "整体", "逻辑", "代码", "流程", "一下", "怎么",
    "什么", "如何", "项目", "部分", "相关", "请求", "处理",
}
_ENTRY_NAME_RE = re.compile(
    r"(^|_)(main|run|start|serve|server|app|entry|cli|dispatch|router|route|handler|create)(_|$)",
    re.IGNORECASE,
)


def _query_terms(query: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in _TERM_RE.finditer(query or ""):
        term = match.group(0).lower()
        if len(term) < 2 or term in _STOP_TERMS or term in seen:
            continue
        seen.add(term)
        out.append(term)
    return out


def build_scoped_inventory(idx: Index, query: str = "",
                           scope: dict | None = None, *,
                           symbol_budget: int = 240) -> str:
    """Small, deterministic inventory around one question.

    Sending every callable to a slice request is wasteful: the model only needs
    the seed symbols (scope/query matches), their immediate neighbours, and a
    few high-fan-in orientation points. The skeleton still gets the broad
    inventory; slices use this focused view.
    """
    callables = sorted(
        idx.callable_symbols(),
        key=lambda s: (s.relpath, s.range.start_line, s.qualname),
    )
    total = len(callables)
    by_id = {s.id: s for s in callables}
    names = {sid: s.qualname for sid, s in idx.symbols.items()}
    out_edges: dict[str, list[str]] = {}
    in_edges: dict[str, list[str]] = {}
    for edge in idx.edges:
        out_edges.setdefault(edge.caller_id, []).append(edge.callee_id)
        in_edges.setdefault(edge.callee_id, []).append(edge.caller_id)

    selected: list[str] = []
    chosen: set[str] = set()

    def add(sid: str | None) -> None:
        if not sid or sid in chosen or sid not in by_id:
            return
        chosen.add(sid)
        selected.append(sid)

    def add_many(ids) -> None:
        for sid in ids:
            add(str(sid))

    scope = scope or {}
    # 1. Explicit scope wins: a symbol, selection, file, module or skeleton node.
    if isinstance(scope.get("symbolIds"), list):
        add_many(scope["symbolIds"])
    if scope.get("symbolId"):
        add(str(scope["symbolId"]))
    file = str(scope.get("file") or "").strip()
    if file:
        try:
            start = int(scope.get("startLine") or 1)
            end = int(scope.get("endLine") or 0)
        except (TypeError, ValueError):
            start, end = 1, 0
        for sym in callables:
            if sym.relpath != file:
                continue
            if end and (sym.body_range.end_line + 1 < start
                        or sym.body_range.start_line + 1 > end):
                continue
            add(sym.id)
    module = str(scope.get("module") or "").strip().replace("\\", "/")
    if module:
        for sym in callables:
            if sym.relpath == module or sym.relpath.startswith(module.rstrip("/") + "/"):
                add(sym.id)
    scoped_files = scope.get("files") or []
    if isinstance(scoped_files, str):
        scoped_files = [scoped_files]
    for scoped_file in scoped_files:
        scoped_file = str(scoped_file).strip()
        if not scoped_file:
            continue
        for sym in callables:
            if sym.relpath == scoped_file:
                add(sym.id)

    # 2. Lexical seeds from the question. Short/common words are ignored so a
    #    question like "整体逻辑" does not drag in every get/create call.
    terms = _query_terms(query)
    lexical_hits = 0
    if terms:
        matches: list[tuple[int, int, str]] = []
        for sym in callables:
            haystack = f"{sym.qualname} {sym.relpath} {sym.signature}".lower()
            hits = sum(1 for term in terms if term in haystack)
            if hits:
                matches.append((-hits, len(sym.qualname), sym.id))
        lexical_hits = len(matches)
        for _, _, sid in sorted(matches)[:60]:
            add(sid)
        if scope.get("text"):
            text_ids = _query_terms(str(scope["text"]))
            for sym in callables:
                qual = f"{sym.qualname} {sym.relpath}".lower()
                if any(term in qual for term in text_ids):
                    add(sym.id)
                    lexical_hits += 1

    # 3. Orientation points: entry-like names and high fan-in hubs. They make
    #    broad questions answerable without falling back to the full index.
    degree = sorted(
        callables,
        key=lambda s: (-(len(in_edges.get(s.id, [])) + len(out_edges.get(s.id, []))),
                       s.relpath, s.range.start_line),
    )
    for sym in degree[:24]:
        add(sym.id)
    for sym in callables:
        if _ENTRY_NAME_RE.search(sym.qualname.split("::")[-1].split(".")[-1]):
            add(sym.id)

    # A broad or non-matching question gets a bounded sample, not just the
    # 24 hubs. Still much cheaper than shipping every callable.
    no_explicit_scope = not (
        scope.get("symbolIds") or scope.get("symbolId") or file or module
    )
    broad_sample = no_explicit_scope and not lexical_hits
    if broad_sample:
        for sym in callables[:min(symbol_budget, 120)]:
            add(sym.id)

    # 4. One hop of real neighbours. This is where "who calls this / what does
    #    it call" becomes answerable without dumping the project. Broad samples
    #    already carry calls/called-by in each row; expanding all of them would
    #    recreate the full index.
    if not broad_sample:
        seed_ids = list(selected)
        for sid in seed_ids:
            for nxt in out_edges.get(sid, []):
                add(nxt)
            for prev in in_edges.get(sid, []):
                add(prev)

    # 5. Same-file context for explicit/file questions, capped tightly.
    if file:
        for sym in callables:
            if sym.relpath == file:
                add(sym.id)

    # No signal at all (empty/very broad query): a bounded whole-project sample
    # is the honest fallback, not a fabricated focus.
    if not chosen:
        for sym in callables[:min(symbol_budget, 160)]:
            add(sym.id)

    kept = [by_id[sid] for sid in selected if sid in by_id][:symbol_budget]
    kept.sort(key=lambda s: (s.relpath, s.range.start_line, s.qualname))

    lines: list[str] = [
        f"PROJECT: {idx.root}",
        f"SYMBOLS: {total} callable definitions"
        + (f" (showing {len(kept)} focused" if total > len(kept) else " (focused"),
        f"FOCUS: {(query or '(broad)')[:240]}",
        f"SCOPE: {scope.get('kind') or 'query'}",
        "",
        "Format: <id> | <signature> | lines <start>-<end> | calls: <callees> | called by: <callers>",
        "This is a focused view around the question; missing symbols are outside the focus, not absent from the project.",
        "",
    ]
    if total > len(kept):
        lines[1] += f" of {total})"
    else:
        lines[1] += ")"

    current = None
    for sym in kept:
        if sym.relpath != current:
            current = sym.relpath
            lines.append(f"--- {current}")
        callees = sorted({names.get(c, c) for c in out_edges.get(sym.id, ())})
        callers = sorted({names.get(c, c) for c in in_edges.get(sym.id, ())})
        lines.append(
            f"{sym.id} | {sym.signature or sym.qualname}"
            f" | lines {sym.body_range.start_line + 1}-{sym.body_range.end_line + 1}"
            f" | calls: {', '.join(callees[:8]) or '-'}"
            f" | called by: {', '.join(callers[:6]) or '-'}"
        )

    if idx.unresolved_calls:
        tally: dict[str, int] = {}
        for _, name, _ in idx.unresolved_calls:
            tally[name] = tally.get(name, 0) + 1
        top = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[:30]
        lines += ["", "--- calls leaving the project: "
                  + ", ".join(f"{n}x{c}" for n, c in top)]
    return "\n".join(lines)


def load_credentials() -> tuple[str, str, str]:
    from .settings import resolve_credentials
    key, base, model = resolve_credentials()
    if not key:
        raise PlanError(
            "no API key: open API settings in the top bar, or set "
            f"{DEFAULT_KEY_ENV} / QTA_API_KEY."
        )
    return key, base, model


def _client(key: str, base_url: str):
    if anthropic is None:
        raise PlanError("the anthropic package is not installed: pip install anthropic")
    return anthropic.Anthropic(api_key=key, base_url=base_url)


def request_views(
    idx: Index,
    query: str,
    *,
    inventory: str | None = None,
    key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    max_tokens: int = 8000,
) -> ViewBundle:
    if key is None or base_url is None or model is None:
        k, b, m = load_credentials()
        key = key or k
        base_url = base_url or b
        model = model or m

    inv = inventory if inventory is not None else build_inventory(idx)

    system = [
        {"type": "text", "text": SYSTEM_PROMPT},
        # the inventory is the large stable part; marking it cacheable means
        # repeated questions about the same tree only pay for the question
        {"type": "text", "text": inv, "cache_control": {"type": "ephemeral"}},
    ]

    client = _client(key, base_url)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            # this endpoint rejects tool_choice unless thinking is explicitly off
            thinking={"type": "disabled"},
            system=system,
            tools=[VIEW_TOOL],
            tool_choice={"type": "tool", "name": "emit_views"},
            messages=[{"role": "user",
                       "content": f"Question: {query}\n\nProduce the views."}],
        )
    except Exception as exc:
        raise PlanError(f"model call failed: {exc}") from exc

    raw = next((b.input for b in resp.content if b.type == "tool_use"), None)
    if raw is None:
        text = next((b.text for b in resp.content if b.type == "text"), "")
        raise PlanError(
            f"model did not return views (stop_reason={resp.stop_reason}); "
            f"text was: {text[:200]}"
        )

    return validate_views(raw, idx, query)


def validate_views(raw: Any, idx: Index, query: str) -> ViewBundle:
    """Keep only symbol ids the index can prove. Report the rest, never repair."""
    known = idx.symbols
    title = str(raw.get("title") or query).strip()
    summary = str(raw.get("summary") or "").strip()

    rejected: list[str] = []
    views: list[View] = []

    for entry in (raw.get("views") or [])[:MAX_VIEWS]:
        kind = entry.get("kind")
        if kind not in VIEW_KINDS:
            rejected.append(f"view kind '{kind}'")
            continue

        nodes: list[ViewNode] = []
        seen: set[str] = set()
        for raw_node in entry.get("nodes") or []:
            sid = str(raw_node.get("symbolId") or "").strip()
            if not sid:
                continue
            if sid not in known:
                rejected.append(sid)
                continue
            if sid in seen:  # one row per symbol per view
                continue
            seen.add(sid)
            depth = raw_node.get("depth")
            try:
                depth = int(depth) if depth is not None else 0
            except (TypeError, ValueError):
                depth = 0
            nodes.append(ViewNode(
                symbol_id=sid,
                group=str(raw_node.get("group") or "").strip(),
                depth=max(0, min(depth, MAX_DEPTH)),
                note=str(raw_node.get("note") or "").strip(),
            ))

        if not nodes:
            continue
        views.append(View(
            kind=kind,
            title=str(entry.get("title") or kind).strip(),
            rationale=str(entry.get("rationale") or "").strip(),
            nodes=nodes,
        ))

    return ViewBundle(query=query, title=title, summary=summary,
                      views=views, rejected=rejected)


# --- local fallback, so the viewer works with no key --------------------

HTTP_HINT = re.compile(
    r"(route|router|handler|endpoint|view|api|controller|request|response|"
    r"@app\.|@router\.|do_GET|do_POST|urls?\.py|http)", re.IGNORECASE)
DB_HINT = re.compile(
    r"(repo|repository|dao|db|database|session|query|cursor|engine|orm|model|sql)",
    re.IGNORECASE)
LOG_HINT = re.compile(
    r"(log|logger|logging|metric|metrics|telemetry|trace|monitor|audit|span)",
    re.IGNORECASE)


def _is_noise(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return (rel.startswith(("spike/", "node_modules/"))
            or name.startswith(("test_", "verify_", "probe")))


def heuristic_views(idx: Index, query: str) -> ViewBundle:
    """No model: match names, and be explicit that this is a stopgap.

    Deliberately dumb. Its job is to keep the viewer usable without a key, not
    to imitate the model's judgement about shape.
    """
    if HTTP_HINT.search(query):
        hint, label, kind = HTTP_HINT, "HTTP 相关", "crosscut"
    elif DB_HINT.search(query):
        hint, label, kind = DB_HINT, "数据访问", "crosscut"
    elif LOG_HINT.search(query):
        hint, label, kind = LOG_HINT, "观测", "crosscut"
    else:
        tokens = [t for t in re.split(r"\W+", query) if len(t) > 2]
        hint = re.compile("|".join(map(re.escape, tokens)), re.IGNORECASE) if tokens else None
        label, kind = "相关", "crosscut"

    if hint is None:
        return ViewBundle(query=query, title=query,
                          summary="问题太短，本地无法匹配。配置 API key 可由模型选择视图形状。",
                          views=[], rejected=[])

    entry, touched, noise = [], [], []
    for sym in sorted(idx.callable_symbols(), key=lambda s: s.id):
        if _is_noise(sym.relpath):
            continue
        if LOG_HINT.search(sym.qualname) or LOG_HINT.search(sym.relpath):
            noise.append(sym.id)
        elif hint.search(sym.qualname) or hint.search(sym.relpath):
            entry.append(sym.id)
        elif hint.search(sym.signature or ""):
            touched.append(sym.id)

    nodes: list[ViewNode] = []
    nodes += [ViewNode(s, label, 0, "") for s in entry[:20]]
    nodes += [ViewNode(s, "签名相关", 0, "参数或返回类型涉及该主题") for s in touched[:20]]
    nodes += [ViewNode(s, "观测/旁路", 0, "日志与指标，通常可跳过") for s in noise[:16]]

    views = [View(kind, f"{label}（本地匹配）", nodes,
                  "本地启发式按名称匹配，未调用模型")] if nodes else []

    return ViewBundle(
        query=query, title=query,
        summary=(f"本地启发式匹配（未调用模型）：按名称把与 `{query}` 相关的符号分组。"
                 f"配置 API key 后可获得模型选择的视图形状与真正的分层。"),
        views=views, rejected=[])


def views_or_fallback(idx: Index, query: str, **kwargs) -> tuple[ViewBundle, str]:
    """Return (bundle, source) where source is 'model' or 'heuristic'."""
    try:
        return request_views(idx, query, **kwargs), "model"
    except PlanError as exc:
        bundle = heuristic_views(idx, query)
        bundle.summary = f"{bundle.summary}\n\n_模型不可用（{exc}），以下是本地匹配结果。_"
        return bundle, "heuristic"
