from __future__ import annotations

from typing import Any, Callable, Type

import iris_persistence.models
from iris_persistence.runtime import get_runtime
from iris_persistence.schema_inspection import (
    _collect_live_schema_state as _collect_live_schema_state,
)
from iris_persistence.schema_inspection import (
    _runtime_property_name,
    _set_runtime_property_if_not_none,
)
from iris_persistence.schema_inspection import diff_schema as _diff_schema
from iris_persistence.schema_inspection import (
    diff_schema_operations as diff_schema_operations,
)
from iris_persistence.schema_state import (
    _PROPERTY_FLAG_FIELDS,
    _PROPERTY_PARAM_FIELDS,
    _PROPERTY_VALUE_FIELDS,
    CLASS_METADATA_FLAG_KEYS,
    CLASS_METADATA_KEYS,
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
    _collect_model_schema_state_for_field,
    _find_existing_classname,
    _index_state_from_meta,
    _owned_schema_member_entries,
    _remove_owned_schema_member_entries,
    _resolve_model_type,
    _schema_classname_for_save,
    _state_to_dict,
)
from iris_persistence.schema_state import (
    SchemaDiff as SchemaDiff,
)
from iris_persistence.schema_state import (
    SchemaOperation as SchemaOperation,
)
from iris_persistence.schema_state import (
    SchemaState as SchemaState,
)
from iris_persistence.schema_state import (
    _map_python_type_to_iris as _map_python_type_to_iris,
)


class StorageMigrationRequired(RuntimeError):
    """Raised when a compiled class would require physical storage migration."""


def diff_schema(model_cls: Type[Any]) -> SchemaDiff:
    """Describe schema changes using this module's configured runtime."""
    return _diff_schema(model_cls, runtime=get_runtime())


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
) -> tuple[Any, bool, str]:
    existing_classname = _find_existing_classname(runtime, classname)
    schema_classname = existing_classname or _schema_classname_for_save(classname)

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
    if mode != "managed":
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
        insert=lambda name, default: _new_parameter_definition(runtime, classname, name, default),
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
        update=lambda obj, state: _apply_property_definition_state(runtime, obj, state, exact=True),
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
        "managed",
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
        "managed",
    )


_STORAGE_BOOL_ATTRS = {"bias_queries_as_outlier", "conditional_with_host_vars"}
_STORAGE_MEMBER_INSERT_SPECS = (
    ("Indices", "%Dictionary.StorageIndexDefinition", "indices", STORAGE_INDEX_KEYS),
    ("Properties", "%Dictionary.StoragePropertyDefinition", "properties", STORAGE_PROPERTY_KEYS),
)
_SQL_MAP_MEMBER_INSERT_SPECS = (
    ("Data", "%Dictionary.StorageSQLMapDataDefinition", "data", STORAGE_SQL_MAP_DATA_KEYS),
    (
        "RowIdSpecs",
        "%Dictionary.StorageSQLMapRowIdSpecDefinition",
        "row_id_specs",
        STORAGE_SQL_MAP_ROW_ID_SPEC_KEYS,
    ),
)
_SQL_MAP_SUB_MEMBER_INSERT_SPECS = (
    (
        "Accessvars",
        "%Dictionary.StorageSQLMapSubAccessvarDefinition",
        "access_vars",
        STORAGE_SQL_MAP_SUB_ACCESS_VAR_KEYS,
    ),
    (
        "Invalidconditions",
        "%Dictionary.StorageSQLMapSubInvalidconditionDefinition",
        "invalid_conditions",
        STORAGE_SQL_MAP_SUB_INVALID_CONDITION_KEYS,
    ),
)


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

        for list_property, dictionary_class, attr_name, member_keys in _SQL_MAP_MEMBER_INSERT_SPECS:
            _insert_schema_members(
                runtime,
                runtime.get_property(sql_map, list_property),
                dictionary_class,
                sql_map_parent,
                getattr(sql_map_meta, attr_name, ()) or (),
                member_keys,
            )

        subscript_list = runtime.get_property(sql_map, "Subscripts")
        for sub_meta in getattr(sql_map_meta, "subscripts", ()) or ():
            subscript = _new_schema_member(
                runtime, "%Dictionary.StorageSQLMapSubDefinition", sub_meta.name, sql_map_parent
            )
            _apply_state_attrs(runtime, subscript, sub_meta, STORAGE_SQL_MAP_SUB_KEYS)
            sub_parent = f"{sql_map_parent}||{sub_meta.name}"
            for (
                list_property,
                dictionary_class,
                attr_name,
                child_keys,
            ) in _SQL_MAP_SUB_MEMBER_INSERT_SPECS:
                _insert_schema_members(
                    runtime,
                    runtime.get_property(subscript, list_property),
                    dictionary_class,
                    sub_parent,
                    getattr(sub_meta, attr_name, ()) or (),
                    child_keys,
                )
            runtime.invoke_method(subscript_list, "Insert", subscript)

        runtime.invoke_method(sql_maps_list, "Insert", sql_map)


def _sync_storage(
    runtime: Any,
    class_definition: Any,
    classname: str,
    storage_tuning: Any,
    custom_storage: Any,
    *,
    exists: bool,
) -> None:
    storage_meta = custom_storage or storage_tuning
    if storage_meta is None or exists:
        return

    storage_list = runtime.get_property(class_definition, "Storages")
    if storage_list is None:
        return
    storage_definition = runtime.new_object("%Dictionary.StorageDefinition")
    storage_name = custom_storage.name if custom_storage is not None else "Default"
    runtime.set_property(storage_definition, "Name", storage_name)
    runtime.set_property(storage_definition, "parent", classname)
    if storage_name != "Default":
        runtime.set_property(class_definition, "StorageStrategy", storage_name)

    if storage_tuning is not None:
        runtime.set_property(storage_definition, "Type", "%Storage.Persistent")
        _apply_state_attrs(runtime, storage_definition, storage_tuning, STORAGE_KEYS)
        index_list = runtime.get_property(storage_definition, "Indices")
        for name, location in storage_tuning.index_locations.items():
            index_definition = _new_schema_member(
                runtime,
                "%Dictionary.StorageIndexDefinition",
                str(name),
                f"{classname}||Default",
            )
            runtime.set_property(index_definition, "Location", str(location))
            runtime.invoke_method(index_list, "Insert", index_definition)
        runtime.invoke_method(storage_list, "Insert", storage_definition)
        return

    _apply_state_attrs(runtime, storage_definition, custom_storage, STORAGE_KEYS)
    _insert_storage_data(runtime, storage_definition, classname, storage_name, custom_storage)
    storage_parent = f"{classname}||{storage_name}"
    for list_property, dictionary_class, attr_name, storage_keys in _STORAGE_MEMBER_INSERT_SPECS:
        _insert_schema_members(
            runtime,
            runtime.get_property(storage_definition, list_property),
            dictionary_class,
            storage_parent,
            getattr(custom_storage, attr_name, ()) or (),
            storage_keys,
        )
    _insert_storage_sql_maps(runtime, storage_definition, classname, storage_name, custom_storage)

    runtime.invoke_method(storage_list, "Insert", storage_definition)


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
            f"Schema compile failed for {schema_classname}: {runtime.format_status(compile_status)}"
        )


def _sync_schema_state(runtime: Any, state: SchemaState | dict[str, Any]) -> None:
    state = SchemaState.from_dict(_state_to_dict(state))
    if not state.superclasses:
        return

    cd, _exists, schema_classname = _ensure_class_definition(runtime, state.classname)
    _apply_class_definition(runtime, cd, schema_classname, state.superclasses, state.metadata)
    _sync_parameters(runtime, cd, schema_classname, state.parameters, "managed")
    _sync_properties_from_state(runtime, cd, schema_classname, state.properties)
    _sync_indexes_from_state(runtime, cd, schema_classname, state.indexes)
    _save_and_compile_schema_class(runtime, cd, schema_classname)


def _run_with_schema_transaction(runtime: Any, action: Callable[[], Any]) -> Any:
    runtime.begin_transaction()
    try:
        result = action()
    except Exception:
        try:
            runtime.rollback_transaction()
        except Exception:
            pass
        raise

    try:
        runtime.commit_transaction()
    except Exception:
        try:
            runtime.rollback_transaction()
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

    schema_diff = _diff_schema(model_cls, runtime=runtime)
    if any(operation.safety == "blocked" for operation in schema_diff.operations):
        raise StorageMigrationRequired(
            f"Storage for {schema_classname} differs from its creation-time declaration; "
            "an explicit data migration is required"
        )

    cd, exists, schema_classname = _ensure_class_definition(runtime, classname)
    class_metadata = getattr(model_cls, "_class_metadata", None)
    _apply_class_definition(runtime, cd, schema_classname, superclasses, class_metadata)

    parameters = getattr(model_cls, "_parameters", {}) or {}
    _sync_parameters(runtime, cd, schema_classname, parameters, mode)

    model_fields = getattr(model_cls, "__model_fields__", {})
    _sync_related_models(runtime, model_cls, model_fields, seen)
    _sync_properties(runtime, cd, schema_classname, model_fields, mode)

    indexes = getattr(model_cls, "_indexes", [])
    _sync_indexes(runtime, cd, schema_classname, indexes, mode)

    _sync_storage(
        runtime,
        cd,
        schema_classname,
        getattr(model_cls, "_storage_tuning", None),
        getattr(model_cls, "_custom_storage", None),
        exists=exists,
    )
    _save_and_compile_schema_class(runtime, cd, schema_classname)


def sync_schema(model_cls: Type[Any], _seen: set[str] | None = None) -> None:
    if getattr(model_cls, "_sync_mode", iris_persistence.models.DEFAULT_SYNC_MODE) == "observe":
        return

    runtime = get_runtime()
    if _seen is not None:
        _sync_schema_model(runtime, model_cls, _seen)
        return

    _run_with_schema_transaction(runtime, lambda: _sync_schema_model(runtime, model_cls, set()))
