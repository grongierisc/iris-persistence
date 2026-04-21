import iris_orm.runtime as runtime_module
from iris_orm.models import Model
from iris_orm.query import _resolve_sql_table_name
from iris_orm.runtime import configure_default_runtime


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


class QueryFixture(Model):
    my_field: str

    class Meta:
        classname = "User.Simple"
        mode = "observe"


def test_resolve_sql_table_name_materializes_remote_rows_before_cursor_close():
    previous_runtime = runtime_module._active_runtime
    configure_default_runtime(_FakeRuntime())
    QueryFixture._sql_table_name = None

    try:
        assert _resolve_sql_table_name(QueryFixture) == "SQLUser.Simple"
    finally:
        runtime_module._active_runtime = previous_runtime
        QueryFixture._sql_table_name = None
