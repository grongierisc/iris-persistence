from __future__ import annotations

from typing import Any


class IRISORMError(Exception):
    """Base class for all iris_orm exceptions."""


class IRISStatusError(IRISORMError):
    """Wraps a raw IRIS ``%Status`` failure.

    Attributes
    ----------
    status:
        The raw ``%Status`` value returned by IRIS (may be a string, integer,
        or an opaque IRIS object depending on the backend).
    """

    def __init__(self, message: str, status: Any = None) -> None:
        super().__init__(message)
        self.status: Any = status


class IRISObjectNotFound(IRISStatusError, LookupError):
    """Raised when ``get()`` / ``open_object()`` finds no record.

    Extends both :class:`IRISStatusError` and :class:`LookupError` so
    callers can catch either::

        try:
            product = Product.get(999)
        except LookupError:
            product = Product(Name="New")
    """


class IRISConcurrencyError(IRISStatusError):
    """Raised when ``%Save()`` fails due to a concurrency or lock conflict."""


class IRISValidationError(IRISStatusError):
    """Raised when a required field is missing or a type mismatch occurs on
    save."""


class IRISCompileError(IRISStatusError):
    """Raised when ``%SYSTEM.OBJ.Compile()`` returns an error status."""


class IRISSchemaError(IRISStatusError):
    """Raised when ``replace_class()`` or another schema-modification
    operation fails."""
