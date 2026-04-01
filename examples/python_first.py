from __future__ import annotations

from iris_orm import IRISModel, field, index, parameter


@parameter("DEFAULTGLOBAL", "^Demo.ProductD")
@index("NameIdx", properties="Name", unique=True)
class Product(IRISModel):
    _iris_classname = "Demo.ExampleProduct"
    _iris_mode = "python"
    _iris_storage = {
        "name": "Default",
        "type": "%Storage.Persistent",
        "data_location": "^Demo.ExampleProductD",
        "default_data": "ExampleProductDefaultData",
    }

    Name: str = field(required=True, maxlen=200)
    Price: float = field(default=0.0)


def main() -> None:
    row = Product(Name="Widget", Price=9.99).save()
    print("saved", row.pk)


if __name__ == "__main__":
    main()

