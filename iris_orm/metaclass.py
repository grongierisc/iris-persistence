"""
Metaclass and base classes for the embedded IRIS ORM runtime.

Two workflows are supported:
  Existing-class binding: introspect an IRIS class and inject descriptors.
  Declared models: define fields and relationships directly in Python.
"""
from __future__ import annotations

import typing
from typing import Any, ClassVar, Optional, get_type_hints

from .connection import IRISConnection
from .descriptors import (
    IRISDescriptor,
    IRISRelationshipDescriptor,
    IRISSerialDescriptor,
    _wrap_iris_obj,
)
from .fields import FieldDefinition, RelationshipDefinition
from .introspection import PropertyInfo, get_class_properties
from .query import IRISQuerySet
from .types import python_type_to_iris, unwrap_optional

_MODEL_REGISTRY: dict[str, type] = {}


class _SchemaProperty:
    """Class-level descriptor returning a ``SchemaManager``."""

    def __get__(self, obj: Any, objtype: type | None = None) -> Any:
        if objtype is None:
            objtype = type(obj)
        from .schema import SchemaManager  # noqa: PLC0415

        return SchemaManager(objtype)


def _is_classvar(annotation: Any) -> bool:
    """Return ``True`` when *annotation* is a ``ClassVar``."""
    origin = getattr(annotation, "__origin__", None)
    if origin is ClassVar:
        return True
    if hasattr(typing, "ClassVar") and annotation is ClassVar:
        return True
    text = str(annotation)
    return text.startswith("typing.ClassVar") or text.startswith("ClassVar")


class IRISMeta(type):
    """Metaclass that injects IRIS-aware descriptors onto model classes."""

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type:
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        iris_classname = namespace.get("_iris_classname", "")
        if not iris_classname:
            return cls

        raw_annotations: dict[str, Any] = namespace.get("__annotations__", {})
        user_annotations = {
            key: value
            for key, value in raw_annotations.items()
            if not key.startswith("_") and not _is_classvar(value)
        }
        has_field_defs = any(
            isinstance(value, (FieldDefinition, RelationshipDefinition))
            for value in namespace.values()
        )
        if user_annotations or has_field_defs:
            mcs._setup_python_first(cls, namespace, user_annotations)
        else:
            mcs._setup_existing_binding(cls, namespace)

        if "_iris_schema_snapshot" not in namespace:
            cls._iris_schema_snapshot = {}  # type: ignore[attr-defined]
        if "_iris_class_parameters" not in namespace:
            cls._iris_class_parameters = {}  # type: ignore[attr-defined]
        if "_iris_indexes" not in namespace:
            cls._iris_indexes = []  # type: ignore[attr-defined]

        _MODEL_REGISTRY[iris_classname] = cls
        if not getattr(cls, "_iris_serial", False):
            cls.objects = IRISQuerySet(cls)  # type: ignore[attr-defined]
        return cls

    @staticmethod
    def _setup_python_first(
        cls: type,
        namespace: dict[str, Any],
        user_annotations: dict[str, Any],
    ) -> None:
        iris_properties: list[PropertyInfo] = []
        iris_field_defs: dict[str, FieldDefinition] = {}
        iris_rel_defs: dict[str, RelationshipDefinition] = {}

        try:
            resolved = get_type_hints(cls)
        except Exception:
            resolved = {}
            for key, value in user_annotations.items():
                if isinstance(value, str):
                    resolved[key] = next(
                        (model for model in _MODEL_REGISTRY.values() if model.__name__ == value),
                        value,
                    )
                else:
                    resolved[key] = value

        for attr_name, raw_type in user_annotations.items():
            namespace_value = namespace.get(attr_name)
            if isinstance(namespace_value, RelationshipDefinition):
                continue

            resolved_type = resolved.get(attr_name, raw_type)
            inner_type = unwrap_optional(resolved_type)
            field_def = namespace_value if isinstance(namespace_value, FieldDefinition) else FieldDefinition()
            field_def.prop_name = attr_name
            field_def.python_type = inner_type

            if getattr(inner_type, "_iris_serial", False):
                iris_type = inner_type._iris_classname
                field_def.iris_type = iris_type
                prop_info = PropertyInfo(
                    name=attr_name,
                    iris_type=iris_type,
                    python_type=inner_type,
                    required=field_def.required,
                    collection=field_def.collection,
                    default="" if field_def.default is None else str(field_def.default),
                )
                iris_properties.append(prop_info)
                iris_field_defs[attr_name] = field_def
                if attr_name not in namespace or isinstance(namespace_value, FieldDefinition):
                    IRISMeta._install_descriptor(
                        cls,
                        attr_name,
                        IRISSerialDescriptor(attr_name, iris_type),
                    )
                IRISMeta._set_optional_annotation(cls, attr_name, inner_type)
                continue

            iris_type = field_def.iris_type or python_type_to_iris(inner_type)
            field_def.iris_type = iris_type
            prop_info = PropertyInfo(
                name=attr_name,
                iris_type=iris_type,
                python_type=inner_type,
                required=field_def.required,
                collection=field_def.collection,
                default="" if field_def.default is None else str(field_def.default),
                maxlen=field_def.maxlen,
                description=field_def.description,
            )
            iris_properties.append(prop_info)
            iris_field_defs[attr_name] = field_def

            if attr_name not in namespace or isinstance(namespace_value, FieldDefinition):
                IRISMeta._install_descriptor(
                    cls,
                    attr_name,
                    IRISDescriptor(attr_name, inner_type, field_def.required),
                )
            IRISMeta._set_optional_annotation(cls, attr_name, inner_type)

        for attr_name, value in namespace.items():
            if not isinstance(value, RelationshipDefinition):
                continue
            value.prop_name = attr_name
            iris_rel_defs[attr_name] = value
            IRISMeta._install_descriptor(
                cls,
                attr_name,
                IRISRelationshipDescriptor(
                    prop_name=attr_name,
                    related_classname=value.related_classname,
                    cardinality=value.cardinality,
                    inverse=value.inverse,
                ),
            )

        cls._iris_properties = iris_properties  # type: ignore[attr-defined]
        cls._iris_field_defs = iris_field_defs  # type: ignore[attr-defined]
        cls._iris_rel_defs = iris_rel_defs  # type: ignore[attr-defined]
        cls._iris_declared_model = True  # type: ignore[attr-defined]

    @staticmethod
    def _setup_existing_binding(cls: type, namespace: dict[str, Any]) -> None:
        try:
            props = get_class_properties(cls._iris_classname, IRISConnection())  # type: ignore[attr-defined]
        except Exception:
            props = []

        if not hasattr(cls, "__annotations__"):
            cls.__annotations__ = {}

        for prop in props:
            if prop.name in namespace:
                continue
            serial_class = _MODEL_REGISTRY.get(prop.iris_type)
            if serial_class is not None and getattr(serial_class, "_iris_serial", False):
                descriptor: IRISDescriptor | IRISSerialDescriptor = IRISSerialDescriptor(
                    prop.name,
                    prop.iris_type,
                )
            else:
                descriptor = IRISDescriptor(prop.name, prop.python_type, prop.required)
            IRISMeta._install_descriptor(cls, prop.name, descriptor)
            cls.__annotations__[prop.name] = Optional[prop.python_type]  # type: ignore[valid-type]

        cls._iris_properties = props  # type: ignore[attr-defined]
        cls._iris_field_defs = {}  # type: ignore[attr-defined]
        cls._iris_rel_defs = {}  # type: ignore[attr-defined]
        cls._iris_declared_model = False  # type: ignore[attr-defined]

    @staticmethod
    def _install_descriptor(cls: type, attr_name: str, descriptor: Any) -> None:
        descriptor.attr_name = attr_name
        setattr(cls, attr_name, descriptor)

    @staticmethod
    def _set_optional_annotation(cls: type, attr_name: str, inner_type: Any) -> None:
        if not hasattr(cls, "__annotations__"):
            cls.__annotations__ = {}
        cls.__annotations__[attr_name] = Optional[inner_type]  # type: ignore[valid-type]


class _IRISBoundBase(metaclass=IRISMeta):
    """Shared behavior for persistent and serial IRIS-backed Python classes."""

    _iris_classname: ClassVar[str] = ""
    _iris_schema_snapshot: ClassVar[dict[str, str]] = {}
    _iris_storage: ClassVar[str] = ""
    _iris_storage_mode: ClassVar[str] = ""
    _iris_lockfile_path: ClassVar[str] = ""
    _iris_superclass: ClassVar[str] = ""
    _iris_class_parameters: ClassVar[dict[str, str]] = {}
    _iris_indexes: ClassVar[list[dict[str, Any]]] = []

    _iris_properties: ClassVar[list[PropertyInfo]]
    _iris_field_defs: ClassVar[dict[str, FieldDefinition]]
    _iris_rel_defs: ClassVar[dict[str, RelationshipDefinition]]
    _iris_declared_model: ClassVar[bool]

    schema: ClassVar[Any] = _SchemaProperty()

    def __init__(self, **kwargs: Any) -> None:
        object.__setattr__(self, "_iris_obj", self._create_backing_object())
        object.__setattr__(self, "_iris_id", None)
        for key, value in kwargs.items():
            setattr(self, key, value)

    @classmethod
    def _connection(cls) -> IRISConnection:
        return IRISConnection()

    @classmethod
    def _create_backing_object(cls) -> Any:
        if not cls._iris_classname:
            return None
        return cls._connection().new_object(cls._iris_classname)

    @classmethod
    def _wrap(cls, iris_obj: Any) -> Any:
        return _wrap_iris_obj(cls, iris_obj)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")
        try:
            iris_obj = object.__getattribute__(self, "_iris_obj")
        except AttributeError as exc:
            raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}") from exc
        if iris_obj is None:
            raise AttributeError(
                f"{type(self).__name__!r} has no attribute {name!r} "
                "(no underlying IRIS object)"
            )
        return getattr(iris_obj, name)

    def __setattr__(self, name: str, value: Any) -> None:
        for klass in type(self).__mro__:
            descriptor = klass.__dict__.get(name)
            if descriptor is None:
                continue
            if hasattr(descriptor, "__set__"):
                descriptor.__set__(self, value)
                return
            break
        if not name.startswith("_"):
            try:
                iris_obj = object.__getattribute__(self, "_iris_obj")
            except AttributeError:
                iris_obj = None
            if iris_obj is not None:
                setattr(iris_obj, name, value)
                return
        object.__setattr__(self, name, value)

    @classmethod
    def bind(cls) -> None:
        if getattr(cls, "_iris_declared_model", False):
            raise RuntimeError(
                f"{cls.__name__} was declared in Python. "
                "bind() is only needed for classes bound to an existing IRIS definition."
            )
        IRISMeta._setup_existing_binding(cls, {})


class IRISModel(_IRISBoundBase):
    """Base class for IRIS ``%Persistent`` models."""

    _iris_superclass: ClassVar[str] = "%Persistent"
    _iris_serial: ClassVar[bool] = False
    objects: ClassVar[IRISQuerySet]

    def save(self) -> None:
        iris_obj = object.__getattribute__(self, "_iris_obj")
        if iris_obj is None:
            raise RuntimeError(
                "No underlying IRIS object. Use MyModel.create() to obtain a new instance."
            )
        status = iris_obj._Save()
        if not status:
            raise RuntimeError(f"_Save() failed with status: {status!r}")
        try:
            object.__setattr__(self, "_iris_id", str(iris_obj._Id()))
        except Exception:
            object.__setattr__(self, "_iris_id", None)

    def delete(self) -> None:
        obj_id = object.__getattribute__(self, "_iris_id")
        if not obj_id:
            raise RuntimeError("Cannot delete: object has no ID (not yet saved).")
        type(self)._connection().delete_object(self._iris_classname, obj_id)
        object.__setattr__(self, "_iris_obj", None)
        object.__setattr__(self, "_iris_id", None)

    @property
    def pk(self) -> Optional[str]:
        return object.__getattribute__(self, "_iris_id")

    @classmethod
    def get(cls, obj_id: Any) -> Optional["IRISModel"]:
        return cls._open(str(obj_id))

    @classmethod
    def create(cls, **kwargs: Any) -> "IRISModel":
        instance = cls._wrap(cls._connection().new_object(cls._iris_classname))
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance

    @classmethod
    def _open(cls, obj_id: str) -> Optional["IRISModel"]:
        try:
            iris_obj = cls._connection().open_object(cls._iris_classname, obj_id)
        except Exception:
            return None
        if iris_obj is None:
            return None
        return cls._wrap(iris_obj)


class IRISSerial(_IRISBoundBase):
    """Base class for IRIS ``%SerialObject`` embedded types."""

    _iris_serial: ClassVar[bool] = True
    _iris_superclass: ClassVar[str] = "%SerialObject"

    @classmethod
    def _create_backing_object(cls) -> Any:
        return None
