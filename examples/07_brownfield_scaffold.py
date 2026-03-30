"""
07_brownfield_scaffold.py — Brownfield import / scaffold
========================================================

This example shows how to bring an existing IRIS project into `iris_orm`.

It covers two import paths:
1. Live IRIS namespace → scaffold Python models + sidecar lockfiles
2. Exported .cls tree   → scaffold Python models + sidecar lockfiles

The generated Python defaults to editable Plan C models, while the sidecar
lockfiles preserve IRIS-owned details such as storage, indexes, and class
parameters.
"""
from __future__ import annotations

from pathlib import Path
import sys
sys.path.insert(0, ".")  # for easier imports in examples
from iris_orm.scaffold import refresh_from_iris, scaffold_from_cls, scaffold_from_iris


OUTPUT_ROOT = Path("./generated_models")
STATE_ROOT = Path("./.iris_orm/state")


# ---------------------------------------------------------------------------
# 1. Brownfield import from a live IRIS namespace
# ---------------------------------------------------------------------------
# Use this when classes already exist in IRIS and you want Python models
# generated from %Dictionary.
#
# Example:
#   Class Demo.Article Extends %Persistent
#   Class Demo.Author  Extends %Persistent
#   Class Demo.Address Extends %SerialObject

written = scaffold_from_iris(
    "Demo.*",
    OUTPUT_ROOT,
    state_root=STATE_ROOT,
    style="plan-c",
)

print("Scaffolded from live IRIS:")
for path in written:
    print(f"  {path}")


# ---------------------------------------------------------------------------
# 2. Brownfield import from exported .cls sources
# ---------------------------------------------------------------------------
# Use this when you have an existing ObjectScript repo or exported classes on
# disk and want the same Python + sidecar shape generated from source files.
#
# Example expected tree:
#   ./cls/Demo/Article.cls
#   ./cls/Demo/Author.cls

cls_root = Path("./cls")
if cls_root.exists():
    written_from_cls = scaffold_from_cls(
        cls_root,
        OUTPUT_ROOT,
        state_root=STATE_ROOT,
        style="plan-c",
        refresh=True,
    )
    print("\nScaffolded from .cls:")
    for path in written_from_cls:
        print(f"  {path}")
else:
    print("\nSkipping .cls import example (./cls not found).")


# ---------------------------------------------------------------------------
# 3. Refresh when IRIS changes
# ---------------------------------------------------------------------------
# After the initial scaffold, refresh updates the generated block and sidecar
# metadata while preserving manual Python code outside the generated markers.

refreshed = refresh_from_iris(
    "Demo.*",
    OUTPUT_ROOT,
    state_root=STATE_ROOT,
    style="plan-c",
)

print("\nRefreshed scaffold from live IRIS:")
for path in refreshed:
    print(f"  {path}")


# ---------------------------------------------------------------------------
# 4. What gets written
# ---------------------------------------------------------------------------
#
# generated_models/demo/article.py
#   → real Python model you can edit
#
# .iris_orm/state/Demo.Article.json
#   → lockfile preserving storage, superclass, parameters, indexes, source
#
# The generated model contains:
#   _iris_classname
#   _iris_storage_mode = "preserve"
#   _iris_lockfile_path = "../../../.iris_orm/state/Demo.Article.json"
#
# That means:
#   - Python owns logical fields / relationships
#   - the sidecar owns IRIS-specific physical details
#   - refresh will fail if you manually edit the generated block itself
