"""
iris_persistence core package
"""

__version__ = "0.3.0"

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
from iris_persistence.query import from_iris, materialize
from iris_persistence.runtime import configure
from iris_persistence.scaffold import ScaffoldResult, ScaffoldWarning, scaffold_from_iris
from iris_persistence.schema import SchemaDiff, StorageMigrationRequired, diff_schema
from iris_persistence.types import (
    UNSET,
    ClassMetadata,
    Field,
    Index,
    StorageTuning,
)

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
