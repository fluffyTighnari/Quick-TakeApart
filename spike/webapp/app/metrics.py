"""Cross-cutting observability. Real calls from every layer, never part of a request path."""

import time

_calls: dict[str, int] = {}
_latencies: dict[str, list[float]] = {}


def record_request(handler: str, ms: float) -> None:
    _calls[handler] = _calls.get(handler, 0) + 1
    _latencies.setdefault(handler, []).append(ms)


def timer(handler: str):
    start = time.perf_counter()
    return lambda: record_request(handler, (time.perf_counter() - start) * 1000)


def snapshot() -> dict:
    return {
        "calls": dict(_calls),
        "p50": {k: sorted(v)[len(v) // 2] for k, v in _latencies.items() if v},
    }
