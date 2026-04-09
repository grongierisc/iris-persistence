from __future__ import annotations

from .exceptions import (
    IRISCompileError,
    IRISConcurrencyError,
    IRISObjectNotFound,
    IRISORMError,
    IRISSchemaError,
    IRISStatusError,
    IRISValidationError,
)
from .fields import Field, FieldDefinition, Index, IndexDefinition, ParameterDefinition, field, index, parameter
from .model import IRISMeta, IRISModel
from .protocol import IRISRuntimeProtocol
from .runtime import (
    CommunityRuntime,
    EmbeddedRuntime,
    OfficialRuntime,
    configure,
    configure_default_runtime,  # kept for backward compat; prefer configure()
    reset_default_runtime,
)
from .scaffold import scaffold_from_cls, scaffold_from_iris
from .storage import StorageData, StorageDefinition, StorageProperty, StorageSQLMap

__all__ = [
    # Models
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
    "EmbeddedRuntime",
    "CommunityRuntime",
    "OfficialRuntime",
    "configure",
    "configure_default_runtime",
    "reset_default_runtime",
    # Scaffold
    "scaffold_from_cls",
    "scaffold_from_iris",
    # Exceptions
    "IRISORMError",
    "IRISStatusError",
    "IRISObjectNotFound",
    "IRISConcurrencyError",
    "IRISValidationError",
    "IRISCompileError",
    "IRISSchemaError",
]
