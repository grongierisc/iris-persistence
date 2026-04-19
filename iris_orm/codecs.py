from __future__ import annotations

import datetime
from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin


def resolve_declared_type(hint: Any) -> Any:
    """Resolve Annotated/Optional wrappers down to the declared core Python type."""
    origin = get_origin(hint)
    if origin is Annotated:
        return resolve_declared_type(get_args(hint)[0])
    if origin in (Union, UnionType):
        args = [arg for arg in get_args(hint) if arg is not type(None)]
        if len(args) == 1:
            return resolve_declared_type(args[0])
    return hint


def _convert_with_iris(class_name: str, method_name: str, value: str) -> Any:
    try:
        import iris
    except ImportError:
        return value
    return getattr(iris.cls(class_name), method_name)(value)


def _coerce_logical_time(value: Any) -> datetime.time:
    total_microseconds = round(float(value) * 1_000_000)
    hours, remainder = divmod(total_microseconds, 3_600_000_000)
    minutes, remainder = divmod(remainder, 60_000_000)
    seconds, microseconds = divmod(remainder, 1_000_000)
    return datetime.time(int(hours), int(minutes), int(seconds), int(microseconds))


def coerce_value_for_save(expected_type: Any, value: Any) -> Any:
    """Convert Python values into a form IRIS save paths accept reliably."""
    if value is None:
        return None
    if expected_type is datetime.datetime and isinstance(value, datetime.datetime):
        return _convert_with_iris("%Library.TimeStamp", "OdbcToLogical", value.isoformat(sep=" "))
    if (
        expected_type is datetime.date
        and isinstance(value, datetime.date)
        and not isinstance(value, datetime.datetime)
    ):
        return _convert_with_iris("%Library.Date", "OdbcToLogical", value.isoformat())
    if expected_type is datetime.time and isinstance(value, datetime.time):
        return _convert_with_iris("%Library.Time", "OdbcToLogical", value.isoformat())
    return value


def coerce_value_for_load(expected_type: Any, value: Any) -> Any:
    """Convert values loaded from IRIS back to the declared Python type."""
    if value is None:
        return None
    if expected_type in (datetime.datetime, datetime.date, datetime.time) and value == "":
        return None
    if expected_type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"0", "false"}:
                return False
            if lowered in {"1", "true"}:
                return True
    if expected_type is datetime.datetime and isinstance(value, str):
        return datetime.datetime.fromisoformat(value)
    if expected_type is datetime.date:
        if isinstance(value, str) and "-" in value:
            return datetime.date.fromisoformat(value)
        logical_value = _convert_with_iris("%Library.Date", "LogicalToOdbc", str(value))
        if isinstance(logical_value, str):
            return datetime.date.fromisoformat(logical_value)
    if expected_type is datetime.time:
        if isinstance(value, str) and ":" in value:
            return datetime.time.fromisoformat(value)
        return _coerce_logical_time(value)
    return value
