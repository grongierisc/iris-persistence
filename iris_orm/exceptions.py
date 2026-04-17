from __future__ import annotations

from typing import Any


class IRISORMError(Exception):
    """Base class for all iris_orm exceptions."""


class IRISStatusError(IRISORMError):
    """Wraps a raw IRIS ``%Status`` failure."""

    def __init__(self, message: str, status: Any = None) -> None:
        super().__init__(message)
        self.status: Any = status


class IRISObjectNotFound(IRISStatusError, LookupError):
    """Raised when ``get()`` finds no record."""


class IRISConcurrencyError(IRISStatusError):
    """Raised when ``%Save()`` fails due to a concurrency or lock conflict."""


class IRISValidationError(IRISStatusError):
    """Raised when a required field is missing or a type mismatch occurs on save."""


class IRISCompileError(IRISStatusError):
    """Raised when ``%SYSTEM.OBJ.Compile()`` returns an error status."""


class IRISSchemaError(IRISStatusError):
    """Raised when a schema-modification operation fails."""
