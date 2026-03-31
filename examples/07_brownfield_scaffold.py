"""
07_brownfield_scaffold.py — Brownfield import / scaffold
========================================================

This example shows how to bring an existing IRIS project into `iris_orm`.

It covers two import paths:
1. Live IRIS namespace → scaffold Python models + sidecar lockfiles
2. Exported .cls tree   → scaffold Python models + sidecar lockfiles

The generated Python defaults to editable typed models, while the sidecar
files preserve IRIS-owned details such as storage, indexes, and class
parameters.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm.errors import LockfileDriftError
from iris_orm.scaffold import refresh_from_iris, scaffold_from_cls, scaffold_from_iris


OUTPUT_ROOT = Path("./generated_models")


def _print_written(header: str, paths: list[Path]) -> None:
    print(header)
    if not paths:
        print("  (no classes matched)")
        return
    for path in paths:
        print(f"  {path}")


def scaffold_live_namespace() -> None:
    """Scaffold from a live IRIS namespace when embedded IRIS is available."""
    try:
        written = scaffold_from_iris("Ens.StringRequest", OUTPUT_ROOT)
    except Exception as exc:
        print("Skipping live IRIS scaffold:")
        print(f"  {exc}")
        return
    _print_written("Scaffolded from live IRIS:", written)


def scaffold_from_exported_cls() -> None:
    """Scaffold from exported .cls files if a local cls tree exists."""
    cls_root = Path("./cls")
    if not cls_root.exists():
        print("\nSkipping .cls import example (./cls not found).")
        return

    written = scaffold_from_cls(cls_root, OUTPUT_ROOT)
    _print_written("\nScaffolded from .cls:", written)


def refresh_live_namespace() -> None:
    """Refresh an existing scaffold from a live IRIS namespace."""
    try:
        refreshed = refresh_from_iris("Ens.StringRequest", OUTPUT_ROOT)
    except LockfileDriftError as exc:
        print("\nSkipping live refresh:")
        print(f"  {exc}")
        print("  Run the initial scaffold first so adjacent lockfiles exist.")
        return
    except Exception as exc:
        print("\nSkipping live refresh:")
        print(f"  {exc}")
        return
    _print_written("\nRefreshed scaffold from live IRIS:", refreshed)


def main() -> None:
    # -----------------------------------------------------------------------
    # 1. Brownfield import from a live IRIS namespace
    # -----------------------------------------------------------------------
    # Use this when classes already exist in IRIS and you want Python models
    # generated from %Dictionary.
    scaffold_live_namespace()

    # -----------------------------------------------------------------------
    # 2. Brownfield import from exported .cls sources
    # -----------------------------------------------------------------------
    # Use this when you have an existing ObjectScript repo or exported classes
    # on disk and want the same Python + sidecar shape generated from source
    # files.
    scaffold_from_exported_cls()

    # -----------------------------------------------------------------------
    # 3. Refresh after IRIS changes
    # -----------------------------------------------------------------------
    # Refresh updates the generated block and sidecar metadata while preserving
    # manual Python code outside the generated markers.
    refresh_live_namespace()

    # -----------------------------------------------------------------------
    # 4. What gets written
    # -----------------------------------------------------------------------
    #
    # generated_models/demo/article.py
    #   -> real Python model you can edit
    #
    # generated_models/demo/article.iris.lock.json
    #   -> lockfile preserving superclass, parameters, indexes, source,
    #      generated-region hash, and the storage sidecar path
    #
    # generated_models/demo/article.iris.lock.json
    #   -> editable IRIS storage definition in native XML/text form
    #
    # The generated model contains:
    #   _iris_classname
    #   _iris_storage_mode = "preserve"
    #   _iris_lockfile_path = "article.iris.lock.json"
    #
    # That means:
    #   - Python owns logical fields / relationships
    #   - the sidecar files own IRIS-specific physical details
    #   - refresh will fail if you manually edit the generated block itself


if __name__ == "__main__":
    main()
