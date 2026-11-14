"""Tiny web app shaped like a real one: routes -> service -> repo, with
observability wired through every layer. Used to test reading-plan quality."""

from app.users_api import router as users_router
from app.orders_api import router as orders_router

ROUTES = {
    "GET /users": users_router["list"],
    "POST /users": users_router["create"],
    "GET /orders": orders_router["list"],
    "POST /orders": orders_router["create"],
}


def dispatch(method: str, path: str, body: dict) -> dict:
    key = f"{method} {path}"
    handler = ROUTES.get(key)
    if handler is None:
        return {"status": 404}
    return handler(body)
