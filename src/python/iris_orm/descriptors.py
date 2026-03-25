"""
Per-property descriptor that proxies typed get/set operations to the
underlying IRIS object via the Object API.
"""
from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar, overload, TYPE_CHECKING

if TYPE_CHECKING:
    from .metaclass import IRISModel  # noqa: F401

T = TypeVar("T")


class IRISDescriptor(Generic[T]):
    """Data descriptor backed by an IRIS object property.

    Gets and sets the property value directly on the wrapped IRIS object
    (``_iris_obj``) stored on each :class:`~iris_orm.IRISModel` instance.
    Type coercion is applied on *get* so that the value always matches the
    declared Python type (or ``None`` when the IRIS value is ``""``/``None``).
    """

    def __init__(self, prop_name: str, python_type: type, required: bool = False) -> None:
        self._prop_name = prop_name
        self._python_type = python_type
        self._required = required
        # Set by __set_name__ when the descriptor is assigned inside a class body.
        self._attr_name: str = prop_name

    def __set_name__(self, owner: type, name: str) -> None:
        self._attr_name = name

    # ------------------------------------------------------------------
    # descriptor protocol
    # ------------------------------------------------------------------

    @overload
    def __get__(self, obj: None, objtype: type) -> "IRISDescriptor[T]": ...

    @overload
    def __get__(self, obj: "IRISModel", objtype: type) -> Optional[T]: ...

    def __get__(self, obj: Any, objtype: Any = None) -> Any:
        if obj is None:
            return self
        iris_obj = object.__getattribute__(obj, "_iris_obj")
        raw = getattr(iris_obj, self._prop_name)
        return self._coerce(raw)

    def __set__(self, obj: Any, value: Optional[T]) -> None:
        iris_obj = object.__getattribute__(obj, "_iris_obj")
        setattr(iris_obj, self._prop_name, self._serialize(value))

    def __delete__(self, obj: Any) -> None:
        self.__set__(obj, None)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _coerce(self, raw: Any) -> Optional[T]:
        """Convert a raw IRIS value to the declared Python type."""
        if raw is None or raw == "":
            return None
        if self._python_type is Any:
            return raw  # type: ignore[return-value]
        try:
            return self._python_type(raw)  # type: ignore[call-arg]
        except (TypeError, ValueError):
            return raw  # type: ignore[return-value]

    def _serialize(self, value: Optional[T]) -> Any:
        """Convert a Python value back to a form suitable for IRIS."""
        if value is None:
            return ""
        import datetime
        if isinstance(value, datetime.datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(value, datetime.date):
            return value.strftime("%Y-%m-%d")
        if isinstance(value, datetime.time):
            return value.strftime("%H:%M:%S")
        return value

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"IRISDescriptor(prop={self._prop_name!r}, "
            f"type={getattr(self._python_type, '__name__', self._python_type)!r})"
        )
