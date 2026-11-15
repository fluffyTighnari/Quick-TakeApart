"""Profile catalogue rules from the model-config contract."""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
from unittest.mock import patch

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine import llm_config as c

results: list[bool] = []


def check(label: str, passed: bool) -> bool:
    results.append(passed)
    print(f"  {'ok  ' if passed else 'FAIL'} {label}")
    return passed


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("QTA_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
                              "ANTHROPIC_API_KEY", "QTA_BASE_URL", "QTA_MODEL")}
        clean["QTA_LLM_DIR"] = tmp
        clean["QTA_SETTINGS_PATH"] = str(pathlib.Path(tmp) / "settings.json")
        with patch.dict(os.environ, clean, clear=True):
            print("=== provider catalogue ===")
            check("providers available", len(c.providers()) >= 10)
            try:
                c.provider("deepsek")
                check("unknown provider refused", False)
            except c.LlmConfigError as exc:
                check("unknown provider refused", "deepsek" in str(exc))
                check("error lists custom", "custom" in str(exc))

            print("\n=== first profile / key handling ===")
            p = c.create_profile({
                "provider_id": "deepseek",
                "model": "deepseek-flash",
                "models": ["deepseek-v4-pro"],
                "api_key": "sk-test-1234567890",
            })
            check("first profile active", p["is_active"] is True)
            check("models includes current first", p["models"][0] == "deepseek-flash")
            check("key masked, raw absent", "sk-test-1234567890" not in str(p))
            check("has key", p["has_key"] is True)
            check("default context derived", p["effective_num_ctx"] > 0)

            print("\n=== PATCH keeps omitted fields, models invariant ===")
            p2 = c.update_profile(p["profile_id"], {
                "model": "deepseek-v4-pro", "models": ["deepseek-flash"],
            })
            check("model moved first", p2["models"][0] == "deepseek-v4-pro")
            check("old model kept", "deepseek-flash" in p2["models"])
            check("label preserved", p2["label"] == p["label"])

            print("\n=== activate is one action ===")
            active = c.activate_profile(p["profile_id"], "deepseek-flash")
            check("active", active["is_active"] is True)
            check("model switched", active["model"] == "deepseek-flash")
            try:
                c.activate_profile(p["profile_id"], "not-in-profile")
                check("unchecked model refused", False)
            except c.LlmConfigError:
                check("unchecked model refused", True)

            print("\n=== second profile and deletion fallback ===")
            q = c.create_profile({"provider_id": "openai", "model": "gpt-4.1-mini",
                                  "api_key": "sk-openai-123456"})
            check("second profile not active", q["is_active"] is False)
            c.activate_profile(q["profile_id"])
            deleted = c.delete_profile(q["profile_id"])
            check("active falls back", deleted["active_profile_id"] == p["profile_id"])
            check("config has active", c.config_view()["active"]["profile_id"] == p["profile_id"])

            print("\n=== invalid base URL is a field error ===")
            try:
                c.create_profile({"provider_id": "custom", "model": "x",
                                  "base_url": "api.example.com"})
                check("bad URL refused", False)
            except c.LlmConfigError as exc:
                check("bad URL refused", "http://" in str(exc) or "https://" in str(exc))

    passed = sum(results)
    print(f"\nRESULT: {'PASS' if passed == len(results) else 'FAIL'} ({passed}/{len(results)})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
