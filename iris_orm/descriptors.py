"""
Runtime descriptors installed by the explicit binder.
"""
from __future__ import annotations

import datetime
from typing import Any, Generic, TypeVar

T = TypeVar("T")

_BOUND_MODEL_REGISTRY: dict[str, type] = {}


def register_bound_model(model_class: type) -> None:
    classname = getattr(model_class, "_iris_classname", "")
    if classname:
        _BOUND_MODEL_REGISTRY[classname] = model_class


def _wrap_iris_obj(model_class: type, iris_obj: Any, *, session: Any = None) -> Any:
    instance = object.__new__(model_class)
    object.__setattr__(instance, "_iris_obj", iris_obj)
    object.__setattr__(instance, "_iris_data", {})
    object.__setattr__(instance, "_iris_dirty_fields", set())
    object.__setattr__(instance, "_iris_session", session)
    try:
        object.__setattr__(instance, "_iris_id", str(iris_obj._Id()))
    except Exception:
        object.__setattr__(instance, "_iris_id", None)
    return instance


class IRISDescriptor(Generic[T]):
    def __init__(self, prop_name: str, python_type: type, required: bool = False) -> None:
        self.prop_name = prop_name
        self.python_type = python_type
        self.required = required

    def __set_name__(self, owner: type, name: str) -> None:
        self.attr_name = name

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        iris_obj = object.__getattribute__(obj, "_iris_obj")
        if iris_obj is None:
            return object.__getattribute__(obj, "_iris_data").get(self.prop_name)
        raw = getattr(iris_obj, self.prop_name)
        return self._coerce(raw)

    def __set__(self, obj: Any, value: Any) -> None:
        object.__getattribute__(obj, "_iris_data")[self.prop_name] = value
        iris_obj = object.__getattribute__(obj, "_iris_obj")
        if iris_obj is not None:
            setattr(iris_obj, self.prop_name, self._serialize(value))
        obj._mark_dirty(self.prop_name)

    def _coerce(self, raw: Any) -> Any:
        if raw is None or raw == "":
            return None
        if self.python_type is Any:
            return raw
        if isinstance(raw, self.python_type):
            return raw
        try:
            if self.python_type is datetime.datetime and isinstance(raw, str):
                return datetime.datetime.fromisoformat(raw)
            if self.python_type is datetime.date and isinstance(raw, str):
                return datetime.date.fromisoformat(raw)
            if self.python_type is datetime.time and isinstance(raw, str):
                return datetime.time.fromisoformat(raw)
            return self.python_type(raw)
        except (TypeError, ValueError):
            return raw

    def _serialize(self, value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, datetime.datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, datetime.date):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, datetime.time):
            return value.strftime("%H:%M:%S")
        return value


class InMemoryRelationshipManager:
    def __init__(self, obj: Any, prop_name: str) -> None:
        self._obj = obj
        self._prop_name = prop_name
        state = object.__getattribute__(obj, "_iris_data")
        state.setdefault(prop_name, [])

    def __iter__(self):
        yield from list(object.__getattribute__(self._obj, "_iris_data").get(self._prop_name, []))

    def count(self) -> int:
        return len(object.__getattribute__(self._obj, "_iris_data").get(self._prop_name, []))

    def __len__(self) -> int:
        return self.count()

    def add(self, instance: Any) -> None:
        values = object.__getattribute__(self._obj, "_iris_data").setdefault(self._prop_name, [])
        values.append(instance)
        self._obj._mark_dirty(self._prop_name)

    def remove(self, instance: Any) -> None:
        values = object.__getattribute__(self._obj, "_iris_data").setdefault(self._prop_name, [])
        values.remove(instance)
        self._obj._mark_dirty(self._prop_name)


class IRISRelationshipManager:
    def __init__(self, iris_collection: Any, related_model: type, *, session: Any = None) -> None:
        self._collection = iris_collection
        self._related_model = related_model
        self._session = session

    def __iter__(self):
        count = int(self._collection.Count())
        for index in range(1, count + 1):
            yield _wrap_iris_obj(self._related_model, self._collection.GetAt(index), session=self._session)

    def count(self) -> int:
        return int(self._collection.Count())

    def __len__(self) -> int:
        return self.count()

    def add(self, instance: Any) -> None:
        iris_obj = object.__getattribute__(instance, "_iris_obj")
        self._collection.Insert(iris_obj)

    def remove(self, instance: Any) -> None:
        iris_obj = object.__getattribute__(instance, "_iris_obj")
        self._collection.RemoveAt(str(iris_obj._Id()))


class IRISRelationshipDescriptor:
    def __init__(self, prop_name: str, related_classname: str, cardinality: str, inverse: str) -> None:
        self.prop_name = prop_name
        self.related_classname = related_classname
        self.cardinality = cardinality
        self.inverse = inverse

    def __set_name__(self, owner: type, name: str) -> None:
        self.attr_name = name

    def _resolve_model(self) -> type:
        model = _BOUND_MODEL_REGISTRY.get(self.related_classname)
        if model is None:
            raise LookupError(f"No bound model registered for IRIS class {self.related_classname!r}")
        return model

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        iris_obj = object.__getattribute__(obj, "_iris_obj")
        if iris_obj is None:
            if self.cardinality in {"children", "many"}:
                return InMemoryRelationshipManager(obj, self.prop_name)
            return object.__getattribute__(obj, "_iris_data").get(self.prop_name)

        related_model = self._resolve_model()
        raw = getattr(iris_obj, self.prop_name)
        if self.cardinality in {"parent", "one"}:
            if raw is None:
                return None
            return _wrap_iris_obj(
                related_model,
                raw,
                session=object.__getattribute__(obj, "_iris_session"),
            )
        return IRISRelationshipManager(
            raw,
            related_model,
            session=object.__getattribute__(obj, "_iris_session"),
        )

    def __set__(self, obj: Any, value: Any) -> None:
        if self.cardinality in {"children", "many"}:
            raise AttributeError(
                f"Cannot assign to collection relationship {self.prop_name!r}; use .add()/.remove()."
            )
        object.__getattribute__(obj, "_iris_data")[self.prop_name] = value
        iris_obj = object.__getattribute__(obj, "_iris_obj")
        if iris_obj is not None:
            setattr(
                iris_obj,
                self.prop_name,
                None if value is None else object.__getattribute__(value, "_iris_obj"),
            )
        obj._mark_dirty(self.prop_name)


class IRISSerialDescriptor:
    def __init__(self, prop_name: str, serial_classname: str) -> None:
        self.prop_name = prop_name
        self.serial_classname = serial_classname

    def __set_name__(self, owner: type, name: str) -> None:
        self.attr_name = name

    def _resolve_model(self) -> type:
        model = _BOUND_MODEL_REGISTRY.get(self.serial_classname)
        if model is None:
            raise LookupError(f"No bound serial model registered for IRIS class {self.serial_classname!r}")
        return model

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        iris_obj = object.__getattribute__(obj, "_iris_obj")
        if iris_obj is None:
            return object.__getattribute__(obj, "_iris_data").get(self.prop_name)
        raw = getattr(iris_obj, self.prop_name)
        if raw in (None, ""):
            return None
        return _wrap_iris_obj(
            self._resolve_model(),
            raw,
            session=object.__getattribute__(obj, "_iris_session"),
        )

    def __set__(self, obj: Any, value: Any) -> None:
        object.__getattribute__(obj, "_iris_data")[self.prop_name] = value
        iris_obj = object.__getattribute__(obj, "_iris_obj")
        if iris_obj is not None:
            setattr(
                iris_obj,
                self.prop_name,
                None if value is None else object.__getattribute__(value, "_iris_obj"),
            )
        obj._mark_dirty(self.prop_name)
