"""
iris_orm — Python ORM for InterSystems IRIS.

Supports two modes:
  Plan A (introspection-first): set _iris_classname; metaclass queries IRIS.
  Plan C (Python-first): write typed annotations + field()/relationship() metadata.
"""
from __future__ import annotations

from .connection import IRISConnection
from .metaclass import IRISModel, IRISSerial, IRISMeta, _MODEL_REGISTRY
from .query import IRISQuerySet
from .fields import field, relationship, FieldDefinition, RelationshipDefinition
from .errors import StorageConflictError, LockfileDriftError, UnsupportedClassFeatureError
from .types import (
    iris_type_to_python,
    python_type_to_iris,
    iris_type_to_annotation,
    IRIS_TO_PYTHON,
    PYTHON_TO_IRIS,
)
from . import schema

__all__ = [
    "IRISConnection",
    "IRISModel",
    "IRISSerial",
    "IRISMeta",
    "_MODEL_REGISTRY",
    "IRISQuerySet",
    "StorageConflictError",
    "LockfileDriftError",
    "UnsupportedClassFeatureError",
    "field",
    "relationship",
    "FieldDefinition",
    "RelationshipDefinition",
    "iris_type_to_python",
    "python_type_to_iris",
    "iris_type_to_annotation",
    "IRIS_TO_PYTHON",
    "PYTHON_TO_IRIS",
    "schema",
]

__version__ = "0.4.0"
