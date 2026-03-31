"""
Validated session-scoped query builder.
"""
from __future__ import annotations

from typing import Any, Iterator


class SessionQuery:
    def __init__(
        self,
        session: Any,
        model_class: type,
        *,
        filters_eq: dict[str, Any] | None = None,
        filters_in: dict[str, list[Any]] | None = None,
        order: list[tuple[str, str]] | None = None,
        limit_value: int | None = None,
        offset_value: int | None = None,
    ) -> None:
        self._session = session
        self._model_class = model_class
        self._schema = session.binder.schema_for(model_class)
        self._filters_eq = filters_eq or {}
        self._filters_in = filters_in or {}
        self._order = order or []
        self._limit_value = limit_value
        self._offset_value = offset_value

    def filter_eq(self, **kwargs: Any) -> "SessionQuery":
        updated = dict(self._filters_eq)
        updated.update(kwargs)
        return SessionQuery(
            self._session,
            self._model_class,
            filters_eq=updated,
            filters_in=dict(self._filters_in),
            order=list(self._order),
            limit_value=self._limit_value,
            offset_value=self._offset_value,
        )

    def filter_in(self, **kwargs: list[Any]) -> "SessionQuery":
        updated = dict(self._filters_in)
        updated.update({key: list(value) for key, value in kwargs.items()})
        return SessionQuery(
            self._session,
            self._model_class,
            filters_eq=dict(self._filters_eq),
            filters_in=updated,
            order=list(self._order),
            limit_value=self._limit_value,
            offset_value=self._offset_value,
        )

    def order_by(self, field_name: str, direction: str = "asc") -> "SessionQuery":
        return SessionQuery(
            self._session,
            self._model_class,
            filters_eq=dict(self._filters_eq),
            filters_in=dict(self._filters_in),
            order=self._order + [(field_name, direction)],
            limit_value=self._limit_value,
            offset_value=self._offset_value,
        )

    def limit(self, value: int) -> "SessionQuery":
        return SessionQuery(
            self._session,
            self._model_class,
            filters_eq=dict(self._filters_eq),
            filters_in=dict(self._filters_in),
            order=list(self._order),
            limit_value=int(value),
            offset_value=self._offset_value,
        )

    def offset(self, value: int) -> "SessionQuery":
        return SessionQuery(
            self._session,
            self._model_class,
            filters_eq=dict(self._filters_eq),
            filters_in=dict(self._filters_in),
            order=list(self._order),
            limit_value=self._limit_value,
            offset_value=int(value),
        )

    def count(self) -> int:
        sql, params = self._build_sql(count_only=True)
        rows = self._session.adapter.sql_exec(sql, params)
        for row in rows:
            return int(row[0])
        return 0

    def first(self) -> Any | None:
        query = self.limit(1)
        for item in query:
            return item
        return None

    def all(self) -> list[Any]:
        return list(self)

    def __iter__(self) -> Iterator[Any]:
        sql, params = self._build_sql(count_only=False)
        rows = self._session.adapter.sql_exec(sql, params)
        sliced = list(rows)
        if self._offset_value is not None:
            sliced = sliced[self._offset_value :]
        if self._limit_value is not None:
            sliced = sliced[: self._limit_value]
        for row in sliced:
            yield self._session.get(self._model_class, str(row[0]))

    def _build_sql(self, *, count_only: bool) -> tuple[str, list[Any]]:
        table = self._schema.name
        select = f"SELECT COUNT(*) FROM {table}" if count_only else f"SELECT %ID FROM {table}"
        params: list[Any] = []
        clauses: list[str] = []
        valid_fields = {prop.name for prop in self._schema.properties}
        for field_name, value in sorted(self._filters_eq.items()):
            self._validate_field(field_name, valid_fields)
            clauses.append(f"{field_name} = ?")
            params.append(value)
        for field_name, values in sorted(self._filters_in.items()):
            self._validate_field(field_name, valid_fields)
            if not values:
                clauses.append("1 = 0")
                continue
            placeholders = ", ".join("?" for _ in values)
            clauses.append(f"{field_name} IN ({placeholders})")
            params.extend(list(values))
        if clauses:
            select += " WHERE " + " AND ".join(clauses)
        if self._order and not count_only:
            parts = []
            for field_name, direction in self._order:
                self._validate_field(field_name, valid_fields)
                normalized = str(direction).lower()
                if normalized not in {"asc", "desc"}:
                    raise ValueError(f"Unsupported sort direction: {direction!r}")
                parts.append(f"{field_name} {normalized.upper()}")
            select += " ORDER BY " + ", ".join(parts)
        return select, params

    @staticmethod
    def _validate_field(field_name: str, valid_fields: set[str]) -> None:
        if field_name not in valid_fields:
            raise ValueError(f"Unknown field {field_name!r}")
