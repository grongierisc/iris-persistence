from __future__ import annotations

from typing import Any, Callable

from iris_persistence.catalog import dictionary_rows as _dictionary_rows
from iris_persistence.catalog import safe_get_property as _safe_get_property
from iris_persistence.field_utils import coerce_bool
from iris_persistence.schema.state import (
    _PROPERTY_FLAG_FIELDS,
    _PROPERTY_VALUE_FIELDS,
    _STORAGE_SQL_MAP_RUNTIME_CHILDREN,
    CLASS_METADATA_FLAG_KEYS,
    CLASS_METADATA_KEYS,
    STORAGE_DATA_KEYS,
    STORAGE_INDEX_KEYS,
    STORAGE_KEYS,
    STORAGE_PROPERTY_KEYS,
    STORAGE_SQL_MAP_KEYS,
    SchemaState,
    _compact_mapping,
    _compact_property_state,
    _empty_schema_state,
    _empty_storage_state,
    _find_existing_classname,
    _index_state_from_getter,
    _is_system_member_name,
    _item_belongs_to_class,
    _iter_runtime_list,
    _normalize_values_mapping,
    _row_value,
    _schema_classname_for_save,
    _sort_mapping,
)
from iris_persistence.types import UNSET


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


class _LiveSchemaReader:
    def __init__(
        self,
        runtime: Any,
        classname: str,
        *,
        include_storage: bool,
        storage_name: str | None,
    ) -> None:
        self.runtime = runtime
        self.requested_classname = classname
        self.include_storage = include_storage
        self.storage_name = storage_name
        self.state = _empty_schema_state(_schema_classname_for_save(classname))
        self.classname = _find_existing_classname(runtime, classname)
        self.class_def: Any | None = None

    def read(self) -> SchemaState:
        if self.classname is None:
            return SchemaState.from_dict(self.state)
        self.class_def = self.runtime.get_object("%Dictionary.ClassDefinition", self.classname)
        self._read_class()
        self._read_members()
        if self.include_storage:
            self._read_storage()
        return SchemaState.from_dict(self.state)

    def _read_class(self) -> None:
        assert self.class_def is not None and self.classname is not None
        self.state["classname"] = self.classname
        self.state["super"] = _safe_get_property(self.runtime, self.class_def, "Super")
        self.state["metadata"] = _runtime_state_from_item(
            self.runtime,
            self.class_def,
            CLASS_METADATA_KEYS,
            bool_keys=CLASS_METADATA_FLAG_KEYS,
        )

    def _property_state(self, item: Any) -> dict[str, Any]:
        params = _safe_get_property(self.runtime, item, "Parameters")
        max_length = self._parameter_value(params, "MAXLEN")
        scale = self._parameter_value(params, "SCALE")
        return _property_state_from_getter(
            lambda name: _safe_get_property(self.runtime, item, name),
            max_length=max_length,
            scale=scale,
        )

    def _parameter_value(self, params: Any, name: str) -> Any:
        if params is None:
            return None
        try:
            return self.runtime.invoke_method(params, "GetAt", name)
        except Exception:
            return None

    def _read_members(self) -> None:
        assert self.class_def is not None and self.classname is not None
        runtime, class_def, classname = self.runtime, self.class_def, self.classname
        self.state["parameters"] = _collect_live_members(
            runtime,
            class_def,
            classname,
            list_property="Parameters",
            skip=_is_system_member_name,
            item_state=lambda item: str(_safe_get_property(runtime, item, "Default")),
            sql_fallback=_collect_live_parameters_from_sql(runtime, classname),
        )
        self.state["properties"] = _collect_live_members(
            runtime,
            class_def,
            classname,
            list_property="Properties",
            skip=lambda name: name.startswith("%"),
            item_state=self._property_state,
            sql_fallback=_collect_live_properties_from_sql(runtime, classname),
        )
        self.state["indexes"] = _collect_live_members(
            runtime,
            class_def,
            classname,
            list_property="Indices",
            item_state=lambda item: _index_state_from_getter(
                lambda name: _safe_get_property(runtime, item, name)
            ),
            sql_fallback=_collect_live_indexes_from_sql(runtime, classname),
        )

    def _select_storage(self) -> Any | None:
        assert self.class_def is not None
        strategy = (
            self.storage_name
            or _safe_get_property(self.runtime, self.class_def, "StorageStrategy")
            or "Default"
        )
        storages = _iter_runtime_list(
            self.runtime, _safe_get_property(self.runtime, self.class_def, "Storages")
        )
        for storage in storages:
            if _safe_get_property(self.runtime, storage, "Name") == strategy:
                return storage
        return storages[0] if self.storage_name is None and storages else None

    def _read_storage(self) -> None:
        storage = self._select_storage()
        if storage is None:
            return
        result = _empty_storage_state()
        result["name"] = _safe_get_property(self.runtime, storage, "Name")
        result["attrs"] = _runtime_state_from_item(self.runtime, storage, STORAGE_KEYS)
        result["data"] = self._read_storage_data(storage)
        result["indices"] = _collect_runtime_state_mapping(
            self.runtime, storage, "Indices", STORAGE_INDEX_KEYS
        )
        result["properties"] = _collect_runtime_state_mapping(
            self.runtime,
            storage,
            "Properties",
            STORAGE_PROPERTY_KEYS,
            bool_keys={"bias_queries_as_outlier"},
        )
        result["sql_maps"] = self._read_sql_maps(storage)
        self.state["storage"] = result

    def _read_storage_data(self, storage: Any) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        items = _iter_runtime_list(self.runtime, _safe_get_property(self.runtime, storage, "Data"))
        for item in items:
            name = _safe_get_property(self.runtime, item, "Name")
            if not name:
                continue
            values = self._read_storage_values(item)
            item_state = _runtime_state_from_item(self.runtime, item, STORAGE_DATA_KEYS)
            item_state["values"] = _normalize_values_mapping(values)
            result[str(name)] = _compact_mapping(item_state)
        return _sort_mapping(result)

    def _read_storage_values(self, item: Any) -> dict[str, str]:
        values: dict[str, str] = {}
        children = _iter_runtime_list(
            self.runtime, _safe_get_property(self.runtime, item, "Values")
        )
        for child in children:
            name = _safe_get_property(self.runtime, child, "Name")
            if name not in (None, ""):
                values[str(name)] = str(_safe_get_property(self.runtime, child, "Value"))
        return values

    def _read_sql_maps(self, storage: Any) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        items = _iter_runtime_list(
            self.runtime, _safe_get_property(self.runtime, storage, "SQLMaps")
        )
        for item in items:
            name = _safe_get_property(self.runtime, item, "Name")
            if not name:
                continue
            item_state = _runtime_state_from_item(
                self.runtime,
                item,
                STORAGE_SQL_MAP_KEYS,
                bool_keys={"conditional_with_host_vars"},
            )
            item_state.update(
                _collect_runtime_children(self.runtime, item, _STORAGE_SQL_MAP_RUNTIME_CHILDREN)
            )
            result[str(name)] = item_state
        return _sort_mapping(result)


def _collect_live_schema_state(
    runtime: Any,
    classname: str,
    *,
    include_storage: bool = False,
    storage_name: str | None = None,
) -> SchemaState:
    return _LiveSchemaReader(
        runtime,
        classname,
        include_storage=include_storage,
        storage_name=storage_name,
    ).read()
