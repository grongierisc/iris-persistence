"""
Embedded IRIS adapter and low-level runtime helpers.
"""
from __future__ import annotations

from typing import Any


class IRISAdapter:
    """Low-level adapter around the embedded ``iris`` runtime."""

    def __init__(self) -> None:
        self._iris = self._import_iris()

    @staticmethod
    def _import_iris() -> Any:
        import iris  # noqa: PLC0415

        return iris

    def sql_exec(self, sql: str, params: list[Any] | None = None) -> Any:
        if params is None:
            return self._iris.sql.exec(sql)
        if not params:
            return self._iris.sql.exec(sql)
        return self._iris.sql.exec(sql, *params)

    def iris_cls(self, classname: str) -> Any:
        return self._iris.cls(classname)

    def new_object(self, classname: str) -> Any:
        return self.iris_cls(classname)._New()

    def open_object(self, classname: str, obj_id: str) -> Any:
        return self.iris_cls(classname)._OpenId(str(obj_id))

    def delete_object(self, classname: str, obj_id: str) -> None:
        self.iris_cls(classname)._DeleteId(str(obj_id))

    def class_exists(self, classname: str) -> bool:
        try:
            rows = self.sql_exec(
                "SELECT Name FROM %Dictionary.ClassDefinition WHERE Name = ?",
                [classname],
            )
            for _row in rows:
                return True
        except Exception:
            pass
        try:
            return bool(self.iris_cls("%Dictionary.ClassDefinition")._ExistsId(classname))
        except Exception:
            return False

    def compile_class(self, classname: str, flags: str = "ck") -> None:
        self.iris_cls("%SYSTEM.OBJ").Compile(classname, flags)

    def begin(self) -> None:
        try:
            self.sql_exec("START TRANSACTION", [])
        except Exception:
            pass

    def commit(self) -> None:
        try:
            self.sql_exec("COMMIT", [])
        except Exception:
            pass

    def rollback(self) -> None:
        try:
            self.sql_exec("ROLLBACK", [])
        except Exception:
            pass

    @staticmethod
    def is_success_status(status: Any) -> bool:
        return status in (None, 1, True) or str(status).strip() == "1"

    def save(self, item: Any, *, kind: str, identifier: str) -> None:
        try:
            status = item._Save()
        except Exception as exc:
            raise RuntimeError(f"Failed to save {kind} {identifier!r}: {exc}") from exc
        if not self.is_success_status(status):
            raise RuntimeError(f"Failed to save {kind} {identifier!r}: {status}")

    @staticmethod
    def looks_like_iris_object(value: Any) -> bool:
        return value is not None and hasattr(value, "_Save")
