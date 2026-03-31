"""
08_python_first_sync.py — Python-owned schema sync with a canonical lockfile.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm import IRISModel, Registry, SchemaCompiler, field

from examples._common import bind_session, sync_registry, write_model_lockfile


class Product(IRISModel):
    _iris_classname = "Demo.Product"
    _iris_class_parameters = {"DEFAULTGLOBAL": "^Demo.ProductD"}
    _iris_indexes = [{"name": "NameIdx", "properties": "Name", "unique": True, "primary_key": False}]

    Name: str = field(required=True, maxlen=200)
    Price: float = field(default=0.0)
    InStock: bool = field(default=True)


def main() -> None:
    registry = Registry()
    registry.register(Product)

    adapter = sync_registry(registry)
    lockfile_path = write_model_lockfile(Product, registry)

    live = SchemaCompiler(adapter).catalog_from_iris(registry.classnames())
    desired = registry.export_schema()

    print(f"Lockfile: {lockfile_path}")
    print("Desired classes:", [item.name for item in desired.classes])
    print("Live classes:", [item.name for item in live.classes])

    _adapter, _binder, session = bind_session(registry, adapter=adapter)
    product = Product(Name="Widget", Price=12.5, InStock=True)
    session.add(product)
    session.commit()

    fetched = session.query(Product).filter_eq(Name="Widget").first()
    print("Saved product id:", product.pk)
    print("Fetched:", fetched.Name, fetched.Price, fetched.InStock)


if __name__ == "__main__":
    main()
