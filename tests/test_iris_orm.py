from __future__ import annotations

from pathlib import Path

import pytest

from iris_orm import Binder, IRISModel, IRISSerial, Registry, SchemaApplier, SchemaCatalog, SchemaCompiler, SchemaPlanner, Session, field, relationship
from iris_orm.lockfile import build_lockfile, compute_hash, load_lockfile, write_lockfile

from .fake_runtime import FakeAdapter, preload_schema


def _without_source(payload):
    payload = dict(payload)
    payload.pop("source", None)
    return payload


def test_declared_models_export_canonical_schema_without_live_attach():
    class Address(IRISSerial):
        _iris_classname = "Demo.Address"

        City: str = field(required=True, maxlen=100)

    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Name: str = field(required=True, maxlen=200)
        Address: Address

    registry = Registry()
    registry.register(Address)
    registry.register(Product)

    catalog = registry.export_schema()
    assert [item.name for item in catalog.classes] == ["Demo.Address", "Demo.Product"]
    product = catalog.get_class("Demo.Product")
    assert product is not None
    assert product.property_map["Name"].maxlen == 200
    assert product.property_map["Address"].iris_type == "Demo.Address"


def test_lockfile_roundtrip_is_hash_stable(tmp_path: Path):
    class Product(IRISModel):
        _iris_classname = "Demo.Product"
        _iris_class_parameters = {"DEFAULTGLOBAL": "^Demo.ProductD"}
        _iris_indexes = [{"name": "NameIdx", "properties": "Name", "unique": True, "primary_key": False}]
        _iris_storage = {
            "name": "Default",
            "type": "%Storage.Persistent",
            "data_location": "^Demo.ProductD",
            "default_data": "ProductDefaultData",
            "data": [{"name": "ProductDefaultData", "structure": "listnode", "values": [{"name": "1", "value": "Name"}]}],
        }

        Name: str = field(required=True, maxlen=200)

    registry = Registry()
    registry.register(Product)
    schema = registry.export_schema()
    lockfile = build_lockfile(schema, source={"kind": "declared", "origin": "tests"})
    path = tmp_path / "product.iris.lock.json"
    write_lockfile(path, lockfile)

    loaded = load_lockfile(path)
    assert loaded.schema.to_dict() == schema.to_dict()
    assert loaded.schema_hash == compute_hash(schema.to_dict())


def test_existing_binding_requires_explicit_binder():
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Article",
            "superclass": "%Persistent",
            "properties": {
                "Title": {"iris_type": "%String", "required": True, "collection": "", "default": "", "maxlen": 500, "description": ""},
            },
            "relationships": {},
            "indexes": {},
            "parameters": {},
            "storage": None,
        },
    )

    registry = Registry()
    Article = registry.bind_existing("Demo.Article")
    assert "Title" not in Article.__dict__

    binder = Binder(registry, adapter)
    binder.bind_all()

    assert "Title" in Article.__dict__
    assert Article._iris_bound is True


def test_schema_applier_and_compiler_roundtrip_live_schema():
    adapter = FakeAdapter()

    class Category(IRISModel):
        _iris_classname = "Demo.Category"

        Name: str = field(required=True, maxlen=80)

    class Product(IRISModel):
        _iris_classname = "Demo.Product"
        _iris_class_parameters = {"DEFAULTGLOBAL": "^Demo.ProductD"}
        _iris_indexes = [{"name": "NameIdx", "properties": "Name", "unique": True, "primary_key": False}]
        _iris_storage = {
            "name": "Default",
            "type": "%Storage.Persistent",
            "data_location": "^Demo.ProductD",
            "default_data": "ProductDefaultData",
            "data": [{"name": "ProductDefaultData", "structure": "listnode", "values": [{"name": "1", "value": "Name"}]}],
        }

        Name: str = field(required=True, maxlen=200)
        Category = relationship("Demo.Category", inverse="Products", cardinality="parent")

    registry = Registry()
    registry.register(Category)
    registry.register(Product)
    desired = registry.export_schema()

    plan = SchemaPlanner().diff(SchemaCompiler(adapter).catalog_from_iris(registry.classnames()), desired)
    SchemaApplier(adapter).apply(plan, allow_manual=True)

    live = SchemaCompiler(adapter).catalog_from_iris(registry.classnames())
    assert [_without_source(item.to_dict()) for item in live.classes] == [
        _without_source(item.to_dict()) for item in desired.classes
    ]


def test_session_crud_query_and_identity_map():
    adapter = FakeAdapter()

    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Name: str = field(required=True, maxlen=200)
        Price: float = field(default=0.0)

    registry = Registry()
    registry.register(Product)
    desired = registry.export_schema()
    SchemaApplier(adapter).apply(SchemaPlanner().diff(SchemaCompiler(adapter).catalog_from_iris(["Demo.Product"]), desired))

    binder = Binder(registry, adapter)
    binder.bind_all()
    session = Session(binder, adapter)

    product = Product(Name="Widget", Price=9.5)
    session.add(product)
    session.commit()

    loaded = session.get(Product, product.pk)
    assert loaded is product

    second = Product(Name="Bolt", Price=1.5)
    session.add(second)
    session.commit()

    query = session.query(Product).filter_in(Name=["Widget", "Bolt"]).order_by("Price")
    names = [item.Name for item in query]
    assert names == ["Bolt", "Widget"]
    assert query.count() == 2
    assert session.query(Product).filter_eq(Name="Widget").first() is product


def test_query_rejects_unknown_fields():
    adapter = FakeAdapter()

    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Name: str = field(required=True)

    registry = Registry()
    registry.register(Product)
    SchemaApplier(adapter).apply(SchemaPlanner().diff(SchemaCatalog(), registry.export_schema()))
    binder = Binder(registry, adapter)
    binder.bind_all()
    session = Session(binder, adapter)

    with pytest.raises(ValueError, match="Unknown field"):
        session.query(Product).filter_eq(Missing="x").all()
