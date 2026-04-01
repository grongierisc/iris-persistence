from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TypeVar, overload

_SENTINEL = object()
_ModelClass = TypeVar("_ModelClass", bound=type)
_FieldValue = TypeVar("_FieldValue")


def _ensure_model_class(value: Any) -> type:
    if not isinstance(value, type):
        raise TypeError("IRIS decorators can only be applied to classes")
    return value


@dataclass
class FieldDefinition:
    required: bool = False
    default: Any = _SENTINEL
    maxlen: Optional[int] = None
    iris_type: Optional[str] = None
    description: str = ""
    python_type: type | None = None
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
        cls = _ensure_model_class(cls)
        current = list(getattr(cls, "_iris_indexes", []))
        current.append(self.to_dict())
        setattr(cls, "_iris_indexes", current)
        return cls


@dataclass
class ParameterDefinition:
    name: str
    value: str

    def to_pair(self) -> tuple[str, str]:
        return (self.name, self.value)

    def __call__(self, cls: _ModelClass) -> _ModelClass:
        cls = _ensure_model_class(cls)
        current = dict(getattr(cls, "_iris_parameters", {}))
        current[self.name] = self.value
        setattr(cls, "_iris_parameters", current)
        return cls


@overload
def field(
    *,
    required: bool = False,
    default: _FieldValue,
    maxlen: Optional[int] = None,
    iris_type: Optional[str] = None,
    description: str = "",
) -> _FieldValue:
    ...


@overload
def field(
    *,
    required: bool = False,
    default: Any = _SENTINEL,
    maxlen: Optional[int] = None,
    iris_type: Optional[str] = None,
    description: str = "",
) -> Any:
    ...


def field(
    *,
    required: bool = False,
    default: Any = _SENTINEL,
    maxlen: Optional[int] = None,
    iris_type: Optional[str] = None,
    description: str = "",
) -> Any:
    return FieldDefinition(
        required=required,
        default=default,
        maxlen=maxlen,
        iris_type=iris_type,
        description=description,
    )


def index(
    name: str,
    *,
    properties: str,
    unique: bool = False,
    primary_key: bool = False,
) -> IndexDefinition:
    return IndexDefinition(
        name=name,
        properties=properties,
        unique=unique,
        primary_key=primary_key,
    )


def parameter(name: str, value: Any) -> ParameterDefinition:
    return ParameterDefinition(name=str(name), value=str(value))
