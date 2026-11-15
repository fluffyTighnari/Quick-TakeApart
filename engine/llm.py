"""One model call adapter for both Anthropic and OpenAI/Ollama protocols.

Stage modules no longer own credential/bootstrap code. The active model profile
decides protocol, endpoint, key, thinking and context budget; callers only pass
a tool schema and text.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

from .llm_config import resolve_active


class LlmError(RuntimeError):
    pass


def credentials() -> tuple[str, str, str]:
    cfg = resolve_active()
    key = str(cfg.get("api_key") or "")
    if not key and cfg.get("kind") not in ("ollama", "openai"):
        raise LlmError("no API key: open model settings and configure a profile")
    return key, str(cfg.get("base_url") or ""), str(cfg.get("model") or "")


def _tool_input(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict) and isinstance(raw.get("input"), dict):
        raw = raw["input"]
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LlmError(f"model returned invalid tool JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise LlmError("model returned no tool input")
    return raw


def _post(url: str, key: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **({"Authorization": f"Bearer {key}"} if key else {}),
            **({"x-api-key": key} if key else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            detail = ""
        raise LlmError(f"model HTTP {exc.code}: {detail or exc.reason}") from exc
    except OSError as exc:
        raise LlmError(f"model request failed: {exc}") from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise LlmError(f"model returned non-JSON: {body[:200]}") from exc


def _anthropic_tool(cfg: dict, *, system_text: str, tool: dict,
                     user_text: str, inventory: str, max_tokens: int,
                     timeout: float) -> dict:
    if anthropic is None:
        raise LlmError("the anthropic package is not installed: pip install anthropic")
    system: list[dict[str, Any]] = [{"type": "text", "text": system_text}]
    if inventory:
        system.append({
            "type": "text", "text": inventory,
            "cache_control": {"type": "ephemeral"},
        })
    client = anthropic.Anthropic(
        api_key=str(cfg.get("api_key") or ""),
        base_url=str(cfg.get("base_url") or ""),
        timeout=timeout,
    )
    try:
        resp = client.messages.create(
            model=str(cfg.get("model") or ""),
            max_tokens=max_tokens,
            thinking={"type": "disabled"},
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": user_text}],
        )
    except Exception as exc:  # noqa: BLE001
        raise LlmError(f"model call failed: {exc}") from exc
    raw = next((b.input for b in resp.content if b.type == "tool_use"), None)
    if raw is None:
        text = next((b.text for b in resp.content if b.type == "text"), "")
        raise LlmError(
            f"model returned no tool input (stop_reason={resp.stop_reason}); "
            f"text: {text[:200]}")
    return _tool_input(raw)


def _openai_tool(cfg: dict, *, system_text: str, tool: dict,
                  user_text: str, inventory: str, max_tokens: int,
                  timeout: float) -> dict:
    base = str(cfg.get("base_url") or "").rstrip("/")
    key = str(cfg.get("api_key") or "")
    messages = [{"role": "system", "content": system_text}]
    if inventory:
        messages.append({"role": "system", "content": inventory})
    messages.append({"role": "user", "content": user_text})
    function = {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool.get("input_schema") or {"type": "object"},
    }
    payload: dict[str, Any] = {
        "model": str(cfg.get("model") or ""),
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
        "tools": [{"type": "function", "function": function}],
        "tool_choice": {"type": "function", "function": {"name": tool["name"]}},
    }
    if str(cfg.get("think") or "") == "true":
        # A broad hint; providers that do not know it ignore it.
        payload["reasoning_effort"] = "high"
    try:
        raw = _post(base + "/chat/completions", key, payload, timeout)
    except LlmError:
        # Several OpenAI-compatible gateways reject tool_choice; retry without it.
        payload.pop("tool_choice", None)
        raw = _post(base + "/chat/completions", key, payload, timeout)
    choices = raw.get("choices") or []
    message = (choices[0].get("message") if choices else {}) or {}
    calls = message.get("tool_calls") or []
    if calls:
        return _tool_input(calls[0].get("function", {}).get("arguments"))
    content = message.get("content")
    if content:
        return _tool_input(content)
    raise LlmError(f"model returned no tool call: {str(raw)[:300]}")


def _ollama_tool(cfg: dict, *, system_text: str, tool: dict,
                  user_text: str, inventory: str, max_tokens: int,
                  timeout: float) -> dict:
    base = str(cfg.get("base_url") or "").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    function = {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": tool.get("input_schema") or {"type": "object"},
    }
    messages = [{"role": "system", "content": system_text}]
    if inventory:
        messages.append({"role": "system", "content": inventory})
    messages.append({"role": "user", "content": user_text})
    payload: dict[str, Any] = {
        "model": str(cfg.get("model") or ""),
        "messages": messages,
        "stream": False,
        "tools": [{"type": "function", "function": function}],
        "options": {"num_ctx": int(cfg.get("effective_num_ctx") or 0) or 8192},
    }
    if str(cfg.get("think") or ""):
        payload["think"] = str(cfg.get("think")) == "true"
    raw = _post(base + "/api/chat", "", payload, timeout)
    message = raw.get("message") or {}
    calls = message.get("tool_calls") or []
    if calls:
        return _tool_input(calls[0].get("function", {}).get("arguments"))
    content = message.get("content")
    if content:
        return _tool_input(content)
    raise LlmError(f"model returned no tool call: {str(raw)[:300]}")


def call_tool(
    *,
    system_text: str,
    tool: dict[str, Any],
    user_text: str,
    inventory: str = "",
    max_tokens: int = 8000,
    timeout: float = 180.0,
) -> dict[str, Any]:
    cfg = resolve_active()
    kind = str(cfg.get("kind") or "openai")
    if kind == "anthropic":
        return _anthropic_tool(cfg, system_text=system_text, tool=tool,
                               user_text=user_text, inventory=inventory,
                               max_tokens=max_tokens, timeout=timeout)
    if kind == "ollama":
        return _ollama_tool(cfg, system_text=system_text, tool=tool,
                            user_text=user_text, inventory=inventory,
                            max_tokens=max_tokens, timeout=timeout)
    return _openai_tool(cfg, system_text=system_text, tool=tool,
                        user_text=user_text, inventory=inventory,
                        max_tokens=max_tokens, timeout=timeout)
