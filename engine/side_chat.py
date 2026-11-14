"""Side-panel answers with verifiable references.

The side panel is not a generic chatbot. It answers a question about one slice, in
the context of the selected code, and every symbol or line reference it emits is
checked against the index. Answers can suggest a new slice, but they cannot mutate
the current plan; promotion is an explicit user action.
"""

from __future__ import annotations

import pathlib
import re

from .llm import LlmError, call_tool
from .model import Index
from .slices import Slice

SYM_TOKEN = re.compile(r"\[\[sym:([^|\]]+)(?:\|([^\]]+))?\]\]")
LOC_TOKEN = re.compile(r"\[\[loc:(.+?):(\d+)(?:-(\d+))?(?:\|([^\]]+))?\]\]")


SIDE_TOOL = {
    "name": "answer_question",
    "description": (
        "Answer a question about a reading slice. Use only real symbols and ranges "
        "from the provided material. Return citations separately from the prose."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reply": {
                "type": "string",
                "description": (
                    "Markdown answer in the user's language. Reference real symbols with "
                    "[[sym:path::qualname|label]] and real ranges with "
                    "[[loc:path:12-28|label]]. Do not output HTML."
                ),
            },
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["symbol", "range"]},
                        "symbolId": {"type": "string"},
                        "file": {"type": "string"},
                        "startLine": {"type": "integer"},
                        "endLine": {"type": "integer"},
                        "label": {"type": "string"},
                    },
                    "required": ["kind"],
                    "additionalProperties": False,
                },
            },
            "suggestedSlices": {
                "type": "array",
                "description": "Optional follow-up slices the reader may want to generate.",
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "title": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["query", "title"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["reply", "citations"],
        "additionalProperties": False,
    },
}


SYSTEM_PROMPT = """You are the side panel of a code-reading tool. Answer the user's question
about the current slice, using the provided code and the language-server inventory.

Rules:
1. Every symbol you name must be copied from the inventory. Every line range must be
   inside a real file. If you are unsure, say what you cannot verify instead of guessing.
2. Prefer short, anchored explanations over summaries. Use [[sym:...]] and [[loc:...]]
   tokens so the reader can jump to the code.
3. The slice is the scope. If the answer requires code outside it, say so and suggest a
   follow-up slice in `suggestedSlices`; do not pretend the slice contains it.
4. Do not repeat whole functions. Quote only the lines that carry the point.
5. The thread is independent from the plan-design conversation. Do not assume you know
   the plan unless it is included in the material.
6. Write in the same language as the user's question.
7. Do not write an inventory audit. Do not mention LSP, called-by emptiness, unresolved
   symbols, or analysis-tool limits unless the user explicitly asks about them. Answer
   the reading question directly.
8. Do not output raw HTML. Markdown, Mermaid fences, and the token syntax only."""


def _slice_material(slice_: Slice, context: dict | None) -> str:
    lines: list[str] = []
    lines.append(f"SLICE: {slice_.title}")
    lines.append(f"QUERY: {slice_.query}")
    if slice_.summary:
        lines.append("SUMMARY:\n" + slice_.summary)
    lines.append("STRATEGIES: " + ", ".join(slice_.strategies))

    for view in slice_.views:
        lines.append(f"\nVIEW [{view.get('kind')}] {view.get('title')}")
        if view.get("rationale"):
            lines.append("RATIONALE: " + str(view["rationale"]))
        for node in view.get("nodes") or []:
            lines.append(f"  node {node.get('symbolId')} role={node.get('role')} "
                         f"note={node.get('note') or ''}")
        for msg in view.get("messages") or []:
            lines.append(f"  message {msg.get('from')} -> {msg.get('to')} "
                         f"[{msg.get('status')}] {msg.get('label') or ''}")

    for seg in slice_.segments:
        lines.append(f"\nSEGMENT {seg.get('id')} {seg.get('file')}:"
                     f"{seg.get('startLine')}-{seg.get('endLine')} "
                     f"role={seg.get('role')} symbol={seg.get('symbolId') or ''}")
        if seg.get("note"):
            lines.append("NOTE: " + str(seg["note"]))

    if context:
        lines.append("\nSELECTED CONTEXT:")
        lines.append(f"file={context.get('file')} "
                     f"start={context.get('startLine')} end={context.get('endLine')} "
                     f"columns={context.get('startColumn', 0)}-{context.get('endColumn', 0)}")
        if context.get("symbolId"):
            lines.append("symbol=" + str(context["symbolId"]))
        if context.get("text"):
            lines.append(str(context["text"])[:8000])

    return "\n".join(lines)


def _segment_code(root: pathlib.Path, slice_: Slice, limit: int = 14000) -> str:
    chunks: list[str] = []
    total = 0
    for seg in slice_.segments:
        try:
            text = (root / str(seg["file"])).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        start = max(1, int(seg["startLine"]))
        end = min(len(lines), int(seg["endLine"]))
        block = "\n".join(f"{n:>5} {lines[n - 1]}" for n in range(start, end + 1))
        header = f"\n--- {seg['file']}:{start}-{end} ({seg.get('role')})"
        if total + len(block) > limit:
            chunks.append(header + "\n[truncated]")
            break
        chunks.append(header + "\n" + block)
        total += len(block)
    return "\n".join(chunks)


def _focused_inventory(idx: Index, symbol_ids: set[str]) -> str:
    names = {sid: s.qualname for sid, s in idx.symbols.items()}
    out_edges: dict[str, list[str]] = {}
    in_edges: dict[str, list[str]] = {}
    for e in idx.edges:
        if e.caller_id in symbol_ids or e.callee_id in symbol_ids:
            out_edges.setdefault(e.caller_id, []).append(e.callee_id)
            in_edges.setdefault(e.callee_id, []).append(e.caller_id)
    lines = ["FOCUSED SYMBOLS", "Format: <id> | <signature> | calls | called by"]
    for sid in sorted(symbol_ids):
        sym = idx.symbols.get(sid)
        if sym is None:
            continue
        callees = sorted({names.get(c, c) for c in out_edges.get(sid, [])})
        callers = sorted({names.get(c, c) for c in in_edges.get(sid, [])})
        lines.append(f"{sid} | {sym.signature or sym.qualname} | "
                     f"calls: {', '.join(callees[:10]) or '-'} | "
                     f"called by: {', '.join(callers[:8]) or '-'}")
    return "\n".join(lines)


def validate_citations(raw: list | None, idx: Index) -> tuple[list[dict], list[str]]:
    out: list[dict] = []
    rejected: list[str] = []
    files = {s.relpath for s in idx.symbols.values()}
    for item in raw or []:
        kind = str(item.get("kind") or "")
        if kind == "symbol":
            sid = str(item.get("symbolId") or "").strip()
            if sid in idx.symbols:
                out.append({"kind": "symbol", "symbolId": sid,
                            "label": str(item.get("label") or idx.symbols[sid].qualname)})
            else:
                rejected.append(f"citation symbol {sid or '?'}")
        elif kind == "range":
            file = str(item.get("file") or "").strip()
            if file not in files:
                rejected.append(f"citation file {file or '?'}")
                continue
            try:
                start = max(1, int(item.get("startLine") or 1))
                end = max(start, int(item.get("endLine") or start))
            except (TypeError, ValueError):
                rejected.append("citation range with bad lines")
                continue
            out.append({"kind": "range", "file": file, "startLine": start,
                        "endLine": end, "label": str(item.get("label") or f"{file}:{start}")})
        else:
            rejected.append(f"citation kind {kind or '?'}")
    return out, rejected


def validate_tokens(text: str, idx: Index) -> list[str]:
    rejected: list[str] = []
    files = {s.relpath for s in idx.symbols.values()}
    for m in SYM_TOKEN.finditer(text or ""):
        if m.group(1) not in idx.symbols:
            rejected.append(m.group(1))
    for m in LOC_TOKEN.finditer(text or ""):
        file = m.group(1)
        start = int(m.group(2))
        end = int(m.group(3) or start)
        if file not in files or start < 1 or end < start:
            rejected.append(f"{file}:{start}-{end}")
    return rejected


def request_answer(root: pathlib.Path, idx: Index, slice_: Slice,
                   messages: list[dict], question: str,
                   context: dict | None = None) -> dict:
    symbol_ids: set[str] = set()
    for view in slice_.views:
        for node in view.get("nodes") or []:
            if node.get("symbolId"):
                symbol_ids.add(node["symbolId"])
        for msg in view.get("messages") or []:
            if msg.get("symbolId"):
                symbol_ids.add(msg["symbolId"])
    for seg in slice_.segments:
        if seg.get("symbolId"):
            symbol_ids.add(seg["symbolId"])
    if context and context.get("symbolId"):
        symbol_ids.add(context["symbolId"])
    # include one hop of neighbours so the model can answer "who calls this"
    focus_ids = set(symbol_ids)
    for sid in list(symbol_ids):
        symbol_ids.update(e.callee_id for e in idx.edges if e.caller_id == sid)
        symbol_ids.update(e.caller_id for e in idx.edges if e.callee_id == sid)
    # The slice plus one hop is the contract; a hub must not expand it forever.
    extras = [sid for sid in sorted(symbol_ids) if sid not in focus_ids]
    symbol_ids = focus_ids | set(extras[:max(0, 120 - len(focus_ids))])

    inventory = "\n\n".join([
        _focused_inventory(idx, symbol_ids),
        "SLICE MATERIAL\n" + _slice_material(slice_, context),
        "SLICE CODE\n" + _segment_code(root, slice_),
    ])

    history = []
    for msg in messages[-8:]:
        role = "assistant" if msg.get("role") == "assistant" else "user"
        history.append(f"{role.upper()}: {msg.get('content') or ''}")
    user = (
        "THREAD SO FAR:\n" + ("\n".join(history) if history else "(new thread)") +
        f"\n\nUSER QUESTION: {question}\n\nAnswer with citations."
    )
    raw = call_tool(
        system_text=SYSTEM_PROMPT,
        inventory=inventory,
        user_text=user,
        tool=SIDE_TOOL,
        max_tokens=5000,
    )
    citations, rejected = validate_citations(raw.get("citations"), idx)
    reply = str(raw.get("reply") or "").strip()
    rejected += validate_tokens(reply, idx)
    suggested = []
    for item in raw.get("suggestedSlices") or []:
        query = str(item.get("query") or "").strip()
        if query:
            suggested.append({
                "query": query,
                "title": str(item.get("title") or query).strip(),
                "reason": str(item.get("reason") or "").strip(),
            })
    return {"reply": reply, "citations": citations,
            "suggestedSlices": suggested, "rejected": rejected}


def fallback_answer(idx: Index, slice_: Slice, question: str) -> dict:
    citations: list[dict] = []
    for seg in slice_.segments[:8]:
        citations.append({
            "kind": "range", "file": seg["file"],
            "startLine": seg["startLine"], "endLine": seg["endLine"],
            "label": f"{seg['file']}:{seg['startLine']}",
        })
    names = ", ".join(
        sorted({n.get("symbolId", "").split("::")[-1]
                for v in slice_.views for n in (v.get("nodes") or [])
                if n.get("symbolId")})[:12]
    )
    reply = (
        "模型当前不可用，无法生成讲解。\n\n"
        f"问题：{question}\n\n"
        f"这条切片涉及的符号：{names or '（无）'}。\n"
        "可以先打开右侧引用位置阅读；配置 API key 后即可获得基于代码的讲解。"
    )
    return {"reply": reply, "citations": citations,
            "suggestedSlices": [], "rejected": []}


def answer(root: pathlib.Path, idx: Index, slice_: Slice,
           messages: list[dict], question: str,
           context: dict | None = None) -> dict:
    try:
        return request_answer(root, idx, slice_, messages, question, context)
    except LlmError:
        return fallback_answer(idx, slice_, question)
