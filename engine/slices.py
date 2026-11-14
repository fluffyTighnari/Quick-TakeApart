"""Slices: the persistent unit of stage three.

A flow alone is a shape without material. A slice is the shape plus the actual
code ranges the reader needs, the notes anchored to them, and the diagrams that
make the shape visible. The structure is frozen; the code text stays live and
decay is reported per symbol.

The validator is deliberately strict in one direction only: it refuses invented
symbols and ranges, but it never "repairs" a weak answer into a prettier one.
A missing view or a thin segment is a legitimate outcome; a fabricated one is not.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import secrets
from datetime import datetime, timezone

from .llm import LlmError, call_tool
from .model import Index
from .plan import build_scoped_inventory, heuristic_views
from .store import Fingerprint, fingerprint_of, staleness_of

SLICE_DIR = ".qta/slices"
FORMAT_VERSION = 1

VIEW_KINDS = ("path", "sequence", "crosscut", "zones", "calltree", "dataflow")
MAX_VIEWS = 6
MAX_SEGMENT_LINES = 180
ROLES = ("entry", "trunk", "branch", "context", "skip")


class SliceError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str, limit: int = 22) -> str:
    cleaned = re.sub(r"[^\w一-鿿-]+", "-", text, flags=re.UNICODE).strip("-")
    return cleaned[:limit] or "slice"


def _new_id(name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{_slug(name, 16)}-{secrets.token_hex(2)}"


def _safe_id(value: str) -> bool:
    return bool(value) and not any(c in value for c in ("/", "\\", ".."))


def _short(sid: str) -> str:
    rel, _, qual = sid.partition("::")
    return f"{rel.rsplit('/', 1)[-1]}.{qual}" if qual else rel


@dataclasses.dataclass
class Slice:
    id: str
    track_id: str
    title: str
    query: str
    summary: str
    strategies: list[str]
    views: list[dict]
    segments: list[dict]
    annotations: list[dict]
    diagrams: list[dict]
    source: dict
    rejected: list[str]
    created_at: str
    revision: str
    fingerprints: dict[str, Fingerprint]

    @property
    def name(self) -> str:
        return self.title

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trackId": self.track_id,
            "title": self.title,
            "query": self.query,
            "summary": self.summary,
            "strategies": self.strategies,
            "views": self.views,
            "segments": self.segments,
            "annotations": self.annotations,
            "diagrams": self.diagrams,
            "source": self.source,
            "rejected": self.rejected,
            "createdAt": self.created_at,
            "revision": self.revision,
            "fingerprints": {
                sid: {"line": f.line, "endLine": f.end_line, "signature": f.signature}
                for sid, f in self.fingerprints.items()
            },
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Slice":
        fps = {
            sid: Fingerprint(int(v.get("line") or 0), int(v.get("endLine") or 0),
                             str(v.get("signature") or ""))
            for sid, v in (raw.get("fingerprints") or {}).items()
        }
        return cls(
            id=str(raw.get("id") or ""),
            track_id=str(raw.get("trackId") or ""),
            title=str(raw.get("title") or raw.get("query") or "未命名切片"),
            query=str(raw.get("query") or ""),
            summary=str(raw.get("summary") or ""),
            strategies=[str(x) for x in (raw.get("strategies") or [])],
            views=list(raw.get("views") or []),
            segments=list(raw.get("segments") or []),
            annotations=list(raw.get("annotations") or []),
            diagrams=list(raw.get("diagrams") or []),
            source=dict(raw.get("source") or {}),
            rejected=[str(x) for x in (raw.get("rejected") or [])],
            created_at=str(raw.get("createdAt") or ""),
            revision=str(raw.get("revision") or ""),
            fingerprints=fps,
        )


# --- validation ---------------------------------------------------------


def _norm_kind(kind: str) -> str:
    return "path" if kind == "chain" else kind


def _mermaid_escape(text: str) -> str:
    return (text or "").replace('"', "'").replace("|", "/").replace("\n", " ").strip()


def _short_label(text: str, limit: int = 36) -> str:
    value = _mermaid_escape(text)
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _find_edge(idx: Index, a: str, b: str):
    forward = next((e for e in idx.edges if e.caller_id == a and e.callee_id == b), None)
    if forward:
        return forward, "direct"
    reverse = next((e for e in idx.edges if e.caller_id == b and e.callee_id == a), None)
    if reverse:
        return reverse, "reverse"
    return None, "inferred"


def validate_slice_views(raw: dict, idx: Index, query: str) -> tuple[list[dict], list[str]]:
    """Keep only views whose nodes/messages resolve to real symbols."""
    rejected: list[str] = []
    views: list[dict] = []

    for entry in (raw.get("views") or [])[:MAX_VIEWS]:
        kind = _norm_kind(str(entry.get("kind") or "").strip())
        if kind not in VIEW_KINDS:
            rejected.append(f"view kind '{entry.get('kind')}'")
            continue

        nodes: list[dict] = []
        seen: set[str] = set()
        for raw_node in entry.get("nodes") or []:
            sid = str(raw_node.get("symbolId") or "").strip()
            if not sid:
                continue
            if sid not in idx.symbols:
                rejected.append(sid)
                continue
            if sid in seen:
                continue
            seen.add(sid)
            try:
                depth = int(raw_node.get("depth") or 0)
            except (TypeError, ValueError):
                depth = 0
            nodes.append({
                "symbolId": sid,
                "group": str(raw_node.get("group") or "").strip(),
                "depth": max(0, min(depth, 12)),
                "note": str(raw_node.get("note") or "").strip(),
                "role": str(raw_node.get("role") or "context").strip(),
            })

        messages: list[dict] = []
        if kind == "sequence":
            for raw_msg in (entry.get("messages") or [])[:40]:
                src = str(raw_msg.get("from") or "").strip()
                dst = str(raw_msg.get("to") or "").strip()
                sid = str(raw_msg.get("symbolId") or "").strip()
                if not src or not dst:
                    rejected.append("sequence message without from/to")
                    continue
                if sid and sid not in idx.symbols:
                    rejected.append(sid)
                    sid = ""
                status = str(raw_msg.get("status") or "inferred").strip()
                if status not in ("direct", "reverse", "inferred"):
                    status = "inferred"
                site = None
                # Only claim direct/reverse when the index can support it.
                from_sid = src if src in idx.symbols else ""
                to_sid = dst if dst in idx.symbols else ""
                edge = next((e for e in idx.edges
                             if (from_sid and e.caller_id == from_sid and
                                 (e.callee_id == to_sid or (sid and e.callee_id == sid)))
                             or (to_sid and e.caller_id == to_sid and
                                 (e.callee_id == from_sid or (sid and e.callee_id == sid)))), None)
                if edge:
                    if edge.caller_id == from_sid:
                        status = "direct"
                    elif edge.caller_id == to_sid:
                        status = "reverse"
                    sym = idx.symbols.get(edge.caller_id)
                    site = {"file": sym.relpath if sym else "",
                            "line": edge.site.start_line + 1}
                else:
                    status = "inferred"
                    if sid:
                        sym = idx.symbols[sid]
                        site = {"file": sym.relpath, "line": sym.body_range.start_line + 1}
                messages.append({
                    "from": src, "to": dst,
                    "label": str(raw_msg.get("label") or "").strip(),
                    "symbolId": sid, "status": status, "site": site,
                })

        if not nodes and not messages:
            continue

        if kind in ("crosscut", "zones") and nodes:
            missing = [node for node in nodes if not node.get("group")]
            if missing:
                role_labels = {
                    "entry": "入口", "branch": "分支", "trunk": "主干",
                    "context": "上下文", "skip": "可跳过",
                }
                for node in missing:
                    if kind == "zones":
                        node["group"] = role_labels.get(node.get("role") or "", "其他")
                    else:
                        sym = idx.symbols.get(node["symbolId"])
                        rel = sym.relpath if sym else ""
                        node["group"] = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0] or "其他"
                note = ("模型没有给出分组，已按角色回退。" if kind == "zones"
                        else "模型没有给出分组，已按文件回退。")
                entry["rationale"] = (str(entry.get("rationale") or "").strip()
                                      + " " + note).strip()

        links: list[dict] = []
        if kind in ("path", "calltree", "dataflow"):
            for a, b in zip(nodes, nodes[1:]):
                edge, status = _find_edge(idx, a["symbolId"], b["symbolId"])
                links.append({
                    "from": a["symbolId"], "to": b["symbolId"],
                    "status": status,
                    "file": edge.site and idx.symbols[a["symbolId"]].relpath if edge else "",
                    "line": (edge.site.start_line + 1) if edge else None,
                })
        elif kind == "sequence":
            for msg in messages:
                links.append({
                    "from": msg["from"], "to": msg["to"],
                    "status": msg["status"],
                    "file": (msg.get("site") or {}).get("file", ""),
                    "line": (msg.get("site") or {}).get("line"),
                })

        views.append({
            "kind": kind,
            "title": str(entry.get("title") or kind).strip(),
            "rationale": str(entry.get("rationale") or "").strip(),
            "nodes": nodes,
            "messages": messages,
            "links": links,
        })

    return views, rejected


def _line_count(root: pathlib.Path, rel: str) -> int:
    try:
        return max(1, len((root / rel).read_text(encoding="utf-8", errors="replace").splitlines()))
    except OSError:
        return 1


def validate_segments(raw_segments: list | None, root: pathlib.Path, idx: Index,
                      views: list[dict]) -> list[dict]:
    """Resolve segment ranges against real files. Never invent a file or range."""
    files = {s.relpath for s in idx.symbols.values()}
    out: list[dict] = []
    seen: set[tuple[str, int, int]] = set()

    def add(file: str, start: int, end: int, sid: str, role: str,
            note: str, flow_title: str) -> None:
        if file not in files:
            return
        count = _line_count(root, file)
        start = max(1, min(int(start), count))
        end = max(start, min(int(end), count))
        if end - start + 1 > MAX_SEGMENT_LINES:
            sym = idx.symbols.get(sid) if sid else None
            if sym is not None:
                sym_start = sym.body_range.start_line + 1
                sym_end = sym.body_range.end_line + 1
                if sym_end - sym_start + 1 <= MAX_SEGMENT_LINES:
                    start, end = sym_start, sym_end
                else:
                    start, end = sym_start, sym_start + MAX_SEGMENT_LINES - 1
            else:
                end = start + MAX_SEGMENT_LINES - 1
            note = (note + f" 长片段已裁剪到 {MAX_SEGMENT_LINES} 行。").strip()
        key = (file, start, end)
        if key in seen:
            return
        seen.add(key)
        out.append({
            "id": f"seg-{len(out) + 1}",
            "file": file,
            "startLine": start,
            "endLine": end,
            "symbolId": sid,
            "role": role if role in ROLES else "context",
            "note": note,
            "flowTitle": flow_title,
        })

    for raw in raw_segments or []:
        sid = str(raw.get("symbolId") or "").strip()
        if sid and sid not in idx.symbols:
            continue
        sym = idx.symbols.get(sid) if sid else None
        file = str(raw.get("file") or (sym.relpath if sym else "")).strip()
        if not file:
            continue
        note = str(raw.get("note") or "").strip()
        flow_title = str(raw.get("flowTitle") or "").strip()
        if sym:
            body_start = sym.body_range.start_line + 1
            body_end = sym.body_range.end_line + 1
            raw_start = raw.get("startLine")
            raw_end = raw.get("endLine")
            if raw_start is None and raw_end is None:
                start, end = body_start, body_end
            else:
                try:
                    start = int(raw_start if raw_start is not None else body_start)
                    end = int(raw_end if raw_end is not None else body_end)
                except (TypeError, ValueError):
                    start, end = body_start, body_end
                    note = (note + " 行号无法解析，已回退到符号定义。").strip()
                else:
                    # The model often emits file-relative or function-relative
                    # line numbers. Trust only a plausible sub-range inside the
                    # symbol body; otherwise the index's body range is the truth.
                    valid = (body_start <= start <= end <= body_end
                             and end - start + 1 >= 2)
                    if not valid:
                        start, end = body_start, body_end
                        note = (note + " 行号已按符号定义校正。").strip()
        else:
            try:
                start = int(raw.get("startLine") or 1)
                end = int(raw.get("endLine") or _line_count(root, file))
            except (TypeError, ValueError):
                start, end = 1, _line_count(root, file)
        add(file, start, end, sid, str(raw.get("role") or "context").strip(),
            note, flow_title)

    if out:
        # If a single-view slice has no flowTitle, there is no ambiguity; if a
        # symbol belongs to exactly one parallel flow, attach the segment to it.
        if views:
            if len(views) == 1:
                for segment in out:
                    if not segment["flowTitle"]:
                        segment["flowTitle"] = views[0]["title"]
            else:
                by_symbol: dict[str, set[str]] = {}
                for view in views:
                    for node in view.get("nodes") or []:
                        sid = node.get("symbolId")
                        if sid:
                            by_symbol.setdefault(sid, set()).add(view["title"])
                for segment in out:
                    if segment["flowTitle"] or not segment["symbolId"]:
                        continue
                    titles = by_symbol.get(segment["symbolId"]) or set()
                    if len(titles) == 1:
                        segment["flowTitle"] = next(iter(titles))
        return out

    # No usable segments: derive from the validated flow, using the symbol body.
    for view in views:
        for node in view.get("nodes") or []:
            sid = node.get("symbolId")
            sym = idx.symbols.get(sid)
            if sym is None:
                continue
            add(sym.relpath, sym.body_range.start_line + 1,
                sym.body_range.end_line + 1, sid,
                node.get("role") or "context", node.get("note") or "",
                view.get("title") or "")
    if not out:
        raise SliceError("a slice needs at least one real code segment")
    return out


def validate_annotations(raw_annotations: list | None, root: pathlib.Path,
                         idx: Index, segments: list[dict]) -> list[dict]:
    out: list[dict] = []
    for raw in raw_annotations or []:
        markdown = str(raw.get("markdown") or "").strip()
        if not markdown:
            continue
        anchor = raw.get("anchor") or {}
        kind = str(anchor.get("kind") or "").strip()
        clean: dict = {"kind": kind}
        if kind == "segment":
            try:
                index = int(anchor.get("index"))
            except (TypeError, ValueError):
                continue
            if not (0 <= index < len(segments)):
                continue
            clean["segmentId"] = segments[index]["id"]
        elif kind == "symbol":
            sid = str(anchor.get("symbolId") or "").strip()
            if sid not in idx.symbols:
                continue
            clean["symbolId"] = sid
        elif kind == "range":
            file = str(anchor.get("file") or "").strip()
            if not any(s.relpath == file for s in idx.symbols.values()):
                continue
            try:
                start = int(anchor.get("startLine") or 1)
                end = int(anchor.get("endLine") or start)
            except (TypeError, ValueError):
                continue
            clean.update({"file": file, "startLine": start, "endLine": max(start, end)})
        else:
            continue
        out.append({"id": f"note-{len(out) + 1}", "anchor": clean, "markdown": markdown})
    return out


def build_diagrams(views: list[dict], idx: Index) -> list[dict]:
    diagrams: list[dict] = []
    for view_index, view in enumerate(views):
        kind = view["kind"]
        title = view["title"]
        lines: list[str] = []
        if kind == "sequence":
            labels: list[str] = []
            for msg in view.get("messages") or []:
                for label in (msg["from"], msg["to"]):
                    if label not in labels:
                        labels.append(label)
            if not labels:
                continue
            lines.append("sequenceDiagram")
            lines.append("    autonumber")
            for i, label in enumerate(labels):
                lines.append(f"    participant P{i} as {_mermaid_escape(label)}")
            index_of = {label: i for i, label in enumerate(labels)}
            for msg in view.get("messages") or []:
                arrow = "-->>" if msg["status"] == "inferred" else "->>"
                label = _short_label(msg["label"] or msg.get("symbolId", ""))
                if msg["status"] == "reverse":
                    label = "反向 · " + label
                lines.append(
                    f"    P{index_of[msg['from']]} {arrow} P{index_of[msg['to']]}: {label}")
        elif kind in ("crosscut", "zones"):
            lines.append("graph LR")
            groups: dict[str, list[dict]] = {}
            for node in view.get("nodes") or []:
                groups.setdefault(node.get("group") or "未分组", []).append(node)
            for gi, (group, nodes) in enumerate(groups.items()):
                lines.append(f'    subgraph g{gi}["{_mermaid_escape(group)}"]')
                for node in nodes:
                    sym = idx.symbols[node["symbolId"]]
                    nid = f"n{view_index}_{len(lines)}_{abs(hash(node['symbolId'])) % 9999}"
                    lines.append(f'        {nid}["{_mermaid_escape(sym.qualname)}"]')
                lines.append("    end")
        else:
            lines.append("graph TD")
            ids: list[str] = []
            for i, node in enumerate(view.get("nodes") or []):
                sym = idx.symbols[node["symbolId"]]
                nid = f"n{i}"
                ids.append(nid)
                lines.append(f'    {nid}["{_mermaid_escape(sym.qualname)}"]')
            for link in view.get("links") or []:
                try:
                    a = view["nodes"].index(next(n for n in view["nodes"]
                                                 if n["symbolId"] == link["from"]))
                    b = view["nodes"].index(next(n for n in view["nodes"]
                                                 if n["symbolId"] == link["to"]))
                except (StopIteration, ValueError):
                    continue
                if link["status"] == "direct":
                    lines.append(f"    n{a} --> n{b}")
                elif link["status"] == "reverse":
                    lines.append(f"    n{a} -.->|反向| n{b}")
                else:
                    lines.append(f"    n{a} -.->|推断| n{b}")
        if len(lines) > 1:
            diagrams.append({
                "id": f"diag-{view_index + 1}",
                "kind": kind,
                "title": title,
                "mermaid": "\n".join(lines),
            })
    return diagrams


def _fingerprints(idx: Index, views: list[dict], segments: list[dict]) -> dict[str, Fingerprint]:
    ids: set[str] = set()
    for view in views:
        for node in view.get("nodes") or []:
            if node.get("symbolId"):
                ids.add(node["symbolId"])
        for msg in view.get("messages") or []:
            if msg.get("symbolId"):
                ids.add(msg["symbolId"])
    for segment in segments:
        if segment.get("symbolId"):
            ids.add(segment["symbolId"])
    return fingerprint_of(idx, sorted(ids))


# --- generation ---------------------------------------------------------

SLICE_TOOL = {
    "name": "emit_slice",
    "description": (
        "Emit a reading slice: one or more views that answer the question, the real "
        "code ranges a reader needs, and short anchored notes. Copy symbol ids "
        "verbatim from the inventory. Never invent ids, files, or line ranges."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {
                "type": "string",
                "description": (
                    "Two to four sentences: what this slice answers, the reading route, "
                    "and what can be skipped. No inventory audit or tooling caveats."
                ),
            },
            "strategies": {
                "type": "array",
                "items": {"type": "string", "enum": list(VIEW_KINDS)},
                "description": "Which lenses the slice uses.",
            },
            "views": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_VIEWS,
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(VIEW_KINDS)},
                        "title": {"type": "string"},
                        "rationale": {"type": "string"},
                        "nodes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "symbolId": {"type": "string"},
                                    "group": {
                                        "type": "string",
                                        "description": "Required for crosscut and zones; bucket/region name.",
                                    },
                                    "depth": {"type": "integer"},
                                    "note": {"type": "string"},
                                    "role": {"type": "string", "enum": list(ROLES)},
                                },
                                "required": ["symbolId"],
                                "additionalProperties": False,
                            },
                        },
                        "messages": {
                            "type": "array",
                            "description": "Only for sequence views.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "from": {"type": "string"},
                                    "to": {"type": "string"},
                                    "label": {"type": "string"},
                                    "symbolId": {"type": "string"},
                                    "status": {"type": "string", "enum": ["direct", "reverse", "inferred"]},
                                },
                                "required": ["from", "to"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["kind", "title", "nodes"],
                    "additionalProperties": False,
                },
            },
            "segments": {
                "type": "array",
                "description": "The actual code ranges, in reading order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbolId": {"type": "string"},
                        "file": {"type": "string"},
                        "startLine": {
                            "type": "integer",
                            "description": "1-based file line inside the symbol body. Omit if unsure.",
                        },
                        "endLine": {
                            "type": "integer",
                            "description": "1-based inclusive file line inside the symbol body. Omit if unsure.",
                        },
                        "role": {"type": "string", "enum": list(ROLES)},
                        "note": {"type": "string"},
                        "flowTitle": {
                            "type": "string",
                            "description": "The view title this segment belongs to, for parallel flows.",
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "annotations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "anchor": {
                            "type": "object",
                            "properties": {
                                "kind": {"type": "string", "enum": ["segment", "symbol", "range"]},
                                "index": {"type": "integer"},
                                "symbolId": {"type": "string"},
                                "file": {"type": "string"},
                                "startLine": {"type": "integer"},
                                "endLine": {"type": "integer"},
                            },
                            "required": ["kind"],
                            "additionalProperties": False,
                        },
                        "markdown": {"type": "string"},
                    },
                    "required": ["anchor", "markdown"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "summary", "strategies", "views", "segments"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You extract the code a person actually needs to read to answer their question.

You are given a language-server inventory: symbols and the calls that really happen.
It is ground truth. You choose what matters, which shape the answer should take, and
which ranges of code the reader should see. You never decide what exists.

Output a slice. A slice has:
- views: one or more lenses over the same material. Use up to six. Multiple `path` or
  `sequence` views are allowed and useful when the question contains several parallel
  flows (for example several HTTP endpoints). Each such view must be internally complete.
- segments: real code ranges, in reading order, each with a role. Prefer 8-40 lines per
  segment; include the lines that carry the logic, not the whole file. You may include
  context outside a symbol body when it is genuinely needed. Set `flowTitle` to the
  view title when a segment belongs to one parallel flow; leave it empty for shared
  context. `startLine`/`endLine` are 1-based file lines and must lie inside the symbol
  body; if you are not sure of the numbers, omit them and the server will use the
  symbol's definition range.
- annotations: one-sentence Markdown notes anchored to a segment or symbol. Say the
  local role in this reading route, or what to skip. Do not repeat the code, the slice
  summary, or a global component explanation.

Pick lenses honestly:
- path: one linear flow, entry to exit. Use for "what happens when X".
- sequence: participants and messages. Use when order between actors matters, or when
  one request fans out.
- crosscut: scattered points grouped by purpose. Use for logging, metrics, db, auth.
  Never force these into a path; that line would be false.
- zones: architecture regions. Use for "how is this organised".
- calltree: nested calls under one root.
- dataflow: input → transformation → storage → output.

Composition:
- path + sequence works well (order + actors).
- zones + crosscut works well (regions + concerns).
- path + crosscut only when the crosscut points are explicitly side channels the reader
  may skip; never as a single main chain.
- sequence + crosscut is usually a contradiction; avoid it unless crosscut is a sidebar.
- For `crosscut` and `zones`, every node MUST have a non-empty `group`. If you cannot
  put the material into at least two real groups, do not emit that view; use `path` or
  `calltree` instead.

Rules that matter:
1. Copy symbol ids verbatim. An invented id is discarded.
2. A claimed call must be a real edge in the inventory. If a hop is an inference, say so
   in the node note; do not present it as a direct call. In a `path` or `calltree`,
   order nodes by the actual call/control sequence. Do not insert a factory/assembly
   helper between two functions that directly call each other; mention the helper in a
   note instead. If the evidence cannot order the calls, use `zones` or `calltree`
   rather than forcing a linear path.
3. If the inventory cannot prove a needed edge, choose a view that does not pretend it
   is a direct call, or omit the edge. Do not write an inventory audit: no LSP/索引/
   called-by empty/unresolved/tooling caveats in `summary` or annotations. One short
   neutral limitation is enough only when it changes what the reader should do.
4. `summary` is a reading orientation, not a second global explanation: what question
   this slice answers, the route, and what can be skipped. Two to four sentences.
5. Write title, summary, notes, and rationale in the same language as the question.
6. Keep the slice scoped: a reader should finish it knowing what to read next, and what
   they can safely skip.
7. For stage-one architecture questions, do not produce function-by-function detail;
   a slice is stage three and may go finer.
"""


def _scope_text(scope: dict | None) -> str:
    if not scope:
        return ""
    lines = [f"SCOPE KIND: {scope.get('kind') or 'query'}"]
    for key in ("file", "symbolId", "startLine", "endLine", "module", "planStep",
                "skeletonId", "nodeId", "label"):
        if scope.get(key) not in (None, ""):
            lines.append(f"{key}: {scope[key]}")
    if scope.get("text"):
        lines.append("SELECTED CODE:\n" + str(scope["text"])[:8000])
    return "\n".join(lines)


def request_slice(idx: Index, query: str, *, strategies: list[str] | None = None,
                  scope: dict | None = None, inventory: str | None = None) -> dict:
    inv = inventory if inventory is not None else build_scoped_inventory(
        idx, query, scope)
    wanted = ", ".join(strategies or []) or "choose what fits"
    user = (
        f"QUESTION: {query}\n"
        f"REQUESTED LENSES: {wanted}\n"
        f"{_scope_text(scope)}\n"
        "\nProduce the slice."
    )
    raw = call_tool(
        system_text=SYSTEM_PROMPT,
        inventory=inv,
        user_text=user,
        tool=SLICE_TOOL,
        max_tokens=7000,
        timeout=180,
    )
    views, rejected = validate_slice_views(raw, idx, query)
    return {
        "title": str(raw.get("title") or query).strip(),
        "summary": str(raw.get("summary") or "").strip(),
        "strategies": [str(x) for x in (raw.get("strategies") or [])],
        "views": views,
        "segments": list(raw.get("segments") or []),
        "annotations": list(raw.get("annotations") or []),
        "rejected": rejected,
    }


def heuristic_payload(idx: Index, query: str) -> dict:
    bundle = heuristic_views(idx, query)
    views: list[dict] = []
    for view in bundle.views:
        nodes = [{
            "symbolId": n.symbol_id, "group": n.group, "depth": n.depth,
            "note": n.note, "role": "context",
        } for n in view.nodes]
        views.append({
            "kind": view.kind, "title": view.title, "rationale": view.rationale,
            "nodes": nodes, "messages": [], "links": [],
        })
    if not views:
        nodes = [{"symbolId": s.id, "group": "相关符号", "depth": 0,
                  "note": "", "role": "context"}
                 for s in sorted(idx.callable_symbols(), key=lambda s: s.id)[:12]]
        if nodes:
            views = [{
                "kind": "crosscut", "title": "本地匹配",
                "rationale": "模型不可用，按名称/文件匹配的占位结果。",
                "nodes": nodes, "messages": [], "links": [],
            }]
    return {
        "title": query,
        "summary": bundle.summary + "\n\n_本地启发式结果；配置模型后可获得真正的切片策略。_",
        "strategies": sorted({v["kind"] for v in views}),
        "views": views,
        "segments": [],
        "annotations": [],
        "rejected": bundle.rejected,
    }


# --- storage ------------------------------------------------------------


def save_slice(root: pathlib.Path, idx: Index, payload: dict, *,
               track_id: str, source: dict,
               replace_id: str | None = None,
               created_at: str | None = None) -> Slice:
    query = str(payload.get("query") or payload.get("title") or "未命名切片").strip()
    views, rejected = validate_slice_views(payload, idx, query)
    if not views:
        raise SliceError("模型没有生成任何可读视图")

    segments = validate_segments(payload.get("segments"), root, idx, views)
    annotations = validate_annotations(payload.get("annotations"), root, idx, segments)
    diagrams = build_diagrams(views, idx)
    fingerprints = _fingerprints(idx, views, segments)
    if not fingerprints:
        raise SliceError("切片没有落到任何真实符号")

    title = str(payload.get("title") or query).strip()
    if replace_id and not _safe_id(replace_id):
        raise SliceError("invalid slice id")
    slice_ = Slice(
        id=replace_id or _new_id(title),
        track_id=track_id,
        title=title,
        query=query,
        summary=str(payload.get("summary") or "").strip(),
        strategies=[str(x) for x in (payload.get("strategies") or
                                     sorted({v["kind"] for v in views}))],
        views=views,
        segments=segments,
        annotations=annotations,
        diagrams=diagrams,
        source=source,
        rejected=[str(x) for x in (rejected + list(payload.get("rejected") or []))],
        created_at=created_at or _now(),
        revision=idx.revision,
        fingerprints=fingerprints,
    )

    directory = root / SLICE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{slice_.id}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"version": FORMAT_VERSION, "slice": slice_.to_dict()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(target)
    return slice_


def generate_slice(root: pathlib.Path, idx: Index, *, track_id: str,
                   query: str, strategies: list[str] | None = None,
                   scope: dict | None = None,
                   inventory: str | None = None,
                   replace_id: str | None = None,
                   created_at: str | None = None,
                   allow_fallback: bool = True) -> tuple[Slice, str]:
    """Return (slice, source) where source is 'model' or 'heuristic'."""
    source = "model"
    try:
        payload = request_slice(idx, query, strategies=strategies, scope=scope,
                                inventory=inventory)
        payload["query"] = query
        slice_ = save_slice(root, idx, payload, track_id=track_id, source={
            "kind": (scope or {}).get("kind") or "query",
            "label": (scope or {}).get("label") or query,
            "ref": scope or {},
            "generator": source,
        }, replace_id=replace_id, created_at=created_at)
        return slice_, source
    except (LlmError, SliceError) as exc:
        if not allow_fallback:
            raise
        payload = heuristic_payload(idx, query)
        payload["summary"] += f"\n\n_模型输出不可用（{exc}），以下是本地匹配结果。_"
        payload["query"] = query
        source = "heuristic"
        slice_ = save_slice(root, idx, payload, track_id=track_id, source={
            "kind": (scope or {}).get("kind") or "query",
            "label": (scope or {}).get("label") or query,
            "ref": scope or {},
            "generator": source,
        }, replace_id=replace_id, created_at=created_at)
        return slice_, source


def regenerate_slice(root: pathlib.Path, idx: Index, slice_id: str,
                     *, inventory: str | None = None) -> tuple[Slice, str]:
    old = load_slice(root, slice_id)
    if old is None:
        raise SliceError("slice not found")
    scope = old.source.get("ref") if isinstance(old.source.get("ref"), dict) else None
    try:
        slice_, source = generate_slice(
            root, idx,
            track_id=old.track_id,
            query=old.query or old.title,
            strategies=old.strategies,
            scope=scope,
            inventory=inventory,
            replace_id=old.id,
            created_at=old.created_at,
            allow_fallback=False,
        )
    except LlmError as exc:
        raise SliceError(f"模型生成失败，旧切片已保留：{exc}") from exc
    return slice_, source


def load_slice(root: pathlib.Path, slice_id: str) -> Slice | None:
    if not _safe_id(slice_id):
        return None
    path = root / SLICE_DIR / f"{slice_id}.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        body = raw.get("slice") if isinstance(raw, dict) else None
        return Slice.from_dict(body) if isinstance(body, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def list_slices(root: pathlib.Path) -> list[Slice]:
    directory = root / SLICE_DIR
    if not directory.is_dir():
        return []
    out: list[Slice] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        slice_ = load_slice(root, path.stem)
        if slice_ is not None:
            out.append(slice_)
    return out


def delete_slice(root: pathlib.Path, slice_id: str) -> bool:
    if not _safe_id(slice_id):
        return False
    path = root / SLICE_DIR / f"{slice_id}.json"
    if not path.is_file():
        return False
    path.unlink()
    return True


def rename_slice(root: pathlib.Path, slice_id: str, name: str) -> Slice | None:
    slice_ = load_slice(root, slice_id)
    if slice_ is None or not name.strip():
        return None
    slice_.title = name.strip()[:120]
    path = root / SLICE_DIR / f"{slice_id}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"version": FORMAT_VERSION, "slice": slice_.to_dict()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)
    return slice_


def check_slice_staleness(slice_: Slice, idx: Index):
    return staleness_of(slice_.revision, slice_.fingerprints, idx)


def slice_record(slice_: Slice, idx: Index) -> dict:
    record = slice_.to_dict()
    record.pop("fingerprints", None)
    record["staleness"] = check_slice_staleness(slice_, idx).to_dict()
    record["symbolCount"] = len({n.get("symbolId")
                                 for v in slice_.views for n in (v.get("nodes") or [])
                                 if n.get("symbolId")} | {
                                     s.get("symbolId") for s in slice_.segments
                                     if s.get("symbolId")})
    record["segmentCount"] = len(slice_.segments)
    thin = 0
    for segment in slice_.segments:
        try:
            thin += 1 if int(segment.get("endLine") or 0) - int(segment.get("startLine") or 0) <= 0 else 0
        except (TypeError, ValueError):
            thin += 1
    ungrouped = any(
        view.get("kind") in ("crosscut", "zones")
        and (view.get("nodes") or [])
        and not any(node.get("group") for node in (view.get("nodes") or []))
        for view in slice_.views
    )
    record["quality"] = {
        "thinSegments": thin,
        "ungroupedViews": ungrouped,
        "ok": thin == 0 and not ungrouped,
    }
    return record


def slices_with_staleness(root: pathlib.Path, idx: Index) -> list[dict]:
    return [slice_record(s, idx) for s in list_slices(root)]
