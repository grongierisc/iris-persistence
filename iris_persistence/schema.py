from __future__ import annotations

import decimal
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from difflib import unified_diff
from types import SimpleNamespace
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
    "scale",
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


def _owned_schema_member_indices(
    runtime: Any,
    list_obj: Any,
    classname: str,
    *,
    skip_system_names: bool = True,
) -> tuple[list[int], set[str]]:
    indices: list[int] = []
    names: set[str] = set()
    for index, item in _iter_runtime_list_with_indices(runtime, list_obj):
        name = _safe_get_property(runtime, item, "Name")
        if not name:
            continue
        name = str(name)
        if skip_system_names and (name.startswith("%") or name == "GUID"):
            continue
        if not _item_belongs_to_class(runtime, item, classname):
            continue
        indices.append(index)
        names.add(name)
    return indices, names


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
        if skip_system_names and (name.startswith("%") or name == "GUID"):
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
        if skip_system_names and (name.startswith("%") or name == "GUID"):
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
        return not _coerce_bool(inherited)

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


def _compact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    compact = {}
    for key, value in mapping.items():
        if value in (None, "", False):
            continue
        compact[key] = value
    return compact


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
    return _compact_mapping(
        {
            "type": iris_type,
            "required": getattr(field_meta, "required", False),
            "readonly": getattr(field_meta, "readonly", False),
            "collection": getattr(field_meta, "collection", None),
            "sql_field_name": getattr(field_meta, "sql_field_name", None),
            "identity": getattr(field_meta, "identity", False),
            "relationship": getattr(field_meta, "relationship", None),
            "on_delete": getattr(field_meta, "on_delete", None),
            "inverse": getattr(field_meta, "inverse", None),
            "transient": getattr(field_meta, "transient", False),
            "storable": (False if getattr(field_meta, "storable", True) is False else None),
            "multi_dimensional": getattr(field_meta, "multi_dimensional", False),
            "sql_list_delimiter": getattr(field_meta, "sql_list_delimiter", None),
            "sql_list_type": getattr(field_meta, "sql_list_type", None),
            "sql_compute_code": getattr(field_meta, "sql_compute_code", None),
            "sql_compute_on_change": getattr(field_meta, "sql_compute_on_change", None),
            "sql_computed": getattr(field_meta, "sql_computed", False),
            "initial_expression": _field_initial_expression(field_meta),
            "max_length": getattr(field_meta, "max_length", None),
            "scale": _decimal_scale_for_field(py_type, iris_type),
        }
    )


def _collect_model_schema_state(model_cls: Type[Any]) -> SchemaState:
    classname = _schema_classname_for_save(getattr(model_cls, "_classname", model_cls.__name__))
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
        properties[field_name] = _collect_model_schema_state_for_field(field_name, model_field)
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
        storage_state = _empty_storage_state()
        storage_state["name"] = "CustomStorage"
        storage_state["attrs"] = _compact_mapping(
            {key: getattr(storage_meta, key, None) for key in STORAGE_KEYS}
        )
        storage_state["data"] = _sort_mapping(
            {
                item.name: _compact_mapping(
                    {
                        "structure": getattr(item, "structure", None),
                        "attribute": getattr(item, "attribute", None),
                        "subscript": getattr(item, "subscript", None),
                        "values": _normalize_values_mapping(getattr(item, "values", None)),
                    }
                )
                for item in getattr(storage_meta, "data", ()) or ()
            }
        )
        storage_state["indices"] = _sort_mapping(
            {
                item.name: _compact_mapping(
                    {key: getattr(item, key, None) for key in STORAGE_INDEX_KEYS}
                )
                for item in getattr(storage_meta, "indices", ()) or ()
            }
        )
        storage_state["properties"] = _sort_mapping(
            {
                item.name: _compact_mapping(
                    {key: getattr(item, key, None) for key in STORAGE_PROPERTY_KEYS}
                )
                for item in getattr(storage_meta, "properties", ()) or ()
            }
        )
        storage_state["sql_maps"] = _sort_mapping(
            {
                item.name: _compact_mapping(
                    {
                        **{key: getattr(item, key, None) for key in STORAGE_SQL_MAP_KEYS},
                        "data": _sort_mapping(
                            {
                                child.name: _compact_mapping(
                                    {
                                        key: getattr(child, key, None)
                                        for key in STORAGE_SQL_MAP_DATA_KEYS
                                    }
                                )
                                for child in (getattr(item, "data", None) or ())
                            }
                        ),
                        "row_id_specs": _sort_mapping(
                            {
                                child.name: _compact_mapping(
                                    {
                                        key: getattr(child, key, None)
                                        for key in STORAGE_SQL_MAP_ROW_ID_SPEC_KEYS
                                    }
                                )
                                for child in getattr(item, "row_id_specs", ()) or ()
                            }
                        ),
                        "subscripts": _sort_mapping(
                            {
                                child.name: _compact_mapping(
                                    {
                                        **{
                                            key: getattr(child, key, None)
                                            for key in STORAGE_SQL_MAP_SUB_KEYS
                                        },
                                        "access_vars": _sort_mapping(
                                            {
                                                nested.name: _compact_mapping(
                                                    {
                                                        key: getattr(nested, key, None)
                                                        for key in (
                                                            STORAGE_SQL_MAP_SUB_ACCESS_VAR_KEYS
                                                        )
                                                    }
                                                )
                                                for nested in (
                                                    getattr(child, "access_vars", ()) or ()
                                                )
                                            }
                                        ),
                                        "invalid_conditions": _sort_mapping(
                                            {
                                                nested.name: _compact_mapping(
                                                    {
                                                        key: getattr(nested, key, None)
                                                        for key in (
                                                            STORAGE_SQL_MAP_SUB_INVALID_CONDITION_KEYS
                                                        )
                                                    }
                                                )
                                                for nested in (
                                                    getattr(child, "invalid_conditions", ()) or ()
                                                )
                                            }
                                        ),
                                    }
                                )
                                for child in getattr(item, "subscripts", ()) or ()
                            }
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
        if not name or str(name).startswith("%") or str(name) == "GUID":
            continue
        parameters[str(name)] = str(_row_value(row, "Default"))
    return parameters


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
        max_length = _row_value(row, "MAXLEN")
        scale = _row_value(row, "SCALE")
        properties[str(name)] = _compact_mapping(
            {
                "type": _row_value(row, "Type"),
                "required": _coerce_bool(_row_value(row, "Required")),
                "readonly": _coerce_bool(_row_value(row, "ReadOnly")),
                "collection": _row_value(row, "Collection"),
                "sql_field_name": _row_value(row, "SqlFieldName"),
                "identity": _coerce_bool(_row_value(row, "Identity")),
                "relationship": _row_value(row, "Relationship"),
                "on_delete": _row_value(row, "OnDelete"),
                "inverse": _row_value(row, "Inverse"),
                "transient": _coerce_bool(_row_value(row, "Transient")),
                "storable": False if _row_value(row, "Storable") in (0, "0", False) else None,
                "multi_dimensional": _coerce_bool(_row_value(row, "MultiDimensional")),
                "sql_list_delimiter": _row_value(row, "SqlListDelimiter"),
                "sql_list_type": _row_value(row, "SqlListType"),
                "sql_compute_code": _row_value(row, "SqlComputeCode"),
                "sql_compute_on_change": _row_value(row, "SqlComputeOnChange"),
                "sql_computed": _coerce_bool(_row_value(row, "SqlComputed")),
                "initial_expression": _row_value(row, "InitialExpression"),
                "max_length": str(max_length) if max_length not in (None, "") else None,
                "scale": str(scale) if scale not in (None, "") else None,
            }
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
        indexes[str(name)] = _compact_mapping(
            {
                "properties": _row_value(row, "Properties"),
                "unique": _coerce_bool(_row_value(row, "Unique")),
                "type": _row_value(row, "Type"),
                "primary_key": _coerce_bool(_row_value(row, "PrimaryKey")),
            }
        )
    return indexes


def _collect_live_schema_state(runtime: Any, classname: str) -> SchemaState:
    state = _empty_schema_state(_schema_classname_for_save(classname))
    existing_classname = _find_existing_classname(runtime, classname)
    if existing_classname is None:
        return SchemaState.from_dict(state)

    state["classname"] = existing_classname
    class_def = runtime.get_object("%Dictionary.ClassDefinition", existing_classname)
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
        if not _item_belongs_to_class(runtime, item, existing_classname):
            continue
        parameters[str(name)] = str(_safe_get_property(runtime, item, "Default"))
    state["parameters"] = parameters
    for name, parameter in _collect_live_parameters_from_sql(runtime, existing_classname).items():
        state["parameters"].setdefault(name, parameter)

    properties = {}
    for item in _iter_runtime_list(runtime, _safe_get_property(runtime, class_def, "Properties")):
        name = _safe_get_property(runtime, item, "Name")
        if not name or str(name).startswith("%"):
            continue
        if not _item_belongs_to_class(runtime, item, existing_classname):
            continue
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
                "scale": str(scale) if scale not in (None, "") else None,
            }
        )
    state["properties"] = properties
    for name, property_state in _collect_live_properties_from_sql(
        runtime,
        existing_classname,
    ).items():
        state["properties"].setdefault(name, property_state)

    indexes = {}
    for item in _iter_runtime_list(runtime, _safe_get_property(runtime, class_def, "Indices")):
        name = _safe_get_property(runtime, item, "Name")
        if not name:
            continue
        if not _item_belongs_to_class(runtime, item, existing_classname):
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
    for name, index_state in _collect_live_indexes_from_sql(runtime, existing_classname).items():
        state["indexes"].setdefault(name, index_state)

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
        storage_state["attrs"] = _compact_mapping(
            {
                key: _safe_get_property(
                    runtime,
                    selected_storage,
                    "".join(part.capitalize() for part in key.split("_")),
                )
                for key in STORAGE_KEYS
            }
        )
        storage_data = _safe_get_property(runtime, selected_storage, "Data")
        for item in _iter_runtime_list(runtime, storage_data):
            name = _safe_get_property(runtime, item, "Name")
            if not name:
                continue
            values = {}
            value_items = _safe_get_property(runtime, item, "Values")
            for value_item in _iter_runtime_list(runtime, value_items):
                value_name = _safe_get_property(runtime, value_item, "Name")
                if value_name in (None, ""):
                    continue
                values[str(value_name)] = str(_safe_get_property(runtime, value_item, "Value"))
            storage_state["data"][str(name)] = _compact_mapping(
                {
                    "structure": _safe_get_property(runtime, item, "Structure"),
                    "attribute": _safe_get_property(runtime, item, "Attribute"),
                    "subscript": _safe_get_property(runtime, item, "Subscript"),
                    "values": _normalize_values_mapping(values),
                }
            )
        storage_state["data"] = _sort_mapping(storage_state["data"])

        storage_indices = _safe_get_property(runtime, selected_storage, "Indices")
        for item in _iter_runtime_list(runtime, storage_indices):
            name = _safe_get_property(runtime, item, "Name")
            if not name:
                continue
            storage_state["indices"][str(name)] = _compact_mapping(
                {
                    "location": _safe_get_property(runtime, item, "Location"),
                    "small_chunk_size": _safe_get_property(runtime, item, "SmallChunkSize"),
                }
            )
        storage_state["indices"] = _sort_mapping(storage_state["indices"])

        storage_properties = _safe_get_property(runtime, selected_storage, "Properties")
        for item in _iter_runtime_list(runtime, storage_properties):
            name = _safe_get_property(runtime, item, "Name")
            if not name:
                continue
            storage_state["properties"][str(name)] = _compact_mapping(
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
        storage_state["properties"] = _sort_mapping(storage_state["properties"])

        storage_sql_maps = _safe_get_property(runtime, selected_storage, "SQLMaps")
        for item in _iter_runtime_list(runtime, storage_sql_maps):
            name = _safe_get_property(runtime, item, "Name")
            if not name:
                continue
            map_state = _compact_mapping(
                {
                    "block_count": _safe_get_property(runtime, item, "BlockCount"),
                    "condition": _safe_get_property(runtime, item, "Condition"),
                    "condition_fields": _safe_get_property(runtime, item, "ConditionFields"),
                    "conditional_with_host_vars": _coerce_bool(
                        _safe_get_property(runtime, item, "ConditionalWithHostVars")
                    ),
                    "global_name": _safe_get_property(runtime, item, "Global"),
                    "population_pct": _safe_get_property(runtime, item, "PopulationPct"),
                    "population_type": _safe_get_property(runtime, item, "PopulationType"),
                    "row_reference": _safe_get_property(runtime, item, "RowReference"),
                    "structure": _safe_get_property(runtime, item, "Structure"),
                    "type": _safe_get_property(runtime, item, "Type"),
                    "data": {},
                    "row_id_specs": {},
                    "subscripts": {},
                }
            )
            data_items = _safe_get_property(runtime, item, "Data")
            for data_item in _iter_runtime_list(runtime, data_items):
                data_name = _safe_get_property(runtime, data_item, "Name")
                if not data_name:
                    continue
                map_state["data"][str(data_name)] = _compact_mapping(
                    {
                        "node": _safe_get_property(runtime, data_item, "Node"),
                        "piece": _safe_get_property(runtime, data_item, "Piece"),
                        "delimiter": _safe_get_property(runtime, data_item, "Delimiter"),
                        "retrieval_code": _safe_get_property(runtime, data_item, "RetrievalCode"),
                    }
                )
            map_state["data"] = _sort_mapping(map_state["data"])

            row_id_spec_items = _safe_get_property(runtime, item, "RowIdSpecs")
            for spec_item in _iter_runtime_list(runtime, row_id_spec_items):
                spec_name = _safe_get_property(runtime, spec_item, "Name")
                if not spec_name:
                    continue
                map_state["row_id_specs"][str(spec_name)] = _compact_mapping(
                    {
                        "field": _safe_get_property(runtime, spec_item, "Field"),
                        "expression": _safe_get_property(runtime, spec_item, "Expression"),
                    }
                )
            map_state["row_id_specs"] = _sort_mapping(map_state["row_id_specs"])

            subscript_items = _safe_get_property(runtime, item, "Subscripts")
            for sub_item in _iter_runtime_list(runtime, subscript_items):
                sub_name = _safe_get_property(runtime, sub_item, "Name")
                if not sub_name:
                    continue
                sub_state = _compact_mapping(
                    {
                        "access_type": _safe_get_property(runtime, sub_item, "AccessType"),
                        "data_access": _safe_get_property(runtime, sub_item, "DataAccess"),
                        "delimiter": _safe_get_property(runtime, sub_item, "Delimiter"),
                        "expression": _safe_get_property(runtime, sub_item, "Expression"),
                        "loop_init_value": _safe_get_property(runtime, sub_item, "LoopInitValue"),
                        "next_code": _safe_get_property(runtime, sub_item, "NextCode"),
                        "null_marker": _safe_get_property(runtime, sub_item, "NullMarker"),
                        "start_value": _safe_get_property(runtime, sub_item, "StartValue"),
                        "stop_expression": _safe_get_property(runtime, sub_item, "StopExpression"),
                        "stop_value": _safe_get_property(runtime, sub_item, "StopValue"),
                        "access_vars": {},
                        "invalid_conditions": {},
                    }
                )
                access_var_items = _safe_get_property(runtime, sub_item, "Accessvars")
                for access_item in _iter_runtime_list(runtime, access_var_items):
                    access_name = _safe_get_property(runtime, access_item, "Name")
                    if not access_name:
                        continue
                    sub_state["access_vars"][str(access_name)] = _compact_mapping(
                        {
                            "variable": _safe_get_property(runtime, access_item, "Variable"),
                            "code": _safe_get_property(runtime, access_item, "Code"),
                        }
                    )
                sub_state["access_vars"] = _sort_mapping(sub_state["access_vars"])
                invalid_items = _safe_get_property(runtime, sub_item, "Invalidconditions")
                for invalid_item in _iter_runtime_list(runtime, invalid_items):
                    invalid_name = _safe_get_property(runtime, invalid_item, "Name")
                    if not invalid_name:
                        continue
                    sub_state["invalid_conditions"][str(invalid_name)] = _compact_mapping(
                        {
                            "expression": _safe_get_property(runtime, invalid_item, "Expression"),
                        }
                    )
                sub_state["invalid_conditions"] = _sort_mapping(
                    sub_state["invalid_conditions"]
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
    if mode == "managed":
        planned = deepcopy(live_mapping)
        planned["super"] = desired_mapping["super"]
        for key, value in desired_mapping["metadata"].items():
            if value not in (None, "", False):
                planned["metadata"][key] = value
        planned["parameters"] = deepcopy(desired_mapping["parameters"])
        planned["properties"] = deepcopy(desired_mapping["properties"])
        planned["indexes"] = deepcopy(desired_mapping["indexes"])
        if desired_mapping["storage"] is not None:
            planned["storage"] = deepcopy(desired_mapping["storage"])
        return SchemaState.from_dict(planned)

    planned = deepcopy(live_mapping)
    planned["super"] = desired_mapping["super"]
    for key, value in desired_mapping["metadata"].items():
        if value not in (None, "", False):
            planned["metadata"][key] = value
    for key, value in desired_mapping["parameters"].items():
        planned["parameters"].setdefault(key, value)
    for key, value in desired_mapping["properties"].items():
        planned["properties"].setdefault(key, value)
    for key, value in desired_mapping["indexes"].items():
        planned["indexes"].setdefault(key, value)
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
        for name in sorted(storage.get("data", {})):
            item = storage["data"][name]
            parts = _render_attribute_parts(STORAGE_DATA_KEYS, item)
            lines.append(f"storage_data {name}" + (f" {parts}" if parts else ""))
            values = item.get("values") or {}
            for value_key in sorted(values, key=str):
                lines.append(
                    f"storage_data_value {name}.{value_key}={_format_value(values[value_key])}"
                )
        for name in sorted(storage.get("indices", {})):
            parts = _render_attribute_parts(STORAGE_INDEX_KEYS, storage["indices"][name])
            lines.append(f"storage_index {name}" + (f" {parts}" if parts else ""))
        for name in sorted(storage["properties"]):
            parts = _render_attribute_parts(STORAGE_PROPERTY_KEYS, storage["properties"][name])
            lines.append(f"storage_property {name}" + (f" {parts}" if parts else ""))
        for name in sorted(storage.get("sql_maps", {})):
            item = storage["sql_maps"][name]
            parts = _render_attribute_parts(STORAGE_SQL_MAP_KEYS, item)
            lines.append(f"storage_sql_map {name}" + (f" {parts}" if parts else ""))
            for data_name in sorted(item.get("data", {})):
                parts = _render_attribute_parts(
                    STORAGE_SQL_MAP_DATA_KEYS,
                    item["data"][data_name],
                )
                lines.append(
                    f"storage_sql_map_data {name}.{data_name}"
                    + (f" {parts}" if parts else "")
                )
            for spec_name in sorted(item.get("row_id_specs", {})):
                parts = _render_attribute_parts(
                    STORAGE_SQL_MAP_ROW_ID_SPEC_KEYS,
                    item["row_id_specs"][spec_name],
                )
                lines.append(
                    f"storage_sql_map_row_id_spec {name}.{spec_name}"
                    + (f" {parts}" if parts else "")
                )
            for sub_name in sorted(item.get("subscripts", {})):
                subscript = item["subscripts"][sub_name]
                parts = _render_attribute_parts(STORAGE_SQL_MAP_SUB_KEYS, subscript)
                lines.append(
                    f"storage_sql_map_subscript {name}.{sub_name}"
                    + (f" {parts}" if parts else "")
                )
                for access_name in sorted(subscript.get("access_vars", {})):
                    parts = _render_attribute_parts(
                        STORAGE_SQL_MAP_SUB_ACCESS_VAR_KEYS,
                        subscript["access_vars"][access_name],
                    )
                    lines.append(
                        f"storage_sql_map_sub_access_var {name}.{sub_name}.{access_name}"
                        + (f" {parts}" if parts else "")
                    )
                for invalid_name in sorted(subscript.get("invalid_conditions", {})):
                    parts = _render_attribute_parts(
                        STORAGE_SQL_MAP_SUB_INVALID_CONDITION_KEYS,
                        subscript["invalid_conditions"][invalid_name],
                    )
                    lines.append(
                        f"storage_sql_map_sub_invalid_condition "
                        f"{name}.{sub_name}.{invalid_name}"
                        + (f" {parts}" if parts else "")
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

    if py_type is str:
        return "%Library.String"
    if py_type is int:
        return "%Library.Integer"
    if py_type is float:
        return "%Library.Double"
    if py_type is decimal.Decimal:
        return "%Library.Decimal"
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
    _diff_mapping_items(
        operations,
        classname=classname,
        prefix="metadata",
        before=before.get("metadata", {}),
        after=after.get("metadata", {}),
        mode=mode,
    )
    _diff_mapping_items(
        operations,
        classname=classname,
        prefix="parameters",
        before=before.get("parameters", {}),
        after=after.get("parameters", {}),
        mode=mode,
    )
    _diff_mapping_items(
        operations,
        classname=classname,
        prefix="properties",
        before=before.get("properties", {}),
        after=after.get("properties", {}),
        mode=mode,
    )
    _diff_mapping_items(
        operations,
        classname=classname,
        prefix="indexes",
        before=before.get("indexes", {}),
        after=after.get("indexes", {}),
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


def _set_property_parameter_if_not_none(
    runtime: Any,
    prop: Any,
    key: str,
    value: Any,
) -> None:
    if value is None:
        return
    params = runtime.get_property(prop, "Parameters")
    if params is not None:
        runtime.invoke_method(params, "SetAt", str(value), key)


def _set_runtime_flag_if_true(runtime: Any, obj: Any, prop_name: str, enabled: Any) -> None:
    if enabled:
        runtime.set_property(obj, prop_name, 1)


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

    class_definition = runtime.create_object("%Dictionary.ClassDefinition")
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
    _set_runtime_property_if_not_none(
        runtime,
        class_definition,
        "Description",
        _mapping_or_attr_value(class_metadata, "description"),
    )
    _set_runtime_flag_if_true(
        runtime,
        class_definition,
        "Deprecated",
        _mapping_or_attr_value(class_metadata, "deprecated"),
    )
    _set_runtime_flag_if_true(
        runtime,
        class_definition,
        "Final",
        _mapping_or_attr_value(class_metadata, "final"),
    )
    _set_runtime_property_if_not_none(
        runtime,
        class_definition,
        "SqlTableName",
        _mapping_or_attr_value(class_metadata, "sql_table_name"),
    )
    _set_runtime_flag_if_true(
        runtime,
        class_definition,
        "ProcedureBlock",
        _mapping_or_attr_value(class_metadata, "procedure_block"),
    )


def _sync_parameters(
    runtime: Any,
    class_definition: Any,
    classname: str,
    parameters: dict[str, Any],
    mode: str,
) -> None:
    if mode not in {"extend", "managed", "replace"} or not isinstance(parameters, dict):
        return

    parameter_list = runtime.get_property(class_definition, "Parameters")
    existing_parameters: set[str] = set()
    if parameter_list is None:
        return
    owned_entries = _owned_schema_member_entries(
        runtime,
        parameter_list,
        classname,
        dictionary_class_name="%Dictionary.ParameterDefinition",
    )
    owned_names = set(owned_entries)
    if mode == "managed":
        desired_names = set(parameters)
        removed_entries = [
            entry
            for name, entry in owned_entries.items()
            if name not in desired_names
        ]
        _remove_owned_schema_member_entries(
            runtime,
            parameter_list,
            removed_entries,
            dictionary_class_name="%Dictionary.ParameterDefinition",
            context=f"{classname}.Parameters",
        )
    elif mode == "extend":
        existing_parameters = owned_names

    for param_name, param_default in parameters.items():
        if mode == "extend" and param_name in existing_parameters:
            continue
        if mode == "managed" and param_name in owned_entries:
            runtime.set_property(owned_entries[param_name][1], "Default", str(param_default))
            continue
        param_def = runtime.create_object("%Dictionary.ParameterDefinition")
        runtime.set_property(param_def, "Name", param_name)
        runtime.set_property(param_def, "parent", classname)
        runtime.set_property(param_def, "Default", str(param_default))
        runtime.invoke_method(parameter_list, "Insert", param_def)


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

    py_type = _resolve_model_type(model_field.declared_type)
    iris_type = _map_python_type_to_iris(py_type, field_meta)
    _set_property_parameter_if_not_none(
        runtime,
        prop,
        "MAXLEN",
        getattr(field_meta, "max_length", None),
    )
    _set_property_parameter_if_not_none(
        runtime,
        prop,
        "SCALE",
        _decimal_scale_for_field(py_type, iris_type),
    )
    return prop


def _build_property_definition_from_state(
    runtime: Any,
    classname: str,
    field_name: str,
    property_state: dict[str, Any],
) -> Any:
    prop = runtime.create_object("%Dictionary.PropertyDefinition")
    runtime.set_property(prop, "Name", field_name)
    runtime.set_property(prop, "parent", classname)
    _set_runtime_property_if_not_none(runtime, prop, "Type", property_state.get("type"))
    _set_runtime_flag_if_true(runtime, prop, "Required", property_state.get("required"))
    _set_runtime_flag_if_true(runtime, prop, "ReadOnly", property_state.get("readonly"))
    _set_runtime_property_if_not_none(runtime, prop, "Collection", property_state.get("collection"))
    _set_runtime_property_if_not_none(
        runtime, prop, "SqlFieldName", property_state.get("sql_field_name")
    )
    _set_runtime_flag_if_true(runtime, prop, "Identity", property_state.get("identity"))
    _set_runtime_property_if_not_none(
        runtime, prop, "Relationship", property_state.get("relationship")
    )
    _set_runtime_property_if_not_none(runtime, prop, "OnDelete", property_state.get("on_delete"))
    _set_runtime_property_if_not_none(runtime, prop, "Inverse", property_state.get("inverse"))
    _set_runtime_flag_if_true(runtime, prop, "Transient", property_state.get("transient"))
    if property_state.get("storable") is False:
        runtime.set_property(prop, "Storable", 0)
    _set_runtime_flag_if_true(
        runtime,
        prop,
        "MultiDimensional",
        property_state.get("multi_dimensional"),
    )
    _set_runtime_property_if_not_none(
        runtime, prop, "SqlListDelimiter", property_state.get("sql_list_delimiter")
    )
    _set_runtime_property_if_not_none(
        runtime, prop, "SqlListType", property_state.get("sql_list_type")
    )
    _set_runtime_property_if_not_none(
        runtime, prop, "SqlComputeCode", property_state.get("sql_compute_code")
    )
    _set_runtime_property_if_not_none(
        runtime,
        prop,
        "SqlComputeOnChange",
        property_state.get("sql_compute_on_change"),
    )
    _set_runtime_flag_if_true(runtime, prop, "SqlComputed", property_state.get("sql_computed"))
    _set_runtime_property_if_not_none(
        runtime,
        prop,
        "InitialExpression",
        property_state.get("initial_expression"),
    )

    _set_property_parameter_if_not_none(runtime, prop, "MAXLEN", property_state.get("max_length"))
    _set_property_parameter_if_not_none(runtime, prop, "SCALE", property_state.get("scale"))
    return prop


def _apply_property_definition_from_state(
    runtime: Any,
    prop: Any,
    property_state: dict[str, Any],
) -> None:
    _set_runtime_property_if_not_none(runtime, prop, "Type", property_state.get("type"))
    _set_runtime_flag_exact(runtime, prop, "Required", property_state.get("required"))
    _set_runtime_flag_exact(runtime, prop, "ReadOnly", property_state.get("readonly"))
    _set_runtime_property_exact(runtime, prop, "Collection", property_state.get("collection"))
    _set_runtime_property_exact(
        runtime, prop, "SqlFieldName", property_state.get("sql_field_name")
    )
    _set_runtime_flag_exact(runtime, prop, "Identity", property_state.get("identity"))
    _set_runtime_property_exact(
        runtime, prop, "Relationship", property_state.get("relationship")
    )
    _set_runtime_property_exact(runtime, prop, "OnDelete", property_state.get("on_delete"))
    _set_runtime_property_exact(runtime, prop, "Inverse", property_state.get("inverse"))
    _set_runtime_flag_exact(runtime, prop, "Transient", property_state.get("transient"))
    _set_runtime_flag_exact(
        runtime,
        prop,
        "Storable",
        property_state.get("storable") is not False,
    )
    _set_runtime_flag_exact(
        runtime,
        prop,
        "MultiDimensional",
        property_state.get("multi_dimensional"),
    )
    _set_runtime_property_exact(
        runtime, prop, "SqlListDelimiter", property_state.get("sql_list_delimiter")
    )
    _set_runtime_property_exact(
        runtime, prop, "SqlListType", property_state.get("sql_list_type")
    )
    _set_runtime_property_exact(
        runtime, prop, "SqlComputeCode", property_state.get("sql_compute_code")
    )
    _set_runtime_property_exact(
        runtime,
        prop,
        "SqlComputeOnChange",
        property_state.get("sql_compute_on_change"),
    )
    _set_runtime_flag_exact(runtime, prop, "SqlComputed", property_state.get("sql_computed"))
    _set_runtime_property_exact(
        runtime,
        prop,
        "InitialExpression",
        property_state.get("initial_expression"),
    )

    max_length = property_state.get("max_length")
    scale = property_state.get("scale")
    params = runtime.get_property(prop, "Parameters")
    if params is not None:
        if max_length is not None:
            runtime.invoke_method(params, "SetAt", str(max_length), "MAXLEN")
        else:
            _remove_runtime_parameter(runtime, params, "MAXLEN")
        if scale is not None:
            runtime.invoke_method(params, "SetAt", str(scale), "SCALE")
        else:
            _remove_runtime_parameter(runtime, params, "SCALE")


def _sync_properties(
    runtime: Any,
    class_definition: Any,
    classname: str,
    model_fields: dict[str, Any],
    mode: str,
) -> None:
    props_oref_list = runtime.get_property(class_definition, "Properties")
    if props_oref_list is None:
        return
    owned_entries = _owned_schema_member_entries(
        runtime,
        props_oref_list,
        classname,
        dictionary_class_name="%Dictionary.PropertyDefinition",
    )
    existing_props = set(owned_entries)
    if mode == "managed":
        desired_names = set(model_fields)
        removed_entries = [
            entry
            for name, entry in owned_entries.items()
            if name not in desired_names
        ]
        _remove_owned_schema_member_entries(
            runtime,
            props_oref_list,
            removed_entries,
            dictionary_class_name="%Dictionary.PropertyDefinition",
            context=f"{classname}.Properties",
        )

    for field_name, model_field in model_fields.items():
        if mode == "extend" and field_name in existing_props:
            continue
        if mode == "managed" and field_name in owned_entries:
            state = _collect_model_schema_state_for_field(field_name, model_field)
            _apply_property_definition_from_state(
                runtime,
                owned_entries[field_name][1],
                state,
            )
            continue
        prop = _build_property_definition(runtime, classname, field_name, model_field)
        runtime.invoke_method(props_oref_list, "Insert", prop)


def _sync_properties_from_state(
    runtime: Any,
    class_definition: Any,
    classname: str,
    properties: dict[str, dict[str, Any]],
) -> None:
    props_oref_list = runtime.get_property(class_definition, "Properties")
    for field_name, property_state in sorted(properties.items(), key=lambda item: item[0]):
        prop = _build_property_definition_from_state(
            runtime,
            classname,
            field_name,
            property_state,
        )
        runtime.invoke_method(props_oref_list, "Insert", prop)


def _sync_indexes(
    runtime: Any,
    class_definition: Any,
    classname: str,
    indexes: list[Any],
    mode: str,
) -> None:
    if mode not in {"extend", "managed", "replace"} or not isinstance(indexes, list):
        return

    index_list = runtime.get_property(class_definition, "Indices")
    existing_indexes: set[str] = set()
    if index_list is None:
        return
    owned_entries = _owned_schema_member_entries(
        runtime,
        index_list,
        classname,
        dictionary_class_name="%Dictionary.IndexDefinition",
    )
    owned_names = set(owned_entries)
    if mode == "managed":
        desired_names = {index_meta.name for index_meta in indexes}
        removed_entries = [
            entry
            for name, entry in owned_entries.items()
            if name not in desired_names
        ]
        _remove_owned_schema_member_entries(
            runtime,
            index_list,
            removed_entries,
            dictionary_class_name="%Dictionary.IndexDefinition",
            context=f"{classname}.Indices",
        )
    elif mode == "extend":
        existing_indexes = owned_names

    for index_meta in indexes:
        if mode == "extend" and index_meta.name in existing_indexes:
            continue
        if mode == "managed" and index_meta.name in owned_entries:
            idx_def = owned_entries[index_meta.name][1]
            runtime.set_property(idx_def, "Properties", index_meta.properties)
            runtime.set_property(
                idx_def,
                "Unique",
                1 if getattr(index_meta, "unique", False) else 0,
            )
            _set_runtime_property_if_not_none(
                runtime,
                idx_def,
                "Type",
                getattr(index_meta, "type", None),
            )
            runtime.set_property(
                idx_def,
                "PrimaryKey",
                1 if getattr(index_meta, "primary_key", False) else 0,
            )
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


def _sync_indexes_from_state(
    runtime: Any,
    class_definition: Any,
    classname: str,
    indexes: dict[str, dict[str, Any]],
) -> None:
    index_list = runtime.get_property(class_definition, "Indices")
    if index_list is None:
        return

    for index_name, index_state in sorted(indexes.items(), key=lambda item: item[0]):
        idx_def = runtime.create_object("%Dictionary.IndexDefinition")
        runtime.set_property(idx_def, "Name", index_name)
        runtime.set_property(idx_def, "parent", classname)
        _set_runtime_property_if_not_none(
            runtime, idx_def, "Properties", index_state.get("properties")
        )
        _set_runtime_flag_if_true(runtime, idx_def, "Unique", index_state.get("unique"))
        _set_runtime_property_if_not_none(runtime, idx_def, "Type", index_state.get("type"))
        _set_runtime_flag_if_true(
            runtime,
            idx_def,
            "PrimaryKey",
            index_state.get("primary_key"),
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
    if not storage_meta or mode not in {"managed", "replace"}:
        return

    storage_list = runtime.get_property(class_definition, "Storages")
    if storage_list is None:
        return
    if mode == "managed":
        owned_indices, _owned_names = _owned_schema_member_indices(
            runtime,
            storage_list,
            classname,
            skip_system_names=False,
        )
        _remove_runtime_list_indices(
            runtime,
            storage_list,
            owned_indices,
            context=f"{classname}.Storages",
        )
    storage_definition = runtime.create_object("%Dictionary.StorageDefinition")
    storage_name = getattr(storage_meta, "name", None) or "CustomStorage"
    runtime.set_property(storage_definition, "Name", storage_name)
    runtime.set_property(storage_definition, "parent", classname)
    runtime.set_property(class_definition, "StorageStrategy", storage_name)

    _apply_storage_attributes(runtime, storage_definition, storage_meta)
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


def _schema_transaction_methods(runtime: Any) -> tuple[Any, Any, Any] | None:
    begin = getattr(runtime, "begin_transaction", None)
    commit = getattr(runtime, "commit_transaction", None)
    rollback = getattr(runtime, "rollback_transaction", None)
    if callable(begin) and callable(commit) and callable(rollback):
        return (begin, commit, rollback)
    return None


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

    transaction_methods = _schema_transaction_methods(runtime)
    if transaction_methods is None:
        _sync_schema_model(runtime, model_cls, set())
        return

    begin_transaction, commit_transaction, rollback_transaction = transaction_methods
    begin_transaction()
    try:
        _sync_schema_model(runtime, model_cls, set())
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
