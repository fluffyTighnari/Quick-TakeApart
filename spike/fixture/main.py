"""Entry point. Ground truth: main() -> OrderApi.create() -> validate() + OrderService.place()."""

from shop.api import OrderApi


def main() -> None:
    api = OrderApi()
    result = api.create({"items": [{"price": 10, "qty": 2}]})
    print(result)


if __name__ == "__main__":
    main()
