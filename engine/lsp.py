"""Minimal LSP client over stdio. One server process, one workspace."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
from typing import Any


class LspError(RuntimeError):
    pass


class LspClient:
    def __init__(self, cmd: list[str], cwd: pathlib.Path):
        self.cmd = cmd
        self.cwd = cwd
        self._proc: asyncio.subprocess.Process | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None
        self._closed = False
        # a frame is written in several steps; concurrent writers would interleave
        # header/body and corrupt the stream, so all writes serialize here
        self._write_lock = asyncio.Lock()

    async def __aenter__(self) -> "LspClient":
        self._proc = await asyncio.create_subprocess_exec(
            *self.cmd,
            cwd=str(self.cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._reader = asyncio.create_task(self._read_loop())
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._proc and self._proc.returncode is None:
            self._proc.kill()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
        if self._reader and not self._reader.done():
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        stream = self._proc.stdout
        try:
            while True:
                headers: dict[str, str] = {}
                while True:
                    raw = await stream.readline()
                    if not raw:
                        return
                    line = raw.decode("utf-8", "replace").strip()
                    if not line:
                        break
                    if ":" in line:
                        k, v = line.split(":", 1)
                        headers[k.strip().lower()] = v.strip()
                try:
                    n = int(headers.get("content-length", 0))
                except ValueError:
                    return
                if n <= 0:
                    continue
                body = await stream.readexactly(n)
                msg = json.loads(body.decode("utf-8"))
                self._dispatch(msg)
        except (asyncio.IncompleteReadError, asyncio.CancelledError):
            return

    def _dispatch(self, msg: dict[str, Any]) -> None:
        has_method = "method" in msg
        if "id" in msg and not has_method:
            fut = self._pending.pop(msg["id"], None)
            if fut and not fut.done():
                if "error" in msg:
                    fut.set_exception(LspError(str(msg["error"])))
                else:
                    fut.set_result(msg.get("result"))
        elif "id" in msg and has_method:
            # server -> client request; we support none, reply null
            self._fire_and_forget({"jsonrpc": "2.0", "id": msg["id"], "result": None})
        # else: notification, ignored

    def _fire_and_forget(self, msg: dict[str, Any]) -> None:
        asyncio.create_task(self._send(msg))

    async def _send(self, msg: dict[str, Any]) -> None:
        assert self._proc and self._proc.stdin
        data = json.dumps(msg).encode("utf-8")
        frame = f"Content-Length: {len(data)}\r\n\r\n".encode() + data
        async with self._write_lock:
            self._proc.stdin.write(frame)
            await self._proc.stdin.drain()

    async def request(self, method: str, params: Any, timeout: float = 120.0) -> Any:
        self._next_id += 1
        rid = self._next_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        await self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise LspError(f"timeout: {method}") from None

    async def notify(self, method: str, params: Any) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    # --- lifecycle ---

    async def initialize(self, root: pathlib.Path, timeout: float = 120.0,
                         options: dict | None = None) -> dict:
        params = {
            "processId": os.getpid(),
            "rootUri": root.as_uri(),
            "workspaceFolders": [{"uri": root.as_uri(), "name": root.name}],
            "capabilities": {
                "textDocument": {
                    "callHierarchy": {"dynamicRegistration": False},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                    "synchronization": {},
                },
                "workspace": {"workspaceFolders": True},
            },
        }
        if options:
            params["initializationOptions"] = options
        result = await self.request("initialize", params, timeout=timeout)
        await self.notify("initialized", {})
        return result or {}

    async def open_file(self, path: pathlib.Path, language_id: str = "plaintext") -> str:
        uri = path.as_uri()
        await self.notify("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": language_id,
                "version": 1,
                "text": path.read_text(encoding="utf-8", errors="replace"),
            }
        })
        return uri
