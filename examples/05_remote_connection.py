"""
05_remote_connection.py — Connecting to a remote IRIS server
=============================================================

iris_orm supports the same SQLAlchemy engine connection strings as the
iris-global-reference project:

    iris://username:password@host:port/namespace        (community driver)
    iris+intersystems://username:password@dsn/namespace (official driver)
    iris+emb:///namespace                              (embedded)
    None                                               (embedded, default)

Set _iris_engine on any model class to route all its operations through
that engine.  Different model classes can use different connections.

Note: the Object API (iris.cls(...)) is only available for embedded
connections.  Over a remote connection, CRUD goes through SQL (SELECT %ID,
etc.) automatically.  Schema operations (push/pull/status) use
%Dictionary.PropertyDefinition queries and are fully supported remotely.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. Remote connection
# ---------------------------------------------------------------------------
# pip install sqlalchemy iris-driver  (or intersystems-irispython)

from sqlalchemy import create_engine

# Edit to match your IRIS instance:
IRIS_URL = "iris://SuperUser:SYS@localhost:1972/USER"

engine = create_engine(IRIS_URL)


# ---------------------------------------------------------------------------
# 2. Plan A with remote engine
# ---------------------------------------------------------------------------

from iris_orm import IRISModel

class RemoteTest(IRISModel):
    _iris_classname = "Demo.Test"
    _iris_engine    = engine           # ← all SQL goes through this engine

# Bind descriptors from the remote IRIS (queries %Dictionary.PropertyDefinition)
RemoteTest.bind()

# CRUD over remote connection
t = RemoteTest(Foo="remote hello", Bar=99)
t.save()
print(f"Saved remotely: pk={t.pk}")

loaded = RemoteTest.get(t.pk)
print(f"Loaded remotely: Foo={loaded.Foo!r}  Bar={loaded.Bar}")

print(f"Total records: {RemoteTest.objects.count()}")

t.delete()


# ---------------------------------------------------------------------------
# 3. Plan C with remote engine
# ---------------------------------------------------------------------------

from iris_orm import field
from iris_orm import schema

class RemoteArticle(IRISModel):
    _iris_classname = "Demo.RemoteArticle"
    _iris_engine    = engine

    Title:   str = field(required=True, maxlen=500)
    Content: str
    Views:   int = field(default=0)

    _iris_schema_snapshot: dict = {}

# Generate + compile the class over the remote connection
# (uses %SYSTEM.OBJ.Load via a temp file on the server)
RemoteArticle.schema.compile_to_iris()

a = RemoteArticle(Title="Remote Article", Content="Written from Python")
a.save()
print(f"\nRemote article saved: pk={a.pk}")

# Schema sync over remote connection
RemoteArticle.schema.commit()
d = RemoteArticle.schema.status()
print(f"Schema status: {'in sync' if d.in_sync else str(d)}")


# ---------------------------------------------------------------------------
# 4. Mixed: one class local, one class remote
# ---------------------------------------------------------------------------

class LocalCache(IRISModel):
    """Reads from the local embedded IRIS instance."""
    _iris_classname = "Demo.LocalCache"
    _iris_engine    = None             # embedded (default)

    Key:   str = field(required=True)
    Value: str

class RemoteData(IRISModel):
    """Reads from the remote IRIS server."""
    _iris_classname = "Demo.RemoteData"
    _iris_engine    = engine

    Payload: str


# ---------------------------------------------------------------------------
# 5. Connection string reference
# ---------------------------------------------------------------------------
#
# Community SQLAlchemy driver (open source):
#   pip install sqlalchemy-iris
#   engine = create_engine("iris://user:pass@host:1972/NAMESPACE")
#
# Official InterSystems driver:
#   pip install intersystems-irispython
#   engine = create_engine("iris+intersystems://user:pass@DSN/NAMESPACE")
#
# Embedded (in-process, fastest):
#   engine = None   (default)
#   engine = create_engine("iris+emb:///USER")
#
# The engine is passed transparently to IRISConnection which wraps it.
# iris_orm never imports sqlalchemy at package-import time — it is only
# imported lazily inside IRISConnection when engine is not None.
