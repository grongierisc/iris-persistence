from contextlib import contextmanager
from typing import Any

import pytest

import iris_persistence.runtime as runtime_module
from iris_persistence import Field
from iris_persistence.models import Model
from iris_persistence.query import (
    _build_model_from_iris_obj,
    _resolve_sql_table_name,
    from_iris,
    materialize,
    save_model,
)
from iris_persistence.runtime import install_runtime
from iris_persistence.testing import InMemoryAdapter


class _CursorBoundRow:
    def __init__(self, values, cursor):
        self._values = values
        self._cursor = cursor

    def __iter__(self):
        if self._cursor.closed:
            raise RuntimeError("row became inaccessible after cursor close")
        return iter(self._values)


class _FakeCursor:
    def __init__(self):
        self.closed = False

    def execute(self, sql, params=()):
        self.sql = sql
        self.params = params

    def fetchone(self):
        return _CursorBoundRow(("Simple", "SQLUser"), self)

    def close(self):
        self.closed = True


class _FakeConnection:
    def cursor(self):
        return _FakeCursor()

    def close(self):
        pass


class _FakeRuntime:
    def get_dbapi_connection(self):
        return _FakeConnection()

    @contextmanager
    def connection(self):
        connection = self.get_dbapi_connection()
        try:
            yield connection
        finally:
            connection.close()


class _FailingMetadataRuntime:
    def get_dbapi_connection(self):
        raise RuntimeError("metadata unavailable")

    @contextmanager
    def connection(self):
        yield self.get_dbapi_connection()


class _ClosingCursor:
    def __init__(self, rows):
        self.rows = rows
        self.closed = False

    def execute(self, sql, params=()):
        self.sql = sql
        self.params = params

    def __iter__(self):
        return iter(self.rows)

    def close(self):
        self.closed = True


class _ClosingConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


class QueryFixture(Model):
    my_field: str

    class Meta:
        classname = "User.Simple"
        mode = "observe"


class _FakeClassRef:
    def __init__(self, obj):
        self._obj = obj

    def _New(self):
        return self._obj


class _SaveRuntime:
    def __init__(self):
        self.obj = type("FakeIRISObject", (), {})()
        self.set_calls = []

    def new_object(self, class_name):
        return self.obj

    def set_property(self, obj, prop_name, value):
        self.set_calls.append((prop_name, value))
        setattr(obj, prop_name, value)

    def inject_iris_value(self, obj, field_name, val, field_meta=None):
        self.set_property(obj, field_name, val)

    def save_object(self, obj):
        return True

    def is_ok(self, status):
        return bool(status)

    def format_status(self, status):
        return str(status)

    def check_status(self, status, operation):
        if not self.is_ok(status):
            raise RuntimeError(f"{operation} failed: {self.format_status(status)}")

    def get_object_id(self, obj):
        return "1"

    def extract_python_value(self, val):
        return val

    def extract_typed_python_value(self, val, collection_kind):
        return val

    def clear_reference(self, obj, field_name, *, serial=False):
        self.set_property(obj, field_name, "")
        return True


class _NativeOref:
    def __init__(self):
        self.set_calls = []

    def get(self, field_name):
        return object()

    def invoke(self, method_name, *args):
        if method_name != "Clear":
            raise AttributeError(method_name)
        return None

    def set(self, field_name, value):
        self.set_calls.append((field_name, value))


class _NativeHandleObject:
    def __init__(self):
        self._oref = _NativeOref()
        self._db = object()


class _NativeEmptyReferenceRuntime(runtime_module.IRISRuntime):
    def __init__(self):
        self.obj = _NativeHandleObject()

    def new_object(self, class_name):
        return self.obj

    def get_object(self, class_name, obj_id):
        return self.obj

    def save_object(self, obj):
        return True

    def is_ok(self, status):
        return bool(status)

    def format_status(self, status):
        return str(status)

    def get_object_id(self, obj):
        return "1"


class _ReferenceClearObject:
    def __init__(self):
        self.clear_calls = []

    def ChildSetObjectId(self, object_id):
        self.clear_calls.append(("ChildSetObjectId", object_id))


class _ReferenceClearRuntime(_SaveRuntime):
    def __init__(self):
        super().__init__()
        self.obj = _ReferenceClearObject()

    def get_object(self, class_name, obj_id):
        return self.obj

    def invoke_method(self, obj, method_name, *args):
        return getattr(obj, method_name)(*args)

    def clear_reference(self, obj, field_name, *, serial=False):
        self.invoke_method(obj, f"{field_name}SetObjectId", "")
        return True


class _NativeAndReferenceClearObject(_ReferenceClearObject):
    def __init__(self):
        super().__init__()
        self._oref = _NativeOref()
        self._db = object()


class _NativeAndReferenceClearRuntime(_ReferenceClearRuntime):
    def __init__(self):
        super().__init__()
        self.obj = _NativeAndReferenceClearObject()

    def clear_reference(self, obj, field_name, *, serial=False):
        return runtime_module.IRISRuntime.clear_reference(
            self,
            obj,
            field_name,
            serial=serial,
        )


class _NativeReferenceMethodOref(_NativeOref):
    def __init__(self):
        super().__init__()
        self.invoke_calls = []

    def invoke(self, method_name, *args):
        if method_name == "ChildSetObjectId":
            self.invoke_calls.append((method_name, *args))
            return None
        return super().invoke(method_name, *args)


class _NativeReferenceMethodObject:
    def __init__(self):
        self._oref = _NativeReferenceMethodOref()
        self._db = object()


class _NativeReferenceMethodRuntime(_NativeEmptyReferenceRuntime):
    def __init__(self):
        self.obj = _NativeReferenceMethodObject()


def test_resolve_sql_table_name_materializes_remote_rows_before_cursor_close():
    previous_runtime = runtime_module._active_runtime
    install_runtime(_FakeRuntime())
    QueryFixture._sql_table_name = None

    try:
        assert _resolve_sql_table_name(QueryFixture) == "SQLUser.Simple"
    finally:
        runtime_module._active_runtime = previous_runtime
        QueryFixture._sql_table_name = None


def test_resolve_sql_table_name_warns_when_metadata_lookup_fails():
    previous_runtime = runtime_module._active_runtime
    install_runtime(_FailingMetadataRuntime())
    QueryFixture._sql_table_name = None

    try:
        with pytest.warns(RuntimeWarning, match="Could not resolve SQL table name"):
            assert _resolve_sql_table_name(QueryFixture) == "User.Simple"
    finally:
        runtime_module._active_runtime = previous_runtime
        QueryFixture._sql_table_name = None


def test_queryset_rejects_unknown_where_field():
    QueryFixture._sql_table_name = "User.Simple"

    try:
        with pytest.raises(ValueError, match="Unknown field"):
            QueryFixture.where(**{"my_field; DROP": "x"}).all()
    finally:
        QueryFixture._sql_table_name = None


def test_queryset_rejects_unknown_order_by_field():
    QueryFixture._sql_table_name = "User.Simple"

    try:
        with pytest.raises(ValueError, match="Unknown field"):
            QueryFixture.where().order_by("my_field; DROP").all()
    finally:
        QueryFixture._sql_table_name = None


def test_queryset_all_closes_cursor_and_connection(monkeypatch):
    cursor = _ClosingCursor(rows=[("1",), ("2",)])
    connection = _ClosingConnection(cursor)

    class _Runtime:
        def get_dbapi_connection(self):
            return connection

        @contextmanager
        def connection(self):
            try:
                yield connection
            finally:
                connection.close()

    previous_runtime = runtime_module._active_runtime
    install_runtime(_Runtime())
    QueryFixture._sql_table_name = "User.Simple"
    monkeypatch.setattr(QueryFixture, "get", classmethod(lambda cls, pk: f"obj-{pk}"))

    try:
        assert QueryFixture.all() == ["obj-1", "obj-2"]
    finally:
        runtime_module._active_runtime = previous_runtime
        QueryFixture._sql_table_name = None

    assert cursor.closed is True
    assert connection.closed is True


def test_save_casts_string_none_to_iris_empty_string_marker_generic_path():
    import datetime

    class NullableStringFixture(Model):
        Name: str | None = None
        CreatedAt: datetime.datetime | None = None

        class Meta:
            classname = "Demo.NullableStringFixture"

    previous_runtime = runtime_module._active_runtime
    runtime = _SaveRuntime()
    install_runtime(runtime)

    try:
        save_model(NullableStringFixture(Name=None))
    finally:
        runtime_module._active_runtime = previous_runtime

    assert ("Name", chr(0)) in runtime.set_calls


def test_fast_save_casts_string_none_to_iris_empty_string_marker():
    class FastNullableStringFixture(Model):
        Name: str | None = None

    obj = type("FakeIRISObject", (), {})()

    FastNullableStringFixture._fast_save(obj, {"Name": None})

    assert obj.Name == chr(0)


def test_fast_save_clears_nullable_scalar_none_values():
    class FastNullableScalarFixture(Model):
        Count: int | None = None
        Enabled: bool | None = None

    obj = type("FakeIRISObject", (), {"Count": 7, "Enabled": 1})()

    FastNullableScalarFixture._fast_save(obj, {"Count": None, "Enabled": None})

    assert obj.Count == ""
    assert obj.Enabled == ""


def test_fast_save_does_not_touch_absent_fields():
    class FastPartialFixture(Model):
        Count: int | None

    obj = type("FakeIRISObject", (), {"Count": 7})()

    FastPartialFixture._fast_save(obj, {})

    assert obj.Count == 7


def test_fast_load_casts_iris_empty_string_marker_to_none():
    class FastLoadNullableStringFixture(Model):
        Name: str | None = None

    iris_obj = type("FakeIRISObject", (), {"Name": chr(0)})()

    loaded = _build_model_from_iris_obj(FastLoadNullableStringFixture, iris_obj, known_pk="1")

    assert loaded is not None
    assert loaded.Name is None


def test_generic_load_casts_iris_empty_string_marker_to_none():
    import datetime

    class GenericLoadNullableStringFixture(Model):
        Name: str | None = None
        CreatedAt: datetime.datetime | None = None

    previous_runtime = runtime_module._active_runtime
    install_runtime(_SaveRuntime())
    iris_obj = type("FakeIRISObject", (), {"Name": chr(0), "CreatedAt": ""})()

    try:
        loaded = _build_model_from_iris_obj(
            GenericLoadNullableStringFixture,
            iris_obj,
            known_pk="1",
        )
    finally:
        runtime_module._active_runtime = previous_runtime

    assert loaded is not None
    assert loaded.Name is None


@pytest.mark.parametrize("raw_null", ["", 0])
def test_load_casts_empty_related_object_reference_to_none(raw_null):
    class NullableRelatedAddress(Model, persistent=True):
        street: str
        city: str
        zip_code: str

    class NullableRelatedPerson(Model, persistent=True):
        name: str
        birth_address: NullableRelatedAddress | None = None

    previous_runtime = runtime_module._active_runtime
    install_runtime(InMemoryAdapter())
    iris_obj = type(
        "FakeIRISObject",
        (),
        {
            "name": "John Doe",
            "birth_address": raw_null,
        },
    )()

    try:
        loaded = _build_model_from_iris_obj(
            NullableRelatedPerson,
            iris_obj,
            known_pk="1",
        )
    finally:
        runtime_module._active_runtime = previous_runtime

    assert loaded is not None
    assert loaded.birth_address is None


def test_materialize_does_not_save_related_persistent_models():
    class MaterializeChild(Model, persistent=True):
        Name: str

    class MaterializeParent(Model, persistent=True):
        Child: MaterializeChild

    previous_runtime = runtime_module._active_runtime
    adapter = InMemoryAdapter()
    install_runtime(adapter)

    try:
        child = MaterializeChild(Name="nested")
        parent = MaterializeParent(Child=child)

        iris_obj = materialize(parent)

        assert parent.pk is None
        assert child.pk is None
        assert adapter.db == {}
        assert parent._iris_obj is iris_obj
        assert child._iris_obj is iris_obj.Child
        assert iris_obj.Child.Name == "nested"
    finally:
        runtime_module._active_runtime = previous_runtime


def test_materialize_uses_shared_population_path_for_serial_objects(monkeypatch):
    class FastSerialChild(Model, serial=True):
        Name: str | None = None

    class FastSerialParent(Model, persistent=True):
        Child: FastSerialChild

    previous_runtime = runtime_module._active_runtime
    adapter = InMemoryAdapter()
    install_runtime(adapter)
    calls = []
    original_fast_save = FastSerialChild._fast_save

    def wrapped_fast_save(iris_obj, inst_dict):
        calls.append(inst_dict.copy())
        original_fast_save(iris_obj, inst_dict)

    monkeypatch.setattr(FastSerialChild, "_fast_save", wrapped_fast_save)

    try:
        parent = FastSerialParent(Child=FastSerialChild(Name="nested"))

        iris_obj = materialize(parent)

        assert calls == [{"_pk": None, "_iris_obj": iris_obj.Child, "Name": "nested"}]
        assert iris_obj.Child.Name == "nested"
    finally:
        runtime_module._active_runtime = previous_runtime


def test_save_none_clears_nullable_complex_field():
    class NullableComplexFixture(Model, persistent=True):
        Payload: dict[str, str] | None = None

    previous_runtime = runtime_module._active_runtime
    adapter = InMemoryAdapter()
    install_runtime(adapter)

    try:
        model = NullableComplexFixture(Payload={"a": "b"})
        model.save()

        model.Payload = None
        model.save()

        assert adapter.db[NullableComplexFixture._classname][model.pk]["Payload"] is None
    finally:
        runtime_module._active_runtime = previous_runtime


def test_save_none_leaves_new_nullable_related_model_unset():
    class NativeNullChild(Model, persistent=True):
        Name: str

    class NativeNullParent(Model, persistent=True):
        Child: NativeNullChild | None = None

    previous_runtime = runtime_module._active_runtime
    runtime = _NativeEmptyReferenceRuntime()
    install_runtime(runtime)

    try:
        save_model(NativeNullParent(Child=None))
    finally:
        runtime_module._active_runtime = previous_runtime

    assert runtime.obj._oref.set_calls == []


def test_save_empty_string_leaves_new_nullable_related_model_unset():
    class NativeNullChild(Model, persistent=True):
        Name: str

    class NativeNullParent(Model, persistent=True):
        Child: NativeNullChild | None = None

    previous_runtime = runtime_module._active_runtime
    runtime = _NativeEmptyReferenceRuntime()
    install_runtime(runtime)

    try:
        model = NativeNullParent()
        model.Child = ""
        save_model(model)
    finally:
        runtime_module._active_runtime = previous_runtime

    assert runtime.obj._oref.set_calls == []


def test_save_none_clears_existing_nullable_related_model_with_native_empty_reference():
    class ExistingNativeNullChild(Model, persistent=True):
        Name: str

    class ExistingNativeNullParent(Model, persistent=True):
        Child: ExistingNativeNullChild | None = None

    previous_runtime = runtime_module._active_runtime
    runtime = _NativeEmptyReferenceRuntime()
    install_runtime(runtime)

    try:
        model = ExistingNativeNullParent(Child=None)
        model._pk = "7"
        save_model(model)
    finally:
        runtime_module._active_runtime = previous_runtime

    assert runtime.obj._oref.set_calls == [("Child", "")]


def test_save_empty_string_clears_existing_nullable_related_model_with_native_empty_reference():
    class ExistingNativeNullChild(Model, persistent=True):
        Name: str

    class ExistingNativeNullParent(Model, persistent=True):
        Child: ExistingNativeNullChild | None = None

    previous_runtime = runtime_module._active_runtime
    runtime = _NativeEmptyReferenceRuntime()
    install_runtime(runtime)

    try:
        model = ExistingNativeNullParent()
        model.Child = ""
        model._pk = "7"
        save_model(model)
    finally:
        runtime_module._active_runtime = previous_runtime

    assert runtime.obj._oref.set_calls == [("Child", "")]


def test_save_empty_string_clears_scaffold_style_nullable_reference_with_native_empty():
    class ExistingScaffoldStyleParent(Model, persistent=True):
        Child: Any | None = Field(iris_type="Demo.ReferenceChild", default=None)

    previous_runtime = runtime_module._active_runtime
    runtime = _NativeEmptyReferenceRuntime()
    install_runtime(runtime)

    try:
        model = ExistingScaffoldStyleParent()
        model.Child = ""
        model._pk = "7"
        save_model(model)
    finally:
        runtime_module._active_runtime = previous_runtime

    assert ExistingScaffoldStyleParent._save_fields["complex"][0].name == "Child"
    assert runtime.obj._oref.set_calls == [("Child", "")]


def test_save_none_clears_existing_nullable_related_model_with_object_id_setter():
    class ExistingClearChild(Model, persistent=True):
        Name: str

    class ExistingClearParent(Model, persistent=True):
        Child: ExistingClearChild | None = None

    previous_runtime = runtime_module._active_runtime
    runtime = _ReferenceClearRuntime()
    install_runtime(runtime)

    try:
        model = ExistingClearParent(Child=None)
        model._pk = "7"
        save_model(model)
    finally:
        runtime_module._active_runtime = previous_runtime

    assert runtime.obj.clear_calls == [("ChildSetObjectId", "")]
    assert runtime.set_calls == []


def test_save_empty_string_prefers_object_id_clear_over_native_empty_reference():
    class ExistingClearChild(Model, persistent=True):
        Name: str

    class ExistingClearParent(Model, persistent=True):
        Child: ExistingClearChild | None = None

    previous_runtime = runtime_module._active_runtime
    runtime = _NativeAndReferenceClearRuntime()
    install_runtime(runtime)

    try:
        model = ExistingClearParent()
        model.Child = ""
        model._pk = "7"
        save_model(model)
    finally:
        runtime_module._active_runtime = previous_runtime

    assert runtime.obj.clear_calls == [("ChildSetObjectId", "")]
    assert runtime.obj._oref.set_calls == []


def test_save_empty_string_invokes_native_object_id_clear_before_native_empty_reference():
    class ExistingClearChild(Model, persistent=True):
        Name: str

    class ExistingClearParent(Model, persistent=True):
        Child: ExistingClearChild | None = None

    previous_runtime = runtime_module._active_runtime
    runtime = _NativeReferenceMethodRuntime()
    install_runtime(runtime)

    try:
        model = ExistingClearParent()
        model.Child = ""
        model._pk = "7"
        save_model(model)
    finally:
        runtime_module._active_runtime = previous_runtime

    assert runtime.obj._oref.invoke_calls == [("ChildSetObjectId", "")]
    assert runtime.obj._oref.set_calls == []


def test_save_none_clears_nullable_date_with_empty_scalar_null():
    import datetime

    class NullableDateFixture(Model, persistent=True):
        EventDate: datetime.date | None = None

    previous_runtime = runtime_module._active_runtime
    runtime = _SaveRuntime()
    install_runtime(runtime)

    try:
        save_model(NullableDateFixture(EventDate=None))
    finally:
        runtime_module._active_runtime = previous_runtime

    assert ("EventDate", "") in runtime.set_calls


def test_save_reuses_materialized_iris_object_and_saves_related_model():
    class ReuseChild(Model, persistent=True):
        Name: str

    class ReuseParent(Model, persistent=True):
        Child: ReuseChild

    previous_runtime = runtime_module._active_runtime
    adapter = InMemoryAdapter()
    install_runtime(adapter)

    try:
        child = ReuseChild(Name="nested")
        parent = ReuseParent(Child=child)
        parent_iris_obj = parent.to_iris()
        child_iris_obj = child._iris_obj

        parent.save()

        assert parent.pk is not None
        assert child.pk is not None
        assert parent._iris_obj is parent_iris_obj
        assert child._iris_obj is child_iris_obj
        assert getattr(parent_iris_obj, "id_val") == parent.pk
        assert getattr(child_iris_obj, "id_val") == child.pk
        assert adapter.db[ReuseChild._classname][child.pk]["Name"] == "nested"
        assert adapter.db[ReuseParent._classname][parent.pk]["Child"] is child_iris_obj
    finally:
        runtime_module._active_runtime = previous_runtime


def test_from_iris_wraps_existing_object_handle():
    class FromIrisFixture(Model):
        Name: str
        Active: bool

    iris_obj = type("FakeIRISObject", (), {"Name": "demo", "Active": 1})()

    loaded = from_iris(FromIrisFixture, iris_obj, known_pk="7")
    method_loaded = FromIrisFixture.from_iris(iris_obj, known_pk="8")

    assert loaded is not None
    assert loaded.Name == "demo"
    assert loaded.Active is True
    assert loaded.pk == "7"
    assert loaded._iris_obj is iris_obj
    assert method_loaded is not None
    assert method_loaded.pk == "8"
