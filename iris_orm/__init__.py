"""
iris_orm — explicit IRIS mapper and schema toolkit.
"""
from __future__ import annotations

from .adapter import IRISAdapter
from .binder import Binder
from .fields import FieldDefinition, RelationshipDefinition, field, relationship
from .metaclass import IRISMeta, IRISModel, IRISSerial, _MODEL_REGISTRY
from .registry import Registry
from .schema import (
    SchemaApplier,
    SchemaCatalog,
    SchemaClass,
    SchemaCompiler,
    SchemaIndex,
    SchemaPlan,
    SchemaPlanner,
    SchemaProperty,
    SchemaRelationship,
    SchemaStorage,
    SchemaStorageData,
    SchemaStorageValue,
    compile_declared_model_schema,
)
from .session import Session
from .types import (
    IRIS_TO_PYTHON,
    PYTHON_TO_IRIS,
    iris_type_to_annotation,
    iris_type_to_python,
    python_type_to_iris,
)

__all__ = [
    "IRISAdapter",
    "IRISMeta",
    "IRISModel",
    "IRISSerial",
    "Session",
    "Registry",
    "Binder",
    "SchemaApplier",
    "SchemaCatalog",
    "SchemaClass",
    "SchemaCompiler",
    "SchemaIndex",
    "SchemaPlan",
    "SchemaPlanner",
    "SchemaProperty",
    "SchemaRelationship",
    "SchemaStorage",
    "SchemaStorageData",
    "SchemaStorageValue",
    "_MODEL_REGISTRY",
    "FieldDefinition",
    "RelationshipDefinition",
    "field",
    "relationship",
    "compile_declared_model_schema",
    "IRIS_TO_PYTHON",
    "PYTHON_TO_IRIS",
    "iris_type_to_annotation",
    "iris_type_to_python",
    "python_type_to_iris",
]

__version__ = "0.5.0"
