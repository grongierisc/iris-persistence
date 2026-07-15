"""Expert-only complete IRIS storage definitions."""

from __future__ import annotations

from dataclasses import dataclass, fields
from dataclasses import field as dataclass_field
from typing import Any, Dict, Optional, Tuple


@dataclass
class StorageProperty:
    name: str
    average_field_size: Optional[str] = None
    selectivity: Optional[str] = None
    outlier_selectivity: Optional[str] = None
    histogram: Optional[str] = None
    child_block_count: Optional[str] = None
    child_extent_size: Optional[str] = None
    bias_queries_as_outlier: Optional[bool] = None
    stream_location: Optional[str] = None


@dataclass
class StorageIndex:
    name: str
    location: Optional[str] = None
    small_chunk_size: Optional[str] = None


@dataclass
class StorageData:
    name: str
    structure: str
    attribute: Optional[str] = None
    subscript: Optional[str] = None
    values: Dict[str, str] = dataclass_field(default_factory=dict)


@dataclass
class StorageSQLMapData:
    name: str
    node: Optional[str] = None
    piece: Optional[str] = None
    delimiter: Optional[str] = None
    retrieval_code: Optional[str] = None


@dataclass
class StorageSQLMapRowIdSpec:
    name: str
    field: Optional[str] = None
    expression: Optional[str] = None


@dataclass
class StorageSQLMapSubAccessVar:
    name: str
    variable: Optional[str] = None
    code: Optional[str] = None


@dataclass
class StorageSQLMapSubInvalidCondition:
    name: str
    expression: Optional[str] = None


@dataclass
class StorageSQLMapSub:
    name: str
    access_type: Optional[str] = None
    data_access: Optional[str] = None
    delimiter: Optional[str] = None
    expression: Optional[str] = None
    loop_init_value: Optional[str] = None
    next_code: Optional[str] = None
    null_marker: Optional[str] = None
    start_value: Optional[str] = None
    stop_expression: Optional[str] = None
    stop_value: Optional[str] = None
    access_vars: Tuple[StorageSQLMapSubAccessVar, ...] = ()
    invalid_conditions: Tuple[StorageSQLMapSubInvalidCondition, ...] = ()


@dataclass
class StorageSQLMap:
    name: str
    block_count: Optional[str] = None
    condition: Optional[str] = None
    condition_fields: Optional[str] = None
    conditional_with_host_vars: Optional[bool] = None
    global_name: Optional[str] = None
    population_pct: Optional[str] = None
    population_type: Optional[str] = None
    row_reference: Optional[str] = None
    structure: Optional[str] = None
    type: Optional[str] = None
    data: Optional[Tuple[StorageSQLMapData, ...]] = None
    row_id_specs: Tuple[StorageSQLMapRowIdSpec, ...] = ()
    subscripts: Tuple[StorageSQLMapSub, ...] = ()


@dataclass
class StorageDefinition:
    name: str = "CustomStorage"
    type: str = "%Storage.Persistent"
    data_location: Optional[str] = None
    default_data: Optional[str] = None
    extent_location: Optional[str] = None
    extent_size: Optional[str] = None
    counter_location: Optional[str] = None
    version_location: Optional[str] = None
    id_location: Optional[str] = None
    id_expression: Optional[str] = None
    id_function: Optional[str] = None
    index_location: Optional[str] = None
    state: Optional[str] = None
    stream_location: Optional[str] = None
    sql_child_sub: Optional[str] = None
    sql_id_expression: Optional[str] = None
    sql_row_id_name: Optional[str] = None
    sql_row_id_property: Optional[str] = None
    sql_table_number: Optional[str] = None
    sequence_number: Optional[str] = None
    data: Tuple[StorageData, ...] = ()
    indices: Tuple[StorageIndex, ...] = ()
    properties: Tuple[StorageProperty, ...] = ()
    sql_maps: Tuple[StorageSQLMap, ...] = ()


@dataclass(frozen=True)
class ExistingStorageTuningResult:
    """Summary of an explicit in-place statistics update."""

    classname: str
    storage_name: str
    updated_properties: Tuple[str, ...]


_EXISTING_STORAGE_STATISTIC_KEYS = (
    "average_field_size",
    "selectivity",
    "outlier_selectivity",
    "histogram",
    "child_block_count",
    "child_extent_size",
    "bias_queries_as_outlier",
)


def _runtime_property(runtime: Any, obj: Any, name: str) -> Any:
    try:
        return runtime.get_property(obj, name)
    except (AttributeError, RuntimeError):
        return None


def _runtime_items(runtime: Any, collection: Any) -> tuple[Any, ...]:
    if collection is None:
        return ()
    count = int(runtime.invoke_method(collection, "Count") or 0)
    return tuple(runtime.invoke_method(collection, "GetAt", index) for index in range(1, count + 1))


def tune_existing_storage_statistics(
    classname: str,
    properties: Tuple[StorageProperty, ...],
    *,
    storage_name: str | None = None,
) -> ExistingStorageTuningResult:
    """Update non-location optimizer statistics on an existing defined storage.

    This expert API never changes data, ID, index, stream, counter, version, or extent
    locations. Physical relocation requires a separate data-copy and cutover workflow.
    """
    from iris_persistence.runtime import get_runtime

    if not properties:
        raise ValueError("At least one StorageProperty tuning is required")
    if any(not isinstance(item, StorageProperty) for item in properties):
        raise TypeError("properties must contain StorageProperty instances")
    if any(item.stream_location is not None for item in properties):
        raise ValueError("stream_location is physical storage and cannot be tuned in place")

    runtime = get_runtime()
    runtime.begin_transaction()
    try:
        class_definition = runtime.get_object("%Dictionary.ClassDefinition", classname)
        if class_definition is None:
            raise ValueError(f"IRIS class {classname!r} does not exist")

        selected_name = storage_name or _runtime_property(
            runtime, class_definition, "StorageStrategy"
        ) or "Default"
        storages = _runtime_items(
            runtime,
            _runtime_property(runtime, class_definition, "Storages"),
        )
        storage = next(
            (
                item
                for item in storages
                if str(_runtime_property(runtime, item, "Name")) == selected_name
            ),
            None,
        )
        if storage is None:
            raise ValueError(
                f"Storage {selected_name!r} is not defined for IRIS class {classname!r}"
            )

        property_collection = _runtime_property(runtime, storage, "Properties")
        existing = {
            str(_runtime_property(runtime, item, "Name")): item
            for item in _runtime_items(runtime, property_collection)
        }
        for tuning in properties:
            definition = existing.get(tuning.name)
            if definition is None:
                definition = runtime.new_object("%Dictionary.StoragePropertyDefinition")
                runtime.set_property(definition, "Name", tuning.name)
                runtime.set_property(definition, "parent", f"{classname}||{selected_name}")
                runtime.invoke_method(property_collection, "Insert", definition)
            for key in _EXISTING_STORAGE_STATISTIC_KEYS:
                value = getattr(tuning, key)
                if value is None:
                    continue
                runtime_name = "".join(part.capitalize() for part in key.split("_"))
                runtime.set_property(
                    definition,
                    runtime_name,
                    1 if key == "bias_queries_as_outlier" and value else value,
                )

        status = runtime.save_object(class_definition)
        if not runtime.is_ok(status):
            raise RuntimeError(f"Storage tuning save failed: {runtime.format_status(status)}")
        status = runtime.call_classmethod(
            "%SYSTEM.OBJ", "Compile", classname, "fc /display=none"
        )
        if not runtime.is_ok(status):
            raise RuntimeError(f"Storage tuning compile failed: {runtime.format_status(status)}")
        runtime.commit_transaction()
    except Exception:
        runtime.rollback_transaction()
        raise

    return ExistingStorageTuningResult(
        classname=classname,
        storage_name=str(selected_name),
        updated_properties=tuple(item.name for item in properties),
    )


def _state_items(model: type[Any], mapping: dict[str, dict[str, Any]]) -> tuple[Any, ...]:
    allowed = {item.name for item in fields(model)} - {"name"}
    return tuple(
        model(name=name, **{key: value for key, value in values.items() if key in allowed})
        for name, values in sorted(mapping.items())
    )


def _sql_map_subs(mapping: dict[str, dict[str, Any]]) -> tuple[StorageSQLMapSub, ...]:
    result = []
    allowed = {item.name for item in fields(StorageSQLMapSub)} - {
        "name",
        "access_vars",
        "invalid_conditions",
    }
    for name, values in sorted(mapping.items()):
        result.append(
            StorageSQLMapSub(
                name=name,
                **{key: value for key, value in values.items() if key in allowed},
                access_vars=_state_items(
                    StorageSQLMapSubAccessVar, values.get("access_vars", {})
                ),
                invalid_conditions=_state_items(
                    StorageSQLMapSubInvalidCondition,
                    values.get("invalid_conditions", {}),
                ),
            )
        )
    return tuple(result)


def _sql_maps(mapping: dict[str, dict[str, Any]]) -> tuple[StorageSQLMap, ...]:
    result = []
    allowed = {item.name for item in fields(StorageSQLMap)} - {
        "name",
        "data",
        "row_id_specs",
        "subscripts",
    }
    for name, values in sorted(mapping.items()):
        result.append(
            StorageSQLMap(
                name=name,
                **{key: value for key, value in values.items() if key in allowed},
                data=_state_items(StorageSQLMapData, values.get("data", {})),
                row_id_specs=_state_items(
                    StorageSQLMapRowIdSpec, values.get("row_id_specs", {})
                ),
                subscripts=_sql_map_subs(values.get("subscripts", {})),
            )
        )
    return tuple(result)


def inspect_existing_storage(
    classname: str,
    *,
    storage_name: str | None = None,
    _runtime: Any | None = None,
) -> StorageDefinition:
    """Return a typed snapshot of writable storage metadata for an existing class."""
    from iris_persistence.runtime import get_runtime
    from iris_persistence.schema.inspection import _collect_live_schema_state

    state = _collect_live_schema_state(
        _runtime or get_runtime(),
        classname,
        include_storage=True,
        storage_name=storage_name,
    )
    storage = state.storage
    if storage is None:
        target = f" storage {storage_name!r}" if storage_name else " active storage"
        raise ValueError(f"IRIS class {classname!r} has no{target}")

    attrs = {
        key: value
        for key, value in storage.get("attrs", {}).items()
        if key in STORAGE_DEFINITION_SCALAR_KEYS
    }
    data = []
    for name, values in sorted(storage.get("data", {}).items()):
        item_values = dict(values)
        stored_values = item_values.pop("values", {})
        data.append(StorageData(name=name, values=stored_values, **item_values))
    return StorageDefinition(
        name=str(storage.get("name") or storage_name or "Default"),
        **attrs,
        data=tuple(data),
        indices=_state_items(StorageIndex, storage.get("indices", {})),
        properties=_state_items(StorageProperty, storage.get("properties", {})),
        sql_maps=_sql_maps(storage.get("sql_maps", {})),
    )


STORAGE_DEFINITION_SCALAR_KEYS = tuple(
    item.name
    for item in fields(StorageDefinition)
    if item.name not in {"name", "data", "indices", "properties", "sql_maps"}
)


def _storage_scalar_keys(model: type[Any], *containers: str) -> tuple[str, ...]:
    return tuple(item.name for item in fields(model) if item.name not in {"name", *containers})


STORAGE_PROPERTY_SCALAR_KEYS = _storage_scalar_keys(StorageProperty)
STORAGE_DATA_SCALAR_KEYS = _storage_scalar_keys(StorageData, "values")
STORAGE_INDEX_SCALAR_KEYS = _storage_scalar_keys(StorageIndex)
STORAGE_SQL_MAP_SCALAR_KEYS = _storage_scalar_keys(
    StorageSQLMap, "data", "row_id_specs", "subscripts"
)
STORAGE_SQL_MAP_DATA_SCALAR_KEYS = _storage_scalar_keys(StorageSQLMapData)
STORAGE_SQL_MAP_ROW_ID_SPEC_SCALAR_KEYS = _storage_scalar_keys(StorageSQLMapRowIdSpec)
STORAGE_SQL_MAP_SUB_SCALAR_KEYS = _storage_scalar_keys(
    StorageSQLMapSub, "access_vars", "invalid_conditions"
)
STORAGE_SQL_MAP_SUB_ACCESS_VAR_SCALAR_KEYS = _storage_scalar_keys(StorageSQLMapSubAccessVar)
STORAGE_SQL_MAP_SUB_INVALID_CONDITION_SCALAR_KEYS = _storage_scalar_keys(
    StorageSQLMapSubInvalidCondition
)
