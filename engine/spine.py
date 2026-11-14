"""Extract golden execution paths ("spines") from the call graph.

A spine is an ordered list of resolved edges starting at a real entry point.
Entry points are taken from artifacts that already prove the path runs: tests,
``__main__`` blocks, and module-level functions named like handlers.
Nothing here is guessed — every step is an edge the indexer verified.
"""

from __future__ import annotations

import dataclasses
import pathlib
import re

from .model import Edge, Index, Symbol

# names that usually carry I/O or process boundaries; used only for scoring
IO_HINTS = re.compile(
    r"\b(open|read|write|save|load|fetch|request|send|recv|query|commit|"
    r"render|print|log|upload|download|parse|decode|encode|connect|exec)\w*",
    re.IGNORECASE,
)
ENTRY_NAME_HINTS = re.compile(r"^(main|run|start|serve|handle|on_|entry|cli)\w*", re.IGNORECASE)


@dataclasses.dataclass(frozen=True, slots=True)
class Entry:
    symbol_id: str
    reason: str
    score: float


@dataclasses.dataclass
class Step:
    edge: Edge
    from_symbol: Symbol
    to_symbol: Symbol
    depth: int

    @property
    def is_cross_file(self) -> bool:
        return self.from_symbol.relpath != self.to_symbol.relpath


@dataclasses.dataclass
class Spine:
    entry: Entry
    steps: list[Step]
    # node_id -> resolved outgoing edges that were NOT followed
    branch_points: dict[str, list[str]]
    truncated: list[str]

    @property
    def symbol_ids(self) -> list[str]:
        out: list[str] = []
        for s in self.steps:
            if s.from_symbol.id not in out:
                out.append(s.from_symbol.id)
            if s.to_symbol.id not in out:
                out.append(s.to_symbol.id)
        return out

    @property
    def files(self) -> list[str]:
        seen: list[str] = []
        for step in self.steps:
            for rel in (step.from_symbol.relpath, step.to_symbol.relpath):
                if rel not in seen:
                    seen.append(rel)
        return seen


def find_entries(idx: Index, limit: int = 12) -> list[Entry]:
    """Entry candidates ranked by how strongly they are evidenced as real starts."""
    out: list[Entry] = []
    indeg: dict[str, int] = {}
    for e in idx.edges:
        indeg[e.callee_id] = indeg.get(e.callee_id, 0) + 1
    outdeg: dict[str, int] = {}
    for e in idx.edges:
        outdeg[e.caller_id] = outdeg.get(e.caller_id, 0) + 1

    by_id = idx.symbols
    has_incoming = set(indeg)

    for sid, sym in by_id.items():
        if not sym.is_callable:
            continue
        score = 0.0
        reasons: list[str] = []
        relbase = pathlib.PurePosixPath(sym.relpath).name

        is_test = bool(re.match(r"(test_|.*_test\.py$)", relbase)) or sym.qualname.startswith("test")
        if is_test and sym.name.startswith("test"):
            score += 10.0
            reasons.append("test function")

        if sym.name == "<module>":
            continue

        if sym.name in ("main", "__main__") or sym.qualname.endswith(".__main__"):
            score += 9.0
            reasons.append("main()")

        if ENTRY_NAME_HINTS.match(sym.name) and sym.name not in ("main",):
            score += 3.0
            reasons.append("handler-like name")

        # a true root has no callers inside the project
        if sid not in has_incoming:
            score += 4.0
            reasons.append("no internal callers")

        if sid in has_incoming and is_test:
            pass  # tests are called by the runner, not by the code

        outs = outdeg.get(sid, 0)
        if outs >= 2:
            score += min(outs, 8) * 0.5
            reasons.append(f"{outs} outgoing calls")

        if score <= 0:
            continue
        out.append(Entry(sid, " + ".join(reasons), score))

    out.sort(key=lambda e: (-e.score, e.symbol_id))
    return out[:limit]


def extract_spine(idx: Index, entry: Entry, *, max_depth: int = 8,
                  max_steps: int = 60) -> Spine:
    """Breadth-first walk from `entry`: a call chain is read level by level.

    Depth-first interleaves sibling calls with their callees, which makes the
    printed order look like execution order when it is not. Breadth-first keeps
    each hop narrated together with everything else at that hop.
    """
    by_id = idx.symbols
    out_map: dict[str, list[Edge]] = {}
    for e in idx.edges:
        out_map.setdefault(e.caller_id, []).append(e)

    steps: list[Step] = []
    branches: dict[str, list[str]] = {}
    truncated: list[str] = []
    visited: set[str] = {entry.symbol_id}

    def weight(e: Edge) -> tuple[int, int]:
        tgt = by_id[e.callee_id]
        score = 0
        if IO_HINTS.search(tgt.name):
            score += 2
        if e.kind == "cross":
            score += 1
        return (score, -tgt.range.line_count)

    frontier: list[tuple[str, int]] = [(entry.symbol_id, 0)]
    while frontier and len(steps) < max_steps:
        next_frontier: list[tuple[str, int]] = []
        for sid, depth in frontier:
            if len(steps) >= max_steps:
                break
            if depth >= max_depth:
                if out_map.get(sid):
                    truncated.append(sid)
                continue
            edges = sorted(out_map.get(sid, []), key=weight, reverse=True)
            followed = []
            for e in edges:
                if e.callee_id in visited:
                    continue
                src, dst = by_id.get(e.caller_id), by_id.get(e.callee_id)
                if src is None or dst is None:
                    continue
                visited.add(e.callee_id)
                steps.append(Step(e, src, dst, depth))
                followed.append(e.callee_id)
                next_frontier.append((e.callee_id, depth + 1))
                if len(steps) >= max_steps:
                    break
            skipped = [e.callee_id for e in edges if e.callee_id not in followed]
            if skipped:
                branches[sid] = skipped
        frontier = next_frontier

    if frontier:
        truncated.extend(sid for sid, _ in frontier)

    return Spine(entry, steps, branches, truncated)
