from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated
import warnings

import pytest

import iris_orm.runtime as runtime_module
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
from iris_orm.schema import SchemaClass, SchemaCompiler, SchemaIndex, SchemaProperty, schema_equals
from iris_orm.schema import read_dynamic_value
from iris_orm.scaffold import parse_cls
from iris_orm.testing import FakeAdapter, FakeIRISList, preload_schema


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
            mode = "replace"
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
            mode = "replace"
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


def test_default_extend_mode_keeps_live_members() -> None:
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
    assert Product._iris_state.mode == "extend"
    assert "OldField" in live.property_map
    assert "Price" in live.property_map
    assert "OldIdx" in live.index_map
    assert live.parameters["OLD"] == "1"


def test_explicit_extend_mode_overwrites_conflicting_types_without_removing_live_members() -> None:
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Product",
            "properties": {
                "LegacyOnly": {"iris_type": "%String"},
                "Price": {"iris_type": "%String"},
            },
            "indexes": {
                "LegacyIdx": {"properties": "LegacyOnly"},
            },
            "parameters": {"OLD": "1"},
        },
    )
    configure_default_runtime(runtime=adapter)

    class Product(IRISModel):
        Price: Annotated[float, Field(default=0.0)]
        Name: Annotated[str, Field(required=True)]

        class Meta:
            classname = "Demo.Product"
            mode = "extend"
            indexes = [Index("NameIdx", properties="Name", unique=True)]
            parameters = {"DEFAULTGLOBAL": "^Demo.ProductD"}

    Product.sync()
    live = SchemaCompiler(adapter).class_from_iris("Demo.Product")

    assert live.property_map["Price"].iris_type == "%Float"
    assert "LegacyOnly" in live.property_map
    assert "Name" in live.property_map
    assert "LegacyIdx" in live.index_map
    assert "NameIdx" in live.index_map
    assert live.parameters["OLD"] == "1"
    assert live.parameters["DEFAULTGLOBAL"] == "^Demo.ProductD"


def test_plan_uses_extend_merge_when_mode_is_extend() -> None:
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Product",
            "properties": {
                "LegacyOnly": {"iris_type": "%String"},
            },
            "indexes": {},
            "parameters": {},
        },
    )
    configure_default_runtime(runtime=adapter)

    class Product(IRISModel):
        Name: Annotated[str, Field(required=True)]

        class Meta:
            classname = "Demo.Product"
            mode = "extend"

    plan = Product.plan()
    assert "LegacyOnly" in plan.desired.property_map
    assert "Name" in plan.desired.property_map


def test_observe_mode_uses_live_schema_without_overwrite() -> None:
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
            mode = "observe"

    Article.bind()

    assert Article._iris_state.mode == "observe"
    assert "Title" in Article._iris_state.declared_fields
    assert Article._iris_state.storage is not None
    assert Article._iris_state.storage.data_location == "^Demo.ArticleD"
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


def test_default_runtime_falls_back_to_embedded_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    created: list[object] = []

    def fake_runtime_factory():
        created.append(sentinel)
        return sentinel

    monkeypatch.setattr(runtime_module, "EmbeddedRuntime", fake_runtime_factory)

    first = runtime_module._get_runtime()
    second = runtime_module._get_runtime()

    assert first is sentinel
    assert second is sentinel
    assert created == [sentinel]


def test_date_time_and_decimal_types_compile_and_roundtrip_defaults() -> None:
    class Event(IRISModel):
        EventDate: Annotated[date, Field(default=date(2024, 1, 2))]
        EventTime: Annotated[time, Field(default=time(3, 4, 5, 600000))]
        EventTimestamp: Annotated[datetime, Field(default=datetime(2024, 1, 2, 3, 4, 5, 600000))]
        Price: Annotated[Decimal, Field(default=Decimal("12.34"))]

        class Meta:
            classname = "Demo.Event"

    schema = SchemaCompiler().compile_model(Event)
    assert schema.property_map["EventDate"].iris_type == "%Date"
    assert schema.property_map["EventDate"].default == "66841"
    assert schema.property_map["EventTime"].iris_type == "%Time"
    assert schema.property_map["EventTime"].default == "11045.6"
    assert schema.property_map["EventTimestamp"].iris_type == "%TimeStamp"
    assert schema.property_map["EventTimestamp"].default == "2024-01-02 03:04:05.6"
    assert schema.property_map["Price"].iris_type == "%Decimal"
    assert schema.property_map["Price"].default == "12.34"

    assert Event._iris_state.declared_fields["EventDate"].default == date(2024, 1, 2)
    assert Event._iris_state.declared_fields["EventTime"].default == time(3, 4, 5, 600000)
    assert Event._iris_state.declared_fields["EventTimestamp"].default == datetime(2024, 1, 2, 3, 4, 5, 600000)
    assert Event._iris_state.declared_fields["Price"].default == Decimal("12.34")


def test_property_parameters_compile_and_bind() -> None:
    class Product(IRISModel):
        Status: Annotated[str, Field(iris_type="%String", parameters={"VALUELIST": ",Active,Inactive"})]
        Price: Annotated[Decimal, Field(iris_type="%Decimal", parameters={"SCALE": "2", "PRECISION": "10"})]

        class Meta:
            classname = "Demo.Product"

    schema = SchemaCompiler().compile_model(Product)
    assert schema.property_map["Status"].parameters == {"VALUELIST": ",Active,Inactive"}
    assert schema.property_map["Price"].parameters == {"SCALE": "2", "PRECISION": "10"}
    assert Product._iris_state.declared_fields["Price"].parameters == {"SCALE": "2", "PRECISION": "10"}


def test_property_parameters_roundtrip_with_fake_runtime() -> None:
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Product",
            "properties": {
                "Status": {"iris_type": "%String", "parameters": {"VALUELIST": ",Active,Inactive"}},
                "Price": {"iris_type": "%Decimal", "parameters": {"SCALE": "2", "PRECISION": "10"}},
            },
        },
    )
    configure_default_runtime(runtime=adapter)

    class Product(IRISModel):
        class Meta:
            classname = "Demo.Product"
            mode = "observe"

    Product.bind()
    assert Product._iris_state.declared_fields["Status"].parameters == {"VALUELIST": ",Active,Inactive"}
    assert Product._iris_state.declared_fields["Price"].parameters == {"SCALE": "2", "PRECISION": "10"}


def test_runtime_and_model_coercion_support_date_time_and_decimal() -> None:
    class DummyStream:
        def __init__(self, value):
            self.value = value

        def ReadAll(self):
            return self.value

    class DummyEmbeddedBinaryStream:
        def __init__(self, value):
            self.value = value
            self.rewound = False

        def Rewind(self):
            self.rewound = True

        def SizeGet(self):
            return len(self.value)

        def ReadSQL(self):
            return self.value.decode("latin-1")

        def Read(self, size=None):
            if size is None:
                raise RuntimeError("Method not found")
            return self.value[:size].decode("latin-1")

    assert runtime_module._BaseRuntime._coerce_runtime_value(date(2024, 1, 2), "%Date") == 66841
    assert runtime_module._BaseRuntime._coerce_runtime_value(time(3, 4, 5, 600000), "%Time") == "11045.6"
    assert runtime_module._BaseRuntime._coerce_runtime_value(datetime(2024, 1, 2, 3, 4, 5, 600000), "%TimeStamp") == "2024-01-02 03:04:05.6"
    assert runtime_module._BaseRuntime._coerce_runtime_value(Decimal("12.340"), "%Decimal") == "12.340"
    assert runtime_module._BaseRuntime._coerce_runtime_value(b"\x00\x01", "%Stream.GlobalBinary") == b"\x00\x01"
    assert runtime_module._BaseRuntime._coerce_runtime_value({"count": 2, "flag": True}, "%DynamicObject") == '{"count":2,"flag":true}'
    assert runtime_module._BaseRuntime._coerce_runtime_value(["a", 1], "%DynamicArray") == '["a",1]'

    assert IRISModel._coerce_python_value("66841", "%Date") == date(2024, 1, 2)
    assert IRISModel._coerce_python_value("11045.6", "%Time") == time(3, 4, 5, 600000)
    assert IRISModel._coerce_python_value("2024-01-02 03:04:05.6", "%TimeStamp") == datetime(2024, 1, 2, 3, 4, 5, 600000)
    assert IRISModel._coerce_python_value("12.340", "%Decimal") == Decimal("12.340")
    assert IRISModel._coerce_python_value(DummyStream("abc"), "%Stream.GlobalCharacter") == "abc"
    assert IRISModel._coerce_python_value(DummyEmbeddedBinaryStream(b"\x00\x01"), "%Stream.GlobalBinary") == b"\x00\x01"
    assert IRISModel._coerce_python_value('{"count":2,"flag":true}', "%DynamicObject") == {"count": 2, "flag": True}
    assert IRISModel._coerce_python_value('["a",1]', "%DynamicArray") == ["a", 1]
    assert IRISModel._coerce_python_value("", "%Float") is None

    class DummyRemoteBinaryStream:
        def invoke(self, method_name, *args):
            if method_name == "ReadAll":
                raise RuntimeError("method missing")
            if method_name == "ReadSQL":
                return "\x00\x01\xff"
            return None

        def invokeString(self, method_name, *args):
            if method_name == "ReadAll":
                raise RuntimeError("method missing")
            if method_name == "ReadSQL":
                return "\x00\x01\xff"
            return ""

    assert IRISModel._coerce_python_value(DummyRemoteBinaryStream(), "%Stream.GlobalBinary") == b"\x00\x01\xff"


def test_dynamic_object_defaults_compile_to_json_literals() -> None:
    class JsonDoc(IRISModel):
        Meta: Annotated[dict, Field(default={"flag": True}, iris_type="%DynamicObject")]
        Tags: Annotated[list, Field(default=["a", 1], iris_type="%DynamicArray")]

        class Meta:
            classname = "Demo.JsonDoc"

    schema = SchemaCompiler().compile_model(JsonDoc)

    assert schema.property_map["Meta"].default == '"{""flag"":true}"'
    assert schema.property_map["Tags"].default == '"[""a"",1]"'
    assert schema.property_map["Meta"].iris_type == "%DynamicObject"
    assert schema.property_map["Tags"].iris_type == "%DynamicArray"


def test_generic_dict_and_list_annotations_map_to_dynamic_types() -> None:
    class JsonDoc(IRISModel):
        Payload: dict[str, str]
        Tags: list[str]

        class Meta:
            classname = "Demo.JsonDocGenerics"

    schema = SchemaCompiler().compile_model(JsonDoc)

    assert schema.property_map["Payload"].iris_type == "%DynamicObject"
    assert schema.property_map["Tags"].iris_type == "%DynamicArray"


def test_dynamic_object_properties_roundtrip_with_fake_adapter() -> None:
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.JsonDoc",
            "properties": {
                "Meta": {"iris_type": "%DynamicObject"},
                "Tags": {"iris_type": "%DynamicArray"},
                "Title": {"iris_type": "%String", "required": True},
            },
        },
    )
    configure_default_runtime(runtime=adapter)

    class JsonDoc(IRISModel):
        Meta: Annotated[dict, Field(iris_type="%DynamicObject")]
        Tags: Annotated[list, Field(iris_type="%DynamicArray")]
        Title: Annotated[str, Field(required=True)]

        class Meta:
            classname = "Demo.JsonDoc"

    row = JsonDoc(Title="Hello", Meta={"flag": True, "count": 2}, Tags=["a", 1]).save()
    loaded = JsonDoc.get(row.pk)

    assert loaded is not None
    assert loaded.Meta == {"flag": True, "count": 2}
    assert loaded.Tags == ["a", 1]


def test_stream_properties_roundtrip_with_fake_adapter() -> None:
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Document",
            "properties": {
                "Body": {"iris_type": "%Stream.GlobalCharacter"},
                "Payload": {"iris_type": "%Stream.GlobalBinary"},
                "Title": {"iris_type": "%String", "required": True},
            },
        },
    )
    configure_default_runtime(runtime=adapter)

    class Document(IRISModel):
        Body: Annotated[str, Field(iris_type="%Stream.GlobalCharacter")]
        Payload: Annotated[bytes, Field(iris_type="%Stream.GlobalBinary")]
        Title: Annotated[str, Field(required=True)]

        class Meta:
            classname = "Demo.Document"

    row = Document(Title="Hello", Body="Long body", Payload=b"\x00\x01\x02").save()
    loaded = Document.get(row.pk)

    assert loaded is not None
    assert loaded.Body == "Long body"
    assert loaded.Payload == b"\x00\x01\x02"
    assert adapter.rows["Demo.Document"][1]["Body"].ReadAll() == "Long body"
    assert adapter.rows["Demo.Document"][1]["Payload"].ReadAll() == b"\x00\x01\x02"


def test_base_runtime_stream_save_and_open_use_stream_objects() -> None:
    class DummyStream:
        def __init__(self, *, binary: bool) -> None:
            self.binary = binary
            self.value: str | bytes = b"" if binary else ""
            self.rewound = False

        def Write(self, data):
            self.value = data

        def ReadAll(self):
            return self.value

        def Rewind(self):
            self.rewound = True

    class DummyObject:
        def __init__(self, obj_id=None) -> None:
            self._obj_id = obj_id

        def _Save(self):
            if self._obj_id is None:
                self._obj_id = 1
            objects[self._obj_id] = self
            return 1

        def _Id(self):
            return self._obj_id

    class DummyPersistentClass:
        def _New(self):
            return DummyObject()

        def _OpenId(self, obj_id):
            return objects.get(obj_id, "")

    class DummyStreamClass:
        def __init__(self, *, binary: bool) -> None:
            self.binary = binary

        def _New(self):
            return DummyStream(binary=self.binary)

    class DummyRuntime:
        def cls(self, classname):
            if classname == "Demo.StreamDoc":
                return DummyPersistentClass()
            if classname == "%Stream.GlobalCharacter":
                return DummyStreamClass(binary=False)
            if classname == "%Stream.GlobalBinary":
                return DummyStreamClass(binary=True)
            raise AssertionError(classname)

    class Harness(runtime_module._BaseRuntime):
        def __init__(self) -> None:
            self.runtime = DummyRuntime()

        def load_schema(self, classname: str):
            return {
                "name": classname,
                "properties": [
                    {"name": "Body", "iris_type": "%Stream.GlobalCharacter"},
                    {"name": "Payload", "iris_type": "%Stream.GlobalBinary"},
                ],
            }

    objects = {}
    runtime = Harness()

    obj_id = runtime.save_object("Demo.StreamDoc", {"Body": "abc", "Payload": b"\x01\x02"})
    opened = runtime.open_object("Demo.StreamDoc", obj_id)

    assert objects[1].Body.ReadAll() == "abc"
    assert objects[1].Body.rewound is True
    assert objects[1].Payload.ReadAll() == b"\x01\x02"
    assert objects[1].Payload.rewound is True
    assert opened == {"id": 1, "data": {"Body": "abc", "Payload": b"\x01\x02"}}


def test_base_runtime_dynamic_json_save_and_open_use_dynamic_objects() -> None:
    class DummyDynamicValue:
        def __init__(self, json_text: str) -> None:
            self.json_text = json_text

        def _ToJSON(self) -> str:
            return self.json_text

    class DummyObject:
        def __init__(self, obj_id=None) -> None:
            self._obj_id = obj_id

        def _Save(self):
            if self._obj_id is None:
                self._obj_id = 1
            objects[self._obj_id] = self
            return 1

        def _Id(self):
            return self._obj_id

    class DummyPersistentClass:
        def _New(self):
            return DummyObject()

        def _OpenId(self, obj_id):
            return objects.get(obj_id, "")

    class DummyDynamicClass:
        def _FromJSON(self, json_text):
            return DummyDynamicValue(json_text)

    class DummyRuntime:
        def cls(self, classname):
            if classname == "Demo.JsonDoc":
                return DummyPersistentClass()
            if classname in {"%DynamicObject", "%DynamicArray"}:
                return DummyDynamicClass()
            raise AssertionError(classname)

    class Harness(runtime_module._BaseRuntime):
        def __init__(self) -> None:
            self.runtime = DummyRuntime()

        def load_schema(self, classname: str):
            return {
                "name": classname,
                "properties": [
                    {"name": "Meta", "iris_type": "%DynamicObject"},
                    {"name": "Tags", "iris_type": "%DynamicArray"},
                ],
            }

    objects = {}
    runtime = Harness()

    obj_id = runtime.save_object("Demo.JsonDoc", {"Meta": {"flag": True}, "Tags": ["a", 1]})
    opened = runtime.open_object("Demo.JsonDoc", obj_id)

    assert objects[1].Meta.json_text == '{"flag":true}'
    assert objects[1].Tags.json_text == '["a",1]'
    assert opened == {"id": 1, "data": {"Meta": {"flag": True}, "Tags": ["a", 1]}}


def test_base_runtime_object_invoke_uses_embedded_percent_method_mapping() -> None:
    class EmbeddedLikeObject:
        def __getattr__(self, name):
            if name == "%Save":
                raise SystemError("Cannot modify a string currently used")
            raise AttributeError(name)

        def _Save(self):
            return 1

    assert runtime_module._BaseRuntime()._object_invoke(EmbeddedLikeObject(), "%Save") == 1


def test_embedded_runtime_query_rows_opens_each_object_by_id() -> None:
    class DummyObject:
        def __init__(self, obj_id, title, price):
            self._obj_id = obj_id
            self.Title = title
            self.Price = price

    class DummyPersistentClass:
        def _OpenId(self, obj_id):
            return objects.get(obj_id, "")

    class DummySQL:
        @staticmethod
        def exec(statement, *params):
            assert statement == 'SELECT %ID FROM Demo.Product WHERE "Price" = ? ORDER BY "Title"'
            assert list(params) == [2.0]
            return [(2,), (1,)]

    class DummyRuntime:
        sql = DummySQL()

        def cls(self, classname):
            if classname == "Demo.Product":
                return DummyPersistentClass()
            raise AssertionError(classname)

    class Harness(runtime_module.EmbeddedRuntime):
        def __init__(self) -> None:
            self.runtime = DummyRuntime()

        def load_schema(self, classname: str):
            return {
                "name": classname,
                "properties": [
                    {"name": "Title", "iris_type": "%String"},
                    {"name": "Price", "iris_type": "%Float"},
                ],
            }

    objects = {
        1: DummyObject(1, "A", 2.0),
        2: DummyObject(2, "B", 2.0),
    }
    rows = Harness().query_rows("Demo.Product", ["Title", "Price"], {"Price": 2.0}, order_by="Title")

    assert rows == [
        {"id": 2, "Title": "B", "Price": 2.0},
        {"id": 1, "Title": "A", "Price": 2.0},
    ]


def test_query_rows_quotes_user_package_classname() -> None:
    class DummySQL:
        @staticmethod
        def exec(statement, *params):
            captured.append(statement)
            return []

    captured: list[str] = []
    class Harness(runtime_module.EmbeddedRuntime):
        def __init__(self) -> None:
            self.runtime = type("DummyRuntime", (), {"sql": DummySQL()})()

        def load_schema(self, classname: str):
            return {"name": classname, "properties": [{"name": "Toto", "iris_type": "%String"}]}

        def _object_open(self, classname: str, obj_id):
            return ""

    runtime = Harness()
    runtime.query_rows("User.Demo", ["Toto"], {}, order_by="Toto")

    assert captured == ['SELECT %ID FROM SQLUser.Demo ORDER BY "Toto"']


def test_base_runtime_load_and_replace_property_parameters() -> None:
    class ParametersCollection(dict):
        def GetAt(self, key):
            return self.get(key, "")

        def SetAt(self, value, key):
            self[key] = value

        def RemoveAt(self, key):
            self.pop(key, None)

    class PropertyDefinition:
        def __init__(self, name="", parent=None):
            self.Name = name
            self.parent = parent
            self.Parameters = ParametersCollection()
            self.Required = False
            self.Type = "%String"
            self.InitialExpression = ""
            self.Description = ""

        def _Save(self):
            if self not in self.parent.Properties:
                self.parent.Properties.append(self)
            properties[f"{self.parent.Name}||{self.Name}"] = self
            return 1

        def ParametersGetAt(self, key):
            return self.Parameters.GetAt(key)

        def ParametersSetAt(self, value, key):
            self.Parameters.SetAt(value, key)

        def ParametersRemoveAt(self, key):
            self.Parameters.RemoveAt(key)

    class ClassDefinition:
        def __init__(self, name=""):
            self.Name = name
            self.Super = "%Persistent"
            self.Properties = []

        def _Save(self):
            classes[self.Name] = self
            return 1

    class DictionaryClassFactory:
        def __init__(self, kind):
            self.kind = kind

        def _OpenId(self, object_id):
            if self.kind == "%Dictionary.ClassDefinition":
                return classes.get(object_id, "")
            if self.kind == "%Dictionary.PropertyDefinition":
                return properties.get(object_id, "")
            return ""

        def _New(self):
            if self.kind == "%Dictionary.ClassDefinition":
                return ClassDefinition()
            if self.kind == "%Dictionary.PropertyDefinition":
                return PropertyDefinition()
            raise AssertionError(self.kind)

    class DummyRuntime:
        def cls(self, classname):
            return DictionaryClassFactory(classname)

    class Harness(runtime_module._BaseRuntime):
        def __init__(self):
            self.runtime = DummyRuntime()

        def sql(self, statement, params=None):
            if "FROM %Dictionary.PropertyDefinition" in statement and "SELECT Name" in statement:
                classname = params[0]
                return [(prop.Name,) for prop in properties.values() if prop.parent.Name == classname]
            if "FROM %Dictionary.IndexDefinition" in statement or "FROM %Dictionary.ParameterDefinition" in statement:
                return []
            return []

        def compile(self, classname):
            compiled.append(classname)

    classes = {"Demo.Product": ClassDefinition("Demo.Product")}
    existing = PropertyDefinition("Status", parent=classes["Demo.Product"])
    existing.ParametersSetAt(",Active,Inactive", "VALUELIST")
    classes["Demo.Product"].Properties.append(existing)
    properties = {"Demo.Product||Status": existing}
    compiled: list[str] = []
    runtime = Harness()

    loaded = runtime.load_schema("Demo.Product")
    assert loaded is not None
    assert loaded["properties"][0]["parameters"] == {"VALUELIST": ",Active,Inactive"}

    schema = SchemaCompiler().compile_model(
        type(
            "Product",
            (IRISModel,),
            {
                "__annotations__": {
                    "Status": Annotated[str, Field(iris_type="%String", parameters={"VALUELIST": ",Active,Inactive"})],
                    "Price": Annotated[Decimal, Field(iris_type="%Decimal", parameters={"SCALE": "2", "PRECISION": "10"})],
                },
                "Meta": type("Meta", (), {"classname": "Demo.Product", "mode": "replace"}),
            },
        )
    )

    runtime.replace_class(schema)

    assert properties["Demo.Product||Status"].Parameters == {"VALUELIST": ",Active,Inactive"}
    assert properties["Demo.Product||Price"].Parameters == {"SCALE": "2", "PRECISION": "10"}
    assert compiled == ["Demo.Product"]


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
            mode = "observe"

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
            mode = "observe"

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
            mode = "observe"
            superclasses = "Ens.Request"
            parameters = {"DEFAULTGLOBAL": "^Demo.MetaProductD"}

    assert Product._iris_classname == "Demo.MetaProduct"
    assert Product._iris_mode == "observe"
    assert Product._iris_superclasses == "Ens.Request"
    assert Product._iris_parameters == {"DEFAULTGLOBAL": "^Demo.MetaProductD"}


def test_default_classname_uses_user_package_and_python_class_name() -> None:
    class Product(IRISModel):
        Name: Annotated[str, Field(required=True)]

    class ExplicitBase(IRISModel):
        Name: Annotated[str, Field(required=True)]

        class Meta:
            classname = "Demo.BaseProduct"

    class DerivedProduct(ExplicitBase):
        Price: Annotated[float, Field(default=0.0)]

    assert Product._iris_classname == "User.Product"
    assert DerivedProduct._iris_classname == "User.DerivedProduct"


def test_meta_mode_validation_raises_at_class_definition_time() -> None:
    with pytest.raises(ValueError, match="Unsupported _iris_mode"):
        class Product(IRISModel):
            Name: Annotated[str, Field(required=True)]

            class Meta:
                classname = "Demo.InvalidProduct"
                mode = "Proxy"


def test_legacy_iris_mode_validation_raises_at_class_definition_time() -> None:
    with pytest.raises(ValueError, match="Unsupported _iris_mode"):
        class Product(IRISModel):
            _iris_classname = "Demo.InvalidLegacyProduct"
            _iris_mode = "Proxy"

            Name: Annotated[str, Field(required=True)]


def test_meta_storage_validation_raises_at_class_definition_time() -> None:
    with pytest.raises(TypeError, match=r"Unknown storage keys for Meta\.storage: data_locatoin"):
        class Product(IRISModel):
            Name: Annotated[str, Field(required=True)]

            class Meta:
                classname = "Demo.InvalidStorageProduct"
                storage = {"data_locatoin": "^Demo.ProductD"}


def test_legacy_storage_validation_raises_at_class_definition_time() -> None:
    with pytest.raises(TypeError, match=r"Unknown storage keys for _iris_storage: data_locatoin"):
        class Product(IRISModel):
            _iris_classname = "Demo.InvalidLegacyStorageProduct"
            _iris_storage = {"data_locatoin": "^Demo.ProductD"}

            Name: Annotated[str, Field(required=True)]


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




# ---------------------------------------------------------------------------
# Remote / NativeObjectProxy regression tests
#
# These replicate the exact behaviour of iris_utils.NativeObjectProxy without
# requiring a live IRIS connection.  Key gateway constraint: oref.get(name)
# NEVER raises — it returns "" for unknown names.  This trips up code that
# checks for callable attributes on the result.
# ---------------------------------------------------------------------------


class _GatewayORef:
    """Minimal fake of intersystems_iris.IRISObject (the raw oref)."""

    def __init__(self, props=None):
        self._props: dict = dict(props or {})
        self.invocations: list = []

    def get(self, name: str):
        # Gateway key behaviour: returns "" for unknown names, NEVER raises.
        return self._props.get(name, "")

    def set(self, name: str, value) -> None:
        # set() packs value into IRISList — fails for any ORef/Python-object.
        if not isinstance(value, (str, int, float, bytes, bool, type(None))):
            raise RuntimeError(
                f"<LIST ERROR> Incorrect list format, unsupported type for IRISList; "
                f"type detected : 36 ({type(value).__name__})"
            )
        self._props[name] = value

    def invoke(self, method_name: str, *args):
        self.invocations.append((method_name, args))
        return self._props.get(f"__invoke_{method_name}", None)


class _GatewayProxy:
    """Replicates iris_utils.NativeObjectProxy behaviour exactly."""

    def __init__(self, oref: _GatewayORef) -> None:
        object.__setattr__(self, "_oref", oref)

    def __getattr__(self, name: str):
        mapped = name.replace("_", "%", 1) if name.startswith("_") else name
        # Speculative property read — returns "" for unknown, never raises.
        val = self._oref.get(mapped)
        if val != "":
            return val  # non-callable scalar (e.g. "%Id" → "42" after %Save)
        # Returns "" → expose as a method proxy (callable).
        def method_proxy(*args):
            return self._oref.invoke(mapped, *args)
        return method_proxy

    def __setattr__(self, name: str, value) -> None:
        if name == "_oref":
            object.__setattr__(self, name, value)
            return
        mapped = name.replace("_", "%", 1) if name.startswith("_") else name
        self._oref.set(mapped, value)


def test_remote_object_invoke_returns_id_when_get_succeeds_non_callable() -> None:
    """Bug 1: NativeObjectProxy.get('%Id') returns the id string directly after
    %Save (speculative property read succeeds, value is non-callable).
    Old _object_invoke did ``method = getattr(obj, '_Id')`` → got "42" → tried
    to call "42"(*args) → TypeError.
    Fixed: if val is non-callable and no args, return val as-is."""
    oref = _GatewayORef(props={"%Id": "42"})
    proxy = _GatewayProxy(oref)

    class Harness(runtime_module._BaseRuntime):
        def __init__(self):
            self.runtime = None
        def sql(self, stmt, params=None):
            return []
        def load_schema(self, classname):
            return None
        def cls(self, classname):
            raise NotImplementedError

    result = Harness()._object_invoke(proxy, "%Id")
    assert result == "42"


def test_remote_write_stream_property_modifies_in_place_without_oref_arg() -> None:
    """Bug 2: assigning a new stream ORef via oref.set(prop, oref) or
    oref.invoke(PropSet, oref) fails over the gateway (IRISList can't encode
    ORef type 36).
    Fixed: _write_stream_property calls PropGet() to obtain the existing stream,
    then calls Clear()/Write(payload)/Rewind() on it in-place — no ORef is ever
    passed as an argument."""

    class TrackingStream:
        """Simulates a stream ORef returned by the getter method."""
        def __init__(self):
            self.calls: list = []

        def invoke(self, method_name, *args):
            self.calls.append((method_name, args))
            return None

    stream = TrackingStream()

    class Harness(runtime_module._BaseRuntime):
        def __init__(self):
            self.runtime = None
            self.set_calls: list = []

        def _object_invoke(self, obj, method_name, *args):
            if method_name == "BodyGet":
                return stream
            return super()._object_invoke(obj, method_name, *args)

        def _object_set(self, obj, prop_name, value):
            self.set_calls.append((prop_name, value))
            # Simulate gateway rejection of ORef args in set().
            if not isinstance(value, (str, int, float, bytes, bool, type(None))):
                raise RuntimeError("<LIST ERROR> type 36")

        def looks_like_iris_object(self, v):
            return v is stream  # stream is the "live" object

        def sql(self, stmt, params=None):
            return []

        def load_schema(self, classname):
            return None

        def cls(self, classname):
            raise NotImplementedError

    rt = Harness()
    rt._write_stream_property("fake_obj", "Body", "hello world", "%Stream.GlobalCharacter")

    # Stream was modified in-place — Write/Clear/Rewind called on existing ORef.
    call_names = [c[0] for c in stream.calls]
    assert "Clear" in call_names
    assert "Write" in call_names
    assert "Rewind" in call_names
    assert stream.calls[call_names.index("Write")][1] == ("hello world",)

    # _object_set was NEVER called — no ORef passed as an argument.
    assert rt.set_calls == []


def test_read_dynamic_value_bypasses_speculative_get_for_gateway_proxy() -> None:
    """Bug 3: NativeObjectProxy.__getattr__ calls oref.get() speculatively and
    returns "" (not callable) for unknown attribute names — including "_ToJSON",
    "ToJSON", "invoke", "invokeString".  Old read_dynamic_value fell through all
    callable checks and hit copy.deepcopy(proxy) → TypeError: cannot pickle.
    Fixed: bypass via value._oref.invoke('%ToJSON') directly."""
    oref = _GatewayORef(props={"__invoke_%ToJSON": '{"flag": true, "count": 3}'})
    proxy = _GatewayProxy(oref)

    result = read_dynamic_value(proxy)
    assert result == {"flag": True, "count": 3}
