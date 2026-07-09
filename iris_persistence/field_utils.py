from __future__ import annotations

import datetime
import decimal
from typing import Any, Callable, Dict, List, get_args, get_origin

from iris_persistence.codecs import resolve_declared_type

IRIS_LIST_TYPES = frozenset(
    {
        "%List",
        "%ListOfDataTypes",
        "%ListOfObjects",
        "%Library.List",
        "%Library.ListOfDataTypes",
        "%Library.ListOfObjects",
    }
)
IRIS_ARRAY_TYPES = frozenset(
    {
        "%ArrayOfDataTypes",
        "%ArrayOfObjects",
        "%Library.ArrayOfDataTypes",
        "%Library.ArrayOfObjects",
    }
)
IRIS_COLLECTION_TYPES = IRIS_LIST_TYPES | IRIS_ARRAY_TYPES
PERCENT_LIST_TYPES = frozenset({"%List", "%Library.List"})
SCALAR_STRING_TYPES = frozenset(
    {
        "%String",
        "%RawString",
        "%Library.String",
        "%Library.RawString",
    }
)


def is_application_iris_class(iris_type: Any) -> bool:
    return isinstance(iris_type, str) and iris_type != "" and not iris_type.startswith("%")


def is_iris_collection_type(iris_type: Any) -> bool:
    return iris_type in IRIS_COLLECTION_TYPES


def is_model_type(value: Any) -> bool:
    from iris_persistence.models import Model

    return isinstance(value, type) and issubclass(value, Model)


def is_serial_model_type(model_cls: type[Any]) -> bool:
    superclasses = getattr(model_cls, "_superclasses", "") or ""
    return "SerialObject" in superclasses


def collection_value_type(declared_type: Any) -> tuple[str | None, Any]:
    origin = get_origin(declared_type)
    if origin in (list, List):
        args = get_args(declared_type)
        element_type = resolve_declared_type(args[0]) if args else Any
        return ("list", element_type)
    if origin in (dict, Dict):
        args = get_args(declared_type)
        element_type = resolve_declared_type(args[1]) if len(args) == 2 else Any
        return ("array", element_type)
    return (None, None)


def walk_declared_value(
    value: Any,
    declared_type: Any,
    leaf: Callable[[Any, Any], Any],
    *,
    stringify_keys: bool = False,
) -> Any:
    if value is None:
        return None

    resolved_type = resolve_declared_type(declared_type)
    collection_kind, element_type = collection_value_type(resolved_type)
    if collection_kind == "list" and isinstance(value, list):
        return [
            walk_declared_value(item, element_type, leaf, stringify_keys=stringify_keys)
            for item in value
        ]
    if collection_kind == "array" and isinstance(value, dict):
        return {
            str(key) if stringify_keys else key: walk_declared_value(
                item,
                element_type,
                leaf,
                stringify_keys=stringify_keys,
            )
            for key, item in value.items()
        }
    return leaf(value, resolved_type)


def is_percent_list_field(field_meta: Any | None) -> bool:
    return getattr(field_meta, "iris_type", None) in PERCENT_LIST_TYPES


def is_scalar_string_field(field_meta: Any | None) -> bool:
    if field_meta is None or getattr(field_meta, "collection", None):
        return False
    return getattr(field_meta, "iris_type", None) in SCALAR_STRING_TYPES


def collection_kind_from_iris_type(iris_type: Any) -> str | None:
    if iris_type in IRIS_LIST_TYPES:
        return "list"
    if iris_type in IRIS_ARRAY_TYPES:
        return "array"
    return None


def collection_kind_from_field(field_meta: Any | None) -> str | None:
    collection = getattr(field_meta, "collection", None)
    if collection in {"list", "array"}:
        return collection
    return collection_kind_from_iris_type(getattr(field_meta, "iris_type", None))


def coerce_bool(value: Any) -> bool:
    return value == 1 or value == "1" or str(value).lower() == "true"


# Single source of truth for scalar type mapping between Python and IRIS.
# Rows: (
#   python type,
#   python type name for codegen,
#   IRIS type,
#   reverse-only IRIS aliases,
#   scalar categories,
# ).
# A `None` python name marks forward-only rows (scaffolded code never emits that name).
_TYPE_MAP: tuple[tuple[Any, str | None, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        str,
        "str",
        "%Library.String",
        ("%Stream.GlobalCharacter", "%Stream.FileCharacter"),
        ("direct_property", "python_scalar"),
    ),
    (int, "int", "%Library.Integer", (), ("direct_property", "python_scalar")),
    (
        float,
        "float",
        "%Library.Double",
        ("%Library.Float", "%Library.Decimal"),
        ("direct_property", "python_scalar"),
    ),
    (bool, "bool", "%Library.Boolean", (), ("direct_property", "python_scalar")),
    (bytes, "bytes", "%Stream.GlobalBinary", ("%Stream.FileBinary",), ("python_scalar",)),
    (bytearray, None, "%Stream.GlobalBinary", (), ("python_scalar",)),
    (decimal.Decimal, None, "%Library.Decimal", (), ()),
    (dict, "dict", "%Library.DynamicObject", (), ()),
    (list, "list", "%Library.DynamicArray", (), ()),
    (datetime.datetime, "datetime.datetime", "%Library.TimeStamp", (), ()),
    (datetime.date, "datetime.date", "%Library.Date", (), ()),
    (datetime.time, "datetime.time", "%Library.Time", (), ()),
)

PYTHON_TO_IRIS_TYPE: dict[Any, str] = {
    py: iris for py, _name, iris, _aliases, _categories in _TYPE_MAP
}
DIRECT_PROPERTY_TYPES: frozenset[type] = frozenset(
    py for py, _name, _iris, _aliases, categories in _TYPE_MAP if "direct_property" in categories
)
PYTHON_SCALAR_TYPES: frozenset[type] = frozenset(
    py for py, _name, _iris, _aliases, categories in _TYPE_MAP if "python_scalar" in categories
)


def _build_reverse_type_map() -> dict[str, str]:
    reverse: dict[str, str] = {}
    for _py, name, iris_type, aliases, _categories in _TYPE_MAP:
        if name is None:
            continue
        for iris_name in (iris_type, *aliases):
            reverse.setdefault(iris_name, name)
    return reverse


IRIS_TYPE_TO_PYTHON_NAME: dict[str, str] = _build_reverse_type_map()


def python_annotation_for_iris_type(iris_type: str) -> str:
    """Return the Python annotation name scaffolded for an IRIS property type."""
    if not iris_type or is_iris_collection_type(iris_type):
        return "Any"
    mapped = IRIS_TYPE_TO_PYTHON_NAME.get(iris_type)
    if mapped is not None:
        return mapped
    if iris_type.startswith("%"):
        return "str"
    return "Any"
