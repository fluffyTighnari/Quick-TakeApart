"""One model call adapter for both Anthropic and OpenAI/Ollama protocols.

Stage modules no longer own credential/bootstrap code. The active model profile
decides protocol, endpoint, key, thinking and context budget; callers only pass
a tool schema and text.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

from .llm_config import OPENCODE_SESSION, USER_AGENT, resolve_active


class LlmError(RuntimeError):
    pass


def credentials() -> tuple[str, str, str]:
    cfg = resolve_active()
    key = str(cfg.get("api_key") or "")
    if not key and cfg.get("kind") not in ("ollama", "openai"):
        raise LlmError("no API key: open model settings and configure a profile")
    return key, str(cfg.get("base_url") or ""), str(cfg.get("model") or "")


_FENCE = re.compile(r"^```(?:[A-Za-z]+)?\s*|\s*```$")


def _balance_json(text: str) -> str:
    """Terminate an open string and close whatever containers are still open."""
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    out = text
    while out and (out[-1] in ",:" or out[-1].isspace()):
        out = out[:-1]
    if in_string:
        out += '"'
    return out + "".join(reversed(stack))


def _last_separator(text: str) -> int:
    """Index of the last comma or colon outside a string, or -1."""
    in_string = False
    escaped = False
    found = -1
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in ",:":
            found = i
    return found


def _salvage_json(text: str) -> Any:
    """Recover tool arguments that arrived wrapped, truncated or slightly broken.

    Gateways differ: some fence the arguments in markdown, some stop mid-object
    when the output budget runs out. Both are normal enough that losing the whole
    result to a JSON error would be wasteful. We first take the last complete
    object, then close a truncated one, and finally drop the incomplete trailing
    member (a half-written key or value) and close again.
    """
    body = _FENCE.sub("", text.strip())
    start = body.find("{")
    if start < 0:
        return None
    body = body[start:]

    # A complete object followed by stray text is the easiest case: keep the
    # object and ignore the tail.
    stack_depth = 0
    in_str = False
    esc = False
    closed_at = -1
    for i, ch in enumerate(body):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack_depth += 1
        elif ch in "}]":
            stack_depth -= 1
            if stack_depth == 0:
                closed_at = i
    if closed_at > 0:
        try:
            return json.loads(body[:closed_at + 1])
        except json.JSONDecodeError:
            pass

    trimmed = body
    for attempt in range(12):
        candidate = _balance_json(trimmed)
        for cleaned in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                continue
        cut = _last_separator(trimmed)
        if cut <= 0:
            break
        trimmed = trimmed[:cut]
    return None


def _tool_input(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict) and isinstance(raw.get("input"), dict):
        raw = raw["input"]
    if isinstance(raw, str):
        text = raw
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raw = _salvage_json(text)
            if raw is None:
                raise LlmError(
                    "model returned invalid tool JSON: "
                    f"{exc}; head={text[:120]!r} tail={text[-120:]!r}") from exc
    if not isinstance(raw, dict):
        raise LlmError("model returned no tool input")
    return raw


def _post(url: str, key: str, payload: dict, timeout: float) -> dict:
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["x-api-key"] = key
    # opencode's gateway rejects untagged chat calls with 400 MissingSessionID;
    # one id per process keeps its routing/caching behaviour.
    if "opencode.ai" in url:
        headers["x-opencode-session"] = OPENCODE_SESSION

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
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
