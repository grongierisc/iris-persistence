from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Type

import iris_persistence.models
from iris_persistence.catalog import (
    dictionary_rows as _dictionary_rows,
)
from iris_persistence.catalog import (
    safe_get_property as _safe_get_property,
)
from iris_persistence.field_utils import coerce_bool
from iris_persistence.runtime import get_runtime
from iris_persistence.schema_state import (
    _PROPERTY_FLAG_FIELDS,
    _PROPERTY_VALUE_FIELDS,
    _STORAGE_SQL_MAP_RUNTIME_CHILDREN,
    CLASS_METADATA_FLAG_KEYS,
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
    _compact_mapping,
    _compact_property_state,
    _empty_schema_state,
    _empty_storage_state,
    _find_existing_classname,
    _format_value,
    _index_state_from_getter,
    _is_system_member_name,
    _item_belongs_to_class,
    _iter_runtime_list,
    _normalize_values_mapping,
    _row_value,
    _schema_classname_for_save,
    _sort_mapping,
    _state_to_dict,
)
from iris_persistence.types import (
    UNSET,
)


def _collect_live_parameters_from_sql(runtime: Any, classname: str) -> dict[str, Any]:
    rows = _dictionary_rows(
        runtime,
        "SELECT Name, Default FROM %Dictionary.ParameterDefinition WHERE parent = ?",
        (classname,),
    )
    parameters = {}
    for row in rows:
        name = _row_value(row, "Name")
        if not name or _is_system_member_name(str(name)):
            continue
        parameters[str(name)] = str(_row_value(row, "Default"))
    return parameters


def _property_state_from_getter(
    get_value: Any,
    *,
    max_length: Any = UNSET,
    scale: Any = UNSET,
) -> dict[str, Any]:
    if max_length is UNSET:
        max_length = get_value("MAXLEN")
    if scale is UNSET:
        scale = get_value("SCALE")
    state = {
        "type": get_value("Type"),
        "storable": False if get_value("Storable") in (0, "0", False) else None,
        "max_length": str(max_length) if max_length not in (None, "") else None,
        "scale": str(scale) if scale not in (None, "") else None,
    }
    state.update(
        {key: coerce_bool(get_value(prop_name)) for key, prop_name in _PROPERTY_FLAG_FIELDS}
    )
    state.update({key: get_value(prop_name) for key, prop_name in _PROPERTY_VALUE_FIELDS})
    return _compact_property_state(state)


def _collect_live_properties_from_sql(runtime: Any, classname: str) -> dict[str, dict[str, Any]]:
    rows = _dictionary_rows(
        runtime,
        "SELECT * FROM %Dictionary.PropertyDefinition WHERE parent = ?",
        (classname,),
    )
    properties = {}
    for row in rows:
        name = _row_value(row, "Name")
        if not name or str(name).startswith("%"):
            continue
        properties[str(name)] = _property_state_from_getter(
            lambda property_name, row=row: _row_value(row, property_name)
        )
    return properties


def _collect_live_indexes_from_sql(runtime: Any, classname: str) -> dict[str, dict[str, Any]]:
    rows = _dictionary_rows(
        runtime,
        "SELECT * FROM %Dictionary.IndexDefinition WHERE parent = ?",
        (classname,),
    )
    indexes = {}
    for row in rows:
        name = _row_value(row, "Name")
        if not name:
            continue
        indexes[str(name)] = _index_state_from_getter(
            lambda property_name, row=row: _row_value(row, property_name)
        )
    return indexes


def _runtime_property_name(state_key: str) -> str:
    if state_key == "global_name":
        return "Global"
    return "".join(part.capitalize() for part in state_key.split("_"))


def _runtime_state_from_item(
    runtime: Any,
    item: Any,
    keys: tuple[str, ...],
    *,
    bool_keys: set[str] | None = None,
) -> dict[str, Any]:
    bool_keys = bool_keys or set()
    return _compact_mapping(
        {
            key: (
                coerce_bool(_safe_get_property(runtime, item, _runtime_property_name(key)))
                if key in bool_keys
                else _safe_get_property(runtime, item, _runtime_property_name(key))
            )
            for key in keys
        }
    )


def _collect_runtime_state_mapping(
    runtime: Any,
    parent: Any,
    list_property: str,
    keys: tuple[str, ...],
    *,
    bool_keys: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    items = {}
    for item in _iter_runtime_list(runtime, _safe_get_property(runtime, parent, list_property)):
        name = _safe_get_property(runtime, item, "Name")
        if name:
            items[str(name)] = _runtime_state_from_item(
                runtime,
                item,
                keys,
                bool_keys=bool_keys,
            )
    return _sort_mapping(items)


def _collect_runtime_children(
    runtime: Any,
    parent: Any,
    specs: tuple[Any, ...],
) -> dict[str, dict[str, Any]]:
    result = {}
    for state_key, list_property, keys, bool_keys, children in specs:
        items = {}
        for item in _iter_runtime_list(runtime, _safe_get_property(runtime, parent, list_property)):
            name = _safe_get_property(runtime, item, "Name")
            if not name:
                continue
            state = _runtime_state_from_item(runtime, item, keys, bool_keys=bool_keys)
            state.update(_collect_runtime_children(runtime, item, children))
            items[str(name)] = state
        result[state_key] = _sort_mapping(items)
    return result


def _collect_live_members(
    runtime: Any,
    class_def: Any,
    classname: str,
    *,
    list_property: str,
    item_state: Callable[[Any], Any],
    sql_fallback: dict[str, Any],
    skip: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Collect owned schema members from the runtime object walk plus a SQL fallback."""
    members: dict[str, Any] = {}
    for item in _iter_runtime_list(runtime, _safe_get_property(runtime, class_def, list_property)):
        name = _safe_get_property(runtime, item, "Name")
        if not name:
            continue
        name = str(name)
        if skip is not None and skip(name):
            continue
        if not _item_belongs_to_class(runtime, item, classname):
            continue
        members[name] = item_state(item)
    for name, member_state in sql_fallback.items():
        members.setdefault(name, member_state)
    return members


def _collect_live_schema_state(
    runtime: Any,
    classname: str,
    *,
    include_storage: bool = False,
) -> SchemaState:
    state = _empty_schema_state(_schema_classname_for_save(classname))
    existing_classname = _find_existing_classname(runtime, classname)
    if existing_classname is None:
        return SchemaState.from_dict(state)

    state["classname"] = existing_classname
    class_def = runtime.get_object("%Dictionary.ClassDefinition", existing_classname)
    state["super"] = _safe_get_property(runtime, class_def, "Super")
    state["metadata"] = _runtime_state_from_item(
        runtime,
        class_def,
        CLASS_METADATA_KEYS,
        bool_keys=CLASS_METADATA_FLAG_KEYS,
    )

    state["parameters"] = _collect_live_members(
        runtime,
        class_def,
        existing_classname,
        list_property="Parameters",
        skip=_is_system_member_name,
        item_state=lambda item: str(_safe_get_property(runtime, item, "Default")),
        sql_fallback=_collect_live_parameters_from_sql(runtime, existing_classname),
    )

    def _live_property_state(item: Any) -> dict[str, Any]:
        max_length = None
        scale = None
        params = _safe_get_property(runtime, item, "Parameters")
        if params is not None:
            try:
                max_length = runtime.invoke_method(params, "GetAt", "MAXLEN")
            except Exception:
                max_length = None
            try:
                scale = runtime.invoke_method(params, "GetAt", "SCALE")
            except Exception:
                scale = None
        return _property_state_from_getter(
            lambda property_name: _safe_get_property(runtime, item, property_name),
            max_length=max_length,
            scale=scale,
        )

    state["properties"] = _collect_live_members(
        runtime,
        class_def,
        existing_classname,
        list_property="Properties",
        skip=lambda name: name.startswith("%"),
        item_state=_live_property_state,
        sql_fallback=_collect_live_properties_from_sql(runtime, existing_classname),
    )

    state["indexes"] = _collect_live_members(
        runtime,
        class_def,
        existing_classname,
        list_property="Indices",
        item_state=lambda item: _index_state_from_getter(
            lambda property_name: _safe_get_property(runtime, item, property_name)
        ),
        sql_fallback=_collect_live_indexes_from_sql(runtime, existing_classname),
    )

    if not include_storage:
        return SchemaState.from_dict(state)

    storage_strategy = _safe_get_property(runtime, class_def, "StorageStrategy") or "Default"
    storages = _iter_runtime_list(runtime, _safe_get_property(runtime, class_def, "Storages"))
    selected_storage = None
    for item in storages:
        name = _safe_get_property(runtime, item, "Name")
        if storage_strategy and name == storage_strategy:
            selected_storage = item
            break
    if selected_storage is None and storages:
        selected_storage = storages[0]

    if selected_storage is not None:
        storage_state = _empty_storage_state()
        storage_state["name"] = _safe_get_property(runtime, selected_storage, "Name")
        storage_state["attrs"] = _runtime_state_from_item(
            runtime,
            selected_storage,
            STORAGE_KEYS,
        )
        for item in _iter_runtime_list(
            runtime,
            _safe_get_property(runtime, selected_storage, "Data"),
        ):
            name = _safe_get_property(runtime, item, "Name")
            if not name:
                continue
            values = {}
            for value_item in _iter_runtime_list(
                runtime,
                _safe_get_property(runtime, item, "Values"),
            ):
                value_name = _safe_get_property(runtime, value_item, "Name")
                if value_name in (None, ""):
                    continue
                values[str(value_name)] = str(_safe_get_property(runtime, value_item, "Value"))
            data_state = _runtime_state_from_item(runtime, item, STORAGE_DATA_KEYS)
            data_state["values"] = _normalize_values_mapping(values)
            storage_state["data"][str(name)] = _compact_mapping(data_state)
        storage_state["data"] = _sort_mapping(storage_state["data"])

        storage_state["indices"] = _collect_runtime_state_mapping(
            runtime,
            selected_storage,
            "Indices",
            STORAGE_INDEX_KEYS,
        )
        storage_state["properties"] = _collect_runtime_state_mapping(
            runtime,
            selected_storage,
            "Properties",
            STORAGE_PROPERTY_KEYS,
            bool_keys={"bias_queries_as_outlier"},
        )

        for item in _iter_runtime_list(
            runtime,
            _safe_get_property(runtime, selected_storage, "SQLMaps"),
        ):
            name = _safe_get_property(runtime, item, "Name")
            if not name:
                continue
            map_state = _runtime_state_from_item(
                runtime,
                item,
                STORAGE_SQL_MAP_KEYS,
                bool_keys={"conditional_with_host_vars"},
            )
            map_state.update(
                _collect_runtime_children(runtime, item, _STORAGE_SQL_MAP_RUNTIME_CHILDREN)
            )
            storage_state["sql_maps"][str(name)] = map_state
        storage_state["sql_maps"] = _sort_mapping(storage_state["sql_maps"])
        state["storage"] = storage_state

    return SchemaState.from_dict(state)


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
    storage = state["storage"]
    if storage is not None:
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
    return tuple(lines)


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
