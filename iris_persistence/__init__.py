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
from iris_persistence.runtime import configure_runtime
from iris_persistence.scaffold import ScaffoldResult, ScaffoldWarning, scaffold_from_iris
from iris_persistence.schema import SchemaDiff, StorageMigrationRequired, diff_schema
from iris_persistence.types import (
    UNSET,
    ClassMetadata,
    Field,
    Index,
    StorageTuning,
)


def configure(
    native_connection: Any | None = None,
    *,
    dbapi_connection: Any | None = None,
    iris_handle: Any | None = None,
    mode: str | None = None,
    install_dir: str | None = None,
) -> None:
    """Deprecated alias for :func:`configure_runtime`."""
    warnings.warn(
        "iris_persistence.configure() is deprecated; use configure_runtime() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    configure_runtime(
        native_connection,
        dbapi_connection=dbapi_connection,
        iris_handle=iris_handle,
        mode=mode,
        install_dir=install_dir,
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
    "configure",
    "configure_runtime",
    "create_plan",
    "diff_schema",
    "from_iris",
    "materialize",
    "rollback_backup",
    "ScaffoldResult",
    "ScaffoldWarning",
    "scaffold_from_iris",
    "verify_plan",
]
