from dataclasses import dataclass
from inspect import signature
from typing import Annotated, Optional

import pytest

from iris_persistence import ClassMetadata, Field, Index, Model
from iris_persistence.runtime import configure_default_runtime
from iris_persistence.testing import InMemoryAdapter
from tests.fixtures.python.model_behavior_fixtures import (
    AutoSyncModel,
    ClassMetadataModel,
    FailingSaveModel,
    ManagedAutoSyncModel,
    ObserveAutoSyncModel,
    Product,
    QueryAliasModel,
    ReadonlyModel,
    ReplaceAutoSyncModel,
)


class LiteProduct(Model, persistent=True):
    Id: Optional[int] = Field(default=None, primary_key=True)
    Name: str = Field(required=True, max_length=200)
    Price: Annotated[float, Field(default=0.0)]
    InStock: bool = True
    Tags: list[str] = Field(default_factory=list, iris_type="%List")

    class Meta:
        classname = "Demo.LiteProduct"
        mode = "replace"


class IndexedProduct(Model, persistent=True):
    Id: Optional[int] = Field(default=None, primary_key=True, index_name="PK")
    Name: str = Field(required=True, unique=True, index_type="bitmap")
    Sku: str = Field(required=True, index=True)

    class Meta:
        classname = "Demo.IndexedProduct"
        mode = "replace"


class BaseInventoryItem(Model):
    Name: str
    Tags: list[str] = Field(default_factory=list)


class InventoryItem(BaseInventoryItem):
    Price: float = 0.0


class OrderLineModel(Model, serial=True):
    Sku: str
    Qty: int


class OrderModel(Model):
    Number: str
    Lines: list[OrderLineModel] = Field(default_factory=list)
    Lookup: dict[str, OrderLineModel] = Field(default_factory=dict)


@dataclass
class OrderLineDTO:
    Sku: str
    Qty: int


@dataclass
class OrderDTO:
    Number: str
    Lines: list[OrderLineDTO]
    Lookup: dict[str, OrderLineDTO]


@pytest.fixture(autouse=True)
def setup_fake_backend():
    adapter = InMemoryAdapter()
    configure_default_runtime(adapter)


def test_save_and_get():
    p = Product(Name="Widget", Price=12.5, InStock=True, Docs={"key": "value"}, Thumbnail=b"bytes")
    p.save()

    assert p.pk is not None

    p2 = Product.get(p.pk)
    assert p2 is not None
    assert p2.Name == "Widget"
    assert p2.Price == 12.5
    assert p2.InStock is True
    assert p2.Docs == {"key": "value"}
    assert p2.Thumbnail == b"bytes"


def test_query_all():
    p1 = Product(Name="A", Price=1)
    p2 = Product(Name="B", Price=2)
    p1.save()
    p2.save()

    products = list(Product.all())
    assert len(products) >= 2
    names = [x.Name for x in products]
    assert "A" in names
    assert "B" in names


def test_query_uses_sql_field_name():
    adapter = InMemoryAdapter()
    configure_default_runtime(adapter)

    QueryAliasModel.where(Payload="x").order_by("Payload").all()

    assert adapter.last_sql is not None
    assert "WHERE payload_json = ?" in adapter.last_sql
    assert "ORDER BY payload_json" in adapter.last_sql
    assert adapter.last_params == ("x",)


def test_readonly_field_is_not_updated_after_create():
    model = ReadonlyModel(Code="A1", Name="first")
    model.save()

    loaded = ReadonlyModel.get(model.pk)
    assert loaded is not None
    loaded.Code = "B2"
    loaded.Name = "second"
    loaded.save()

    reloaded = ReadonlyModel.get(model.pk)
    assert reloaded is not None
    assert reloaded.Code == "A1"
    assert reloaded.Name == "second"


def test_none_clears_nullable_scalar_fields_on_update():
    class NullableScalarUpdateModel(Model, persistent=True):
        Count: int | None = None
        Enabled: bool | None = None

    model = NullableScalarUpdateModel(Count=7, Enabled=True)
    model.save()

    model.Count = None
    model.Enabled = None
    model.save()

    loaded = NullableScalarUpdateModel.get(model.pk)

    assert loaded is not None
    assert loaded.Count is None
    assert loaded.Enabled is None


def test_absent_fields_do_not_clear_existing_values_on_update():
    class PartialScalarUpdateModel(Model, persistent=True):
        Count: int | None

    model = PartialScalarUpdateModel(Count=7)
    model.save()

    partial = PartialScalarUpdateModel()
    partial._pk = model.pk
    partial.save()

    loaded = PartialScalarUpdateModel.get(model.pk)

    assert loaded is not None
    assert loaded.Count == 7


def test_model_meta_sets_auto_sync_flag():
    assert AutoSyncModel._auto_sync is True
    assert Product._auto_sync is False


def test_model_meta_defaults_to_managed_sync_mode():
    class DefaultModeModel(Model):
        pass

    assert DefaultModeModel._sync_mode == "managed"


def test_plain_collection_annotations_infer_schema_collection():
    class CollectionAnnotationModel(Model):
        Tags: list[str] = Field(default_factory=list)
        Lookup: dict[str, str] = Field(default_factory=dict)
        PackedTags: list[str] = Field(default_factory=list, iris_type="%List")

    assert CollectionAnnotationModel._fields["Tags"].collection == "list"
    assert CollectionAnnotationModel._fields["Lookup"].collection == "array"
    assert CollectionAnnotationModel._fields["PackedTags"].collection is None


def test_model_meta_sets_class_metadata():
    assert ClassMetadataModel._class_metadata == ClassMetadata(
        description="class-level description",
        deprecated=True,
        final=True,
        sql_table_name="Demo_ClassMetadataModel",
        procedure_block=True,
    )


def test_auto_sync_calls_sync_schema_before_save(monkeypatch):
    calls = []

    def fake_sync_schema(cls):
        calls.append(cls)

    monkeypatch.setattr(AutoSyncModel, "sync_schema", classmethod(fake_sync_schema))

    model = AutoSyncModel(Name="demo")
    model.save()

    assert calls == [AutoSyncModel]
    assert model.pk is not None


def test_auto_sync_runs_once_per_model_process_cache(monkeypatch):
    calls = []

    def fake_sync_schema(cls):
        calls.append(cls)

    monkeypatch.setattr(AutoSyncModel, "sync_schema", classmethod(fake_sync_schema))

    first = AutoSyncModel(Name="first")
    second = AutoSyncModel(Name="second")
    first.save()
    second.save()
    first.to_iris()

    assert calls == [AutoSyncModel]
    assert first.pk is not None
    assert second.pk is not None


def test_auto_sync_rejects_observe_mode():
    with pytest.raises(RuntimeError, match="mode='observe'"):
        ObserveAutoSyncModel(Name="demo").save()


def test_auto_sync_rejects_replace_mode():
    with pytest.raises(RuntimeError, match="mode='replace'"):
        ReplaceAutoSyncModel(Name="demo").save()


def test_auto_sync_allows_managed_mode_without_process_cache(monkeypatch):
    calls = []

    def fake_sync_schema(cls):
        calls.append(cls)

    monkeypatch.setattr(ManagedAutoSyncModel, "sync_schema", classmethod(fake_sync_schema))

    first = ManagedAutoSyncModel(Name="first")
    second = ManagedAutoSyncModel(Name="second")
    first.save()
    second.save()

    assert calls == [ManagedAutoSyncModel, ManagedAutoSyncModel]
    assert first.pk is not None
    assert second.pk is not None


def test_save_failure_uses_formatted_status_message(monkeypatch):
    class FailingAdapter(InMemoryAdapter):
        def save_object(self, obj):
            return "0 raw-status"

        def is_ok(self, status):
            return False

        def format_status(self, status):
            assert status == "0 raw-status"
            return "ERROR #5808: Key not unique"

    configure_default_runtime(FailingAdapter())
    monkeypatch.setattr(FailingSaveModel, "sync_schema", classmethod(lambda cls: None))

    with pytest.raises(
        RuntimeError,
        match=r"Save failed for Demo\.FailingSaveModel: ERROR #5808: Key not unique",
    ):
        FailingSaveModel(Name="demo").save()


def test_model_supports_field_assignment_syntax_and_runtime_values():
    product = LiteProduct(Name="Widget Pro")

    assert isinstance(product.Name, str)
    assert product.Name.split() == ["Widget", "Pro"]
    assert product.Price == 0.0
    assert product.InStock is True
    assert product.Tags == []
    assert product.__dict__["Name"] == "Widget Pro"
    assert getattr(LiteProduct, "Name", None) is None


def test_model_supports_mixed_syntax_and_persistence_round_trip():
    product = LiteProduct(Name="Widget", Tags=["a", "b"])
    product.save()

    loaded = LiteProduct.get(product.pk)

    assert loaded is not None
    assert loaded.Name == "Widget"
    assert loaded.Price == 0.0
    assert loaded.InStock is True
    assert loaded.Tags == ["a", "b"]


def test_model_default_factory_is_per_instance():
    first = LiteProduct(Name="First")
    second = LiteProduct(Name="Second")

    first.Tags.append("x")

    assert first.Tags == ["x"]
    assert second.Tags == []


def test_model_inheritance_collects_base_fields():
    item = InventoryItem(Name="Widget", Tags=["inventory"], Price=12.5)

    assert list(InventoryItem.__model_fields__) == ["Name", "Tags", "Price"]
    assert list(signature(InventoryItem).parameters) == ["Name", "Tags", "Price"]
    assert item.Name == "Widget"
    assert item.Tags == ["inventory"]
    assert item.Price == 12.5


def test_model_to_dict_and_from_dict_include_inherited_fields():
    item = InventoryItem.from_dict({"Name": "Widget", "Tags": ["a"], "Price": 10.0})

    assert isinstance(item, InventoryItem)
    assert item.to_dict() == {"Name": "Widget", "Tags": ["a"], "Price": 10.0}


def test_model_dict_conversion_recurses_nested_models():
    order = OrderModel.from_dict(
        {
            "Number": "A100",
            "Lines": [{"Sku": "SKU-1", "Qty": 2}],
            "Lookup": {"primary": {"Sku": "SKU-2", "Qty": 3}},
        }
    )

    assert isinstance(order.Lines[0], OrderLineModel)
    assert isinstance(order.Lookup["primary"], OrderLineModel)
    assert order.to_dict() == {
        "Number": "A100",
        "Lines": [{"Sku": "SKU-1", "Qty": 2}],
        "Lookup": {"primary": {"Sku": "SKU-2", "Qty": 3}},
    }


def test_model_dataclass_conversion_recurses_nested_dtos():
    order = OrderModel(
        Number="A100",
        Lines=[OrderLineModel(Sku="SKU-1", Qty=2)],
        Lookup={"primary": OrderLineModel(Sku="SKU-2", Qty=3)},
    )

    dto = order.to_dataclass(OrderDTO)

    assert dto == OrderDTO(
        Number="A100",
        Lines=[OrderLineDTO(Sku="SKU-1", Qty=2)],
        Lookup={"primary": OrderLineDTO(Sku="SKU-2", Qty=3)},
    )


def test_model_from_dataclass_recurses_nested_dtos():
    dto = OrderDTO(
        Number="A100",
        Lines=[OrderLineDTO(Sku="SKU-1", Qty=2)],
        Lookup={"primary": OrderLineDTO(Sku="SKU-2", Qty=3)},
    )

    order = OrderModel.from_dataclass(dto)

    assert isinstance(order, OrderModel)
    assert isinstance(order.Lines[0], OrderLineModel)
    assert isinstance(order.Lookup["primary"], OrderLineModel)
    assert order.to_dict() == {
        "Number": "A100",
        "Lines": [{"Sku": "SKU-1", "Qty": 2}],
        "Lookup": {"primary": {"Sku": "SKU-2", "Qty": 3}},
    }


def test_dataclass_conversion_rejects_wrong_inputs():
    item = InventoryItem(Name="Widget")

    with pytest.raises(TypeError, match="dataclass type"):
        item.to_dataclass(dict)

    with pytest.raises(TypeError, match="dataclass instance"):
        InventoryItem.from_dataclass({"Name": "Widget"})


def test_model_signature_exposes_normalized_constructor_fields():
    params = signature(LiteProduct).parameters

    assert list(params) == ["Id", "Name", "Price", "InStock", "Tags"]
    assert params["Name"].default is params["Name"].empty
    assert params["Price"].default == 0.0
    assert params["InStock"].default is True


def test_model_rejects_unknown_fields():
    with pytest.raises(TypeError, match="unexpected keyword argument|Unknown field"):
        LiteProduct(Name="Widget", Missing=True)


def test_model_rejects_ambiguous_dual_field_declarations():
    with pytest.raises(TypeError, match="cannot declare Field"):
        class BadModel(Model):
            Name: Annotated[str, Field(max_length=100)] = Field(required=True)


def test_model_generates_real_constructor_per_class():
    assert LiteProduct.__dict__["__init__"] is not Model.__init__
    assert list(signature(LiteProduct.__init__).parameters) == [
        "self",
        "Id",
        "Name",
        "Price",
        "InStock",
        "Tags",
    ]


def test_model_init_subclass_accepts_model_keywords():
    params = signature(Model.__init_subclass__).parameters

    assert "persistent" in params
    assert "serial" in params
    assert "superclasses" in params


def test_field_index_metadata_synthesizes_model_indexes():
    indexes = {index.name: index for index in IndexedProduct._indexes}

    assert indexes["PK"].properties == "Id"
    assert indexes["PK"].primary_key is True
    assert indexes["PK"].unique is True
    assert indexes["NameIdx"].properties == "Name"
    assert indexes["NameIdx"].unique is True
    assert indexes["NameIdx"].type == "bitmap"
    assert indexes["SkuIdx"].properties == "Sku"
    assert indexes["SkuIdx"].unique is False


def test_field_index_metadata_conflicts_with_meta_indexes():
    with pytest.raises(TypeError, match="Meta.indexes already defines index"):
        class BadIndexedModel(Model, persistent=True):
            Name: str = Field(required=True, unique=True)

            class Meta:
                classname = "Demo.BadIndexedModel"
                mode = "replace"
                indexes = [Index("ExistingNameIdx", properties="Name")]


def test_model_class_flags_control_superclasses():
    class PersistentModel(Model, persistent=True):
        Name: str

    class SerialModel(Model, serial=True):
        Name: str

    assert PersistentModel._superclasses == "%Persistent"
    assert SerialModel._superclasses == "%SerialObject"


@pytest.mark.parametrize("field_name", ["pk", "_pk", "_iris_obj"])
def test_model_rejects_reserved_field_names(field_name):
    with pytest.raises(TypeError, match="reserved field name"):
        namespace = {"__annotations__": {field_name: str}}
        ModelMeta = type(Model)
        ModelMeta("BadReservedModel", (Model,), namespace)
