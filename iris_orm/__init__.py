from __future__ import annotations

from .fields import Field, FieldDefinition, Index, IndexDefinition, ParameterDefinition, field, index, parameter
from .model import IRISMeta, IRISModel
from .protocol import IRISRuntimeProtocol
from .runtime import (
    EmbeddedRuntime,
    IRISRuntime,
    NetworkRuntime,
    OfficialRuntime,
    configure,
    configure_default_runtime,  # kept for backward compat; prefer configure()
    reset_default_runtime,
)
from .scaffold import scaffold_from_cls, scaffold_from_iris
from .storage import StorageData, StorageDefinition, StorageProperty, StorageSQLMap

__all__ = [
    # Models
    "IRISMeta",
    "IRISModel",
    # Fields
    "Field",
    "FieldDefinition",
    "Index",
    "IndexDefinition",
    "ParameterDefinition",
    "field",
    "index",
    "parameter",
    # Storage
    "StorageDefinition",
    "StorageData",
    "StorageProperty",
    "StorageSQLMap",
    # Runtime — public surface
    "IRISRuntimeProtocol",
    "IRISRuntime",
    "EmbeddedRuntime",
    "NetworkRuntime",
    "OfficialRuntime",
    "configure",
    "configure_default_runtime",
    "reset_default_runtime",
    # Scaffold
    "scaffold_from_cls",
    "scaffold_from_iris",
]
