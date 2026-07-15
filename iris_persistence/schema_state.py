from __future__ import annotations

import decimal
import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from difflib import unified_diff
from typing import Any, Type, get_args, get_origin

import iris_persistence.models
from iris_persistence.advanced_storage import (
    STORAGE_DATA_SCALAR_KEYS,
    STORAGE_DEFINITION_SCALAR_KEYS,
    STORAGE_INDEX_SCALAR_KEYS,
    STORAGE_PROPERTY_SCALAR_KEYS,
    STORAGE_SQL_MAP_DATA_SCALAR_KEYS,
    STORAGE_SQL_MAP_ROW_ID_SPEC_SCALAR_KEYS,
    STORAGE_SQL_MAP_SCALAR_KEYS,
    STORAGE_SQL_MAP_SUB_ACCESS_VAR_SCALAR_KEYS,
    STORAGE_SQL_MAP_SUB_INVALID_CONDITION_SCALAR_KEYS,
    STORAGE_SQL_MAP_SUB_SCALAR_KEYS,
)
from iris_persistence.catalog import (
    dictionary_rows as _dictionary_rows,
)
from iris_persistence.catalog import (
    item_belongs_to_class,
)
from iris_persistence.catalog import (
    safe_get_property as _safe_get_property,
)
from iris_persistence.field_utils import PYTHON_TO_IRIS_TYPE, coerce_bool
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
_PROPERTY_FLAG_FIELDS = tuple((key, name) for key, name, kind in _PROPERTY_SPEC if kind == "flag")
_PROPERTY_VALUE_FIELDS = tuple((key, name) for key, name, kind in _PROPERTY_SPEC if kind == "value")
_PROPERTY_PARAM_FIELDS = tuple((key, name) for key, name, kind in _PROPERTY_SPEC if kind == "param")
DEFAULT_DECIMAL_SCALE = "18"
INDEX_KEYS = ("properties", "unique", "type", "primary_key")
STORAGE_KEYS = STORAGE_DEFINITION_SCALAR_KEYS
STORAGE_PROPERTY_KEYS = STORAGE_PROPERTY_SCALAR_KEYS
STORAGE_DATA_KEYS = STORAGE_DATA_SCALAR_KEYS
STORAGE_INDEX_KEYS = STORAGE_INDEX_SCALAR_KEYS
STORAGE_SQL_MAP_KEYS = STORAGE_SQL_MAP_SCALAR_KEYS
STORAGE_SQL_MAP_DATA_KEYS = STORAGE_SQL_MAP_DATA_SCALAR_KEYS
STORAGE_SQL_MAP_ROW_ID_SPEC_KEYS = STORAGE_SQL_MAP_ROW_ID_SPEC_SCALAR_KEYS
STORAGE_SQL_MAP_SUB_KEYS = STORAGE_SQL_MAP_SUB_SCALAR_KEYS
STORAGE_SQL_MAP_SUB_ACCESS_VAR_KEYS = STORAGE_SQL_MAP_SUB_ACCESS_VAR_SCALAR_KEYS
STORAGE_SQL_MAP_SUB_INVALID_CONDITION_KEYS = STORAGE_SQL_MAP_SUB_INVALID_CONDITION_SCALAR_KEYS

# (state key, runtime list property, scalar keys, boolean keys, nested children)
_STORAGE_SQL_MAP_RUNTIME_CHILDREN: tuple[Any, ...] = (
    ("data", "Data", STORAGE_SQL_MAP_DATA_KEYS, set(), ()),
    ("row_id_specs", "RowIdSpecs", STORAGE_SQL_MAP_ROW_ID_SPEC_KEYS, set(), ()),
    (
        "subscripts",
        "Subscripts",
        STORAGE_SQL_MAP_SUB_KEYS,
        set(),
        (
            (
                "access_vars",
                "Accessvars",
                STORAGE_SQL_MAP_SUB_ACCESS_VAR_KEYS,
                set(),
                (),
            ),
            (
                "invalid_conditions",
                "Invalidconditions",
                STORAGE_SQL_MAP_SUB_INVALID_CONDITION_KEYS,
                set(),
                (),
            ),
        ),
    ),
)

# (attribute/state key, scalar keys, nested children)
_STORAGE_SQL_MAP_STATE_CHILDREN: tuple[Any, ...] = (
    ("data", STORAGE_SQL_MAP_DATA_KEYS, ()),
    ("row_id_specs", STORAGE_SQL_MAP_ROW_ID_SPEC_KEYS, ()),
    (
        "subscripts",
        STORAGE_SQL_MAP_SUB_KEYS,
        (
            ("access_vars", STORAGE_SQL_MAP_SUB_ACCESS_VAR_KEYS, ()),
            ("invalid_conditions", STORAGE_SQL_MAP_SUB_INVALID_CONDITION_KEYS, ()),
        ),
    ),
)


@dataclass(frozen=True)
class SchemaOperation:
    classname: str
    op_type: str
    path: str
    before: Any = None
    after: Any = None
    safety: str = "safe"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    # Definition lists contain owned members; older test/runtime facades may not
    # expose Origin/Parent metadata for them.
    return item_belongs_to_class(runtime, item, classname, unknown_is_owned=True)


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
    children: tuple[Any, ...] = (),
) -> dict[str, Any]:
    states = {}
    for item in items or ():
        state = _object_state(item, keys)
        if extra is not None:
            state.update(extra(item))
        for attr_name, child_keys, grandchildren in children:
            state[attr_name] = _named_object_mapping(
                getattr(item, attr_name, None),
                child_keys,
                children=grandchildren,
            )
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
        "kind": None,
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

    storage_tuning = getattr(model_cls, "_storage_tuning", None)
    custom_storage = getattr(model_cls, "_custom_storage", None)
    if storage_tuning is not None:
        storage_state = _empty_storage_state()
        storage_state["kind"] = "tuning"
        storage_state["name"] = "Default"
        storage_state["attrs"] = {
            key: value
            for key, value in _object_state(storage_tuning, STORAGE_KEYS).items()
            if value not in (None, "")
        }
        storage_state["indices"] = {
            str(name): {"location": str(location)}
            for name, location in storage_tuning.index_locations.items()
        }
        state["storage"] = storage_state
    elif custom_storage is not None:
        storage_state = _empty_storage_state()
        storage_state["kind"] = "custom"
        storage_state["name"] = custom_storage.name
        storage_state["attrs"] = _object_state(custom_storage, STORAGE_KEYS)
        storage_state["data"] = _named_object_mapping(
            custom_storage.data,
            STORAGE_DATA_KEYS,
            extra=lambda item: {"values": _normalize_values_mapping(getattr(item, "values", None))},
        )
        storage_state["indices"] = _named_object_mapping(
            custom_storage.indices,
            STORAGE_INDEX_KEYS,
        )
        storage_state["properties"] = _named_object_mapping(
            custom_storage.properties,
            STORAGE_PROPERTY_KEYS,
        )
        storage_state["sql_maps"] = _named_object_mapping(
            custom_storage.sql_maps,
            STORAGE_SQL_MAP_KEYS,
            children=_STORAGE_SQL_MAP_STATE_CHILDREN,
        )
        state["storage"] = storage_state

    return SchemaState.from_dict(state)
