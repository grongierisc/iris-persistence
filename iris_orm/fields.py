from __future__ import annotations

import warnings
from dataclasses import MISSING, dataclass
from typing import Any, Optional, TypeVar, overload

_ModelClass = TypeVar("_ModelClass", bound=type)
_FieldValue = TypeVar("_FieldValue")


def _ensure_model_class(value: Any) -> type:
    if not isinstance(value, type):
        raise TypeError("IRIS decorators can only be applied to classes")
    return value


@dataclass(init=False)
class Field:
    """Metadata for an IRIS ORM property.

    Use as ``Annotated[str, Field(required=True)]`` or as a class-level default.
    """

    required: bool
    default: Any
    has_default: bool
    maxlen: Optional[int]
    iris_type: Optional[str]
    description: str
    parameters: dict[str, str]
    python_type: Any
    prop_name: str

    def __init__(
        self,
        *,
        required: bool = False,
        default: Any = MISSING,
        maxlen: Optional[int] = None,
        iris_type: Optional[str] = None,
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self.required = required
        self.default = None if default is MISSING else default
        self.has_default = default is not MISSING
        self.maxlen = maxlen
        self.iris_type = iris_type
        self.description = description
        self.parameters = {str(k): str(v) for k, v in dict(parameters or {}).items()}
        self.python_type = None
        self.prop_name = ""

    def copy(self) -> "Field":
        clone = Field(
            required=self.required,
            default=self.default if self.has_default else MISSING,
            maxlen=self.maxlen,
            iris_type=self.iris_type,
            description=self.description,
            parameters=dict(self.parameters),
        )
        clone.python_type = self.python_type
        clone.prop_name = self.prop_name
        return clone


# Alias used in type hints and ``__init__.py`` exports
FieldDefinition = Field


@dataclass
class IndexDefinition:
    """Descriptor for an IRIS index definition."""

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
        state = getattr(cls, "_iris_state", None)
        if state is not None:
            state.indexes.append(self.to_dict())
        else:
            current = list(getattr(cls, "_iris_indexes", []))
            current.append(self.to_dict())
            setattr(cls, "_iris_indexes", current)
        return cls


@dataclass
class ParameterDefinition:
    """Descriptor for an IRIS class parameter."""

    name: str
    value: str

    def to_pair(self) -> tuple[str, str]:
        return (self.name, self.value)

    def __call__(self, cls: _ModelClass) -> _ModelClass:
        cls = _ensure_model_class(cls)
        state = getattr(cls, "_iris_state", None)
        if state is not None:
            state.parameters[self.name] = self.value
        else:
            current = dict(getattr(cls, "_iris_parameters", {}))
            current[self.name] = self.value
            setattr(cls, "_iris_parameters", current)
        return cls


# Public short alias
Index = IndexDefinition


@overload
def field(
    *,
    required: bool = False,
    default: _FieldValue,
    maxlen: Optional[int] = None,
    iris_type: Optional[str] = None,
    description: str = "",
    parameters: dict[str, Any] | None = None,
) -> _FieldValue: ...


@overload
def field(
    *,
    required: bool = False,
    default: Any = MISSING,
    maxlen: Optional[int] = None,
    iris_type: Optional[str] = None,
    description: str = "",
    parameters: dict[str, Any] | None = None,
) -> Any: ...


def field(
    *,
    required: bool = False,
    default: Any = MISSING,
    maxlen: Optional[int] = None,
    iris_type: Optional[str] = None,
    description: str = "",
    parameters: dict[str, Any] | None = None,
) -> Any:
    """Deprecated: use ``Annotated[..., Field(...)]`` instead."""
    warnings.warn(
        "field(...) is deprecated; use Annotated[..., Field(...)] instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return Field(
        required=required,
        default=default,
        maxlen=maxlen,
        iris_type=iris_type,
        description=description,
        parameters=parameters,
    )


def index(
    name: str,
    *,
    properties: str,
    unique: bool = False,
    primary_key: bool = False,
) -> IndexDefinition:
    """Deprecated: use ``class Meta`` ``indexes`` instead."""
    warnings.warn(
        "index(...) is deprecated; use class Meta.indexes = [Index(...)] instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return IndexDefinition(name=name, properties=properties, unique=unique, primary_key=primary_key)


def parameter(name: str, value: Any) -> ParameterDefinition:
    """Deprecated: use ``class Meta`` ``parameters`` instead."""
    warnings.warn(
        "parameter(...) is deprecated; use class Meta.parameters instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return ParameterDefinition(name=str(name), value=str(value))
