"""Persistent learning tracks and conversation threads.

A workspace is a directory. Inside it, a person can run several learning
*Tracks* (e.g. "overall understanding", "fix this bug", "only auth"). Each track
owns a plan and a plan-design conversation. Slices are workspace-global: a track
can reference any slice, and the library view shows all of them.

Threads are deliberately not one shared chat. The plan-design conversation and
the slice side-panel are different memories; mixing them makes the plan drift and
the side-panel lose its anchor. The store keeps that separation structural rather
than trusting the UI to remember it.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import secrets
from datetime import datetime, timezone

TRACK_DIR = ".qta/tracks"
THREAD_DIR = ".qta/threads"
FORMAT_VERSION = 1


class SessionError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(text: str, limit: int = 24) -> str:
    cleaned = re.sub(r"[^\w一-鿿-]+", "-", text, flags=re.UNICODE).strip("-")
    return cleaned[:limit] or "item"


def _new_id(prefix: str, name: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{_slug(name, 16)}-{secrets.token_hex(2)}"


def _safe_id(value: str) -> bool:
    return bool(value) and not any(c in value for c in ("/", "\\", ".."))


def _dir(root: pathlib.Path, rel: str) -> pathlib.Path:
    return root / rel


def _read(root: pathlib.Path, rel: str, key: str) -> dict | None:
    path = _dir(root, rel)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = raw.get(key) if isinstance(raw, dict) else None
    return value if isinstance(value, dict) else None


def _write(root: pathlib.Path, rel: str, key: str, value: dict) -> None:
    path = _dir(root, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"version": FORMAT_VERSION, key: value},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


@dataclasses.dataclass
class Track:
    id: str
    name: str
    intent: str = ""
    depth: str = ""                 # 粒度契约: 粗看 / 结构 / 逐函数 / 只看某模块
    plan_id: str = ""
    plan_thread_id: str = ""
    pinned_slice_ids: list[str] = dataclasses.field(default_factory=list)
    stage: str = "architecture"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "intent": self.intent,
            "depth": self.depth, "planId": self.plan_id,
            "planThreadId": self.plan_thread_id,
            "pinnedSliceIds": list(self.pinned_slice_ids),
            "stage": self.stage,
            "createdAt": self.created_at, "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Track":
        return cls(
            id=str(raw.get("id") or ""),
            name=str(raw.get("name") or "未命名轨道"),
            intent=str(raw.get("intent") or ""),
            depth=str(raw.get("depth") or ""),
            plan_id=str(raw.get("planId") or ""),
            plan_thread_id=str(raw.get("planThreadId") or ""),
            pinned_slice_ids=[str(x) for x in (raw.get("pinnedSliceIds") or [])],
            stage=str(raw.get("stage") or "architecture"),
            created_at=str(raw.get("createdAt") or ""),
            updated_at=str(raw.get("updatedAt") or ""),
        )


@dataclasses.dataclass
class Thread:
    id: str
    scope: str                     # plan / slice / symbol / range / file
    track_id: str = ""
    slice_id: str = ""
    anchor: dict = dataclasses.field(default_factory=dict)
    title: str = ""
    messages: list[dict] = dataclasses.field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "scope": self.scope, "trackId": self.track_id,
            "sliceId": self.slice_id, "anchor": self.anchor,
            "title": self.title, "messages": self.messages,
            "createdAt": self.created_at, "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Thread":
        return cls(
            id=str(raw.get("id") or ""),
            scope=str(raw.get("scope") or "slice"),
            track_id=str(raw.get("trackId") or ""),
            slice_id=str(raw.get("sliceId") or ""),
            anchor=dict(raw.get("anchor") or {}),
            title=str(raw.get("title") or ""),
            messages=list(raw.get("messages") or []),
            created_at=str(raw.get("createdAt") or ""),
            updated_at=str(raw.get("updatedAt") or ""),
        )


# --- tracks -------------------------------------------------------------


def create_track(root: pathlib.Path, name: str, intent: str = "",
                 depth: str = "") -> Track:
    track_id = _new_id("track", name or "新轨道")
    now = _now()
    track = Track(
        id=track_id, name=(name or "新轨道").strip()[:80],
        intent=intent.strip(), depth=depth.strip(),
        created_at=now, updated_at=now,
    )
    # every track gets its own plan-design memory from the start
    thread = create_thread(root, "plan", track_id=track.id, title=f"{track.name} · 计划设计")
    track.plan_thread_id = thread.id
    _write(root, f"{TRACK_DIR}/{track.id}.json", "track", track.to_dict())
    return track


def load_track(root: pathlib.Path, track_id: str) -> Track | None:
    if not _safe_id(track_id):
        return None
    raw = _read(root, f"{TRACK_DIR}/{track_id}.json", "track")
    return Track.from_dict(raw) if raw else None


def list_tracks(root: pathlib.Path) -> list[Track]:
    directory = _dir(root, TRACK_DIR)
    if not directory.is_dir():
        return []
    out: list[Track] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        track = load_track(root, path.stem)
        if track is not None:
            out.append(track)
    return out


def update_track(root: pathlib.Path, track_id: str, **fields) -> Track | None:
    track = load_track(root, track_id)
    if track is None:
        return None
    allowed = {"name", "intent", "depth", "plan_id", "plan_thread_id",
               "pinned_slice_ids", "stage"}
    for key, value in fields.items():
        if key in allowed:
            setattr(track, key, value)
    track.updated_at = _now()
    _write(root, f"{TRACK_DIR}/{track.id}.json", "track", track.to_dict())
    return track


def delete_track(root: pathlib.Path, track_id: str) -> bool:
    track = load_track(root, track_id)
    if track is None:
        return False
    # The plan is owned by the track; slices are global and deliberately survive.
    if track.plan_id and _safe_id(track.plan_id):
        plan_path = root / ".qta" / "plans" / f"{track.plan_id}.json"
        if plan_path.is_file():
            plan_path.unlink()
    for thread in list_threads(root):
        if thread.track_id == track_id:
            delete_thread(root, thread.id)
    path = _dir(root, f"{TRACK_DIR}/{track_id}.json")
    if path.is_file():
        path.unlink()
    return True


# --- threads ------------------------------------------------------------


def create_thread(root: pathlib.Path, scope: str, *, track_id: str = "",
                  slice_id: str = "", anchor: dict | None = None,
                  title: str = "") -> Thread:
    now = _now()
    thread = Thread(
        id=_new_id("thread", title or scope),
        scope=scope, track_id=track_id, slice_id=slice_id,
        anchor=dict(anchor or {}), title=title.strip() or f"{scope} 对话",
        created_at=now, updated_at=now,
    )
    _write(root, f"{THREAD_DIR}/{thread.id}.json", "thread", thread.to_dict())
    return thread


def load_thread(root: pathlib.Path, thread_id: str) -> Thread | None:
    if not _safe_id(thread_id):
        return None
    raw = _read(root, f"{THREAD_DIR}/{thread_id}.json", "thread")
    return Thread.from_dict(raw) if raw else None


def list_threads(root: pathlib.Path, *, track_id: str = "",
                 slice_id: str = "") -> list[Thread]:
    directory = _dir(root, THREAD_DIR)
    if not directory.is_dir():
        return []
    out: list[Thread] = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        thread = load_thread(root, path.stem)
        if thread is None:
            continue
        if track_id and thread.track_id != track_id:
            continue
        if slice_id and thread.slice_id != slice_id:
            continue
        out.append(thread)
    return out


def find_thread(root: pathlib.Path, *, scope: str, track_id: str = "",
                slice_id: str = "") -> Thread | None:
    for thread in list_threads(root, track_id=track_id, slice_id=slice_id):
        if thread.scope == scope:
            return thread
    return None


def ensure_plan_thread(root: pathlib.Path, track: Track) -> Thread:
    if track.plan_thread_id:
        thread = load_thread(root, track.plan_thread_id)
        if thread is not None:
            return thread
    thread = find_thread(root, scope="plan", track_id=track.id)
    if thread is None:
        thread = create_thread(root, "plan", track_id=track.id,
                               title=f"{track.name} · 计划设计")
    update_track(root, track.id, plan_thread_id=thread.id)
    track.plan_thread_id = thread.id
    return thread


def ensure_slice_thread(root: pathlib.Path, track_id: str, slice_id: str,
                        title: str = "") -> Thread:
    thread = find_thread(root, scope="slice", track_id=track_id, slice_id=slice_id)
    if thread is None:
        thread = create_thread(root, "slice", track_id=track_id,
                               slice_id=slice_id,
                               title=title or "切片问答")
    return thread


def append_message(root: pathlib.Path, thread_id: str, role: str,
                   content: str, *, citations: list | None = None,
                   turn: dict | None = None, context: dict | None = None) -> Thread | None:
    thread = load_thread(root, thread_id)
    if thread is None:
        return None
    message = {
        "id": _new_id("msg", role),
        "role": role,
        "content": content,
        "citations": citations or [],
        "turn": turn or {},
        "context": context or {},
        "createdAt": _now(),
    }
    thread.messages.append(message)
    thread.updated_at = message["createdAt"]
    _write(root, f"{THREAD_DIR}/{thread.id}.json", "thread", thread.to_dict())
    return thread


def delete_thread(root: pathlib.Path, thread_id: str) -> bool:
    if not _safe_id(thread_id):
        return False
    path = _dir(root, f"{THREAD_DIR}/{thread_id}.json")
    if not path.is_file():
        return False
    path.unlink()
    return True


def ensure_default_track(root: pathlib.Path) -> Track:
    """A workspace always has at least one track, so the shell has somewhere to land."""
    tracks = list_tracks(root)
    if tracks:
        return tracks[0]
    return create_track(root, "整体了解", "先建立整体位置感，再决定深入哪里。", "粗看")
