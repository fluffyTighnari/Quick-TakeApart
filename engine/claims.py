"""Structured claims, validated against the index before any prose is rendered.

The failure mode this prevents: a model narrating a system from reading order
produces fluent sentences that name components without asserting anything
checkable ("this layer handles business logic"). Claims are typed, anchored,
and verified against real symbols and edges; anything unverifiable is dropped
rather than softened into vagueness.
"""

from __future__ import annotations

import dataclasses
from typing import Literal

from .model import Index

ClaimKind = Literal[
    "calls",        # A calls B, with the call site
    "called_by",    # B is called by A
    "reads",        # A reads/writes a module-level thing (informational)
    "boundary",     # A is the only path between two zones
    "holds",        # an invariant that can be checked by reading a range
    "unresolved",   # A makes a call we could not resolve — must be said out loud
]

PREDICATE_BY_KIND: dict[str, str] = {
    "calls": "calls",
    "called_by": "is called by",
    "reads": "references",
    "boundary": "is the boundary between",
    "holds": "holds",
    "unresolved": "makes an unresolvable call to",
}


@dataclasses.dataclass(frozen=True, slots=True)
class Claim:
    kind: ClaimKind
    subject: str            # symbol id
    object: str             # symbol id (or literal name for unresolved)
    anchor_file: str        # where the evidence lives
    anchor_line: int        # 1-based
    text: str = ""          # optional model prose; never rendered if unverified


@dataclasses.dataclass(frozen=True, slots=True)
class Rejection:
    claim: Claim
    reason: str


@dataclasses.dataclass
class Verification:
    accepted: list[Claim]
    rejected: list[Rejection]

    @property
    def ok(self) -> bool:
        return not self.rejected

    def summary(self) -> str:
        return f"{len(self.accepted)} accepted, {len(self.rejected)} rejected"


def verify(claims: list[Claim], idx: Index) -> Verification:
    """Keep only claims that the index can prove."""
    edge_pairs = {(e.caller_id, e.callee_id) for e in idx.edges}
    by_id = idx.symbols
    unresolved_pairs = {(c, n) for c, n, _ in idx.unresolved_calls}

    accepted: list[Claim] = []
    rejected: list[Rejection] = []

    for c in claims:
        if c.subject not in by_id:
            rejected.append(Rejection(c, f"unknown subject: {c.subject}"))
            continue

        subj = by_id[c.subject]

        if c.kind == "calls":
            if c.object not in by_id:
                rejected.append(Rejection(c, f"unknown callee: {c.object}"))
                continue
            if (c.subject, c.object) not in edge_pairs:
                rejected.append(Rejection(
                    c, f"no such edge: {_short(c.subject)} -> {_short(c.object)}"))
                continue
            if not _line_in_range(c.anchor_line, subj.body_range):
                rejected.append(Rejection(
                    c, f"anchor line {c.anchor_line} outside "
                       f"{_span(subj.body_range)}"))
                continue
            accepted.append(c)

        elif c.kind == "called_by":
            if c.object not in by_id:
                rejected.append(Rejection(c, f"unknown caller: {c.object}"))
                continue
            if (c.object, c.subject) not in edge_pairs:
                rejected.append(Rejection(
                    c, f"no such edge: {_short(c.object)} -> {_short(c.subject)}"))
                continue
            accepted.append(c)

        elif c.kind == "unresolved":
            if (c.subject, c.object) not in unresolved_pairs:
                rejected.append(Rejection(
                    c, f"not recorded as unresolved: {_short(c.subject)} -> {c.object}"))
                continue
            accepted.append(c)

        elif c.kind == "holds":
            if not _line_in_range(c.anchor_line, subj.body_range):
                rejected.append(Rejection(
                    c, f"anchor line {c.anchor_line} outside subject range"))
                continue
            if not c.text.strip():
                rejected.append(Rejection(c, "invariant claim has no text"))
                continue
            accepted.append(c)

        elif c.kind == "boundary":
            if c.object not in by_id:
                rejected.append(Rejection(c, f"unknown object: {c.object}"))
                continue
            if not ((c.subject, c.object) in edge_pairs
                    or (c.object, c.subject) in edge_pairs):
                rejected.append(Rejection(c, "no edge connects the two symbols"))
                continue
            accepted.append(c)

        else:
            rejected.append(Rejection(c, f"unknown claim kind: {c.kind}"))

    return Verification(accepted, rejected)


def _line_in_range(line: int, rng) -> bool:
    return rng.start_line + 1 <= line <= rng.end_line + 1


def _span(rng) -> str:
    return f"{rng.start_line + 1}-{rng.end_line + 1}"


def _short(symbol_id: str) -> str:
    rel, _, qual = symbol_id.partition("::")
    return f"{rel.rsplit('/', 1)[-1]}.{qual}"


def claims_from_edges(idx: Index, symbol_ids: list[str],
                      *, site_lead: int = 1) -> list[Claim]:
    """Mine provable claims straight from the graph — no model involved.

    This is the floor the narrator builds on: every one of these is true by
    construction, so a rendered explanation can never start from invention.
    """
    wanted = set(symbol_ids)
    out: list[Claim] = []

    for e in idx.edges:
        if e.caller_id not in wanted:
            continue
        src = idx.symbols.get(e.caller_id)
        if src is None:
            continue
        out.append(Claim(
            kind="calls",
            subject=e.caller_id,
            object=e.callee_id,
            anchor_file=src.relpath,
            anchor_line=e.site.start_line + 1,
        ))

    for caller_id, name, site in idx.unresolved_calls:
        if caller_id not in wanted:
            continue
        src = idx.symbols.get(caller_id)
        if src is None:
            continue
        out.append(Claim(
            kind="unresolved",
            subject=caller_id,
            object=name,
            anchor_file=src.relpath,
            anchor_line=site.start_line + 1,
        ))

    return out
