"""
Data descriptors for IRIS properties and relationships.
"""
from __future__ import annotations

import datetime
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")

# Registry populated by IRISMeta; maps IRIS classname → Python model class.
# Imported here to avoid circular import — metaclass imports this module.
_MODEL_REGISTRY: dict[str, type] = {}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _wrap_iris_obj(model_class: type, iris_obj: Any) -> Any:
    """Wrap a raw IRIS object in a model class instance without calling __init__."""
    instance = object.__new__(model_class)
    object.__setattr__(instance, "_iris_obj", iris_obj)
    try:
        object.__setattr__(instance, "_iris_id", str(iris_obj._Id()))
    except Exception:
        object.__setattr__(instance, "_iris_id", None)
    return instance


# ---------------------------------------------------------------------------
# Plain property descriptor
# ---------------------------------------------------------------------------

class IRISDescriptor(Generic[T]):
    """Data descriptor that proxies a single IRIS persistent property."""

    def __init__(
        self,
        prop_name: str,
        python_type: type,
        required: bool = False,
    ) -> None:
        self.prop_name = prop_name
        self.python_type = python_type
        self.required = required

    def __set_name__(self, owner: type, name: str) -> None:
        self.attr_name = name

    # ------------------------------------------------------------------
    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        iris_obj = object.__getattribute__(obj, "_iris_obj")
        if iris_obj is None:
            return None
        raw = getattr(iris_obj, self.prop_name)
        return self._coerce(raw)

    def __set__(self, obj: Any, value: Any) -> None:
        iris_obj = object.__getattribute__(obj, "_iris_obj")
        if iris_obj is None:
            raise AttributeError(
                f"Cannot set '{self.prop_name}': IRIS object not loaded. "
                "Call model.create() or model._open() first."
            )
        setattr(iris_obj, self.prop_name, self._serialize(value))

    def __delete__(self, obj: Any) -> None:
        self.__set__(obj, None)

    # ------------------------------------------------------------------
    def _coerce(self, raw: Any) -> Any:
        """Convert a raw IRIS value to the Python type."""
        if raw is None or raw == "":
            return None
        from typing import Any as _Any
        if self.python_type is _Any:
            return raw
        # Already the right type
        if isinstance(raw, self.python_type):
            return raw
        try:
            # datetime.datetime must be tried before datetime.date because
            # datetime is a subclass of date.
            if self.python_type is datetime.datetime:
                if isinstance(raw, str):
                    return datetime.datetime.fromisoformat(raw)
                return raw
            if self.python_type is datetime.date:
                if isinstance(raw, str):
                    return datetime.date.fromisoformat(raw)
                return raw
            if self.python_type is datetime.time:
                if isinstance(raw, str):
                    return datetime.time.fromisoformat(raw)
                return raw
            return self.python_type(raw)
        except (ValueError, TypeError):
            return raw

    def _serialize(self, value: Any) -> Any:
        """Convert a Python value to something IRIS can accept."""
        if value is None:
            return ""
        if isinstance(value, datetime.datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, datetime.date):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, datetime.time):
            return value.strftime("%H:%M:%S")
        return value


# ---------------------------------------------------------------------------
# Relationship helpers
# ---------------------------------------------------------------------------

class IRISRelationshipManager:
    """Iterable proxy for a collection-side IRIS relationship."""

    def __init__(self, iris_collection: Any, related_model: type) -> None:
        self._collection = iris_collection
        self._related_model = related_model

    # ------------------------------------------------------------------
    def __iter__(self):
        count = int(self._collection.Count())
        for i in range(1, count + 1):
            iris_obj = self._collection.GetAt(i)
            yield _wrap_iris_obj(self._related_model, iris_obj)

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


# ---------------------------------------------------------------------------
# Relationship descriptor
# ---------------------------------------------------------------------------

class IRISRelationshipDescriptor:
    """Data descriptor that proxies an IRIS Relationship property."""

    def __init__(
        self,
        prop_name: str,
        related_classname: str,
        cardinality: str,
        inverse: str,
    ) -> None:
        self.prop_name = prop_name
        self.related_classname = related_classname
        self.cardinality = cardinality
        self.inverse = inverse

    def __set_name__(self, owner: type, name: str) -> None:
        self.attr_name = name

    # ------------------------------------------------------------------
    def _resolve_model(self) -> type:
        from .metaclass import _MODEL_REGISTRY as _REG
        model = _REG.get(self.related_classname)
        if model is None:
            raise LookupError(
                f"No model registered for IRIS class '{self.related_classname}'. "
                "Ensure the related model class is defined before accessing this relationship."
            )
        return model

    # ------------------------------------------------------------------
    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if obj is None:
            return self
        iris_obj = object.__getattribute__(obj, "_iris_obj")
        if iris_obj is None:
            return None

        related_model = self._resolve_model()
        raw = getattr(iris_obj, self.prop_name)

        if self.cardinality in ("parent", "one"):
            if raw is None:
                return None
            return _wrap_iris_obj(related_model, raw)
        else:  # children / many
            return IRISRelationshipManager(raw, related_model)

    def __set__(self, obj: Any, value: Any) -> None:
        if self.cardinality in ("children", "many"):
            raise AttributeError(
                f"Cannot assign to '{self.prop_name}': "
                "use .add() / .remove() on the relationship manager instead."
            )
        iris_obj = object.__getattribute__(obj, "_iris_obj")
        if iris_obj is None:
            raise AttributeError(
                f"Cannot set '{self.prop_name}': IRIS object not loaded."
            )
        if value is None:
            setattr(iris_obj, self.prop_name, None)
        else:
            related_iris_obj = object.__getattribute__(value, "_iris_obj")
            setattr(iris_obj, self.prop_name, related_iris_obj)
