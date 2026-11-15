"""Language adapters are data, not scattered extension checks."""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE))

from engine.languages import language_specs, language_status, spec_for_path

results: list[bool] = []


def check(label: str, passed: bool) -> bool:
    results.append(passed)
    print(f"  {'ok  ' if passed else 'FAIL'} {label}")
    return passed


def main() -> int:
    specs = {spec.id: spec for spec in language_specs()}
    check("python spec exists", "python" in specs)
    check("typescript spec exists", "typescript" in specs)
    check("go spec exists", "go" in specs)

    check("python extension", spec_for_path("a.py") is not None
          and spec_for_path("a.py").id == "python")
    check("typescript extension", spec_for_path("a.tsx") is not None
          and spec_for_path("a.tsx").id == "typescript")
    check("javascript extension", spec_for_path("a.js") is not None
          and spec_for_path("a.js").id == "typescript")
    check("go extension", spec_for_path("a.go") is not None
          and spec_for_path("a.go").id == "go")
    check("unknown extension", spec_for_path("a.rb") is None)

    status = language_status(HERE)
    ids = {item["id"] for item in status}
    check("status covers all adapters", {"python", "typescript", "go"} <= ids)
    check("status has file counts", all("files" in item for item in status))

    passed = sum(results)
    print(f"\nRESULT: {'PASS' if passed == len(results) else 'FAIL'} ({passed}/{len(results)})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
