from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from iris_persistence.field_utils import coerce_bool


class DictionarySession:
    """Shared lifecycle and query primitives for IRIS dictionary readers."""

    def __init__(self, connection: Any):
        self._connection = connection
        self._cursor = connection.cursor()

    def close(self) -> None:
        for handle in (self._cursor, self._connection):
            close = getattr(handle, "close", None)
            if callable(close):
                close()

    def fetchall(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        self._cursor.execute(sql, params)
        return list(self._cursor.fetchall())

    def fetchone(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        self._cursor.execute(sql, params)
        return self._cursor.fetchone()


@contextmanager
def dbapi_cursor(runtime: Any) -> Iterator[Any]:
    """Yield a DB-API cursor and close every handle owned by the call."""
    connection = runtime.get_dbapi_connection()
    cursor = connection.cursor()
    try:
        yield cursor
    finally:
        for handle in (cursor, connection):
            close = getattr(handle, "close", None)
            if callable(close):
                close()


def safe_get_property(runtime: Any, obj: Any, name: str) -> Any:
    try:
        return runtime.get_property(obj, name)
    except Exception:
        return None


def item_belongs_to_class(
    runtime: Any,
    item: Any,
    classname: str,
    *,
    unknown_is_owned: bool = False,
) -> bool:
    """Resolve ownership with an explicit policy for incomplete dictionary metadata."""
    inherited = safe_get_property(runtime, item, "Inherited")
    if inherited is not None:
        return not coerce_bool(inherited)

    for attr_name in ("Origin", "Parent", "parent", "Class"):
        owner = safe_get_property(runtime, item, attr_name)
        if owner in (None, ""):
            continue
        owner_name = safe_get_property(runtime, owner, "Name")
        return str(owner_name if owner_name not in (None, "") else owner) == classname

    return unknown_is_owned


def dictionary_rows(runtime: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Execute a dictionary query, returning an empty fallback for unsupported projections."""
    try:
        with dbapi_cursor(runtime) as cursor:
            cursor.execute(sql, params)
            columns = [str(column[0]) for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception:
        # Dictionary columns differ between supported IRIS releases. Callers
        # combine this result with the object API, which is the compatibility fallback.
        return []
