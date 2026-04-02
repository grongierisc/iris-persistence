from __future__ import annotations

import copy
import fnmatch
from typing import Any

from iris_orm.schema import SchemaClass


class FakeAdapter:
    def __init__(self) -> None:
        self.schemas: dict[str, dict[str, Any]] = {}
        self.rows: dict[str, dict[int, dict[str, Any]]] = {}
        self.next_ids: dict[str, int] = {}
        self.instance_methods: dict[str, dict[str, Any]] = {}
        self.class_methods: dict[str, dict[str, Any]] = {}

    def list_classes(self, pattern: str) -> list[str]:
        return sorted(name for name in self.schemas if fnmatch.fnmatch(name, pattern))

    def load_schema(self, classname: str) -> dict[str, Any] | None:
        payload = self.schemas.get(classname)
        return copy.deepcopy(payload) if payload is not None else None

    def replace_class(self, schema_class: SchemaClass) -> None:
        self.schemas[schema_class.name] = schema_class.to_dict()
        self.rows.setdefault(schema_class.name, {})
        self.next_ids.setdefault(schema_class.name, 1)

    def save_object(self, classname: str, data: dict[str, Any], obj_id: Any | None = None) -> Any:
        self.rows.setdefault(classname, {})
        self.next_ids.setdefault(classname, 1)
        if obj_id is None:
            obj_id = self.next_ids[classname]
            self.next_ids[classname] += 1
        self.rows[classname][int(obj_id)] = copy.deepcopy(data)
        return obj_id

    def open_object(self, classname: str, obj_id: Any) -> dict[str, Any] | None:
        row = self.rows.get(classname, {}).get(int(obj_id))
        if row is None:
            return None
        return {"id": int(obj_id), "data": copy.deepcopy(row)}

    def open_native_object(self, classname: str, obj_id: Any) -> Any | None:
        row = self.rows.get(classname, {}).get(int(obj_id))
        if row is None:
            return None
        adapter = self
        methods = self.instance_methods.get(classname, {})

        class NativeObject:
            pass

        obj = NativeObject()
        for key, value in row.items():
            setattr(obj, key, copy.deepcopy(value))
        for name, method in methods.items():
            setattr(obj, name, method.__get__(obj, NativeObject))
        return obj

    def native_class(self, classname: str) -> Any:
        methods = self.class_methods.get(classname, {})

        class NativeClass:
            pass

        native = NativeClass()
        for name, method in methods.items():
            setattr(native, name, method)
        return native

    def delete_object(self, classname: str, obj_id: Any) -> None:
        self.rows.get(classname, {}).pop(int(obj_id), None)

    def query_rows(
        self,
        classname: str,
        fields: list[str],
        filters: dict[str, Any],
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = []
        for obj_id, row in self.rows.get(classname, {}).items():
            if all(row.get(key) == value for key, value in filters.items()):
                payload = {"id": obj_id}
                for field in fields:
                    payload[field] = row.get(field)
                rows.append(payload)
        if order_by:
            rows.sort(key=lambda item: (item.get(order_by) is None, item.get(order_by)))
        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return rows

    # ------------------------------------------------------------------ stubs satisfying IRISRuntimeProtocol

    def sql(self, statement: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        return []

    def compile(self, classname: str) -> None:
        pass

    def looks_like_iris_object(self, value: Any) -> bool:
        return value is not None and value != ""

    def begin(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def preload_schema(adapter: FakeAdapter, payload: dict[str, Any]) -> None:
    properties = payload.get("properties", {})
    if isinstance(properties, dict):
        properties = [
            {
                "name": name,
                "iris_type": item.get("iris_type", "%String"),
                "required": bool(item.get("required", False)),
                "default": str(item.get("default", "") or ""),
                "maxlen": item.get("maxlen"),
                "description": str(item.get("description", "") or ""),
            }
            for name, item in properties.items()
        ]
    indexes = payload.get("indexes", {})
    if isinstance(indexes, dict):
        indexes = [
            {
                "name": name,
                "properties": item.get("properties", ""),
                "unique": bool(item.get("unique", False)),
                "primary_key": bool(item.get("primary_key", False)),
            }
            for name, item in indexes.items()
        ]
    adapter.schemas[str(payload["name"])] = {
        "name": str(payload["name"]),
        "superclasses": list(
            payload.get("superclasses")
            if payload.get("superclasses") is not None
            else [str(payload.get("superclass", "%Persistent"))]
        ),
        "properties": properties,
        "indexes": indexes,
        "parameters": dict(payload.get("parameters", {})),
        "storage": copy.deepcopy(payload.get("storage")),
        "source": {"kind": "fake"},
    }
    adapter.rows.setdefault(str(payload["name"]), {})
    adapter.next_ids.setdefault(str(payload["name"]), 1)
