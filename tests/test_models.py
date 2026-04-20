from typing import Annotated

import pytest

from iris_orm import ClassMetadata, Field, Index, IRISModel
from iris_orm.runtime import configure_default_runtime
from iris_orm.testing import FakeAdapter


@pytest.fixture(autouse=True)
def setup_fake_backend():
    adapter = FakeAdapter()
    configure_default_runtime(adapter)


class Product(IRISModel):
    Name: Annotated[str, Field(required=True, maxlen=200)]
    Price: Annotated[float, Field(default=0.0)]
    InStock: Annotated[bool, Field(default=True)]
    Docs: dict[str, str]
    Thumbnail: bytes

    class Meta:
        classname = "Demo.Product"
        mode = "replace"
        indexes = [Index("NameIdx", properties="Name", unique=True)]


class QueryAliasModel(IRISModel):
    Payload: Annotated[str | None, Field(sql_field_name="payload_json")] = None

    class Meta:
        classname = "Demo.QueryAliasModel"
        mode = "observe"


class ReadonlyModel(IRISModel):
    Code: Annotated[str | None, Field(readonly=True)] = None
    Name: Annotated[str | None, Field()] = None

    class Meta:
        classname = "Demo.ReadonlyModel"
        mode = "replace"


class AutoSyncModel(IRISModel):
    Name: Annotated[str | None, Field()] = None

    class Meta:
        classname = "Demo.AutoSyncModel"
        mode = "extend"
        auto_sync = True


class ObserveAutoSyncModel(IRISModel):
    Name: Annotated[str | None, Field()] = None

    class Meta:
        classname = "Demo.ObserveAutoSyncModel"
        mode = "observe"
        auto_sync = True


class ReplaceAutoSyncModel(IRISModel):
    Name: Annotated[str | None, Field()] = None

    class Meta:
        classname = "Demo.ReplaceAutoSyncModel"
        mode = "replace"
        auto_sync = True


class FailingSaveModel(IRISModel):
    Name: Annotated[str | None, Field()] = None

    class Meta:
        classname = "Demo.FailingSaveModel"
        mode = "observe"


class ClassMetadataModel(IRISModel):
    Name: Annotated[str | None, Field()] = None

    class Meta:
        classname = "Demo.ClassMetadataModel"
        metadata = ClassMetadata(
            description="class-level description",
            deprecated=True,
            final=True,
            sql_table_name="Demo_ClassMetadataModel",
            procedure_block=True,
        )


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
    adapter = FakeAdapter()
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


def test_model_meta_sets_auto_sync_flag():
    assert AutoSyncModel._auto_sync is True
    assert Product._auto_sync is False


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


def test_auto_sync_rejects_observe_mode():
    with pytest.raises(RuntimeError, match="mode='observe'"):
        ObserveAutoSyncModel(Name="demo").save()


def test_auto_sync_rejects_replace_mode():
    with pytest.raises(RuntimeError, match="mode='replace'"):
        ReplaceAutoSyncModel(Name="demo").save()


def test_save_failure_uses_formatted_status_message(monkeypatch):
    class FailingAdapter(FakeAdapter):
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
