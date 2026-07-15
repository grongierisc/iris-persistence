from __future__ import annotations

import datetime
from dataclasses import dataclass
from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin

# Sentinel stored in IRIS string properties to represent Python None.
NULL_STRING = "\x00"


@dataclass(frozen=True)
class ScalarCodec:
    """Classify scalar fields for the generic load and save plans."""

    read_kind: str
    save_kind: str

SCALAR_CODECS: dict[Any, ScalarCodec] = {
    str: ScalarCodec("str", "scalar_fast"),
    bool: ScalarCodec("bool", "scalar_fast"),
    int: ScalarCodec("primitive", "scalar_fast"),
    float: ScalarCodec("primitive", "scalar_fast"),
}


# Scalar conversion rules used by the generic load/save paths.
def load_scalar_str(value: Any) -> Any:
    """IRIS str property -> Python (NULL_STRING sentinel -> None, falsy -> '')."""
    return None if value == NULL_STRING else (value if value else "")


def load_scalar_number(value: Any, nullable: bool) -> Any:
    return None if nullable and value in ("", None) else value


def load_scalar_bool(value: Any, nullable: bool) -> Any:
    if nullable and value in ("", None):
        return None
    return bool(value or 0)


def save_scalar_null(declared_type: Any) -> Any:
    """Value stored in IRIS for None in a nullable scalar property."""
    return NULL_STRING if declared_type is str else ""


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
    from iris_persistence.runtime import RuntimeConfigurationError, get_runtime

    try:
        return get_runtime().call_classmethod(class_name, method_name, value)
    except RuntimeConfigurationError:
        return value


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


def _load_bool(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false"}:
            return False
        if normalized in {"1", "true"}:
            return True
    return value


def _load_datetime(value: Any) -> Any:
    return datetime.datetime.fromisoformat(value) if isinstance(value, str) else value


def _load_date(value: Any) -> Any:
    if isinstance(value, str) and "-" in value:
        return datetime.date.fromisoformat(value)
    logical_value = _convert_with_iris("%Library.Date", "LogicalToOdbc", str(value))
    return (
        datetime.date.fromisoformat(logical_value)
        if isinstance(logical_value, str)
        else value
    )


def _load_time(value: Any) -> Any:
    if isinstance(value, str) and ":" in value:
        return datetime.time.fromisoformat(value)
    return _coerce_logical_time(value)


_LOAD_COERCERS = {
    bool: _load_bool,
    datetime.datetime: _load_datetime,
    datetime.date: _load_date,
    datetime.time: _load_time,
}


def coerce_value_for_load(expected_type: Any, value: Any) -> Any:
    """Convert values loaded from IRIS back to the declared Python type."""
    if value is None or (expected_type is str and value == NULL_STRING):
        return None
    if expected_type in (datetime.datetime, datetime.date, datetime.time) and value == "":
        return None
    coercer = _LOAD_COERCERS.get(expected_type)
    return coercer(value) if coercer is not None else value
