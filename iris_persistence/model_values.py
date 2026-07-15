from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any, Dict, List, get_args, get_origin

from iris_persistence.field_utils import (
    is_application_iris_class,
    is_model_type,
    walk_declared_value,
)
from iris_persistence.types import ModelField


def _is_model_instance(value: Any) -> bool:
    from iris_persistence.models import Model

    return isinstance(value, Model)


RESERVED_FIELD_NAMES = frozenset({"pk", "_pk", "_iris_obj"})


def _is_object_reference_field(model_field: ModelField) -> bool:
    if model_field._is_model_field:
        return True
    if model_field._collection_kind is not None:
        return False
    if getattr(model_field.field_info, "collection", None) is not None:
        return False
    return is_application_iris_class(getattr(model_field.field_info, "iris_type", None))


def _value_matches_declared_type(declared_type: Any, value: Any) -> bool:
    origin = get_origin(declared_type)
    if declared_type is Any:
        return True
    if origin is None:
        return _matches_concrete_type(declared_type, value)
    if origin in (list, List):
        return _matches_list_type(declared_type, value)
    if origin in (dict, Dict):
        return _matches_dict_type(declared_type, value)
    union_args = [arg for arg in get_args(declared_type) if arg is not type(None)]
    return not union_args or any(_value_matches_declared_type(arg, value) for arg in union_args)


def _matches_concrete_type(declared_type: Any, value: Any) -> bool:
    if not isinstance(declared_type, type):
        return True
    if declared_type is float and isinstance(value, (int, float)) and not isinstance(value, bool):
        return True
    if declared_type is int and isinstance(value, bool):
        return False
    return isinstance(value, declared_type)


def _matches_list_type(declared_type: Any, value: Any) -> bool:
    if not isinstance(value, list):
        return False
    args = get_args(declared_type)
    return not args or all(_value_matches_declared_type(args[0], item) for item in value)


def _matches_dict_type(declared_type: Any, value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    args = get_args(declared_type)
    if len(args) != 2:
        return True
    key_type, value_type = args
    return all(
        _value_matches_declared_type(key_type, key)
        and _value_matches_declared_type(value_type, item)
        for key, item in value.items()
    )


def _validate_field_value(model_field: ModelField, value: Any) -> Any:
    if value is None:
        if model_field.nullable or model_field.default is None:
            return value
        raise ValueError(f"Field '{model_field.name}' does not allow null values")
    if (
        isinstance(value, str)
        and value == ""
        and model_field.nullable
        and _is_object_reference_field(model_field)
    ):
        return None

    max_length = model_field.field_info.max_length
    if max_length is not None and hasattr(value, "__len__") and len(value) > max_length:
        raise ValueError(
            f"Field '{model_field.name}' exceeds max_length={max_length}: {len(value)}"
        )

    if not _value_matches_declared_type(model_field.declared_type, value):
        raise TypeError(
            f"Field '{model_field.name}' expected "
            f"{getattr(model_field.declared_type, '__name__', repr(model_field.declared_type))}, "
            f"got {type(value).__name__}"
        )

    return value


def _model_value_to_dict(value: Any) -> Any:
    if _is_model_instance(value):
        return value.to_dict()
    if isinstance(value, list):
        return [_model_value_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: _model_value_to_dict(item) for key, item in value.items()}
    return value


def _convert_recursive_value(
    value: Any,
    declared_type: Any,
    mode: str,
) -> Any:
    def convert_leaf(leaf_value: Any, resolved_type: Any) -> Any:
        if (
            mode == "mapping_to_model"
            and is_model_type(resolved_type)
            and isinstance(leaf_value, dict)
        ):
            return resolved_type.from_dict(leaf_value)
        if (
            mode == "dataclass_to_model"
            and is_model_type(resolved_type)
            and is_dataclass(leaf_value)
            and not isinstance(leaf_value, type)
        ):
            return resolved_type.from_dataclass(leaf_value)
        if mode == "model_to_dataclass" and _is_model_instance(leaf_value):
            if isinstance(resolved_type, type) and is_dataclass(resolved_type):
                return leaf_value.to_dataclass(resolved_type)
            return leaf_value.to_dict()
        return leaf_value

    return walk_declared_value(value, declared_type, convert_leaf)
