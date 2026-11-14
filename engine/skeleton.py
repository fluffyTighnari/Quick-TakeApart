"""Stage one, redesigned: a logical skeleton rather than a module showcase.

The old stage one tried to be a module map, sequence viewer, dossier and data-flow
view at once. This module keeps one artifact with two clearly separated parts:

    main flow        an ordered runtime spine (startup -> request -> response)
    parallel support cross-cutting capabilities (config, logging, metrics, errors)

The skeleton is intentionally coarse: a node is a component/responsibility with a
one-line summary and the real symbols/files behind it. Detailed, plain-language
explanations are generated lazily per node and frozen on the skeleton.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import secrets
from datetime import datetime, timezone

from .arch import heuristic_architecture
from .llm import LlmError, call_tool
from .model import Index
from .plan import build_inventory
from .store import Fingerprint, fingerprint_of, staleness_of

SKELETON_DIR = ".qta/skeletons"
FORMAT_VERSION = 1
MAX_MAIN = 12
MAX_SUPPORT = 8


class SkeletonError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^\w一-鿿-]+", "-", text, flags=re.UNICODE).strip("-")
    return cleaned[:40] or fallback


def _new_id(name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{_slug(name, 'skeleton')[:18]}-{secrets.token_hex(2)}"


def _safe_id(value: str) -> bool:
    return bool(value) and not any(c in value for c in ("/", "\\", ".."))


def _node_files(idx: Index, symbol_ids: list[str]) -> list[str]:
    seen: list[str] = []
    for sid in symbol_ids:
        sym = idx.symbols.get(sid)
        if sym and sym.relpath not in seen:
            seen.append(sym.relpath)
    return seen


def _node_symbols(idx: Index, raw_ids: list, rejected: list[str]) -> list[str]:
    out: list[str] = []
    for raw in raw_ids or []:
        sid = str(raw).strip()
        if not sid:
            continue
        if sid not in idx.symbols:
            rejected.append(sid)
            continue
        if sid not in out:
            out.append(sid)
    return out


def _node_links(idx: Index, nodes: list[dict]) -> list[dict]:
    links: list[dict] = []
    for a, b in zip(nodes, nodes[1:]):
        a_ids = set(a.get("symbolIds") or [])
        b_ids = set(b.get("symbolIds") or [])
        direct = next((e for e in idx.edges
                       if e.caller_id in a_ids and e.callee_id in b_ids), None)
        reverse = next((e for e in idx.edges
                        if e.caller_id in b_ids and e.callee_id in a_ids), None)
        edge = direct or reverse
        status = "direct" if direct else "reverse" if reverse else "inferred"
        site = None
        if edge:
            sym = idx.symbols.get(edge.caller_id)
            site = {"file": sym.relpath if sym else "", "line": edge.site.start_line + 1}
        links.append({
            "from": a.get("id"), "to": b.get("id"), "status": status,
            "file": (site or {}).get("file", ""),
            "line": (site or {}).get("line"),
        })
    return links


def _fallback_node(node: dict) -> dict:
    node.setdefault("detail", "")
    node.setdefault("detailCreatedAt", "")
    return node


@dataclasses.dataclass
class Skeleton:
    id: str
    track_id: str
    focus: str
    title: str
    overview: str
    main: list[dict]
    support: list[dict]
    links: list[dict]
    created_at: str
    revision: str
    fingerprints: dict[str, Fingerprint]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trackId": self.track_id,
            "focus": self.focus,
            "title": self.title,
            "overview": self.overview,
            "main": self.main,
            "support": self.support,
            "links": self.links,
            "createdAt": self.created_at,
            "revision": self.revision,
            "fingerprints": {
                sid: {"line": f.line, "endLine": f.end_line, "signature": f.signature}
                for sid, f in self.fingerprints.items()
            },
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Skeleton":
        fps = {
            sid: Fingerprint(int(v.get("line") or 0), int(v.get("endLine") or 0),
                             str(v.get("signature") or ""))
            for sid, v in (raw.get("fingerprints") or {}).items()
        }
        return cls(
            id=str(raw.get("id") or ""),
            track_id=str(raw.get("trackId") or ""),
            focus=str(raw.get("focus") or ""),
            title=str(raw.get("title") or "骨架"),
            overview=str(raw.get("overview") or ""),
            main=list(raw.get("main") or []),
            support=list(raw.get("support") or []),
            links=list(raw.get("links") or []),
            created_at=str(raw.get("createdAt") or ""),
            revision=str(raw.get("revision") or ""),
            fingerprints=fps,
        )


SKELETON_TOOL = {
    "name": "emit_skeleton",
    "description": (
        "Emit a logical skeleton: an ordered main flow plus parallel support nodes. "
        "Every node must list real symbol ids from the inventory. Keep summaries "
        "plain-language and component-level; do not explain functions in detail."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "overview": {"type": "string", "description": "Two or three sentences about the system's shape."},
            "main": {
                "type": "array",
                "minItems": 2,
                "maxItems": MAX_MAIN,
                "description": "Runtime main flow, in order. Each node is a component/responsibility.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Short ASCII slug."},
                        "title": {"type": "string", "description": "Clear component/step name, e.g. 服务启动."},
                        "summary": {"type": "string", "description": "One or two plain-language sentences."},
                        "phase": {"type": "string", "description": "Optional stage label, e.g. 启动阶段."},
                        "symbolIds": {"type": "array", "items": {"type": "string"}},
                        "files": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "title", "summary", "symbolIds"],
                    "additionalProperties": False,
                },
            },
            "support": {
                "type": "array",
                "maxItems": MAX_SUPPORT,
                "description": "Parallel support capabilities, not part of the linear main flow.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "phase": {"type": "string"},
                        "symbolIds": {"type": "array", "items": {"type": "string"}},
                        "files": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id", "title", "summary", "symbolIds"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "overview", "main", "support"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You are building the logical skeleton of a codebase for a reader who wants to understand the complete flow, not every function.

You are given a language-server inventory. It is ground truth: those symbols exist and those calls happen. You decide the components and the order; you never invent symbols.

Produce two parts:

1. `main` — the runtime main flow, in order. Each node is one clear component or
   responsibility, not a file and not a single function. Aim for 6–10 nodes; a tiny
   project may have fewer. Use titles a reader can understand immediately, for example:
   服务启动 / 路由与中间件 / Handler 请求处理 / Service 业务处理 / 数据访问 /
   响应与错误处理. Write a one- or two-sentence plain-language summary: what this
   node does and what it hands to the next node. No code, no function-by-function detail.

   **Stages, not domains.** If several domains (for example users and orders) share the
   same pipeline, represent the shared stages once (handler -> service -> repo -> db) and
   mention the domain variants in the summaries. Do not append one domain branch after
   another as if they ran in sequence. Only split them into separate main nodes when they
   are genuinely sequential in time.

   Independent entry points that do not belong to the main request path — health checks,
   CLIs, background jobs, test-only paths — go into `support` or into `overview`, not at
   the end of `main`.

2. `support` — parallel capabilities that cut across the main flow: configuration,
   logging, metrics, error handling, cache, background workers, independent health
   checks. These are not steps in the linear path. Keep 3–6 nodes. Write a one-sentence
   summary for each.

Rules:
- Every node must list real symbol ids copied verbatim from the inventory. A node with
  no resolvable symbols is discarded.
- `files` is optional; if present, use real indexed file paths. The server derives files
  from symbols when omitted.
- Do not force every function into the skeleton. The main flow is a reading spine, not a
  call graph dump.
- If the inventory cannot support a separate main flow (a flat script), say so in
  `overview` and return the smallest honest skeleton.
- Write title, summaries, phases and overview in the same language as the question."""


def validate_skeleton(raw: dict, idx: Index, focus: str, track_id: str) -> Skeleton:
    rejected: list[str] = []
    title = str(raw.get("title") or "逻辑骨架").strip()
    overview = str(raw.get("overview") or "").strip()

    def parse_nodes(items: list, prefix: str) -> list[dict]:
        out: list[dict] = []
        seen_ids: set[str] = set()
        for index, raw_node in enumerate(items or []):
            symbols = _node_symbols(idx, raw_node.get("symbolIds") or [], rejected)
            if not symbols:
                rejected.append(str(raw_node.get("title") or raw_node.get("id") or "?"))
                continue
            node_id = _slug(str(raw_node.get("id") or raw_node.get("title") or ""),
                            f"{prefix}{index + 1}")
            if node_id in seen_ids:
                node_id = f"{node_id}-{index + 1}"
            seen_ids.add(node_id)
            files = _node_files(idx, symbols)
            raw_files = [str(f).strip() for f in (raw_node.get("files") or [])]
            for file in raw_files:
                if file and file not in files and any(
                        s.relpath == file for s in idx.symbols.values()):
                    files.append(file)
            out.append({
                "id": node_id,
                "title": str(raw_node.get("title") or node_id).strip(),
                "summary": str(raw_node.get("summary") or "").strip(),
                "phase": str(raw_node.get("phase") or "").strip(),
                "symbolIds": symbols,
                "files": files,
                "detail": "",
                "detailCreatedAt": "",
            })
        return out

    main = parse_nodes(raw.get("main") or [], "m")
    support = parse_nodes(raw.get("support") or [], "s")
    if not main:
        raise SkeletonError("骨架没有可落地的主流程节点")

    ids = {sid for node in main + support for sid in node["symbolIds"]}
    skeleton = Skeleton(
        id=_new_id(title),
        track_id=track_id,
        focus=focus,
        title=title,
        overview=overview + (f"\n\n_丢弃了 {len(rejected)} 个无法落地的节点/符号。_" if rejected else ""),
        main=main,
        support=support,
        links=_node_links(idx, main),
        created_at=_now(),
        revision=idx.revision,
        fingerprints=fingerprint_of(idx, sorted(ids)),
    )
    return skeleton


def request_skeleton(idx: Index, focus: str, *, inventory: str) -> Skeleton:
    raw = call_tool(
        system_text=SYSTEM_PROMPT,
        inventory=inventory,
        user_text=(f"FOCUS: {focus or '整体逻辑'}\n"
                   "Build the logical skeleton. Main flow and parallel support."),
        tool=SKELETON_TOOL,
        max_tokens=6000,
        timeout=180,
    )
    return validate_skeleton(raw, idx, focus, "")


def heuristic_skeleton(idx: Index, focus: str = "") -> Skeleton:
    arch = heuristic_architecture(idx)
    nodes = []
    for i, node in enumerate(arch.nodes[:MAX_MAIN]):
        nodes.append({
            "id": node.id,
            "title": node.label,
            "summary": node.note or node.relation or "本地按命名推测的模块。",
            "phase": "本地推测",
            "symbolIds": node.symbol_ids,
            "files": _node_files(idx, node.symbol_ids),
            "detail": "",
            "detailCreatedAt": "",
        })
    support = []
    if len(nodes) > 2:
        support = [nodes.pop()]
    raw = {
        "title": "逻辑骨架（本地推测）",
        "overview": "模型不可用，按文件名与命名推测主流程。配置 key 后可获得真正的骨架与节点讲解。",
        "main": nodes,
        "support": support,
    }
    skeleton = validate_skeleton(raw, idx, focus, "")
    skeleton.id = _new_id(skeleton.title)
    return skeleton


def save_skeleton(root: pathlib.Path, skeleton: Skeleton, *,
                  replace_id: str | None = None,
                  created_at: str | None = None) -> Skeleton:
    if replace_id:
        if not _safe_id(replace_id):
            raise SkeletonError("invalid skeleton id")
        skeleton.id = replace_id
    if created_at:
        skeleton.created_at = created_at
    directory = root / SKELETON_DIR
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{skeleton.id}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"version": FORMAT_VERSION, "skeleton": skeleton.to_dict()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    tmp.replace(target)
    return skeleton


def generate_skeleton(root: pathlib.Path, idx: Index, *, track_id: str,
                      focus: str = "", inventory: str | None = None
                      ) -> tuple[Skeleton, str]:
    try:
        skeleton = request_skeleton(
            idx, focus,
            inventory=inventory if inventory is not None else build_inventory(
                idx, symbol_budget=900, compact=True))
        skeleton.track_id = track_id
        source = "model"
    except (LlmError, SkeletonError):
        skeleton = heuristic_skeleton(idx, focus)
        skeleton.track_id = track_id
        source = "heuristic"
    save_skeleton(root, skeleton)
    return skeleton, source


NODE_TOOL = {
    "name": "explain_skeleton_node",
    "description": (
        "Write a plain-language, file-level explanation of one skeleton node. "
        "No code blocks; use real symbol and location references."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "description": (
                    "Markdown explanation with sections 节点定位 / 核心函数 / 关系与数据流 / "
                    "异常与边界 / 本节点总结. Use [[sym:...]] and [[loc:...]] tokens."
                ),
            },
        },
        "required": ["detail"],
        "additionalProperties": False,
    },
}

NODE_PROMPT = """You are explaining one node of a codebase skeleton to a reader who wants the complete logic, not a function-by-function tour.

Write in the user's language. Use this structure:
## 节点定位
## 核心函数
## 关系与数据流
## 异常与边界
## 本节点总结

Rules:
- File-level explanation. Name functions only where they matter to the logic; do not paste code blocks.
- Explain what the node does, what it depends on, and what it hands to the next node.
- Use plain language. Avoid academic jargon and long lists of symbol names.
- Use [[sym:path::qualname|label]] for important functions and [[loc:path:start-end|label]]
  for real locations. Never invent a symbol or line.
- Only assert behavior supported by the provided code/inventory. Do not invent routes,
  endpoints, middleware, framework behavior, configuration keys or example paths. If the
  material does not show something (for example the actual route table), say
  「索引/代码里没有展开，无法确认」instead of giving a plausible example.
- 600–1200 Chinese characters is usually enough. Be decisive; do not pad.
"""


def _node_code(root: pathlib.Path, idx: Index, node: dict,
               limit: int = 14000) -> str:
    """Show the real code around a node's symbols.

    Symbol lists alone invite the model to infer a route table or middleware that
    does not exist. A bounded code window keeps the explanation grounded without
    pasting whole repositories into the prompt.
    """
    files: list[str] = []
    for sid in node.get("symbolIds") or []:
        sym = idx.symbols.get(sid)
        if sym and sym.relpath not in files:
            files.append(sym.relpath)
    chunks: list[str] = []
    total = 0
    for file in files[:8]:
        try:
            lines = (root / file).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        ranges: list[tuple[int, int]] = []
        for sid in node.get("symbolIds") or []:
            sym = idx.symbols.get(sid)
            if sym is None or sym.relpath != file:
                continue
            start = max(1, sym.body_range.start_line + 1 - 10)
            end = min(len(lines), sym.body_range.end_line + 1 + 4)
            ranges.append((start, end))
        if not ranges:
            ranges = [(1, min(len(lines), 80))]
        ranges.sort()
        merged: list[tuple[int, int]] = []
        for start, end in ranges:
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        for start, end in merged:
            block = "\n".join(f"{n:>5} {lines[n - 1]}"
                              for n in range(start, end + 1))
            header = f"\n--- {file}:{start}-{end}"
            if total + len(block) > limit:
                chunks.append(header + "\n[truncated]")
                return "\n".join(chunks)
            chunks.append(header + "\n" + block)
            total += len(block)
    return "\n".join(chunks)


def _focused_inventory(idx: Index, symbol_ids: list[str]) -> str:
    wanted = set(symbol_ids)
    names = {sid: s.qualname for sid, s in idx.symbols.items()}
    out_edges: dict[str, list[str]] = {}
    in_edges: dict[str, list[str]] = {}
    for e in idx.edges:
        if e.caller_id in wanted or e.callee_id in wanted:
            out_edges.setdefault(e.caller_id, []).append(e.callee_id)
            in_edges.setdefault(e.callee_id, []).append(e.caller_id)
    lines = ["FOCUSED SYMBOLS", "Format: <id> | <signature> | lines | calls | called by"]
    for sid in sorted(wanted):
        sym = idx.symbols.get(sid)
        if sym is None:
            continue
        lines.append(
            f"{sid} | {sym.signature or sym.qualname}"
            f" | lines {sym.body_range.start_line + 1}-{sym.body_range.end_line + 1}"
            f" | calls: {', '.join(sorted(names.get(c, c) for c in out_edges.get(sid, []))[:10]) or '-'}"
            f" | called by: {', '.join(sorted(names.get(c, c) for c in in_edges.get(sid, []))[:8]) or '-'}"
        )
    return "\n".join(lines)


def explain_node(root: pathlib.Path, idx: Index, skeleton: Skeleton,
                 node_id: str) -> tuple[Skeleton, dict]:
    node = next((n for n in skeleton.main + skeleton.support if n.get("id") == node_id), None)
    if node is None:
        raise SkeletonError(f"node not found: {node_id}")
    symbol_ids = list(node.get("symbolIds") or [])
    # one hop of neighbours makes "who calls this" answerable without dumping the project
    for sid in list(symbol_ids):
        symbol_ids += [e.callee_id for e in idx.edges if e.caller_id == sid]
        symbol_ids += [e.caller_id for e in idx.edges if e.callee_id == sid]
    # Keep the node's own symbols first; cap neighbours so a hub cannot turn one
    # node explanation into a project-wide inventory.
    symbol_ids = list(dict.fromkeys(symbol_ids))[:80]

    material = "\n".join([
        f"SKELETON: {skeleton.title}",
        f"OVERVIEW: {skeleton.overview}",
        f"NODE: {node.get('title')}",
        f"PHASE: {node.get('phase') or '-'}",
        f"SUMMARY: {node.get('summary') or '-'}",
        "FILES: " + ", ".join(node.get("files") or []),
        "MAIN FLOW: " + " -> ".join(n.get("title", "") for n in skeleton.main),
        "SUPPORT: " + ", ".join(n.get("title", "") for n in skeleton.support),
        "",
        _focused_inventory(idx, symbol_ids),
        "",
        "REAL CODE AROUND THIS NODE (line numbers are file lines):",
        _node_code(root, idx, node),
    ])
    try:
        raw = call_tool(
            system_text=NODE_PROMPT,
            inventory=material,
            user_text=f"解释节点「{node.get('title')}」。重点讲清完整逻辑与它在主流程中的位置。",
            tool=NODE_TOOL,
            max_tokens=3500,
            timeout=120,
        )
        detail = str(raw.get("detail") or "").strip()
        if not detail:
            raise LlmError("model returned empty explanation")
        source = "model"
    except LlmError:
        names = ", ".join(
            idx.symbols[sid].qualname for sid in node.get("symbolIds") or []
            if sid in idx.symbols
        )
        detail = (
            f"## 节点定位\n{node.get('summary') or node.get('title')}\n\n"
            f"## 核心函数\n{names or '（无）'}\n\n"
            "## 关系与数据流\n模型当前不可用，无法生成完整关系讲解。\n\n"
            "## 本节点总结\n这是本地回退说明；配置模型后可获得完整讲解。"
        )
        source = "heuristic"
    node["detail"] = detail
    node["detailCreatedAt"] = _now()
    node["detailSource"] = source
    save_skeleton(root, skeleton, replace_id=skeleton.id, created_at=skeleton.created_at)
    return skeleton, node


def load_skeleton(root: pathlib.Path, skeleton_id: str) -> Skeleton | None:
    if not _safe_id(skeleton_id):
        return None
    path = root / SKELETON_DIR / f"{skeleton_id}.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        body = raw.get("skeleton") if isinstance(raw, dict) else None
        return Skeleton.from_dict(body) if isinstance(body, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def list_skeletons(root: pathlib.Path) -> list[Skeleton]:
    directory = root / SKELETON_DIR
    if not directory.is_dir():
        return []
    out: list[Skeleton] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        skeleton = load_skeleton(root, path.stem)
        if skeleton is not None:
            out.append(skeleton)
    return out


def delete_skeleton(root: pathlib.Path, skeleton_id: str) -> bool:
    if not _safe_id(skeleton_id):
        return False
    path = root / SKELETON_DIR / f"{skeleton_id}.json"
    if not path.is_file():
        return False
    path.unlink()
    return True


def skeleton_record(skeleton: Skeleton, idx: Index) -> dict:
    record = skeleton.to_dict()
    record.pop("fingerprints", None)
    record["staleness"] = staleness_of(skeleton.revision, skeleton.fingerprints, idx).to_dict()
    record["detailCount"] = sum(
        1 for n in skeleton.main + skeleton.support if n.get("detail"))
    return record


def skeletons_with_staleness(root: pathlib.Path, idx: Index) -> list[dict]:
    return [skeleton_record(s, idx) for s in list_skeletons(root)]
