"""Build a language-neutral Symbol/Edge index through LSP servers.

Python is the original adapter and remains bundled. Additional languages are
declared in engine/languages.py; this module knows nothing language-specific
beyond the LSP shape returned by documentSymbol/callHierarchy.
"""

from __future__ import annotations

import asyncio
import hashlib
import pathlib
import urllib.parse
from typing import Any

from .languages import LanguageSpec, discover_files, language_specs
from .lsp import LspClient, LspError
from .model import Edge, Index, Range, Symbol, SymbolKind

LSP_KIND: dict[int, SymbolKind] = {
    5: "class",      # class
    6: "method",
    9: "method",     # constructor
    10: "class",     # enum
    11: "class",     # interface
    12: "function",
    23: "class",     # struct
}
NESTED_KINDS = {5, 10, 11, 23}


def _python_spec(pyright_bin: pathlib.Path | None = None) -> LanguageSpec:
    command = (("node", str(pyright_bin), "--stdio")
               if pyright_bin is not None else None)
    return LanguageSpec(
        id="python", label="Python", extensions=(".py", ".pyi"),
        language_id="python", command=command,
        constructor_names=("__init__",),
        keywords=(),
    )


def discover_py_files(root: pathlib.Path, limit: int = 3000) -> list[pathlib.Path]:
    """Backward-compatible Python-only discovery helper."""
    return discover_files(root, _python_spec(), limit)


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
    """Normalize a file:// URI for lookup."""
    parsed = urllib.parse.urlsplit(uri)
    path = urllib.parse.unquote(parsed.path)
    return f"{parsed.scheme}://{parsed.netloc}{path}".casefold()


def _lines_of(text: str) -> list[str]:
    return text.splitlines()


def _signature_at(lines: list[str], r: Range, spec: LanguageSpec) -> str:
    if not lines or r.start_line >= len(lines):
        return ""
    if spec.id == "python":
        for i in range(r.start_line, min(r.start_line + 4, len(lines))):
            s = lines[i].strip()
            if s.startswith(("def ", "async def ", "class ")):
                buf = s
                j = i
                while not buf.rstrip().endswith(":") and j + 1 < len(lines) and j - i < 8:
                    j += 1
                    buf += " " + lines[j].strip()
                return " ".join(buf.split())
    for i in range(r.start_line, min(r.start_line + 3, len(lines))):
        s = lines[i].strip()
        if s:
            return " ".join(s.split())
    return ""


async def _request_retry(lsp: LspClient, method: str, params: dict,
                         timeout: float, attempts: int = 3) -> Any | None:
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


async def _index_language(root: pathlib.Path, spec: LanguageSpec,
                          files: list[pathlib.Path], idx: Index,
                          max_call_hierarchy: int, concurrency: int,
                          progress=None) -> None:
    if not spec.available or not spec.command or not files:
        return
    file_uri_to_rel: dict[str, str] = {}
    file_rel_to_uri: dict[str, str] = {}
    file_texts: dict[str, str] = {}
    try:
        async with LspClient(list(spec.command), root) as lsp:
            await lsp.initialize(root, options=spec.initialization_options)
            for f in files:
                try:
                    uri = await lsp.open_file(f, spec.language_id)
                except Exception:
                    continue
                rel = _rel(f, root)
                file_uri_to_rel[uri_key(uri)] = rel
                file_rel_to_uri[rel] = uri
                file_texts[rel] = f.read_text(encoding="utf-8", errors="replace")

            if progress:
                progress(f"{spec.id}: opened {len(file_uri_to_rel)} files")

            async def symbols_for(rel: str, uri: str) -> None:
                res = None
                # TypeScript's tsserver can briefly return [] while the project
                # is still loading. Retry an empty answer instead of caching an
                # empty file.
                for attempt in range(4):
                    res = await _request_retry(
                        lsp, "textDocument/documentSymbol",
                        {"textDocument": {"uri": uri}}, timeout=60)
                    if res:
                        break
                    await asyncio.sleep(0.35 * (attempt + 1))
                if res is None:
                    return
                lines = _lines_of(file_texts[rel])
                for qual, kind_lsp, sel, body in _flatten_symbols(res, uri):
                    kind = LSP_KIND.get(kind_lsp)
                    if kind is None:
                        continue
                    idx.symbols[f"{rel}::{qual}"] = Symbol(
                        id=f"{rel}::{qual}", name=qual.rsplit(".", 1)[-1],
                        qualname=qual, relpath=rel, kind=kind,
                        range=sel, body_range=body,
                        signature=_signature_at(lines, sel, spec),
                    )

            # Use the original URI case; documentSymbol in some servers (ts)
            # treats the lower-cased lookup key as a different file.
            await asyncio.gather(
                *(symbols_for(rel, uri) for rel, uri in file_rel_to_uri.items()))

            if progress:
                progress(f"{spec.id}: symbols {len(idx.symbols)}")

            local_ids = set(file_rel_to_uri)
            targets = sorted(
                (s for s in idx.callable_symbols() if s.relpath in local_ids),
                key=lambda s: s.range.start_line,
            )[:max_call_hierarchy]
            sem = asyncio.Semaphore(concurrency)
            lock = asyncio.Lock()
            done = 0

            async def edges_for(sym: Symbol) -> None:
                nonlocal done
                uri = file_rel_to_uri[sym.relpath]
                async with sem:
                    prep = await _request_retry(
                        lsp, "textDocument/prepareCallHierarchy", {
                            "textDocument": {"uri": uri},
                            "position": {"line": sym.range.start_line,
                                         "character": sym.range.start_char},
                        }, timeout=45)
                    if not prep:
                        return
                    out = await _request_retry(
                        lsp, "callHierarchy/outgoingCalls",
                        {"item": prep[0]}, timeout=45)
                    if out is None:
                        return

                local: list[Edge] = []
                unresolved: list[tuple[str, str, Range]] = []
                for call in out or []:
                    tgt = call.get("to") or {}
                    tgt_rel = file_uri_to_rel.get(uri_key(tgt.get("uri", "")))
                    sel = (tgt.get("selectionRange") or tgt.get("range") or {})
                    if not sel:
                        continue
                    tgt_rng = Range.from_lsp(sel)
                    from_ranges = call.get("fromRanges") or []
                    site = (Range.from_lsp(from_ranges[0])
                            if from_ranges else sym.range)
                    if tgt_rel is None:
                        unresolved.append((sym.id, str(tgt.get("name") or ""), site))
                        continue
                    match = _find_symbol_at(idx.symbols, tgt_rel, tgt_rng)
                    if match is None:
                        unresolved.append((sym.id, str(tgt.get("name") or ""), site))
                        continue
                    local.append(Edge(
                        caller_id=sym.id, callee_id=match, site=site,
                        kind=("intra" if match.split("::")[0] == sym.relpath
                              else "cross"),
                    ))
                async with lock:
                    idx.edges.extend(local)
                    idx.unresolved_calls.extend(unresolved)
                    done += 1
                    if progress and done % 25 == 0:
                        progress(f"{spec.id}: call hierarchy {done}/{len(targets)}")

            await asyncio.gather(*(edges_for(s) for s in targets))
            _resolve_constructor_edges(idx, spec)
    except (LspError, OSError):
        if progress:
            progress(f"{spec.id}: language server unavailable")


async def build_index(
    root: pathlib.Path,
    pyright_bin: pathlib.Path | None = None,
    *,
    max_call_hierarchy: int = 400,
    concurrency: int = 3,
    progress=None,
    specs: list[LanguageSpec] | None = None,
) -> Index:
    root = root.resolve()
    if specs is None:
        specs = ([_python_spec(pyright_bin)] if pyright_bin is not None
                 else language_specs())

    file_sets: list[tuple[LanguageSpec, list[pathlib.Path]]] = []
    all_files: list[pathlib.Path] = []
    seen: set[pathlib.Path] = set()
    for spec in specs:
        files = discover_files(root, spec)
        file_sets.append((spec, files))
        for file in files:
            if file not in seen:
                seen.add(file)
                all_files.append(file)
    all_files.sort()
    if not all_files:
        return Index(root=str(root), revision="empty", files=[])

    rel_files = sorted({_rel(f, root) for f in all_files})
    idx = Index(root=str(root), revision=revision_of(all_files, root),
                files=rel_files)
    for spec, files in file_sets:
        await _index_language(root, spec, files, idx, max_call_hierarchy,
                              concurrency, progress)

    # dedupe edges by (caller, callee, site line)
    seen_edges: set[tuple[str, str, int]] = set()
    uniq: list[Edge] = []
    for e in idx.edges:
        if e.key in seen_edges:
            continue
        seen_edges.add(e.key)
        uniq.append(e)
    idx.edges = uniq

    # drop edges to symbols that are not in our file set
    idx.edges = [e for e in idx.edges
                 if e.callee_id in idx.symbols and e.caller_id in idx.symbols]
    return idx


def _resolve_constructor_edges(idx: Index, spec: LanguageSpec) -> list[Edge]:
    """Point class-instantiation edges at the class constructor.

    Python uses __init__, TypeScript uses constructor; Go has no constructor
    edge convention. Language-specific names live in LanguageSpec, not here.
    """
    if not spec.constructor_names:
        return idx.edges
    init_by_class: dict[str, str] = {}
    for sid, sym in idx.symbols.items():
        if sym.kind == "method" and sym.name in spec.constructor_names:
            rel, _, qual = sid.partition("::")
            owner = qual.rsplit(".", 1)[0] if "." in qual else ""
            if owner:
                init_by_class[f"{rel}::{owner}"] = sid

    out: list[Edge] = []
    for e in idx.edges:
        target = init_by_class.get(e.callee_id, e.callee_id)
        out.append(Edge(e.caller_id, target, e.site, e.kind)
                   if target != e.callee_id else e)
    idx.edges = out
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
            nested = it["kind"] in NESTED_KINDS
            walk(children, [*prefix, it["name"]] if nested else prefix)

    walk(items, [])
    return out


def _find_symbol_at(symbols: dict[str, Symbol], relpath: str,
                    rng: Range) -> str | None:
    for sid, s in symbols.items():
        if s.relpath != relpath:
            continue
        if (s.range.start_line, s.range.start_char) == (rng.start_line, rng.start_char):
            return sid
    return None
