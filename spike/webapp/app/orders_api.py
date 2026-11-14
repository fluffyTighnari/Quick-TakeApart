"""HTTP entry points for /orders."""

from app import logging_util, metrics
from app.orders_repo import OrderRepo
from app.orders_service import OrderService
from app.users_repo import UserRepo

logger = logging_util.get_logger("orders_api")


def _service() -> OrderService:
    return OrderService(OrderRepo(), UserRepo())


def list_orders(body: dict) -> dict:
    done = metrics.timer("list_orders")
    logging_util.log_request_started(logger, "/orders")
    data = _service().list_orders()
    done()
    logging_util.log_request_finished(logger, "/orders", 2.0)
    return {"status": 200, "data": data}


def create_order(body: dict) -> dict:
    done = metrics.timer("create_order")
    logging_util.log_request_started(logger, "/orders")
    try:
        order = _service().create_order(body)
    except ValueError as err:
        logging_util.log_error(logger, "/orders", str(err))
        return {"status": 400, "error": str(err)}
    done()
    return {"status": 201, "data": order}


router = {"list": list_orders, "create": create_order}
