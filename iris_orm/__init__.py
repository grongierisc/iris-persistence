"""
iris_orm core package
"""

__version__ = "0.1.0"

from iris_orm.models import IRISModel
from iris_orm.runtime import configure
from iris_orm.scaffold import ScaffoldResult, ScaffoldWarning, scaffold_from_cls, scaffold_from_iris
from iris_orm.types import (
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
)

__all__ = [
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
    "IRISModel",
    "configure",
    "ScaffoldResult",
    "ScaffoldWarning",
    "scaffold_from_iris",
    "scaffold_from_cls",
]
