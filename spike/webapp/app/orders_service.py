"""Order rules: pricing, then persistence."""

from app import metrics
from app.orders_repo import OrderRepo
from app.users_repo import UserRepo


class OrderService:
    def __init__(self, repo: OrderRepo, users: UserRepo):
        self.repo = repo
        self.users = users

    def list_orders(self) -> list[dict]:
        return self.repo.fetch_all()

    def create_order(self, payload: dict) -> dict:
        user_id = int(payload["user_id"])
        if self.users.fetch_one(user_id) is None:
            raise ValueError(f"user {user_id} not found")
        total = self.price(payload["items"])
        order_id = self.repo.insert(user_id, total)
        metrics.record_request("create_order", 0.0)
        return {"id": order_id, "user_id": user_id, "total": total}

    def price(self, items: list) -> float:
        return sum(float(i["price"]) * int(i.get("qty", 1)) for i in items)

    def spend_of_user(self, user_id: int) -> float:
        return self.repo.total_for_user(user_id)
