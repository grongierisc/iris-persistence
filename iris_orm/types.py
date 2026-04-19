"""
Types and definitions for iris_orm schema layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Optional, Union, Tuple, Dict


@dataclass
class Field:
    """Metadata definition for a model field."""
    required: bool = False
    default: Any = None
    maxlen: Optional[int] = None
    readonly: bool = False
    collection: Optional[str] = None  # e.g. "list", "array"
    sql_type: Optional[str] = None
    sql_field_name: Optional[str] = None


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


@dataclass
class StorageData:
    name: str
    structure: str
    values: Dict[str, str] = dataclass_field(default_factory=dict)


@dataclass
class StorageSQLMap:
    name: str
    block_count: Optional[str] = None
    data: Optional[Tuple[Any, ...]] = None


@dataclass
class StorageDefinition:
    type: str = "%Storage.Persistent"
    data_location: Optional[str] = None
    default_data: Optional[str] = None
    id_location: Optional[str] = None
    index_location: Optional[str] = None
    stream_location: Optional[str] = None
    data: Tuple[StorageData, ...] = ()
    properties: Tuple[StorageProperty, ...] = ()
    sql_maps: Tuple[StorageSQLMap, ...] = ()
