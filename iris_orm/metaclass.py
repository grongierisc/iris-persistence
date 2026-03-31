"""
Declaration-only model metaclass and base classes.
"""
from __future__ import annotations

import copy
import typing
from typing import Any, ClassVar, Optional, get_type_hints

from .fields import FieldDefinition, RelationshipDefinition
from .types import python_type_to_iris, unwrap_optional

_MODEL_REGISTRY: dict[str, type] = {}


def _is_classvar(annotation: Any) -> bool:
    origin = getattr(annotation, "__origin__", None)
    if origin is ClassVar:
        return True
    if hasattr(typing, "ClassVar") and annotation is ClassVar:
        return True
    text = str(annotation)
    return text.startswith("typing.ClassVar") or text.startswith("ClassVar")


class IRISMeta(type):
    """Collect declaration metadata without touching live IRIS state."""

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type:
        cleaned = dict(namespace)
        raw_annotations: dict[str, Any] = dict(cleaned.get("__annotations__", {}))

        declared_fields: dict[str, FieldDefinition] = {}
        declared_relationships: dict[str, RelationshipDefinition] = {}
        for attr_name, value in list(cleaned.items()):
            if isinstance(value, FieldDefinition):
                declared_fields[attr_name] = copy.deepcopy(value)
                cleaned.pop(attr_name, None)
            elif isinstance(value, RelationshipDefinition):
                declared_relationships[attr_name] = copy.deepcopy(value)
                cleaned.pop(attr_name, None)

        cls = super().__new__(mcs, name, bases, cleaned, **kwargs)

        if not hasattr(cls, "_iris_declared_fields"):
            cls._iris_declared_fields = {}  # type: ignore[attr-defined]
        if not hasattr(cls, "_iris_declared_relationships"):
            cls._iris_declared_relationships = {}  # type: ignore[attr-defined]
        if not hasattr(cls, "_iris_class_parameters"):
            cls._iris_class_parameters = {}  # type: ignore[attr-defined]
        if not hasattr(cls, "_iris_indexes"):
            cls._iris_indexes = []  # type: ignore[attr-defined]
        if not hasattr(cls, "_iris_storage"):
            cls._iris_storage = None  # type: ignore[attr-defined]

        iris_classname = getattr(cls, "_iris_classname", "")
        if not iris_classname:
            return cls

        resolved = mcs._resolve_annotations(cls, raw_annotations)
        normalized_fields: dict[str, FieldDefinition] = {}

        for attr_name, annotation in raw_annotations.items():
            if attr_name.startswith("_") or _is_classvar(annotation):
                continue
            if attr_name in declared_relationships:
                continue

            field_def = copy.deepcopy(declared_fields.get(attr_name, FieldDefinition()))
            inner_type = unwrap_optional(resolved.get(attr_name, annotation))
            field_def.prop_name = attr_name
            field_def.python_type = inner_type
            if getattr(inner_type, "_iris_serial", False):
                field_def.iris_type = getattr(inner_type, "_iris_classname", field_def.iris_type)
            elif not field_def.iris_type:
                field_def.iris_type = python_type_to_iris(inner_type)
            normalized_fields[attr_name] = field_def

        for attr_name, field_def in list(declared_fields.items()):
            if attr_name in normalized_fields:
                continue
            inner_type = getattr(field_def, "python_type", None) or str
            field_def = copy.deepcopy(field_def)
            field_def.prop_name = attr_name
            field_def.python_type = inner_type
            if not field_def.iris_type:
                field_def.iris_type = python_type_to_iris(inner_type)
            normalized_fields[attr_name] = field_def

        normalized_relationships: dict[str, RelationshipDefinition] = {}
        for attr_name, rel_def in declared_relationships.items():
            rel_copy = copy.deepcopy(rel_def)
            rel_copy.prop_name = attr_name
            normalized_relationships[attr_name] = rel_copy

        cls._iris_declared_fields = normalized_fields  # type: ignore[attr-defined]
        cls._iris_declared_relationships = normalized_relationships  # type: ignore[attr-defined]
        cls._iris_bound = False  # type: ignore[attr-defined]
        cls._iris_bound_schema = None  # type: ignore[attr-defined]

        _MODEL_REGISTRY[iris_classname] = cls
        return cls

    @staticmethod
    def _resolve_annotations(cls: type, raw_annotations: dict[str, Any]) -> dict[str, Any]:
        try:
            return get_type_hints(cls)
        except Exception:
            resolved: dict[str, Any] = {}
            by_name = {model.__name__: model for model in _MODEL_REGISTRY.values()}
            for key, value in raw_annotations.items():
                if isinstance(value, str):
                    resolved[key] = by_name.get(value, value)
                else:
                    resolved[key] = value
            return resolved


class _IRISModelBase(metaclass=IRISMeta):
    _iris_classname: ClassVar[str] = ""
    _iris_superclass: ClassVar[str] = ""
    _iris_serial: ClassVar[bool] = False
    _iris_lockfile_path: ClassVar[str] = ""
    _iris_storage: ClassVar[Any] = None
    _iris_class_parameters: ClassVar[dict[str, str]] = {}
    _iris_indexes: ClassVar[list[dict[str, Any]]] = []

    _iris_declared_fields: ClassVar[dict[str, FieldDefinition]]
    _iris_declared_relationships: ClassVar[dict[str, RelationshipDefinition]]
    _iris_bound_schema: ClassVar[Any]
    _iris_bound: ClassVar[bool]

    def __init__(self, **kwargs: Any) -> None:
        object.__setattr__(self, "_iris_obj", None)
        object.__setattr__(self, "_iris_id", None)
        object.__setattr__(self, "_iris_data", {})
        object.__setattr__(self, "_iris_dirty_fields", set())
        object.__setattr__(self, "_iris_session", None)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")
        declared = set(type(self)._iris_declared_fields) | set(type(self)._iris_declared_relationships)
        if name in declared:
            return object.__getattribute__(self, "_iris_data").get(name)
        raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")

    def __setattr__(self, name: str, value: Any) -> None:
        declared = set(type(self)._iris_declared_fields) | set(type(self)._iris_declared_relationships)
        if name in declared:
            self._set_declared_value(name, value)
            return
        object.__setattr__(self, name, value)

    def _set_declared_value(self, name: str, value: Any) -> None:
        data = object.__getattribute__(self, "_iris_data")
        data[name] = value
        self._mark_dirty(name)

    def _mark_dirty(self, name: str) -> None:
        dirty = object.__getattribute__(self, "_iris_dirty_fields")
        dirty.add(name)
        session = object.__getattribute__(self, "_iris_session")
        if session is not None:
            session._mark_dirty(self)

    @property
    def pk(self) -> Optional[str]:
        return object.__getattribute__(self, "_iris_id")

    def to_dict(self) -> dict[str, Any]:
        keys = list(type(self)._iris_declared_fields) + list(type(self)._iris_declared_relationships)
        return {key: getattr(self, key, None) for key in keys}


class IRISModel(_IRISModelBase):
    _iris_superclass: ClassVar[str] = "%Persistent"
    _iris_serial: ClassVar[bool] = False


class IRISSerial(_IRISModelBase):
    _iris_superclass: ClassVar[str] = "%SerialObject"
    _iris_serial: ClassVar[bool] = True
