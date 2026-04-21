"""
Types and definitions for iris_orm schema layout.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Callable, Dict, Optional, Tuple, overload


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
    maxlen: Optional[int] = None
    readonly: bool = False
    collection: Optional[str] = None  # e.g. "list", "array"
    iris_type: Optional[str] = None
    # Backward-compatible alias for older callers; prefer `iris_type`.
    sql_type: Optional[str] = None
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
        if self.iris_type is None and self.sql_type is not None:
            self.iris_type = self.sql_type
        elif self.iris_type is not None and self.sql_type is None:
            self.sql_type = self.iris_type
        if self.max_length is None and self.maxlen is not None:
            self.max_length = self.maxlen
        elif self.max_length is not None and self.maxlen is None:
            self.maxlen = self.max_length
        elif self.max_length is not None and self.maxlen is not None:
            self.maxlen = self.max_length
        if self.default is not UNSET and self.default_factory is not UNSET:
            raise TypeError("Field cannot define both default and default_factory")
        if self.default_factory is not UNSET and not callable(self.default_factory):
            raise TypeError("Field default_factory must be callable")


@overload
def Field(
    *,
    required: bool = ...,
    default: Any = ...,
    default_factory: Callable[[], Any] | Any = ...,
    nullable: Optional[bool] = ...,
    primary_key: bool = ...,
    index: bool = ...,
    unique: bool = ...,
    index_name: Optional[str] = ...,
    index_type: Optional[str] = ...,
    max_length: Optional[int] = ...,
    initial_expression: Optional[str] = ...,
    maxlen: Optional[int] = ...,
    readonly: bool = ...,
    collection: Optional[str] = ...,
    iris_type: Optional[str] = ...,
    sql_type: Optional[str] = ...,
    sql_field_name: Optional[str] = ...,
    identity: bool = ...,
    relationship: Optional[str] = ...,
    on_delete: Optional[str] = ...,
    inverse: Optional[str] = ...,
    transient: bool = ...,
    storable: bool = ...,
    multi_dimensional: bool = ...,
    sql_list_delimiter: Optional[str] = ...,
    sql_list_type: Optional[str] = ...,
    sql_compute_code: Optional[str] = ...,
    sql_compute_on_change: Optional[str] = ...,
    sql_computed: bool = ...,
) -> Any: ...


def Field(
    *,
    required: bool = False,
    default: Any = UNSET,
    default_factory: Callable[[], Any] | Any = UNSET,
    nullable: Optional[bool] = None,
    primary_key: bool = False,
    index: bool = False,
    unique: bool = False,
    index_name: Optional[str] = None,
    index_type: Optional[str] = None,
    max_length: Optional[int] = None,
    initial_expression: Optional[str] = None,
    maxlen: Optional[int] = None,
    readonly: bool = False,
    collection: Optional[str] = None,
    iris_type: Optional[str] = None,
    sql_type: Optional[str] = None,
    sql_field_name: Optional[str] = None,
    identity: bool = False,
    relationship: Optional[str] = None,
    on_delete: Optional[str] = None,
    inverse: Optional[str] = None,
    transient: bool = False,
    storable: bool = True,
    multi_dimensional: bool = False,
    sql_list_delimiter: Optional[str] = None,
    sql_list_type: Optional[str] = None,
    sql_compute_code: Optional[str] = None,
    sql_compute_on_change: Optional[str] = None,
    sql_computed: bool = False,
) -> Any:
    return FieldInfo(
        required=required,
        default=default,
        default_factory=default_factory,
        nullable=nullable,
        primary_key=primary_key,
        index=index,
        unique=unique,
        index_name=index_name,
        index_type=index_type,
        max_length=max_length,
        initial_expression=initial_expression,
        maxlen=maxlen,
        readonly=readonly,
        collection=collection,
        iris_type=iris_type,
        sql_type=sql_type,
        sql_field_name=sql_field_name,
        identity=identity,
        relationship=relationship,
        on_delete=on_delete,
        inverse=inverse,
        transient=transient,
        storable=storable,
        multi_dimensional=multi_dimensional,
        sql_list_delimiter=sql_list_delimiter,
        sql_list_type=sql_list_type,
        sql_compute_code=sql_compute_code,
        sql_compute_on_change=sql_compute_on_change,
        sql_computed=sql_computed,
    )


@dataclass(frozen=True)
class ModelField:
    name: str
    declared_type: Any
    field_info: FieldInfo
    required: bool = False
    nullable: bool = False
    init: bool = True
    sql_field_name: Optional[str] = None

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


@dataclass
class StorageProperty:
    name: str
    average_field_size: Optional[str] = None
    selectivity: Optional[str] = None
    outlier_selectivity: Optional[str] = None
    histogram: Optional[str] = None
    child_block_count: Optional[str] = None
    child_extent_size: Optional[str] = None
    bias_queries_as_outlier: Optional[bool] = None
    stream_location: Optional[str] = None


@dataclass
class StorageIndex:
    name: str
    location: Optional[str] = None
    small_chunk_size: Optional[str] = None


@dataclass
class StorageData:
    name: str
    structure: str
    attribute: Optional[str] = None
    subscript: Optional[str] = None
    values: Dict[str, str] = dataclass_field(default_factory=dict)


@dataclass
class StorageSQLMapData:
    name: str
    node: Optional[str] = None
    piece: Optional[str] = None
    delimiter: Optional[str] = None
    retrieval_code: Optional[str] = None


@dataclass
class StorageSQLMapRowIdSpec:
    name: str
    field: Optional[str] = None
    expression: Optional[str] = None


@dataclass
class StorageSQLMapSubAccessVar:
    name: str
    variable: Optional[str] = None
    code: Optional[str] = None


@dataclass
class StorageSQLMapSubInvalidCondition:
    name: str
    expression: Optional[str] = None


@dataclass
class StorageSQLMapSub:
    name: str
    access_type: Optional[str] = None
    data_access: Optional[str] = None
    delimiter: Optional[str] = None
    expression: Optional[str] = None
    loop_init_value: Optional[str] = None
    next_code: Optional[str] = None
    null_marker: Optional[str] = None
    start_value: Optional[str] = None
    stop_expression: Optional[str] = None
    stop_value: Optional[str] = None
    access_vars: Tuple[StorageSQLMapSubAccessVar, ...] = ()
    invalid_conditions: Tuple[StorageSQLMapSubInvalidCondition, ...] = ()


@dataclass
class StorageSQLMap:
    name: str
    block_count: Optional[str] = None
    condition: Optional[str] = None
    condition_fields: Optional[str] = None
    conditional_with_host_vars: Optional[bool] = None
    global_name: Optional[str] = None
    population_pct: Optional[str] = None
    population_type: Optional[str] = None
    row_reference: Optional[str] = None
    structure: Optional[str] = None
    type: Optional[str] = None
    data: Optional[Tuple[StorageSQLMapData, ...]] = None
    row_id_specs: Tuple[StorageSQLMapRowIdSpec, ...] = ()
    subscripts: Tuple[StorageSQLMapSub, ...] = ()


@dataclass
class StorageDefinition:
    type: str = "%Storage.Persistent"
    data_location: Optional[str] = None
    default_data: Optional[str] = None
    extent_location: Optional[str] = None
    extent_size: Optional[str] = None
    counter_location: Optional[str] = None
    version_location: Optional[str] = None
    id_location: Optional[str] = None
    id_expression: Optional[str] = None
    id_function: Optional[str] = None
    index_location: Optional[str] = None
    state: Optional[str] = None
    stream_location: Optional[str] = None
    sql_child_sub: Optional[str] = None
    sql_id_expression: Optional[str] = None
    sql_row_id_name: Optional[str] = None
    sql_row_id_property: Optional[str] = None
    sql_table_number: Optional[str] = None
    sequence_number: Optional[str] = None
    data: Tuple[StorageData, ...] = ()
    indices: Tuple[StorageIndex, ...] = ()
    properties: Tuple[StorageProperty, ...] = ()
    sql_maps: Tuple[StorageSQLMap, ...] = ()
