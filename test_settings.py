"""API settings are local, masked, and actually used by the model clients."""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
from unittest.mock import patch

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine.settings import (
    load_settings, public_settings, resolve_credentials, save_settings,
)

results: list[bool] = []


def check(label: str, passed: bool) -> bool:
    results.append(passed)
    print(f"  {'ok  ' if passed else 'FAIL'} {label}")
    return passed


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        path = str(pathlib.Path(tmp) / "settings.json")
        clean = {k: v for k, v in os.environ.items()
                 if k not in ("QTA_API_KEY", "ANTHROPIC_API_KEY",
                              "DEEPSEEK_API_KEY", "QTA_BASE_URL", "QTA_MODEL")}
        clean["QTA_SETTINGS_PATH"] = path
        with patch.dict(os.environ, clean, clear=True):
            print("=== empty settings ===")
            public = public_settings()
            check("no key by default", public["hasKey"] is False)
            check("env key reported separately", public["envKey"] is False)
            check("default base URL", "deepseek" in public["baseUrl"])
            check("default model", public["model"] == "deepseek-flash")

            print("\n=== save and mask ===")
            saved = save_settings({
                "apiKey": "sk-test-1234567890",
                "baseUrl": "https://example.test/anthropic",
                "model": "example-model",
            })
            check("key marked present", saved["hasKey"] is True)
            check("key is masked", saved["keyHint"] == "sk-t…7890")
            check("base URL saved", saved["baseUrl"] == "https://example.test/anthropic")
            check("model saved", saved["model"] == "example-model")
            check("raw key not in public payload", "sk-test-1234567890" not in str(saved))

            print("\n=== resolve uses UI settings ===")
            key, base, model = resolve_credentials()
            check("key resolved", key == "sk-test-1234567890")
            check("base resolved", base == "https://example.test/anthropic")
            check("model resolved", model == "example-model")

            print("\n=== blank key keeps the old key ===")
            save_settings({"baseUrl": "https://example.test/v2", "model": "m2"})
            key, base, model = resolve_credentials()
            check("key kept", key == "sk-test-1234567890")
            check("base changed", base == "https://example.test/v2")

            print("\n=== clear falls back to env ===")
            save_settings({}, clear_key=True)
            check("stored key cleared", load_settings()["apiKey"] == "")
            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}, clear=False):
                key, _, _ = resolve_credentials()
            check("env fallback used", key == "env-key")

    passed = sum(results)
    print(f"\nRESULT: {'PASS' if passed == len(results) else 'FAIL'} ({passed}/{len(results)})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
