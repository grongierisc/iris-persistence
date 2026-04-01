"""
Shared error types for iris_orm.
"""
from __future__ import annotations


class StorageConflictError(Exception):
    """Raised when preserved storage drift is detected."""


class UnsupportedClassFeatureError(Exception):
    """Raised when a class uses unsupported features for scaffolding."""
