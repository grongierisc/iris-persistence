from __future__ import annotations

from contextvars import ContextVar
import importlib
from typing import Any

from .protocol import IRISRuntimeProtocol
from ._object_mixin import _IRISObjectMixin
from ._value_mixin import _PropertyValueMixin
from ._schema_mixin import _SchemaMixin
from ._storage_mixin import _StorageMixin
from ._sql_mixin import _SqlMixin, _quote_sql_identifier, _quote_sql_classname


class _BaseRuntime(_IRISObjectMixin, _PropertyValueMixin, _SchemaMixin, _StorageMixin, _SqlMixin):
    """Composed ORM runtime.  Subclasses bind ``self.runtime`` to the IRIS native-API object."""

    runtime: Any


class EmbeddedRuntime(_BaseRuntime, IRISRuntimeProtocol):
    """Backend for the embedded InterSystems IRIS Python runtime (``iris`` module)."""

    def __init__(self, iris_module: Any | None = None) -> None:
        self.runtime = iris_module or importlib.import_module("iris")

    def query_rows(
        self,
        classname: str,
        fields: list[str],
        filters: dict[str, Any],
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        # Embedded: SELECT only %ID then open each object individually so that
        # stream/dynamic properties are read correctly via the IRIS object API.
        sql_stmt = f"SELECT {_quote_sql_identifier('%ID')} FROM {_quote_sql_classname(classname)}"
        params: list[Any] = []
        if filters:
            clauses = [f"{_quote_sql_identifier(key)} = ?" for key in filters]
            params.extend(filters.values())
            sql_stmt += " WHERE " + " AND ".join(clauses)
        if order_by:
            sql_stmt += f" ORDER BY {_quote_sql_identifier(order_by)}"
        if limit is not None:
            sql_stmt += f" LIMIT {int(limit)}"
        if offset:
            sql_stmt += f" OFFSET {int(offset)}"

        rows = self.sql(sql_stmt, params)
        result: list[dict[str, Any]] = []
        schema = self.load_schema(classname) or {"properties": []}
        property_types = {
            item["name"]: item.get("iris_type", "%String") for item in schema.get("properties", [])
        }
        for row in rows:
            obj_id = row[0]
            obj = self._object_open(classname, obj_id)
            if not self.looks_like_iris_object(obj):
                continue
            payload: dict[str, Any] = {"id": obj_id}
            for f in fields:
                iris_type = property_types.get(f, "%String")
                payload[f] = self._read_property_value(obj, f, iris_type)
            result.append(payload)
        return result


# ---------------------------------------------------------------------------
# Module-level default-runtime management
# ---------------------------------------------------------------------------

_DEFAULT_RUNTIME: ContextVar[IRISRuntimeProtocol | None] = ContextVar(
    "iris_orm_default_runtime", default=None
)
_RUNTIME_GENERATION = 0


def _get_runtime() -> IRISRuntimeProtocol:
    runtime = _DEFAULT_RUNTIME.get()
    if runtime is None:
        runtime = EmbeddedRuntime()
        _DEFAULT_RUNTIME.set(runtime)
    return runtime


def _runtime_version() -> int:
    return _RUNTIME_GENERATION


def reset_default_runtime() -> None:
    global _RUNTIME_GENERATION
    _DEFAULT_RUNTIME.set(None)
    _RUNTIME_GENERATION += 1


def configure(conn: Any | None = None) -> IRISRuntimeProtocol:
    """Primary entry point for connecting iris_orm to IRIS.

    In embedded mode (running inside IRIS) no argument is needed::

        import iris_orm
        iris_orm.configure()

    For remote mode, pass the IRIS native-API connection object returned by
    ``iris.createIRIS()``.  iris_orm calls ``iris.set_active_connection()`` so
    that all subsequent ``iris.cls()`` calls are routed to that connection::

        import iris, iris_orm
        conn = iris.createIRIS(iris.createConnection(host, port, ns, user, pw))
        iris_orm.configure(conn)

    Returns the registered runtime backend.
    """
    global _RUNTIME_GENERATION
    if conn is not None:
        import iris as _iris_module  # type: ignore[import]
        _iris_module.set_active_connection(conn)
    runtime: IRISRuntimeProtocol = EmbeddedRuntime()
    _DEFAULT_RUNTIME.set(runtime)
    _RUNTIME_GENERATION += 1
    return runtime
