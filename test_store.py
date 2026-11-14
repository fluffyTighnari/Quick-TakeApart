"""The store is what makes a flow a reference instead of a rendering.

Two properties decide whether the whole three-stage structure can stand:

  1. a frozen flow replays identically — no model call, no drift
  2. a frozen flow reports its own decay instead of silently rendering stale code
"""

from __future__ import annotations

import asyncio
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine import build_index
from engine.model import Range, Symbol
from engine.store import (CHANGED, MISSING, MOVED, OK, StoreError,
                          check_staleness, delete_flow, list_flows, load_flow,
                          rename_flow, save_flow)

PYRIGHT = HERE / "node_modules" / "pyright" / "langserver.index.js"
WEBAPP = HERE / "spike" / "webapp"

results: list[bool] = []


def check(label: str, passed: bool) -> bool:
    results.append(passed)
    print(f"  {'ok  ' if passed else 'FAIL'} {label}")
    return passed


def sample_payload(ids: list[str]) -> dict:
    return {
        "query": "追踪 http 请求",
        "title": "HTTP 请求链路",
        "summary": "从 dispatch 到 repo。",
        "views": [{
            "kind": "path",
            "title": "主链路",
            "rationale": "一条自上而下的调用链",
            "nodes": [{"symbolId": s, "depth": i} for i, s in enumerate(ids)],
        }],
    }


def run_store_tests(idx, root: pathlib.Path) -> None:
    real = sorted(idx.symbols)
    chain = [s for s in real if "users_api" in s or "users_service" in s][:3]
    if len(chain) < 2:
        chain = real[:3]

    print("\n=== save and replay ===")
    flow = save_flow(root, idx, sample_payload(chain), name="HTTP 请求链路")
    check("flow got an id", bool(flow.id))
    check("fingerprints recorded for every symbol",
          set(flow.fingerprints) == set(chain))

    again = load_flow(root, flow.id)
    check("loads back", again is not None)
    check("same id", again.id == flow.id)
    check("same nodes", [n["symbolId"] for n in again.views[0]["nodes"]] == chain)
    check("same revision", again.revision == idx.revision)

    print("\n=== a fresh flow reports itself fresh ===")
    st = check_staleness(again, idx)
    check("marked fresh", st.fresh)
    check("everything OK", all(v == OK for v in st.detail.values()))

    print("\n=== save refuses junk ===")
    for label, payload in [
        ("no views", {"views": []}),
        ("no real symbols", {"views": [{"kind": "path", "title": "x",
                                        "nodes": [{"symbolId": "ghost::fn"}]}]}),
    ]:
        try:
            save_flow(root, idx, payload)
            check(f"rejected {label}", False)
        except StoreError:
            check(f"rejected {label}", True)

    print("\n=== a flow cannot be saved into the wrong project ===")
    # this is what happens when the UI holds a plan from project A and the user
    # switches to project B before saving: the artifact would name symbols that
    # do not exist here, and could never be replayed.
    foreign = dict(sample_payload(chain))
    foreign["views"] = [{
        "kind": "path", "title": "x",
        "nodes": [{"symbolId": chain[0]},
                  {"symbolId": "some/other/project.py::handler"}],
    }]
    try:
        save_flow(root, idx, foreign)
        check("rejected a half-foreign flow", False)
    except StoreError as exc:
        check("rejected a half-foreign flow", "not in this project" in str(exc))

    print("\n=== listing and lookup ===")
    second = save_flow(root, idx, sample_payload(chain[:1]), name="第二条")
    listed = list_flows(root)
    check(f"lists both ({len(listed)})", len(listed) >= 2)
    check("path traversal refused", load_flow(root, "../../etc/passwd") is None)
    check("unknown id returns None", load_flow(root, "nope") is None)

    print("\n=== rename ===")
    renamed = rename_flow(root, second.id, "改名后的流")
    check("name changed", renamed is not None and renamed.name == "改名后的流")
    check("replay still intact",
          load_flow(root, second.id).views[0]["nodes"][0]["symbolId"] == chain[0])

    print("\n=== delete ===")
    check("deleted", delete_flow(root, second.id))
    check("gone", load_flow(root, second.id) is None)
    check("delete is not repeatable", not delete_flow(root, second.id))

    return flow


def run_decay_tests(idx, root: pathlib.Path, flow) -> None:
    """Simulate the three ways a frozen flow can rot."""
    print("\n=== decay: symbol moved ===")
    sid = sorted(flow.fingerprints)[0]
    shifted = _clone_index(idx)
    sym = shifted.symbols[sid]
    shifted.symbols[sid] = Symbol(
        id=sym.id, name=sym.name, qualname=sym.qualname, relpath=sym.relpath,
        kind=sym.kind, range=sym.range, body_range=sym.body_range,
        signature=sym.signature,
    )
    # move it down three lines
    moved_body = Range(sym.body_range.start_line + 3, 0,
                       sym.body_range.end_line + 3, 0)
    shifted.symbols[sid] = Symbol(
        id=sym.id, name=sym.name, qualname=sym.qualname, relpath=sym.relpath,
        kind=sym.kind, range=sym.range, body_range=moved_body,
        signature=sym.signature,
    )
    st = check_staleness(flow, shifted)
    check("not fresh", not st.fresh)
    check("reported as moved", st.detail.get(sid) == MOVED)
    check("still usable", st.usable)

    print("\n=== decay: signature changed ===")
    edited = _clone_index(idx)
    sym = edited.symbols[sid]
    edited.symbols[sid] = Symbol(
        id=sym.id, name=sym.name, qualname=sym.qualname, relpath=sym.relpath,
        kind=sym.kind, range=sym.range, body_range=sym.body_range,
        signature="def totally_different(a, b, c):",
    )
    st = check_staleness(flow, edited)
    check("reported as changed", st.detail.get(sid) == CHANGED)

    print("\n=== decay: symbol gone ===")
    gutted = _clone_index(idx)
    for fpid in flow.fingerprints:
        gutted.symbols.pop(fpid, None)
    st = check_staleness(flow, gutted)
    check("reported missing", all(v == MISSING for v in st.detail.values()))
    check("not usable when nothing survives", not st.usable)
    check("summary mentions it", "已不存在" in st.summary())

    print("\n=== partial loss stays usable ===")
    partial = _clone_index(idx)
    victim = sorted(flow.fingerprints)[0]
    partial.symbols.pop(victim, None)
    st = check_staleness(flow, partial)
    check("still usable", st.usable)
    check("names the casualty", victim in st.missing)


def _clone_index(idx):
    """A shallow copy deep enough to mutate symbols without touching the original."""
    clone = type(idx)(root=idx.root, revision=idx.revision + "-edited")
    clone.symbols = dict(idx.symbols)
    clone.edges = list(idx.edges)
    clone.unresolved_calls = list(idx.unresolved_calls)
    return clone


async def main() -> int:
    idx = await build_index(WEBAPP, PYRIGHT, max_call_hierarchy=60)
    print(f"fixture: {len(idx.symbols)} symbols, {len(idx.edges)} edges")

    sandbox = pathlib.Path(tempfile.mkdtemp(prefix="qta-store-"))
    try:
        flow = run_store_tests(idx, sandbox)
        run_decay_tests(idx, sandbox, flow)
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)

    passed = sum(results)
    print(f"\nRESULT: {'PASS' if passed == len(results) else 'FAIL'} ({passed}/{len(results)})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
