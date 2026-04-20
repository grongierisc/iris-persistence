from typing import Any, Dict

from iris_orm.runtime import RuntimeAdapter


class FakeAdapter(RuntimeAdapter):
    """Simple CRUD-only test double.

    This adapter is intentionally narrow: it is useful for model/query tests but does
    not emulate IRIS schema compilation or %Dictionary metadata.
    """

    def __init__(self):
        self.db: Dict[str, Dict[str, Any]] = {}
        self._id_counter = 1
        self.last_sql: str | None = None
        self.last_params: tuple[Any, ...] | None = None

    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any:
        pass

    def create_object(self, class_name: str) -> Any:
        class _FakeObj:
            _classname = class_name

            def _Id(self):
                return getattr(self, "id_val", None)

            def __getattr__(self, name):
                if name == "_Id":
                    return self._Id
                raise AttributeError(name)

        obj = _FakeObj()
        obj._is_new = True
        return obj

    def save_object(self, obj: Any) -> Any:
        class_name = getattr(obj, "_classname", "Demo.Unknown")
        if class_name not in self.db:
            self.db[class_name] = {}

        if not hasattr(obj, "id_val") or obj.id_val is None:
            obj.id_val = str(self._id_counter)
            self._id_counter += 1

        data = {}
        for k in dir(obj):
            if not k.startswith("_") and k != "id_val" and not callable(getattr(obj, k)):
                data[k] = getattr(obj, k)

        self.db[class_name][obj.id_val] = data
        return True  # OK status

    def get_object(self, class_name: str, obj_id: str) -> Any:
        if class_name not in self.db or obj_id not in self.db[class_name]:
            return None
        data = self.db[class_name][obj_id]

        class _FakeObj:
            _classname = class_name

            def __init__(self, obj_id):
                self.id_val = obj_id

            def _Id(self):
                return self.id_val

        obj = _FakeObj(obj_id)
        for k, v in data.items():
            setattr(obj, k, v)
        return obj

    def delete_object(self, class_name: str, obj_id: str) -> bool:
        if class_name in self.db and obj_id in self.db[class_name]:
            del self.db[class_name][obj_id]
            return True
        return False

    def set_property(self, obj: Any, prop_name: str, value: Any) -> None:
        setattr(obj, prop_name, value)

    def get_property(self, obj: Any, prop_name: str) -> Any:
        return getattr(obj, prop_name, None)

    def invoke_method(self, obj: Any, method_name: str, *args: Any) -> Any:
        pass

    def get_object_id(self, obj: Any) -> str:
        return getattr(obj, "id_val", None)

    def is_ok(self, status: Any) -> bool:
        return status is True

    def format_status(self, status: Any) -> str:
        return str(status)

    def extract_python_value(self, val: Any) -> Any:
        return val

    def decode_percent_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def inject_iris_value(
        self,
        obj: Any,
        field_name: str,
        val: Any,
        field_meta: Any | None = None,
    ) -> None:
        setattr(obj, field_name, val)

    def get_dbapi_connection(self) -> Any:
        class _Cursor:
            def __init__(self, db):
                self._db = db
                self._rows = []

            def execute(self, sql, params=()):
                self._db_adapter.last_sql = sql
                self._db_adapter.last_params = tuple(params)
                table_name = sql.split("FROM ")[1].split(" ")[0].replace("_", ".")
                if table_name in self._db:
                    self._rows = [(k,) for k in self._db[table_name].keys()]
                else:
                    self._rows = []

            def fetchall(self):
                return self._rows

            def __iter__(self):
                return iter(self._rows)

            def close(self):
                pass

        class _Connection:
            def __init__(self, db, db_adapter):
                self._db = db
                self._db_adapter = db_adapter

            def cursor(self):
                cursor = _Cursor(self._db)
                cursor._db_adapter = self._db_adapter
                return cursor

            def close(self):
                pass

        return _Connection(self.db, self)


def preload_schema(*args, **kwargs):
    pass
