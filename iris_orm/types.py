"""
Types and definitions for iris_orm schema layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, Dict, Optional, Tuple


@dataclass
class Field:
    """Metadata definition for a model field."""

    required: bool = False
    default: Any = None
    initial_expression: Optional[str] = None
    maxlen: Optional[int] = None
    readonly: bool = False
    collection: Optional[str] = None  # e.g. "list", "array"
    iris_type: Optional[str] = None
    # Backward-compatible alias for older callers; prefer `iris_type`.
    sql_type: Optional[str] = None
    sql_field_name: Optional[str] = None

    def __post_init__(self) -> None:
        if self.iris_type is None and self.sql_type is not None:
            self.iris_type = self.sql_type
        elif self.iris_type is not None and self.sql_type is None:
            self.sql_type = self.iris_type


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
    properties: Tuple[StorageProperty, ...] = ()
    sql_maps: Tuple[StorageSQLMap, ...] = ()
