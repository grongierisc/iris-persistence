"""
08_python_first_sync.py — Python-first sync with sidecar state
==============================================================

This example shows a Python-first model that also uses a scaffold lockfile.

The point of the lockfile is to let Python own the logical model while
preserving IRIS-owned details such as storage, indexes, and class parameters.
"""
from __future__ import annotations

from pathlib import Path

from iris_orm import IRISModel, field
from iris_orm.errors import LockfileDriftError, StorageConflictError
from iris_orm.lockfile import IRISLockfile, compute_hash, timestamp_utc, write_lockfile


STATE_ROOT = Path("./.iris_orm/state")
LOCKFILE_PATH = STATE_ROOT / "Demo.Product.json"


# ---------------------------------------------------------------------------
# 1. Python-first model with sidecar metadata
# ---------------------------------------------------------------------------

class Product(IRISModel):
    _iris_classname = "Demo.Product"
    _iris_storage_mode = "preserve"
    _iris_lockfile_path = "../.iris_orm/state/Demo.Product.json"

    Name: str = field(required=True, maxlen=200)
    Price: float = field(default=0.0)
    InStock: bool = field(default=True)


# ---------------------------------------------------------------------------
# 2. Create a sidecar lockfile
# ---------------------------------------------------------------------------
# In a real brownfield project this usually comes from `iris_orm.scaffold`.
# Here we create it explicitly so the example is self-contained.

lockfile = IRISLockfile(
    classname="Demo.Product",
    super="%Persistent",
    storage_mode="preserve",
    storage_definition="",
    storage_hash=compute_hash(""),
    class_parameters={"DEFAULTGLOBAL": "^Demo.ProductD"},
    indexes=[],
    source={"kind": "iris", "origin": "Demo.*"},
    scaffold_style="plan-c",
    generated_at=timestamp_utc(),
)
write_lockfile(LOCKFILE_PATH, lockfile)
print(f"Lockfile written: {LOCKFILE_PATH}")


# ---------------------------------------------------------------------------
# 3. Sync Python → IRIS
# ---------------------------------------------------------------------------
# Because storage mode is `preserve`, schema sync will protect storage drift.

try:
    Product.schema.ensure_iris_class()
    Product.schema.commit()
    print("Product synced to IRIS and snapshot committed.")
except StorageConflictError as exc:
    print(f"Storage conflict: {exc}")
except LockfileDriftError as exc:
    print(f"Lockfile drift: {exc}")


# ---------------------------------------------------------------------------
# 4. Check status
# ---------------------------------------------------------------------------

status = Product.schema.status()
print("\nSchema status:")
print(status)


# ---------------------------------------------------------------------------
# 5. Evolve the Python model
# ---------------------------------------------------------------------------
# In practice you edit the class body and re-run sync. The lockfile remains the
# preserved record of IRIS-owned details.
#
# Example next step:
#   add `Description: str = field()`
#   run `Product.schema.push()`
#
# If IRIS storage was tuned manually and no longer matches the lockfile,
# `push()` / `ensure_iris_class()` will raise `StorageConflictError`.
#
# If the sidecar is missing or stale, they will raise `LockfileDriftError`.
#
# That keeps Python-first workflows safe for brownfield IRIS projects.
