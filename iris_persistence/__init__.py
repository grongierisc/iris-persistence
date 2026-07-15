"""Python models, persistence, runtime configuration, and managed IRIS schema."""

from __future__ import annotations

import warnings
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any

try:
    __version__ = version("iris-persistence")
except PackageNotFoundError:  # pragma: no cover - source tree without installed metadata
    __version__ = "0+unknown"

from iris_persistence.models import Model
from iris_persistence.query import from_iris as _from_iris
from iris_persistence.query import materialize as _materialize
from iris_persistence.runtime import (
    Runtime,
    RuntimeConfig,
    configure_runtime,
    get_runtime,
    install_runtime,
)
from iris_persistence.schema import SchemaDiff, StorageMigrationRequired, diff_schema
from iris_persistence.types import (
    UNSET,
    ClassMetadata,
    Field,
    Index,
    StorageTuning,
)

_DEPRECATED_ROOT_EXPORTS = {
    "ApplyResult": ("iris_persistence.migrations", "ApplyResult"),
    "BackupRestoreError": ("iris_persistence.migrations", "BackupRestoreError"),
    "MigrationOperation": ("iris_persistence.migrations", "MigrationOperation"),
    "MigrationPlan": ("iris_persistence.migrations", "MigrationPlan"),
    "RollbackResult": ("iris_persistence.migrations", "RollbackResult"),
    "VerifyResult": ("iris_persistence.migrations", "VerifyResult"),
    "apply_plan": ("iris_persistence.migrations", "apply_plan"),
    "check_drift": ("iris_persistence.migrations", "check_drift"),
    "create_plan": ("iris_persistence.migrations", "create_plan"),
    "rollback_backup": ("iris_persistence.migrations", "rollback_backup"),
    "verify_plan": ("iris_persistence.migrations", "verify_plan"),
    "ScaffoldResult": ("iris_persistence.scaffold", "ScaffoldResult"),
    "ScaffoldWarning": ("iris_persistence.scaffold", "ScaffoldWarning"),
    "scaffold_from_iris": ("iris_persistence.scaffold", "scaffold_from_iris"),
}


def __getattr__(name: str) -> Any:
    replacement = _DEPRECATED_ROOT_EXPORTS.get(name)
    if replacement is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = replacement
    warnings.warn(
        f"iris_persistence.{name} is deprecated and will be removed in 0.4.0; "
        f"import {attribute_name} from {module_name} instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return getattr(import_module(module_name), attribute_name)


def materialize(*args: Any, **kwargs: Any) -> Any:
    """Deprecated root wrapper; use ``Model.to_iris()`` instead."""
    warnings.warn(
        "iris_persistence.materialize() is deprecated and will be removed in 0.4.0; "
        "use Model.to_iris() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return _materialize(*args, **kwargs)


def from_iris(*args: Any, **kwargs: Any) -> Any:
    """Deprecated root wrapper; use ``Model.from_iris()`` instead."""
    warnings.warn(
        "iris_persistence.from_iris() is deprecated and will be removed in 0.4.0; "
        "use Model.from_iris() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return _from_iris(*args, **kwargs)


__all__ = [
    "ClassMetadata",
    "Field",
    "Index",
    "Model",
    "Runtime",
    "RuntimeConfig",
    "SchemaDiff",
    "StorageMigrationRequired",
    "StorageTuning",
    "UNSET",
    "configure_runtime",
    "diff_schema",
    "get_runtime",
    "install_runtime",
]
