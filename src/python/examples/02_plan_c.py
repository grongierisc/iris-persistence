"""
02_plan_c.py — Plan C: Python-first model definition
=====================================================

Use this when Python is the source of truth.  You define the schema in Python
using typed annotations + field() metadata, then generate the ObjectScript
.cls file and optionally compile it directly into IRIS.

No IRIS class needs to exist beforehand — iris_orm creates it for you.
"""
from __future__ import annotations
import sys
sys.path.insert(0, "./src/python/")
from iris_orm import IRISModel, field
from iris_orm import schema

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

    # Storage block — set once, never touched by the ORM again.
    # Leave empty to let IRIS auto-generate on first compile.
    _iris_storage: str = ""


# ---------------------------------------------------------------------------
# 2. Generate ObjectScript source
# ---------------------------------------------------------------------------

cls_source = Article.schema.generate_cls()
print("=== Generated ObjectScript ===")
print(cls_source)


# ---------------------------------------------------------------------------
# 3. Write to disk (preserves existing Storage block if file already exists)
# ---------------------------------------------------------------------------

output_path = Article.schema.write_cls("./output/cls")
print(f"Written: {output_path}")


# ---------------------------------------------------------------------------
# 4. Compile into IRIS
# ---------------------------------------------------------------------------
# This compiles the generated source directly into the connected IRIS instance.

# Article.schema.compile_to_iris()


# ---------------------------------------------------------------------------
# 5. CRUD — identical to Plan A once compiled
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
# 6. Stub generation for IDE auto-complete
# ---------------------------------------------------------------------------
# python -m iris_orm.stubs Demo.Article ./src/python/
# → writes ./src/python/Demo/Article.pyi
