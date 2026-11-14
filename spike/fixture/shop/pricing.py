"""Pure computation. Ground truth: total() calls _line(), leaf otherwise."""


def total(items: list) -> float:
    return sum(_line(it) for it in items)


def _line(item: dict) -> float:
    return float(item.get("price", 0)) * int(item.get("qty", 1))
