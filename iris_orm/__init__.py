"""
iris_orm core package
"""

__version__ = "0.1.0"

from iris_orm.models import IRISModel, Model
from iris_orm.runtime import configure
from iris_orm.schema import SchemaDiff, diff_schema
from iris_orm.scaffold import ScaffoldResult, ScaffoldWarning, scaffold_from_cls, scaffold_from_iris
from iris_orm.types import (
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
    "IRISModel",
    "SchemaDiff",
    "UNSET",
    "configure",
    "diff_schema",
    "ScaffoldResult",
    "ScaffoldWarning",
    "scaffold_from_iris",
    "scaffold_from_cls",
]
