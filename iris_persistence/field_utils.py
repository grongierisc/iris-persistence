from __future__ import annotations

from typing import Any, Dict, List, get_args, get_origin

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
