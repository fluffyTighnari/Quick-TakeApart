"""Render an explanation from verified structure.

Output is derived, not narrated: every statement traces to a symbol id, an
edge, or a symbol range. Where the graph cannot say anything (external calls,
dynamic dispatch) it says so instead of filling the gap.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re

from .claims import Claim, claims_from_edges, verify
from .layers import Zone, levels_of
from .model import Index
from .spine import Spine, extract_spine, find_entries

SIGNAL_IO = re.compile(
    r"(open|read|write|save|load|fetch|request|send|recv|query|commit|"
    r"render|print|log|upload|download|connect|exec|run|serve|handle)",
    re.IGNORECASE,
)


def _short(symbol_id: str) -> str:
    rel, _, qual = symbol_id.partition("::")
    return f"{rel.rsplit('/', 1)[-1]}.{qual}"


def _loc(sym, line: int | None = None) -> str:
    ln = line if line is not None else sym.body_range.start_line + 1
    return f"{sym.relpath}:{ln}"


def _is_test_path(rel: str) -> bool:
    name = pathlib.PurePosixPath(rel).name
    return name.startswith("test_") or name.endswith("_test.py") or "/tests/" in f"/{rel}"


def _is_stub_path(rel: str) -> bool:
    return "/spike/" in f"/{rel}" or rel.startswith("spike/")


@dataclasses.dataclass
class Explanation:
    text: str
    stats: dict[str, int]


def explain(idx: Index, *, max_spines: int = 1, depth: int = 6,
            skip_tests: bool = True, skip_stubs: bool = True) -> Explanation:
    lines: list[str] = []
    stats = {"claims": 0, "rejected": 0, "spines": 0, "unresolved": len(idx.unresolved_calls)}

    production = [s for s in idx.callable_symbols()
                  if not (skip_tests and _is_test_path(s.relpath))
                  and not (skip_stubs and _is_stub_path(s.relpath))]

    files = sorted({s.relpath for s in idx.symbols.values()
                    if not (skip_tests and _is_test_path(s.relpath))
                    and not (skip_stubs and _is_stub_path(s.relpath))})
    total_lines = 0
    for rel in files:
        path = pathlib.Path(idx.root) / rel
        try:
            total_lines += sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
        except OSError:
            pass

    # ---- layer 1: orientation ----
    lines.append("# What this is")
    lines.append("")
    lines.append(f"{len(files)} files · {len(production)} functions/methods · "
                 f"{total_lines} lines · {len(idx.edges)} resolved call edges")
    ext = {}
    for _, name, _ in idx.unresolved_calls:
        ext[name] = ext.get(name, 0) + 1
    if ext:
        top = ", ".join(f"{n}({c})" for n, c in
                        sorted(ext.items(), key=lambda kv: -kv[1])[:6])
        lines.append(f"Most frequent calls leaving the project: {top}.")
    lines.append("")

    entries = find_entries(idx)
    if skip_tests:
        entries = [e for e in entries if not _is_test_path(idx.symbols[e.symbol_id].relpath)]
    if skip_stubs:
        entries = [e for e in entries
                   if not _is_stub_path(idx.symbols[e.symbol_id].relpath)]
    if not entries:
        lines.append("_No entry point identified: nothing in the graph is both uncalled "
                     "and calling inward. That usually means the project is a library._")
        lines.append("")
        return Explanation("\n".join(lines), stats)

    # ---- layer 2: one walkthrough, chosen by evidence ----
    spine = extract_spine(idx, entries[0], max_depth=depth)
    stats["spines"] = 1
    entry_sym = idx.symbols[spine.entry.symbol_id]

    lines.append("# Where a request enters")
    lines.append("")
    lines.append(f"`{entry_sym.signature or entry_sym.name}` at {_loc(entry_sym)}")
    lines.append(f"_chosen because: {spine.entry.reason}_")
    lines.append("")

    crawled = claims_from_edges(idx, spine.symbol_ids)
    verification = verify(crawled, idx)
    stats["claims"] = len(verification.accepted)
    stats["rejected"] = len(verification.rejected)

    lines.append("# What happens, in order")
    lines.append("")
    lines.append("Each step is one call edge that the language server resolved. "
                 "Indentation is call depth, not file structure.")
    lines.append("")

    seen_files: list[str] = []
    for n, step in enumerate(spine.steps, 1):
        indent = "  " * (step.depth + 1)
        site_loc = f"{step.from_symbol.relpath}:{step.edge.site.start_line + 1}"
        def_loc = f"{step.to_symbol.relpath}:{step.to_symbol.body_range.start_line + 1}"
        lines.append(f"{indent}{n}. `{step.from_symbol.qualname}` → "
                     f"`{step.to_symbol.qualname}`")
        lines.append(f"{indent}   called at {site_loc}  ·  defined at {def_loc}")
        if step.to_symbol.signature:
            lines.append(f"{indent}   `{step.to_symbol.signature}`")
        for rel in (step.from_symbol.relpath, step.to_symbol.relpath):
            if rel not in seen_files:
                seen_files.append(rel)
    lines.append("")

    if spine.branch_points:
        lines.append("# Branches the walk did not take")
        lines.append("")
        lines.append("These are real edges too — the flow is not linear.")
        lines.append("")
        for sid, targets in spine.branch_points.items():
            names = ", ".join(f"`{_short(t)}`" for t in targets[:6])
            lines.append(f"- `{_short(sid)}` also calls {names}")
        lines.append("")

    if spine.truncated:
        lines.append(f"_Stopped descending at: "
                     f"{', '.join(f'`{_short(s)}`' for s in spine.truncated[:6])}_")
        lines.append("")

    # ---- layer 3: boundaries actually crossed ----
    lines.append("# What crosses a boundary")
    lines.append("")
    boundary_claims = [
        c for c in verification.accepted
        if c.kind in ("calls", "called_by", "boundary")
        and c.object in idx.symbols
        and idx.symbols[c.subject].relpath != idx.symbols[c.object].relpath
    ]
    if not boundary_claims:
        lines.append("_The walked path never leaves a single file._")
    for c in boundary_claims[:12]:
        src, dst = idx.symbols[c.subject], idx.symbols[c.object]
        lines.append(f"- `{src.qualname}` ({src.relpath}:{c.anchor_line}) "
                     f"calls `{dst.qualname}` in {dst.relpath}")
    lines.append("")

    walked = 0
    total_out = 0
    for d in spine.symbol_ids:
        total_out += len(idx.outgoing(d))
        walked += sum(1 for e in idx.outgoing(d) if e.callee_id in spine.symbol_ids)
    if total_out > walked:
        lines.append(f"**This path covers {walked} of {total_out} outgoing calls** from the "
                     f"functions it visits — the rest are real edges, still unread.")
        lines.append("")

    # ---- layer 4: honest gaps ----
    external = [c for c in verification.accepted if c.kind == "unresolved"]
    if external:
        by_target: dict[str, list[Claim]] = {}
        for c in external:
            by_target.setdefault(c.object, []).append(c)
        lines.append("# What could not be resolved")
        lines.append("")
        lines.append("Calls leaving the project, or through dynamic dispatch. These are "
                     "**not** analysed — treat them as boundaries, not as known behaviour.")
        lines.append("")
        for name, cs in sorted(by_target.items(), key=lambda kv: -len(kv[1]))[:10]:
            where = ", ".join(f"{idx.symbols[c.subject].relpath}:{c.anchor_line}"
                              for c in cs[:3])
            lines.append(f"- `{name}` × {len(cs)}  ({where})")
        lines.append("")

    return Explanation("\n".join(lines), stats)
