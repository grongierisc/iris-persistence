from __future__ import annotations

from copy import deepcopy
from typing import Any, Type

import iris_persistence.models
from iris_persistence.runtime import get_runtime
from iris_persistence.schema_live import (
    _collect_live_schema_state,
)
from iris_persistence.schema_live import (
    _runtime_property_name as _runtime_property_name,
)
from iris_persistence.schema_state import (
    CLASS_METADATA_KEYS,
    INDEX_KEYS,
    PROPERTY_KEYS,
    STORAGE_DATA_KEYS,
    STORAGE_INDEX_KEYS,
    STORAGE_KEYS,
    STORAGE_PROPERTY_KEYS,
    STORAGE_SQL_MAP_DATA_KEYS,
    STORAGE_SQL_MAP_KEYS,
    STORAGE_SQL_MAP_ROW_ID_SPEC_KEYS,
    STORAGE_SQL_MAP_SUB_ACCESS_VAR_KEYS,
    STORAGE_SQL_MAP_SUB_INVALID_CONDITION_KEYS,
    STORAGE_SQL_MAP_SUB_KEYS,
    SchemaDiff,
    SchemaOperation,
    SchemaState,
    _append_state_line,
    _append_state_lines,
    _collect_model_schema_state,
    _format_value,
    _state_to_dict,
)


def _project_storage_state(
    live_storage: dict[str, Any] | None,
    desired_storage: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if desired_storage is None:
        return None
    if live_storage is None:
        return None

    def project(live: Any, desired: Any) -> Any:
        if not isinstance(desired, dict):
            return live
        live_mapping = live if isinstance(live, dict) else {}
        return {key: project(live_mapping.get(key), value) for key, value in desired.items()}

    projected = project(live_storage, desired_storage)
    # ``kind`` describes the Python declaration and has no IRIS dictionary field.
    projected["kind"] = desired_storage.get("kind")
    return projected


def _normalize_compiler_property_defaults(
    live_state: SchemaState,
    desired_state: SchemaState,
) -> SchemaState:
    """Ignore IRIS's generated empty-string expression for an undeclared default."""
    live_mapping = _state_to_dict(live_state)
    for name, desired_property in desired_state.properties.items():
        live_property = live_mapping["properties"].get(name)
        if (
            live_property is not None
            and "initial_expression" not in desired_property
            and live_property.get("initial_expression") == '""'
        ):
            live_property.pop("initial_expression")
    return SchemaState.from_dict(live_mapping)


def _merge_schema_state_for_sync(
    *,
    mode: str,
    live_state: SchemaState | dict[str, Any],
    desired_state: SchemaState | dict[str, Any],
) -> SchemaState:
    live_mapping = _state_to_dict(live_state)
    desired_mapping = _state_to_dict(desired_state)
    merge = iris_persistence.models.SYNC_POLICIES[mode].merge
    if merge == "live":
        return SchemaState.from_dict(live_mapping)
    if not live_mapping["super"]:
        return SchemaState.from_dict(desired_mapping)

    planned = deepcopy(live_mapping)
    planned["super"] = desired_mapping["super"]
    for key, value in desired_mapping["metadata"].items():
        if value not in (None, "", False):
            planned["metadata"][key] = value

    if merge == "managed":
        for section in ("parameters", "properties", "indexes"):
            planned[section] = deepcopy(desired_mapping[section])
        if desired_mapping["storage"] is not None:
            planned["storage"] = deepcopy(desired_mapping["storage"])
    return SchemaState.from_dict(planned)


def _render_schema_state(state: SchemaState | dict[str, Any]) -> tuple[str, ...]:
    state = _state_to_dict(state)
    lines = [f"class {state['classname']}"]
    if state["super"]:
        lines.append(f"super {state['super']}")
    for key in CLASS_METADATA_KEYS:
        value = state["metadata"].get(key)
        if value in (None, "", False):
            continue
        lines.append(f"class_metadata {key}={_format_value(value)}")
    for name in sorted(state["parameters"]):
        lines.append(f"parameter {name}={_format_value(state['parameters'][name])}")
    _append_state_lines(lines, "property", state["properties"], PROPERTY_KEYS)
    _append_state_lines(lines, "index", state["indexes"], INDEX_KEYS)
    if state["storage"] is not None:
        _append_rendered_storage(lines, state["storage"])
    return tuple(lines)


def _append_rendered_storage(lines: list[str], storage: dict[str, Any]) -> None:
    for key in STORAGE_KEYS:
        value = storage["attrs"].get(key)
        if value in (None, "", False):
            continue
        lines.append(f"storage {key}={_format_value(value)}")
    for name in sorted(storage.get("data", {})):
        item = storage["data"][name]
        _append_state_line(lines, "storage_data", name, STORAGE_DATA_KEYS, item)
        values = item.get("values") or {}
        for value_key in sorted(values, key=str):
            lines.append(
                f"storage_data_value {name}.{value_key}={_format_value(values[value_key])}"
            )
    _append_state_lines(lines, "storage_index", storage.get("indices", {}), STORAGE_INDEX_KEYS)
    _append_state_lines(
        lines,
        "storage_property",
        storage["properties"],
        STORAGE_PROPERTY_KEYS,
    )
    for name in sorted(storage.get("sql_maps", {})):
        item = storage["sql_maps"][name]
        _append_state_line(lines, "storage_sql_map", name, STORAGE_SQL_MAP_KEYS, item)
        _append_state_lines(
            lines,
            "storage_sql_map_data",
            item.get("data", {}),
            STORAGE_SQL_MAP_DATA_KEYS,
            name_prefix=f"{name}.",
        )
        _append_state_lines(
            lines,
            "storage_sql_map_row_id_spec",
            item.get("row_id_specs", {}),
            STORAGE_SQL_MAP_ROW_ID_SPEC_KEYS,
            name_prefix=f"{name}.",
        )
        for sub_name in sorted(item.get("subscripts", {})):
            subscript = item["subscripts"][sub_name]
            _append_state_line(
                lines,
                "storage_sql_map_subscript",
                f"{name}.{sub_name}",
                STORAGE_SQL_MAP_SUB_KEYS,
                subscript,
            )
            _append_state_lines(
                lines,
                "storage_sql_map_sub_access_var",
                subscript.get("access_vars", {}),
                STORAGE_SQL_MAP_SUB_ACCESS_VAR_KEYS,
                name_prefix=f"{name}.{sub_name}.",
            )
            _append_state_lines(
                lines,
                "storage_sql_map_sub_invalid_condition",
                subscript.get("invalid_conditions", {}),
                STORAGE_SQL_MAP_SUB_INVALID_CONDITION_KEYS,
                name_prefix=f"{name}.{sub_name}.",
            )


def _operation_safety(op_type: str, before: Any, after: Any, mode: str) -> str:
    if mode == "managed" and op_type in {
        "delete_parameter",
        "delete_property",
        "delete_index",
    }:
        return "managed-delete"
    if mode == "managed" and op_type in {
        "update_parameter",
        "update_property",
        "update_index",
    }:
        return "managed-update"
    if op_type in {"delete_parameter", "delete_property", "delete_index"}:
        return "destructive"
    if op_type == "add_storage":
        return "safe"
    if before in (None, {}, []) and after not in (None, {}, []):
        return "safe"
    if op_type in {"update_property", "update_index", "update_super"}:
        return "manual-review"
    if before not in (None, {}, []) and after not in (None, {}, []) and before != after:
        return "manual-review"
    return "safe"


def _operation_type(path: str, before: Any, after: Any) -> str:
    noun: str | None
    if path == "class":
        return "create_class" if before in (None, {}, []) else "update_class"
    if path == "super":
        return "update_super"
    if path.startswith("metadata."):
        return "update_class_metadata"
    if path == "storage" or path.startswith("storage."):
        noun, update = "storage", "update_storage"
    else:
        nouns = {
            "parameters": "parameter",
            "properties": "property",
            "indexes": "index",
        }
        noun = nouns.get(path.partition(".")[0])
        if noun is None:
            return "update_schema"
        update = f"update_{noun}"
    if before in (None, {}, []):
        return f"add_{noun}"
    if after in (None, {}, []):
        return f"delete_{noun}"
    return update


def _append_operation(
    operations: list[SchemaOperation],
    *,
    classname: str,
    path: str,
    before: Any,
    after: Any,
    mode: str,
) -> None:
    if before == after:
        return
    op_type = _operation_type(path, before, after)
    operations.append(
        SchemaOperation(
            classname=classname,
            op_type=op_type,
            path=path,
            before=deepcopy(before),
            after=deepcopy(after),
            safety=_operation_safety(op_type, before, after, mode),
        )
    )


def _diff_mapping_items(
    operations: list[SchemaOperation],
    *,
    classname: str,
    prefix: str,
    before: dict[str, Any],
    after: dict[str, Any],
    mode: str,
) -> None:
    for key in sorted(set(before) | set(after), key=str):
        _append_operation(
            operations,
            classname=classname,
            path=f"{prefix}.{key}",
            before=before.get(key),
            after=after.get(key),
            mode=mode,
        )


def diff_schema_operations(
    before_state: SchemaState | dict[str, Any],
    after_state: SchemaState | dict[str, Any],
    *,
    mode: str = iris_persistence.models.DEFAULT_SYNC_MODE,
) -> tuple[SchemaOperation, ...]:
    before = _state_to_dict(before_state)
    after = _state_to_dict(after_state)
    classname = str(after["classname"])
    operations: list[SchemaOperation] = []

    if not before.get("super") and after.get("super"):
        _append_operation(
            operations,
            classname=classname,
            path="class",
            before=None,
            after={"classname": after["classname"], "super": after["super"]},
            mode=mode,
        )
    elif before.get("classname") != after.get("classname"):
        _append_operation(
            operations,
            classname=classname,
            path="class",
            before=before.get("classname"),
            after=after.get("classname"),
            mode=mode,
        )

    _append_operation(
        operations,
        classname=classname,
        path="super",
        before=before.get("super"),
        after=after.get("super"),
        mode=mode,
    )
    for prefix in ("metadata", "parameters", "properties", "indexes"):
        _diff_mapping_items(
            operations,
            classname=classname,
            prefix=prefix,
            before=before.get(prefix, {}),
            after=after.get(prefix, {}),
            mode=mode,
        )
    if before.get("storage") != after.get("storage"):
        if before.get("super"):
            operations.append(
                SchemaOperation(
                    classname=classname,
                    op_type="blocked_storage_change",
                    path="storage",
                    before=deepcopy(before.get("storage")),
                    after=deepcopy(after.get("storage")),
                    safety="blocked",
                )
            )
        else:
            _append_operation(
                operations,
                classname=classname,
                path="storage",
                before=before.get("storage"),
                after=after.get("storage"),
                mode=mode,
            )
    if operations:
        operations.append(
            SchemaOperation(
                classname=classname,
                op_type="compile_class",
                path="compile",
                safety="safe",
            )
        )
    return tuple(operations)


def diff_schema(model_cls: Type[Any], *, runtime: Any | None = None) -> SchemaDiff:
    runtime = runtime or get_runtime()
    classname = getattr(model_cls, "_classname", model_cls.__name__)
    mode = getattr(model_cls, "_sync_mode", iris_persistence.models.DEFAULT_SYNC_MODE)
    desired_state = _collect_model_schema_state(model_cls)
    live_state = _collect_live_schema_state(
        runtime,
        classname,
        include_storage=desired_state.storage is not None,
    )
    live_state = _normalize_compiler_property_defaults(live_state, desired_state)
    if desired_state.storage is not None:
        live_mapping = _state_to_dict(live_state)
        live_mapping["storage"] = _project_storage_state(
            live_mapping.get("storage"),
            desired_state.storage,
        )
        live_state = SchemaState.from_dict(live_mapping)
    planned_state = _merge_schema_state_for_sync(
        mode=mode,
        live_state=live_state,
        desired_state=desired_state,
    )
    return SchemaDiff(
        classname=planned_state["classname"],
        before=_render_schema_state(live_state),
        after=_render_schema_state(planned_state),
        before_state=live_state,
        after_state=planned_state,
        operations=diff_schema_operations(live_state, planned_state, mode=mode),
    )


def _set_runtime_property_if_not_none(
    runtime: Any,
    obj: Any,
    prop_name: str,
    value: Any,
) -> None:
    if value is not None:
        runtime.set_property(obj, prop_name, value)
