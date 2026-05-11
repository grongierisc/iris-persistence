"""
iris_persistence core package
"""

__version__ = "0.1.0"

from iris_persistence.models import Model
from iris_persistence.runtime import configure
from iris_persistence.schema import SchemaDiff, diff_schema
from iris_persistence.scaffold import ScaffoldResult, ScaffoldWarning, scaffold_from_cls, scaffold_from_iris
from iris_persistence.types import (
    ClassMetadata,
    Field,
    Index,
    StorageData,
    StorageDefinition,
    StorageIndex,
    StorageProperty,
    StorageSQLMap,
    StorageSQLMapData,
    StorageSQLMapRowIdSpec,
    StorageSQLMapSub,
    StorageSQLMapSubAccessVar,
    StorageSQLMapSubInvalidCondition,
    UNSET,
)

__all__ = [
    "ClassMetadata",
    "Field",
    "Index",
    "StorageDefinition",
    "StorageData",
    "StorageIndex",
    "StorageProperty",
    "StorageSQLMap",
    "StorageSQLMapData",
    "StorageSQLMapRowIdSpec",
    "StorageSQLMapSub",
    "StorageSQLMapSubAccessVar",
    "StorageSQLMapSubInvalidCondition",
    "Model",
    "SchemaDiff",
    "UNSET",
    "configure",
    "diff_schema",
    "ScaffoldResult",
    "ScaffoldWarning",
    "scaffold_from_iris",
    "scaffold_from_cls",
]
