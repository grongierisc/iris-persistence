"""
08_python_first_sync.py — Declared-model sync with sidecar state
================================================================

This example shows a declared model that auto-generates adjacent sidecar files.

The point of the sidecar files is to let Python own the logical model while
preserving IRIS-owned details such as storage, indexes, and class parameters.
"""
from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm import IRISModel, field
from iris_orm.connection import IRISConnection
from iris_orm.errors import LockfileDriftError, StorageConflictError


class Product(IRISModel):
    _iris_classname = "Demo.Product"

    Name: str = field(required=True, maxlen=200)
    Price: float = field(default=0.0)
    InStock: bool = field(default=True)


def _embedded_iris_available() -> bool:
    """Return True when the embedded IRIS object API is actually usable."""
    try:
        conn = IRISConnection()
        class_proxy = conn.iris_cls("%Dictionary.ClassDefinition")
    except Exception:
        return False
    return not isinstance(class_proxy, Mock)


def main() -> None:
    # -----------------------------------------------------------------------
    # 1. Preflight
    # -----------------------------------------------------------------------
    # `ensure_iris_class()` will create or update the IRIS class and then write
    # `08_python_first_sync.iris.lock.json` next to this Python module.
    if not _embedded_iris_available():
        print("Skipping declared-model sync example:")
        print("  Embedded IRIS is not available in this environment.")
        return

    # -----------------------------------------------------------------------
    # 2. Sync Python -> IRIS
    # -----------------------------------------------------------------------
    try:
        Product.schema.ensure_iris_class()
        Product.schema.commit()
    except StorageConflictError as exc:
        print(f"Storage conflict: {exc}")
        return
    except LockfileDriftError as exc:
        print(f"Lockfile drift: {exc}")
        return

    print(f"Sidecar lockfile: {Product._iris_lockfile_path}")
    print("Product synced to IRIS and snapshot committed.")

    # -----------------------------------------------------------------------
    # 3. Check status
    # -----------------------------------------------------------------------
    status = Product.schema.status()
    print("\nSchema status:")
    print(status)

    # -----------------------------------------------------------------------
    # 4. Evolve the Python model
    # -----------------------------------------------------------------------
    # In practice you edit the class body and re-run sync. The lockfile remains
    # the preserved record of IRIS-owned details, including canonical storage
    # metadata.
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
    # That keeps declared-model workflows safe for brownfield IRIS projects.


if __name__ == "__main__":
    main()
