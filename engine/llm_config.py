"""Multi-provider model profiles.

The UI is a catalogue + profile editor, not a single base_url/key form. Keys live
in separate files (never in the profile JSON, logs or API responses). Model list
and probe failures are data (200 + note/detail), not request validation errors.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import secrets
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .settings import load_settings, mask_key, settings_path

CONFIG_DIR = ".qta"
FORMAT_VERSION = 1
# Sent on every outbound model request: Cloudflare in front of some gateways
# (opencode.ai among them) rejects the bare "Python-urllib/x.y" agent with 403.
USER_AGENT = "Quick-TakeApart/2.1"
# The same gateway wants an x-opencode-session tag on chat calls (400
# MissingSessionID otherwise); one per app run is enough for its routing.
OPENCODE_SESSION = str(uuid.uuid4())
PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
THINK_VALUES = ("", "true", "false")


class LlmConfigError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def config_dir() -> pathlib.Path:
    explicit = os.environ.get("QTA_LLM_DIR")
    if explicit:
        return pathlib.Path(explicit).expanduser()
    return settings_path().parent


def profiles_path() -> pathlib.Path:
    return config_dir() / "llm_profiles.json"


def secrets_dir() -> pathlib.Path:
    return config_dir() / "secrets"


PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "provider_id": "deepseek", "label": "DeepSeek", "kind": "openai",
        "base_url": "https://api.deepseek.com/v1", "needs_key": True,
        "supports_model_list": True, "default_model": "deepseek-flash",
        "key_hint": "在 DeepSeek 控制台创建 API key",
        "known_models": ["deepseek-flash", "deepseek-v4-pro", "deepseek-chat"],
        "context_window": 1_048_576,
    },
    "openai": {
        "provider_id": "openai", "label": "OpenAI", "kind": "openai",
        "base_url": "https://api.openai.com/v1", "needs_key": True,
        "supports_model_list": True, "default_model": "gpt-4.1-mini",
        "key_hint": "在 OpenAI 平台创建 API key",
        "known_models": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
        "context_window": 1_047_576,
    },
    "dashscope": {
        "provider_id": "dashscope", "label": "阿里云 DashScope", "kind": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "needs_key": True, "supports_model_list": True,
        "default_model": "qwen-plus", "key_hint": "在阿里云百炼控制台创建 API key",
        "known_models": ["qwen-plus", "qwen-turbo", "qwen-max"],
        "context_window": 131072,
    },
    "moonshot": {
        "provider_id": "moonshot", "label": "Moonshot", "kind": "openai",
        "base_url": "https://api.moonshot.cn/v1", "needs_key": True,
        "supports_model_list": True, "default_model": "moonshot-v1-8k",
        "key_hint": "在 Moonshot 控制台创建 API key",
        "known_models": ["moonshot-v1-8k", "moonshot-v1-32k"],
        "context_window": 32768,
    },
    "zhipu": {
        "provider_id": "zhipu", "label": "智谱 GLM", "kind": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4", "needs_key": True,
        "supports_model_list": True, "default_model": "glm-4-flash",
        "key_hint": "在智谱开放平台创建 API key",
        "known_models": ["glm-4-flash", "glm-4-plus"],
        "context_window": 131072,
    },
    "siliconflow": {
        "provider_id": "siliconflow", "label": "SiliconFlow", "kind": "openai",
        "base_url": "https://api.siliconflow.cn/v1", "needs_key": True,
        "supports_model_list": True, "default_model": "Qwen/Qwen3-8B",
        "key_hint": "在 SiliconFlow 控制台创建 API key",
        "known_models": ["Qwen/Qwen3-8B", "deepseek-ai/DeepSeek-V3"],
        "context_window": 32768,
    },
    "openrouter": {
        "provider_id": "openrouter", "label": "OpenRouter", "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1", "needs_key": True,
        "supports_model_list": True, "default_model": "openai/gpt-4.1-mini",
        "key_hint": "在 OpenRouter 创建 API key",
        "known_models": ["openai/gpt-4.1-mini", "anthropic/claude-sonnet-4"],
        "context_window": 128000,
    },
    "groq": {
        "provider_id": "groq", "label": "Groq", "kind": "openai",
        "base_url": "https://api.groq.com/openai/v1", "needs_key": True,
        "supports_model_list": True, "default_model": "llama-3.3-70b-versatile",
        "key_hint": "在 Groq 控制台创建 API key",
        "known_models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        "context_window": 131072,
    },
    "ollama": {
        "provider_id": "ollama", "label": "Ollama", "kind": "ollama",
        "base_url": "http://127.0.0.1:11434", "needs_key": False,
        "supports_model_list": True, "default_model": "llama3.2",
        "key_hint": "本地服务，不需要 key",
        "known_models": ["llama3.2", "qwen2.5-coder", "deepseek-r1"],
        "context_window": 8192,
    },
    "lmstudio": {
        "provider_id": "lmstudio", "label": "LM Studio", "kind": "openai",
        "base_url": "http://127.0.0.1:1234/v1", "needs_key": False,
        "supports_model_list": True, "default_model": "local-model",
        "key_hint": "本地服务，不需要 key",
        "known_models": ["local-model"],
        "context_window": 32768,
    },
    "vllm": {
        "provider_id": "vllm", "label": "vLLM", "kind": "openai",
        "base_url": "http://127.0.0.1:8000/v1", "needs_key": False,
        "supports_model_list": True, "default_model": "local-model",
        "key_hint": "本地服务，不需要 key",
        "known_models": ["local-model"],
        "context_window": 32768,
    },
    "anthropic": {
        "provider_id": "anthropic", "label": "Anthropic", "kind": "anthropic",
        "base_url": "https://api.anthropic.com", "needs_key": True,
        "supports_model_list": True, "default_model": "claude-sonnet-4-20250514",
        "key_hint": "在 Anthropic Console 创建 API key",
        "known_models": ["claude-sonnet-4-20250514", "claude-3-5-haiku-latest"],
        "context_window": 200000,
    },
    "custom": {
        "provider_id": "custom", "label": "自定义 OpenAI 兼容", "kind": "openai",
        "base_url": "", "needs_key": True, "supports_model_list": True,
        "default_model": "", "key_hint": "填入任何 OpenAI 兼容服务的 /v1 地址",
        "known_models": [], "context_window": 32768,
    },
}


def providers() -> list[dict]:
    return list(PROVIDERS.values())


def provider(provider_id: str) -> dict:
    if provider_id not in PROVIDERS:
        raise LlmConfigError(
            f"不认识的服务商：'{provider_id}'。可用：{', '.join(PROVIDERS)}。"
            "表里没有的请用 provider_id='custom' 并自己填 base_url。")
    return PROVIDERS[provider_id]


def _empty_store() -> dict:
    return {"version": FORMAT_VERSION, "profiles": []}


def _load_store() -> dict:
    path = profiles_path()
    if not path.is_file():
        return _empty_store()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(raw, dict) or not isinstance(raw.get("profiles"), list):
        return _empty_store()
    return raw


def _save_store(store: dict) -> None:
    path = profiles_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _key_path(profile_id: str) -> pathlib.Path:
    if not PROFILE_ID_RE.match(profile_id):
        raise LlmConfigError(f"profile_id 非法：{profile_id}")
    return secrets_dir() / f"{profile_id}.key"


def _read_key(profile_id: str) -> str:
    path = _key_path(profile_id)
    try:
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    except OSError:
        return ""


def _write_key(profile_id: str, key: str) -> None:
    path = _key_path(profile_id)
    if not key:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _profile_id(store: dict) -> str:
    used = {str(p.get("profile_id")) for p in store["profiles"]}
    for i in range(1, 10000):
        candidate = f"LP-{i:04d}"
        if candidate not in used:
            return candidate
    return f"LP-{secrets.token_hex(4)}"


def _base_url(raw: str, provider_def: dict) -> str:
    value = str(raw or "").strip() or provider_def["base_url"]
    if not value:
        raise LlmConfigError(
            f"{provider_def['label']} 没有默认地址，必须自己填 base_url"
            "（任何 OpenAI 兼容服务，含 /v1）。")
    if not value.startswith(("http://", "https://")):
        raise LlmConfigError(
            f"base_url 必须以 http:// 或 https:// 开头，收到 '{value}'")
    return value.rstrip("/")


def _model(raw: str, provider_def: dict) -> str:
    value = str(raw or "").strip() or provider_def["default_model"]
    if not value:
        raise LlmConfigError("没给模型名，而这家也没有默认值 —— 请填一个模型名。")
    return value


def _models(raw: Any, model: str) -> list[str]:
    values = [str(x).strip() for x in (raw or []) if str(x).strip()] \
        if isinstance(raw, list) else []
    values = [model, *values]
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def _effective_ctx(provider_def: dict, num_ctx: int) -> int:
    return num_ctx if num_ctx > 0 else int(provider_def.get("context_window") or 32768)


def _public(profile: dict, provider_def: dict) -> dict:
    pid = str(profile.get("profile_id"))
    key = _read_key(pid)
    num_ctx = int(profile.get("num_ctx") or 0)
    return {
        "profile_id": pid,
        "label": profile.get("label") or provider_def["label"],
        "provider_id": provider_def["provider_id"],
        "kind": provider_def["kind"],
        "base_url": profile.get("base_url") or provider_def["base_url"],
        "model": profile.get("model") or provider_def["default_model"],
        "models": _models(profile.get("models"), profile.get("model") or provider_def["default_model"]),
        "think": profile.get("think") if profile.get("think") in THINK_VALUES else "",
        "num_ctx": num_ctx,
        "effective_num_ctx": _effective_ctx(provider_def, num_ctx),
        "is_active": bool(profile.get("is_active")),
        "note": str(profile.get("note") or ""),
        "has_key": bool(key),
        "key_masked": mask_key(key) if key else "",
        "created_at": profile.get("created_at") or "",
        "updated_at": profile.get("updated_at") or "",
    }


def _normalize(profile: dict) -> tuple[dict, dict]:
    provider_def = provider(str(profile.get("provider_id") or "custom"))
    base = _base_url(str(profile.get("base_url") or ""), provider_def)
    model = _model(str(profile.get("model") or ""), provider_def)
    num_ctx = int(profile.get("num_ctx") or 0)
    if num_ctx < 0:
        num_ctx = 0
    normalized = {
        **profile,
        "provider_id": provider_def["provider_id"],
        "base_url": base,
        "model": model,
        "models": _models(profile.get("models"), model),
        "think": profile.get("think") if profile.get("think") in THINK_VALUES else "",
        "num_ctx": num_ctx,
        "note": str(profile.get("note") or ""),
        "updated_at": _now(),
    }
    return normalized, provider_def


def list_profiles() -> list[dict]:
    store = _load_store()
    out: list[dict] = []
    for raw in store["profiles"]:
        try:
            normalized, provider_def = _normalize(raw)
        except (LlmConfigError, ValueError):
            continue
        out.append(_public(normalized, provider_def))
    return out


def get_profile(profile_id: str) -> dict | None:
    for profile in list_profiles():
        if profile["profile_id"] == profile_id:
            return profile
    return None


def _find_raw(store: dict, profile_id: str) -> dict | None:
    return next((p for p in store["profiles"]
                 if str(p.get("profile_id")) == profile_id), None)


def create_profile(body: dict) -> dict:
    store = _load_store()
    provider_id = str(body.get("provider_id") or "").strip()
    provider_def = provider(provider_id)
    pid = _profile_id(store)
    raw = {
        "profile_id": pid,
        "label": str(body.get("label") or "").strip(),
        "provider_id": provider_id,
        "base_url": str(body.get("base_url") or "").strip(),
        "model": str(body.get("model") or "").strip(),
        "models": body.get("models") or [],
        "think": str(body.get("think") or ""),
        "num_ctx": body.get("num_ctx") or 0,
        "note": str(body.get("note") or ""),
        "is_active": not any(bool(p.get("is_active")) for p in store["profiles"]),
        "created_at": _now(),
        "updated_at": _now(),
    }
    normalized, provider_def = _normalize(raw)
    _write_key(pid, str(body.get("api_key") or "").strip())
    store["profiles"].append(normalized)
    _save_store(store)
    return _public(normalized, provider_def)


def update_profile(profile_id: str, body: dict) -> dict:
    """True PATCH semantics: only provided fields change."""
    store = _load_store()
    raw = _find_raw(store, profile_id)
    if raw is None:
        raise LlmConfigError(f"没有这份配置：{profile_id}")
    current, provider_def = _normalize(dict(raw))
    for key in ("label", "base_url", "model", "models", "think", "num_ctx", "note"):
        if key in body:
            current[key] = body[key]
    if "api_key" in body:
        key_value = str(body.get("api_key") or "")
        _write_key(profile_id, key_value.strip())
    current["updated_at"] = _now()
    normalized, provider_def = _normalize(current)
    store["profiles"] = [
        normalized if str(p.get("profile_id")) == profile_id else p
        for p in store["profiles"]
    ]
    _save_store(store)
    return _public(normalized, provider_def)


def delete_profile(profile_id: str) -> dict:
    store = _load_store()
    profile = _find_raw(store, profile_id)
    if profile is None:
        raise LlmConfigError(f"没有这份配置：{profile_id}")
    was_active = bool(profile.get("is_active"))
    store["profiles"] = [
        p for p in store["profiles"] if str(p.get("profile_id")) != profile_id
    ]
    if was_active:
        for p in store["profiles"]:
            p["is_active"] = False
        if store["profiles"]:
            store["profiles"][0]["is_active"] = True
    _write_key(profile_id, "")
    _save_store(store)
    active = next((str(p.get("profile_id")) for p in store["profiles"]
                   if p.get("is_active")), None)
    return {"profile_id": profile_id, "active_profile_id": active}


def activate_profile(profile_id: str, model: str | None = None) -> dict:
    store = _load_store()
    raw = _find_raw(store, profile_id)
    if raw is None:
        raise LlmConfigError(f"没有这份配置：{profile_id}")
    current, provider_def = _normalize(dict(raw))
    if model is not None:
        model = str(model).strip()
        if model not in current["models"]:
            raise LlmConfigError("这个模型不在档案里。")
        current["model"] = model
        current["models"] = _models(current["models"], model)
    for p in store["profiles"]:
        p["is_active"] = str(p.get("profile_id")) == profile_id
    current["is_active"] = True
    current["updated_at"] = _now()
    normalized, provider_def = _normalize(current)
    store["profiles"] = [
        normalized if str(p.get("profile_id")) == profile_id else p
        for p in store["profiles"]
    ]
    _save_store(store)
    return _public(normalized, provider_def)


def _env_fallback() -> dict:
    key = (os.environ.get("QTA_API_KEY")
           or os.environ.get("OPENAI_API_KEY")
           or os.environ.get("DEEPSEEK_API_KEY")
           or os.environ.get("ANTHROPIC_API_KEY")
           or "")
    base = os.environ.get("QTA_BASE_URL") or ""
    model = os.environ.get("QTA_MODEL") or ""
    old = load_settings()
    key = key or str(old.get("apiKey") or "")
    base = base or str(old.get("baseUrl") or "")
    model = model or str(old.get("model") or "")
    base = base or "https://api.deepseek.com/v1"
    model = model or "deepseek-flash"
    kind = "anthropic" if "/anthropic" in base else "openai"
    if "11434" in base:
        kind = "ollama"
    return {
        "kind": kind, "base_url": base.rstrip("/"), "model": model,
        "api_key": key, "has_key": bool(key), "source": "env_or_legacy",
    }


def get_active() -> dict:
    store = _load_store()
    raw = next((p for p in store["profiles"] if p.get("is_active")), None)
    if raw is not None:
        try:
            normalized, provider_def = _normalize(dict(raw))
            public = _public(normalized, provider_def)
            return {
                **public,
                "api_key": _read_key(public["profile_id"]),
                "profile_id": public["profile_id"],
                "source": "profile",
            }
        except (LlmConfigError, ValueError):
            pass
    return _env_fallback()


def config_view() -> dict:
    active = get_active()
    public = {k: v for k, v in active.items() if k != "api_key"}
    fallback = _env_fallback()
    return {
        "active": public,
        "fallback": {**{k: v for k, v in fallback.items() if k != "api_key"},
                      "has_key": bool(fallback.get("api_key"))},
        "env_loaded": bool(fallback.get("api_key")),
        "profiles_path": str(profiles_path()),
        "secrets_path": str(secrets_dir()),
    }


def _request_json(url: str, key: str, *, method: str = "GET",
                  payload: dict | None = None, timeout: int = 12) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        # opencode.ai sits behind Cloudflare, which answers 403 (error 1010) to
        # the default "Python-urllib/x.y" agent. Any explicit UA passes.
        "User-Agent": USER_AGENT,
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["x-api-key"] = key
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _model_names(raw: Any) -> list[str]:
    items = raw.get("data") if isinstance(raw, dict) else raw
    if isinstance(items, dict):
        items = items.get("models")
    if not isinstance(items, list):
        items = raw.get("models") if isinstance(raw, dict) else None
    out: list[str] = []
    for item in items or []:
        if isinstance(item, str):
            value = item.strip()
        elif isinstance(item, dict):
            value = str(item.get("id") or item.get("name") or item.get("model") or "").strip()
        else:
            value = ""
        if value and value not in out:
            out.append(value)
    return out


def _openai_models(profile: dict) -> tuple[list[str], str]:
    base = profile["base_url"].rstrip("/")
    urls = [base + "/models"]
    if not base.endswith("/v1") and "/v1/" not in base:
        urls.append(base + "/v1/models")
    errors: list[str] = []
    for url in urls:
        try:
            raw = _request_json(url, _read_key(profile["profile_id"]))
            names = _model_names(raw)
            if names:
                return names, f"从 {url} 拉取"
            errors.append(f"{url}: 响应里没有模型名")
        except (OSError, urllib.error.HTTPError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{url}: {exc}")
    return [], "；".join(errors[-2:]) or "拉不到模型清单"


def _ollama_models(profile: dict) -> tuple[list[str], str]:
    base = profile["base_url"].rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    try:
        raw = _request_json(base + "/api/tags", "", timeout=8)
        names = _model_names(raw)
        # Ollama returns models[].name, which _model_names already handles.
        return names, f"从 {base}/api/tags 拉取"
    except (OSError, urllib.error.HTTPError, ValueError, json.JSONDecodeError) as exc:
        return [], str(exc)


def list_models(profile_id: str) -> dict:
    store = _load_store()
    raw = _find_raw(store, profile_id)
    if raw is None:
        raise LlmConfigError(f"没有这份配置：{profile_id}")
    profile, provider_def = _normalize(dict(raw))
    if not provider_def.get("supports_model_list"):
        return {"profile_id": profile_id, "models": [],
                "note": "这家服务不支持自动拉取清单，请手动填模型名。"}
    if provider_def.get("needs_key") and not _read_key(profile_id):
        return {"profile_id": profile_id, "models": [],
                "note": "还没有保存 API Key，先保存 Key 再拉清单。"}
    if provider_def["kind"] == "ollama":
        models, note = _ollama_models(profile)
    else:
        models, note = _openai_models(profile)
    return {"profile_id": profile_id, "models": models, "note": note}


def _chat(profile: dict, provider_def: dict, message: str = "ping") -> dict:
    key = _read_key(profile["profile_id"])
    base = profile["base_url"].rstrip("/")
    model = profile["model"]
    think = profile.get("think") or ""
    num_ctx = int(profile.get("effective_num_ctx") or 0)
    if provider_def["kind"] == "anthropic":
        payload = {
            "model": model, "max_tokens": 4,
            "messages": [{"role": "user", "content": message}],
        }
        anthropic_base = base if base.endswith("/v1") else base + "/v1"
        raw = _request_json(anthropic_base + "/messages", key, method="POST",
                            payload=payload, timeout=20)
        return {"ok": True, "detail": "可用", "raw": raw}
    if provider_def["kind"] == "ollama":
        payload = {"model": model, "messages": [{"role": "user", "content": message}],
                   "stream": False, "options": {"num_ctx": num_ctx}}
        if think:
            payload["think"] = think == "true"
        raw = _request_json(base + "/api/chat", "", method="POST", payload=payload, timeout=20)
        return {"ok": True, "detail": "可用", "raw": raw}
    payload = {
        "model": model, "max_tokens": 4,
        "messages": [{"role": "user", "content": message}],
        "stream": False,
    }
    raw = _request_json(base + "/chat/completions", key, method="POST", payload=payload, timeout=20)
    return {"ok": True, "detail": "可用", "raw": raw}


def probe(profile_id: str) -> dict:
    store = _load_store()
    raw = _find_raw(store, profile_id)
    if raw is None:
        raise LlmConfigError(f"没有这份配置：{profile_id}")
    profile, provider_def = _normalize(dict(raw))
    listed = list_models(profile_id)
    if profile["model"] in listed["models"]:
        return {"profile_id": profile_id, "ok": True, "detail": "可用"}
    # Model catalog is not authoritative (aliases may be callable). Make a real call.
    try:
        _chat(profile, provider_def)
        return {"profile_id": profile_id, "ok": True, "detail": "可用（模型不在清单里，但实际调用成功）"}
    except (OSError, urllib.error.HTTPError, ValueError, json.JSONDecodeError) as exc:
        return {"profile_id": profile_id, "ok": False, "detail": f"调用失败：{exc}"}


def resolve_active() -> dict:
    active = get_active()
    if not active.get("api_key") and active.get("kind") != "ollama":
        # local OpenAI-compatible servers often ignore keys; leave them usable
        pass
    return active
