"""
01_plan_a.py — Plan A: bind to an existing IRIS class
======================================================

Use this when the IRIS class already exists (created in Studio / VS Code
ObjectScript extension / migration).  The metaclass queries
%Dictionary.PropertyDefinition at class-creation time and injects typed
descriptors automatically.

Assumes the following class exists in IRIS:

    Class Demo.Test Extends %Persistent
    {
        Property Foo As %String;
        Property Bar As %Integer;
    }
"""
import sys
sys.path.insert(0, "..")  # for easier imports in examples
from iris_orm import IRISModel

# ---------------------------------------------------------------------------
# 1. Bind to an existing IRIS class
# ---------------------------------------------------------------------------
# Just set _iris_classname.  No annotations needed.
# If IRIS is connected, descriptors (Test.Foo, Test.Bar) are auto-injected.
# If not connected yet, use Test.bind() after connecting.

class Test(IRISModel):
    _iris_classname = "Demo.Test"


# ---------------------------------------------------------------------------
# 2. Create and save
# ---------------------------------------------------------------------------

t = Test(Foo="hello", Bar=42)
t.save()
print(f"Saved: pk={t.pk}  Foo={t.Foo!r}  Bar={t.Bar}")


# ---------------------------------------------------------------------------
# 3. Open by ID
# ---------------------------------------------------------------------------

loaded = Test.get(t.pk)
print(f"Loaded: pk={loaded.pk}  Foo={loaded.Foo!r}  Bar={loaded.Bar}")


# ---------------------------------------------------------------------------
# 4. Update
# ---------------------------------------------------------------------------

loaded.Foo = "world"
loaded.Bar = loaded.Bar + 1
loaded.save()
print(f"Updated: Foo={loaded.Foo!r}  Bar={loaded.Bar}")


# ---------------------------------------------------------------------------
# 5. Query
# ---------------------------------------------------------------------------

# Create a few more records
for i in range(3):
    r = Test(Foo=f"item-{i}", Bar=i * 10)
    r.save()

print(f"\nAll Test records ({Test.objects.count()} total):")
for rec in Test.objects.all():
    print(f"  [{rec.pk}] Foo={rec.Foo!r}  Bar={rec.Bar}")

print("\nFilter Bar=20:")
for rec in Test.objects.filter(Bar=20):
    print(f"  [{rec.pk}] Foo={rec.Foo!r}  Bar={rec.Bar}")

first = Test.objects.first()
print(f"\nFirst: [{first.pk}] Foo={first.Foo!r}")


# ---------------------------------------------------------------------------
# 6. Delete
# ---------------------------------------------------------------------------

t.delete()
print(f"\nDeleted pk={t.pk} (should be None after delete): {t.pk}")


# ---------------------------------------------------------------------------
# 7. bind() — useful when class is defined before IRIS connects
# ---------------------------------------------------------------------------
# If you define your model classes at module import time (before the IRIS
# connection is established), descriptors won't be injected by the metaclass.
# Call .bind() once the connection is ready:
#
class Test(IRISModel):
    _iris_classname = "Demo.Test"

# ... later, connection established ...
Test.bind()   # re-runs introspection, injects typed descriptors
