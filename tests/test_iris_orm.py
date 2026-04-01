from __future__ import annotations

import pytest

from iris_orm import Binder, IRISModel, IRISSerial, Registry, SchemaApplier, SchemaCatalog, SchemaCompiler, SchemaPlanner, Session, bind_existing, configure_default_runtime, field, index, parameter, relationship, reset_default_runtime, session_scope, trigger

from .fake_runtime import FakeAdapter, preload_schema


def _without_source(payload):
    payload = dict(payload)
    payload.pop("source", None)
    return payload


@pytest.fixture(autouse=True)
def reset_runtime():
    reset_default_runtime()
    yield
    reset_default_runtime()


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


def test_declared_boolean_default_is_normalized_for_iris():
    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        InStock: bool = field(default=True)

    schema_class = SchemaCompiler().compile_model(Product)
    assert schema_class.property_map["InStock"].default == "1"


def test_declared_string_default_is_quoted_for_iris():
    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Foo: str = field(default="bar")

    schema_class = SchemaCompiler().compile_model(Product)
    assert schema_class.property_map["Foo"].default == '"bar"'


def test_declared_stringified_boolean_default_is_normalized_for_iris():
    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        InStock: bool = field(default="True", iris_type="%Boolean")

    schema_class = SchemaCompiler().compile_model(Product)
    assert schema_class.property_map["InStock"].default == "1"


def test_declared_empty_defaults_do_not_emit_initial_expression():
    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        EmptyText: str = field(default="")
        OptionalText: str = field(default=None)
        EmptyList: list = field(default=[], iris_type="%List")

    schema_class = SchemaCompiler().compile_model(Product)
    assert schema_class.property_map["EmptyText"].default == ""
    assert schema_class.property_map["OptionalText"].default == ""
    assert schema_class.property_map["EmptyList"].default == ""


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


def test_python_index_helper_exports_canonical_schema():
    class Product(IRISModel):
        _iris_classname = "Demo.Product"
        _iris_indexes = [
            index("NameIdx", properties="Name", unique=True),
        ]

        Name: str = field(required=True, maxlen=200)

    schema_class = SchemaCompiler().compile_model(Product)
    assert schema_class.index_map["NameIdx"].properties == "Name"
    assert schema_class.index_map["NameIdx"].unique is True


def test_python_trigger_helper_exports_canonical_schema():
    class Product(IRISModel):
        _iris_classname = "Demo.Product"
        _iris_triggers = [
            trigger("AuditInsert", event="INSERT", time="AFTER", code="set x=1"),
        ]

        Name: str = field(required=True, maxlen=200)

    schema_class = SchemaCompiler().compile_model(Product)
    assert schema_class.trigger_map["AuditInsert"].event == "INSERT"
    assert schema_class.trigger_map["AuditInsert"].time == "AFTER"
    assert schema_class.trigger_map["AuditInsert"].code == "set x=1"


def test_python_parameter_helper_exports_canonical_schema():
    class Product(IRISModel):
        _iris_classname = "Demo.Product"
        _iris_class_parameters = [
            parameter("DEFAULTGLOBAL", "^Demo.ProductD"),
        ]

        Name: str = field(required=True, maxlen=200)

    schema_class = SchemaCompiler().compile_model(Product)
    assert schema_class.parameters["DEFAULTGLOBAL"] == "^Demo.ProductD"


def test_python_schema_decorators_export_canonical_schema():
    @parameter("DEFAULTGLOBAL", "^Demo.ProductD")
    @trigger("AuditInsert", event="INSERT", time="AFTER", code="set x=1")
    @index("NameIdx", properties="Name", unique=True)
    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Name: str = field(required=True, maxlen=200)

    schema_class = SchemaCompiler().compile_model(Product)
    assert schema_class.parameters["DEFAULTGLOBAL"] == "^Demo.ProductD"
    assert schema_class.index_map["NameIdx"].properties == "Name"
    assert schema_class.index_map["NameIdx"].unique is True
    assert schema_class.trigger_map["AuditInsert"].event == "INSERT"
    assert schema_class.trigger_map["AuditInsert"].time == "AFTER"
    assert schema_class.trigger_map["AuditInsert"].code == "set x=1"


def test_schema_applier_and_compiler_roundtrip_live_schema():
    adapter = FakeAdapter()

    class Category(IRISModel):
        _iris_classname = "Demo.Category"

        Name: str = field(required=True, maxlen=80)

    class Product(IRISModel):
        _iris_classname = "Demo.Product"
        _iris_class_parameters = [parameter("DEFAULTGLOBAL", "^Demo.ProductD")]
        _iris_indexes = [index("NameIdx", properties="Name", unique=True)]
        _iris_triggers = [trigger("AuditInsert", event="INSERT", time="AFTER", code="set x=1")]
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


def test_introspection_normalizes_empty_string_initial_expression():
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Product",
            "superclass": "%Persistent",
            "properties": {
                "Name": {"iris_type": "%String", "required": True, "collection": "", "default": '""', "maxlen": 200, "description": ""},
            },
            "relationships": {},
            "indexes": {},
            "parameters": {},
            "storage": None,
        },
    )

    live = SchemaCompiler(adapter).class_from_iris("Demo.Product")
    assert live.property_map["Name"].default == ""


def test_python_mode_plan_clears_existing_storage_when_not_declared():
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Product",
            "superclass": "%Persistent",
            "properties": {
                "Name": {"iris_type": "%String", "required": True, "collection": "", "default": "", "maxlen": 200, "description": ""},
            },
            "relationships": {},
            "indexes": {},
            "parameters": {},
            "storage": {
                "name": "Default",
                "type": "%Storage.Persistent",
                "default_data": "ProductDefaultData",
                "data": [{"name": "ProductDefaultData", "structure": "listnode", "values": [{"name": "1", "value": "Name"}]}],
            },
        },
    )

    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Name: str = field(required=True, maxlen=200)

    desired = SchemaCompiler().compile_model(Product)
    live = SchemaCompiler(adapter).class_from_iris("Demo.Product")
    plan = SchemaPlanner().diff(SchemaCatalog(classes=(live,)), SchemaCatalog(classes=(desired,)))
    assert any(item.kind == "clear_storage" for item in plan.operations)

    SchemaApplier(adapter).apply(plan, allow_manual=True)
    refreshed = SchemaCompiler(adapter).class_from_iris("Demo.Product")
    assert refreshed.storage is None


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


def test_default_runtime_sugar_hides_adapter_and_session():
    adapter = FakeAdapter()
    configure_default_runtime(adapter=adapter)

    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Name: str = field(required=True, maxlen=200)
        Price: float = field(default=0.0)

    item = Product(Name="Widget", Price=9.5)
    item.save()
    fetched = Product.get(item.pk)
    assert fetched is not None
    assert fetched.Name == "Widget"
    assert Product.where(Name="Widget").count() == 1


def test_default_runtime_session_scope_batches_operations():
    adapter = FakeAdapter()
    configure_default_runtime(adapter=adapter)

    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Name: str = field(required=True)

    with session_scope() as _session:
        first = Product(Name="One")
        second = Product(Name="Two")
        first.save()
        second.save()

    assert Product.query().count() == 2


def test_auto_sync_raises_on_manual_drift_until_forced():
    adapter = FakeAdapter()
    configure_default_runtime(adapter=adapter)
    preload_schema(
        adapter,
        {
            "name": "Demo.Product",
            "superclass": "%Persistent",
            "properties": {
                "Name": {"iris_type": "%String", "required": True, "collection": "", "default": "", "maxlen": 200, "description": ""},
                "LegacyOnly": {"iris_type": "%String", "required": False, "collection": "", "default": "", "maxlen": None, "description": ""},
            },
            "relationships": {},
            "indexes": {},
            "parameters": {},
            "storage": None,
        },
    )

    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Name: str = field(required=True, maxlen=200)

    with pytest.raises(RuntimeError, match="sync\\(force=True\\)"):
        Product.where(Name="x").count()

    Product.sync(force=True)
    Product(Name="Widget").save()
    assert Product.where(Name="Widget").count() == 1


def test_bind_existing_is_runtime_only_for_schema_operations():
    adapter = FakeAdapter()
    configure_default_runtime(adapter=adapter)
    preload_schema(
        adapter,
        {
            "name": "Demo.LegacyArticle",
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

    LegacyArticle = bind_existing("Demo.LegacyArticle")
    assert LegacyArticle._iris_mode == "proxy"
    with pytest.raises(RuntimeError, match='only available for models with _iris_mode = "python"'):
        LegacyArticle.plan()
    with pytest.raises(RuntimeError, match='only available for models with _iris_mode = "python"'):
        LegacyArticle.sync()
