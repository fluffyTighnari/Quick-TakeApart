"""Fixture with known ground-truth call graph, used to verify LSP edge accuracy."""

from shop import service
from shop import repo


class OrderApi:
    def __init__(self):
        self.svc = service.OrderService(repo.InMemoryOrderRepo())

    def create(self, payload: dict):
        validated = self.validate(payload)
        return self.svc.place(validated)

    def validate(self, payload: dict) -> dict:
        if not payload.get("items"):
            raise ValueError("empty")
        return {"items": payload["items"], "note": payload.get("note", "")}
