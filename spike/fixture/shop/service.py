"""Business layer. Ground truth: place() calls repo.save()/count() and pricing.total()."""

from shop import pricing
from shop import repo


class OrderService:
    def __init__(self, r: repo.InMemoryOrderRepo):
        self.repo = r

    def place(self, order: dict) -> dict:
        priced = pricing.total(order["items"])
        record = {"id": self.next_id(), "total": priced, "note": order["note"]}
        self.repo.save(record)
        return record

    def next_id(self) -> int:
        return self.repo.count() + 1
