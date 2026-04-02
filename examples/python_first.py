from __future__ import annotations

from typing import Annotated

from iris_orm import Field, IRISModel, Index, StorageDefinition

class Product(IRISModel):
    Name: Annotated[str, Field(required=True, maxlen=200)]
    Price: Annotated[float, Field(default=0.0)]

    class Meta:
        classname = "Demo.ExampleProduct"
        mode = "python"
        storage = StorageDefinition(
            data_location="^Demo.ExampleProductD",
            default_data="ExampleProductDefaultData",
            type="%Storage.Persistent",
        )
        indexes = [Index("NameIdx", properties="Name", unique=True)]
        parameters = {"DEFAULTGLOBAL": "^Demo.ProductD"}


def main() -> None:
    row = Product(Name="Widget", Price=9.99).save()
    print("saved", row.pk)


if __name__ == "__main__":
    main()
