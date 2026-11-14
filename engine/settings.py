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
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_MODEL = "deepseek-v4.1-flash"
DEFAULT_MODELS = ("deepseek-v4.1-flash", "deepseek-flash", "deepseek-v4-pro")
DEFAULT_BASE_URL = "https://api.deepseek.com/anthropic"
DEFAULT_KEY_ENV = "ANTHROPIC_API_KEY"
SETTINGS_DIR = ".qta"


class SettingsError(RuntimeError):
    pass


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
        "updatedAt": str(raw.get("updatedAt") or ""),
    }


def save_settings(values: dict, *, clear_key: bool = False) -> dict:
    current = load_settings()
    api_key = current.get("apiKey") or ""
    if clear_key:
        api_key = ""
    elif str(values.get("apiKey") or "").strip():
        api_key = str(values["apiKey"]).strip()
    base_url = str(values.get("baseUrl") or "").strip()
    model = str(values.get("model") or "").strip()
    updated = {
        "apiKey": api_key,
        "baseUrl": base_url,
        "model": model,
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


def _model_urls(base_url: str) -> list[str]:
    base = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    urls: list[str] = []
    if base.endswith("/anthropic"):
        urls.append(base[:-len("/anthropic")] + "/models")
    urls.append(base + "/models")
    if not base.endswith("/v1"):
        urls.append(base + "/v1/models")
    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


def fetch_models(base_url: str, api_key: str) -> list[str]:
    """Ask an OpenAI-compatible /models endpoint for model ids.

    Anthropic-style base URLs (for example .../anthropic) are also handled by
    trying the sibling /models path. The endpoint is allowed to be custom; a
    failure is reported as a readable settings error, not a crash.
    """
    if not api_key:
        raise SettingsError("no API key: enter a key or configure one in the environment")
    errors: list[str] = []
    for url in _model_urls(base_url):
        request = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {api_key}",
            "x-api-key": api_key,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                raw = json.loads(response.read().decode("utf-8", "replace"))
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
            errors.append(f"{url}: {exc}")
            continue
        items = raw.get("data") if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            items = raw.get("models") if isinstance(raw, dict) else None
        models: list[str] = []
        for item in items or []:
            if isinstance(item, str):
                model = item.strip()
            elif isinstance(item, dict):
                model = str(item.get("id") or item.get("name") or "").strip()
            else:
                model = ""
            if model and model not in models:
                models.append(model)
        if models:
            return models
        errors.append(f"{url}: no model ids in response")
    raise SettingsError("; ".join(errors[-3:]) or "model catalog unavailable")
