"""Small shared helper for the new model calls.

The existing stage modules each carry their own Anthropic bootstrap. New code
uses this one so the credential/caching/tool-call rules live in a single place.
"""

from __future__ import annotations

from typing import Any

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

from .settings import DEFAULT_BASE_URL, DEFAULT_KEY_ENV, DEFAULT_MODEL, resolve_credentials


class LlmError(RuntimeError):
    pass


def credentials() -> tuple[str, str, str]:
    key, base, model = resolve_credentials()
    if not key:
        raise LlmError(
            "no API key: open API settings in the top bar, or set "
            f"{DEFAULT_KEY_ENV} / QTA_API_KEY."
        )
    return key, base, model


def call_tool(
    *,
    system_text: str,
    tool: dict[str, Any],
    user_text: str,
    inventory: str = "",
    max_tokens: int = 8000,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """Call a tool-only model turn and return the tool input.

    `thinking` must be explicitly disabled for the DeepSeek Anthropic endpoint:
    it rejects `tool_choice` otherwise.
    """
    key, base, model = credentials()
    if anthropic is None:
        raise LlmError("the anthropic package is not installed: pip install anthropic")

    system: list[dict[str, Any]] = [{"type": "text", "text": system_text}]
    if inventory:
        system.append({
            "type": "text",
            "text": inventory,
            "cache_control": {"type": "ephemeral"},
        })

    client = anthropic.Anthropic(api_key=key, base_url=base, timeout=timeout)
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "disabled"},
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": user_text}],
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller
        raise LlmError(f"model call failed: {exc}") from exc

    raw = next((b.input for b in resp.content if b.type == "tool_use"), None)
    if raw is None:
        text = next((b.text for b in resp.content if b.type == "text"), "")
        raise LlmError(
            f"model returned no tool input (stop_reason={resp.stop_reason}); "
            f"text: {text[:200]}"
        )
    return raw
