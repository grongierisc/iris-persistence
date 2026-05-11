import iris_persistence.runtime as runtime_module
from iris_persistence.models import Model
from iris_persistence.query import _build_model_from_iris_obj, _resolve_sql_table_name, save_model
from iris_persistence.runtime import configure_default_runtime


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

    def _cls(self, class_name):
        return _FakeClassRef(self.obj)

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

    def get_object_id(self, obj):
        return "1"

    def extract_python_value(self, val):
        return val


def test_resolve_sql_table_name_materializes_remote_rows_before_cursor_close():
    previous_runtime = runtime_module._active_runtime
    configure_default_runtime(_FakeRuntime())
    QueryFixture._sql_table_name = None

    try:
        assert _resolve_sql_table_name(QueryFixture) == "SQLUser.Simple"
    finally:
        runtime_module._active_runtime = previous_runtime
        QueryFixture._sql_table_name = None


def test_queryset_all_closes_cursor_and_connection(monkeypatch):
    cursor = _ClosingCursor(rows=[("1",), ("2",)])
    connection = _ClosingConnection(cursor)

    class _Runtime:
        def get_dbapi_connection(self):
            return connection

    previous_runtime = runtime_module._active_runtime
    configure_default_runtime(_Runtime())
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
    configure_default_runtime(runtime)

    try:
        save_model(NullableStringFixture(Name=None))
    finally:
        runtime_module._active_runtime = previous_runtime
        NullableStringFixture._fast_new = None

    assert ("Name", chr(0)) in runtime.set_calls


def test_fast_save_casts_string_none_to_iris_empty_string_marker():
    class FastNullableStringFixture(Model):
        Name: str | None = None

    obj = type("FakeIRISObject", (), {})()

    FastNullableStringFixture._fast_save(obj, {"Name": None})

    assert obj.Name == chr(0)


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
    configure_default_runtime(_SaveRuntime())
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
