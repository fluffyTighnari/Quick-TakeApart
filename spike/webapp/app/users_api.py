"""HTTP entry points for /users."""

from app import logging_util, metrics
from app.db import get_connection
from app.users_repo import UserRepo
from app.users_service import UserService

logger = logging_util.get_logger("users_api")


def _service() -> UserService:
    return UserService(UserRepo())


def list_users(body: dict) -> dict:
    done = metrics.timer("list_users")
    logging_util.log_request_started(logger, "/users")
    logging_util.log_request_started(logger, "/users")
    data = _service().list_users()
    done()
    logging_util.log_request_finished(logger, "/users", 1.0)
    return {"status": 200, "data": data}


def create_user(body: dict) -> dict:
    done = metrics.timer("create_user")
    logging_util.log_request_started(logger, "/users")
    try:
        user = _service().create_user(body)
    except ValueError as err:
        logging_util.log_error(logger, "/users", str(err))
        return {"status": 400, "error": str(err)}
    done()
    return {"status": 201, "data": user}


def get_user(body: dict) -> dict:
    done = metrics.timer("get_user")
    user = _service().get_user(int(body["id"]))
    done()
    return {"status": 200, "data": user}


def healthcheck(body: dict) -> dict:
    conn = get_connection()
    conn.execute("SELECT 1")
    return {"status": 200, "ok": True}


router = {"list": list_users, "create": create_user, "get": get_user}
