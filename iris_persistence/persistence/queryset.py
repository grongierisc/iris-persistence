from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Dict, Generic, List, Optional, Type, TypeVar

from iris_persistence.catalog import dbapi_cursor
from iris_persistence.runtime import get_runtime

if TYPE_CHECKING:
    from iris_persistence.models import Model

TModel = TypeVar("TModel", bound="Model")


def _resolve_sql_field_name(model_cls: Type[TModel], field_name: str) -> str:
    field_meta = model_cls._fields.get(field_name)
    if field_meta is None:
        valid_fields = ", ".join(sorted(model_cls._fields))
        raise ValueError(
            f"Unknown field {field_name!r} for {model_cls.__name__}. "
            f"Expected one of: {valid_fields}"
        )
    return str(getattr(field_meta, "sql_field_name", None) or field_name)


def _compiled_table_name(model_cls: Type[TModel]) -> str | None:
    runtime = get_runtime()
    try:
        with dbapi_cursor(runtime) as cursor:
            cursor.execute(
                "SELECT SqlTableName, SqlSchemaName FROM %Dictionary.CompiledClass WHERE Name = ?",
                (model_cls._classname,),
            )
            fetched = cursor.fetchone() if hasattr(cursor, "fetchone") else None
            row = tuple(fetched) if fetched is not None else None
            if row is None and not hasattr(cursor, "fetchone") and hasattr(cursor, "fetchall"):
                rows = cursor.fetchall()
                row = tuple(rows[0]) if rows else None
    except Exception as exc:
        warnings.warn(
            f"Could not resolve SQL table name for {model_cls._classname!r} "
            f"from IRIS metadata: {exc}. Falling back to model metadata.",
            RuntimeWarning,
            stacklevel=3,
        )
        return None
    if not row or not row[0]:
        return None
    return f"{row[1]}.{row[0]}" if row[1] else str(row[0])


def _resolve_sql_table_name(model_cls: Type[TModel]) -> str:
    cached = getattr(model_cls, "_sql_table_name", None)
    if cached:
        return cached
    metadata = getattr(model_cls, "_class_metadata", None)
    resolved = _compiled_table_name(model_cls)
    if resolved is None and metadata is not None:
        resolved = getattr(metadata, "sql_table_name", None)
    resolved = resolved or model_cls._classname
    setattr(model_cls, "_sql_table_name", resolved)
    return resolved


class QuerySet(Generic[TModel]):
    def __init__(
        self,
        model_cls: Type[TModel],
        filter_kwargs: Optional[Dict[str, Any]] = None,
        order_by_keys: Optional[List[str]] = None,
    ):
        self.model_cls = model_cls
        self.filter_kwargs = filter_kwargs or {}
        self.order_by_keys = order_by_keys or []

    def where(self, **kwargs: Any) -> QuerySet[TModel]:
        return QuerySet(self.model_cls, {**self.filter_kwargs, **kwargs}, self.order_by_keys)

    def order_by(self, *keys: str) -> QuerySet[TModel]:
        return QuerySet(self.model_cls, self.filter_kwargs, [*self.order_by_keys, *keys])

    def _select_ids(self) -> tuple[str, list[Any]]:
        sql = f"SELECT ID FROM {_resolve_sql_table_name(self.model_cls)}"
        params: list[Any] = []
        if self.filter_kwargs:
            conditions = []
            for name, value in self.filter_kwargs.items():
                conditions.append(f"{_resolve_sql_field_name(self.model_cls, name)} = ?")
                params.append(value)
            sql += " WHERE " + " AND ".join(conditions)
        if self.order_by_keys:
            fields = (_resolve_sql_field_name(self.model_cls, key) for key in self.order_by_keys)
            sql += " ORDER BY " + ", ".join(fields)
        return sql, params

    def all(self) -> List[TModel]:
        results: list[TModel] = []
        sql, params = self._select_ids()
        with dbapi_cursor(get_runtime()) as cursor:
            cursor.execute(sql, params)
            for row in cursor:
                instance = self.model_cls.get(str(row[0]))
                if instance is not None:
                    results.append(instance)
        return results
