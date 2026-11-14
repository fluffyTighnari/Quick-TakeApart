"""Freeze a logic flow so it can be replayed instead of regenerated.

Why this exists: the model's output drifts. Asking the same question twice yields
two different groupings, which makes a flow useless as a reference — you cannot
build a reading path on something that changes every time you look at it, and you
cannot point someone at it. Freezing turns a result into an artifact.

The cost of freezing is decay: a frozen flow names symbols as they were. When the
code moves, the artifact must say so rather than quietly render whatever still
happens to match. Staleness is therefore per-symbol, not per-revision — a flow is
still mostly usable when three of its forty symbols moved.

Storage is one file per flow, so a single flow can be copied or shared without
carrying the whole collection, and concurrent writes cannot corrupt one another.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import re
import secrets
from datetime import datetime, timezone

from .model import Index

STORE_DIR = ".qta/flows"
FORMAT_VERSION = 1

# per-symbol staleness
OK = "ok"
MOVED = "moved"        # still there, line numbers shifted
CHANGED = "changed"    # signature differs — the function itself probably changed
MISSING = "missing"    # no longer in the index at all


class StoreError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class Fingerprint:
    line: int
    end_line: int
    signature: str


@dataclasses.dataclass
class SavedFlow:
    id: str
    name: str
    query: str
    title: str
    summary: str
    views: list[dict]
    created_at: str
    revision: str
    fingerprints: dict[str, Fingerprint]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "query": self.query,
            "title": self.title,
            "summary": self.summary,
            "views": self.views,
            "createdAt": self.created_at,
            "revision": self.revision,
            "fingerprints": {
                sid: {"line": f.line, "endLine": f.end_line, "signature": f.signature}
                for sid, f in self.fingerprints.items()
            },
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "SavedFlow":
        fps = {
            sid: Fingerprint(int(v.get("line") or 0), int(v.get("endLine") or 0),
                             str(v.get("signature") or ""))
            for sid, v in (raw.get("fingerprints") or {}).items()
        }
        return cls(
            id=str(raw["id"]),
            name=str(raw.get("name") or ""),
            query=str(raw.get("query") or ""),
            title=str(raw.get("title") or ""),
            summary=str(raw.get("summary") or ""),
            views=list(raw.get("views") or []),
            created_at=str(raw.get("createdAt") or ""),
            revision=str(raw.get("revision") or ""),
            fingerprints=fps,
        )


@dataclasses.dataclass
class Staleness:
    """How far a frozen flow has drifted from the code as it is now."""

    fresh: bool
    missing: list[str]
    moved: list[str]
    changed: list[str]
    detail: dict[str, str]   # symbol id -> OK / MOVED / CHANGED / MISSING

    @property
    def usable(self) -> bool:
        return len(self.missing) < len(self.detail)

    def summary(self) -> str:
        if self.fresh:
            return "与当前代码一致"
        bits = []
        if self.missing:
            bits.append(f"{len(self.missing)} 个符号已不存在")
        if self.changed:
            bits.append(f"{len(self.changed)} 个签名已变")
        if self.moved:
            bits.append(f"{len(self.moved)} 个位置已移动")
        return "、".join(bits) if bits else "与当前代码一致"

    def to_dict(self) -> dict:
        return {
            "fresh": self.fresh,
            "usable": self.usable,
            "missing": self.missing,
            "moved": self.moved,
            "changed": self.changed,
            "detail": self.detail,
            "summary": self.summary(),
        }


def _flows_dir(root: pathlib.Path) -> pathlib.Path:
    return root / STORE_DIR


def _slug(text: str, limit: int = 24) -> str:
    cleaned = re.sub(r"[^\w一-鿿-]+", "-", text, flags=re.UNICODE).strip("-")
    return cleaned[:limit] or "flow"


def _new_id(name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{_slug(name, 16)}-{secrets.token_hex(2)}"


def fingerprint_of(idx: Index, symbol_ids: list[str]) -> dict[str, Fingerprint]:
    out: dict[str, Fingerprint] = {}
    for sid in symbol_ids:
        sym = idx.symbols.get(sid)
        if sym is None:
            continue
        out[sid] = Fingerprint(
            line=sym.body_range.start_line + 1,
            end_line=sym.body_range.end_line + 1,
            signature=sym.signature,
        )
    return out


def save_flow(root: pathlib.Path, idx: Index, payload: dict, *,
              name: str | None = None,
              symbol_ids: list[str] | None = None) -> SavedFlow:
    """Persist a flow. `symbol_ids` lets the caller say which symbols are in scope;
    by default they are read out of the views."""
    views = payload.get("views") or []
    if not views:
        raise StoreError("a flow with no views is not worth freezing")

    ids = symbol_ids if symbol_ids is not None else sorted({
        n.get("symbolId")
        for v in views for n in (v.get("nodes") or [])
        if n.get("symbolId")
    })
    ids = [i for i in ids if i in idx.symbols]
    if not ids:
        raise StoreError("none of the flow's symbols exist in the index")

    # A flow belongs to the project whose symbols it names. Saving one against
    # the wrong project produces an artifact that can never be replayed.
    named = {
        n.get("symbolId")
        for v in views for n in (v.get("nodes") or [])
        if n.get("symbolId")
    }
    unknown = sorted(named - set(idx.symbols))
    if unknown:
        raise StoreError(
            f"flow references {len(unknown)} symbol(s) not in this project, "
            f"e.g. {unknown[0]}"
        )

    title = str(payload.get("title") or payload.get("query") or "未命名")
    flow = SavedFlow(
        id=_new_id(name or title),
        name=(name or title).strip(),
        query=str(payload.get("query") or ""),
        title=title,
        summary=str(payload.get("summary") or ""),
        views=views,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        revision=idx.revision,
        fingerprints=fingerprint_of(idx, ids),
    )

    directory = _flows_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{flow.id}.json"

    # write-then-rename so a crash cannot leave a half-written flow behind
    tmp = target.with_suffix(".json.tmp")
    body = {"version": FORMAT_VERSION, "flow": flow.to_dict()}
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return flow


def load_flow(root: pathlib.Path, flow_id: str) -> SavedFlow | None:
    # the id arrives from the network; refuse anything that is not a plain name
    if not flow_id or "/" in flow_id or "\\" in flow_id or ".." in flow_id:
        return None
    path = _flows_dir(root) / f"{flow_id}.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    flow = raw.get("flow") if isinstance(raw, dict) else None
    if not isinstance(flow, dict):
        return None
    try:
        return SavedFlow.from_dict(flow)
    except (KeyError, TypeError, ValueError):
        return None


def list_flows(root: pathlib.Path) -> list[SavedFlow]:
    directory = _flows_dir(root)
    if not directory.is_dir():
        return []
    out: list[SavedFlow] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        flow = load_flow(root, path.stem)
        if flow is not None:
            out.append(flow)
    return out


def delete_flow(root: pathlib.Path, flow_id: str) -> bool:
    if not flow_id or "/" in flow_id or "\\" in flow_id or ".." in flow_id:
        return False
    path = _flows_dir(root) / f"{flow_id}.json"
    if not path.is_file():
        return False
    path.unlink()
    return True


def rename_flow(root: pathlib.Path, flow_id: str, name: str) -> SavedFlow | None:
    flow = load_flow(root, flow_id)
    if flow is None or not name.strip():
        return None
    flow.name = name.strip()[:120]
    target = _flows_dir(root) / f"{flow_id}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"version": FORMAT_VERSION, "flow": flow.to_dict()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    tmp.replace(target)
    return flow


def staleness_of(revision: str, fingerprints: dict[str, Fingerprint],
                 idx: Index) -> Staleness:
    """Compare a frozen set of symbol fingerprints against the current index.

    The revision check is a fast path only. Two revisions that differ say nothing
    about whether *these* symbols are still valid, so the per-symbol comparison
    always runs when they differ.
    """
    detail: dict[str, str] = {}
    missing: list[str] = []
    moved: list[str] = []
    changed: list[str] = []

    if revision and revision == idx.revision and fingerprints:
        for sid in fingerprints:
            detail[sid] = OK
        return Staleness(True, [], [], [], detail)

    for sid, fp in fingerprints.items():
        sym = idx.symbols.get(sid)
        if sym is None:
            detail[sid] = MISSING
            missing.append(sid)
            continue
        now_line = sym.body_range.start_line + 1
        now_sig = sym.signature
        if now_sig != fp.signature:
            detail[sid] = CHANGED
            changed.append(sid)
        elif now_line != fp.line:
            detail[sid] = MOVED
            moved.append(sid)
        else:
            detail[sid] = OK

    return Staleness(False, sorted(missing), sorted(moved), sorted(changed), detail)


def check_staleness(flow: SavedFlow, idx: Index) -> Staleness:
    return staleness_of(flow.revision, flow.fingerprints, idx)


def flows_with_staleness(root: pathlib.Path, idx: Index) -> list[dict]:
    out = []
    for flow in list_flows(root):
        record = flow.to_dict()
        # don't ship fingerprints to the client; the verdict is what it needs
        record.pop("fingerprints", None)
        record["staleness"] = check_staleness(flow, idx).to_dict()
        out.append(record)
    return out
