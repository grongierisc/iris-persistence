"""
06_migrations.py — Alembic-style versioned migrations
======================================================

iris_orm ships a migration system that generates versioned Python files,
tracks applied revisions in IRIS, and supports upgrade/downgrade — no
external tools required.

Workflow
--------
1. init          — create the MigrationHistory class in IRIS (once)
2. generate      — autogenerate a migration file from your Python models
3. upgrade       — apply pending migrations
4. (edit model)  — add a new field in Python
5. generate      — autogenerate the next migration
6. upgrade       — apply it
7. downgrade     — roll back if needed

Each generated file looks like:

    revision = "0001"
    down_revision = None

    def upgrade(conn):
        conn.create_class("Demo.Article", extends="%Persistent")
        conn.add_property("Demo.Article", "Title", "%String", required=True, maxlen=500)
        conn.add_property("Demo.Article", "Views",  "%Integer")

    def downgrade(conn):
        conn.drop_class("Demo.Article")
"""
from __future__ import annotations
import sys
sys.path.insert(0, "./src/python/")

from iris_orm import IRISModel, field
from iris_orm.migrations import MigrationRunner

# ---------------------------------------------------------------------------
# 1. Define the model
# ---------------------------------------------------------------------------

class Article(IRISModel):
    _iris_classname = "Demo.Article"
    Title: str = field(required=True, maxlen=500, description="Article headline")
    Body:  str = field(description="Full article body")


# ---------------------------------------------------------------------------
# 2. Create the migration history table in IRIS (idempotent — run once)
# ---------------------------------------------------------------------------

runner = MigrationRunner("./migrations")
runner.init()


# ---------------------------------------------------------------------------
# 3. Autogenerate the first migration
# ---------------------------------------------------------------------------

runner.generate("create article table", models=[Article])
# → writes ./migrations/0001_create_article_table.py

# Check what was generated:
runner.history()
# Rev     Status     Description
# --------------------------------------------------------
#  0001   pending    create article table


# ---------------------------------------------------------------------------
# 4. Apply the migration
# ---------------------------------------------------------------------------

runner.upgrade()
# Applying 0001: create article table … done

runner.current()    # → "0001"
runner.history()
# ✓ 0001   applied    create article table


# ---------------------------------------------------------------------------
# 5. Add a new field to the model
# ---------------------------------------------------------------------------

# In real code you'd edit the class body; here we simulate it:
from iris_orm.introspection import PropertyInfo
Article._iris_properties.append(
    PropertyInfo(name="Views", iris_type="%Integer",
                 python_type=int, required=False, collection="", default="0")
)

runner.generate("add views counter", models=[Article])
# → writes ./migrations/0002_add_views_counter.py


# ---------------------------------------------------------------------------
# 6. Apply the new migration
# ---------------------------------------------------------------------------

runner.upgrade()
# Applying 0002: add views counter … done

runner.history()
# ✓ 0001   applied    create article table
# ✓ 0002   applied    add views counter


# ---------------------------------------------------------------------------
# 7. Downgrade one step
# ---------------------------------------------------------------------------

runner.downgrade("0001")
# Reverting 0002: add views counter … done

runner.current()    # → "0001"


# ---------------------------------------------------------------------------
# Notes on destructive operations
# ---------------------------------------------------------------------------
# drop_class() and drop_property() are NEVER auto-generated.
# Add them manually to the generated migration file when intentional:
#
#   def upgrade(conn):
#       conn.drop_property("Demo.Article", "ObsoleteField")
#
#   def downgrade(conn):
#       conn.add_property("Demo.Article", "ObsoleteField", "%String")
