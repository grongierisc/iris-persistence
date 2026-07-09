from __future__ import annotations

import decimal
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from difflib import unified_diff
from types import SimpleNamespace
from typing import Any, Callable, Type, get_args, get_origin

import iris_persistence.models
from iris_persistence.field_utils import PYTHON_TO_IRIS_TYPE, coerce_bool
from iris_persistence.runtime import get_runtime
from iris_persistence.types import UNSET, FieldInfo

CLASS_METADATA_KEYS = (
    "description",
    "deprecated",
    "final",
    "sql_table_name",
    "procedure_block",
)
CLASS_METADATA_FLAG_KEYS = {"deprecated", "final", "procedure_block"}
# Single source of truth for property state keys.
# Rows: (state key, %Dictionary property/parameter name, kind) where kind is:
#   "flag"    boolean stored as 1/0 on the property definition
#   "value"   plain value stored on the property definition
#   "param"   property parameter (Parameters.SetAt)
#   "special" handled explicitly (computed type, inverted storable)
_PROPERTY_SPEC = (
    ("type", "Type", "special"),
    ("required", "Required", "flag"),
    ("readonly", "ReadOnly", "flag"),
    ("collection", "Collection", "value"),
    ("sql_field_name", "SqlFieldName", "value"),
    ("identity", "Identity", "flag"),
    ("relationship", "Relationship", "value"),
    ("on_delete", "OnDelete", "value"),
    ("inverse", "Inverse", "value"),
    ("transient", "Transient", "flag"),
    ("storable", "Storable", "special"),
    ("multi_dimensional", "MultiDimensional", "flag"),
    ("sql_list_delimiter", "SqlListDelimiter", "value"),
    ("sql_list_type", "SqlListType", "value"),
    ("sql_compute_code", "SqlComputeCode", "value"),
    ("sql_compute_on_change", "SqlComputeOnChange", "value"),
    ("sql_computed", "SqlComputed", "flag"),
    ("initial_expression", "InitialExpression", "value"),
    ("max_length", "MAXLEN", "param"),
    ("scale", "SCALE", "param"),
)
PROPERTY_KEYS = tuple(key for key, _name, _kind in _PROPERTY_SPEC)
_PROPERTY_FLAG_FIELDS = tuple(
    (key, name) for key, name, kind in _PROPERTY_SPEC if kind == "flag"
)
_PROPERTY_VALUE_FIELDS = tuple(
    (key, name) for key, name, kind in _PROPERTY_SPEC if kind == "value"
)
_PROPERTY_PARAM_FIELDS = tuple(
    (key, name) for key, name, kind in _PROPERTY_SPEC if kind == "param"
)
DEFAULT_DECIMAL_SCALE = "18"
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
STORAGE_DATA_KEYS = ("structure", "attribute", "subscript")
STORAGE_INDEX_KEYS = ("location", "small_chunk_size")
STORAGE_SQL_MAP_KEYS = (
    "block_count",
    "condition",
    "condition_fields",
    "conditional_with_host_vars",
    "global_name",
    "population_pct",
    "population_type",
    "row_reference",
    "structure",
    "type",
)
STORAGE_SQL_MAP_DATA_KEYS = ("node", "piece", "delimiter", "retrieval_code")
STORAGE_SQL_MAP_ROW_ID_SPEC_KEYS = ("field", "expression")
STORAGE_SQL_MAP_SUB_KEYS = (
    "access_type",
    "data_access",
    "delimiter",
    "expression",
    "loop_init_value",
    "next_code",
    "null_marker",
    "start_value",
    "stop_expression",
    "stop_value",
)
STORAGE_SQL_MAP_SUB_ACCESS_VAR_KEYS = ("variable", "code")
STORAGE_SQL_MAP_SUB_INVALID_CONDITION_KEYS = ("expression",)


@dataclass(frozen=True)
class SchemaOperation:
    classname: str
    op_type: str
    path: str
    before: Any = None
    after: Any = None
    safety: str = "safe"

    def to_dict(self) -> dict[str, Any]:
        return {
            "classname": self.classname,
            "op_type": self.op_type,
            "path": self.path,
            "before": self.before,
            "after": self.after,
            "safety": self.safety,
        }


@dataclass(frozen=True)
class SchemaState:
    classname: str
    superclasses: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    properties: dict[str, dict[str, Any]] = field(default_factory=dict)
    indexes: dict[str, dict[str, Any]] = field(default_factory=dict)
    storage: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, state: dict[str, Any]) -> "SchemaState":
        return cls(
            classname=str(state["classname"]),
            superclasses=state.get("super"),
            metadata=deepcopy(state.get("metadata", {})),
            parameters=deepcopy(state.get("parameters", {})),
            properties=deepcopy(state.get("properties", {})),
            indexes=deepcopy(state.get("indexes", {})),
            storage=deepcopy(state.get("storage")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "classname": self.classname,
            "super": self.superclasses,
            "metadata": deepcopy(self.metadata),
            "parameters": deepcopy(self.parameters),
            "properties": deepcopy(self.properties),
            "indexes": deepcopy(self.indexes),
            "storage": deepcopy(self.storage),
        }

    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def __getitem__(self, key: str) -> Any:
        if key == "super":
            return self.superclasses
        return getattr(self, key)


@dataclass(frozen=True)
class SchemaDiff:
    classname: str
    before: tuple[str, ...]
    after: tuple[str, ...]
    before_state: SchemaState | None = None
    after_state: SchemaState | None = None
    operations: tuple[SchemaOperation, ...] = ()

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


def _safe_get_property(runtime: Any, obj: Any, prop_name: str) -> Any:
    try:
        return runtime.get_property(obj, prop_name)
    except Exception:
        return None


def _iter_runtime_list(runtime: Any, list_obj: Any) -> list[Any]:
    return [item for _index, item in _iter_runtime_list_with_indices(runtime, list_obj)]


def _iter_runtime_list_with_indices(runtime: Any, list_obj: Any) -> list[tuple[int, Any]]:
    if list_obj is None:
        return []
    try:
        count = runtime.invoke_method(list_obj, "Count")
    except Exception:
        return []
    items = []
    for index in range(1, count + 1):
        try:
            items.append((index, runtime.invoke_method(list_obj, "GetAt", index)))
        except Exception:
            continue
    return items


def _remove_runtime_list_indices(
    runtime: Any,
    list_obj: Any,
    indices: list[int],
    *,
    context: str,
) -> None:
    for index in sorted(indices, reverse=True):
        last_error: Exception | None = None
        for method_name in ("RemoveAt", "DeleteAt", "Remove"):
            try:
                runtime.invoke_method(list_obj, method_name, index)
                break
            except Exception as exc:
                last_error = exc
        else:
            raise RuntimeError(f"Could not remove schema member from {context}") from last_error


def _is_system_member_name(name: str) -> bool:
    return name.startswith("%") or name == "GUID"


def _owned_schema_member_entries(
    runtime: Any,
    list_obj: Any,
    classname: str,
    *,
    dictionary_class_name: str | None = None,
    skip_system_names: bool = True,
) -> dict[str, tuple[int, Any, str | None]]:
    entries: dict[str, tuple[int, Any, str | None]] = {}
    for index, item in _iter_runtime_list_with_indices(runtime, list_obj):
        name = _safe_get_property(runtime, item, "Name")
        if not name:
            continue
        name = str(name)
        if skip_system_names and _is_system_member_name(name):
            continue
        if not _item_belongs_to_class(runtime, item, classname):
            continue
        entries[name] = (index, item, None)
    if dictionary_class_name is None:
        return entries

    rows = _dictionary_rows(
        runtime,
        f"SELECT %ID, Name FROM {dictionary_class_name} WHERE parent = ?",
        (classname,),
    )
    for row in rows:
        name = _row_value(row, "Name")
        object_id = _row_value(row, "%ID")
        if not name or not object_id:
            continue
        name = str(name)
        if skip_system_names and _is_system_member_name(name):
            continue
        try:
            obj = runtime.get_object(dictionary_class_name, str(object_id))
        except Exception:
            continue
        existing = entries.get(name)
        if existing is None:
            entries[name] = (0, obj, str(object_id))
        else:
            entries[name] = (existing[0], existing[1], str(object_id))
    return entries


def _remove_owned_schema_member_entries(
    runtime: Any,
    list_obj: Any,
    entries: list[tuple[int, Any, str | None]],
    *,
    dictionary_class_name: str,
    context: str,
) -> None:
    _remove_runtime_list_indices(
        runtime,
        list_obj,
        [index for index, _item, _object_id in entries if index > 0],
        context=context,
    )
    for _index, _item, object_id in entries:
        if object_id is None:
            continue
        try:
            runtime.delete_object(dictionary_class_name, object_id)
        except Exception:
            pass


def _item_belongs_to_class(runtime: Any, item: Any, classname: str) -> bool:
    inherited = _safe_get_property(runtime, item, "Inherited")
    if inherited is not None:
        return not coerce_bool(inherited)

    for attr_name in ("Origin", "Parent", "parent", "Class"):
        owner = _safe_get_property(runtime, item, attr_name)
        if owner in (None, ""):
            continue
        owner_name = _safe_get_property(runtime, owner, "Name")
        if owner_name not in (None, ""):
            return str(owner_name) == classname
        return str(owner) == classname
    return True


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    return repr(value)


def _compact_mapping(
    mapping: dict[str, Any],
    *,
    preserve_false_keys: tuple[str, ...] = (),
) -> dict[str, Any]:
    compact = {}
    for key, value in mapping.items():
        if value in (None, "") or (value is False and key not in preserve_false_keys):
            continue
        compact[key] = value
    return compact


def _compact_property_state(mapping: dict[str, Any]) -> dict[str, Any]:
    return _compact_mapping(mapping, preserve_false_keys=("storable",))


def _object_state(obj: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    return _compact_mapping({key: getattr(obj, key, None) for key in keys})


def _named_object_mapping(
    items: Any,
    keys: tuple[str, ...],
    *,
    extra: Any = None,
) -> dict[str, Any]:
    states = {}
    for item in items or ():
        state = _object_state(item, keys)
        if extra is not None:
            state.update(extra(item))
        states[item.name] = _compact_mapping(state)
    return _sort_mapping(states)


def _sort_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    return {str(key): mapping[key] for key in sorted(mapping, key=str)}


def _normalize_values_mapping(mapping: dict[Any, Any] | None) -> dict[str, str]:
    if not mapping:
        return {}
    return {str(key): str(mapping[key]) for key in sorted(mapping, key=lambda item: str(item))}


def _row_value(row: dict[str, Any], name: str) -> Any:
    for key, value in row.items():
        if key.lower() == name.lower():
            return value
        if name == "%ID" and key.lower() == "id":
            return value
    return None


def _dictionary_rows(runtime: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    try:
        cursor = runtime.get_dbapi_connection().cursor()
        cursor.execute(sql, params)
        columns = [str(column[0]) for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    except Exception:
        return []


def _state_to_dict(state: SchemaState | dict[str, Any]) -> dict[str, Any]:
    return state.to_dict() if isinstance(state, SchemaState) else deepcopy(state)


def _render_attribute_parts(keys: tuple[str, ...], mapping: dict[str, Any]) -> str:
    parts = []
    for key in keys:
        value = mapping.get(key)
        if value in (None, "", False):
            continue
        parts.append(f"{key}={_format_value(value)}")
    return " ".join(parts)


def _append_state_lines(
    lines: list[str],
    prefix: str,
    items: dict[str, dict[str, Any]],
    keys: tuple[str, ...],
    *,
    name_prefix: str = "",
) -> None:
    for name in sorted(items):
        _append_state_line(lines, prefix, f"{name_prefix}{name}", keys, items[name])


def _append_state_line(
    lines: list[str],
    prefix: str,
    name: str,
    keys: tuple[str, ...],
    item: dict[str, Any],
) -> None:
    parts = _render_attribute_parts(keys, item)
    if not name and not parts:
        return
    label = f"{prefix} {name}" if name else prefix
    lines.append(label + (f" {parts}" if parts else ""))


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


def _empty_storage_state() -> dict[str, Any]:
    return {
        "name": None,
        "attrs": {},
        "data": {},
        "indices": {},
        "properties": {},
        "sql_maps": {},
    }


def _schema_classname_for_save(classname: str) -> str:
    if "." in classname or classname.startswith("%"):
        return classname
    return f"User.{classname}"


def _candidate_classnames(classname: str) -> tuple[str, ...]:
    default_classname = _schema_classname_for_save(classname)
    if default_classname == classname:
        return (classname,)
    return (classname, default_classname)


def _find_existing_classname(runtime: Any, classname: str) -> str | None:
    for candidate in _candidate_classnames(classname):
        if runtime.call_classmethod("%Dictionary.ClassDefinition", "_ExistsId", candidate):
            return candidate
    return None


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


def _decimal_scale_for_field(py_type: Any, iris_type: str) -> str | None:
    if py_type in (float, decimal.Decimal) and iris_type == "%Library.Decimal":
        return DEFAULT_DECIMAL_SCALE
    return None


def _collect_model_schema_state_for_field(field_name: str, model_field: Any) -> dict[str, Any]:
    field_meta = model_field.field_info
    py_type = _resolve_model_type(model_field.declared_type)
    iris_type = _map_python_type_to_iris(py_type, field_meta)
    overrides = {
        "type": iris_type,
        "storable": (False if getattr(field_meta, "storable", True) is False else None),
        "initial_expression": _field_initial_expression(field_meta),
        "scale": _decimal_scale_for_field(py_type, iris_type),
    }
    return _compact_property_state(
        {
            key: overrides[key] if key in overrides else getattr(field_meta, key, None)
            for key, _name, _kind in _PROPERTY_SPEC
        }
    )


def _collect_model_schema_state(model_cls: Type[Any]) -> SchemaState:
    classname = _schema_classname_for_save(getattr(model_cls, "_classname", model_cls.__name__))
    state = _empty_schema_state(classname)
    state["super"] = getattr(model_cls, "_superclasses", "%Persistent")

    class_metadata = getattr(model_cls, "_class_metadata", None)
    if class_metadata is not None:
        state["metadata"] = _object_state(class_metadata, CLASS_METADATA_KEYS)

    parameters = getattr(model_cls, "_parameters", {}) or {}
    state["parameters"] = {str(name): str(value) for name, value in parameters.items()}

    properties = {}
    for field_name, model_field in getattr(model_cls, "__model_fields__", {}).items():
        properties[field_name] = _collect_model_schema_state_for_field(field_name, model_field)
    state["properties"] = properties

    indexes = {}
    for index_meta in getattr(model_cls, "_indexes", []) or []:
        indexes[index_meta.name] = _index_state_from_meta(index_meta)
    state["indexes"] = indexes

    storage_meta = getattr(model_cls, "_storage", None)
    if storage_meta is not None:
        storage_state = _empty_storage_state()
        storage_state["name"] = "CustomStorage"
        storage_state["attrs"] = _object_state(storage_meta, STORAGE_KEYS)
        storage_state["data"] = _named_object_mapping(
            getattr(storage_meta, "data", None),
            STORAGE_DATA_KEYS,
            extra=lambda item: {
                "values": _normalize_values_mapping(getattr(item, "values", None))
            },
        )
        storage_state["indices"] = _named_object_mapping(
            getattr(storage_meta, "indices", None),
            STORAGE_INDEX_KEYS,
        )
        storage_state["properties"] = _named_object_mapping(
            getattr(storage_meta, "properties", None),
            STORAGE_PROPERTY_KEYS,
        )
        storage_state["sql_maps"] = _sort_mapping(
            {
                item.name: _compact_mapping(
                    {
                        **_object_state(item, STORAGE_SQL_MAP_KEYS),
                        "data": _named_object_mapping(
                            getattr(item, "data", None),
                            STORAGE_SQL_MAP_DATA_KEYS,
                        ),
                        "row_id_specs": _named_object_mapping(
                            getattr(item, "row_id_specs", None),
                            STORAGE_SQL_MAP_ROW_ID_SPEC_KEYS,
                        ),
                        "subscripts": _named_object_mapping(
                            getattr(item, "subscripts", None),
                            STORAGE_SQL_MAP_SUB_KEYS,
                            extra=lambda child: {
                                "access_vars": _named_object_mapping(
                                    getattr(child, "access_vars", None),
                                    STORAGE_SQL_MAP_SUB_ACCESS_VAR_KEYS,
                                ),
                                "invalid_conditions": _named_object_mapping(
                                    getattr(child, "invalid_conditions", None),
                                    STORAGE_SQL_MAP_SUB_INVALID_CONDITION_KEYS,
                                ),
                            },
                        ),
                    }
                )
                for item in getattr(storage_meta, "sql_maps", ()) or ()
            }
        )
        state["storage"] = storage_state

    return SchemaState.from_dict(state)


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


def _index_state_from_getter(get_value: Any) -> dict[str, Any]:
    return _compact_mapping(
        {
            "properties": get_value("Properties"),
            "unique": coerce_bool(get_value("Unique")),
            "type": get_value("Type"),
            "primary_key": coerce_bool(get_value("PrimaryKey")),
        }
    )


def _index_state_from_meta(index_meta: Any) -> dict[str, Any]:
    return _compact_mapping(
        {
            "properties": index_meta.properties,
            "unique": getattr(index_meta, "unique", False),
            "type": getattr(index_meta, "type", None),
            "primary_key": getattr(index_meta, "primary_key", False),
        }
    )


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


def _collect_live_schema_state(runtime: Any, classname: str) -> SchemaState:
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
            map_state["data"] = _collect_runtime_state_mapping(
                runtime,
                item,
                "Data",
                STORAGE_SQL_MAP_DATA_KEYS,
            )
            map_state["row_id_specs"] = _collect_runtime_state_mapping(
                runtime,
                item,
                "RowIdSpecs",
                STORAGE_SQL_MAP_ROW_ID_SPEC_KEYS,
            )
            map_state["subscripts"] = {}

            for sub_item in _iter_runtime_list(
                runtime,
                _safe_get_property(runtime, item, "Subscripts"),
            ):
                sub_name = _safe_get_property(runtime, sub_item, "Name")
                if not sub_name:
                    continue
                sub_state = _runtime_state_from_item(
                    runtime,
                    sub_item,
                    STORAGE_SQL_MAP_SUB_KEYS,
                )
                sub_state["access_vars"] = _collect_runtime_state_mapping(
                    runtime,
                    sub_item,
                    "Accessvars",
                    STORAGE_SQL_MAP_SUB_ACCESS_VAR_KEYS,
                )
                sub_state["invalid_conditions"] = _collect_runtime_state_mapping(
                    runtime,
                    sub_item,
                    "Invalidconditions",
                    STORAGE_SQL_MAP_SUB_INVALID_CONDITION_KEYS,
                )
                map_state["subscripts"][str(sub_name)] = sub_state
            map_state["subscripts"] = _sort_mapping(map_state["subscripts"])
            storage_state["sql_maps"][str(name)] = map_state
        storage_state["sql_maps"] = _sort_mapping(storage_state["sql_maps"])
        state["storage"] = storage_state

    return SchemaState.from_dict(state)


def _merge_schema_state_for_sync(
    *,
    mode: str,
    live_state: SchemaState | dict[str, Any],
    desired_state: SchemaState | dict[str, Any],
) -> SchemaState:
    live_mapping = _state_to_dict(live_state)
    desired_mapping = _state_to_dict(desired_state)
    if mode == "observe":
        return SchemaState.from_dict(live_mapping)
    if not live_mapping["super"] or mode == "replace":
        return SchemaState.from_dict(desired_mapping)

    planned = deepcopy(live_mapping)
    planned["super"] = desired_mapping["super"]
    for key, value in desired_mapping["metadata"].items():
        if value not in (None, "", False):
            planned["metadata"][key] = value

    if mode == "managed":
        for section in ("parameters", "properties", "indexes"):
            planned[section] = deepcopy(desired_mapping[section])
        if desired_mapping["storage"] is not None:
            planned["storage"] = deepcopy(desired_mapping["storage"])
    else:
        for section in ("parameters", "properties", "indexes"):
            for key, value in desired_mapping[section].items():
                planned[section].setdefault(key, value)
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

    if isinstance(py_type, type):
        mapped = PYTHON_TO_IRIS_TYPE.get(py_type)
        if mapped is not None:
            return mapped
        if issubclass(py_type, iris_persistence.models.Model):
            return _schema_classname_for_save(py_type._classname)

    return "%Library.String"


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
    if op_type in {"delete_parameter", "delete_property", "delete_index", "delete_storage"}:
        return "destructive"
    if op_type in {"add_storage", "replace_storage"}:
        return "manual-review"
    if before in (None, {}, []) and after not in (None, {}, []):
        return "safe"
    if op_type in {"update_property", "update_index", "update_super"}:
        return "manual-review"
    if before not in (None, {}, []) and after not in (None, {}, []) and before != after:
        return "manual-review"
    return "safe"


def _operation_type(path: str, before: Any, after: Any) -> str:
    if path == "class":
        return "create_class" if before in (None, {}, []) else "update_class"
    if path == "super":
        return "update_super"
    if path.startswith("metadata."):
        return "update_class_metadata"
    if path.startswith("parameters."):
        if before in (None, {}, []):
            return "add_parameter"
        if after in (None, {}, []):
            return "delete_parameter"
        return "update_parameter"
    if path.startswith("properties."):
        if before in (None, {}, []):
            return "add_property"
        if after in (None, {}, []):
            return "delete_property"
        return "update_property"
    if path.startswith("indexes."):
        if before in (None, {}, []):
            return "add_index"
        if after in (None, {}, []):
            return "delete_index"
        return "update_index"
    if path == "storage" or path.startswith("storage."):
        if before in (None, {}, []):
            return "add_storage"
        if after in (None, {}, []):
            return "delete_storage"
        return "replace_storage"
    return "update_schema"


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


def diff_schema(model_cls: Type[Any]) -> SchemaDiff:
    runtime = get_runtime()
    classname = getattr(model_cls, "_classname", model_cls.__name__)
    mode = getattr(model_cls, "_sync_mode", iris_persistence.models.DEFAULT_SYNC_MODE)
    live_state = _collect_live_schema_state(runtime, classname)
    desired_state = _collect_model_schema_state(model_cls)
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


def _set_runtime_property_exact(
    runtime: Any,
    obj: Any,
    prop_name: str,
    value: Any,
) -> None:
    try:
        runtime.set_property(obj, prop_name, "" if value is None else value)
    except AttributeError:
        pass


def _set_runtime_flag_exact(
    runtime: Any,
    obj: Any,
    prop_name: str,
    enabled: Any,
) -> None:
    try:
        runtime.set_property(obj, prop_name, 1 if enabled else 0)
    except AttributeError:
        pass


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


def _ensure_class_definition(
    runtime: Any,
    classname: str,
    mode: str,
) -> tuple[Any, bool, str]:
    existing_classname = _find_existing_classname(runtime, classname)
    schema_classname = existing_classname or _schema_classname_for_save(classname)

    if mode == "replace" and existing_classname is not None:
        runtime.call_classmethod("%SYSTEM.OBJ", "Delete", existing_classname, "-d")
        existing_classname = None
        schema_classname = _schema_classname_for_save(classname)

    if existing_classname is not None:
        return (
            runtime.get_object("%Dictionary.ClassDefinition", existing_classname),
            True,
            existing_classname,
        )

    class_definition = runtime.new_object("%Dictionary.ClassDefinition")
    runtime.set_property(class_definition, "Name", schema_classname)
    return (class_definition, False, schema_classname)


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
    for key in CLASS_METADATA_KEYS:
        value = _mapping_or_attr_value(class_metadata, key)
        property_name = _runtime_property_name(key)
        if key in CLASS_METADATA_FLAG_KEYS:
            _set_runtime_flag_if_true(runtime, class_definition, property_name, value)
        else:
            _set_runtime_property_if_not_none(runtime, class_definition, property_name, value)


def _sync_members(
    runtime: Any,
    class_definition: Any,
    classname: str,
    *,
    list_property: str,
    dictionary_class_name: str,
    desired: dict[str, Any],
    mode: str,
    update: Callable[[Any, Any], None],
    insert: Callable[[str, Any], Any],
) -> None:
    """Sync one kind of owned schema member (parameters, properties, indexes).

    `update(existing_obj, state)` mutates an owned member in managed mode;
    `insert(name, state)` builds a new member definition to append to the list.
    """
    if mode not in {"extend", "managed", "replace"}:
        return

    member_list = runtime.get_property(class_definition, list_property)
    if member_list is None:
        return
    owned_entries = _owned_schema_member_entries(
        runtime,
        member_list,
        classname,
        dictionary_class_name=dictionary_class_name,
    )
    if mode == "managed":
        _remove_owned_schema_member_entries(
            runtime,
            member_list,
            [entry for name, entry in owned_entries.items() if name not in desired],
            dictionary_class_name=dictionary_class_name,
            context=f"{classname}.{list_property}",
        )

    for name, state in desired.items():
        if name in owned_entries:
            if mode == "extend":
                continue
            if mode == "managed":
                update(owned_entries[name][1], state)
                continue
        runtime.invoke_method(member_list, "Insert", insert(name, state))


def _new_parameter_definition(runtime: Any, classname: str, name: str, default: Any) -> Any:
    param_def = _new_schema_member(runtime, "%Dictionary.ParameterDefinition", name, classname)
    runtime.set_property(param_def, "Default", str(default))
    return param_def


def _sync_parameters(
    runtime: Any,
    class_definition: Any,
    classname: str,
    parameters: dict[str, Any],
    mode: str,
) -> None:
    if not isinstance(parameters, dict):
        return
    _sync_members(
        runtime,
        class_definition,
        classname,
        list_property="Parameters",
        dictionary_class_name="%Dictionary.ParameterDefinition",
        desired=parameters,
        mode=mode,
        update=lambda obj, default: runtime.set_property(obj, "Default", str(default)),
        insert=lambda name, default: _new_parameter_definition(
            runtime, classname, name, default
        ),
    )


def _sync_related_models(
    runtime: Any,
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
            _sync_schema_model(runtime, resolved, seen)


def _apply_property_definition_state(
    runtime: Any,
    prop: Any,
    property_state: dict[str, Any],
    *,
    exact: bool,
) -> None:
    _set_runtime_property_if_not_none(runtime, prop, "Type", property_state.get("type"))
    _apply_runtime_state_fields(
        runtime,
        prop,
        property_state,
        flag_fields=_PROPERTY_FLAG_FIELDS,
        value_fields=_PROPERTY_VALUE_FIELDS,
        exact=exact,
    )

    if exact:
        _set_runtime_flag_exact(
            runtime,
            prop,
            "Storable",
            property_state.get("storable") is not False,
        )
    elif property_state.get("storable") is False:
        runtime.set_property(prop, "Storable", 0)

    params = runtime.get_property(prop, "Parameters")
    if params is None:
        return

    for state_key, parameter_name in _PROPERTY_PARAM_FIELDS:
        value = property_state.get(state_key)
        if value is not None:
            runtime.invoke_method(params, "SetAt", str(value), parameter_name)
        elif exact:
            _remove_runtime_parameter(runtime, params, parameter_name)


def _build_property_definition_from_state(
    runtime: Any,
    classname: str,
    field_name: str,
    property_state: dict[str, Any],
) -> Any:
    prop = runtime.new_object("%Dictionary.PropertyDefinition")
    runtime.set_property(prop, "Name", field_name)
    runtime.set_property(prop, "parent", classname)
    _apply_property_definition_state(runtime, prop, property_state, exact=False)
    return prop


def _sync_property_states(
    runtime: Any,
    class_definition: Any,
    classname: str,
    properties: dict[str, dict[str, Any]],
    mode: str,
) -> None:
    _sync_members(
        runtime,
        class_definition,
        classname,
        list_property="Properties",
        dictionary_class_name="%Dictionary.PropertyDefinition",
        desired=properties,
        mode=mode,
        update=lambda obj, state: _apply_property_definition_state(
            runtime, obj, state, exact=True
        ),
        insert=lambda name, state: _build_property_definition_from_state(
            runtime, classname, name, state
        ),
    )


def _sync_properties(
    runtime: Any,
    class_definition: Any,
    classname: str,
    model_fields: dict[str, Any],
    mode: str,
) -> None:
    desired = {
        field_name: _collect_model_schema_state_for_field(field_name, model_field)
        for field_name, model_field in model_fields.items()
    }
    _sync_property_states(runtime, class_definition, classname, desired, mode)


def _sync_properties_from_state(
    runtime: Any,
    class_definition: Any,
    classname: str,
    properties: dict[str, dict[str, Any]],
) -> None:
    _sync_property_states(
        runtime,
        class_definition,
        classname,
        dict(sorted(properties.items())),
        "replace",
    )


def _apply_index_definition_state(
    runtime: Any,
    idx_def: Any,
    index_state: dict[str, Any],
    *,
    exact: bool,
) -> None:
    _apply_runtime_state_fields(
        runtime,
        idx_def,
        index_state,
        flag_fields=(("unique", "Unique"), ("primary_key", "PrimaryKey")),
        value_fields=(("properties", "Properties"), ("type", "Type")),
        exact=exact,
        exact_values=False,
    )


def _build_index_definition_from_state(
    runtime: Any,
    classname: str,
    index_name: str,
    index_state: dict[str, Any],
) -> Any:
    idx_def = _new_schema_member(runtime, "%Dictionary.IndexDefinition", index_name, classname)
    _apply_index_definition_state(runtime, idx_def, index_state, exact=False)
    return idx_def


def _sync_index_states(
    runtime: Any,
    class_definition: Any,
    classname: str,
    indexes: dict[str, dict[str, Any]],
    mode: str,
) -> None:
    _sync_members(
        runtime,
        class_definition,
        classname,
        list_property="Indices",
        dictionary_class_name="%Dictionary.IndexDefinition",
        desired=indexes,
        mode=mode,
        update=lambda obj, state: _apply_index_definition_state(runtime, obj, state, exact=True),
        insert=lambda name, state: _build_index_definition_from_state(
            runtime, classname, name, state
        ),
    )


def _sync_indexes(
    runtime: Any,
    class_definition: Any,
    classname: str,
    indexes: list[Any],
    mode: str,
) -> None:
    if not isinstance(indexes, list):
        return
    desired = {index_meta.name: _index_state_from_meta(index_meta) for index_meta in indexes}
    _sync_index_states(runtime, class_definition, classname, desired, mode)


def _sync_indexes_from_state(
    runtime: Any,
    class_definition: Any,
    classname: str,
    indexes: dict[str, dict[str, Any]],
) -> None:
    _sync_index_states(
        runtime,
        class_definition,
        classname,
        dict(sorted(indexes.items())),
        "replace",
    )


_STORAGE_BOOL_ATTRS = {"bias_queries_as_outlier", "conditional_with_host_vars"}


def _apply_state_attrs(
    runtime: Any,
    obj: Any,
    meta: Any,
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        value = getattr(meta, key, None)
        property_name = _runtime_property_name(key)
        if key in _STORAGE_BOOL_ATTRS and value is not None:
            runtime.set_property(obj, property_name, 1 if value else 0)
        else:
            _set_runtime_property_if_not_none(runtime, obj, property_name, value)


def _new_schema_member(
    runtime: Any,
    dictionary_class: str,
    name: Any,
    parent: str,
) -> Any:
    obj = runtime.new_object(dictionary_class)
    runtime.set_property(obj, "Name", name)
    runtime.set_property(obj, "parent", parent)
    return obj


def _insert_schema_members(
    runtime: Any,
    target_list: Any,
    dictionary_class: str,
    parent: str,
    items: Any,
    keys: tuple[str, ...],
) -> None:
    for meta in items or ():
        obj = _new_schema_member(runtime, dictionary_class, meta.name, parent)
        _apply_state_attrs(runtime, obj, meta, keys)
        runtime.invoke_method(target_list, "Insert", obj)


def _insert_storage_data(
    runtime: Any,
    storage_definition: Any,
    classname: str,
    storage_name: str,
    storage_meta: Any,
) -> None:
    parent = f"{classname}||{storage_name}"
    data_list = runtime.get_property(storage_definition, "Data")
    for data_meta in getattr(storage_meta, "data", []) or ():
        data_definition = _new_schema_member(
            runtime, "%Dictionary.StorageDataDefinition", data_meta.name, parent
        )
        _apply_state_attrs(runtime, data_definition, data_meta, STORAGE_DATA_KEYS)

        value_list = runtime.get_property(data_definition, "Values")
        for key, value in (getattr(data_meta, "values", None) or {}).items():
            value_definition = _new_schema_member(
                runtime,
                "%Dictionary.StorageDataValueDefinition",
                str(key),
                f"{parent}||{data_meta.name}",
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
    _insert_schema_members(
        runtime,
        runtime.get_property(storage_definition, "Indices"),
        "%Dictionary.StorageIndexDefinition",
        f"{classname}||{storage_name}",
        getattr(storage_meta, "indices", ()) or (),
        STORAGE_INDEX_KEYS,
    )


def _insert_storage_properties(
    runtime: Any,
    storage_definition: Any,
    classname: str,
    storage_name: str,
    storage_meta: Any,
) -> None:
    _insert_schema_members(
        runtime,
        runtime.get_property(storage_definition, "Properties"),
        "%Dictionary.StoragePropertyDefinition",
        f"{classname}||{storage_name}",
        getattr(storage_meta, "properties", []) or (),
        STORAGE_PROPERTY_KEYS,
    )


def _insert_storage_sql_maps(
    runtime: Any,
    storage_definition: Any,
    classname: str,
    storage_name: str,
    storage_meta: Any,
) -> None:
    parent = f"{classname}||{storage_name}"
    sql_maps_list = runtime.get_property(storage_definition, "SQLMaps")
    for sql_map_meta in getattr(storage_meta, "sql_maps", []) or ():
        sql_map = _new_schema_member(
            runtime, "%Dictionary.StorageSQLMapDefinition", sql_map_meta.name, parent
        )
        _apply_state_attrs(runtime, sql_map, sql_map_meta, STORAGE_SQL_MAP_KEYS)
        sql_map_parent = f"{parent}||{sql_map_meta.name}"

        _insert_schema_members(
            runtime,
            runtime.get_property(sql_map, "Data"),
            "%Dictionary.StorageSQLMapDataDefinition",
            sql_map_parent,
            getattr(sql_map_meta, "data", ()) or (),
            STORAGE_SQL_MAP_DATA_KEYS,
        )
        _insert_schema_members(
            runtime,
            runtime.get_property(sql_map, "RowIdSpecs"),
            "%Dictionary.StorageSQLMapRowIdSpecDefinition",
            sql_map_parent,
            getattr(sql_map_meta, "row_id_specs", ()) or (),
            STORAGE_SQL_MAP_ROW_ID_SPEC_KEYS,
        )

        subscript_list = runtime.get_property(sql_map, "Subscripts")
        for sub_meta in getattr(sql_map_meta, "subscripts", ()) or ():
            subscript = _new_schema_member(
                runtime, "%Dictionary.StorageSQLMapSubDefinition", sub_meta.name, sql_map_parent
            )
            _apply_state_attrs(runtime, subscript, sub_meta, STORAGE_SQL_MAP_SUB_KEYS)
            sub_parent = f"{sql_map_parent}||{sub_meta.name}"
            _insert_schema_members(
                runtime,
                runtime.get_property(subscript, "Accessvars"),
                "%Dictionary.StorageSQLMapSubAccessvarDefinition",
                sub_parent,
                getattr(sub_meta, "access_vars", ()) or (),
                STORAGE_SQL_MAP_SUB_ACCESS_VAR_KEYS,
            )
            _insert_schema_members(
                runtime,
                runtime.get_property(subscript, "Invalidconditions"),
                "%Dictionary.StorageSQLMapSubInvalidconditionDefinition",
                sub_parent,
                getattr(sub_meta, "invalid_conditions", ()) or (),
                STORAGE_SQL_MAP_SUB_INVALID_CONDITION_KEYS,
            )
            runtime.invoke_method(subscript_list, "Insert", subscript)

        runtime.invoke_method(sql_maps_list, "Insert", sql_map)


def _sync_storage(
    runtime: Any,
    class_definition: Any,
    classname: str,
    storage_meta: Any,
    mode: str,
) -> None:
    if not storage_meta or mode not in {"managed", "replace"}:
        return

    storage_list = runtime.get_property(class_definition, "Storages")
    if storage_list is None:
        return
    if mode == "managed":
        owned_entries = _owned_schema_member_entries(
            runtime,
            storage_list,
            classname,
            skip_system_names=False,
        )
        _remove_runtime_list_indices(
            runtime,
            storage_list,
            [entry[0] for entry in owned_entries.values()],
            context=f"{classname}.Storages",
        )
    storage_definition = runtime.new_object("%Dictionary.StorageDefinition")
    storage_name = getattr(storage_meta, "name", None) or "CustomStorage"
    runtime.set_property(storage_definition, "Name", storage_name)
    runtime.set_property(storage_definition, "parent", classname)
    runtime.set_property(class_definition, "StorageStrategy", storage_name)

    _apply_state_attrs(runtime, storage_definition, storage_meta, STORAGE_KEYS)
    _insert_storage_data(runtime, storage_definition, classname, storage_name, storage_meta)
    _insert_storage_indices(runtime, storage_definition, classname, storage_name, storage_meta)
    _insert_storage_properties(runtime, storage_definition, classname, storage_name, storage_meta)
    _insert_storage_sql_maps(runtime, storage_definition, classname, storage_name, storage_meta)

    runtime.invoke_method(storage_list, "Insert", storage_definition)


def _namespace_items(mapping: dict[str, dict[str, Any]]) -> tuple[Any, ...]:
    return tuple(
        SimpleNamespace(name=name, **deepcopy(values))
        for name, values in sorted(mapping.items(), key=lambda item: item[0])
    )


def _storage_meta_from_state(storage_state: dict[str, Any] | None) -> Any:
    if storage_state is None:
        return None

    attrs = deepcopy(storage_state.get("attrs", {}))
    data = _namespace_items(storage_state.get("data", {}))
    indices = _namespace_items(storage_state.get("indices", {}))
    properties = _namespace_items(storage_state.get("properties", {}))
    sql_maps = []
    for map_name, map_state in sorted(
        (storage_state.get("sql_maps") or {}).items(),
        key=lambda item: item[0],
    ):
        map_attrs = deepcopy(map_state)
        map_attrs["data"] = _namespace_items(map_attrs.pop("data", {}))
        map_attrs["row_id_specs"] = _namespace_items(map_attrs.pop("row_id_specs", {}))
        subscripts = []
        for sub_name, sub_state in sorted(
            (map_attrs.pop("subscripts", {}) or {}).items(),
            key=lambda item: item[0],
        ):
            sub_attrs = deepcopy(sub_state)
            sub_attrs["access_vars"] = _namespace_items(sub_attrs.pop("access_vars", {}))
            sub_attrs["invalid_conditions"] = _namespace_items(
                sub_attrs.pop("invalid_conditions", {})
            )
            subscripts.append(SimpleNamespace(name=sub_name, **sub_attrs))
        map_attrs["subscripts"] = tuple(subscripts)
        sql_maps.append(SimpleNamespace(name=map_name, **map_attrs))

    return SimpleNamespace(
        name=storage_state.get("name"),
        **attrs,
        data=data,
        indices=indices,
        properties=properties,
        sql_maps=tuple(sql_maps),
    )


def _save_and_compile_schema_class(
    runtime: Any,
    class_definition: Any,
    schema_classname: str,
) -> None:
    st = runtime.save_object(class_definition)
    if not runtime.is_ok(st):
        raise RuntimeError(
            f"Schema save failed for {schema_classname}: {runtime.format_status(st)}"
        )

    compile_status = runtime.call_classmethod(
        "%SYSTEM.OBJ",
        "Compile",
        schema_classname,
        "fc /display=none",
    )
    if not runtime.is_ok(compile_status):
        raise RuntimeError(
            f"Schema compile failed for {schema_classname}: "
            f"{runtime.format_status(compile_status)}"
        )


def _sync_schema_state(runtime: Any, state: SchemaState | dict[str, Any]) -> None:
    state = SchemaState.from_dict(_state_to_dict(state))
    if not state.superclasses:
        return

    cd, _exists, schema_classname = _ensure_class_definition(runtime, state.classname, "replace")
    _apply_class_definition(runtime, cd, schema_classname, state.superclasses, state.metadata)
    _sync_parameters(runtime, cd, schema_classname, state.parameters, "replace")
    _sync_properties_from_state(runtime, cd, schema_classname, state.properties)
    _sync_indexes_from_state(runtime, cd, schema_classname, state.indexes)
    _sync_storage(runtime, cd, schema_classname, _storage_meta_from_state(state.storage), "replace")
    _save_and_compile_schema_class(runtime, cd, schema_classname)


def _run_with_schema_transaction(runtime: Any, action: Callable[[], Any]) -> Any:
    begin_transaction = getattr(runtime, "begin_transaction", None)
    commit_transaction = getattr(runtime, "commit_transaction", None)
    rollback_transaction = getattr(runtime, "rollback_transaction", None)
    if not (
        callable(begin_transaction)
        and callable(commit_transaction)
        and callable(rollback_transaction)
    ):
        return action()

    begin_transaction()
    try:
        result = action()
    except Exception:
        try:
            rollback_transaction()
        except Exception:
            pass
        raise

    try:
        commit_transaction()
    except Exception:
        try:
            rollback_transaction()
        except Exception:
            pass
        raise
    return result


def _sync_schema_model(
    runtime: Any,
    model_cls: Type[Any],
    seen: set[str],
) -> None:
    mode = getattr(model_cls, "_sync_mode", iris_persistence.models.DEFAULT_SYNC_MODE)
    if mode == "observe":
        return

    classname = getattr(model_cls, "_classname", model_cls.__name__)
    schema_classname = _schema_classname_for_save(classname)
    superclasses = getattr(model_cls, "_superclasses", "%Persistent")
    existing_classname = _find_existing_classname(runtime, classname)
    if existing_classname is not None:
        schema_classname = existing_classname

    if schema_classname in seen:
        return
    seen.add(schema_classname)

    cd, _exists, schema_classname = _ensure_class_definition(runtime, classname, mode)
    class_metadata = getattr(model_cls, "_class_metadata", None)
    _apply_class_definition(runtime, cd, schema_classname, superclasses, class_metadata)

    parameters = getattr(model_cls, "_parameters", {}) or {}
    _sync_parameters(runtime, cd, schema_classname, parameters, mode)

    model_fields = getattr(model_cls, "__model_fields__", {})
    _sync_related_models(runtime, model_cls, model_fields, seen)
    _sync_properties(runtime, cd, schema_classname, model_fields, mode)

    indexes = getattr(model_cls, "_indexes", [])
    _sync_indexes(runtime, cd, schema_classname, indexes, mode)

    storage_meta = getattr(model_cls, "_storage", None)
    _sync_storage(runtime, cd, schema_classname, storage_meta, mode)
    _save_and_compile_schema_class(runtime, cd, schema_classname)


def sync_schema(model_cls: Type[Any], _seen: set[str] | None = None) -> None:
    if getattr(model_cls, "_sync_mode", iris_persistence.models.DEFAULT_SYNC_MODE) == "observe":
        return

    runtime = get_runtime()
    if _seen is not None:
        _sync_schema_model(runtime, model_cls, _seen)
        return

    _run_with_schema_transaction(runtime, lambda: _sync_schema_model(runtime, model_cls, set()))
