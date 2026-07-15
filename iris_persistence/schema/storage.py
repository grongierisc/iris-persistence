from __future__ import annotations

from typing import Any

from iris_persistence.schema.inspection import (
    _runtime_property_name,
    _set_runtime_property_if_not_none,
)
from iris_persistence.schema.state import (
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
