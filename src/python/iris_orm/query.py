"""
IRISQuerySet — iterable result set backed by ``SELECT %ID FROM <classname>``.

Supports lazy iteration, ``filter()``, ``count()``, ``first()``, and
``all()`` so that callers never need to write SQL directly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator, Optional

if TYPE_CHECKING:
    from .metaclass import IRISModel  # noqa: F401


class IRISQuerySet:
    """A lazy, re-iterable query over a single IRIS persistent class.

    The underlying SQL is only executed when the queryset is iterated,
    or when :meth:`count` / :meth:`first` are called.

    Parameters
    ----------
    model_class:
        The :class:`~iris_orm.IRISModel` subclass this queryset operates on.
    where_clauses:
        List of ``(column, operator, value)`` tuples accumulated by
        successive :meth:`filter` calls.
    """

    def __init__(
        self,
        model_class: type,
        where_clauses: Optional[list[tuple[str, str, Any]]] = None,
    ) -> None:
        self._model_class = model_class
        self._where: list[tuple[str, str, Any]] = where_clauses or []

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def filter(self, **kwargs: Any) -> "IRISQuerySet":
        """Return a new queryset with extra equality filters.

        Example::

            Post.objects.filter(Author="alice")
        """
        new_where = list(self._where)
        for key, value in kwargs.items():
            new_where.append((key, "=", value))
        return IRISQuerySet(self._model_class, new_where)

    def all(self) -> "IRISQuerySet":
        """Return a clone of this queryset (mirrors Django convention)."""
        return IRISQuerySet(self._model_class, list(self._where))

    def count(self) -> int:
        """Return the number of matching rows without loading full objects."""
        import iris  # type: ignore[import]

        sql, params = self._build_sql(count_only=True)
        rs = iris.sql.exec(sql, params)
        for row in rs:
            return int(row[0])
        return 0

    def first(self) -> Optional["IRISModel"]:
        """Return the first matching instance, or ``None``."""
        for obj in self:
            return obj
        return None

    # ------------------------------------------------------------------
    # iteration
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator["IRISModel"]:
        import iris  # type: ignore[import]

        classname: str = self._model_class._iris_classname  # type: ignore[attr-defined]
        sql, params = self._build_sql(count_only=False)
        rs = iris.sql.exec(sql, params)
        for row in rs:
            obj_id = str(row[0])
            instance = self._model_class._open(obj_id)  # type: ignore[attr-defined]
            if instance is not None:
                yield instance

    def __len__(self) -> int:
        return self.count()

    def __repr__(self) -> str:  # pragma: no cover
        classname = getattr(self._model_class, "_iris_classname", "?")
        return f"<IRISQuerySet [{classname}] filters={self._where!r}>"

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _build_sql(
        self, count_only: bool = False
    ) -> tuple[str, list[Any]]:
        classname: str = self._model_class._iris_classname  # type: ignore[attr-defined]
        select = "SELECT COUNT(*)" if count_only else "SELECT %ID"
        sql = f"{select} FROM {classname}"
        params: list[Any] = []
        if self._where:
            clauses = []
            for col, op, val in self._where:
                clauses.append(f"{col} {op} ?")
                params.append(val)
            sql += " WHERE " + " AND ".join(clauses)
        return sql, params
