"""
Field and relationship definition helpers for declared model classes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TypeVar

_SENTINEL = object()
_ModelClass = TypeVar("_ModelClass", bound=type)


def _ensure_model_class(value: Any) -> type:
    if not isinstance(value, type):
        raise TypeError("IRIS schema decorators can only be applied to classes")
    return value


def _touch_model_class(cls: _ModelClass) -> _ModelClass:
    setattr(cls, "_iris_bound", False)
    setattr(cls, "_iris_bound_schema", None)
    return cls


def _append_class_sequence(cls: _ModelClass, attr_name: str, item: Any) -> _ModelClass:
    current = list(getattr(cls, attr_name, []))
    current.append(item)
    setattr(cls, attr_name, current)
    return _touch_model_class(cls)


def _set_class_mapping(cls: _ModelClass, attr_name: str, key: str, value: str) -> _ModelClass:
    current = dict(getattr(cls, attr_name, {}))
    current[key] = value
    setattr(cls, attr_name, current)
    return _touch_model_class(cls)


@dataclass
class FieldDefinition:
    required: bool = False
    default: Any = None
    maxlen: Optional[int] = None
    collection: str = ""        # "" | "list" | "array"
    iris_type: Optional[str] = None
    description: str = ""
    # Set by metaclass after inspection:
    prop_name: str = ""
    python_type: type = None  # type: ignore[assignment]


@dataclass
class RelationshipDefinition:
    related_classname: str
    inverse: str
    cardinality: str   # "parent" | "children" | "one" | "many"
    on_delete: str = "cascade"
    description: str = ""
    # Set by metaclass after inspection:
    prop_name: str = ""


@dataclass
class IndexDefinition:
    name: str
    properties: str
    unique: bool = False
    primary_key: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "properties": self.properties,
            "unique": self.unique,
            "primary_key": self.primary_key,
        }

    def __call__(self, cls: _ModelClass) -> _ModelClass:
        return _append_class_sequence(_ensure_model_class(cls), "_iris_indexes", self.to_dict())


@dataclass
class TriggerDefinition:
    name: str
    event: str
    time: str
    code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "event": self.event,
            "time": self.time,
            "code": self.code,
        }

    def __call__(self, cls: _ModelClass) -> _ModelClass:
        return _append_class_sequence(_ensure_model_class(cls), "_iris_triggers", self.to_dict())


@dataclass
class ParameterDefinition:
    name: str
    value: str

    def to_pair(self) -> tuple[str, str]:
        return (self.name, self.value)

    def __call__(self, cls: _ModelClass) -> _ModelClass:
        return _set_class_mapping(_ensure_model_class(cls), "_iris_class_parameters", self.name, self.value)


def field(
    *,
    required: bool = False,
    default: Any = _SENTINEL,
    maxlen: Optional[int] = None,
    collection: str = "",
    iris_type: Optional[str] = None,
    description: str = "",
) -> Any:
    """Declare a typed IRIS property with optional metadata."""
    return FieldDefinition(
        required=required,
        default=None if default is _SENTINEL else default,
        maxlen=maxlen,
        collection=collection,
        iris_type=iris_type,
        description=description,
    )


def relationship(
    related_classname: str,
    *,
    inverse: str,
    cardinality: str,
    on_delete: str = "cascade",
    description: str = "",
) -> Any:
    """Declare an IRIS Relationship property."""
    if cardinality not in ("parent", "children", "one", "many"):
        raise ValueError(
            f"cardinality must be parent/children/one/many, got {cardinality!r}"
        )
    return RelationshipDefinition(
        related_classname=related_classname,
        inverse=inverse,
        cardinality=cardinality,
        on_delete=on_delete,
        description=description,
    )


def index(
    name: str,
    *,
    properties: str,
    unique: bool = False,
    primary_key: bool = False,
) -> IndexDefinition:
    """Declare an IRIS index for a python-owned model."""
    return IndexDefinition(
        name=name,
        properties=properties,
        unique=unique,
        primary_key=primary_key,
    )


def trigger(
    name: str,
    *,
    event: str,
    time: str,
    code: str,
) -> TriggerDefinition:
    """Declare an IRIS trigger for a python-owned model."""
    normalized_event = str(event).upper()
    normalized_time = str(time).upper()
    if normalized_event not in {"INSERT", "UPDATE", "DELETE"}:
        raise ValueError(f"Unsupported trigger event: {event!r}")
    if normalized_time not in {"BEFORE", "AFTER"}:
        raise ValueError(f"Unsupported trigger time: {time!r}")
    return TriggerDefinition(
        name=name,
        event=normalized_event,
        time=normalized_time,
        code=str(code),
    )


def parameter(name: str, value: Any) -> ParameterDefinition:
    """Declare an IRIS class parameter for a python-owned model."""
    return ParameterDefinition(
        name=str(name),
        value=str(value),
    )
