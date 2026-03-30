"""
QuerySet for lazy, chainable IRIS SQL queries.
"""
from __future__ import annotations

from typing import Any, Iterator, Optional

from .connection import IRISConnection


class IRISQuerySet:
    """Lazy, chainable queryset that builds SQL against an IRIS class table."""

    def __init__(
        self,
        model_class: type,
        where_clauses: Optional[list[tuple[str, str, Any]]] = None,
    ) -> None:
        self._model = model_class
        self._where: list[tuple[str, str, Any]] = where_clauses or []

    # ------------------------------------------------------------------
    # Chainable builders
    # ------------------------------------------------------------------

    def filter(self, **kwargs: Any) -> "IRISQuerySet":
        """Return a new queryset restricted by equality conditions."""
        new_where = self._where + [(key, "=", value) for key, value in kwargs.items()]
        return IRISQuerySet(self._model, new_where)

    def all(self) -> "IRISQuerySet":
        """Return a shallow clone of this queryset."""
        return IRISQuerySet(self._model, list(self._where))

    # ------------------------------------------------------------------
    # Terminal methods
    # ------------------------------------------------------------------

    def count(self) -> int:
        sql, params = self._build_sql(count_only=True)
        rs = IRISConnection().sql_exec(sql, params)
        for row in rs:
            return int(row[0])
        return 0

    def first(self) -> Any | None:
        for obj in self:
            return obj
        return None

    def __iter__(self) -> Iterator[Any]:
        sql, params = self._build_sql(count_only=False)
        rs = IRISConnection().sql_exec(sql, params)
        for row in rs:
            obj_id = str(row[0])
            instance = self._model._open(obj_id)
            if instance is not None:
                yield instance

    # ------------------------------------------------------------------
    # SQL builder
    # ------------------------------------------------------------------

    def _build_sql(self, count_only: bool) -> tuple[str, list[Any]]:
        classname: str = self._model._iris_classname  # type: ignore[attr-defined]
        # IRIS SQL uses the class name directly as the table name.
        if count_only:
            select = f"SELECT COUNT(*) FROM {classname}"
        else:
            select = f"SELECT %ID FROM {classname}"

        params: list[Any] = []
        if self._where:
            conditions = []
            for col, op, val in self._where:
                conditions.append(f"{col} {op} ?")
                params.append(val)
            select += " WHERE " + " AND ".join(conditions)

        return select, params
