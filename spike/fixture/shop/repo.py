"""Persistence layer. Ground truth: no outgoing calls into service/api (leaf module)."""


class InMemoryOrderRepo:
    def __init__(self):
        self._rows: list[dict] = []

    def save(self, record: dict) -> None:
        self._rows.append(record)

    def count(self) -> int:
        return len(self._rows)
