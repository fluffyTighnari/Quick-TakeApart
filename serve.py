"""Local HTTP server: index a Python project and serve the reading observatory.

The new API is organized around a directory-level workspace:

    GET  /api/index                 base payload (symbols, edges, files)
    GET  /api/workspace             tracks / slices
    GET  /api/track?id=...          one track with plan, threads, slices
    GET  /api/source?path=...       file text, only for indexed files
    POST /api/open                  {root} -> index a different project
    POST /api/skeletons/generate    {trackId,focus}
    POST /api/slices/generate       {trackId,query,strategies,scope}
    POST /api/plan/chat             {trackId,message} -> changed plan
    POST /api/threads/message       {threadId,message,context}
    POST /api/trace                 {file,line,char,kind}
    GET/POST /api/settings          local model endpoint/key/model

Switching projects re-indexes in place; only one project is held at a time,
but all artifacts live on disk under <project>/.qta/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import socket
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from engine import build_index
from engine.claims import claims_from_edges, verify
from engine.plan import build_inventory, views_or_fallback
from engine.store import (StoreError, check_staleness, delete_flow,
                          flows_with_staleness, load_flow, rename_flow,
                          save_flow)
from engine.plans import (PlanStoreError, SavedPlan, delete_plan, list_plans,
                          load_plan, plan_health, plans_with_health,
                          save_plan, topological_order)
from engine.plans_chat import (ChatError, FlowRequest, apply_turn,
                               bind_generated_flow, request_turn)
from engine.sessions import (SessionError, append_message, create_thread,
                             create_track, delete_track, ensure_default_track,
                             ensure_plan_thread, ensure_slice_thread,
                             list_threads, load_thread, load_track,
                             list_tracks, update_track)
from engine.side_chat import answer as side_answer
from engine.slices import (SliceError, delete_slice, generate_slice, list_slices,
                           load_slice, regenerate_slice, rename_slice,
                           slice_record, slices_with_staleness)
from engine.trace import TraceService
from engine.skeleton import (SkeletonError, delete_skeleton, explain_node,
                             generate_skeleton, list_skeletons, load_skeleton,
                             skeleton_record, skeletons_with_staleness)
from engine.settings import (SettingsError, fetch_models, public_settings,
                             resolve_credentials, save_settings)
from engine.paths import PathError, browse_directories, normalize_path, root_locations
from engine.picker import PickerError, pick_folder
from engine.recent import load_recent, remember

WEB = pathlib.Path(__file__).parent / "web"
DIST = WEB / "dist"
PYRIGHT = pathlib.Path(__file__).parent / "node_modules" / "pyright" / "langserver.index.js"

SKIP_DIRS = ("spike/", "node_modules/", ".venv/", "venv/", "build/", "dist/")
SCRATCH_FILES = ("test_", "verify_", "probe", "conftest")

DEFAULT_QUERIES = [
    "帮我追踪一下所有 http 请求路径",
    "帮我追踪一下 db 调用",
    "log 在整个项目中的位置",
    "这个项目整体是怎么组织的",
]

STATE: dict = {
    "idx": None,
    "base": None,
    "inventory": "",
    "plan_cache": {},
    "recent": load_recent(),
    "trace": None,
}


def _rel(sid: str) -> str:
    return sid.split("::", 1)[0]


def _short(sid: str) -> str:
    rel, _, qual = sid.partition("::")
    return f"{rel.rsplit('/', 1)[-1]}.{qual}"


def _is_scratch(rel: str) -> bool:
    if rel.startswith(SKIP_DIRS):
        return True
    name = rel.rsplit("/", 1)[-1]
    return name.startswith(SCRATCH_FILES)


def build_base_payload(idx) -> dict:
    symbols = {
        sid: {
            "id": sid,
            "name": s.name,
            "qualname": s.qualname,
            "file": s.relpath,
            "kind": s.kind,
            "line": s.body_range.start_line + 1,
            "endLine": s.body_range.end_line + 1,
            "signature": s.signature,
        }
        for sid, s in idx.symbols.items()
        if not _is_scratch(s.relpath)
    }

    edges = [
        {"from": e.caller_id, "to": e.callee_id,
         "line": e.site.start_line + 1, "kind": e.kind}
        for e in idx.edges
        if e.caller_id in symbols and e.callee_id in symbols
    ]

    claims: dict[str, list[dict]] = {}
    for sid in symbols:
        verified = verify(claims_from_edges(idx, [sid]), idx)
        if not verified.accepted:
            continue
        claims[sid] = [
            {"kind": c.kind, "subject": c.subject, "object": c.object,
             "objectLabel": (_short(c.object) if c.object in symbols else c.object),
             "line": c.anchor_line, "file": c.anchor_file}
            for c in verified.accepted
        ]

    files = sorted({s.relpath for s in idx.symbols.values() if s.id in symbols})
    by_file: dict[str, list[str]] = {f: [] for f in files}
    for sid, sym in symbols.items():
        by_file[sym["file"]].append(sid)
    for f in by_file:
        by_file[f].sort(key=lambda sid: symbols[sid]["line"])

    return {
        "root": idx.root,
        "name": pathlib.PurePath(idx.root).name,
        "revision": idx.revision,
        "stats": {
            "symbols": len(symbols),
            "callables": sum(1 for s in idx.symbols.values()
                             if s.id in symbols and s.is_callable),
            "edges": len(edges),
            "crossFile": sum(1 for e in edges if e["kind"] == "cross"),
            "unresolved": sum(1 for c, _, _ in idx.unresolved_calls if c in symbols),
            "files": len(files),
        },
        "symbols": symbols,
        "edges": edges,
        "claims": claims,
        "files": files,
        "byFile": by_file,
        "unresolved": [
            {"caller": c, "name": n, "file": _rel(c), "line": r.start_line + 1}
            for c, n, r in idx.unresolved_calls
            if c in symbols
        ],
        "queries": DEFAULT_QUERIES,
    }


def index_project(root: pathlib.Path, max_symbols: int) -> None:
    root = root.resolve()
    old_trace = STATE.get("trace")
    if old_trace is not None:
        try:
            old_trace.stop()
        except Exception:
            pass
    idx = asyncio.run(build_index(root, PYRIGHT, max_call_hierarchy=max_symbols))
    STATE["idx"] = idx
    STATE["base"] = build_base_payload(idx)
    STATE["inventory"] = build_inventory(idx)
    # Stage one chooses components and symbols, but never emits segment ranges.
    # Dropping line ranges here is pure savings; slices still get a focused
    # inventory with ranges via build_scoped_inventory.
    STATE["skeleton_inventory"] = build_inventory(
        idx, symbol_budget=900, compact=True)
    STATE["plan_cache"] = {}
    STATE["trace"] = TraceService(root, PYRIGHT, idx)
    ensure_default_track(root)

    STATE["recent"] = remember(str(root))


def _flow_record(flow, idx) -> dict:
    record = flow.to_dict()
    record.pop("fingerprints", None)
    record["staleness"] = check_staleness(flow, idx).to_dict()
    return record


def _plan_record(root: pathlib.Path, plan, idx) -> dict:
    """A plan with its flows inlined, so a step renders without a second fetch."""
    from engine.store import list_flows

    flows = {f.id: f for f in list_flows(root)}
    record = plan.to_dict()
    record["health"] = plan_health(plan, flows, idx).to_dict()
    record["order"] = topological_order(plan)

    inlined = {}
    for item in plan.items:
        flow = flows.get(item.flow_id)
        if flow is None:
            continue
        rec = flow.to_dict()
        rec.pop("fingerprints", None)
        rec["staleness"] = check_staleness(flow, idx).to_dict()
        inlined[item.flow_id] = rec
    record["flows"] = inlined
    return record


def _slices_dict(root: pathlib.Path):
    return {s.id: s for s in list_slices(root)}


def _plan_record_slices(root: pathlib.Path, plan, idx) -> dict:
    """A plan record whose steps reference slices, not legacy flows."""
    slices = _slices_dict(root)
    record = plan.to_dict()
    record["health"] = plan_health(plan, slices, idx).to_dict()
    record["order"] = topological_order(plan)
    inlined = {}
    for item in plan.items:
        slice_ = slices.get(item.flow_id)
        if slice_ is not None:
            inlined[item.flow_id] = slice_record(slice_, idx)
    record["slices"] = inlined
    record["flows"] = inlined  # old renderers keep working
    return record


def _track_summary(root: pathlib.Path, track, idx) -> dict:
    plan = load_plan(root, track.plan_id) if track.plan_id else None
    slices = [s for s in list_slices(root) if s.track_id == track.id]
    health = plan_health(plan, _slices_dict(root), idx).to_dict() if plan else None
    record = track.to_dict()
    if plan and plan.intent:
        record["intent"] = plan.intent
    record["plan"] = {
        "id": plan.id, "name": plan.name, "intent": plan.intent,
        "steps": len(plan.items), "health": health,
    } if plan else None
    record["sliceCount"] = len(slices)
    record["threadCount"] = len(list_threads(root, track_id=track.id))
    return record


def _track_record(root: pathlib.Path, track, idx) -> dict:
    plan = load_plan(root, track.plan_id) if track.plan_id else None
    if plan and plan.intent and plan.intent != track.intent:
        updated = update_track(root, track.id, intent=plan.intent)
        if updated is not None:
            track = updated
    plan_thread = load_thread(root, track.plan_thread_id) if track.plan_thread_id else None
    threads = [t.to_dict() for t in list_threads(root, track_id=track.id)]
    slices = [slice_record(s, idx) for s in list_slices(root) if s.track_id == track.id]
    skeletons = [skeleton_record(s, idx) for s in list_skeletons(root)
                 if s.track_id == track.id]
    return {
        "track": track.to_dict(),
        "plan": _plan_record_slices(root, plan, idx) if plan else None,
        "planThread": plan_thread.to_dict() if plan_thread else None,
        "threads": threads,
        "slices": slices,
        "skeletons": skeletons,
    }


def _workspace_record(root: pathlib.Path, idx) -> dict:
    base = STATE["base"]
    tracks = list_tracks(root)
    return {
        "root": str(root),
        "name": pathlib.PurePath(root).name,
        "stats": base["stats"] if base else {},
        "tracks": [_track_summary(root, t, idx) for t in tracks],
        "slices": slices_with_staleness(root, idx),
        "recent": STATE["recent"],
        "queries": DEFAULT_QUERIES,
    }


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Threading server that does not print a traceback for browser disconnects.

    Keep-alive requests can be reset by the browser (tab close, refresh, kill),
    which surfaces as ConnectionResetError inside socketserver's worker. That is
    normal network lifecycle, not an application failure.
    """

    daemon_threads = True
    # SO_REUSEADDR on Windows can allow two processes to bind the same port,
    # which makes a new server appear to start while the old one keeps serving
    # requests. Use exclusive address binding on Windows instead.
    allow_reuse_address = os.name != "nt"

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                self.socket.setsockopt(
                    socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, body: bytes, ctype: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # keep-alive without no-store hands the browser a stale index
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        self._send(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    def _file(self, path: pathlib.Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".mjs": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
            ".map": "application/json; charset=utf-8",
        }.get(path.suffix, "text/plain; charset=utf-8")
        self._send(path.read_bytes(), ctype)

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        route = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if route in ("/", "/index.html"):
            built = DIST / "index.html"
            if not built.is_file():
                self._send(
                    ("<html><body style=\"font:14px/1.6 system-ui;padding:40px;"
                     "background:#f5f8f6;color:#17221f\">"
                     "<h2>前端还没有构建</h2>"
                     "<p>在项目根目录运行：</p>"
                     "<pre>cd web\nnpm install\nnpm run build</pre>"
                     "<p>然后刷新这个页面。</p></body></html>").encode("utf-8"),
                    "text/html; charset=utf-8")
                return
            self._file(built)
            return
        if route.startswith("/assets/"):
            candidate = (DIST / "assets" / route[len("/assets/"):]).resolve()
            if DIST.resolve() not in candidate.parents:
                self.send_error(403)
                return
            self._file(candidate)
            return
        if route.startswith("/static/"):
            candidate = (WEB / route[len("/static/"):]).resolve()
            if WEB.resolve() not in candidate.parents:
                self.send_error(403)
                return
            self._file(candidate)
            return
        if route in ("/api/health", "/api/version"):
            self._json({
                "ok": True,
                "version": "2.0",
                "build": "workspace-tracks-slices-trace",
                "features": [
                    "workspace", "browse", "pick-folder", "tracks",
                    "skeletons", "slices", "regenerate-slice",
                    "plan-chat", "threads", "trace", "settings",
                ],
                "root": STATE["base"]["root"] if STATE["base"] else None,
                "frontend": "dist",
            })
            return
        if route == "/api/index":
            if STATE["base"] is None:
                self._json({"error": "no project open"}, 503)
                return
            self._json(STATE["base"])
            return
        if route == "/api/flows":
            root = self._project_root()
            if root is None:
                self._json({"error": "no project open"}, 503)
                return
            self._json({"flows": flows_with_staleness(root, STATE["idx"])})
            return
        if route == "/api/flow":
            root = self._project_root()
            if root is None:
                self._json({"error": "no project open"}, 503)
                return
            flow_id = (qs.get("id") or [""])[0]
            flow = load_flow(root, flow_id)
            if flow is None:
                self._json({"error": "flow not found"}, 404)
                return
            self._json({"flow": _flow_record(flow, STATE["idx"])})
            return
        if route == "/api/plans":
            root = self._project_root()
            if root is None:
                self._json({"error": "no project open"}, 503)
                return
            self._json({"plans": plans_with_health(root, STATE["idx"])})
            return
        if route == "/api/plans/get":
            root = self._project_root()
            if root is None:
                self._json({"error": "no project open"}, 503)
                return
            plan_id = (qs.get("id") or [""])[0]
            plan = load_plan(root, plan_id)
            if plan is None:
                self._json({"error": "plan not found"}, 404)
                return
            self._json({"plan": _plan_record(root, plan, STATE["idx"])})
            return
        if route == "/api/settings":
            self._json({"settings": public_settings()})
            return
        if route == "/api/workspace":
            if STATE["base"] is None:
                self._json({"error": "no project open"}, 503)
                return
            self._json(_workspace_record(pathlib.Path(STATE["base"]["root"]), STATE["idx"]))
            return
        if route == "/api/track":
            root = self._project_root()
            if root is None:
                self._json({"error": "no project open"}, 503)
                return
            track_id = (qs.get("id") or [""])[0]
            track = load_track(root, track_id) if track_id else None
            if track is None:
                tracks = list_tracks(root)
                track = tracks[0] if tracks else ensure_default_track(root)
            self._json(_track_record(root, track, STATE["idx"]))
            return
        if route == "/api/skeletons":
            root = self._project_root()
            if root is None:
                self._json({"error": "no project open"}, 503)
                return
            self._json({"skeletons": skeletons_with_staleness(root, STATE["idx"])})
            return
        if route == "/api/skeleton":
            root = self._project_root()
            if root is None:
                self._json({"error": "no project open"}, 503)
                return
            skeleton = load_skeleton(root, (qs.get("id") or [""])[0])
            if skeleton is None:
                self._json({"error": "skeleton not found"}, 404)
                return
            self._json({"skeleton": skeleton_record(skeleton, STATE["idx"])})
            return
        if route == "/api/slices":
            root = self._project_root()
            if root is None:
                self._json({"error": "no project open"}, 503)
                return
            self._json({"slices": slices_with_staleness(root, STATE["idx"])})
            return
        if route == "/api/slice":
            root = self._project_root()
            if root is None:
                self._json({"error": "no project open"}, 503)
                return
            slice_ = load_slice(root, (qs.get("id") or [""])[0])
            if slice_ is None:
                self._json({"error": "slice not found"}, 404)
                return
            thread = next(iter(list_threads(
                root, slice_id=slice_.id)), None)
            self._json({
                "slice": slice_record(slice_, STATE["idx"]),
                "thread": thread.to_dict() if thread else None,
            })
            return
        if route == "/api/thread":
            root = self._project_root()
            if root is None:
                self._json({"error": "no project open"}, 503)
                return
            thread = load_thread(root, (qs.get("id") or [""])[0])
            if thread is None:
                self._json({"error": "thread not found"}, 404)
                return
            self._json({"thread": thread.to_dict()})
            return
        if route == "/api/projects":
            self._json({
                "root": STATE["base"]["root"] if STATE["base"] else None,
                "recent": STATE["recent"],
                "defaultRoot": str(pathlib.Path.cwd()),
                "home": str(pathlib.Path.home()),
                "roots": root_locations(),
            })
            return
        if route == "/api/browse":
            raw_path = (qs.get("path") or [""])[0]
            try:
                self._json(browse_directories(raw_path or None))
            except PathError as exc:
                self._json({"error": str(exc)}, 400)
            return
        if route == "/api/source":
            if STATE["base"] is None:
                self._json({"error": "no project open"}, 503)
                return
            rel = (qs.get("path") or [""])[0]
            if rel not in STATE["base"]["files"]:
                self._json({"error": "not an indexed file"}, 404)
                return
            root = pathlib.Path(STATE["base"]["root"])
            target = (root / rel).resolve()
            if root.resolve() not in target.parents and target != root.resolve():
                self._json({"error": "outside project"}, 403)
                return
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._json({"error": "unreadable"}, 500)
                return
            self._json({"path": rel, "text": text})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        route = parsed.path

        if route == "/api/settings":
            self._handle_save_settings()
            return
        if route == "/api/settings/models":
            self._handle_list_models()
            return
        if route == "/api/skeletons/generate":
            self._handle_generate_skeleton()
            return
        if route == "/api/skeletons/node/explain":
            self._handle_explain_skeleton_node()
            return
        if route == "/api/skeletons/import-main":
            self._handle_import_skeleton_main()
            return
        if route == "/api/skeletons/import-node":
            self._handle_import_skeleton_node()
            return
        if route == "/api/skeletons/delete":
            self._handle_delete_skeleton()
            return
        if route == "/api/pick-folder":
            self._handle_pick_folder()
            return
        if route == "/api/tracks":
            self._handle_create_track()
            return
        if route == "/api/tracks/update":
            self._handle_update_track()
            return
        if route == "/api/tracks/delete":
            self._handle_delete_track()
            return
        if route == "/api/slices/generate":
            self._handle_generate_slice()
            return
        if route == "/api/slices/regenerate":
            self._handle_regenerate_slice()
            return
        if route == "/api/slices/delete":
            self._handle_delete_slice()
            return
        if route == "/api/slices/rename":
            self._handle_rename_slice()
            return
        if route == "/api/plan/chat":
            self._handle_track_plan_chat()
            return
        if route == "/api/plan/apply":
            self._handle_apply_plan()
            return
        if route == "/api/tracks/generate-bind":
            self._handle_generate_bind()
            return
        if route == "/api/threads":
            self._handle_create_thread()
            return
        if route == "/api/threads/message":
            self._handle_thread_message()
            return
        if route == "/api/trace":
            self._handle_trace()
            return
        if route == "/api/plan":
            self._handle_plan()
            return
        if route == "/api/open":
            self._handle_open()
            return
        if route == "/api/flows":
            self._handle_save_flow()
            return
        if route == "/api/flows/rename":
            self._handle_rename_flow()
            return
        if route == "/api/flows/delete":
            self._handle_delete_flow()
            return
        if route == "/api/plans":
            self._handle_save_plan()
            return
        if route == "/api/plans/delete":
            self._handle_delete_plan()
            return
        if route == "/api/plans/chat":
            self._handle_plan_chat()
            return
        if route == "/api/plans/generate":
            self._handle_generate_and_bind()
            return
        self.send_error(404)

    # --- tracks / threads ---

    def _handle_create_track(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        track = create_track(
            root,
            str(body.get("name") or "新轨道").strip(),
            str(body.get("intent") or "").strip(),
            str(body.get("depth") or "").strip(),
        )
        self._json({"track": track.to_dict(),
                    "trackRecord": _track_record(root, track, STATE["idx"])})

    def _handle_update_track(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        track_id = str(body.get("id") or "").strip()
        fields = {}
        if "name" in body:
            fields["name"] = str(body.get("name") or "").strip() or "未命名轨道"
        if "intent" in body:
            fields["intent"] = str(body.get("intent") or "")
        if "depth" in body:
            fields["depth"] = str(body.get("depth") or "")
        if "stage" in body:
            fields["stage"] = str(body.get("stage") or "")
        track = update_track(root, track_id, **fields)
        if track is None:
            self._json({"error": "track not found"}, 404)
            return
        self._json({"track": track.to_dict(),
                    "trackRecord": _track_record(root, track, STATE["idx"])})

    def _handle_delete_track(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        self._json({"deleted": delete_track(root, str(body.get("id") or ""))})

    # --- local model settings ---

    def _handle_save_settings(self) -> None:
        body = self._read_json()
        try:
            settings = save_settings(
                body, clear_key=bool(body.get("clearKey")))
        except OSError as exc:
            self._json({"error": f"cannot save settings: {exc}"}, 500)
            return
        self._json({"settings": settings})

    def _handle_list_models(self) -> None:
        body = self._read_json()
        base_url = str(body.get("baseUrl") or "").strip()
        api_key = str(body.get("apiKey") or "").strip()
        if not api_key:
            api_key = resolve_credentials()[0]
        try:
            models = fetch_models(base_url, api_key)
        except SettingsError as exc:
            self._json({"error": str(exc)}, 422)
            return
        self._json({"models": models})

    # --- logical skeleton (stage one) ---

    def _handle_generate_skeleton(self) -> None:
        root = self._project_root()
        if root is None or STATE["idx"] is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        track = load_track(root, str(body.get("trackId") or ""))
        if track is None:
            tracks = list_tracks(root)
            track = tracks[0] if tracks else ensure_default_track(root)
        focus = str(body.get("focus") or "").strip()
        try:
            skeleton, source = generate_skeleton(
                root, STATE["idx"], track_id=track.id, focus=focus,
                inventory=STATE.get("skeleton_inventory"))
        except SkeletonError as exc:
            self._json({"error": str(exc)}, 422)
            return
        self._json({
            "skeleton": skeleton_record(skeleton, STATE["idx"]),
            "source": source,
        })

    def _handle_explain_skeleton_node(self) -> None:
        root = self._project_root()
        if root is None or STATE["idx"] is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        skeleton = load_skeleton(root, str(body.get("skeletonId") or ""))
        if skeleton is None:
            self._json({"error": "skeleton not found"}, 404)
            return
        try:
            skeleton, node = explain_node(
                root, STATE["idx"], skeleton, str(body.get("nodeId") or ""))
        except SkeletonError as exc:
            self._json({"error": str(exc)}, 422)
            return
        self._json({
            "skeleton": skeleton_record(skeleton, STATE["idx"]),
            "node": node,
        })

    def _skeleton_need(self, skeleton, node: dict, after: list[str],
                       *, support: bool = False, granularity: str = "结构") -> dict:
        return {
            "query": f"{node.get('title')}：{node.get('summary') or '讲清这一节点的完整逻辑'}",
            "stepId": f"sk-{node.get('id')}",
            "goal": node.get("title") or node.get("id"),
            "after": after,
            "granularity": granularity,
            "skippable": "平行支撑，可按需跳过" if support else "",
            "skeletonId": skeleton.id,
            "nodeId": node.get("id"),
        }

    def _append_skeleton_import(self, root, track, skeleton,
                                main_nodes: list[dict], support_nodes: list[dict],
                                *, reply: str, notes: list[str]) -> dict:
        needs: list[dict] = []
        after: list[str] = []
        granularity = track.depth or "结构"
        for node in main_nodes:
            need = self._skeleton_need(
                skeleton, node, after, support=False, granularity=granularity)
            needs.append(need)
            after = [need["stepId"]]
        # Support nodes are parallel capabilities, not a second chain and not a
        # hard dependency on the main flow. They can be generated independently.
        for node in support_nodes:
            need = self._skeleton_need(
                skeleton, node, [], support=True, granularity=granularity)
            needs.append(need)
        thread = ensure_plan_thread(root, track)
        append_message(root, thread.id, "assistant", reply, turn={
            "reply": reply,
            "ops": [],
            "rejected": [],
            "notes": notes,
            "needsGeneration": needs,
        })
        update_track(root, track.id, stage="plan", depth="结构")
        track = load_track(root, track.id)
        return {
            "trackRecord": _track_record(root, track, STATE["idx"]),
            "needs": needs,
            "thread": load_thread(root, thread.id).to_dict(),
        }

    def _handle_import_skeleton_main(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        track = load_track(root, str(body.get("trackId") or ""))
        skeleton = load_skeleton(root, str(body.get("skeletonId") or ""))
        if track is None or skeleton is None:
            self._json({"error": "track or skeleton not found"}, 404)
            return
        self._json(self._append_skeleton_import(
            root, track, skeleton, skeleton.main, skeleton.support,
            reply=f"已从「{skeleton.title}」导入 {len(skeleton.main)} 个主流程步骤和 "
                  f"{len(skeleton.support)} 个平行支撑节点；生成切片后才会写入计划。",
            notes=[f"从骨架导入主流程：{skeleton.title}"],
        ))

    def _handle_import_skeleton_node(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        track = load_track(root, str(body.get("trackId") or ""))
        skeleton = load_skeleton(root, str(body.get("skeletonId") or ""))
        if track is None or skeleton is None:
            self._json({"error": "track or skeleton not found"}, 404)
            return
        node_id = str(body.get("nodeId") or "")
        node = next((n for n in skeleton.main + skeleton.support if n.get("id") == node_id), None)
        if node is None:
            self._json({"error": "node not found"}, 404)
            return
        is_main = any(n.get("id") == node_id for n in skeleton.main)
        self._json(self._append_skeleton_import(
            root, track, skeleton,
            [node] if is_main else [],
            [] if is_main else [node],
            reply=f"已把节点「{node.get('title')}」加入计划，生成切片后才会写入计划。",
            notes=[f"从骨架导入节点：{node.get('title')}"],
        ))

    def _handle_delete_skeleton(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        self._json({"deleted": delete_skeleton(root, str(body.get("id") or ""))})

    # --- slices ---

    def _enrich_scope(self, root: pathlib.Path,
                      scope: dict | None) -> dict | None:
        """Attach the node's real symbols/files to a skeleton-node scope.

        The frontend only needs to say which node it came from. The server owns
        the mapping, so a stale/renamed node cannot silently produce a slice
        with no grounded seeds.
        """
        if not scope or scope.get("kind") != "skeleton-node":
            return scope
        skeleton_id = str(scope.get("skeletonId") or "").strip()
        node_id = str(scope.get("nodeId") or "").strip()
        if not skeleton_id or not node_id:
            return scope
        skeleton = load_skeleton(root, skeleton_id)
        if skeleton is None:
            return scope
        node = next((n for n in skeleton.main + skeleton.support
                     if n.get("id") == node_id), None)
        if node is None:
            return scope
        return {
            **scope,
            "symbolIds": list(node.get("symbolIds") or []),
            "files": list(node.get("files") or []),
        }

    def _handle_generate_slice(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        query = str(body.get("query") or "").strip()
        if not query:
            self._json({"error": "empty query"}, 400)
            return
        track_id = str(body.get("trackId") or "").strip()
        track = load_track(root, track_id) if track_id else None
        if track is None:
            tracks = list_tracks(root)
            track = tracks[0] if tracks else ensure_default_track(root)
        strategies = body.get("strategies") or []
        if isinstance(strategies, str):
            strategies = [strategies]
        source = body.get("source") or {"kind": "query", "label": query}
        scope = body.get("scope") if isinstance(body.get("scope"), dict) else None
        scope = self._enrich_scope(root, scope)
        try:
            slice_, source_kind = generate_slice(
                root, STATE["idx"], track_id=track.id, query=query,
                strategies=[str(s) for s in strategies], scope=scope)
        except SliceError as exc:
            self._json({"error": str(exc)}, 422)
            return
        thread = ensure_slice_thread(root, track.id, slice_.id, slice_.title)
        self._json({
            "slice": slice_record(slice_, STATE["idx"]),
            "thread": thread.to_dict(),
            "source": source_kind,
            "sourceRef": source,
        })

    def _handle_regenerate_slice(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        slice_id = str(body.get("id") or "").strip()
        if not slice_id:
            self._json({"error": "missing slice id"}, 400)
            return
        try:
            slice_, source = regenerate_slice(root, STATE["idx"], slice_id)
        except SliceError as exc:
            self._json({"error": str(exc)}, 422)
            return
        thread = ensure_slice_thread(root, slice_.track_id, slice_.id, slice_.title)
        self._json({
            "slice": slice_record(slice_, STATE["idx"]),
            "thread": thread.to_dict(),
            "source": source,
        })

    def _handle_delete_slice(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        self._json({"deleted": delete_slice(root, str(body.get("id") or ""))})

    def _handle_rename_slice(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        slice_ = rename_slice(root, str(body.get("id") or ""),
                              str(body.get("name") or ""))
        if slice_ is None:
            self._json({"error": "slice not found or empty name"}, 404)
            return
        self._json({"slice": slice_record(slice_, STATE["idx"])})

    # --- plan design conversation (persisted) ---

    def _handle_track_plan_chat(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        message = str(body.get("message") or "").strip()
        if not message:
            self._json({"error": "empty message"}, 400)
            return
        track = load_track(root, str(body.get("trackId") or ""))
        if track is None:
            self._json({"error": "track not found"}, 404)
            return

        plan = load_plan(root, track.plan_id) if track.plan_id else None
        slices = list_slices(root)
        try:
            turn = request_turn(message, plan, slices, depth=track.depth)
        except ChatError as exc:
            self._json({"error": str(exc)}, 502)
            return

        # The model may explicitly change the depth contract. This is a track-level
        # memory, not a plan item; apply it before rendering the track record.
        depth_ops = [op.value for op in turn.ops if op.kind == "set_depth"]
        if depth_ops:
            update_track(root, track.id, depth=depth_ops[-1])
            track = load_track(root, track.id)

        base = plan or SavedPlan(
            id="", name=message[:40] or track.name, intent=track.intent,
            items=[], created_at="", updated_at="")
        updated, notes = apply_turn(base, turn)

        plan_record = None
        saved = None
        if updated.items:
            try:
                saved = save_plan(
                    root,
                    {"name": updated.name, "intent": updated.intent,
                     "items": [
                         {"id": i.id, "flowId": i.flow_id, "goal": i.goal,
                          "after": i.after, "skippable": i.skippable,
                          "granularity": i.granularity}
                         for i in updated.items
                     ]},
                    plan_id=plan.id if plan else None,
                    name=updated.name,
                    flows={s.id: s for s in slices},
                )
            except PlanStoreError as exc:
                self._json({"error": f"计划无法保存：{exc}"}, 400)
                return
            update_track(root, track.id, plan_id=saved.id,
                         intent=updated.intent or track.intent)
            track = load_track(root, track.id)
            plan_record = _plan_record_slices(root, saved, STATE["idx"])

        thread = ensure_plan_thread(root, track)
        append_message(root, thread.id, "user", message)
        turn_dict = turn.to_dict()
        turn_dict["notes"] = notes
        append_message(root, thread.id, "assistant", turn.reply,
                       turn=turn_dict)
        thread = load_thread(root, thread.id)

        self._json({
            "reply": turn.reply,
            "turn": turn_dict,
            "notes": notes,
            "plan": plan_record,
            "trackRecord": _track_record(root, track, STATE["idx"]),
            "thread": thread.to_dict() if thread else None,
        })

    def _handle_apply_plan(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        track = load_track(root, str(body.get("trackId") or ""))
        if track is None:
            self._json({"error": "track not found"}, 404)
            return
        plan = load_plan(root, track.plan_id) if track.plan_id else None
        try:
            saved = save_plan(
                root,
                {"name": body.get("name") or (plan.name if plan else track.name),
                 "intent": body.get("intent") or track.intent,
                 "items": body.get("items") or []},
                plan_id=plan.id if plan else None,
                name=body.get("name") or (plan.name if plan else track.name),
                flows=_slices_dict(root),
            )
        except PlanStoreError as exc:
            self._json({"error": str(exc)}, 400)
            return
        update_track(root, track.id, plan_id=saved.id,
                     intent=str(body.get("intent") or saved.intent or track.intent))
        track = load_track(root, track.id)
        self._json({
            "plan": _plan_record_slices(root, saved, STATE["idx"]),
            "trackRecord": _track_record(root, track, STATE["idx"]),
        })

    def _handle_generate_bind(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        track = load_track(root, str(body.get("trackId") or ""))
        if track is None:
            self._json({"error": "track not found"}, 404)
            return
        plan = load_plan(root, track.plan_id) if track.plan_id else None
        req_raw = body.get("request") or {}
        query = str(req_raw.get("query") or "").strip()
        if not query:
            self._json({"error": "empty slice query"}, 400)
            return
        request = FlowRequest(
            query=query,
            step_id=str(req_raw.get("stepId") or "").strip(),
            goal=str(req_raw.get("goal") or "").strip(),
            after=tuple(req_raw.get("after") or []),
            granularity=str(req_raw.get("granularity") or "").strip(),
            skippable=str(req_raw.get("skippable") or "").strip(),
        )
        skeleton_id = str(req_raw.get("skeletonId") or "").strip()
        node_id = str(req_raw.get("nodeId") or "").strip()
        scope = ({
            "kind": "skeleton-node",
            "skeletonId": skeleton_id,
            "nodeId": node_id,
            "label": request.goal or query,
        } if skeleton_id and node_id else {
            "kind": "plan-step", "planStep": request.step_id,
            "label": request.goal or query,
        })
        scope = self._enrich_scope(root, scope)
        try:
            slice_, source = generate_slice(
                root, STATE["idx"], track_id=track.id, query=query,
                scope=scope)
        except SliceError as exc:
            self._json({"error": str(exc)}, 422)
            return

        bind = bind_generated_flow(request, slice_, plan)
        if not bind.ok:
            self._json({"error": bind.rejected,
                        "slice": {"id": slice_.id}, "source": source}, 400)
            return

        steps = [
            {"id": i.id, "flowId": i.flow_id, "goal": i.goal,
             "after": i.after, "skippable": i.skippable,
             "granularity": i.granularity}
            for i in (plan.items if plan else [])
        ]
        steps.append({
            "id": bind.step_id,
            "flowId": bind.flow_id,
            "goal": request.goal or slice_.title,
            "after": list(request.after),
            "skippable": request.skippable,
            "granularity": request.granularity,
        })
        try:
            saved = save_plan(
                root,
                {"name": plan.name if plan else track.name,
                 "intent": plan.intent if plan else track.intent,
                 "items": steps},
                plan_id=plan.id if plan else None,
                name=plan.name if plan else track.name,
                flows=_slices_dict(root),
            )
        except PlanStoreError as exc:
            self._json({"error": f"绑定后计划不成立：{exc}"}, 400)
            return
        update_track(root, track.id, plan_id=saved.id,
                     intent=saved.intent or track.intent)
        track = load_track(root, track.id)
        thread = ensure_slice_thread(root, track.id, slice_.id, slice_.title)
        self._json({
            "bind": bind.to_dict(),
            "source": source,
            "slice": slice_record(slice_, STATE["idx"]),
            "thread": thread.to_dict(),
            "trackRecord": _track_record(root, track, STATE["idx"]),
        })

    # --- side-panel threads ---

    def _handle_create_thread(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        scope = str(body.get("scope") or "slice")
        track_id = str(body.get("trackId") or "").strip()
        slice_id = str(body.get("sliceId") or "").strip()
        anchor = body.get("anchor") if isinstance(body.get("anchor"), dict) else {}
        title = str(body.get("title") or "").strip()
        if scope == "slice":
            if not slice_id or load_slice(root, slice_id) is None:
                self._json({"error": "slice not found"}, 404)
                return
            thread = ensure_slice_thread(root, track_id, slice_id, title)
        else:
            thread = create_thread(root, scope, track_id=track_id,
                                   slice_id=slice_id, anchor=anchor,
                                   title=title)
        self._json({"thread": thread.to_dict()})

    def _handle_thread_message(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        message = str(body.get("message") or "").strip()
        if not message:
            self._json({"error": "empty message"}, 400)
            return
        thread = load_thread(root, str(body.get("threadId") or ""))
        if thread is None:
            self._json({"error": "thread not found"}, 404)
            return
        slice_ = load_slice(root, thread.slice_id) if thread.slice_id else None
        if slice_ is None:
            self._json({"error": "thread has no slice"}, 400)
            return
        context = body.get("context") if isinstance(body.get("context"), dict) else {}
        history = list(thread.messages)
        append_message(root, thread.id, "user", message, context=context)
        result = side_answer(root, STATE["idx"], slice_, history, message, context)
        append_message(root, thread.id, "assistant", result["reply"],
                       citations=result.get("citations"))
        thread = load_thread(root, thread.id)
        self._json({
            "thread": thread.to_dict() if thread else None,
            "rejected": result.get("rejected") or [],
            "suggestedSlices": result.get("suggestedSlices") or [],
        })

    # --- trace ---

    def _handle_trace(self) -> None:
        if STATE["base"] is None or STATE["idx"] is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        file = str(body.get("file") or "").strip()
        if file not in STATE["base"]["files"]:
            self._json({"error": "not an indexed file"}, 404)
            return
        try:
            line = int(body.get("line") or 1)
            char = int(body.get("char") or 0)
        except (TypeError, ValueError):
            self._json({"error": "bad position"}, 400)
            return
        kind = str(body.get("kind") or "definition")
        if kind not in ("definition", "references", "callers", "callees"):
            self._json({"error": "bad trace kind"}, 400)
            return
        service = STATE.get("trace")
        if service is None:
            service = TraceService(pathlib.Path(STATE["base"]["root"]), PYRIGHT,
                                   STATE["idx"])
            STATE["trace"] = service
        try:
            self._json(service.query(file, line, char, kind))
        except Exception as exc:
            self._json({"error": f"trace failed: {exc}"}, 500)

    # --- saved flows ---

    def _project_root(self) -> pathlib.Path | None:
        if STATE["base"] is None:
            return None
        return pathlib.Path(STATE["base"]["root"])

    def _handle_save_flow(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        payload = body.get("plan")
        if not isinstance(payload, dict):
            self._json({"error": "missing plan"}, 400)
            return
        name = body.get("name")
        try:
            flow = save_flow(root, STATE["idx"], payload,
                             name=str(name) if name else None)
        except StoreError as exc:
            self._json({"error": str(exc)}, 400)
            return
        self._json({"flow": _flow_record(flow, STATE["idx"])})

    def _handle_rename_flow(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        flow = rename_flow(root, str(body.get("id") or ""), str(body.get("name") or ""))
        if flow is None:
            self._json({"error": "flow not found or name empty"}, 404)
            return
        self._json({"flow": _flow_record(flow, STATE["idx"])})

    def _handle_delete_flow(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        ok = delete_flow(root, str(body.get("id") or ""))
        self._json({"deleted": ok})

    # --- plan conversation ---

    def _handle_plan_chat(self) -> None:
        """Talk to the plan designer. The product of a turn is a changed plan."""
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return

        from engine.store import list_flows

        body = self._read_json()
        message = str(body.get("message") or "").strip()
        plan_id = str(body.get("planId") or "").strip()
        if not message:
            self._json({"error": "empty message"}, 400)
            return

        plan = load_plan(root, plan_id) if plan_id else None
        flows = list_flows(root)

        try:
            turn = request_turn(message, plan, flows)
        except ChatError as exc:
            self._json({"error": str(exc)}, 502)
            return

        # a first turn with no plan yet: start one from what the model produced
        base = plan or SavedPlan(
            id="", name=message[:40] or "新计划", intent="",
            items=[], created_at="", updated_at="")

        updated, notes = apply_turn(base, turn)

        if not updated.items:
            # Nothing to persist as steps yet, but the intent is still a real
            # product of the turn. Losing it makes "用途改为…" a lie.
            if updated.intent and updated.intent != track.intent:
                update_track(root, track.id, intent=updated.intent)
                track = load_track(root, track.id)
            thread = ensure_plan_thread(root, track)
            append_message(root, thread.id, "user", message)
            turn_dict = turn.to_dict()
            turn_dict["notes"] = notes
            append_message(root, thread.id, "assistant", turn.reply,
                           turn=turn_dict)
            thread = load_thread(root, thread.id)
            self._json({
                "reply": turn.reply,
                "turn": turn_dict,
                "notes": notes,
                "plan": None,
                "trackRecord": _track_record(root, track, STATE["idx"]),
                "thread": thread.to_dict() if thread else None,
            })
            return

        try:
            saved = save_plan(
                root,
                {"name": updated.name, "intent": updated.intent,
                 "items": [
                     {"id": i.id, "flowId": i.flow_id, "goal": i.goal,
                      "after": i.after, "skippable": i.skippable,
                      "granularity": i.granularity}
                     for i in updated.items
                 ]},
                plan_id=plan.id if plan else None,
                name=updated.name,
            )
        except PlanStoreError as exc:
            self._json({"error": f"计划无法保存：{exc}"}, 400)
            return

        self._json({
            "reply": turn.reply,
            "turn": turn.to_dict(),
            "notes": notes,
            "plan": _plan_record(root, saved, STATE["idx"]),
        })

    def _handle_generate_and_bind(self) -> None:
        """Generate the flow a pending request asked for, then bind it to its step.

        This closes the loop the designer leaves open: when the library has no
        flow for what the user wants, the turn records the gap; here the gap gets
        filled and the step lands in the plan in one action.
        """
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return

        from engine.plans import load_plan, save_plan
        from engine.store import list_flows, save_flow
        from engine.plan import views_or_fallback

        body = self._read_json()
        plan_id = str(body.get("planId") or "").strip()
        req_raw = body.get("request") or {}
        query = str(req_raw.get("query") or "").strip()
        if not query:
            self._json({"error": "empty flow query"}, 400)
            return

        plan = load_plan(root, plan_id) if plan_id else None
        request = FlowRequest(
            query=query,
            step_id=str(req_raw.get("stepId") or ""),
            goal=str(req_raw.get("goal") or ""),
            after=tuple(req_raw.get("after") or []),
            granularity=str(req_raw.get("granularity") or ""),
            skippable=str(req_raw.get("skippable") or ""),
        )

        # 1. generate the flow
        bundle, source = views_or_fallback(
            STATE["idx"], query, inventory=STATE["inventory"])
        if not bundle.views:
            self._json({"error": "模型没有生成任何视图"}, 422)
            return

        flow = save_flow(root, STATE["idx"], {
            "query": query, "title": bundle.title,
            "summary": bundle.summary,
            "views": bundle.to_dict().get("views", []),
        }, name=bundle.title or query)

        # 2. bind it, refusing a structurally broken result
        bind = bind_generated_flow(request, flow, plan)
        if not bind.ok:
            self._json({"error": bind.rejected, "flow": {"id": flow.id},
                        "source": source}, 400)
            return

        # 3. put the step on the plan and save
        steps = []
        if plan is not None:
            steps = [
                {"id": i.id, "flowId": i.flow_id, "goal": i.goal,
                 "after": i.after, "skippable": i.skippable,
                 "granularity": i.granularity}
                for i in plan.items
            ]
        steps.append({
            "id": bind.step_id,
            "flowId": bind.flow_id,
            "goal": request.goal or flow.name,
            "after": list(request.after),
            "skippable": request.skippable,
            "granularity": request.granularity,
        })

        try:
            saved = save_plan(
                root,
                {"name": plan.name if plan else (query[:40] or "新计划"),
                 "intent": plan.intent if plan else "",
                 "items": steps},
                plan_id=plan.id if plan else None,
            )
        except PlanStoreError as exc:
            self._json({"error": f"绑定后计划不成立：{exc}",
                        "flow": {"id": flow.id}}, 400)
            return

        self._json({
            "bind": bind.to_dict(),
            "source": source,
            "plan": _plan_record(root, saved, STATE["idx"]),
        })

    # --- plans ---

    def _handle_save_plan(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        try:
            plan = save_plan(root, body,
                             plan_id=body.get("id") or None,
                             name=body.get("name") or None)
        except PlanStoreError as exc:
            self._json({"error": str(exc)}, 400)
            return
        self._json({"plan": _plan_record(root, plan, STATE["idx"])})

    def _handle_delete_plan(self) -> None:
        root = self._project_root()
        if root is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        self._json({"deleted": delete_plan(root, str(body.get("id") or ""))})

    def _handle_plan(self) -> None:
        if STATE["idx"] is None:
            self._json({"error": "no project open"}, 503)
            return
        body = self._read_json()
        query = str(body.get("query") or "").strip()
        if not query:
            self._json({"error": "empty query"}, 400)
            return

        cache = STATE["plan_cache"]
        if query in cache:
            bundle, source = cache[query]
            self._json({"plan": bundle.to_dict(), "source": source, "cached": True})
            return

        bundle, source = views_or_fallback(
            STATE["idx"], query, inventory=STATE["inventory"])
        cache[query] = (bundle, source)
        self._json({"plan": bundle.to_dict(), "source": source, "cached": False})

    def _handle_pick_folder(self) -> None:
        body = self._read_json()
        initial = str(body.get("initial") or "").strip()
        try:
            path = pick_folder(initial)
        except PickerError as exc:
            self._json({
                "error": str(exc),
                "hint": "请用“浏览目录”或直接输入路径。",
            }, 500)
            return
        except Exception as exc:  # dialog is best-effort
            self._json({"error": f"无法打开系统选择器：{exc}"}, 500)
            return
        if path:
            try:
                path = str(normalize_path(path))
            except PathError:
                pass
        self._json({"path": path, "cancelled": not path})

    def _handle_open(self) -> None:
        body = self._read_json()
        raw = str(body.get("root") or "").strip()
        if not raw:
            self._json({"error": "empty root", "hint": "输入或选择一个项目目录"}, 400)
            return
        try:
            target = normalize_path(raw)
        except PathError as exc:
            self._json({"error": str(exc), "hint": "支持绝对路径、~、file:/// 和带引号的路径"}, 400)
            return
        if target.is_file():
            self._json({
                "error": f"这是一个文件，不是目录：{target}",
                "hint": "请选择包含项目的文件夹；如果这是项目文件，请打开它所在的目录。",
                "path": str(target),
            }, 400)
            return
        if not target.exists():
            self._json({
                "error": f"目录不存在：{target}",
                "hint": "检查路径拼写，或用“浏览目录/选择文件夹”重新选择。",
                "path": str(target),
            }, 400)
            return
        if not target.is_dir():
            self._json({"error": f"不是目录：{target}", "path": str(target)}, 400)
            return
        try:
            index_project(target, STATE.get("max_symbols", 400))
        except Exception as exc:
            self._json({
                "error": f"索引失败：{exc}",
                "hint": "确认目录可读、pyright 已安装，并且项目里至少有一个 Python 文件。",
                "path": str(target),
            }, 500)
            return
        self._json(STATE["base"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=pathlib.Path, nargs="?")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (use 0.0.0.0 in Docker)")
    ap.add_argument("--port", type=int, default=7717)
    ap.add_argument("--max-symbols", type=int, default=400)
    args = ap.parse_args()

    if not PYRIGHT.exists():
        print(f"pyright not found at {PYRIGHT}", file=sys.stderr)
        return 2

    STATE["max_symbols"] = args.max_symbols

    if args.root:
        print(f"indexing {args.root.resolve()} ...", file=sys.stderr)
        index_project(args.root, args.max_symbols)
        print(f"  {len(STATE['idx'].symbols)} symbols, "
              f"{len(STATE['idx'].edges)} edges", file=sys.stderr)
    else:
        print("no project given — open one from the UI", file=sys.stderr)

    try:
        srv = QuietThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        print("", file=sys.stderr)
        print(f"  无法绑定端口 {args.port}：{exc}", file=sys.stderr)
        print("  这个端口很可能被另一个旧的 python 进程占用。", file=sys.stderr)
        print("", file=sys.stderr)
        print("  查看占用进程：", file=sys.stderr)
        print(f"    Get-NetTCPConnection -LocalPort {args.port} -State Listen", file=sys.stderr)
        print("  结束旧进程（管理员终端）：", file=sys.stderr)
        print("    taskkill /PID <PID> /F", file=sys.stderr)
        print("", file=sys.stderr)
        print("  或者直接换端口：", file=sys.stderr)
        print(f"    python serve.py <项目目录> --port {args.port + 1}", file=sys.stderr)
        return 1

    actual_port = srv.server_address[1]
    display_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print("", file=sys.stderr)
    print(f"  http://{display_host}:{actual_port}/", file=sys.stderr)
    print(f"  pid {os.getpid()}  ·  ctrl-c to stop", file=sys.stderr)
    print("", file=sys.stderr)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
