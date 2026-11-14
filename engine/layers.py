"""Derive structure from the call graph itself.

Two orthogonal axes, because collapsing them produces nonsense:

* **zone** — a connected subgraph. Separate entry points (an LSP client chain,
  a CLI, a test suite) do not belong in the same "layer" just because both sit
  at distance 0. Zones come from weak connectivity.
* **depth** — position inside a zone, from entry-side to leaf-side, along the
  condensation DAG.

A "layer" is a zone at a given depth, which is only meaningful when both are
reported. Reporting depth alone yields one-symbol layers that name nothing.

Nothing here is named by a model: labels are assigned afterwards from evidence
(dominant file, inbound/outbound targets) and can always be overridden.
"""

from __future__ import annotations

import dataclasses
import pathlib

from .model import Edge, Index, Symbol


@dataclasses.dataclass
class Zone:
    """One connected subgraph — usually one entry point and everything it reaches."""

    index: int
    symbol_ids: list[str]
    entry_ids: list[str]  # members with no in-zone callers
    exit_ids: list[str]   # members with no in-zone callees
    label: str = ""

    @property
    def size(self) -> int:
        return len(self.symbol_ids)

    @property
    def files(self) -> list[str]:
        return sorted({sid.split("::", 1)[0] for sid in self.symbol_ids})

    @property
    def depth(self) -> int:
        """Number of distinct layers inside this zone."""
        return len(self.levels())


@dataclasses.dataclass
class Level:
    """All members of one zone at one call depth."""

    depth: int
    symbol_ids: list[str]
    outbound: list[Edge]  # edges leaving this level (may stay in-zone)
    inbound: list[Edge]

    @property
    def size(self) -> int:
        return len(self.symbol_ids)

    def names(self) -> list[str]:
        return sorted(sid.split("::", 1)[1] for sid in self.symbol_ids)


def _sccs(nodes: list[str], adj: dict[str, list[str]]) -> list[list[str]]:
    """Iterative Tarjan — recursion overflows on real call graphs."""
    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0

    for root in nodes:
        if root in index_of:
            continue
        work: list[tuple[str, int]] = [(root, 0)]
        while work:
            node, pi = work.pop()
            if pi == 0:
                index_of[node] = counter
                low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            recursed = False
            neighbours = adj.get(node, [])
            for i in range(pi, len(neighbours)):
                nxt = neighbours[i]
                if nxt not in index_of:
                    work.append((node, i + 1))
                    work.append((nxt, 0))
                    recursed = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index_of[nxt])
            if recursed:
                continue
            if low[node] == index_of[node]:
                comp: list[str] = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                result.append(comp)
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return result


def _weak_components(nodes: list[str],
                     adj: dict[str, list[str]],
                     rev: dict[str, list[str]]) -> list[list[str]]:
    remaining = set(nodes)
    clusters: list[list[str]] = []
    while remaining:
        start = min(remaining)
        remaining.discard(start)
        comp: list[str] = []
        stack = [start]
        while stack:
            n = stack.pop()
            comp.append(n)
            for nxt in (*adj.get(n, ()), *rev.get(n, ())):
                if nxt in remaining:
                    remaining.discard(nxt)
                    stack.append(nxt)
        clusters.append(comp)
    clusters.sort(key=lambda c: (-len(c), c[0]))
    return clusters


def _depths(members: list[str],
            adj: dict[str, list[str]],
            rev: dict[str, list[str]]) -> dict[str, int]:
    """Longest-path depth within a zone; cycles are collapsed first."""
    mset = set(members)
    sub_adj = {n: [m for m in adj.get(n, []) if m in mset] for n in members}
    comps = _sccs(members, sub_adj)
    comp_of: dict[str, int] = {}
    for ci, comp in enumerate(comps):
        for sid in comp:
            comp_of[sid] = ci

    cadj: dict[int, set[int]] = {i: set() for i in range(len(comps))}
    cindeg: dict[int, int] = {i: 0 for i in range(len(comps))}
    for n in members:
        for m in sub_adj.get(n, ()):
            a, b = comp_of[n], comp_of[m]
            if a != b and b not in cadj[a]:
                cadj[a].add(b)
                cindeg[b] += 1

    cdep: dict[int, int] = {i: 0 for i in range(len(comps))}
    ready = [i for i in range(len(comps)) if cindeg[i] == 0]
    seen: set[int] = set()
    while ready:
        n = ready.pop()
        if n in seen:
            continue
        seen.add(n)
        for nxt in cadj[n]:
            cdep[nxt] = max(cdep[nxt], cdep[n] + 1)
            cindeg[nxt] -= 1
            if cindeg[nxt] == 0:
                ready.append(nxt)

    return {n: cdep.get(comp_of[n], 0) for n in members}


def derive_zones(idx: Index, *, min_zone_size: int = 3) -> list[Zone]:
    callables = idx.callable_symbols()
    if not callables:
        return []

    ids = [s.id for s in callables]
    adj: dict[str, list[str]] = {i: [] for i in ids}
    rev: dict[str, list[str]] = {i: [] for i in ids}
    for e in idx.edges:
        if e.caller_id in adj and e.callee_id in adj:
            if e.callee_id not in adj[e.caller_id]:
                adj[e.caller_id].append(e.callee_id)
            if e.caller_id not in rev[e.callee_id]:
                rev[e.callee_id].append(e.caller_id)

    raw = _weak_components(ids, adj, rev)
    zones: list[Zone] = []
    small: list[list[str]] = []
    for cluster in raw:
        if len(cluster) < min_zone_size:
            small.append(cluster)
            continue
        zones.append(_make_zone(len(zones), cluster, adj, rev, idx))

    # tiny disconnected fragments are noise, not structure: fold them into the
    # largest zone that shares a file, else into the largest zone overall
    for cluster in small:
        files = {sid.split("::", 1)[0] for sid in cluster}
        host = next((z for z in zones if files & set(z.files)), None)
        if host is None and zones:
            host = max(zones, key=lambda z: z.size)
        if host is None:
            continue
        merged = sorted(set(host.symbol_ids) | set(cluster))
        zones[host.index] = _make_zone(host.index, merged, adj, rev, idx)

    zones.sort(key=lambda z: (-z.size, z.index))
    for n, z in enumerate(zones):
        z.index = n
    return zones


def _make_zone(index: int, members: list[str],
               adj: dict[str, list[str]],
               rev: dict[str, list[str]],
               idx: Index) -> Zone:
    mset = set(members)
    dep = _depths(members, adj, rev)

    # Entries must lead somewhere inside the zone; a property with no in-zone
    # callers is just an isolated node, not a way into the code.
    entries = [m for m in members
               if not mset.intersection(rev.get(m, ()))
               and mset.intersection(adj.get(m, ()))]
    exits = [m for m in members if not mset.intersection(adj.get(m, ()))]

    entries.sort(key=lambda m: (-len(adj.get(m, ())), -dep.get(m, 0), m))
    exits.sort(key=lambda m: (dep.get(m, 0), m))
    return Zone(index, sorted(members), entries, exits)


def levels_of(idx: Index, zone: Zone) -> list[Level]:
    """Depth levels inside a zone, entry-side first."""
    mset = set(zone.symbol_ids)
    adj: dict[str, list[str]] = {m: [] for m in zone.symbol_ids}
    rev: dict[str, list[str]] = {m: [] for m in zone.symbol_ids}
    for e in idx.edges:
        if e.caller_id in mset and e.callee_id in mset:
            adj[e.caller_id].append(e.callee_id)
            rev[e.callee_id].append(e.caller_id)

    dep = _depths(zone.symbol_ids, adj, rev)
    buckets: dict[int, list[str]] = {}
    for sid in zone.symbol_ids:
        buckets.setdefault(dep[sid], []).append(sid)

    out: list[Level] = []
    for d in sorted(buckets):
        members = sorted(buckets[d])
        m = set(members)
        out.append(Level(
            depth=d,
            symbol_ids=members,
            outbound=[e for e in idx.edges if e.caller_id in m and e.callee_id not in m],
            inbound=[e for e in idx.edges if e.callee_id in m and e.caller_id not in m],
        ))
    return out
