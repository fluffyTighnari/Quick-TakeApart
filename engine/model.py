"""Core data model. IDs are content-stable: revision + qualname, never raw line numbers."""

from __future__ import annotations

import dataclasses
from typing import Literal

SymbolKind = Literal["function", "method", "class", "module"]
EdgeKind = Literal["intra", "cross", "external"]


@dataclasses.dataclass(frozen=True, slots=True)
class Range:
    start_line: int
    start_char: int
    end_line: int
    end_char: int

    def to_lsp(self) -> dict:
        return {
            "start": {"line": self.start_line, "character": self.start_char},
            "end": {"line": self.end_line, "character": self.end_char},
        }

    @classmethod
    def from_lsp(cls, d: dict) -> "Range":
        return cls(
            d["start"]["line"], d["start"]["character"],
            d["end"]["line"], d["end"]["character"],
        )

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


@dataclasses.dataclass(frozen=True, slots=True)
class Symbol:
    """A definition. `id` = '<relpath>::<qualname>' — stable across edits."""

    id: str
    name: str
    qualname: str
    relpath: str
    kind: SymbolKind
    range: Range          # the identifier range (LSP selectionRange); used to address the symbol
    body_range: Range     # whole definition including body; used to check anchors
    signature: str = ""

    @property
    def is_callable(self) -> bool:
        return self.kind in ("function", "method")


@dataclasses.dataclass(frozen=True, slots=True)
class Edge:
    """A resolved call site. Every edge must point at a real Symbol id."""

    caller_id: str
    callee_id: str
    site: Range
    kind: EdgeKind

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.caller_id, self.callee_id, self.site.start_line)


@dataclasses.dataclass
class Index:
    root: str
    revision: str
    symbols: dict[str, Symbol] = dataclasses.field(default_factory=dict)
    edges: list[Edge] = dataclasses.field(default_factory=list)
    # symbols pyright could not resolve; kept so the UI can say "unknown" instead of guessing
    unresolved_calls: list[tuple[str, str, Range]] = dataclasses.field(default_factory=list)

    def outgoing(self, symbol_id: str) -> list[Edge]:
        return [e for e in self.edges if e.caller_id == symbol_id]

    def incoming(self, symbol_id: str) -> list[Edge]:
        return [e for e in self.edges if e.callee_id == symbol_id]

    def callable_symbols(self) -> list[Symbol]:
        return [s for s in self.symbols.values() if s.is_callable]
