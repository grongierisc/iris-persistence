from __future__ import annotations

from .fields import FieldDefinition, IndexDefinition, ParameterDefinition, field, index, parameter
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

__all__ = [
    # Models
    "IRISMeta",
    "IRISModel",
    # Fields
    "FieldDefinition",
    "IndexDefinition",
    "ParameterDefinition",
    "field",
    "index",
    "parameter",
    # Runtime — public surface
    "IRISRuntimeProtocol",
    "IRISRuntime",
    "EmbeddedRuntime",
    "NetworkRuntime",
    "OfficialRuntime",
    "configure",
    "reset_default_runtime",
    # Scaffold
    "scaffold_from_cls",
    "scaffold_from_iris",
]
