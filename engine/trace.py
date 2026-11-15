"""Hybrid trace service: index first, the file's LSP for the unknown.

Ctrl+click needs to resolve arbitrary identifiers, not just the call edges the
indexer happened to precompute. Warm language servers give real definitions,
references and call hierarchy; the index remains the fast path and the fallback
when a language server is unavailable.

The service runs one asyncio loop in a daemon thread so the synchronous
ThreadingHTTPServer can call it without each request paying process startup.
"""

from __future__ import annotations

import asyncio
import pathlib
import threading
import urllib.parse

from .languages import LanguageSpec, spec_for_path
from .lsp import LspClient, LspError
from .model import Index


def _rel_from_uri(root: pathlib.Path, uri: str) -> str:
    parsed = urllib.parse.urlsplit(uri)
    path = urllib.parse.unquote(parsed.path)
    # Windows: file:///d%3A/... -> /d:/...
    if path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    p = pathlib.Path(path)
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


class TraceService:
    def __init__(self, root: pathlib.Path, idx: Index,
                 specs: list[LanguageSpec] | None = None,
                 timeout: float = 15.0):
        self.root = root.resolve()
        self.idx = idx
        self.specs = specs or []
        self.timeout = timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._clients: dict[str, LspClient] = {}
        self._opened: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()
        self._cache: dict[tuple, dict] = {}
        self._project_files = set(idx.files) | {s.relpath for s in idx.symbols.values()}

    def _spec(self, rel: str) -> LanguageSpec:
        spec = spec_for_path(rel)
        if spec is None:
            raise LspError(f"no language server for {rel}")
        if not spec.available:
            raise LspError(f"{spec.label} language server is not installed")
        return spec

    # --- lifecycle ------------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        loop = asyncio.new_event_loop()

        def run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        thread = threading.Thread(target=run, daemon=True, name="qta-trace")
        thread.start()
        self._loop = loop
        self._thread = thread
        return loop

    def _submit(self, coro, timeout: float | None = None):
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout or self.timeout)

    def stop(self) -> None:
        if self._loop is None:
            return
        try:
            self._submit(self._close(), timeout=5)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    async def _close(self) -> None:
        for client in self._clients.values():
            try:
                await client.close()
            except Exception:
                pass
        self._clients.clear()
        self._opened.clear()

    async def _ensure_client(self, spec: LanguageSpec) -> LspClient:
        async with self._lock:
            client = self._clients.get(spec.id)
            if client is not None:
                return client
            if not spec.command:
                raise LspError(f"{spec.label} language server is not configured")
            client = LspClient(list(spec.command), self.root)
            await client.__aenter__()
            await client.initialize(self.root, options=spec.initialization_options)
            self._clients[spec.id] = client
            return client

    async def _open(self, rel: str) -> tuple[LspClient, str]:
        spec = self._spec(rel)
        client = await self._ensure_client(spec)
        path = (self.root / rel).resolve()
        uri = path.as_uri()
        key = (spec.id, rel)
        if key not in self._opened:
            await client.open_file(path, spec.language_id)
            self._opened.add(key)
        return client, uri

    # --- mapping --------------------------------------------------------

    def _symbol_at(self, rel: str, line: int, char: int) -> str | None:
        """line is 1-based, char is 0-based."""
        best: tuple[int, str] | None = None
        for sid, sym in self.idx.symbols.items():
            if sym.relpath != rel:
                continue
            r = sym.body_range
            if r.start_line + 1 <= line <= r.end_line + 1:
                size = r.end_line - r.start_line
                if best is None or size < best[0]:
                    best = (size, sid)
        return best[1] if best else None

    def _location(self, loc: dict) -> dict | None:
        uri = loc.get("uri") or loc.get("targetUri")
        rng = loc.get("targetSelectionRange") or loc.get("range") or loc.get("targetRange")
        if not uri or not rng:
            return None
        rel = _rel_from_uri(self.root, uri)
        start = rng.get("start") or {}
        end = rng.get("end") or {}
        line = int(start.get("line", 0)) + 1
        char = int(start.get("character", 0))
        sym = self.idx.symbols.get(self._symbol_at(rel, line, char) or "")
        return {
            "file": rel,
            "line": line,
            "char": char,
            "endLine": int(end.get("line", start.get("line", 0))) + 1,
            "endChar": int(end.get("character", 0)),
            "symbolId": sym.id if sym else "",
            "name": sym.qualname if sym else "",
            "external": rel not in self._project_files,
        }

    def _symbol_location(self, sid: str) -> dict | None:
        sym = self.idx.symbols.get(sid)
        if sym is None:
            return None
        return {
            "file": sym.relpath,
            "line": sym.body_range.start_line + 1,
            "char": sym.range.start_char,
            "endLine": sym.body_range.end_line + 1,
            "endChar": sym.body_range.end_char,
            "symbolId": sym.id,
            "name": sym.qualname,
            "external": False,
        }

    # --- public query ---------------------------------------------------

    def query(self, rel: str, line: int, char: int, kind: str) -> dict:
        key = (rel, line, char, kind, self.idx.revision)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            result = self._submit(self._query(rel, line, char, kind))
        except Exception:
            result = self._fallback(rel, line, char, kind)
        self._cache[key] = result
        return result

    async def _query(self, rel: str, line: int, char: int, kind: str) -> dict:
        client, uri = await self._open(rel)
        position = {"line": max(0, line - 1), "character": max(0, char)}
        if kind == "definition":
            raw = await client.request("textDocument/definition", {
                "textDocument": {"uri": uri}, "position": position,
            }, timeout=self.timeout)
            if isinstance(raw, dict):
                raw = [raw]
            locations = [x for x in (self._location(x) for x in (raw or [])
                                     if isinstance(x, dict)) if x]
            kept = [x for x in locations if not x.get("external")]
            return {"kind": kind, "engine": "lsp", "locations": kept,
                    "externalCount": len(locations) - len(kept)}
        if kind == "references":
            raw = await client.request("textDocument/references", {
                "textDocument": {"uri": uri}, "position": position,
                "context": {"includeDeclaration": True},
            }, timeout=self.timeout)
            locations = [x for x in (self._location(x) for x in (raw or [])
                                     if isinstance(x, dict)) if x]
            kept = [x for x in locations if not x.get("external")]
            return {"kind": kind, "engine": "lsp", "locations": kept,
                    "externalCount": len(locations) - len(kept)}
        if kind in ("callers", "callees"):
            prep = await client.request("textDocument/prepareCallHierarchy", {
                "textDocument": {"uri": uri}, "position": position,
            }, timeout=self.timeout)
            if not prep:
                return {"kind": kind, "engine": "lsp", "items": []}
            method = ("callHierarchy/incomingCalls" if kind == "callers"
                      else "callHierarchy/outgoingCalls")
            raw = await client.request(method, {"item": prep[0]}, timeout=self.timeout)
            items = []
            for call in raw or []:
                node = call.get("from") if kind == "callers" else call.get("to")
                if not node:
                    continue
                loc = self._location({"uri": node.get("uri"),
                                      "range": node.get("selectionRange") or node.get("range")})
                if not loc:
                    continue
                sites = []
                for rng in call.get("fromRanges") or []:
                    start = rng.get("start") or {}
                    sites.append({"file": loc["file"], "line": int(start.get("line", 0)) + 1})
                if not loc.get("external"):
                    items.append({**loc, "sites": sites})
            external = sum(1 for call in (raw or [])
                           if call.get("from") or call.get("to"))
            return {"kind": kind, "engine": "lsp", "items": items,
                    "externalCount": max(0, external - len(items))}
        raise LspError(f"unknown trace kind: {kind}")

    # --- fallback -------------------------------------------------------

    def _fallback(self, rel: str, line: int, char: int, kind: str) -> dict:
        sid = self._symbol_at(rel, line, char)
        if kind == "definition":
            loc = self._symbol_location(sid) if sid else None
            return {"kind": kind, "engine": "index",
                    "locations": [loc] if loc else []}
        if kind == "references":
            locs: list[dict] = []
            if sid:
                for e in self.idx.edges:
                    if e.callee_id == sid:
                        sym = self.idx.symbols.get(e.caller_id)
                        if sym:
                            locs.append({
                                "file": sym.relpath,
                                "line": e.site.start_line + 1,
                                "char": e.site.start_char,
                                "endLine": e.site.end_line + 1,
                                "endChar": e.site.end_char,
                                "symbolId": sym.id, "name": sym.qualname,
                            })
                loc = self._symbol_location(sid)
                if loc:
                    locs.append(loc)
            return {"kind": kind, "engine": "index", "locations": locs}
        if kind in ("callers", "callees"):
            items: list[dict] = []
            if sid:
                for e in self.idx.edges:
                    other = e.caller_id if kind == "callers" else e.callee_id
                    sym = self.idx.symbols.get(other)
                    if sym is None:
                        continue
                    items.append({
                        "file": sym.relpath,
                        "line": sym.body_range.start_line + 1,
                        "char": sym.range.start_char,
                        "endLine": sym.body_range.end_line + 1,
                        "endChar": sym.body_range.end_char,
                        "symbolId": sym.id, "name": sym.qualname,
                        "sites": [{"file": self.idx.symbols[e.caller_id].relpath
                                   if e.caller_id in self.idx.symbols else "",
                                   "line": e.site.start_line + 1}],
                    })
            return {"kind": kind, "engine": "index", "items": items}
        return {"kind": kind, "engine": "index", "locations": [], "items": []}
