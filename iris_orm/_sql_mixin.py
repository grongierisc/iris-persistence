from __future__ import annotations

from typing import Any

from .schema import (
    is_dynamic_type,
    is_list_of_datatypes,
    is_stream_type,
)


def _quote_sql_identifier(name: str) -> str:
    if name.startswith("%"):
        return str(name)
    return '"' + str(name).replace('"', '""') + '"'


def _quote_sql_classname(name: str) -> str:
    parts = str(name).split(".", 1)
    if len(parts) == 2:
        schema_name, relation_name = parts
    else:
        schema_name, relation_name = "SQLUser", parts[0]
    if schema_name == "User":
        schema_name = "SQLUser"
    return f"{schema_name}.{relation_name}"


class _SqlMixin:
    """SQL execution and data-level CRUD: save, open, delete, query.

    Depends on ``_IRISObjectMixin`` (``_object_new``, ``_object_open``,
    ``_object_delete_id``, ``_object_invoke``, ``_wrap_native_object``,
    ``looks_like_iris_object``, ``_check_status``), ``_SchemaMixin``
    (``load_schema``), and ``_PropertyValueMixin`` (``_read_property_value``,
    ``_write_stream_property``, ``_write_dynamic_property``,
    ``_coerce_runtime_value``, ``_use_iris_list_for_datatypes``,
    ``_iris_list_from_python``).
    """

    # ------------------------------------------------------------------ Raw SQL

    def sql(self, statement: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        params = params or []
        result = self.runtime.sql.exec(statement, *params)  # type: ignore[attr-defined]
        return [tuple(row) for row in result]

    # ------------------------------------------------------------------ Data CRUD

    def save_object(self, classname: str, data: dict[str, Any], obj_id: Any | None = None) -> Any:
        obj = self._object_open(classname, obj_id) if obj_id is not None else self._object_new(classname)  # type: ignore[attr-defined]
        schema = self.load_schema(classname) or {"properties": []}  # type: ignore[attr-defined]
        property_types = {item["name"]: item.get("iris_type", "%String") for item in schema.get("properties", [])}
        for key, value in data.items():
            iris_type = property_types.get(key, "%String")
            if is_stream_type(iris_type):
                self._write_stream_property(obj, key, value, iris_type)  # type: ignore[attr-defined]
                continue
            if is_dynamic_type(iris_type):
                self._write_dynamic_property(obj, key, value, iris_type)  # type: ignore[attr-defined]
                continue
            if is_list_of_datatypes(iris_type) and self._use_iris_list_for_datatypes():  # type: ignore[attr-defined]
                self._object_set(obj, key, None if value is None else self._iris_list_from_python(list(value)))  # type: ignore[attr-defined]
                continue
            self._object_set(obj, key, self._coerce_runtime_value(value, iris_type))  # type: ignore[attr-defined]
        self._check_status(self._object_invoke(obj, "%Save"))  # type: ignore[attr-defined]
        try:
            return self._object_invoke(obj, "%Id")  # type: ignore[attr-defined]
        except Exception:
            return obj_id

    def open_object(self, classname: str, obj_id: Any) -> dict[str, Any] | None:
        obj = self._object_open(classname, obj_id)  # type: ignore[attr-defined]
        if not self.looks_like_iris_object(obj):  # type: ignore[attr-defined]
            return None
        schema = self.load_schema(classname)  # type: ignore[attr-defined]
        if schema is None:
            return None
        data: dict[str, Any] = {}
        for prop in schema["properties"]:
            iris_type = str(prop.get("iris_type", "%String") or "%String")
            data[prop["name"]] = self._read_property_value(obj, prop["name"], iris_type)  # type: ignore[attr-defined]
        return {"id": obj_id, "data": data}

    def open_native_object(self, classname: str, obj_id: Any) -> Any | None:
        obj = self._object_open(classname, obj_id)  # type: ignore[attr-defined]
        if not self.looks_like_iris_object(obj):  # type: ignore[attr-defined]
            return None
        return self._wrap_native_object(obj, classname)  # type: ignore[attr-defined]

    def delete_object(self, classname: str, obj_id: Any) -> None:
        self._check_status(self._object_delete_id(classname, obj_id))  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ Query

    def query_rows(
        self,
        classname: str,
        fields: list[str],
        filters: dict[str, Any],
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        select_fields = ["%ID"] + fields
        sql_stmt = (
            f"SELECT {', '.join(_quote_sql_identifier(f) for f in select_fields)}"
            f" FROM {_quote_sql_classname(classname)}"
        )
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
        for row in rows:
            payload: dict[str, Any] = {"id": row[0]}
            for idx, f in enumerate(fields, start=1):
                payload[f] = row[idx]
            result.append(payload)
        return result
