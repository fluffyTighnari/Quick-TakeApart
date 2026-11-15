"""Local model API settings.

The UI needs a place to set the endpoint/model/key without editing environment
variables. This module stores a small JSON file under the user's home directory
(or QTA_SETTINGS_PATH for tests) and exposes a masked public view. Keys are never
returned to the browser after saving.
"""

from __future__ import annotations

import json
import os
import pathlib
from datetime import datetime, timezone

DEFAULT_MODEL = "deepseek-flash"
DEFAULT_MODELS = ("deepseek-flash", "deepseek-v4-pro")
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_KEY_ENV = "ANTHROPIC_API_KEY"
SETTINGS_DIR = ".qta"


def settings_path() -> pathlib.Path:
    explicit = os.environ.get("QTA_SETTINGS_PATH")
    if explicit:
        return pathlib.Path(explicit).expanduser()
    return pathlib.Path.home() / SETTINGS_DIR / "settings.json"


def load_settings() -> dict:
    path = settings_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        "apiKey": str(raw.get("apiKey") or ""),
        "baseUrl": str(raw.get("baseUrl") or ""),
        "model": str(raw.get("model") or ""),
        "languageServers": dict(raw.get("languageServers") or {}),
        "updatedAt": str(raw.get("updatedAt") or ""),
    }


def save_settings(values: dict, *, clear_key: bool = False) -> dict:
    current = load_settings()
    api_key = current.get("apiKey") or ""
    if clear_key:
        api_key = ""
    elif str(values.get("apiKey") or "").strip():
        api_key = str(values["apiKey"]).strip()
    base_url = str(current.get("baseUrl") or "").strip()
    model = str(current.get("model") or "").strip()
    if "baseUrl" in values:
        base_url = str(values.get("baseUrl") or "").strip()
    if "model" in values:
        model = str(values.get("model") or "").strip()
    language_servers = dict(current.get("languageServers") or {})
    incoming = values.get("languageServers")
    if isinstance(incoming, dict):
        for key in ("python", "typescript", "go"):
            if key not in incoming:
                continue
            command = str(incoming[key] or "").strip()
            if command:
                language_servers[key] = command
            else:
                language_servers.pop(key, None)
    updated = {
        "apiKey": api_key,
        "baseUrl": base_url,
        "model": model,
        "languageServers": language_servers,
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return public_settings(updated)


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}…{key[-4:]}"


def public_settings(values: dict | None = None) -> dict:
    values = values if values is not None else load_settings()
    key = str(values.get("apiKey") or "")
    env_key = (os.environ.get("QTA_API_KEY")
               or os.environ.get(DEFAULT_KEY_ENV)
               or os.environ.get("DEEPSEEK_API_KEY")
               or "")
    return {
        "baseUrl": values.get("baseUrl") or DEFAULT_BASE_URL,
        "model": values.get("model") or DEFAULT_MODEL,
        "hasKey": bool(key),
        "keyHint": mask_key(key),
        "envKey": bool(env_key),
        "envKeyHint": mask_key(env_key),
        "languageServers": dict(values.get("languageServers") or {}),
        "updatedAt": values.get("updatedAt") or "",
        "settingsPath": str(settings_path()),
    }


def resolve_credentials() -> tuple[str, str, str]:
    """Return (key, base_url, model), UI settings first, env as fallback."""
    values = load_settings()
    key = (values.get("apiKey")
           or os.environ.get("QTA_API_KEY")
           or os.environ.get(DEFAULT_KEY_ENV)
           or os.environ.get("DEEPSEEK_API_KEY")
           or "")
    base = (values.get("baseUrl")
            or os.environ.get("QTA_BASE_URL")
            or DEFAULT_BASE_URL)
    model = (values.get("model")
             or os.environ.get("QTA_MODEL")
             or DEFAULT_MODEL)
    return key, base, model



