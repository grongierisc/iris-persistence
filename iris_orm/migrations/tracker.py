"""
Migration history tracker stored in IRIS.
"""
from __future__ import annotations

from typing import Any

from iris_orm.schema import SchemaApplier, SchemaCatalog, SchemaClass, SchemaProperty

_TRACKER_CLASS = "IrisORM.MigrationHistory"


def init(adapter: Any) -> None:
    if adapter.class_exists(_TRACKER_CLASS):
        return
    tracker_catalog = SchemaCatalog(
        classes=(
            SchemaClass(
                name=_TRACKER_CLASS,
                superclass="%Persistent",
                kind="persistent",
                properties=(
                    SchemaProperty("Revision", "%String", required=True, maxlen=200),
                    SchemaProperty("Description", "%String", required=False, maxlen=500),
                    SchemaProperty("AppliedAt", "%TimeStamp"),
                ),
            ),
        )
    )
    from iris_orm.schema import SchemaPlanner  # noqa: PLC0415

    plan = SchemaPlanner().diff(SchemaCatalog(), tracker_catalog)
    SchemaApplier(adapter).apply(plan, allow_manual=True)


def get_applied(adapter: Any) -> list[str]:
    try:
        rows = adapter.sql_exec(
            f"SELECT Revision FROM {_TRACKER_CLASS} ORDER BY AppliedAt ASC",
            [],
        )
    except Exception:
        return []
    return [str(row[0]) for row in rows]


def mark_applied(adapter: Any, revision: str, description: str = "") -> None:
    import datetime  # noqa: PLC0415

    obj = adapter.iris_cls(_TRACKER_CLASS)._New()
    obj.Revision = revision
    obj.Description = description
    obj.AppliedAt = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    status = obj._Save()
    if not adapter.is_success_status(status):
        raise RuntimeError(f"Failed to record migration {revision!r}: {status!r}")


def mark_reverted(adapter: Any, revision: str) -> None:
    rows = adapter.sql_exec(f"SELECT %ID FROM {_TRACKER_CLASS} WHERE Revision = ?", [revision])
    for row in rows:
        adapter.iris_cls(_TRACKER_CLASS)._DeleteId(str(row[0]))
