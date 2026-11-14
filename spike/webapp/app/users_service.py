"""User business rules. Validates, then delegates to the repo."""

from app import logging_util, metrics
from app.users_repo import UserRepo

logger = logging_util.get_logger("users")


class UserService:
    def __init__(self, repo: UserRepo):
        self.repo = repo

    def list_users(self) -> list[dict]:
        logger("debug", "listing users")
        return self.repo.fetch_all()

    def create_user(self, payload: dict) -> dict:
        name = (payload.get("name") or "").strip()
        if not name:
            raise ValueError("name required")
        user_id = self.repo.insert(name)
        metrics.record_request("create_user", 0.0)
        return {"id": user_id, "name": name}

    def get_user(self, user_id: int) -> dict:
        user = self.repo.fetch_one(user_id)
        if user is None:
            raise ValueError(f"user {user_id} not found")
        return user
