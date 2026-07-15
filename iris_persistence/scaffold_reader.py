from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from iris_persistence.catalog import DictionarySession, item_belongs_to_class
from iris_persistence.field_utils import (
    coerce_bool,
    python_annotation_for_iris_type,
)
from iris_persistence.runtime import get_runtime
from iris_persistence.types import (
    STORAGE_DEFINITION_SCALAR_KEYS,
    STORAGE_SQL_MAP_DATA_SCALAR_KEYS,
    STORAGE_SQL_MAP_ROW_ID_SPEC_SCALAR_KEYS,
    STORAGE_SQL_MAP_SCALAR_KEYS,
    STORAGE_SQL_MAP_SUB_ACCESS_VAR_SCALAR_KEYS,
    STORAGE_SQL_MAP_SUB_INVALID_CONDITION_SCALAR_KEYS,
    STORAGE_SQL_MAP_SUB_SCALAR_KEYS,
    StorageData,
    StorageDefinition,
    StorageIndex,
    StorageProperty,
    StorageSQLMap,
    StorageSQLMapData,
    StorageSQLMapRowIdSpec,
    StorageSQLMapSub,
    StorageSQLMapSubAccessVar,
    StorageSQLMapSubInvalidCondition,
)


def _parse_iris_list(value: Any) -> list[Any]:
    if not isinstance(value, (bytes, str)):
        return []
    items = []
    index = 0
    while index < len(value):
        length = value[index] if isinstance(value, bytes) else ord(value[index])
        if length == 0:
            break
        items.append(value[index + 2 : index + length])
        index += length
    return items


def _parse_iris_dict(value: Any) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in _parse_iris_list(value):
        key_value = _parse_iris_list(item)
        if len(key_value) != 2:
            continue
        key = key_value[0].decode("utf-8") if isinstance(key_value[0], bytes) else str(key_value[0])
        raw_value = (
            key_value[1].decode("utf-8") if isinstance(key_value[1], bytes) else str(key_value[1])
        )
        parsed[key] = raw_value
    return parsed


def _sort_storage_key(item: tuple[str, str]) -> tuple[int, Any]:
    key = item[0]
    if key.isdigit():
        return (0, int(key))
    return (1, key)


def _optional_str(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _row_model_kwargs(
    row: tuple[Any, ...],
    attrs: tuple[str, ...],
    *,
    bool_attrs: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        attr: coerce_bool(row[index + 1]) if attr in bool_attrs else _optional_str(row[index + 1])
        for index, attr in enumerate(attrs)
    }


def _row_model(
    model_cls: Any,
    row: tuple[Any, ...],
    attrs: tuple[str, ...],
    *,
    bool_attrs: tuple[str, ...] = (),
) -> Any:
    return model_cls(
        name=str(row[0]),
        **_row_model_kwargs(row, attrs, bool_attrs=bool_attrs),
    )


def _has_storage_property_metadata(**values: Any) -> bool:
    return any(value is not None for value in values.values())


@dataclass(frozen=True)
class ScaffoldWarning:
    code: str
    message: str
    classname: str | None = None


@dataclass
class ScaffoldResult:
    files: list[str]
    warnings: list[ScaffoldWarning]


@dataclass(frozen=True)
class _CompiledClass:
    name: str
    superclasses: str | None
    description: str | None = None
    deprecated: bool = False
    final: bool = False
    sql_table_name: str | None = None
    procedure_block: bool = False


@dataclass(frozen=True)
class _CompiledProperty:
    name: str
    iris_type: str
    python_type: str
    required: bool
    default: str | None
    maxlen: str | None
    readonly: bool
    collection: str | None
    sql_field_name: str | None
    identity: bool
    relationship: str | None
    on_delete: str | None
    inverse: str | None
    transient: bool
    storable: bool
    multi_dimensional: bool
    sql_list_delimiter: str | None
    sql_list_type: str | None
    sql_compute_code: str | None
    sql_compute_on_change: str | None
    sql_computed: bool


@dataclass(frozen=True)
class _CompiledParameter:
    name: str
    default: str


@dataclass(frozen=True)
class _CompiledIndex:
    name: str
    properties: str
    unique: bool
    index_type: str | None
    primary_key: bool


@dataclass
class _CompiledStorage(StorageDefinition):
    """A `StorageDefinition` scaffolded from %Dictionary, plus its storage name."""

    name: str = ""


STORAGE_SCALAR_KEYS = STORAGE_DEFINITION_SCALAR_KEYS


@dataclass(frozen=True)
class _SQLTree:
    table: str
    columns: str
    model: Any
    attrs: tuple[str, ...]
    bool_attrs: tuple[str, ...] = ()
    children: tuple[tuple[str, "_SQLTree"], ...] = ()


_ACCESS_VAR_SQL = _SQLTree(
    "CompiledStorageSQLMapSubAccessvar",
    "Variable, Code",
    StorageSQLMapSubAccessVar,
    STORAGE_SQL_MAP_SUB_ACCESS_VAR_SCALAR_KEYS,
)
_INVALID_CONDITION_SQL = _SQLTree(
    "CompiledStorageSQLMapSubInvalidcondition",
    "Expression",
    StorageSQLMapSubInvalidCondition,
    STORAGE_SQL_MAP_SUB_INVALID_CONDITION_SCALAR_KEYS,
)
_SUBSCRIPT_SQL = _SQLTree(
    "CompiledStorageSQLMapSub",
    "AccessType, DataAccess, Delimiter, Expression, LoopInitValue, NextCode, NullMarker, "
    "StartValue, StopExpression, StopValue",
    StorageSQLMapSub,
    STORAGE_SQL_MAP_SUB_SCALAR_KEYS,
    children=(("access_vars", _ACCESS_VAR_SQL), ("invalid_conditions", _INVALID_CONDITION_SQL)),
)
_SQL_MAP_SQL = _SQLTree(
    "CompiledStorageSQLMap",
    "BlockCount, Condition, ConditionFields, ConditionalWithHostVars, _Global, PopulationPct, "
    "PopulationType, RowReference, Structure, Type",
    StorageSQLMap,
    STORAGE_SQL_MAP_SCALAR_KEYS,
    bool_attrs=("conditional_with_host_vars",),
    children=(
        (
            "data",
            _SQLTree(
                "CompiledStorageSQLMapData",
                "Node, Piece, Delimiter, RetrievalCode",
                StorageSQLMapData,
                STORAGE_SQL_MAP_DATA_SCALAR_KEYS,
            ),
        ),
        (
            "row_id_specs",
            _SQLTree(
                "CompiledStorageSQLMapRowIdSpec",
                "Field, Expression",
                StorageSQLMapRowIdSpec,
                STORAGE_SQL_MAP_ROW_ID_SPEC_SCALAR_KEYS,
            ),
        ),
        ("subscripts", _SUBSCRIPT_SQL),
    ),
)


class _CompiledDictionaryReader(DictionarySession):
    """Thin reader for the %Dictionary compiled metadata used by scaffolding."""

    def __init__(self, conn: Any, runtime: Any | None = None):
        super().__init__(conn)
        self._runtime = runtime

    def close(self) -> None:
        super().close()

    def _fetchall(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        return self.fetchall(sql, params)

    def _fetchone(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        return self.fetchone(sql, params)

    def _optional_rows(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        try:
            return self._fetchall(sql, params)
        except Exception:
            return []

    def _fetch_tree(self, parent: str, spec: _SQLTree) -> tuple[Any, ...]:
        rows = self._fetchall(
            f"SELECT Name, {spec.columns} FROM %Dictionary.{spec.table} WHERE parent = ?",
            (parent,),
        )
        items = []
        for row in rows:
            name = str(row[0])
            kwargs = _row_model_kwargs(row, spec.attrs, bool_attrs=spec.bool_attrs)
            child_parent = f"{parent}||{name}"
            kwargs.update(
                (attr_name, self._fetch_tree(child_parent, child_spec))
                for attr_name, child_spec in spec.children
            )
            items.append(spec.model(name=name, **kwargs))
        return tuple(sorted(items, key=lambda item: item.name))

    def _normalize_parameters(
        self,
        rows: list[tuple[Any, ...]],
        *,
        parent: str | None = None,
        origin_index: int | None = None,
    ) -> list[_CompiledParameter]:
        params = []
        for row in rows:
            name = row[0]
            default = row[1]
            if str(name).startswith("%") or name == "GUID":
                continue
            if parent is not None and origin_index is not None:
                origin = row[origin_index]
                if origin not in (None, "", parent):
                    continue
            params.append(_CompiledParameter(name=str(name), default=str(default)))
        return params

    def _parameter_belongs_to_class(self, runtime: Any, param: Any, classname: str) -> bool:
        return item_belongs_to_class(runtime, param, classname)

    def list_classes(self, pattern: str) -> list[_CompiledClass]:
        rows = self._fetchall(
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            (pattern,),
        )
        return sorted(
            (_CompiledClass(name=row[0], superclasses=row[1]) for row in rows),
            key=lambda item: item.name,
        )

    def get_class(self, classname: str) -> _CompiledClass | None:
        row = self._fetchone(
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name = ?",
            (classname,),
        )
        if row is None:
            return None
        return _CompiledClass(name=row[0], superclasses=row[1])

    def get_class_metadata(self, classname: str) -> _CompiledClass | None:
        row = self._fetchone(
            (
                "SELECT Description, Deprecated, Final, SqlTableName, ProcedureBlock "
                "FROM %Dictionary.CompiledClass WHERE Name = ?"
            ),
            (classname,),
        )
        if row is None:
            return None
        return _CompiledClass(
            name=classname,
            superclasses=None,
            description=_optional_str(row[0]),
            deprecated=coerce_bool(row[1]),
            final=coerce_bool(row[2]),
            sql_table_name=_optional_str(row[3]),
            procedure_block=coerce_bool(row[4]),
        )

    def list_properties(self, classname: str) -> list[_CompiledProperty]:
        property_rows = self._fetchall(
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            (classname,),
        )
        metadata_by_name: dict[str, dict[str, Any]] = {}
        projections = (
            (
                "Identity, Relationship, OnDelete, Inverse, Transient, Storable, MultiDimensional",
                (
                    "identity",
                    "relationship",
                    "on_delete",
                    "inverse",
                    "transient",
                    "storable",
                    "multi_dimensional",
                ),
            ),
            (
                "SqlListDelimiter, SqlListType, SqlComputeCode, SqlComputeOnChange, SqlComputed",
                (
                    "sql_list_delimiter",
                    "sql_list_type",
                    "sql_compute_code",
                    "sql_compute_on_change",
                    "sql_computed",
                ),
            ),
        )
        for columns, keys in projections:
            projection_rows = self._optional_rows(
                f"SELECT Name, {columns} FROM %Dictionary.CompiledProperty WHERE parent = ?",
                (classname,),
            )
            for row in projection_rows:
                metadata_by_name.setdefault(str(row[0]), {}).update(zip(keys, row[1:]))
        properties = []
        for (
            prop_name,
            prop_type,
            required,
            init_exp,
            params_raw,
            collection,
            sql_field_name,
            readonly,
        ) in property_rows:
            if str(prop_name).startswith("%"):
                continue
            parsed_params = _parse_iris_dict(params_raw) if params_raw else {}
            metadata = metadata_by_name.get(str(prop_name), {})
            properties.append(
                _CompiledProperty(
                    name=prop_name,
                    iris_type=prop_type,
                    python_type=python_annotation_for_iris_type(prop_type),
                    required=coerce_bool(required),
                    default=init_exp if init_exp != '""' and init_exp else None,
                    maxlen=parsed_params.get("MAXLEN"),
                    readonly=coerce_bool(readonly),
                    collection=_optional_str(collection),
                    sql_field_name=(
                        None
                        if not sql_field_name or str(sql_field_name) == str(prop_name)
                        else str(sql_field_name)
                    ),
                    identity=coerce_bool(metadata.get("identity")),
                    relationship=_optional_str(metadata.get("relationship")),
                    on_delete=_optional_str(metadata.get("on_delete")),
                    inverse=_optional_str(metadata.get("inverse")),
                    transient=coerce_bool(metadata.get("transient")),
                    storable=(
                        True
                        if metadata.get("storable") is None
                        else coerce_bool(metadata.get("storable"))
                    ),
                    multi_dimensional=coerce_bool(metadata.get("multi_dimensional")),
                    sql_list_delimiter=_optional_str(metadata.get("sql_list_delimiter")),
                    sql_list_type=_optional_str(metadata.get("sql_list_type")),
                    sql_compute_code=_optional_str(metadata.get("sql_compute_code")),
                    sql_compute_on_change=_optional_str(metadata.get("sql_compute_on_change")),
                    sql_computed=coerce_bool(metadata.get("sql_computed")),
                )
            )
        if properties and any(item.maxlen is None for item in properties):
            try:
                runtime = self._runtime or get_runtime()
                class_def = runtime.get_object("%Dictionary.ClassDefinition", classname)
                if class_def is not None:
                    prop_list = runtime.get_property(class_def, "Properties")
                    if prop_list is not None:
                        count = runtime.invoke_method(prop_list, "Count")
                        maxlen_by_name: dict[str, str] = {}
                        for index in range(1, count + 1):
                            prop = runtime.invoke_method(prop_list, "GetAt", index)
                            name = runtime.get_property(prop, "Name")
                            if not name:
                                continue
                            params = runtime.get_property(prop, "Parameters")
                            if params is None:
                                continue
                            try:
                                maxlen = runtime.invoke_method(params, "GetAt", "MAXLEN")
                            except Exception:
                                maxlen = None
                            if maxlen not in (None, ""):
                                maxlen_by_name[str(name)] = str(maxlen)
                        if maxlen_by_name:
                            properties = [
                                item
                                if item.maxlen is not None or item.name not in maxlen_by_name
                                else replace(item, maxlen=maxlen_by_name[item.name])
                                for item in properties
                            ]
            except Exception:
                pass
        return sorted(properties, key=lambda item: item.name)

    def list_parameters(self, classname: str) -> list[_CompiledParameter]:
        params = self._normalize_parameters(
            self._fetchall(
                "SELECT Name, _Default, Origin FROM %Dictionary.CompiledParameter WHERE parent = ?",
                (classname,),
            ),
            parent=classname,
            origin_index=2,
        )
        if params:
            return sorted(params, key=lambda item: item.name)

        try:
            params = self._normalize_parameters(
                self._fetchall(
                    "SELECT Name, Default FROM %Dictionary.ParameterDefinition WHERE parent = ?",
                    (classname,),
                )
            )
        except Exception:
            params = []
        if params:
            return sorted(params, key=lambda item: item.name)

        try:
            runtime = self._runtime or get_runtime()
            class_def = runtime.get_object("%Dictionary.ClassDefinition", classname)
            if class_def is not None:
                param_list = runtime.get_property(class_def, "Parameters")
                if param_list is not None:
                    count = runtime.invoke_method(param_list, "Count")
                    for index in range(1, count + 1):
                        param = runtime.invoke_method(param_list, "GetAt", index)
                        if not self._parameter_belongs_to_class(runtime, param, classname):
                            continue
                        name = runtime.get_property(param, "Name")
                        default = runtime.get_property(param, "Default")
                        if str(name).startswith("%") or name == "GUID":
                            continue
                        params.append(_CompiledParameter(name=str(name), default=str(default)))
        except Exception:
            pass
        return sorted(params, key=lambda item: item.name)

    def list_indexes(self, classname: str) -> list[_CompiledIndex]:
        rows = self._fetchall(
            (
                "SELECT Name, Properties, _Unique, Type, PrimaryKey "
                "FROM %Dictionary.CompiledIndex WHERE parent = ?"
            ),
            (classname,),
        )
        indexes = []
        for name, properties, is_unique, index_type, primary_key in rows:
            if str(name).startswith("%") or name in ("IDKEY", "$Product"):
                continue
            unique = coerce_bool(is_unique)
            is_primary_key = coerce_bool(primary_key)
            indexes.append(
                _CompiledIndex(
                    name=name,
                    properties=properties,
                    unique=unique,
                    index_type=_optional_str(index_type),
                    primary_key=is_primary_key,
                )
            )
        return sorted(indexes, key=lambda item: item.name)

    def get_storage(
        self,
        classname: str,
        *,
        include_hidden: bool = False,
    ) -> _CompiledStorage | None:
        storage_fields = (
            (
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
                ("Type", "type"),
            )
            if include_hidden
            else (
                ("DataLocation", "data_location"),
                ("DefaultData", "default_data"),
                ("ExtentSize", "extent_size"),
                ("IdLocation", "id_location"),
                ("IndexLocation", "index_location"),
                ("State", "state"),
                ("StreamLocation", "stream_location"),
                ("Type", "type"),
            )
        )
        if include_hidden:
            attrs = tuple(attr for _, attr in storage_fields)
        else:
            attrs = (
                "data_location",
                "default_data",
                "extent_size",
                "id_location",
                "index_location",
                "state",
                "stream_location",
                "type",
            )
        columns = ", ".join(column for column, _ in storage_fields)
        row = self._fetchone(
            f"SELECT Name, {columns} FROM %Dictionary.CompiledStorage WHERE parent = ?",
            (classname,),
        )
        if row is None:
            return None
        values: dict[str, Any] = {attr: None for attr in STORAGE_SCALAR_KEYS}
        values["name"] = str(row[0])
        values.update(_row_model_kwargs(row, attrs))
        return _CompiledStorage(**values)

    def list_storage_data(self, storage_parent: str) -> list[StorageData]:
        rows = self._fetchall(
            (
                "SELECT Name, Structure, Attribute, Subscript "
                "FROM %Dictionary.CompiledStorageData WHERE parent = ?"
            ),
            (storage_parent,),
        )
        data_rows = []
        for name, structure, attribute, subscript in rows:
            values_parent = f"{storage_parent}||{name}"
            value_rows = self._fetchall(
                "SELECT Name, Value FROM %Dictionary.CompiledStorageDataValue WHERE parent = ?",
                (values_parent,),
            )
            values = dict(
                sorted(((str(key), str(val)) for key, val in value_rows), key=_sort_storage_key)
            )
            data_rows.append(
                StorageData(
                    name=name,
                    structure=structure,
                    attribute=attribute or None,
                    subscript=subscript or None,
                    values=values,
                )
            )
        return sorted(data_rows, key=lambda item: item.name)

    def _list_storage_property_rows(
        self,
        table_name: str,
        storage_parent: str,
        include_hidden: bool,
    ) -> list[StorageProperty]:
        if include_hidden:
            rows = self._fetchall(
                (
                    "SELECT Name, AverageFieldSize, Selectivity, OutlierSelectivity, Histogram, "
                    "ChildBlockCount, ChildExtentSize, BiasQueriesAsOutlier, StreamLocation "
                    f"FROM {table_name} WHERE parent = ?"
                ),
                (storage_parent,),
            )
        else:
            rows = self._fetchall(
                (
                    "SELECT Name, AverageFieldSize, Selectivity, OutlierSelectivity "
                    f"FROM {table_name} WHERE parent = ?"
                ),
                (storage_parent,),
            )
        properties = []
        for row in rows:
            values = row if include_hidden else (*row, None, None, None, None, None)
            (
                name,
                avg,
                selectivity,
                outlier_selectivity,
                histogram,
                child_block_count,
                child_extent_size,
                bias_queries_as_outlier,
                stream_location,
            ) = values
            average_field_size = _optional_str(avg)
            selectivity_value = _optional_str(selectivity)
            outlier_selectivity_value = _optional_str(outlier_selectivity)
            histogram_value = _optional_str(histogram)
            child_block_count_value = _optional_str(child_block_count)
            child_extent_size_value = _optional_str(child_extent_size)
            bias_queries_as_outlier_value = (
                coerce_bool(bias_queries_as_outlier)
                if bias_queries_as_outlier is not None and bias_queries_as_outlier != ""
                else None
            )
            stream_location_value = _optional_str(stream_location)
            if str(name).startswith("%") or not _has_storage_property_metadata(
                average_field_size=average_field_size,
                selectivity=selectivity_value,
                outlier_selectivity=outlier_selectivity_value,
                histogram=histogram_value,
                child_block_count=child_block_count_value,
                child_extent_size=child_extent_size_value,
                bias_queries_as_outlier=bias_queries_as_outlier_value,
                stream_location=stream_location_value,
            ):
                continue
            properties.append(
                StorageProperty(
                    name=str(name),
                    average_field_size=average_field_size,
                    selectivity=selectivity_value,
                    outlier_selectivity=outlier_selectivity_value,
                    histogram=histogram_value,
                    child_block_count=child_block_count_value,
                    child_extent_size=child_extent_size_value,
                    bias_queries_as_outlier=bias_queries_as_outlier_value,
                    stream_location=stream_location_value,
                )
            )
        return sorted(properties, key=lambda item: item.name)

    def list_storage_properties(
        self,
        storage_parent: str,
        *,
        include_hidden: bool = False,
    ) -> list[StorageProperty]:
        return self._list_storage_property_rows(
            "%Dictionary.CompiledStorageProperty",
            storage_parent,
            include_hidden,
        )

    def list_storage_property_definitions(
        self,
        storage_parent: str,
        *,
        include_hidden: bool = False,
    ) -> list[StorageProperty]:
        return self._list_storage_property_rows(
            "%Dictionary.StoragePropertyDefinition",
            storage_parent,
            include_hidden,
        )

    def list_storage_indices(self, storage_parent: str) -> list[StorageIndex]:
        rows = self._fetchall(
            (
                "SELECT Name, Location, SmallChunkSize "
                "FROM %Dictionary.CompiledStorageIndex WHERE parent = ?"
            ),
            (storage_parent,),
        )
        return sorted(
            (_row_model(StorageIndex, row, ("location", "small_chunk_size")) for row in rows),
            key=lambda item: item.name,
        )

    def list_storage_sql_maps(self, storage_parent: str) -> list[StorageSQLMap]:
        return list(self._fetch_tree(storage_parent, _SQL_MAP_SQL))
