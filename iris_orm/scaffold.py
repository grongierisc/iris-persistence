from __future__ import annotations

import re
import warnings as py_warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iris_orm.runtime import get_runtime


def _map_iris_type_to_python(iris_type: str) -> str:
    """Map an IRIS type to a Python type string for the generated class."""
    if not iris_type:
        return "Any"

    mapping = {
        "%Library.String": "str",
        "%Library.Integer": "int",
        "%Library.Float": "float",
        "%Library.Double": "float",
        "%Library.Decimal": "float",
        "%Library.Boolean": "bool",
        "%Stream.GlobalBinary": "bytes",
        "%Stream.FileBinary": "bytes",
        "%Stream.GlobalCharacter": "str",
        "%Stream.FileCharacter": "str",
        "%Library.DynamicObject": "dict",
        "%Library.DynamicArray": "list",
        "%Library.Date": "datetime.date",
        "%Library.Time": "datetime.time",
        "%Library.TimeStamp": "datetime.datetime",
    }

    if iris_type in mapping:
        return mapping[iris_type]
    if iris_type in {
        "%List",
        "%ListOfDataTypes",
        "%ListOfObjects",
        "%ArrayOfDataTypes",
        "%ArrayOfObjects",
        "%Library.List",
        "%Library.ListOfDataTypes",
        "%Library.ListOfObjects",
        "%Library.ArrayOfDataTypes",
        "%Library.ArrayOfObjects",
    }:
        return "Any"
    if iris_type.startswith("%"):
        return "str"
    return "Any"


def _collection_from_iris_type(iris_type: str | None) -> str | None:
    if iris_type in {
        "%List",
        "%ListOfDataTypes",
        "%ListOfObjects",
        "%Library.List",
        "%Library.ListOfDataTypes",
        "%Library.ListOfObjects",
    }:
        return "list"
    if iris_type in {
        "%ArrayOfDataTypes",
        "%ArrayOfObjects",
        "%Library.ArrayOfDataTypes",
        "%Library.ArrayOfObjects",
    }:
        return "array"
    return None


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


def _as_bool(value: Any) -> bool:
    return value == 1 or value == "1" or str(value).lower() == "true"


def _optional_str(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _has_storage_property_metadata(
    *,
    average_field_size: str | None,
    selectivity: str | None,
    outlier_selectivity: str | None,
    histogram: str | None,
    child_block_count: str | None,
    child_extent_size: str | None,
    bias_queries_as_outlier: bool | None,
    stream_location: str | None,
) -> bool:
    return any(
        value is not None
        for value in (
            average_field_size,
            selectivity,
            outlier_selectivity,
            histogram,
            child_block_count,
            child_extent_size,
            bias_queries_as_outlier,
            stream_location,
        )
    )


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


@dataclass(frozen=True)
class _CompiledStorage:
    name: str
    data_location: str | None
    default_data: str | None
    extent_location: str | None
    extent_size: str | None
    counter_location: str | None
    version_location: str | None
    id_location: str | None
    id_expression: str | None
    id_function: str | None
    index_location: str | None
    state: str | None
    stream_location: str | None
    sql_child_sub: str | None
    sql_id_expression: str | None
    sql_row_id_name: str | None
    sql_row_id_property: str | None
    sql_table_number: str | None
    sequence_number: str | None
    storage_type: str | None


@dataclass(frozen=True)
class _CompiledStorageData:
    name: str
    structure: str | None
    attribute: str | None
    subscript: str | None
    values: dict[str, str]


@dataclass(frozen=True)
class _CompiledStorageProperty:
    name: str
    average_field_size: str | None
    selectivity: str | None
    outlier_selectivity: str | None
    histogram: str | None
    child_block_count: str | None
    child_extent_size: str | None
    bias_queries_as_outlier: bool | None
    stream_location: str | None


@dataclass(frozen=True)
class _CompiledStorageIndex:
    name: str
    location: str | None
    small_chunk_size: str | None


@dataclass(frozen=True)
class _CompiledStorageSQLMap:
    name: str
    block_count: str | None
    condition: str | None
    condition_fields: str | None
    conditional_with_host_vars: bool
    global_name: str | None
    population_pct: str | None
    population_type: str | None
    row_reference: str | None
    structure: str | None
    map_type: str | None
    data: tuple[_CompiledStorageSQLMapData, ...]
    row_id_specs: tuple[_CompiledStorageSQLMapRowIdSpec, ...]
    subscripts: tuple[_CompiledStorageSQLMapSub, ...]


@dataclass(frozen=True)
class _CompiledStorageSQLMapData:
    name: str
    node: str | None
    piece: str | None
    delimiter: str | None
    retrieval_code: str | None


@dataclass(frozen=True)
class _CompiledStorageSQLMapRowIdSpec:
    name: str
    field: str | None
    expression: str | None


@dataclass(frozen=True)
class _CompiledStorageSQLMapSubAccessVar:
    name: str
    variable: str | None
    code: str | None


@dataclass(frozen=True)
class _CompiledStorageSQLMapSubInvalidCondition:
    name: str
    expression: str | None


@dataclass(frozen=True)
class _CompiledStorageSQLMapSub:
    name: str
    access_type: str | None
    data_access: str | None
    delimiter: str | None
    expression: str | None
    loop_init_value: str | None
    next_code: str | None
    null_marker: str | None
    start_value: str | None
    stop_expression: str | None
    stop_value: str | None
    access_vars: tuple[_CompiledStorageSQLMapSubAccessVar, ...]
    invalid_conditions: tuple[_CompiledStorageSQLMapSubInvalidCondition, ...]


class _CompiledDictionaryReader:
    """Thin reader for the %Dictionary compiled metadata used by scaffolding."""

    def __init__(self, conn: Any):
        self._conn = conn
        self._cursor = conn.cursor()

    def close(self) -> None:
        self._cursor.close()
        self._conn.close()

    def _fetchall(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        self._cursor.execute(sql, params)
        return list(self._cursor.fetchall())

    def _fetchone(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        self._cursor.execute(sql, params)
        return self._cursor.fetchone()

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

    def list_properties(self, classname: str) -> list[_CompiledProperty]:
        rows = self._fetchall(
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            (classname,),
        )
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
        ) in rows:
            if str(prop_name).startswith("%"):
                continue
            parsed_params = _parse_iris_dict(params_raw) if params_raw else {}
            properties.append(
                _CompiledProperty(
                    name=prop_name,
                    iris_type=prop_type,
                    python_type=_map_iris_type_to_python(prop_type),
                    required=_as_bool(required),
                    default=init_exp if init_exp != '""' and init_exp else None,
                    maxlen=parsed_params.get("MAXLEN"),
                    readonly=_as_bool(readonly),
                    collection=_optional_str(collection),
                    sql_field_name=(
                        None
                        if not sql_field_name or str(sql_field_name) == str(prop_name)
                        else str(sql_field_name)
                    ),
                )
            )
        return sorted(properties, key=lambda item: item.name)

    def list_parameters(self, classname: str) -> list[_CompiledParameter]:
        rows = self._fetchall(
            "SELECT Name, Default FROM %Dictionary.CompiledParameter WHERE parent = ?",
            (classname,),
        )
        params = []
        for name, default in rows:
            if str(name).startswith("%") or name == "GUID":
                continue
            params.append(_CompiledParameter(name=name, default=str(default)))
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
            unique = _as_bool(is_unique)
            is_primary_key = _as_bool(primary_key)
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
        if include_hidden:
            row = self._fetchone(
                (
                    "SELECT Name, DataLocation, DefaultData, ExtentLocation, ExtentSize, "
                    "CounterLocation, VersionLocation, IdLocation, IdExpression, IdFunction, "
                    "IndexLocation, State, StreamLocation, SqlChildSub, SqlIdExpression, "
                    "SqlRowIdName, SqlRowIdProperty, SqlTableNumber, SequenceNumber, Type "
                    "FROM %Dictionary.CompiledStorage WHERE parent = ?"
                ),
                (classname,),
            )
        else:
            row = self._fetchone(
                (
                    "SELECT Name, DataLocation, DefaultData, ExtentSize, IdLocation, "
                    "IndexLocation, State, StreamLocation, Type "
                    "FROM %Dictionary.CompiledStorage WHERE parent = ?"
                ),
                (classname,),
            )
        if row is None:
            return None
        if not include_hidden:
            return _CompiledStorage(
                name=str(row[0]),
                data_location=_optional_str(row[1]),
                default_data=_optional_str(row[2]),
                extent_location=None,
                extent_size=_optional_str(row[3]),
                counter_location=None,
                version_location=None,
                id_location=_optional_str(row[4]),
                id_expression=None,
                id_function=None,
                index_location=_optional_str(row[5]),
                state=_optional_str(row[6]),
                stream_location=_optional_str(row[7]),
                sql_child_sub=None,
                sql_id_expression=None,
                sql_row_id_name=None,
                sql_row_id_property=None,
                sql_table_number=None,
                sequence_number=None,
                storage_type=_optional_str(row[8]),
            )
        return _CompiledStorage(
            name=str(row[0]),
            data_location=_optional_str(row[1]),
            default_data=_optional_str(row[2]),
            extent_location=_optional_str(row[3]),
            extent_size=_optional_str(row[4]),
            counter_location=_optional_str(row[5]),
            version_location=_optional_str(row[6]),
            id_location=_optional_str(row[7]),
            id_expression=_optional_str(row[8]),
            id_function=_optional_str(row[9]),
            index_location=_optional_str(row[10]),
            state=_optional_str(row[11]),
            stream_location=_optional_str(row[12]),
            sql_child_sub=_optional_str(row[13]),
            sql_id_expression=_optional_str(row[14]),
            sql_row_id_name=_optional_str(row[15]),
            sql_row_id_property=_optional_str(row[16]),
            sql_table_number=_optional_str(row[17]),
            sequence_number=_optional_str(row[18]),
            storage_type=_optional_str(row[19]),
        )

    def list_storage_data(self, storage_parent: str) -> list[_CompiledStorageData]:
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
                _CompiledStorageData(
                    name=name,
                    structure=structure,
                    attribute=attribute or None,
                    subscript=subscript or None,
                    values=values,
                )
            )
        return sorted(data_rows, key=lambda item: item.name)

    def list_storage_properties(
        self,
        storage_parent: str,
        *,
        include_hidden: bool = False,
    ) -> list[_CompiledStorageProperty]:
        if include_hidden:
            rows = self._fetchall(
                (
                    "SELECT Name, AverageFieldSize, Selectivity, OutlierSelectivity, Histogram, "
                    "ChildBlockCount, ChildExtentSize, BiasQueriesAsOutlier, StreamLocation "
                    "FROM %Dictionary.CompiledStorageProperty WHERE parent = ?"
                ),
                (storage_parent,),
            )
        else:
            rows = self._fetchall(
                (
                    "SELECT Name, AverageFieldSize, Selectivity, OutlierSelectivity "
                    "FROM %Dictionary.CompiledStorageProperty WHERE parent = ?"
                ),
                (storage_parent,),
            )
        properties = []
        for row in rows:
            if include_hidden:
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
                ) = row
            else:
                name, avg, selectivity, outlier_selectivity = row
                histogram = None
                child_block_count = None
                child_extent_size = None
                bias_queries_as_outlier = None
                stream_location = None
            average_field_size = _optional_str(avg)
            selectivity_value = _optional_str(selectivity)
            outlier_selectivity_value = _optional_str(outlier_selectivity)
            histogram_value = _optional_str(histogram)
            child_block_count_value = _optional_str(child_block_count)
            child_extent_size_value = _optional_str(child_extent_size)
            bias_queries_as_outlier_value = (
                _as_bool(bias_queries_as_outlier)
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
                _CompiledStorageProperty(
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

    def list_storage_property_definitions(
        self,
        storage_parent: str,
        *,
        include_hidden: bool = False,
    ) -> list[_CompiledStorageProperty]:
        if include_hidden:
            rows = self._fetchall(
                (
                    "SELECT Name, AverageFieldSize, Selectivity, OutlierSelectivity, Histogram, "
                    "ChildBlockCount, ChildExtentSize, BiasQueriesAsOutlier, StreamLocation "
                    "FROM %Dictionary.StoragePropertyDefinition WHERE parent = ?"
                ),
                (storage_parent,),
            )
        else:
            rows = self._fetchall(
                (
                    "SELECT Name, AverageFieldSize, Selectivity, OutlierSelectivity "
                    "FROM %Dictionary.StoragePropertyDefinition WHERE parent = ?"
                ),
                (storage_parent,),
            )
        properties = []
        for row in rows:
            if include_hidden:
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
                ) = row
            else:
                name, avg, selectivity, outlier_selectivity = row
                histogram = None
                child_block_count = None
                child_extent_size = None
                bias_queries_as_outlier = None
                stream_location = None
            average_field_size = _optional_str(avg)
            selectivity_value = _optional_str(selectivity)
            outlier_selectivity_value = _optional_str(outlier_selectivity)
            histogram_value = _optional_str(histogram)
            child_block_count_value = _optional_str(child_block_count)
            child_extent_size_value = _optional_str(child_extent_size)
            bias_queries_as_outlier_value = (
                _as_bool(bias_queries_as_outlier)
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
                _CompiledStorageProperty(
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

    def list_storage_indices(self, storage_parent: str) -> list[_CompiledStorageIndex]:
        rows = self._fetchall(
            (
                "SELECT Name, Location, SmallChunkSize "
                "FROM %Dictionary.CompiledStorageIndex WHERE parent = ?"
            ),
            (storage_parent,),
        )
        return sorted(
            (
                _CompiledStorageIndex(
                    name=str(name),
                    location=_optional_str(location),
                    small_chunk_size=_optional_str(small_chunk_size),
                )
                for name, location, small_chunk_size in rows
            ),
            key=lambda item: item.name,
        )

    def list_storage_sql_maps(self, storage_parent: str) -> list[_CompiledStorageSQLMap]:
        rows = self._fetchall(
            (
                "SELECT Name, BlockCount, Condition, ConditionFields, ConditionalWithHostVars, "
                "Global, PopulationPct, PopulationType, RowReference, Structure, Type "
                "FROM %Dictionary.CompiledStorageSQLMap WHERE parent = ?"
            ),
            (storage_parent,),
        )
        sql_maps = []
        for (
            name,
            block_count,
            condition,
            condition_fields,
            conditional_with_host_vars,
            global_name,
            population_pct,
            population_type,
            row_reference,
            structure,
            map_type,
        ) in rows:
            data_parent = f"{storage_parent}||{name}"
            data_rows = self._fetchall(
                (
                    "SELECT Name, Node, Piece, Delimiter, RetrievalCode "
                    "FROM %Dictionary.CompiledStorageSQLMapData WHERE parent = ?"
                ),
                (data_parent,),
            )
            data = tuple(
                _CompiledStorageSQLMapData(
                    name=str(data_name),
                    node=_optional_str(node),
                    piece=_optional_str(piece),
                    delimiter=_optional_str(delimiter),
                    retrieval_code=_optional_str(retrieval_code),
                )
                for data_name, node, piece, delimiter, retrieval_code in data_rows
            )
            row_id_spec_rows = self._fetchall(
                (
                    "SELECT Name, Field, Expression "
                    "FROM %Dictionary.CompiledStorageSQLMapRowIdSpec WHERE parent = ?"
                ),
                (data_parent,),
            )
            row_id_specs = tuple(
                _CompiledStorageSQLMapRowIdSpec(
                    name=str(spec_name),
                    field=_optional_str(field),
                    expression=_optional_str(expression),
                )
                for spec_name, field, expression in row_id_spec_rows
            )
            sub_rows = self._fetchall(
                (
                    "SELECT Name, AccessType, DataAccess, Delimiter, Expression, "
                    "LoopInitValue, NextCode, NullMarker, StartValue, StopExpression, StopValue "
                    "FROM %Dictionary.CompiledStorageSQLMapSub WHERE parent = ?"
                ),
                (data_parent,),
            )
            subscripts = []
            for (
                sub_name,
                access_type,
                data_access,
                delimiter,
                expression,
                loop_init_value,
                next_code,
                null_marker,
                start_value,
                stop_expression,
                stop_value,
            ) in sub_rows:
                sub_parent = f"{data_parent}||{sub_name}"
                access_var_rows = self._fetchall(
                    (
                        "SELECT Name, Variable, Code "
                        "FROM %Dictionary.CompiledStorageSQLMapSubAccessvar WHERE parent = ?"
                    ),
                    (sub_parent,),
                )
                access_vars = tuple(
                    _CompiledStorageSQLMapSubAccessVar(
                        name=str(access_name),
                        variable=_optional_str(variable),
                        code=_optional_str(code),
                    )
                    for access_name, variable, code in access_var_rows
                )
                invalid_condition_rows = self._fetchall(
                    (
                        "SELECT Name, Expression "
                        "FROM %Dictionary.CompiledStorageSQLMapSubInvalidcondition "
                        "WHERE parent = ?"
                    ),
                    (sub_parent,),
                )
                invalid_conditions = tuple(
                    _CompiledStorageSQLMapSubInvalidCondition(
                        name=str(condition_name),
                        expression=_optional_str(invalid_expression),
                    )
                    for condition_name, invalid_expression in invalid_condition_rows
                )
                subscripts.append(
                    _CompiledStorageSQLMapSub(
                        name=str(sub_name),
                        access_type=_optional_str(access_type),
                        data_access=_optional_str(data_access),
                        delimiter=_optional_str(delimiter),
                        expression=_optional_str(expression),
                        loop_init_value=_optional_str(loop_init_value),
                        next_code=_optional_str(next_code),
                        null_marker=_optional_str(null_marker),
                        start_value=_optional_str(start_value),
                        stop_expression=_optional_str(stop_expression),
                        stop_value=_optional_str(stop_value),
                        access_vars=access_vars,
                        invalid_conditions=invalid_conditions,
                    )
                )
            sql_maps.append(
                _CompiledStorageSQLMap(
                    name=str(name),
                    block_count=_optional_str(block_count),
                    condition=_optional_str(condition),
                    condition_fields=_optional_str(condition_fields),
                    conditional_with_host_vars=_as_bool(conditional_with_host_vars),
                    global_name=_optional_str(global_name),
                    population_pct=_optional_str(population_pct),
                    population_type=_optional_str(population_type),
                    row_reference=_optional_str(row_reference),
                    structure=_optional_str(structure),
                    map_type=_optional_str(map_type),
                    data=data,
                    row_id_specs=row_id_specs,
                    subscripts=tuple(subscripts),
                )
            )
        return sorted(sql_maps, key=lambda item: item.name)


def _python_default_literal(prop: _CompiledProperty) -> tuple[str | None, str | None]:
    default = prop.default
    if default is None:
        return (None, None)
    if prop.iris_type == "%Library.Boolean" and default in {"1", "0"}:
        literal = "True" if default == "1" else "False"
        return (f"default={literal}", literal)
    if prop.python_type == "int" and re.fullmatch(r"-?\d+", default):
        return (f"default={default}", default)
    if prop.python_type == "float" and re.fullmatch(r"-?(?:\d+\.\d*|\d*\.\d+|\d+)", default):
        return (f"default={default}", default)
    if default.startswith('"') and default.endswith('"'):
        value = default[1:-1].replace('""', '"')
        literal = repr(value)
        return (f"default={literal}", literal)
    return (None, None)


def _is_custom_iris_class(iris_type: str | None) -> bool:
    return bool(iris_type) and not str(iris_type).startswith("%")


def _safe_identifier_part(part: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", part).strip("_")
    return cleaned or "model"


def _camel_case(parts: list[str]) -> str:
    tokens: list[str] = []
    for part in parts:
        cleaned = _safe_identifier_part(part)
        if not cleaned:
            continue
        for token in cleaned.split("_"):
            if not token:
                continue
            tokens.append(token[:1].upper() + token[1:])
    return "".join(tokens)


def _snake_case(parts: list[str]) -> str:
    cleaned_parts = [
        cleaned.lower()
        for part in parts
        if (cleaned := _safe_identifier_part(part))
    ]
    return "_".join(cleaned_parts)


def _assign_generated_names(
    classnames: list[str],
    preferred: list[str],
    formatter: Any,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    used: set[str] = set()
    ordered = preferred + [
        classname for classname in sorted(classnames) if classname not in preferred
    ]

    for classname in ordered:
        parts = classname.split(".")
        for depth in range(1, len(parts) + 1):
            candidate = formatter(parts[-depth:])
            if candidate and candidate not in used:
                resolved[classname] = candidate
                used.add(candidate)
                break
        else:
            candidate = formatter(parts)
            resolved[classname] = candidate
            used.add(candidate)

    return resolved


def _collect_classes(
    reader: _CompiledDictionaryReader,
    pattern: str,
    include_related: bool,
) -> tuple[list[_CompiledClass], dict[str, list[_CompiledProperty]], list[str]]:
    seed_classes = reader.list_classes(pattern)
    seed_names = [item.name for item in seed_classes]
    classes_by_name = {item.name: item for item in seed_classes}
    properties_by_class: dict[str, list[_CompiledProperty]] = {}

    if not include_related:
        return (seed_classes, properties_by_class, seed_names)

    queue = list(seed_names)
    visited = set()
    while queue:
        classname = queue.pop(0)
        if classname in visited:
            continue
        visited.add(classname)
        properties = properties_by_class.setdefault(classname, reader.list_properties(classname))
        for prop in properties:
            if not _is_custom_iris_class(prop.iris_type):
                continue
            if prop.iris_type in classes_by_name:
                if prop.iris_type not in visited:
                    queue.append(prop.iris_type)
                continue
            class_info = reader.get_class(prop.iris_type)
            if class_info is None:
                continue
            classes_by_name[class_info.name] = class_info
            queue.append(class_info.name)

    return (
        sorted(classes_by_name.values(), key=lambda item: item.name),
        properties_by_class,
        seed_names,
    )


def _append_literal_arg(args: list[str], name: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        args.append(f"{name}={'True' if value else 'False'}")
    else:
        args.append(f"{name}={value!r}")


def _double_quoted_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _render_property_type(
    prop: _CompiledProperty,
    python_class_names: dict[str, str],
) -> str:
    if prop.iris_type in python_class_names:
        base_type = python_class_names[prop.iris_type]
    elif _is_custom_iris_class(prop.iris_type):
        base_type = "Any"
    else:
        base_type = prop.python_type

    collection = prop.collection or _collection_from_iris_type(prop.iris_type)
    if collection == "list":
        return f"list[{base_type}]"
    if collection == "array":
        return f"dict[str, {base_type}]"
    return base_type


def _render_storage_sql_map_data(item: _CompiledStorageSQLMapData) -> str:
    args = [f"name={item.name!r}"]
    _append_literal_arg(args, "node", item.node)
    _append_literal_arg(args, "piece", item.piece)
    _append_literal_arg(args, "delimiter", item.delimiter)
    _append_literal_arg(args, "retrieval_code", item.retrieval_code)
    return f"StorageSQLMapData({', '.join(args)})"


def _render_storage_sql_map_row_id_spec(item: _CompiledStorageSQLMapRowIdSpec) -> str:
    args = [f"name={item.name!r}"]
    _append_literal_arg(args, "field", item.field)
    _append_literal_arg(args, "expression", item.expression)
    return f"StorageSQLMapRowIdSpec({', '.join(args)})"


def _render_storage_sql_map_sub_access_var(item: _CompiledStorageSQLMapSubAccessVar) -> str:
    args = [f"name={item.name!r}"]
    _append_literal_arg(args, "variable", item.variable)
    _append_literal_arg(args, "code", item.code)
    return f"StorageSQLMapSubAccessVar({', '.join(args)})"


def _render_storage_sql_map_sub_invalid_condition(
    item: _CompiledStorageSQLMapSubInvalidCondition,
) -> str:
    args = [f"name={item.name!r}"]
    _append_literal_arg(args, "expression", item.expression)
    return f"StorageSQLMapSubInvalidCondition({', '.join(args)})"


def _render_storage_sql_map_sub(item: _CompiledStorageSQLMapSub) -> list[str]:
    args = [f"name={item.name!r}"]
    _append_literal_arg(args, "access_type", item.access_type)
    _append_literal_arg(args, "data_access", item.data_access)
    _append_literal_arg(args, "delimiter", item.delimiter)
    _append_literal_arg(args, "expression", item.expression)
    _append_literal_arg(args, "loop_init_value", item.loop_init_value)
    _append_literal_arg(args, "next_code", item.next_code)
    _append_literal_arg(args, "null_marker", item.null_marker)
    _append_literal_arg(args, "start_value", item.start_value)
    _append_literal_arg(args, "stop_expression", item.stop_expression)
    _append_literal_arg(args, "stop_value", item.stop_value)

    has_nested = bool(item.access_vars or item.invalid_conditions)
    first_line = f"StorageSQLMapSub({', '.join(args)}"
    if has_nested:
        first_line += ","
    lines = [first_line]
    if item.access_vars:
        lines.append("    access_vars=(")
        lines.extend(
            f"        {_render_storage_sql_map_sub_access_var(access_var)},"
            for access_var in item.access_vars
        )
        lines.append("    ),")
    if item.invalid_conditions:
        lines.append("    invalid_conditions=(")
        lines.extend(
            "        "
            f"{_render_storage_sql_map_sub_invalid_condition(condition)},"
            for condition in item.invalid_conditions
        )
        lines.append("    ),")
    lines.append(")")
    return lines


def _render_storage_sql_map(item: _CompiledStorageSQLMap) -> list[str]:
    args = [f"name={item.name!r}"]
    _append_literal_arg(args, "block_count", item.block_count)
    _append_literal_arg(args, "condition", item.condition)
    _append_literal_arg(args, "condition_fields", item.condition_fields)
    if item.conditional_with_host_vars:
        args.append("conditional_with_host_vars=True")
    _append_literal_arg(args, "global_name", item.global_name)
    _append_literal_arg(args, "population_pct", item.population_pct)
    _append_literal_arg(args, "population_type", item.population_type)
    _append_literal_arg(args, "row_reference", item.row_reference)
    _append_literal_arg(args, "structure", item.structure)
    _append_literal_arg(args, "type", item.map_type)

    has_nested = bool(item.data or item.row_id_specs or item.subscripts)
    first_line = f"StorageSQLMap({', '.join(args)}"
    if has_nested:
        first_line += ","
    lines = [first_line]
    if item.data:
        lines.append("    data=(")
        lines.extend(
            f"        {_render_storage_sql_map_data(data_item)},"
            for data_item in item.data
        )
        lines.append("    ),")
    if item.row_id_specs:
        lines.append("    row_id_specs=(")
        lines.extend(
            "        "
            f"{_render_storage_sql_map_row_id_spec(spec)},"
            for spec in item.row_id_specs
        )
        lines.append("    ),")
    if item.subscripts:
        lines.append("    subscripts=(")
        for sub in item.subscripts:
            rendered_sub = _render_storage_sql_map_sub(sub)
            lines.append(f"        {rendered_sub[0]}")
            for sub_line in rendered_sub[1:-1]:
                lines.append(f"        {sub_line}")
            lines.append(f"        {rendered_sub[-1]},")
        lines.append("    ),")
    lines.append(")")
    return lines


def _render_storage_index(item: _CompiledStorageIndex) -> str:
    args = [f"name={_double_quoted_literal(item.name)}"]
    if item.location is not None:
        args.append(f"location={_double_quoted_literal(item.location)}")
    if item.small_chunk_size is not None:
        args.append(f"small_chunk_size={_double_quoted_literal(item.small_chunk_size)}")
    return f"StorageIndex({', '.join(args)})"


def _render_model(
    class_info: _CompiledClass,
    properties: list[_CompiledProperty],
    mode: str,
    parameters: list[_CompiledParameter],
    indexes: list[_CompiledIndex],
    storage: _CompiledStorage | None,
    storage_data: list[_CompiledStorageData],
    storage_indices: list[_CompiledStorageIndex],
    storage_properties: list[_CompiledStorageProperty],
    storage_sql_maps: list[_CompiledStorageSQLMap],
    python_class_names: dict[str, str],
    module_names: dict[str, str],
) -> str:
    custom_imports = []
    for prop in properties:
        if prop.iris_type in python_class_names and prop.iris_type != class_info.name:
            module_name = module_names[prop.iris_type]
            class_name = python_class_names[prop.iris_type]
            custom_imports.append(f"from {module_name} import {class_name}")

    lines = [
        "from __future__ import annotations",
        "",
        "import datetime",
        "from typing import Annotated, Any",
        "",
        (
            "from iris_orm import Field, IRISModel, Index, StorageDefinition, "
            "StorageData, StorageIndex, StorageProperty, StorageSQLMap, StorageSQLMapData, "
            "StorageSQLMapRowIdSpec, StorageSQLMapSub, StorageSQLMapSubAccessVar, "
            "StorageSQLMapSubInvalidCondition"
        ),
    ]
    if custom_imports:
        lines.extend(["", *sorted(set(custom_imports))])
    lines.extend(["", f"class {python_class_names[class_info.name]}(IRISModel):"])

    if not properties:
        lines.append("    pass")
    else:
        for prop in properties:
            type_name = _render_property_type(prop, python_class_names)
            field_args = [f'iris_type="{prop.iris_type}"']
            if prop.required:
                field_args.append("required=True")
            if prop.maxlen:
                field_args.append(f"maxlen={prop.maxlen}")
            if prop.readonly:
                field_args.append("readonly=True")
            if prop.collection:
                field_args.append(f"collection={prop.collection!r}")
            if prop.sql_field_name:
                field_args.append(f"sql_field_name={prop.sql_field_name!r}")
            default_arg, default_value = _python_default_literal(prop)
            if default_arg:
                field_args.append(default_arg)
            elif prop.default is not None:
                field_args.append(f"initial_expression={prop.default!r}")
            field_str = ", ".join(field_args)
            if prop.required:
                suffix = f" = {default_value}" if default_value is not None else ""
                lines.append(f"    {prop.name}: Annotated[{type_name}, Field({field_str})]{suffix}")
            else:
                suffix = f" = {default_value}" if default_value is not None else " = None"
                lines.append(
                    f"    {prop.name}: "
                    f"Annotated[{type_name} | None, Field({field_str})]{suffix}"
                )

    lines.extend(
        [
            "",
            "    class Meta:",
            f'        classname = "{class_info.name}"',
            f'        mode = "{mode}"',
        ]
    )
    if class_info.superclasses:
        lines.append(f'        superclasses = "{class_info.superclasses}"')
    if parameters:
        lines.append("        parameters = {")
        lines.extend(f'            "{param.name}": "{param.default}",' for param in parameters)
        lines.append("        }")
    if indexes:
        lines.append("        indexes = [")
        lines.extend(
            "            "
            + f'Index("{index.name}", properties="{index.properties}", '
            + f'unique={"True" if index.unique else "False"}'
            + (f', type="{index.index_type}"' if index.index_type else "")
            + (", primary_key=True" if index.primary_key else "")
            + "),"
            for index in indexes
        )
        lines.append("        ]")
    if storage:
        lines.append("        storage = StorageDefinition(")
        if storage.data_location is not None:
            lines.append(
                f"            data_location={_double_quoted_literal(storage.data_location)},"
            )
        if storage.default_data is not None:
            lines.append(
                f"            default_data={_double_quoted_literal(storage.default_data)},"
            )
        if storage.extent_location is not None:
            lines.append(
                f"            extent_location={_double_quoted_literal(storage.extent_location)},"
            )
        if storage.extent_size is not None:
            lines.append(
                f"            extent_size={_double_quoted_literal(storage.extent_size)},"
            )
        if storage.counter_location is not None:
            lines.append(
                f"            counter_location={_double_quoted_literal(storage.counter_location)},"
            )
        if storage.version_location is not None:
            lines.append(
                f"            version_location={_double_quoted_literal(storage.version_location)},"
            )
        if storage.id_location is not None:
            lines.append(
                f"            id_location={_double_quoted_literal(storage.id_location)},"
            )
        if storage.id_expression is not None:
            lines.append(
                f"            id_expression={_double_quoted_literal(storage.id_expression)},"
            )
        if storage.id_function is not None:
            lines.append(
                f"            id_function={_double_quoted_literal(storage.id_function)},"
            )
        if storage.index_location is not None:
            lines.append(
                f"            index_location={_double_quoted_literal(storage.index_location)},"
            )
        if storage.state is not None:
            lines.append(f"            state={_double_quoted_literal(storage.state)},")
        if storage.stream_location is not None:
            lines.append(
                f"            stream_location={_double_quoted_literal(storage.stream_location)},"
            )
        if storage.sql_child_sub is not None:
            lines.append(
                f"            sql_child_sub={_double_quoted_literal(storage.sql_child_sub)},"
            )
        if storage.sql_id_expression is not None:
            lines.append(
                "            "
                f"sql_id_expression={_double_quoted_literal(storage.sql_id_expression)},"
            )
        if storage.sql_row_id_name is not None:
            lines.append(
                f"            sql_row_id_name={_double_quoted_literal(storage.sql_row_id_name)},"
            )
        if storage.sql_row_id_property is not None:
            lines.append(
                "            "
                f"sql_row_id_property={_double_quoted_literal(storage.sql_row_id_property)},"
            )
        if storage.sql_table_number is not None:
            lines.append(
                f"            sql_table_number={_double_quoted_literal(storage.sql_table_number)},"
            )
        if storage.sequence_number is not None:
            lines.append(
                f"            sequence_number={_double_quoted_literal(storage.sequence_number)},"
            )
        if storage.storage_type is not None:
            lines.append(f"            type={_double_quoted_literal(storage.storage_type)},")
        if storage_data:
            lines.append("            data=(")
            for item in storage_data:
                lines.append("                StorageData(")
                lines.append(f'                    name="{item.name}",')
                if item.structure:
                    lines.append(f'                    structure="{item.structure}",')
                if item.attribute is not None:
                    lines.append(f"                    attribute={item.attribute!r},")
                if item.subscript is not None:
                    lines.append(f"                    subscript={item.subscript!r},")
                lines.append(f"                    values={item.values!r},")
                lines.append("                ),")
            lines.append("            ),")
        if storage_indices:
            lines.append("            indices=(")
            for item in storage_indices:
                lines.append(f"                {_render_storage_index(item)},")
            lines.append("            ),")
        if storage_properties:
            lines.append("            properties=(")
            for item in storage_properties:
                property_args = [f"name={_double_quoted_literal(item.name)}"]
                if item.average_field_size is not None:
                    property_args.append(
                        "average_field_size="
                        f"{_double_quoted_literal(item.average_field_size)}"
                    )
                if item.selectivity is not None:
                    property_args.append(
                        f"selectivity={_double_quoted_literal(item.selectivity)}"
                    )
                if item.outlier_selectivity is not None:
                    property_args.append(
                        "outlier_selectivity="
                        f"{_double_quoted_literal(item.outlier_selectivity)}"
                    )
                if item.histogram is not None:
                    property_args.append(
                        f"histogram={_double_quoted_literal(item.histogram)}"
                    )
                if item.child_block_count is not None:
                    property_args.append(
                        "child_block_count="
                        f"{_double_quoted_literal(item.child_block_count)}"
                    )
                if item.child_extent_size is not None:
                    property_args.append(
                        "child_extent_size="
                        f"{_double_quoted_literal(item.child_extent_size)}"
                    )
                if item.bias_queries_as_outlier is not None:
                    property_args.append(
                        "bias_queries_as_outlier="
                        f'{"True" if item.bias_queries_as_outlier else "False"}'
                    )
                if item.stream_location is not None:
                    property_args.append(
                        "stream_location="
                        f"{_double_quoted_literal(item.stream_location)}"
                    )
                lines.append(
                    "                "
                    f"StorageProperty({', '.join(property_args)}),"
                )
            lines.append("            ),")
        if storage_sql_maps:
            lines.append("            sql_maps=(")
            for item in storage_sql_maps:
                rendered_map = _render_storage_sql_map(item)
                lines.append(f"                {rendered_map[0]}")
                for map_line in rendered_map[1:-1]:
                    lines.append(f"                {map_line}")
                lines.append(f"                {rendered_map[-1]},")
            lines.append("            ),")
        lines.append("        )")

    return "\n".join(lines) + "\n"


def _merge_storage_properties(
    compiled_properties: list[_CompiledStorageProperty],
    defined_properties: list[_CompiledStorageProperty],
) -> list[_CompiledStorageProperty]:
    merged = {item.name: item for item in compiled_properties}
    for item in defined_properties:
        current = merged.get(item.name)
        if current is None:
            merged[item.name] = item
            continue
        merged[item.name] = _CompiledStorageProperty(
            name=current.name,
            average_field_size=item.average_field_size or current.average_field_size,
            selectivity=item.selectivity or current.selectivity,
            outlier_selectivity=item.outlier_selectivity or current.outlier_selectivity,
            histogram=item.histogram or current.histogram,
            child_block_count=item.child_block_count or current.child_block_count,
            child_extent_size=item.child_extent_size or current.child_extent_size,
            bias_queries_as_outlier=(
                item.bias_queries_as_outlier
                if item.bias_queries_as_outlier is not None
                else current.bias_queries_as_outlier
            ),
            stream_location=item.stream_location or current.stream_location,
        )
    return sorted(merged.values(), key=lambda item: item.name)


def _record_warning(result: ScaffoldResult, code: str, classname: str, exc: Exception) -> None:
    message = f"Failed to scaffold {code} for {classname}: {exc}"
    result.warnings.append(ScaffoldWarning(code=code, message=message, classname=classname))
    py_warnings.warn(message, RuntimeWarning, stacklevel=2)


def scaffold_from_iris(
    pattern: str,
    output_dir: str,
    mode: str = "observe",
    extract_meta: bool = False,
    extract_hidden_meta: bool = False,
    include_related: bool = False,
    scaffold_selectivity: bool = False,
    return_result: bool = False,
) -> list[str] | ScaffoldResult:
    """Scaffold typed models from live IRIS classes."""
    runtime = get_runtime()
    conn = runtime.get_dbapi_connection()
    reader = _CompiledDictionaryReader(conn)
    result = ScaffoldResult(files=[], warnings=[])

    if "*" in pattern:
        pattern = pattern.replace("*", "%")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        classes, properties_by_class, seed_names = _collect_classes(
            reader,
            pattern,
            include_related,
        )
        classnames = [item.name for item in classes]
        python_class_names = _assign_generated_names(classnames, seed_names, _camel_case)
        module_names = _assign_generated_names(classnames, seed_names, _snake_case)
        for class_info in classes:
            properties = properties_by_class.get(class_info.name)
            if properties is None:
                properties = reader.list_properties(class_info.name)

            parameters: list[_CompiledParameter] = []
            indexes: list[_CompiledIndex] = []
            storage: _CompiledStorage | None = None
            storage_data: list[_CompiledStorageData] = []
            storage_indices: list[_CompiledStorageIndex] = []
            storage_properties: list[_CompiledStorageProperty] = []
            storage_sql_maps: list[_CompiledStorageSQLMap] = []

            if extract_meta:
                try:
                    parameters = reader.list_parameters(class_info.name)
                except Exception as exc:
                    _record_warning(result, "parameters", class_info.name, exc)
                try:
                    indexes = reader.list_indexes(class_info.name)
                except Exception as exc:
                    _record_warning(result, "indexes", class_info.name, exc)
                try:
                    storage = reader.get_storage(
                        class_info.name,
                        include_hidden=extract_hidden_meta,
                    )
                    if storage:
                        storage_parent = f"{class_info.name}||{storage.name}"
                        storage_data = reader.list_storage_data(storage_parent)
                        storage_indices = reader.list_storage_indices(storage_parent)
                        storage_properties = reader.list_storage_properties(
                            storage_parent,
                            include_hidden=extract_hidden_meta,
                        )
                        if scaffold_selectivity:
                            storage_properties = _merge_storage_properties(
                                storage_properties,
                                reader.list_storage_property_definitions(
                                    storage_parent,
                                    include_hidden=extract_hidden_meta,
                                ),
                            )
                        storage_sql_maps = reader.list_storage_sql_maps(storage_parent)
                except Exception as exc:
                    _record_warning(result, "storage", class_info.name, exc)

            module_path = output_path / f"{module_names[class_info.name]}.py"
            module_text = _render_model(
                class_info=class_info,
                properties=properties,
                mode=mode,
                parameters=parameters,
                indexes=indexes,
                storage=storage,
                storage_data=storage_data,
                storage_indices=storage_indices,
                storage_properties=storage_properties,
                storage_sql_maps=storage_sql_maps,
                python_class_names=python_class_names,
                module_names=module_names,
            )
            module_path.write_text(module_text, encoding="utf-8")
            result.files.append(str(module_path))
    finally:
        reader.close()

    if return_result:
        return result
    return result.files


def scaffold_from_cls(cls_dir: str, output_dir: str, mode: str = "observe") -> None:
    """Scaffold from exported .cls files."""
    raise NotImplementedError("File scaffolding is not fully implemented yet.")
