"""
04_schema_sync.py — Git-style schema sync
==========================================

The schema manager on every Plan C model provides a git-flavoured workflow
for keeping Python model definitions and live IRIS class definitions in sync.

Commands
--------
  Model.schema.status()    → 3-way diff: snapshot ↔ Python  AND  snapshot ↔ IRIS
  Model.schema.fetch()     → read live IRIS schema (no changes applied)
  Model.schema.push()      → Python additions → IRIS   (raises ConflictError on conflict)
  Model.schema.pull()      → IRIS additions → Python   (raises ConflictError on conflict)
  Model.schema.commit()    → mark current Python state as the new baseline snapshot

Conflict detection
------------------
A _iris_schema_snapshot dict records the agreed state after the last commit().
If BOTH Python and IRIS changed the same property since then → ConflictError.
Resolve by editing one side to match, then re-run push/pull.

Storage blocks
--------------
The Storage block is NEVER touched by any sync operation.
Set _iris_storage on the model to preserve a hand-tuned Storage definition.
"""
from __future__ import annotations

from iris_orm import IRISModel, field
from iris_orm.schema import ConflictError

# ---------------------------------------------------------------------------
# 1. Start: Python-first model with an empty snapshot
# ---------------------------------------------------------------------------

class Product(IRISModel):
    _iris_classname = "Demo.Product"

    Name:  str = field(required=True, maxlen=200)
    Price: float = field(default=0.0)
    Stock: int = field(default=0)

    # Snapshot of agreed state (empty = never committed)
    _iris_schema_snapshot: dict = {}

    # Paste hand-tuned Storage here — never modified by sync
    _iris_storage: str = ""


# Compile initial version to IRIS
Product.schema.compile_to_iris()

# Commit current Python state as baseline
Product.schema.commit()
print("After initial commit:")
print(f"  snapshot = {Product._iris_schema_snapshot}")


# ---------------------------------------------------------------------------
# 2. Python adds a new field
# ---------------------------------------------------------------------------
# Simulate: developer adds Description to the Python class.
# In practice you edit the class body; here we patch _iris_properties
# for demonstration purposes.

from iris_orm.introspection import PropertyInfo
from iris_orm.types import python_type_to_iris

new_prop = PropertyInfo(
    name="Description",
    iris_type="%String",
    python_type=str,
    required=False,
    collection="",
    default="",
)
Product._iris_properties.append(new_prop)

# status() shows the Python addition
d = Product.schema.status()
print(f"\nAfter adding Description in Python:\n{d}")

# push() writes it to IRIS and leaves snapshot unchanged
# (call commit() explicitly after reviewing)
try:
    Product.schema.push()
    print("push() succeeded — Description added to IRIS")
except ConflictError as e:
    print(f"Conflict: {e}")

Product.schema.commit()
print(f"New snapshot: {Product._iris_schema_snapshot}")


# ---------------------------------------------------------------------------
# 3. IRIS adds a new property (e.g. a DBA ran ALTER TABLE)
# ---------------------------------------------------------------------------
# Simulate by temporarily patching fetch() — in reality iris.sql.exec
# would return the new property from %Dictionary.PropertyDefinition.

_original_fetch = Product.schema.fetch

def _patched_fetch():
    result = _original_fetch()
    result["UpdatedAt"] = "%TimeStamp"
    return result

Product.schema.fetch = _patched_fetch

d = Product.schema.status()
print(f"\nAfter IRIS adds UpdatedAt:\n{d}")

# pull() updates the snapshot and injects the descriptor
Product.schema.pull()
print(f"After pull, snapshot: {Product._iris_schema_snapshot}")

# Restore
Product.schema.fetch = _original_fetch


# ---------------------------------------------------------------------------
# 4. Conflict scenario: both sides changed the same property
# ---------------------------------------------------------------------------

# Set snapshot: Price is %Float
Product._iris_schema_snapshot = {
    "Name":  "%String",
    "Price": "%Float",
    "Stock": "%Integer",
}

# Python has changed Price to %String (type mismatch in model)
for p in Product._iris_properties:
    if p.name == "Price":
        object.__setattr__(p, "iris_type", "%String")

# IRIS has changed Price to %Numeric
def _conflict_fetch():
    return {"Name": "%String", "Price": "%Numeric", "Stock": "%Integer"}

Product.schema.fetch = _conflict_fetch

d = Product.schema.status()
print(f"\nConflict scenario:\n{d}")

try:
    Product.schema.push()
except ConflictError as e:
    print(f"\nConflictError raised as expected: {e}")
    for conflict in e.conflicts:
        print(
            f"  Property {conflict.name!r}: "
            f"snapshot={conflict.snapshot_type!r}  "
            f"python={conflict.python_type!r}  "
            f"iris={conflict.iris_type!r}"
        )
    print("\nResolution: align Python or IRIS definition, then re-run push/pull.")


# ---------------------------------------------------------------------------
# 5. Removed properties — warnings only, never auto-deleted
# ---------------------------------------------------------------------------
# The ORM never drops an IRIS property automatically (data loss risk).
# Removals from Python are reported by status() but not applied by push().

print("\nNote: removing a property from Python triggers a warning, not deletion.")
print("Run: Model.schema.status() to see what's out of sync.")
print("Delete from IRIS manually via Studio / %Dictionary if intentional.")
