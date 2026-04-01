from __future__ import annotations

import copy
from typing import Any, ClassVar, Self, get_type_hints

from .fields import FieldDefinition, _SENTINEL
from .schema import iris_type_to_python, python_default_value, python_type_to_iris

_MODEL_REGISTRY: dict[str, type] = {}


def _clone_field_definition(value: FieldDefinition) -> FieldDefinition:
    cloned = copy.deepcopy(value)
    if value.default is _SENTINEL:
        cloned.default = _SENTINEL
    return cloned


class IRISMeta(type):
    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type:
        annotations = dict(namespace.get("__annotations__", {}))
        cleaned = dict(namespace)
        declared_fields: dict[str, FieldDefinition] = {}
        for attr_name, value in list(cleaned.items()):
            if isinstance(value, FieldDefinition):
                declared_fields[attr_name] = _clone_field_definition(value)
                cleaned.pop(attr_name, None)

        cls = super().__new__(mcs, name, bases, cleaned, **kwargs)

        if not hasattr(cls, "_iris_indexes"):
            cls._iris_indexes = []  # type: ignore[attr-defined]
        if not hasattr(cls, "_iris_parameters"):
            cls._iris_parameters = {}  # type: ignore[attr-defined]
        if not hasattr(cls, "_iris_storage"):
            cls._iris_storage = None  # type: ignore[attr-defined]

        classname = str(getattr(cls, "_iris_classname", "") or "")
        if not classname:
            return cls

        resolved = _safe_type_hints(cls, annotations)
        normalized_fields: dict[str, FieldDefinition] = {}
        for attr_name, annotation in annotations.items():
            if attr_name.startswith("_"):
                continue
            field_def = _clone_field_definition(declared_fields.get(attr_name, FieldDefinition()))
            python_type = resolved.get(attr_name, annotation)
            field_def.prop_name = attr_name
            field_def.python_type = python_type
            if not field_def.iris_type:
                field_def.iris_type = python_type_to_iris(python_type)
            normalized_fields[attr_name] = field_def

        for attr_name, field_def in declared_fields.items():
            if attr_name in normalized_fields:
                continue
            extra = _clone_field_definition(field_def)
            extra.prop_name = attr_name
            extra.python_type = extra.python_type or str
            if not extra.iris_type:
                extra.iris_type = python_type_to_iris(extra.python_type)
            normalized_fields[attr_name] = extra

        cls._iris_declared_fields = normalized_fields  # type: ignore[attr-defined]
        cls._iris_bound = False  # type: ignore[attr-defined]
        cls._iris_bound_schema = None  # type: ignore[attr-defined]
        _MODEL_REGISTRY[classname] = cls
        return cls


def _safe_type_hints(cls: type, annotations: dict[str, Any]) -> dict[str, Any]:
    try:
        return get_type_hints(cls)
    except Exception:
        return annotations


class IRISModel(metaclass=IRISMeta):
    _iris_classname: ClassVar[str] = ""
    _iris_superclasses: ClassVar[str | list[str]] = "%Persistent"
    _iris_mode: ClassVar[str] = "python"
    _iris_storage: ClassVar[dict[str, Any] | None] = None
    _iris_indexes: ClassVar[list[dict[str, Any]]] = []
    _iris_parameters: ClassVar[dict[str, str]] = {}
    _iris_declared_fields: ClassVar[dict[str, FieldDefinition]]
    _iris_bound_schema: ClassVar[Any]
    _iris_bound: ClassVar[bool]

    def __init__(self, **kwargs: Any) -> None:
        object.__setattr__(self, "_iris_id", kwargs.pop("id", None))
        object.__setattr__(self, "_iris_data", {})
        for name, field_def in type(self)._iris_declared_fields.items():
            if field_def.default is _SENTINEL:
                continue
            object.__getattribute__(self, "_iris_data")[name] = copy.deepcopy(field_def.default)
        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def pk(self) -> Any:
        return object.__getattribute__(self, "_iris_id")

    @classmethod
    def _runtime(cls) -> Any:
        from .runtime import get_default_runtime

        return get_default_runtime()

    @classmethod
    def bind(cls) -> type[Self]:
        return cls._runtime().bind(cls)

    @classmethod
    def plan(cls) -> Any:
        return cls._runtime().plan(cls)

    @classmethod
    def sync(cls) -> Any:
        return cls._runtime().sync(cls)

    @classmethod
    def get(cls, obj_id: Any) -> Self | None:
        return cls._runtime().get(cls, obj_id)

    @classmethod
    def query(cls) -> Any:
        return cls._runtime().query(cls)

    @classmethod
    def where(cls, **kwargs: Any) -> Any:
        return cls.query().filter_eq(**kwargs)

    @classmethod
    def all(cls) -> list[Self]:
        return cls.query().all()

    def save(self) -> Self:
        type(self)._runtime().save(self)
        return self

    def delete(self) -> None:
        type(self)._runtime().delete(self)

    def __getattr__(self, name: str) -> Any:
        declared = type(self)._iris_declared_fields
        if name in declared:
            return object.__getattribute__(self, "_iris_data").get(name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        declared = type(self)._iris_declared_fields
        if name in declared:
            object.__getattribute__(self, "_iris_data")[name] = value
            return
        object.__setattr__(self, name, value)


def bind_schema(model_class: type, schema_class: Any) -> type:
    existing: dict[str, FieldDefinition] = {}
    for prop in schema_class.properties:
        field_def = FieldDefinition()
        field_def.prop_name = prop.name
        field_def.required = prop.required
        field_def.maxlen = prop.maxlen
        field_def.description = prop.description
        field_def.iris_type = prop.iris_type
        field_def.python_type = iris_type_to_python(prop.iris_type)
        field_def.default = python_default_value(prop.default, prop.iris_type)
        existing[prop.name] = field_def
    model_class._iris_declared_fields = existing  # type: ignore[attr-defined]
    model_class._iris_indexes = [item.to_dict() for item in schema_class.indexes]  # type: ignore[attr-defined]
    model_class._iris_parameters = dict(schema_class.parameters)  # type: ignore[attr-defined]
    model_class._iris_storage = copy.deepcopy(schema_class.storage)  # type: ignore[attr-defined]
    model_class._iris_superclasses = list(schema_class.superclasses) if len(schema_class.superclasses) > 1 else schema_class.superclasses[0]  # type: ignore[attr-defined]
    model_class._iris_bound_schema = schema_class  # type: ignore[attr-defined]
    model_class._iris_bound = True  # type: ignore[attr-defined]
    return model_class
