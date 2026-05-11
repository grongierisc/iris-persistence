from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from difflib import unified_diff
from typing import Any, Type, get_args, get_origin

import iris_persistence.models
from iris_persistence.runtime import get_runtime
from iris_persistence.types import UNSET, FieldInfo

CLASS_METADATA_KEYS = (
    "description",
    "deprecated",
    "final",
    "sql_table_name",
    "procedure_block",
)
PROPERTY_KEYS = (
    "type",
    "required",
    "readonly",
    "collection",
    "sql_field_name",
    "identity",
    "relationship",
    "on_delete",
    "inverse",
    "transient",
    "storable",
    "multi_dimensional",
    "sql_list_delimiter",
    "sql_list_type",
    "sql_compute_code",
    "sql_compute_on_change",
    "sql_computed",
    "initial_expression",
    "max_length",
)
INDEX_KEYS = ("properties", "unique", "type", "primary_key")
STORAGE_KEYS = (
    "type",
    "data_location",
    "default_data",
    "extent_location",
    "extent_size",
    "counter_location",
    "version_location",
    "id_location",
    "id_expression",
    "id_function",
    "index_location",
    "state",
    "stream_location",
    "sql_child_sub",
    "sql_id_expression",
    "sql_row_id_name",
    "sql_row_id_property",
    "sql_table_number",
    "sequence_number",
)
STORAGE_PROPERTY_KEYS = (
    "average_field_size",
    "selectivity",
    "outlier_selectivity",
    "histogram",
    "child_block_count",
    "child_extent_size",
    "bias_queries_as_outlier",
    "stream_location",
)


@dataclass(frozen=True)
class SchemaDiff:
    classname: str
    before: tuple[str, ...]
    after: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return self.before != self.after

    def to_unified_diff(self) -> str:
        if not self.has_changes:
            return ""
        return "\n".join(
            unified_diff(
                self.before,
                self.after,
                fromfile=f"{self.classname}:live",
                tofile=f"{self.classname}:planned",
                lineterm="",
            )
        )

    def __str__(self) -> str:
        return self.to_unified_diff() or "No schema changes."


def _coerce_bool(value: Any) -> bool:
    return value == 1 or value == "1" or value is True or str(value).lower() == "true"


def _safe_get_property(runtime: Any, obj: Any, prop_name: str) -> Any:
    try:
        return runtime.get_property(obj, prop_name)
    except Exception:
        return None


def _iter_runtime_list(runtime: Any, list_obj: Any) -> list[Any]:
    if list_obj is None:
        return []
    try:
        count = runtime.invoke_method(list_obj, "Count")
    except Exception:
        return []
    items = []
    for index in range(1, count + 1):
        try:
            items.append(runtime.invoke_method(list_obj, "GetAt", index))
        except Exception:
            continue
    return items


def _item_belongs_to_class(runtime: Any, item: Any, classname: str) -> bool:
    inherited = _safe_get_property(runtime, item, "Inherited")
    if inherited is not None:
        return not _coerce_bool(inherited)

    for attr_name in ("Origin", "Parent", "parent", "Class"):
        owner = _safe_get_property(runtime, item, attr_name)
        if owner in (None, ""):
            continue
        return str(owner) == classname
    return True


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    return repr(value)


def _compact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    compact = {}
    for key, value in mapping.items():
        if value in (None, "", False):
            continue
        compact[key] = value
    return compact


def _render_attribute_parts(keys: tuple[str, ...], mapping: dict[str, Any]) -> str:
    parts = []
    for key in keys:
        value = mapping.get(key)
        if value in (None, "", False):
            continue
        parts.append(f"{key}={_format_value(value)}")
    return " ".join(parts)


def _empty_schema_state(classname: str) -> dict[str, Any]:
    return {
        "classname": classname,
        "super": None,
        "metadata": {},
        "parameters": {},
        "properties": {},
        "indexes": {},
        "storage": None,
    }


def _field_initial_expression(field_meta: FieldInfo) -> str | None:
    if getattr(field_meta, "initial_expression", None) is not None:
        return field_meta.initial_expression
    default = getattr(field_meta, "default", UNSET)
    if default is UNSET or default is None:
        return None
    if isinstance(default, str):
        return f'"{default}"'
    if isinstance(default, bool):
        return "1" if default else "0"
    return str(default)


def _collect_model_schema_state(model_cls: Type[Any]) -> dict[str, Any]:
    classname = getattr(model_cls, "_classname", model_cls.__name__)
    state = _empty_schema_state(classname)
    state["super"] = getattr(model_cls, "_superclasses", "%Persistent")

    class_metadata = getattr(model_cls, "_class_metadata", None)
    if class_metadata is not None:
        state["metadata"] = _compact_mapping(
            {
                "description": getattr(class_metadata, "description", None),
                "deprecated": getattr(class_metadata, "deprecated", False),
                "final": getattr(class_metadata, "final", False),
                "sql_table_name": getattr(class_metadata, "sql_table_name", None),
                "procedure_block": getattr(class_metadata, "procedure_block", False),
            }
        )

    parameters = getattr(model_cls, "_parameters", {}) or {}
    state["parameters"] = {str(name): str(value) for name, value in parameters.items()}

    properties = {}
    for field_name, model_field in getattr(model_cls, "__model_fields__", {}).items():
        field_meta = model_field.field_info
        property_state = _compact_mapping(
            {
                "type": _map_python_type_to_iris(
                    _resolve_model_type(model_field.declared_type),
                    field_meta,
                ),
                "required": getattr(field_meta, "required", False),
                "readonly": getattr(field_meta, "readonly", False),
                "collection": getattr(field_meta, "collection", None),
                "sql_field_name": getattr(field_meta, "sql_field_name", None),
                "identity": getattr(field_meta, "identity", False),
                "relationship": getattr(field_meta, "relationship", None),
                "on_delete": getattr(field_meta, "on_delete", None),
                "inverse": getattr(field_meta, "inverse", None),
                "transient": getattr(field_meta, "transient", False),
                "storable": (
                    False if getattr(field_meta, "storable", True) is False else None
                ),
                "multi_dimensional": getattr(field_meta, "multi_dimensional", False),
                "sql_list_delimiter": getattr(field_meta, "sql_list_delimiter", None),
                "sql_list_type": getattr(field_meta, "sql_list_type", None),
                "sql_compute_code": getattr(field_meta, "sql_compute_code", None),
                "sql_compute_on_change": getattr(field_meta, "sql_compute_on_change", None),
                "sql_computed": getattr(field_meta, "sql_computed", False),
                "initial_expression": _field_initial_expression(field_meta),
                "max_length": getattr(field_meta, "max_length", None),
            }
        )
        properties[field_name] = property_state
    state["properties"] = properties

    indexes = {}
    for index_meta in getattr(model_cls, "_indexes", []) or []:
        indexes[index_meta.name] = _compact_mapping(
            {
                "properties": index_meta.properties,
                "unique": getattr(index_meta, "unique", False),
                "type": getattr(index_meta, "type", None),
                "primary_key": getattr(index_meta, "primary_key", False),
            }
        )
    state["indexes"] = indexes

    storage_meta = getattr(model_cls, "_storage", None)
    if storage_meta is not None:
        state["storage"] = {
            "attrs": _compact_mapping(
                {key: getattr(storage_meta, key, None) for key in STORAGE_KEYS}
            ),
            "properties": {
                item.name: _compact_mapping(
                    {key: getattr(item, key, None) for key in STORAGE_PROPERTY_KEYS}
                )
                for item in getattr(storage_meta, "properties", ()) or ()
            },
        }

    return state


def _collect_live_schema_state(runtime: Any, classname: str) -> dict[str, Any]:
    exists = runtime.call_classmethod("%Dictionary.ClassDefinition", "_ExistsId", classname)
    state = _empty_schema_state(classname)
    if not exists:
        return state

    class_def = runtime.get_object("%Dictionary.ClassDefinition", classname)
    state["super"] = _safe_get_property(runtime, class_def, "Super")
    state["metadata"] = _compact_mapping(
        {
            "description": _safe_get_property(runtime, class_def, "Description"),
            "deprecated": _coerce_bool(_safe_get_property(runtime, class_def, "Deprecated")),
            "final": _coerce_bool(_safe_get_property(runtime, class_def, "Final")),
            "sql_table_name": _safe_get_property(runtime, class_def, "SqlTableName"),
            "procedure_block": _coerce_bool(
                _safe_get_property(runtime, class_def, "ProcedureBlock")
            ),
        }
    )

    parameters = {}
    for item in _iter_runtime_list(runtime, _safe_get_property(runtime, class_def, "Parameters")):
        name = _safe_get_property(runtime, item, "Name")
        if not name or str(name).startswith("%") or str(name) == "GUID":
            continue
        if not _item_belongs_to_class(runtime, item, classname):
            continue
        parameters[str(name)] = str(_safe_get_property(runtime, item, "Default"))
    state["parameters"] = parameters

    properties = {}
    for item in _iter_runtime_list(runtime, _safe_get_property(runtime, class_def, "Properties")):
        name = _safe_get_property(runtime, item, "Name")
        if not name or str(name).startswith("%"):
            continue
        max_length = None
        params = _safe_get_property(runtime, item, "Parameters")
        if params is not None:
            try:
                max_length = runtime.invoke_method(params, "GetAt", "MAXLEN")
            except Exception:
                max_length = None
        properties[str(name)] = _compact_mapping(
            {
                "type": _safe_get_property(runtime, item, "Type"),
                "required": _coerce_bool(_safe_get_property(runtime, item, "Required")),
                "readonly": _coerce_bool(_safe_get_property(runtime, item, "ReadOnly")),
                "collection": _safe_get_property(runtime, item, "Collection"),
                "sql_field_name": _safe_get_property(runtime, item, "SqlFieldName"),
                "identity": _coerce_bool(_safe_get_property(runtime, item, "Identity")),
                "relationship": _safe_get_property(runtime, item, "Relationship"),
                "on_delete": _safe_get_property(runtime, item, "OnDelete"),
                "inverse": _safe_get_property(runtime, item, "Inverse"),
                "transient": _coerce_bool(_safe_get_property(runtime, item, "Transient")),
                "storable": (
                    False
                    if _safe_get_property(runtime, item, "Storable") in (0, "0", False)
                    else None
                ),
                "multi_dimensional": _coerce_bool(
                    _safe_get_property(runtime, item, "MultiDimensional")
                ),
                "sql_list_delimiter": _safe_get_property(runtime, item, "SqlListDelimiter"),
                "sql_list_type": _safe_get_property(runtime, item, "SqlListType"),
                "sql_compute_code": _safe_get_property(runtime, item, "SqlComputeCode"),
                "sql_compute_on_change": _safe_get_property(
                    runtime, item, "SqlComputeOnChange"
                ),
                "sql_computed": _coerce_bool(_safe_get_property(runtime, item, "SqlComputed")),
                "initial_expression": _safe_get_property(runtime, item, "InitialExpression"),
                "max_length": str(max_length) if max_length not in (None, "") else None,
            }
        )
    state["properties"] = properties

    indexes = {}
    for item in _iter_runtime_list(runtime, _safe_get_property(runtime, class_def, "Indices")):
        name = _safe_get_property(runtime, item, "Name")
        if not name:
            continue
        indexes[str(name)] = _compact_mapping(
            {
                "properties": _safe_get_property(runtime, item, "Properties"),
                "unique": _coerce_bool(_safe_get_property(runtime, item, "Unique")),
                "type": _safe_get_property(runtime, item, "Type"),
                "primary_key": _coerce_bool(_safe_get_property(runtime, item, "PrimaryKey")),
            }
        )
    state["indexes"] = indexes

    storage_strategy = _safe_get_property(runtime, class_def, "StorageStrategy")
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
        state["storage"] = {
            "attrs": _compact_mapping(
                {
                    key: _safe_get_property(
                        runtime,
                        selected_storage,
                        "".join(part.capitalize() for part in key.split("_")),
                    )
                    for key in STORAGE_KEYS
                }
            ),
            "properties": {},
        }
        storage_properties = _safe_get_property(runtime, selected_storage, "Properties")
        for item in _iter_runtime_list(runtime, storage_properties):
            name = _safe_get_property(runtime, item, "Name")
            if not name:
                continue
            state["storage"]["properties"][str(name)] = _compact_mapping(
                {
                    "average_field_size": _safe_get_property(runtime, item, "AverageFieldSize"),
                    "selectivity": _safe_get_property(runtime, item, "Selectivity"),
                    "outlier_selectivity": _safe_get_property(
                        runtime, item, "OutlierSelectivity"
                    ),
                    "histogram": _safe_get_property(runtime, item, "Histogram"),
                    "child_block_count": _safe_get_property(runtime, item, "ChildBlockCount"),
                    "child_extent_size": _safe_get_property(runtime, item, "ChildExtentSize"),
                    "bias_queries_as_outlier": _coerce_bool(
                        _safe_get_property(runtime, item, "BiasQueriesAsOutlier")
                    ),
                    "stream_location": _safe_get_property(runtime, item, "StreamLocation"),
                }
            )

    return state


def _merge_schema_state_for_sync(
    *,
    mode: str,
    live_state: dict[str, Any],
    desired_state: dict[str, Any],
) -> dict[str, Any]:
    if mode == "observe":
        return live_state
    if not live_state["super"] or mode == "replace":
        return desired_state

    planned = deepcopy(live_state)
    planned["super"] = desired_state["super"]
    for key, value in desired_state["metadata"].items():
        if value not in (None, "", False):
            planned["metadata"][key] = value
    for key, value in desired_state["parameters"].items():
        planned["parameters"].setdefault(key, value)
    for key, value in desired_state["properties"].items():
        planned["properties"].setdefault(key, value)
    for key, value in desired_state["indexes"].items():
        planned["indexes"].setdefault(key, value)
    return planned


def _render_schema_state(state: dict[str, Any]) -> tuple[str, ...]:
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
    for name in sorted(state["properties"]):
        parts = _render_attribute_parts(PROPERTY_KEYS, state["properties"][name])
        lines.append(f"property {name}" + (f" {parts}" if parts else ""))
    for name in sorted(state["indexes"]):
        parts = _render_attribute_parts(INDEX_KEYS, state["indexes"][name])
        lines.append(f"index {name}" + (f" {parts}" if parts else ""))
    storage = state["storage"]
    if storage is not None:
        for key in STORAGE_KEYS:
            value = storage["attrs"].get(key)
            if value in (None, "", False):
                continue
            lines.append(f"storage {key}={_format_value(value)}")
        for name in sorted(storage["properties"]):
            parts = _render_attribute_parts(STORAGE_PROPERTY_KEYS, storage["properties"][name])
            lines.append(f"storage_property {name}" + (f" {parts}" if parts else ""))
    return tuple(lines)


def _resolve_model_type(py_type: Any) -> Any:
    origin = get_origin(py_type)
    if origin is not None:
        args = [arg for arg in get_args(py_type) if arg is not type(None)]
        if len(args) == 1:
            return _resolve_model_type(args[0])
    return py_type


def _map_python_type_to_iris(py_type: Any, field_meta: FieldInfo) -> str:
    if field_meta.iris_type is not None:
        return field_meta.iris_type

    if hasattr(py_type, "__origin__"):
        py_type = py_type.__origin__

    if hasattr(py_type, "__args__"):
        args = py_type.__args__
        has_none = type(None) in args
        if has_none and len(args) == 2:
            py_type = args[0] if args[1] is type(None) else args[1]

    if py_type is str:
        return "%Library.String"
    if py_type is int:
        return "%Library.Integer"
    if py_type is float:
        return "%Library.Float"
    if py_type is bool:
        return "%Library.Boolean"
    if py_type is bytes or py_type is bytearray:
        return "%Stream.GlobalBinary"
    if py_type is dict or str(py_type).startswith("dict"):
        return "%Library.DynamicObject"
    if py_type is list or str(py_type).startswith("list"):
        return "%Library.DynamicArray"
    if str(py_type) == "<class 'datetime.datetime'>":
        return "%Library.TimeStamp"
    if str(py_type) == "<class 'datetime.date'>":
        return "%Library.Date"
    if str(py_type) == "<class 'datetime.time'>":
        return "%Library.Time"
    if isinstance(py_type, type) and issubclass(py_type, iris_persistence.models.Model):
        return py_type._classname

    return "%Library.String"


def diff_schema(model_cls: Type[Any]) -> SchemaDiff:
    runtime = get_runtime()
    classname = getattr(model_cls, "_classname", model_cls.__name__)
    live_state = _collect_live_schema_state(runtime, classname)
    desired_state = _collect_model_schema_state(model_cls)
    planned_state = _merge_schema_state_for_sync(
        mode=getattr(model_cls, "_sync_mode", "extend"),
        live_state=live_state,
        desired_state=desired_state,
    )
    return SchemaDiff(
        classname=classname,
        before=_render_schema_state(live_state),
        after=_render_schema_state(planned_state),
    )


def _set_runtime_property(runtime: Any, obj: Any, prop_name: str, value: Any) -> None:
    runtime.set_property(obj, prop_name, value)


def _set_runtime_property_if_not_none(
    runtime: Any,
    obj: Any,
    prop_name: str,
    value: Any,
) -> None:
    if value is not None:
        runtime.set_property(obj, prop_name, value)


def _set_runtime_flag_if_true(runtime: Any, obj: Any, prop_name: str, enabled: Any) -> None:
    if enabled:
        runtime.set_property(obj, prop_name, 1)


def _ensure_class_definition(
    runtime: Any,
    classname: str,
    mode: str,
) -> tuple[Any, bool]:
    exists = runtime.call_classmethod("%Dictionary.ClassDefinition", "_ExistsId", classname)
    if mode == "replace" and exists:
        runtime.call_classmethod("%SYSTEM.OBJ", "Delete", classname, "-d")
        exists = False

    if exists:
        return (runtime.get_object("%Dictionary.ClassDefinition", classname), True)

    class_definition = runtime.create_object("%Dictionary.ClassDefinition")
    runtime.set_property(class_definition, "Name", classname)
    return (class_definition, False)


def _apply_class_definition(
    runtime: Any,
    class_definition: Any,
    classname: str,
    superclasses: str,
    class_metadata: Any,
) -> None:
    runtime.set_property(class_definition, "Super", superclasses)
    if class_metadata is None:
        return
    _set_runtime_property_if_not_none(
        runtime,
        class_definition,
        "Description",
        getattr(class_metadata, "description", None),
    )
    _set_runtime_flag_if_true(
        runtime,
        class_definition,
        "Deprecated",
        getattr(class_metadata, "deprecated", False),
    )
    _set_runtime_flag_if_true(
        runtime,
        class_definition,
        "Final",
        getattr(class_metadata, "final", False),
    )
    _set_runtime_property_if_not_none(
        runtime,
        class_definition,
        "SqlTableName",
        getattr(class_metadata, "sql_table_name", None),
    )
    _set_runtime_flag_if_true(
        runtime,
        class_definition,
        "ProcedureBlock",
        getattr(class_metadata, "procedure_block", False),
    )


def _sync_parameters(
    runtime: Any,
    class_definition: Any,
    classname: str,
    parameters: dict[str, Any],
    mode: str,
) -> None:
    if mode not in {"extend", "replace"} or not isinstance(parameters, dict):
        return

    parameter_list = runtime.get_property(class_definition, "Parameters")
    existing_parameters: set[str] = set()
    if mode == "extend" and parameter_list is not None:
        for parameter in _iter_runtime_list(runtime, parameter_list):
            existing_parameters.add(runtime.get_property(parameter, "Name"))

    if parameter_list is None:
        return

    for param_name, param_default in parameters.items():
        if mode == "extend" and param_name in existing_parameters:
            continue
        param_def = runtime.create_object("%Dictionary.ParameterDefinition")
        runtime.set_property(param_def, "Name", param_name)
        runtime.set_property(param_def, "parent", classname)
        runtime.set_property(param_def, "Default", str(param_default))
        runtime.invoke_method(parameter_list, "Insert", param_def)


def _sync_related_models(
    model_cls: Type[Any],
    model_fields: dict[str, Any],
    seen: set[str],
) -> None:
    for model_field in model_fields.values():
        resolved = _resolve_model_type(model_field.declared_type)
        if (
            isinstance(resolved, type)
            and issubclass(resolved, iris_persistence.models.Model)
            and resolved is not model_cls
        ):
            sync_schema(resolved, seen)


def _property_initial_expression(field_meta: FieldInfo) -> str | None:
    if getattr(field_meta, "initial_expression", None) is not None:
        return field_meta.initial_expression

    default = getattr(field_meta, "default", UNSET)
    if default is UNSET or default is None:
        return None
    if isinstance(default, str):
        return f'"{default}"'
    if isinstance(default, bool):
        return "1" if default else "0"
    return str(default)


def _build_property_definition(
    runtime: Any,
    classname: str,
    field_name: str,
    model_field: Any,
) -> Any:
    field_meta = model_field.field_info
    prop = runtime.create_object("%Dictionary.PropertyDefinition")
    runtime.set_property(prop, "Name", field_name)
    runtime.set_property(prop, "parent", classname)
    runtime.set_property(
        prop,
        "Type",
        _map_python_type_to_iris(
            _resolve_model_type(model_field.declared_type),
            field_meta,
        ),
    )
    _set_runtime_flag_if_true(runtime, prop, "Required", getattr(field_meta, "required", False))
    _set_runtime_flag_if_true(runtime, prop, "ReadOnly", getattr(field_meta, "readonly", False))
    _set_runtime_property_if_not_none(
        runtime, prop, "Collection", getattr(field_meta, "collection", None)
    )
    _set_runtime_property_if_not_none(
        runtime, prop, "SqlFieldName", getattr(field_meta, "sql_field_name", None)
    )
    _set_runtime_flag_if_true(runtime, prop, "Identity", getattr(field_meta, "identity", False))
    _set_runtime_property_if_not_none(
        runtime, prop, "Relationship", getattr(field_meta, "relationship", None)
    )
    _set_runtime_property_if_not_none(
        runtime, prop, "OnDelete", getattr(field_meta, "on_delete", None)
    )
    _set_runtime_property_if_not_none(
        runtime, prop, "Inverse", getattr(field_meta, "inverse", None)
    )
    _set_runtime_flag_if_true(runtime, prop, "Transient", getattr(field_meta, "transient", False))
    if getattr(field_meta, "storable", True) is False:
        runtime.set_property(prop, "Storable", 0)
    _set_runtime_flag_if_true(
        runtime,
        prop,
        "MultiDimensional",
        getattr(field_meta, "multi_dimensional", False),
    )
    _set_runtime_property_if_not_none(
        runtime,
        prop,
        "SqlListDelimiter",
        getattr(field_meta, "sql_list_delimiter", None),
    )
    _set_runtime_property_if_not_none(
        runtime,
        prop,
        "SqlListType",
        getattr(field_meta, "sql_list_type", None),
    )
    _set_runtime_property_if_not_none(
        runtime,
        prop,
        "SqlComputeCode",
        getattr(field_meta, "sql_compute_code", None),
    )
    _set_runtime_property_if_not_none(
        runtime,
        prop,
        "SqlComputeOnChange",
        getattr(field_meta, "sql_compute_on_change", None),
    )
    _set_runtime_flag_if_true(
        runtime,
        prop,
        "SqlComputed",
        getattr(field_meta, "sql_computed", False),
    )
    _set_runtime_property_if_not_none(
        runtime,
        prop,
        "InitialExpression",
        _property_initial_expression(field_meta),
    )

    max_length = getattr(field_meta, "max_length", None)
    if max_length is not None:
        params = runtime.get_property(prop, "Parameters")
        if params is not None:
            runtime.invoke_method(params, "SetAt", str(max_length), "MAXLEN")
    return prop


def _sync_properties(
    runtime: Any,
    class_definition: Any,
    classname: str,
    model_fields: dict[str, Any],
    mode: str,
) -> None:
    props_oref_list = runtime.get_property(class_definition, "Properties")
    existing_props = {
        runtime.get_property(prop, "Name"): prop
        for prop in _iter_runtime_list(runtime, props_oref_list)
    }

    for field_name, model_field in model_fields.items():
        if mode == "extend" and field_name in existing_props:
            continue
        prop = _build_property_definition(runtime, classname, field_name, model_field)
        runtime.invoke_method(props_oref_list, "Insert", prop)


def _sync_indexes(
    runtime: Any,
    class_definition: Any,
    classname: str,
    indexes: list[Any],
    mode: str,
) -> None:
    if mode not in {"extend", "replace"} or not isinstance(indexes, list):
        return

    index_list = runtime.get_property(class_definition, "Indices")
    existing_indexes: set[str] = set()
    if mode == "extend" and index_list is not None:
        for index in _iter_runtime_list(runtime, index_list):
            existing_indexes.add(runtime.get_property(index, "Name"))

    if index_list is None:
        return

    for index_meta in indexes:
        if mode == "extend" and index_meta.name in existing_indexes:
            continue
        idx_def = runtime.create_object("%Dictionary.IndexDefinition")
        runtime.set_property(idx_def, "Name", index_meta.name)
        runtime.set_property(idx_def, "parent", classname)
        runtime.set_property(idx_def, "Properties", index_meta.properties)
        _set_runtime_flag_if_true(runtime, idx_def, "Unique", getattr(index_meta, "unique", False))
        _set_runtime_property_if_not_none(
            runtime,
            idx_def,
            "Type",
            getattr(index_meta, "type", None),
        )
        _set_runtime_flag_if_true(
            runtime,
            idx_def,
            "PrimaryKey",
            getattr(index_meta, "primary_key", False),
        )
        runtime.invoke_method(index_list, "Insert", idx_def)


def _apply_storage_attributes(runtime: Any, storage_definition: Any, storage_meta: Any) -> None:
    storage_attr_map = (
        ("Type", "type"),
        ("DataLocation", "data_location"),
        ("DefaultData", "default_data"),
        ("ExtentLocation", "extent_location"),
        ("ExtentSize", "extent_size"),
        ("CounterLocation", "counter_location"),
        ("VersionLocation", "version_location"),
        ("IdLocation", "id_location"),
        ("IdExpression", "id_expression"),
        ("IdFunction", "id_function"),
        ("IndexLocation", "index_location"),
        ("State", "state"),
        ("StreamLocation", "stream_location"),
        ("SqlChildSub", "sql_child_sub"),
        ("SqlIdExpression", "sql_id_expression"),
        ("SqlRowIdName", "sql_row_id_name"),
        ("SqlRowIdProperty", "sql_row_id_property"),
        ("SqlTableNumber", "sql_table_number"),
        ("SequenceNumber", "sequence_number"),
    )
    for property_name, attr_name in storage_attr_map:
        _set_runtime_property_if_not_none(
            runtime,
            storage_definition,
            property_name,
            getattr(storage_meta, attr_name, None),
        )


def _insert_storage_data(
    runtime: Any,
    storage_definition: Any,
    classname: str,
    storage_name: str,
    storage_meta: Any,
) -> None:
    data_list = runtime.get_property(storage_definition, "Data")
    for data_meta in getattr(storage_meta, "data", []):
        data_definition = runtime.create_object("%Dictionary.StorageDataDefinition")
        runtime.set_property(data_definition, "Name", data_meta.name)
        runtime.set_property(data_definition, "parent", f"{classname}||{storage_name}")
        _set_runtime_property_if_not_none(
            runtime, data_definition, "Structure", getattr(data_meta, "structure", None)
        )
        _set_runtime_property_if_not_none(
            runtime, data_definition, "Attribute", getattr(data_meta, "attribute", None)
        )
        _set_runtime_property_if_not_none(
            runtime, data_definition, "Subscript", getattr(data_meta, "subscript", None)
        )

        value_list = runtime.get_property(data_definition, "Values")
        for key, value in (getattr(data_meta, "values", None) or {}).items():
            value_definition = runtime.create_object("%Dictionary.StorageDataValueDefinition")
            runtime.set_property(value_definition, "Name", str(key))
            runtime.set_property(
                value_definition,
                "parent",
                f"{classname}||{storage_name}||{data_meta.name}",
            )
            runtime.set_property(value_definition, "Value", str(value))
            runtime.invoke_method(value_list, "Insert", value_definition)

        runtime.invoke_method(data_list, "Insert", data_definition)


def _insert_storage_indices(
    runtime: Any,
    storage_definition: Any,
    classname: str,
    storage_name: str,
    storage_meta: Any,
) -> None:
    indices_list = runtime.get_property(storage_definition, "Indices")
    for index_meta in getattr(storage_meta, "indices", ()) or ():
        storage_index = runtime.create_object("%Dictionary.StorageIndexDefinition")
        runtime.set_property(storage_index, "Name", index_meta.name)
        runtime.set_property(storage_index, "parent", f"{classname}||{storage_name}")
        _set_runtime_property_if_not_none(
            runtime, storage_index, "Location", getattr(index_meta, "location", None)
        )
        _set_runtime_property_if_not_none(
            runtime,
            storage_index,
            "SmallChunkSize",
            getattr(index_meta, "small_chunk_size", None),
        )
        runtime.invoke_method(indices_list, "Insert", storage_index)


def _insert_storage_properties(
    runtime: Any,
    storage_definition: Any,
    classname: str,
    storage_name: str,
    storage_meta: Any,
) -> None:
    properties_list = runtime.get_property(storage_definition, "Properties")
    for property_meta in getattr(storage_meta, "properties", []):
        storage_property = runtime.create_object("%Dictionary.StoragePropertyDefinition")
        runtime.set_property(storage_property, "Name", property_meta.name)
        runtime.set_property(storage_property, "parent", f"{classname}||{storage_name}")
        _set_runtime_property_if_not_none(
            runtime,
            storage_property,
            "AverageFieldSize",
            getattr(property_meta, "average_field_size", None),
        )
        _set_runtime_property_if_not_none(
            runtime,
            storage_property,
            "Selectivity",
            getattr(property_meta, "selectivity", None),
        )
        _set_runtime_property_if_not_none(
            runtime,
            storage_property,
            "OutlierSelectivity",
            getattr(property_meta, "outlier_selectivity", None),
        )
        _set_runtime_property_if_not_none(
            runtime, storage_property, "Histogram", getattr(property_meta, "histogram", None)
        )
        _set_runtime_property_if_not_none(
            runtime,
            storage_property,
            "ChildBlockCount",
            getattr(property_meta, "child_block_count", None),
        )
        _set_runtime_property_if_not_none(
            runtime,
            storage_property,
            "ChildExtentSize",
            getattr(property_meta, "child_extent_size", None),
        )
        if getattr(property_meta, "bias_queries_as_outlier", None) is not None:
            runtime.set_property(
                storage_property,
                "BiasQueriesAsOutlier",
                1 if property_meta.bias_queries_as_outlier else 0,
            )
        _set_runtime_property_if_not_none(
            runtime,
            storage_property,
            "StreamLocation",
            getattr(property_meta, "stream_location", None),
        )
        runtime.invoke_method(properties_list, "Insert", storage_property)


def _insert_storage_sql_maps(
    runtime: Any,
    storage_definition: Any,
    classname: str,
    storage_name: str,
    storage_meta: Any,
) -> None:
    sql_maps_list = runtime.get_property(storage_definition, "SQLMaps")
    for sql_map_meta in getattr(storage_meta, "sql_maps", []):
        sql_map = runtime.create_object("%Dictionary.StorageSQLMapDefinition")
        runtime.set_property(sql_map, "Name", sql_map_meta.name)
        runtime.set_property(sql_map, "parent", f"{classname}||{storage_name}")
        _set_runtime_property_if_not_none(
            runtime, sql_map, "BlockCount", getattr(sql_map_meta, "block_count", None)
        )
        _set_runtime_property_if_not_none(
            runtime, sql_map, "Condition", getattr(sql_map_meta, "condition", None)
        )
        _set_runtime_property_if_not_none(
            runtime,
            sql_map,
            "ConditionFields",
            getattr(sql_map_meta, "condition_fields", None),
        )
        if getattr(sql_map_meta, "conditional_with_host_vars", None) is not None:
            runtime.set_property(
                sql_map,
                "ConditionalWithHostVars",
                1 if sql_map_meta.conditional_with_host_vars else 0,
            )
        _set_runtime_property_if_not_none(
            runtime, sql_map, "Global", getattr(sql_map_meta, "global_name", None)
        )
        _set_runtime_property_if_not_none(
            runtime,
            sql_map,
            "PopulationPct",
            getattr(sql_map_meta, "population_pct", None),
        )
        _set_runtime_property_if_not_none(
            runtime,
            sql_map,
            "PopulationType",
            getattr(sql_map_meta, "population_type", None),
        )
        _set_runtime_property_if_not_none(
            runtime,
            sql_map,
            "RowReference",
            getattr(sql_map_meta, "row_reference", None),
        )
        _set_runtime_property_if_not_none(
            runtime, sql_map, "Structure", getattr(sql_map_meta, "structure", None)
        )
        _set_runtime_property_if_not_none(
            runtime, sql_map, "Type", getattr(sql_map_meta, "type", None)
        )

        sql_map_data_list = runtime.get_property(sql_map, "Data")
        for data_meta in getattr(sql_map_meta, "data", ()) or ():
            sql_map_data = runtime.create_object("%Dictionary.StorageSQLMapDataDefinition")
            runtime.set_property(sql_map_data, "Name", data_meta.name)
            runtime.set_property(
                sql_map_data,
                "parent",
                f"{classname}||{storage_name}||{sql_map_meta.name}",
            )
            _set_runtime_property_if_not_none(
                runtime,
                sql_map_data,
                "Node",
                getattr(data_meta, "node", None),
            )
            _set_runtime_property_if_not_none(
                runtime,
                sql_map_data,
                "Piece",
                getattr(data_meta, "piece", None),
            )
            _set_runtime_property_if_not_none(
                runtime, sql_map_data, "Delimiter", getattr(data_meta, "delimiter", None)
            )
            _set_runtime_property_if_not_none(
                runtime,
                sql_map_data,
                "RetrievalCode",
                getattr(data_meta, "retrieval_code", None),
            )
            runtime.invoke_method(sql_map_data_list, "Insert", sql_map_data)

        row_id_spec_list = runtime.get_property(sql_map, "RowIdSpecs")
        for row_id_spec_meta in getattr(sql_map_meta, "row_id_specs", ()) or ():
            row_id_spec = runtime.create_object("%Dictionary.StorageSQLMapRowIdSpecDefinition")
            runtime.set_property(row_id_spec, "Name", row_id_spec_meta.name)
            runtime.set_property(
                row_id_spec,
                "parent",
                f"{classname}||{storage_name}||{sql_map_meta.name}",
            )
            _set_runtime_property_if_not_none(
                runtime, row_id_spec, "Field", getattr(row_id_spec_meta, "field", None)
            )
            _set_runtime_property_if_not_none(
                runtime,
                row_id_spec,
                "Expression",
                getattr(row_id_spec_meta, "expression", None),
            )
            runtime.invoke_method(row_id_spec_list, "Insert", row_id_spec)

        subscript_list = runtime.get_property(sql_map, "Subscripts")
        for sub_meta in getattr(sql_map_meta, "subscripts", ()) or ():
            subscript = runtime.create_object("%Dictionary.StorageSQLMapSubDefinition")
            runtime.set_property(subscript, "Name", sub_meta.name)
            runtime.set_property(
                subscript,
                "parent",
                f"{classname}||{storage_name}||{sql_map_meta.name}",
            )
            _set_runtime_property_if_not_none(
                runtime, subscript, "AccessType", getattr(sub_meta, "access_type", None)
            )
            _set_runtime_property_if_not_none(
                runtime, subscript, "DataAccess", getattr(sub_meta, "data_access", None)
            )
            _set_runtime_property_if_not_none(
                runtime, subscript, "Delimiter", getattr(sub_meta, "delimiter", None)
            )
            _set_runtime_property_if_not_none(
                runtime, subscript, "Expression", getattr(sub_meta, "expression", None)
            )
            _set_runtime_property_if_not_none(
                runtime,
                subscript,
                "LoopInitValue",
                getattr(sub_meta, "loop_init_value", None),
            )
            _set_runtime_property_if_not_none(
                runtime, subscript, "NextCode", getattr(sub_meta, "next_code", None)
            )
            _set_runtime_property_if_not_none(
                runtime, subscript, "NullMarker", getattr(sub_meta, "null_marker", None)
            )
            _set_runtime_property_if_not_none(
                runtime, subscript, "StartValue", getattr(sub_meta, "start_value", None)
            )
            _set_runtime_property_if_not_none(
                runtime,
                subscript,
                "StopExpression",
                getattr(sub_meta, "stop_expression", None),
            )
            _set_runtime_property_if_not_none(
                runtime, subscript, "StopValue", getattr(sub_meta, "stop_value", None)
            )

            access_var_list = runtime.get_property(subscript, "Accessvars")
            for access_var_meta in getattr(sub_meta, "access_vars", ()) or ():
                access_var = runtime.create_object(
                    "%Dictionary.StorageSQLMapSubAccessvarDefinition"
                )
                runtime.set_property(access_var, "Name", access_var_meta.name)
                runtime.set_property(
                    access_var,
                    "parent",
                    f"{classname}||{storage_name}||{sql_map_meta.name}||{sub_meta.name}",
                )
                _set_runtime_property_if_not_none(
                    runtime, access_var, "Variable", getattr(access_var_meta, "variable", None)
                )
                _set_runtime_property_if_not_none(
                    runtime, access_var, "Code", getattr(access_var_meta, "code", None)
                )
                runtime.invoke_method(access_var_list, "Insert", access_var)

            invalid_condition_list = runtime.get_property(subscript, "Invalidconditions")
            for invalid_condition_meta in getattr(sub_meta, "invalid_conditions", ()) or ():
                invalid_condition = runtime.create_object(
                    "%Dictionary.StorageSQLMapSubInvalidconditionDefinition"
                )
                runtime.set_property(invalid_condition, "Name", invalid_condition_meta.name)
                runtime.set_property(
                    invalid_condition,
                    "parent",
                    f"{classname}||{storage_name}||{sql_map_meta.name}||{sub_meta.name}",
                )
                _set_runtime_property_if_not_none(
                    runtime,
                    invalid_condition,
                    "Expression",
                    getattr(invalid_condition_meta, "expression", None),
                )
                runtime.invoke_method(invalid_condition_list, "Insert", invalid_condition)

            runtime.invoke_method(subscript_list, "Insert", subscript)

        runtime.invoke_method(sql_maps_list, "Insert", sql_map)


def _sync_storage(
    runtime: Any,
    class_definition: Any,
    classname: str,
    storage_meta: Any,
    mode: str,
) -> None:
    if not storage_meta or mode != "replace":
        return

    storage_list = runtime.get_property(class_definition, "Storages")
    storage_definition = runtime.create_object("%Dictionary.StorageDefinition")
    storage_name = "CustomStorage"
    runtime.set_property(storage_definition, "Name", storage_name)
    runtime.set_property(storage_definition, "parent", classname)
    runtime.set_property(class_definition, "StorageStrategy", storage_name)

    _apply_storage_attributes(runtime, storage_definition, storage_meta)
    _insert_storage_data(runtime, storage_definition, classname, storage_name, storage_meta)
    _insert_storage_indices(runtime, storage_definition, classname, storage_name, storage_meta)
    _insert_storage_properties(runtime, storage_definition, classname, storage_name, storage_meta)
    _insert_storage_sql_maps(runtime, storage_definition, classname, storage_name, storage_meta)

    runtime.invoke_method(storage_list, "Insert", storage_definition)


def sync_schema(model_cls: Type[Any], _seen: set[str] | None = None) -> None:
    mode = getattr(model_cls, "_sync_mode", "extend")
    if mode == "observe":
        return

    if _seen is None:
        _seen = set()

    runtime = get_runtime()
    classname = getattr(model_cls, "_classname", model_cls.__name__)
    superclasses = getattr(model_cls, "_superclasses", "%Persistent")
    if classname in _seen:
        return
    _seen.add(classname)

    cd, _exists = _ensure_class_definition(runtime, classname, mode)
    class_metadata = getattr(model_cls, "_class_metadata", None)
    _apply_class_definition(runtime, cd, classname, superclasses, class_metadata)

    parameters = getattr(model_cls, "_parameters", {}) or {}
    _sync_parameters(runtime, cd, classname, parameters, mode)

    model_fields = getattr(model_cls, "__model_fields__", {})
    _sync_related_models(model_cls, model_fields, _seen)
    _sync_properties(runtime, cd, classname, model_fields, mode)

    indexes = getattr(model_cls, "_indexes", [])
    _sync_indexes(runtime, cd, classname, indexes, mode)

    storage_meta = getattr(model_cls, "_storage", None)
    _sync_storage(runtime, cd, classname, storage_meta, mode)

    st = runtime.save_object(cd)
    if not runtime.is_ok(st):
        raise RuntimeError(f"Schema save failed for {classname}: {runtime.format_status(st)}")

    runtime.call_classmethod("%SYSTEM.OBJ", "Compile", classname, "fc /display=none")
