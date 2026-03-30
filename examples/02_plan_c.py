"""
02_plan_c.py — Plan C: Python-first model definition
=====================================================

Use this when Python is the source of truth.  You define the schema in Python
using typed annotations + field() metadata, then create the IRIS class directly
via %Dictionary — no .cls files required.

No IRIS class needs to exist beforehand — iris_orm creates it for you.
"""
from __future__ import annotations
import sys
sys.path.insert(0, "./src/python/")
from iris_orm import IRISModel, field

# ---------------------------------------------------------------------------
# 1. Define the model in Python
# ---------------------------------------------------------------------------

class Article(IRISModel):
    _iris_classname = "Demo.Article"

    # Typed annotations + field() metadata drive everything:
    Title:   str = field(required=True, maxlen=500, description="Article headline")
    Slug:    str = field(required=True, maxlen=200, description="URL-safe identifier")
    Body:    str = field(description="Full article body text")
    Views:   int = field(default=0, description="View counter")
    Published: bool = field(default=False)


# ---------------------------------------------------------------------------
# 2. Create or update the IRIS class via %Dictionary (no .cls files)
# ---------------------------------------------------------------------------
# This creates the class definition and all properties directly in IRIS
# using %Dictionary.ClassDefinition and %Dictionary.PropertyDefinition.
# Call this whenever you add, change, or remove properties in your model.

Article.schema.ensure_iris_class()
print("IRIS class created/updated via %Dictionary")


# ---------------------------------------------------------------------------
# 3. CRUD — identical to Plan A once the class exists
# ---------------------------------------------------------------------------

a = Article(Title="Hello iris_orm", Slug="hello-iris-orm", Body="...")
a.save()
print(f"\nSaved: pk={a.pk}  Title={a.Title!r}  Views={a.Views}")

a.Views = 1
a.save()

loaded = Article.get(a.pk)
print(f"Loaded: Views={loaded.Views}")

print(f"\nAll articles ({Article.objects.count()} total):")
for art in Article.objects.all():
    print(f"  [{art.pk}] {art.Title!r}  published={art.Published}")


# ---------------------------------------------------------------------------
# 4. Stub generation for IDE auto-complete
# ---------------------------------------------------------------------------
# python -m iris_orm.stubs Demo.Article ./src/python/
# → writes ./src/python/Demo/Article.pyi
