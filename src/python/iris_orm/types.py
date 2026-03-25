"""
Type mapping utilities between IRIS types and Python types.
"""
from __future__ import annotations

import datetime
from typing import Any, Optional, get_args, get_origin, Union

# IRIS type string → Python type
IRIS_TO_PYTHON: dict[str, type] = {
    "%String": str,
    "%Library.String": str,
    "%Integer": int,
    "%Library.Integer": int,
    "%Float": float,
    "%Library.Float": float,
    "%Numeric": float,
    "%Double": float,
    "%Library.Double": float,
    "%Boolean": bool,
    "%Library.Boolean": bool,
    "%Date": datetime.date,
    "%Library.Date": datetime.date,
    "%Time": datetime.time,
    "%Library.Time": datetime.time,
    "%TimeStamp": datetime.datetime,
    "%Library.TimeStamp": datetime.datetime,
    "%PosixTime": datetime.datetime,
    "%List": list,
    "%Library.List": list,
    "%Stream.GlobalCharacter": str,
    "%Library.GlobalCharacter": str,
    "%Stream.GlobalBinary": bytes,
    "%Library.GlobalBinary": bytes,
}

# Python type → IRIS type
PYTHON_TO_IRIS: dict[type, str] = {
    str: "%String",
    int: "%Integer",
    float: "%Float",
    bool: "%Boolean",
    datetime.date: "%Date",
    datetime.time: "%Time",
    datetime.datetime: "%TimeStamp",
    list: "%List",
    bytes: "%Stream.GlobalBinary",
}


def iris_type_to_python(iris_type: str) -> type:
    """Convert an IRIS type string to a Python type. Falls back to Any."""
    return IRIS_TO_PYTHON.get(iris_type, Any)


def python_type_to_iris(py_type: type) -> str:
    """Convert a Python type to an IRIS type string. Falls back to %String."""
    # Handle Any sentinel
    if py_type is Any:
        return "%String"
    return PYTHON_TO_IRIS.get(py_type, "%String")


def iris_type_to_annotation(iris_type: str) -> str:
    """
    Return a string representation of the Python annotation for an IRIS type.
    e.g. "%String" → "Optional[str]", "%Date" → "Optional[datetime.date]", unknown → "Any"
    """
    py_type = IRIS_TO_PYTHON.get(iris_type)
    if py_type is None:
        return "Any"
    _TYPE_TO_STR: dict[type, str] = {
        str: "str",
        int: "int",
        float: "float",
        bool: "bool",
        datetime.date: "datetime.date",
        datetime.time: "datetime.time",
        datetime.datetime: "datetime.datetime",
        list: "list",
        bytes: "bytes",
    }
    type_str = _TYPE_TO_STR.get(py_type, str(py_type))
    return f"Optional[{type_str}]"


def unwrap_optional(tp: Any) -> type:
    """
    Strip Optional[T] → T. Handles Union[T, None] form.
    Passes everything else through unchanged.
    """
    origin = get_origin(tp)
    if origin is Union:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return tp
