"""Build a Symbol/Edge index for a Python project via pyright's LSP."""

from __future__ import annotations

import asyncio
import hashlib
import pathlib
import sys
import urllib.parse

from .lsp import LspClient, LspError
from .model import Edge, Index, Range, Symbol, SymbolKind

SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "build", "dist",
    "site-packages", ".tox", ".idea", ".vscode",
}

LSP_KIND = {5: "class", 6: "method", 12: "function"}


def discover_py_files(root: pathlib.Path, limit: int = 3000) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        out.append(p)
        if len(out) >= limit:
            break
    return sorted(out)


def revision_of(files: list[pathlib.Path], root: pathlib.Path) -> str:
    h = hashlib.sha256()
    for f in files:
        try:
            st = f.stat()
        except OSError:
            continue
        h.update(f"{f.relative_to(root)}:{st.st_size}:{int(st.st_mtime)}\n".encode())
    return h.hexdigest()[:16]


def _rel(path: pathlib.Path, root: pathlib.Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def uri_key(uri: str) -> str:
    """Normalize a file:// URI for lookup.

    Two traps on Windows: pyright percent-encodes the drive colon
    (``file:///d%3A/...``) while pathlib emits a raw colon, and paths are
    case-insensitive but string comparison is not.
    """
    parsed = urllib.parse.urlsplit(uri)
    path = urllib.parse.unquote(parsed.path)
    return f"{parsed.scheme}://{parsed.netloc}{path}".casefold()


def _lines_of(text: str) -> list[str]:
    return text.splitlines()


def _signature_at(lines: list[str], r: Range) -> str:
    """Return the def/class header line, collapsed to one line."""
    if not lines or r.start_line >= len(lines):
        return ""
    for i in range(r.start_line, min(r.start_line + 4, len(lines))):
        s = lines[i].strip()
        if s.startswith(("def ", "async def ", "class ")):
            # join a multi-line signature
            buf = s
            j = i
            while not buf.rstrip().endswith(":") and j + 1 < len(lines) and j - i < 8:
                j += 1
                buf += " " + lines[j].strip()
            return " ".join(buf.split())
    return lines[r.start_line].strip()


async def _request_retry(lsp: LspClient, method: str, params: dict,
                         timeout: float, attempts: int = 3) -> Any | None:
    """pyright occasionally stalls when several callHierarchy requests race at startup."""
    for i in range(attempts):
        try:
            return await lsp.request(method, params, timeout=timeout)
        except LspError:
            if i == attempts - 1:
                return None
            await asyncio.sleep(0.4 * (i + 1))
        except Exception:
            return None
    return None


async def build_index(
    root: pathlib.Path,
    pyright_bin: pathlib.Path,
    *,
    max_call_hierarchy: int = 400,
    concurrency: int = 3,
    progress=None,
) -> Index:
    root = root.resolve()
    files = discover_py_files(root)
    if not files:
        return Index(root=str(root), revision="empty")

    idx = Index(root=str(root), revision=revision_of(files, root))
    file_uri_to_rel: dict[str, str] = {}
    file_rel_to_uri: dict[str, str] = {}
    file_texts: dict[str, str] = {}

    async with LspClient(["node", str(pyright_bin), "--stdio"], root) as lsp:
        await lsp.initialize(root)

        for f in files:
            try:
                uri = await lsp.open_file(f)
            except Exception:
                continue
            rel = _rel(f, root)
            file_uri_to_rel[uri_key(uri)] = rel
            file_rel_to_uri[rel] = uri
            file_texts[rel] = f.read_text(encoding="utf-8", errors="replace")

        if progress:
            progress(f"opened {len(file_uri_to_rel)} files")

        async def symbols_for(rel: str, uri: str) -> None:
            res = await _request_retry(lsp, "textDocument/documentSymbol",
                                       {"textDocument": {"uri": uri}}, timeout=60)
            if res is None:
                return
            lines = _lines_of(file_texts[rel])
            for qual, kind_lsp, sel, body in _flatten_symbols(res, uri):
                kind = LSP_KIND.get(kind_lsp)
                if kind is None:
                    continue
                idx.symbols[f"{rel}::{qual}"] = Symbol(
                    id=f"{rel}::{qual}", name=qual.rsplit(".", 1)[-1], qualname=qual,
                    relpath=rel, kind=kind, range=sel, body_range=body,
                    signature=_signature_at(lines, sel),
                )

        await asyncio.gather(*(symbols_for(file_uri_to_rel[u], u) for u in file_uri_to_rel))

        if progress:
            progress(f"symbols: {len(idx.symbols)}")

        targets = sorted(idx.callable_symbols(), key=lambda s: s.range.start_line)[:max_call_hierarchy]
        sem = asyncio.Semaphore(concurrency)
        done = 0
        lock = asyncio.Lock()

        async def edges_for(sym: Symbol) -> None:
            nonlocal done
            uri = file_rel_to_uri[sym.relpath]
            async with sem:
                prep = await _request_retry(lsp, "textDocument/prepareCallHierarchy", {
                    "textDocument": {"uri": uri},
                    "position": {"line": sym.range.start_line, "character": sym.range.start_char},
                }, timeout=45)
                if not prep:
                    return
                out = await _request_retry(lsp, "callHierarchy/outgoingCalls",
                                           {"item": prep[0]}, timeout=45)
                if out is None:
                    return

            local: list[Edge] = []
            unresolved: list[tuple[str, str, Range]] = []
            for call in out or []:
                tgt = call["to"]
                tgt_rel = file_uri_to_rel.get(uri_key(tgt["uri"]))
                sel = (tgt.get("selectionRange") or tgt["range"])
                tgt_rng = Range.from_lsp(sel)
                site = Range.from_lsp(call["fromRanges"][0]) if call.get("fromRanges") else sym.range

                if tgt_rel is None:
                    unresolved.append((sym.id, tgt["name"], site))
                    continue
                match = _find_symbol_at(idx.symbols, tgt_rel, tgt_rng)
                if match is None:
                    unresolved.append((sym.id, tgt["name"], site))
                    continue
                local.append(Edge(
                    caller_id=sym.id,
                    callee_id=match,
                    site=site,
                    kind="intra" if match.split("::")[0] == sym.relpath else "cross",
                ))

            async with lock:
                idx.edges.extend(local)
                idx.unresolved_calls.extend(unresolved)
                done += 1
                if progress and done % 25 == 0:
                    progress(f"call hierarchy {done}/{len(targets)}")

        await asyncio.gather(*(edges_for(s) for s in targets))

    # dedupe edges by (caller, callee, site line)
    seen: set[tuple[str, str, int]] = set()
    uniq: list[Edge] = []
    for e in idx.edges:
        if e.key in seen:
            continue
        seen.add(e.key)
        uniq.append(e)
    idx.edges = uniq

    # drop edges to symbols that are not in our file set
    idx.edges = [e for e in idx.edges if e.callee_id in idx.symbols and e.caller_id in idx.symbols]
    idx.edges = _resolve_constructor_edges(idx)
    return idx


def _resolve_constructor_edges(idx: Index) -> list[Edge]:
    """Point class-instantiation edges at the class's __init__.

    pyright reports ``Foo()`` as a call to the class symbol, which leaves
    constructors looking uncalled and floating at the top layer. At runtime
    instantiation *is* a call to __init__, so make the graph say what happens.
    """
    init_by_class: dict[str, str] = {}
    for sid, sym in idx.symbols.items():
        if sym.kind == "method" and sym.name == "__init__":
            rel, _, qual = sid.partition("::")
            owner = qual.rsplit(".", 1)[0] if "." in qual else ""
            if owner:
                init_by_class[f"{rel}::{owner}"] = sid

    out: list[Edge] = []
    for e in idx.edges:
        target = init_by_class.get(e.callee_id, e.callee_id)
        out.append(Edge(e.caller_id, target, e.site, e.kind) if target != e.callee_id else e)
    return out


def _flatten_symbols(items: list, uri: str) -> list[tuple[str, int, Range, Range]]:
    """Yield (qualname, lsp_kind, identifier_range, body_range)."""
    out: list[tuple[str, int, Range, Range]] = []

    def walk(nodes: list, prefix: list[str]) -> None:
        for it in nodes:
            if "location" in it and "range" not in it:
                loc = it["location"]
                rng = Range.from_lsp(loc["range"])
                out.append((it["name"], it["kind"], rng, rng))
                continue
            sel = Range.from_lsp(it.get("selectionRange") or it["range"])
            body = Range.from_lsp(it["range"])
            qual = ".".join([*prefix, it["name"]])
            out.append((qual, it["kind"], sel, body))
            children = it.get("children") or []
            nested = it["kind"] == 5  # class
            walk(children, [*prefix, it["name"]] if nested else prefix)

    walk(items, [])
    return out


def _find_symbol_at(symbols: dict[str, Symbol], relpath: str, rng: Range) -> str | None:
    for sid, s in symbols.items():
        if s.relpath != relpath:
            continue
        if (s.range.start_line, s.range.start_char) == (rng.start_line, rng.start_char):
            return sid
    return None
