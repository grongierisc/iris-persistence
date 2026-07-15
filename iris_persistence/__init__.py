"""
iris_persistence core package
"""

import warnings
from typing import Any

__version__ = "0.4.0"

from iris_persistence.migrations import (
    ApplyResult,
    BackupRestoreError,
    MigrationOperation,
    MigrationPlan,
    RollbackResult,
    VerifyResult,
    apply_plan,
    check_drift,
    create_plan,
    rollback_backup,
    verify_plan,
)
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
from iris_persistence.scaffold import ScaffoldResult, ScaffoldWarning, scaffold_from_iris
from iris_persistence.schema import SchemaDiff, StorageMigrationRequired, diff_schema
from iris_persistence.types import (
    UNSET,
    ClassMetadata,
    Field,
    Index,
    StorageTuning,
)


def materialize(*args: Any, **kwargs: Any) -> Any:
    """Deprecated root wrapper; use ``Model.to_iris()`` instead."""
    warnings.warn(
        "iris_persistence.materialize() is deprecated; use Model.to_iris() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return _materialize(*args, **kwargs)


def from_iris(*args: Any, **kwargs: Any) -> Any:
    """Deprecated root wrapper; use ``Model.from_iris()`` instead."""
    warnings.warn(
        "iris_persistence.from_iris() is deprecated; use Model.from_iris() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return _from_iris(*args, **kwargs)


__all__ = [
    "ClassMetadata",
    "Field",
    "Index",
    "ApplyResult",
    "BackupRestoreError",
    "MigrationOperation",
    "MigrationPlan",
    "RollbackResult",
    "StorageTuning",
    "Model",
    "SchemaDiff",
    "StorageMigrationRequired",
    "UNSET",
    "VerifyResult",
    "apply_plan",
    "check_drift",
    "Runtime",
    "RuntimeConfig",
    "configure_runtime",
    "create_plan",
    "diff_schema",
    "from_iris",
    "materialize",
    "get_runtime",
    "install_runtime",
    "rollback_backup",
    "ScaffoldResult",
    "ScaffoldWarning",
    "scaffold_from_iris",
    "verify_plan",
]
