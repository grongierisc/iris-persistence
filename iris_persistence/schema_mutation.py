from __future__ import annotations

from typing import Any

from iris_persistence.schema_inspection import _set_runtime_property_if_not_none


def _set_runtime_property_exact(
    runtime: Any,
    obj: Any,
    prop_name: str,
    value: Any,
) -> None:
    try:
        runtime.set_property(obj, prop_name, "" if value is None else value)
    except Exception as exc:
        if not _missing_dictionary_property(exc):
            raise


def _set_runtime_flag_exact(
    runtime: Any,
    obj: Any,
    prop_name: str,
    enabled: Any,
) -> None:
    try:
        runtime.set_property(obj, prop_name, 1 if enabled else 0)
    except Exception as exc:
        if not _missing_dictionary_property(exc):
            raise


def _missing_dictionary_property(exc: Exception) -> bool:
    return isinstance(exc, AttributeError) or "PROPERTY DOES NOT EXIST" in str(exc)


def _remove_runtime_parameter(runtime: Any, params: Any, key: str) -> None:
    for method_name in ("RemoveAt", "DeleteAt", "Remove"):
        try:
            runtime.invoke_method(params, method_name, key)
            return
        except Exception:
            continue
    try:
        runtime.invoke_method(params, "SetAt", "", key)
    except Exception:
        pass


def _set_runtime_flag_if_true(runtime: Any, obj: Any, prop_name: str, enabled: Any) -> None:
    if enabled:
        runtime.set_property(obj, prop_name, 1)


def _apply_runtime_state_fields(
    runtime: Any,
    obj: Any,
    state: dict[str, Any],
    *,
    flag_fields: tuple[tuple[str, str], ...] = (),
    value_fields: tuple[tuple[str, str], ...] = (),
    exact: bool,
    exact_values: bool | None = None,
) -> None:
    if exact_values is None:
        exact_values = exact

    for state_key, property_name in flag_fields:
        if exact:
            _set_runtime_flag_exact(runtime, obj, property_name, state.get(state_key))
        else:
            _set_runtime_flag_if_true(runtime, obj, property_name, state.get(state_key))

    for state_key, property_name in value_fields:
        if exact_values:
            _set_runtime_property_exact(runtime, obj, property_name, state.get(state_key))
        else:
            _set_runtime_property_if_not_none(runtime, obj, property_name, state.get(state_key))


def _mapping_or_attr_value(source: Any, name: str) -> Any:
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)
