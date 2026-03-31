"""
Migration history tracker — stores applied revisions in IRIS.

Uses an IRIS %Persistent class `iris_orm.MigrationHistory` created
via %Dictionary on first `init()`.  No external database required.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iris_orm.connection import IRISConnection

_TRACKER_CLASS = "iris_orm.MigrationHistory"

_FIELDS = [
    ("Revision",    "%String",    True,  200),   # (name, type, required, maxlen)
    ("Description", "%String",    False, 500),
    ("AppliedAt",   "%TimeStamp", False, None),
]


def _status_is_success(status: object) -> bool:
    """Return True when an IRIS %Status value represents success."""
    return status in (None, 1, True) or str(status).strip() == "1"


def _save_dictionary_item(item: object, *, kind: str, identifier: str) -> None:
    """Persist a %Dictionary object and raise on error statuses."""
    try:
        status = item._Save()
    except Exception as exc:
        raise RuntimeError(f"Failed to save {kind} {identifier!r}: {exc}") from exc
    if not _status_is_success(status):
        raise RuntimeError(f"Failed to save {kind} {identifier!r}: {status}")


def init(conn: "IRISConnection") -> None:
    """
    Ensure the MigrationHistory %Persistent class exists in IRIS.
    Safe to call multiple times (idempotent).
    """
    from iris_orm.schema import _class_exists_in_iris  # noqa: PLC0415

    if _class_exists_in_iris(_TRACKER_CLASS, conn):
        return

    cls_def = conn.iris_cls("%Dictionary.ClassDefinition")._New()
    cls_def.Name = _TRACKER_CLASS
    cls_def.Super = "%Persistent"
    _save_dictionary_item(cls_def, kind="class", identifier=_TRACKER_CLASS)

    prop_cls = conn.iris_cls("%Dictionary.PropertyDefinition")
    for name, iris_type, required, maxlen in _FIELDS:
        prop_def = prop_cls._New()
        prop_def.Name = name
        prop_def.parent = cls_def
        prop_def.Type = iris_type
        prop_def.Required = int(required)
        if maxlen is not None:
            prop_def.Parameters.SetAt(str(maxlen), "MAXLEN")
        _save_dictionary_item(
            prop_def,
            kind="property",
            identifier=f"{_TRACKER_CLASS}||{name}",
        )

    try:
        conn.iris_cls("%SYSTEM.OBJ").Compile(_TRACKER_CLASS, "ck")
    except Exception as exc:
        import warnings  # noqa: PLC0415
        warnings.warn(f"MigrationHistory compile failed: {exc}", stacklevel=2)


def get_applied(conn: "IRISConnection") -> list[str]:
    """Return list of applied revision IDs, in application order."""
    sql = (
        f"SELECT Revision FROM {_TRACKER_CLASS} "
        "ORDER BY AppliedAt ASC"
    )
    try:
        rs = conn.sql_exec(sql, [])
        return [str(row[0]) for row in rs]
    except Exception:
        return []


def mark_applied(conn: "IRISConnection", revision: str, description: str = "") -> None:
    """Record a revision as applied."""
    import datetime  # noqa: PLC0415

    obj = conn.iris_cls(_TRACKER_CLASS)._New()
    obj.Revision = revision
    obj.Description = description
    obj.AppliedAt = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    obj._Save()


def mark_reverted(conn: "IRISConnection", revision: str) -> None:
    """Remove the applied record for a revision."""
    sql = f"SELECT %ID FROM {_TRACKER_CLASS} WHERE Revision = ?"
    try:
        rs = conn.sql_exec(sql, [revision])
        for row in rs:
            conn.iris_cls(_TRACKER_CLASS)._DeleteId(str(row[0]))
    except Exception as exc:
        raise RuntimeError(f"Failed to revert tracker record for {revision!r}: {exc}") from exc
