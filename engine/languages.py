"""Language adapters for the LSP-backed indexer.

The rest of the app works with the language-neutral Symbol/Edge model. This
module owns the only language-specific knowledge: extensions, LSP commands,
keyword sets and constructor names. A missing language server is reported as
an unavailable language, not silently treated as an empty project.
"""

from __future__ import annotations

import json
import os
import pathlib
import shlex
import shutil
from dataclasses import dataclass, field

from .settings import load_settings, settings_path

APP_ROOT = pathlib.Path(__file__).resolve().parent.parent
PYRIGHT_JS = APP_ROOT / "node_modules" / "pyright" / "langserver.index.js"

SKIP_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    "node_modules", "bower_components", "vendor", "target", "out",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".next",
    ".nuxt", "build", "dist", "site-packages", ".idea", ".vscode",
    "bin", "obj", ".gradle", ".cargo", "coverage",
}

PY_KEYWORDS = (
    "def", "class", "return", "if", "elif", "else", "for", "while", "in",
    "not", "and", "or", "is", "None", "True", "False", "import", "from",
    "as", "with", "try", "except", "finally", "raise", "yield", "lambda",
    "pass", "break", "continue", "global", "nonlocal", "assert", "del",
    "async", "await", "match", "case",
)
TS_KEYWORDS = (
    "const", "let", "var", "function", "return", "if", "else", "for",
    "while", "do", "switch", "case", "default", "class", "interface",
    "type", "enum", "namespace", "import", "from", "export", "extends",
    "implements", "new", "try", "catch", "finally", "throw", "async",
    "await", "yield", "public", "private", "protected", "static",
    "readonly", "as", "in", "of", "instanceof", "typeof", "void", "null",
    "undefined", "true", "false", "this", "super", "break", "continue",
    "abstract", "declare", "keyof", "unknown", "never", "any", "boolean",
    "number", "string", "symbol", "object", "bigint",
)
GO_KEYWORDS = (
    "package", "import", "func", "type", "struct", "interface", "var",
    "const", "return", "if", "else", "for", "range", "go", "defer",
    "chan", "select", "case", "switch", "break", "continue", "fallthrough",
    "map", "make", "new", "nil", "true", "false", "iota", "default",
    "package", "using", "try", "catch", "finally", "throw",
)


@dataclass(frozen=True)
class LanguageSpec:
    id: str
    label: str
    extensions: tuple[str, ...]
    language_id: str
    command: tuple[str, ...] | None
    initialization_options: dict = field(default_factory=dict)
    constructor_names: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    source: str = "auto"

    @property
    def available(self) -> bool:
        if not self.command:
            return False
        executable = self.command[0]
        if pathlib.Path(executable).is_absolute():
            if not pathlib.Path(executable).exists():
                return False
        elif shutil.which(executable) is None:
            return False
        # Python's command is `node <pyright-langserver.js>`; check the JS file too.
        for part in self.command[1:]:
            if (part.endswith(".js") or part.lower().endswith((".cmd", ".exe"))) \
                    and pathlib.Path(part).is_absolute() \
                    and not pathlib.Path(part).exists():
                return False
        return True

    @property
    def command_label(self) -> str:
        return " ".join(self.command) if self.command else ""


def _override(name: str) -> tuple[str, ...] | None:
    env = {
        "python": "QTA_PYRIGHT",
        "typescript": "QTA_TYPESCRIPT_SERVER",
        "go": "QTA_GOPLS",
    }.get(name)
    raw = os.environ.get(env, "") if env else ""
    if not raw:
        values = load_settings()
        raw = str((values.get("languageServers") or {}).get(name) or "")
    if not raw:
        return None
    try:
        return tuple(shlex.split(raw, posix=os.name != "nt"))
    except ValueError:
        return None


def _resolved_command(name: str, args: tuple[str, ...]) -> tuple[str, ...] | None:
    path = shutil.which(name)
    if not path:
        return None
    if os.name == "nt" and path.lower().endswith((".cmd", ".bat")):
        # CreateProcess does not run .cmd shims directly.
        return ("cmd", "/c", path, *args)
    return (path, *args)


def _python_spec() -> LanguageSpec:
    override = _override("python")
    if override:
        command, source = override, "config"
    elif PYRIGHT_JS.exists():
        command, source = ("node", str(PYRIGHT_JS), "--stdio"), "bundled"
    elif shutil.which("pyright-langserver"):
        command, source = ("pyright-langserver", "--stdio"), "path"
    else:
        command, source = None, "missing"
    return LanguageSpec(
        id="python", label="Python", extensions=(".py", ".pyi"),
        language_id="python", command=command, source=source,
        constructor_names=("__init__",), keywords=PY_KEYWORDS,
    )


def _typescript_tsserver() -> pathlib.Path | None:
    candidates = [
        APP_ROOT / "web" / "node_modules" / "typescript" / "lib" / "tsserver.js",
        APP_ROOT / "node_modules" / "typescript" / "lib" / "tsserver.js",
        pathlib.Path.home() / "AppData" / "Roaming" / "npm" / "node_modules"
        / "typescript" / "lib" / "tsserver.js",
        pathlib.Path("/usr/local/lib/node_modules/typescript/lib/tsserver.js"),
        pathlib.Path("/usr/lib/node_modules/typescript/lib/tsserver.js"),
    ]
    tsc = shutil.which("tsc")
    if tsc:
        candidates.append(pathlib.Path(tsc).parent / "node_modules"
                          / "typescript" / "lib" / "tsserver.js")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _typescript_spec() -> LanguageSpec:
    override = _override("typescript")
    if override:
        command, source = override, "config"
    else:
        command = _resolved_command("typescript-language-server", ("--stdio",))
        source = "path" if command else "missing"
    options = {"hostInfo": "quick-take-apart"}
    tsserver = _typescript_tsserver()
    if tsserver is not None:
        options["tsserver"] = {"path": str(tsserver)}
    return LanguageSpec(
        id="typescript", label="TypeScript / JavaScript",
        extensions=(".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"),
        language_id="typescript", command=command, source=source,
        constructor_names=("constructor",), keywords=TS_KEYWORDS,
        initialization_options=options,
    )


def _go_spec() -> LanguageSpec:
    override = _override("go")
    if override:
        command, source = override, "config"
    else:
        command = _resolved_command("gopls", ("serve",))
        source = "path" if command else "missing"
    return LanguageSpec(
        id="go", label="Go", extensions=(".go",), language_id="go",
        command=command, source=source, keywords=GO_KEYWORDS,
    )


def language_specs() -> list[LanguageSpec]:
    return [_python_spec(), _typescript_spec(), _go_spec()]


def spec_for_path(path: str) -> LanguageSpec | None:
    suffix = pathlib.PurePath(path).suffix.lower()
    for spec in language_specs():
        if suffix in spec.extensions:
            return spec
    return None


def discover_files(root: pathlib.Path, spec: LanguageSpec,
                   limit: int = 6000) -> list[pathlib.Path]:
    out: list[pathlib.Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in spec.extensions:
            continue
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in SKIP_DIRS for part in parts):
            continue
        out.append(path)
        if len(out) >= limit:
            break
    return sorted(out)


def language_status(root: pathlib.Path | None) -> list[dict]:
    out: list[dict] = []
    for spec in language_specs():
        files = discover_files(root, spec) if root else []
        out.append({
            "id": spec.id,
            "label": spec.label,
            "extensions": list(spec.extensions),
            "files": len(files),
            "available": spec.available,
            "command": spec.command_label,
            "source": spec.source,
        })
    return out


def supported_extensions() -> set[str]:
    return {ext for spec in language_specs() for ext in spec.extensions}
