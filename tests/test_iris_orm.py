from __future__ import annotations

from typing import Annotated
import warnings

import pytest

from iris_orm import (
    Field,
    IRISModel,
    Index,
    StorageDefinition,
    configure_default_runtime,
    field,
    index,
    parameter,
    reset_default_runtime,
)
from iris_orm.schema import SchemaCompiler, schema_equals
from iris_orm.scaffold import parse_cls
from iris_orm.testing import FakeAdapter, preload_schema


@pytest.fixture(autouse=True)
def reset_runtime() -> None:
    reset_default_runtime()
    yield
    reset_default_runtime()


def test_python_first_compiles_decorators_and_storage() -> None:
    class Product(IRISModel):
        Name: Annotated[str, Field(required=True, maxlen=200)]
        Price: Annotated[float, Field(default=0.0)]
        InStock: Annotated[bool, Field(default=True)]

        class Meta:
            classname = "Demo.Product"
            mode = "python"
            superclasses = ["%Persistent", "Demo.Auditable"]
            storage = StorageDefinition(
                data_location="^Demo.ProductD",
                default_data="ProductDefaultData",
                type="%Storage.Persistent",
            )
            indexes = [Index("NameIdx", properties="Name", unique=True)]
            parameters = {"DEFAULTGLOBAL": "^Demo.ProductD"}

    schema = SchemaCompiler().compile_model(Product)
    assert schema.superclasses == ("%Persistent", "Demo.Auditable")
    assert schema.parameters["DEFAULTGLOBAL"] == "^Demo.ProductD"
    assert schema.index_map["NameIdx"].unique is True
    assert schema.property_map["Price"].default == "0.0"
    assert schema.property_map["InStock"].default == "1"
    assert schema.storage is not None
    assert schema.storage.data_location == "^Demo.ProductD"


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

    class Product(IRISModel):
        Name: Annotated[str, Field(required=True, maxlen=200)]
        Price: Annotated[float, Field(default=0.0)]

        class Meta:
            classname = "Demo.Product"
            mode = "python"
            storage = StorageDefinition(name="Default", data_location="^Demo.ProductD")
            indexes = [Index("NameIdx", properties="Name", unique=True)]
            parameters = {"DEFAULTGLOBAL": "^Demo.ProductD"}

    product = Product(Name="Widget", Price=12.5)
    product.save()

    desired = SchemaCompiler().compile_model(Product)
    live = SchemaCompiler(adapter).class_from_iris("Demo.Product")
    assert schema_equals(live, desired)
    assert "OldField" not in live.property_map
    assert "OldIdx" not in live.index_map
    assert live.parameters == {"DEFAULTGLOBAL": "^Demo.ProductD"}
    assert adapter.rows["Demo.Product"][1]["Name"] == "Widget"


def test_default_additive_mode_keeps_live_members() -> None:
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
        },
    )
    configure_default_runtime(runtime=adapter)

    class Product(IRISModel):
        Name: Annotated[str, Field(required=True)]
        Price: Annotated[float, Field(default=0.0)]

        class Meta:
            classname = "Demo.Product"

    Product(Name="Widget", Price=12.5).save()

    live = SchemaCompiler(adapter).class_from_iris("Demo.Product")
    assert Product._iris_mode == "additive"
    assert "OldField" in live.property_map
    assert "Price" in live.property_map
    assert "OldIdx" in live.index_map
    assert live.parameters["OLD"] == "1"


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
        class Meta:
            classname = "Demo.Article"
            mode = "proxy"

    Article.bind()

    assert Article._iris_mode == "proxy"
    assert "Title" in Article._iris_declared_fields
    assert Article._iris_storage is not None
    assert Article._iris_storage.data_location == "^Demo.ArticleD"
    before = adapter.load_schema("Demo.Article")
    row = Article(Title="Hello", Views=1).save()
    after = adapter.load_schema("Demo.Article")
    assert before == after
    assert row.pk == 1


def test_query_and_get_work_with_fake_runtime() -> None:
    adapter = FakeAdapter()
    configure_default_runtime(runtime=adapter)

    class Product(IRISModel):
        Name: Annotated[str, Field(required=True, maxlen=200)]
        Price: Annotated[float, Field(default=0.0)]

        class Meta:
            classname = "Demo.Product"

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
        Name: Annotated[str, Field(required=True)]

        class Meta:
            classname = "Demo.Product"

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
        class Meta:
            classname = "Demo.Article"
            mode = "proxy"

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
        class Meta:
            classname = "Demo.Article"
            mode = "proxy"

    assert Article.EchoSlug("hello") == "slug:hello"


def test_python_superclasses_accept_string_or_list() -> None:
    class OneBase(IRISModel):
        Name: Annotated[str, Field(required=True)]

        class Meta:
            classname = "Demo.OneBase"
            superclasses = "Ens.Request"

    class ManyBases(IRISModel):
        Name: Annotated[str, Field(required=True)]

        class Meta:
            classname = "Demo.ManyBases"
            superclasses = ["%Persistent", "Demo.Auditable"]

    assert SchemaCompiler().compile_model(OneBase).superclasses == ("Ens.Request",)
    assert SchemaCompiler().compile_model(ManyBases).superclasses == ("%Persistent", "Demo.Auditable")


def test_legacy_field_function_warns_and_still_works() -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")

        class Product(IRISModel):
            Name: str = field(required=True, maxlen=200)

            class Meta:
                classname = "Demo.LegacyProduct"

    assert any(item.category is DeprecationWarning for item in captured)
    compiled = SchemaCompiler().compile_model(Product)
    assert compiled.property_map["Name"].maxlen == 200


def test_meta_replaces_bare_iris_metadata() -> None:
    class Product(IRISModel):
        Name: Annotated[str, Field(required=True)]

        class Meta:
            classname = "Demo.MetaProduct"
            mode = "proxy"
            superclasses = "Ens.Request"
            parameters = {"DEFAULTGLOBAL": "^Demo.MetaProductD"}

    assert Product._iris_classname == "Demo.MetaProduct"
    assert Product._iris_mode == "proxy"
    assert Product._iris_superclasses == "Ens.Request"
    assert Product._iris_parameters == {"DEFAULTGLOBAL": "^Demo.MetaProductD"}


def test_bare_iris_metadata_warns() -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")

        class Product(IRISModel):
            _iris_classname = "Demo.LegacyProduct"

            Name: Annotated[str, Field(required=True)]

    assert any("_iris_classname is deprecated" in str(item.message) for item in captured)


def test_decorator_shims_warn() -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")

        @parameter("DEFAULTGLOBAL", "^Demo.ProductD")
        @index("NameIdx", properties="Name", unique=True)
        class Product(IRISModel):
            Name: Annotated[str, Field(required=True)]

            class Meta:
                classname = "Demo.DecoratedProduct"

    assert Product._iris_parameters == {"DEFAULTGLOBAL": "^Demo.ProductD"}
    assert Product._iris_indexes[0]["name"] == "NameIdx"
    assert any("index(...)" in str(item.message) for item in captured)
    assert any("parameter(...)" in str(item.message) for item in captured)


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
    assert schema.storage is not None
    assert schema.storage.data_location == "^Demo.ProductD"
    assert schema.storage.data[0].values == {"1": "%%CLASSNAME"}
    assert schema.storage.properties[0].average_field_size == "8"
    assert schema.storage.sql_maps[0].block_count == "-4"
