"""
08_python_first_sync.py — Python-owned schema auto-alignment on first use.
"""
from __future__ import annotations

import time
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm import IRISModel, SchemaCompiler, field, index, parameter, trigger


@parameter("DEFAULTGLOBAL", "^Demo.PythonFirstSyncProductD")
@trigger("AuditInsert", event="INSERT", time="AFTER", code="quit")
@index("NameIdx", properties="Name", unique=True)
class Product(IRISModel):
    _iris_classname = "Demo.PythonFirstSyncProduct"
    _iris_mode = "python"

    Name: str = field(required=True, maxlen=200)
    Price: float = field(default=0.0)
    InStock: bool = field(default=True)


def main() -> None:
    Product.sync(force=True)

    live = SchemaCompiler().catalog_from_iris([Product._iris_classname])

    print("Desired classes:", [Product._iris_classname])
    print("Live classes:", [item.name for item in live.classes])

    name = f"Widget-{int(time.time())}"
    product = Product(Name=name, Price=12.5, InStock=True)
    product.save()

    fetched = Product.where(Name=name).order_by("Name").first()
    print("Saved product id:", product.pk)
    print("Fetched:", fetched.Name, fetched.Price, fetched.InStock)


if __name__ == "__main__":
    main()
