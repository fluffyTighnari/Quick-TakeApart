"""Path normalization and a small server-side directory browser.

The browser cannot hand a local filesystem path to the server, so the entry
screen needs a server-side way to browse directories. This module keeps that
logic in one place and makes the manual path input forgiving: quoted paths,
``file://`` URIs, duplicated separators, environment variables and relative
paths all normalize to one real directory.
"""

from __future__ import annotations

import os
import pathlib
import re
import string
import urllib.parse

BROWSE_SKIP = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "site-packages", ".mypy_cache", ".pytest_cache",
    ".idea", ".vscode", ".tox", ".next", ".nuxt", ".qta",
}

PROJECT_MARKERS = (
    ".git", "pyproject.toml", "requirements.txt", "setup.py", "setup.cfg",
    "Pipfile", "poetry.lock", "package.json", "pnpm-workspace.yaml",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "build.gradle.kts",
    "composer.json", "Gemfile", "mix.exs", ".sln",
)


class PathError(ValueError):
    pass


def _strip_quotes(text: str) -> str:
    text = text.strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        text = text[1:-1].strip()
    return text


def normalize_path(raw: str | pathlib.Path) -> pathlib.Path:
    """Turn user input into a resolved path without guessing too much."""
    text = _strip_quotes(str(raw or ""))
    if not text:
        raise PathError("路径为空")

    if text.lower().startswith("file://"):
        parsed = urllib.parse.urlsplit(text)
        text = urllib.parse.unquote(parsed.path)
        if parsed.netloc and parsed.netloc not in ("", "localhost"):
            text = f"//{parsed.netloc}{text}"
        elif os.name == "nt" and text.startswith("/") and len(text) > 2 and text[2] == ":":
            text = text[1:]

    text = _strip_quotes(os.path.expandvars(os.path.expanduser(text)))
    if not text:
        raise PathError("路径为空")

    # Windows drive-relative "D:foo" is not what people mean when they paste it.
    if os.name == "nt" and re.match(r"^[A-Za-z]:[^\\/]", text):
        text = text[:2] + "\\" + text[2:]

    if os.name == "nt":
        if text.startswith("\\\\?\\") or text.startswith("\\\\.\\"):
            prefix, rest = text[:4], text[4:]
            text = prefix + re.sub(r"[\\/]+", lambda _: "\\", rest)
        elif text.startswith("\\\\"):
            text = "\\\\" + re.sub(r"[\\/]+", lambda _: "\\", text[2:])
        else:
            text = re.sub(r"[\\/]+", lambda _: "\\", text)
    else:
        text = re.sub(r"/+", "/", text)

    path = pathlib.Path(text)
    if not path.is_absolute():
        path = pathlib.Path.cwd() / path
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def looks_like_project(path: pathlib.Path) -> bool:
    try:
        if any((path / marker).exists() for marker in PROJECT_MARKERS):
            return True
        return next(path.glob("*.py"), None) is not None
    except OSError:
        return False


def root_locations() -> list[dict]:
    out: list[dict] = []

    def add(path: pathlib.Path, label: str, kind: str) -> None:
        try:
            value = str(path.resolve())
        except OSError:
            value = str(path)
        if not any(item["path"].lower() == value.lower() for item in out):
            out.append({"path": value, "label": label, "kind": kind})

    add(pathlib.Path.home(), "用户目录", "home")
    add(pathlib.Path.cwd(), "当前目录", "cwd")

    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = pathlib.Path(f"{letter}:\\")
            try:
                if drive.exists():
                    add(drive, f"{letter}: 盘", "drive")
            except OSError:
                continue
    else:
        add(pathlib.Path("/"), "根目录", "root")
    return out


def browse_directories(raw: str | None = None) -> dict:
    if raw:
        path = normalize_path(raw)
    else:
        path = pathlib.Path.home()
    try:
        if path.is_file():
            path = path.parent
        if not path.exists():
            raise PathError(f"目录不存在：{path}")
        if not path.is_dir():
            raise PathError(f"不是目录：{path}")
    except OSError as exc:
        raise PathError(str(exc)) from exc

    entries: list[dict] = []
    try:
        children = list(path.iterdir())
    except OSError as exc:
        raise PathError(f"无法读取目录：{exc}") from exc

    for child in children:
        try:
            if not child.is_dir():
                continue
        except OSError:
            continue
        name = child.name
        if name in BROWSE_SKIP:
            continue
        if name.startswith(".") and name not in (".", ".."):
            # keep hidden dirs selectable but quiet; skip known noise above
            pass
        entries.append({
            "name": name,
            "path": str(child),
            "hidden": name.startswith("."),
            "project": looks_like_project(child),
        })

    entries.sort(key=lambda e: (e["project"] is False, e["hidden"], e["name"].lower()))
    parent = path.parent
    return {
        "path": str(path),
        "parent": str(parent) if parent != path else None,
        "entries": entries,
        "roots": root_locations(),
        "home": str(pathlib.Path.home()),
        "cwd": str(pathlib.Path.cwd()),
    }
