"""
Mapping from IRIS type strings to Python types.
"""
from __future__ import annotations

import datetime
from typing import Any, Optional, Type

# Maps IRIS %Library type names to their Python equivalents.
IRIS_TO_PYTHON: dict[str, type] = {
    "%String":               str,
    "%Library.String":       str,
    "%Integer":              int,
    "%Library.Integer":      int,
    "%Float":                float,
    "%Library.Float":        float,
    "%Numeric":              float,
    "%Library.Numeric":      float,
    "%Double":               float,
    "%Library.Double":       float,
    "%Boolean":              bool,
    "%Library.Boolean":      bool,
    "%Date":                 datetime.date,
    "%Library.Date":         datetime.date,
    "%Time":                 datetime.time,
    "%Library.Time":         datetime.time,
    "%TimeStamp":            datetime.datetime,
    "%Library.TimeStamp":    datetime.datetime,
    "%PosixTime":            datetime.datetime,
    "%Library.PosixTime":    datetime.datetime,
    "%List":                 list,
    "%Library.List":         list,
    "%Stream.GlobalCharacter": str,
    "%Library.GlobalCharacter": str,
    "%Stream.GlobalBinary":  bytes,
    "%Library.GlobalBinary": bytes,
}


def iris_type_to_python(iris_type: str) -> type:
    """Return the Python type for a given IRIS type string.

    Falls back to ``Any`` for unknown / custom types.
    """
    return IRIS_TO_PYTHON.get(iris_type, Any)


def iris_type_to_annotation(iris_type: str) -> str:
    """Return a string representation of ``Optional[PythonType]`` for stub generation."""
    py_type = IRIS_TO_PYTHON.get(iris_type)
    if py_type is None:
        return "Any"
    module = getattr(py_type, "__module__", "builtins")
    name = py_type.__name__
    if module == "builtins":
        return f"Optional[{name}]"
    return f"Optional[{module}.{name}]"
