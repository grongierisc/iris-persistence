"""
Types and definitions for iris_persistence schema layout.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Callable, Dict, Optional


class _UnsetType:
    def __repr__(self) -> str:
        return "UNSET"


UNSET = _UnsetType()


@dataclass(frozen=True)
class ClassMetadata:
    description: Optional[str] = None
    deprecated: bool = False
    final: bool = False
    sql_table_name: Optional[str] = None
    procedure_block: bool = False


@dataclass
class FieldInfo:
    """Metadata definition for a model field."""

    required: bool = False
    default: Any = UNSET
    default_factory: Callable[[], Any] | Any = UNSET
    nullable: Optional[bool] = None
    primary_key: bool = False
    index: bool = False
    unique: bool = False
    index_name: Optional[str] = None
    index_type: Optional[str] = None
    max_length: Optional[int] = None
    initial_expression: Optional[str] = None
    readonly: bool = False
    collection: Optional[str] = None  # e.g. "list", "array"
    iris_type: Optional[str] = None
    sql_field_name: Optional[str] = None
    identity: bool = False
    relationship: Optional[str] = None
    on_delete: Optional[str] = None
    inverse: Optional[str] = None
    transient: bool = False
    storable: bool = True
    multi_dimensional: bool = False
    sql_list_delimiter: Optional[str] = None
    sql_list_type: Optional[str] = None
    sql_compute_code: Optional[str] = None
    sql_compute_on_change: Optional[str] = None
    sql_computed: bool = False

    def __post_init__(self) -> None:
        if self.default is not UNSET and self.default_factory is not UNSET:
            raise TypeError("Field cannot define both default and default_factory")
        if self.default_factory is not UNSET and not callable(self.default_factory):
            raise TypeError("Field default_factory must be callable")


def Field(**kwargs: Any) -> Any:
    """Declare field metadata for a model attribute. Accepts any `FieldInfo` keyword."""
    return FieldInfo(**kwargs)


@dataclass(frozen=True)
class ModelField:
    name: str
    declared_type: Any
    field_info: FieldInfo
    required: bool = False
    nullable: bool = False
    init: bool = True
    sql_field_name: Optional[str] = None
    _is_percent_list: bool = False
    _is_scalar_string: bool = False
    _collection_kind: Optional[str] = None
    _element_type: Any = None
    _is_model_field: bool = False

    @property
    def default(self) -> Any:
        return self.field_info.default

    @property
    def default_factory(self) -> Callable[[], Any] | Any:
        return self.field_info.default_factory

    def has_default(self) -> bool:
        return self.default is not UNSET or self.default_factory is not UNSET

    def get_default_value(self) -> Any:
        if self.default_factory is not UNSET:
            return self.default_factory()
        if self.default is not UNSET:
            return deepcopy(self.default)
        return UNSET


@dataclass
class Index:
    """Index definition."""

    name: str
    properties: str
    unique: bool = False
    primary_key: bool = False
    type: Optional[str] = None


@dataclass(frozen=True)
class StorageTuning:
    """Creation-time location overrides for compiler-owned Default storage."""

    data_location: Optional[str] = None
    extent_location: Optional[str] = None
    id_location: Optional[str] = None
    index_location: Optional[str] = None
    stream_location: Optional[str] = None
    counter_location: Optional[str] = None
    version_location: Optional[str] = None
    index_locations: Dict[str, str] = dataclass_field(default_factory=dict)
