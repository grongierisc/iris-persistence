"""
Explicit session runtime for CRUD, queries, and transaction ownership.
"""
from __future__ import annotations

import datetime
from typing import Any

from .adapter import IRISAdapter
from .descriptors import _wrap_iris_obj
from .query import SessionQuery


class Session:
    def __init__(self, binder: Any, adapter: IRISAdapter | None = None) -> None:
        self.binder = binder
        self.adapter = adapter or binder.adapter
        self._identity_map: dict[tuple[type, str], Any] = {}
        self._pending: set[Any] = set()
        self._dirty: set[Any] = set()
        self._deleted: set[Any] = set()

    def add(self, instance: Any) -> Any:
        self.binder.bind_model(type(instance))
        object.__setattr__(instance, "_iris_session", self)
        self._pending.add(instance)
        return instance

    def delete(self, instance: Any) -> None:
        object.__setattr__(instance, "_iris_session", self)
        self._deleted.add(instance)
        self._pending.discard(instance)
        self._dirty.discard(instance)

    def get(self, model_class: type, obj_id: Any) -> Any | None:
        self.binder.bind_model(model_class)
        key = (model_class, str(obj_id))
        if key in self._identity_map:
            return self._identity_map[key]
        iris_obj = self.adapter.open_object(model_class._iris_classname, str(obj_id))  # type: ignore[attr-defined]
        if iris_obj in (None, ""):
            return None
        instance = _wrap_iris_obj(model_class, iris_obj, session=self)
        self._identity_map[key] = instance
        return instance

    def query(self, model_class: type) -> SessionQuery:
        self.binder.bind_model(model_class)
        return SessionQuery(self, model_class)

    def flush(self) -> None:
        saved: set[Any] = set()
        for instance in list(self._pending) + list(self._dirty):
            self._save_instance(instance, saved)

        for instance in list(self._deleted):
            obj_id = object.__getattribute__(instance, "_iris_id")
            if obj_id:
                self.adapter.delete_object(type(instance)._iris_classname, obj_id)  # type: ignore[attr-defined]
                self._identity_map.pop((type(instance), str(obj_id)), None)
            object.__setattr__(instance, "_iris_obj", None)
            object.__setattr__(instance, "_iris_id", None)
            self._deleted.discard(instance)

    def commit(self) -> None:
        self.adapter.begin()
        try:
            self.flush()
        except Exception:
            self.adapter.rollback()
            raise
        self.adapter.commit()

    def rollback(self) -> None:
        self.adapter.rollback()
        self._pending.clear()
        self._dirty.clear()
        self._deleted.clear()

    def _mark_dirty(self, instance: Any) -> None:
        if instance not in self._pending:
            self._dirty.add(instance)

    def _save_instance(self, instance: Any, saved: set[Any]) -> None:
        if instance in saved:
            return
        model_class = type(instance)
        schema = self.binder.schema_for(model_class)
        if getattr(model_class, "_iris_serial", False):
            self._materialize_serial(instance, saved)
            saved.add(instance)
            self._pending.discard(instance)
            self._dirty.discard(instance)
            object.__getattribute__(instance, "_iris_dirty_fields").clear()
            return

        iris_obj = object.__getattribute__(instance, "_iris_obj")
        if iris_obj is None:
            iris_obj = self.adapter.new_object(schema.name)
            object.__setattr__(instance, "_iris_obj", iris_obj)
            object.__setattr__(instance, "_iris_session", self)

        self._sync_runtime_fields(instance, schema, saved)
        status = iris_obj._Save()
        if not self.adapter.is_success_status(status):
            raise RuntimeError(f"_Save() failed for {schema.name!r}: {status!r}")
        obj_id = str(iris_obj._Id())
        object.__setattr__(instance, "_iris_id", obj_id)
        self._identity_map[(model_class, obj_id)] = instance
        self._pending.discard(instance)
        self._dirty.discard(instance)
        object.__getattribute__(instance, "_iris_dirty_fields").clear()
        saved.add(instance)

    def _materialize_serial(self, instance: Any, saved: set[Any]) -> Any:
        iris_obj = object.__getattribute__(instance, "_iris_obj")
        if iris_obj is None:
            iris_obj = self.adapter.new_object(type(instance)._iris_classname)  # type: ignore[attr-defined]
            object.__setattr__(instance, "_iris_obj", iris_obj)
        schema = self.binder.schema_for(type(instance))
        self._sync_runtime_fields(instance, schema, saved)
        return iris_obj

    def _sync_runtime_fields(self, instance: Any, schema: Any, saved: set[Any]) -> None:
        iris_obj = object.__getattribute__(instance, "_iris_obj")
        state = object.__getattribute__(instance, "_iris_data")
        for prop in schema.properties:
            if prop.name not in state:
                continue
            setattr(iris_obj, prop.name, self._serialize_value(state[prop.name], saved))
        for rel in schema.relationships:
            if rel.name not in state or rel.cardinality in {"children", "many"}:
                continue
            setattr(iris_obj, rel.name, self._serialize_value(state[rel.name], saved))

    def _serialize_value(self, value: Any, saved: set[Any]) -> Any:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, datetime.datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, datetime.date):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, datetime.time):
            return value.strftime("%H:%M:%S")
        if hasattr(value, "_iris_classname"):
            if getattr(type(value), "_iris_serial", False):
                return self._materialize_serial(value, saved)
            self._save_instance(value, saved)
            return object.__getattribute__(value, "_iris_obj")
        return value
