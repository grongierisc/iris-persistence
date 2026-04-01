from __future__ import annotations

import pytest

from iris_orm import (
    IRISModel,
    configure_default_runtime,
    field,
    index,
    parameter,
    reset_default_runtime,
)
from iris_orm.schema import SchemaCompiler, schema_equals
from iris_orm.scaffold import parse_cls

from .fake_runtime import FakeAdapter, preload_schema


@pytest.fixture(autouse=True)
def reset_runtime() -> None:
    reset_default_runtime()
    yield
    reset_default_runtime()


def test_python_first_compiles_decorators_and_storage() -> None:
    @parameter("DEFAULTGLOBAL", "^Demo.ProductD")
    @index("NameIdx", properties="Name", unique=True)
    class Product(IRISModel):
        _iris_classname = "Demo.Product"
        _iris_superclasses = ["%Persistent", "Demo.Auditable"]
        _iris_storage = {
            "name": "Default",
            "type": "%Storage.Persistent",
            "data_location": "^Demo.ProductD",
            "default_data": "ProductDefaultData",
        }

        Name: str = field(required=True, maxlen=200)
        Price: float = field(default=0.0)
        InStock: bool = field(default=True)

    schema = SchemaCompiler().compile_model(Product)
    assert schema.superclasses == ("%Persistent", "Demo.Auditable")
    assert schema.parameters["DEFAULTGLOBAL"] == "^Demo.ProductD"
    assert schema.index_map["NameIdx"].unique is True
    assert schema.property_map["Price"].default == "0.0"
    assert schema.property_map["InStock"].default == "1"
    assert schema.storage["data_location"] == "^Demo.ProductD"


def test_python_first_auto_overwrites_live_schema() -> None:
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Product",
            "properties": {
                "OldField": {"iris_type": "%String"},
                "Name": {"iris_type": "%String"},
            },
            "indexes": {
                "OldIdx": {"properties": "OldField"},
            },
            "parameters": {"OLD": "1"},
            "storage": {"name": "Default", "data_location": "^Old.Global"},
        },
    )
    configure_default_runtime(runtime=adapter)

    @parameter("DEFAULTGLOBAL", "^Demo.ProductD")
    @index("NameIdx", properties="Name", unique=True)
    class Product(IRISModel):
        _iris_classname = "Demo.Product"
        _iris_storage = {"name": "Default", "data_location": "^Demo.ProductD"}

        Name: str = field(required=True, maxlen=200)
        Price: float = field(default=0.0)

    product = Product(Name="Widget", Price=12.5)
    product.save()

    desired = SchemaCompiler().compile_model(Product)
    live = SchemaCompiler(adapter).class_from_iris("Demo.Product")
    assert schema_equals(live, desired)
    assert "OldField" not in live.property_map
    assert "OldIdx" not in live.index_map
    assert live.parameters == {"DEFAULTGLOBAL": "^Demo.ProductD"}
    assert adapter.rows["Demo.Product"][1]["Name"] == "Widget"


def test_proxy_model_uses_live_schema_without_overwrite() -> None:
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Article",
            "properties": {
                "Title": {"iris_type": "%String", "required": True, "maxlen": 500},
                "Views": {"iris_type": "%Integer", "default": "0"},
            },
            "indexes": {"TitleIdx": {"properties": "Title", "unique": True}},
            "parameters": {"DEFAULTGLOBAL": "^Demo.ArticleD"},
            "storage": {"name": "Default", "data_location": "^Demo.ArticleD"},
        },
    )
    configure_default_runtime(runtime=adapter)

    class Article(IRISModel):
        _iris_classname = "Demo.Article"
        _iris_mode = "proxy"

    Article.bind()

    assert Article._iris_mode == "proxy"
    assert "Title" in Article._iris_declared_fields
    assert Article._iris_storage["data_location"] == "^Demo.ArticleD"
    before = adapter.load_schema("Demo.Article")
    row = Article(Title="Hello", Views=1).save()
    after = adapter.load_schema("Demo.Article")
    assert before == after
    assert row.pk == 1


def test_query_and_get_work_with_fake_runtime() -> None:
    adapter = FakeAdapter()
    configure_default_runtime(runtime=adapter)

    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Name: str = field(required=True, maxlen=200)
        Price: float = field(default=0.0)

    Product(Name="A", Price=1.0).save()
    Product(Name="B", Price=2.0).save()

    loaded = Product.get(1)
    assert loaded is not None
    assert loaded.Name == "A"

    rows = Product.where(Price=2.0).order_by("Name").all()
    assert [row.Name for row in rows] == ["B"]


def test_query_rejects_unknown_field() -> None:
    adapter = FakeAdapter()
    configure_default_runtime(runtime=adapter)

    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Name: str = field(required=True)

    with pytest.raises(ValueError):
        Product.where(Unknown="x").all()


def test_proxy_instance_method_bridge_works() -> None:
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Article",
            "properties": {
                "Body": {"iris_type": "%String"},
                "Title": {"iris_type": "%String", "required": True},
            },
            "indexes": {},
            "parameters": {},
            "storage": {"name": "Default", "data_location": "^Demo.ArticleD"},
        },
    )

    def method_name(self):
        return self.Body

    adapter.instance_methods["Demo.Article"] = {"MethodName": method_name}
    configure_default_runtime(runtime=adapter)

    class Article(IRISModel):
        _iris_classname = "Demo.Article"
        _iris_mode = "proxy"

    row = Article(Title="Hello", Body="Body text").save()
    loaded = Article.get(row.pk)
    assert loaded is not None
    assert loaded.MethodName() == "Body text"


def test_proxy_class_method_bridge_works() -> None:
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Article",
            "properties": {
                "Title": {"iris_type": "%String", "required": True},
            },
            "indexes": {},
            "parameters": {},
            "storage": {"name": "Default", "data_location": "^Demo.ArticleD"},
        },
    )
    adapter.class_methods["Demo.Article"] = {
        "EchoSlug": staticmethod(lambda slug: f"slug:{slug}"),
    }
    configure_default_runtime(runtime=adapter)

    class Article(IRISModel):
        _iris_classname = "Demo.Article"
        _iris_mode = "proxy"

    assert Article.EchoSlug("hello") == "slug:hello"


def test_python_superclasses_accept_string_or_list() -> None:
    class OneBase(IRISModel):
        _iris_classname = "Demo.OneBase"
        _iris_superclasses = "Ens.Request"

        Name: str = field(required=True)

    class ManyBases(IRISModel):
        _iris_classname = "Demo.ManyBases"
        _iris_superclasses = ["%Persistent", "Demo.Auditable"]

        Name: str = field(required=True)

    assert SchemaCompiler().compile_model(OneBase).superclasses == ("Ens.Request",)
    assert SchemaCompiler().compile_model(ManyBases).superclasses == ("%Persistent", "Demo.Auditable")


def test_parse_storage_preserves_extended_sections() -> None:
    schema = parse_cls(
        """
Class Demo.Product Extends %Persistent, Demo.Auditable
{
Property Name As %String [ Required ];

Storage Default
{
<Data name="ProductDefaultData">
<Structure>listnode</Structure>
<Value name="1">
<Value>%%CLASSNAME</Value>
</Value>
</Data>
<DataLocation>^Demo.ProductD</DataLocation>
<DefaultData>ProductDefaultData</DefaultData>
<ExtentSize>2</ExtentSize>
<Property name="Name">
<AverageFieldSize>8</AverageFieldSize>
<Selectivity>0.0001%</Selectivity>
</Property>
<SQLMap name="IDKEY">
<BlockCount>-4</BlockCount>
</SQLMap>
<Type>%Storage.Persistent</Type>
}
}
""".strip()
    )
    assert schema.superclasses == ("%Persistent", "Demo.Auditable")
    assert schema.storage["extent_size"] == "2"
    assert schema.storage["properties"][0]["name"] == "Name"
    assert schema.storage["properties"][0]["average_field_size"] == "8"
    assert schema.storage["sql_maps"][0]["name"] == "IDKEY"
    assert schema.storage["sql_maps"][0]["block_count"] == "-4"
