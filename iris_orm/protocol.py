from __future__ import annotations

from typing import Any, Protocol

from .schema import SchemaClass


class IRISRuntimeProtocol(Protocol):
    """Protocol defining the interface for IRIS runtime backends.

    Mirrors the architecture of ``iris_global.GrefABC``: the Protocol is
    structural (no inheritance required).  Any object that implements all of
    these methods is accepted by ``iris_orm`` as a runtime backend, including
    ``EmbeddedRuntime``, ``NetworkRuntime``, ``OfficialRuntime``, and the
    ``FakeAdapter`` used in tests.
    """

    # ------------------------------------------------------------------ schema

    def load_schema(self, classname: str) -> dict[str, Any] | None:
        """Return the raw schema dict for *classname*, or ``None`` if it does
        not exist in the IRIS dictionary."""
        ...

    def list_classes(self, pattern: str) -> list[str]:
        """Return sorted class names matching *pattern* (glob-style)."""
        ...

    def replace_class(self, schema_class: SchemaClass) -> None:
        """Upsert an IRIS class definition from *schema_class* and compile it."""
        ...

    # ------------------------------------------------------------------ objects

    def save_object(
        self,
        classname: str,
        data: dict[str, Any],
        obj_id: Any | None = None,
    ) -> Any:
        """Persist *data* as an instance of *classname*.

        Returns the object ID (existing or newly assigned).
        """
        ...

    def open_object(
        self, classname: str, obj_id: Any
    ) -> dict[str, Any] | None:
        """Return ``{"id": …, "data": {…}}`` for *obj_id*, or ``None``."""
        ...

    def open_native_object(self, classname: str, obj_id: Any) -> Any | None:
        """Return the raw IRIS object for *obj_id*, or ``None``."""
        ...

    def native_class(self, classname: str) -> Any:
        """Return the raw IRIS class proxy for *classname*."""
        ...

    def delete_object(self, classname: str, obj_id: Any) -> None:
        """Delete the object identified by *obj_id*."""
        ...

    # ------------------------------------------------------------------ queries

    def query_rows(
        self,
        classname: str,
        fields: list[str],
        filters: dict[str, Any],
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return rows matching *filters* as ``[{"id": …, field: value, …}]``."""
        ...

    def sql(
        self,
        statement: str,
        params: list[Any] | None = None,
    ) -> list[tuple[Any, ...]]:
        """Execute a raw SQL *statement* and return the result rows."""
        ...

    # ------------------------------------------------------------------ utility

    def compile(self, classname: str) -> None:
        """Compile *classname* in IRIS."""
        ...

    def looks_like_iris_object(self, value: Any) -> bool:
        """Return ``True`` when *value* appears to be a valid IRIS object."""
        ...
