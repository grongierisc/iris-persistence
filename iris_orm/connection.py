"""
Embedded IRIS connection helpers used across the ORM runtime.
"""
from __future__ import annotations

from typing import Any


class IRISConnection:
    """Thin wrapper around the embedded ``iris`` module."""

    def __init__(self) -> None:
        self._iris = self._import_iris()

    @staticmethod
    def _import_iris() -> Any:
        import iris  # noqa: PLC0415

        return iris

    def sql_exec(self, sql: str, params: list | None = None) -> Any:
        """Execute SQL through the embedded IRIS runtime."""
        return self._iris.sql.exec(sql, params) if params else self._iris.sql.exec(sql)

    def iris_cls(self, classname: str) -> Any:
        """Return the IRIS class proxy for *classname*."""
        return self._iris.cls(classname)

    def new_object(self, classname: str) -> Any:
        """Instantiate an IRIS object for *classname*."""
        return self.iris_cls(classname)._New()

    def open_object(self, classname: str, obj_id: str) -> Any:
        """Open an IRIS object by ID."""
        return self.iris_cls(classname)._OpenId(obj_id)

    def delete_object(self, classname: str, obj_id: str) -> None:
        """Delete an IRIS object by ID."""
        self.iris_cls(classname)._DeleteId(obj_id)

    def __enter__(self) -> "IRISConnection":
        return self

    def __exit__(self, *args: Any) -> None:
        return None
