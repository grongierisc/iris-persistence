from __future__ import annotations

import datetime
from dataclasses import dataclass
from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin

# Sentinel stored in IRIS string properties to represent Python None.
NULL_STRING = "\x00"


@dataclass(frozen=True)
class ScalarCodec:
    """Scalar semantics shared by generic execution and generated model functions."""

    read_kind: str
    save_kind: str

    def load_expression(self, value: str, *, nullable: bool) -> str:
        if self.read_kind == "str":
            return f"None if {value} == _NULL_STRING else ({value} if {value} else '')"
        if self.read_kind == "bool":
            if nullable:
                return f"None if {value} in ('', None) else bool({value} or 0)"
            return f"bool({value} or 0)"
        if nullable:
            return f"None if {value} in ('', None) else {value}"
        return value

    def save_expression(self, value: str, *, nullable: bool) -> str:
        if self.read_kind == "str":
            return f"_NULL_STRING if {value} is None else {value}"
        if self.read_kind == "bool":
            converted = f"1 if {value} else 0"
            return f"'' if {value} is None else ({converted})" if nullable else converted
        return f"'' if {value} is None else {value}" if nullable else value

    def skips_none_on_save(self, *, nullable: bool) -> bool:
        return not nullable and self.read_kind != "str"


SCALAR_CODECS: dict[Any, ScalarCodec] = {
    str: ScalarCodec("str", "scalar_fast"),
    bool: ScalarCodec("bool", "scalar_fast"),
    int: ScalarCodec("primitive", "scalar_fast"),
    float: ScalarCodec("primitive", "scalar_fast"),
}


# Scalar conversion rules shared by the generic load/save paths (query.py) and the
# per-class code generators (models._build_fast_load/_build_fast_save), which inline
# the same semantics for speed.
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
    if expected_type is str and value == NULL_STRING:
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
