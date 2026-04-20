from __future__ import annotations

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

    return mapping.get(iris_type, "str")


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
    id_location: str | None
    index_location: str | None
    state: str | None
    stream_location: str | None
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

    def get_storage(self, classname: str) -> _CompiledStorage | None:
        row = self._fetchone(
            (
                "SELECT Name, DataLocation, DefaultData, IdLocation, IndexLocation, "
                "State, StreamLocation, Type "
                "FROM %Dictionary.CompiledStorage WHERE parent = ?"
            ),
            (classname,),
        )
        if row is None:
            return None
        return _CompiledStorage(
            name=row[0],
            data_location=row[1],
            default_data=row[2],
            id_location=row[3],
            index_location=row[4],
            state=row[5],
            stream_location=row[6],
            storage_type=row[7],
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

    def list_storage_properties(self, storage_parent: str) -> list[_CompiledStorageProperty]:
        rows = self._fetchall(
            (
                "SELECT Name, AverageFieldSize, Selectivity "
                "FROM %Dictionary.CompiledStorageProperty WHERE parent = ?"
            ),
            (storage_parent,),
        )
        properties = [
            _CompiledStorageProperty(
                name=name,
                average_field_size=_optional_str(avg),
                selectivity=_optional_str(selectivity),
            )
            for name, avg, selectivity in rows
            if not str(name).startswith("%")
            and (_optional_str(avg) is not None or _optional_str(selectivity) is not None)
        ]
        return sorted(properties, key=lambda item: item.name)

    def list_storage_property_definitions(
        self, storage_parent: str
    ) -> list[_CompiledStorageProperty]:
        rows = self._fetchall(
            (
                "SELECT Name, AverageFieldSize, Selectivity "
                "FROM %Dictionary.StoragePropertyDefinition WHERE parent = ?"
            ),
            (storage_parent,),
        )
        properties = [
            _CompiledStorageProperty(
                name=str(name),
                average_field_size=_optional_str(avg),
                selectivity=_optional_str(selectivity),
            )
            for name, avg, selectivity in rows
            if not str(name).startswith("%")
            and (_optional_str(avg) is not None or _optional_str(selectivity) is not None)
        ]
        return sorted(properties, key=lambda item: item.name)

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


def _default_literal(default: str | None) -> tuple[str | None, str | None]:
    if default is None:
        return (None, None)
    if default == "1":
        return ("default=True", "True")
    if default == "0":
        return ("default=False", "False")
    if default.startswith('"') and default.endswith('"'):
        return (f"default={default}", default)
    return (f"default={default}", default)


def _append_literal_arg(args: list[str], name: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        args.append(f"{name}={'True' if value else 'False'}")
    else:
        args.append(f"{name}={value!r}")


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


def _render_model(
    class_info: _CompiledClass,
    properties: list[_CompiledProperty],
    mode: str,
    parameters: list[_CompiledParameter],
    indexes: list[_CompiledIndex],
    storage: _CompiledStorage | None,
    storage_data: list[_CompiledStorageData],
    storage_properties: list[_CompiledStorageProperty],
    storage_sql_maps: list[_CompiledStorageSQLMap],
    known_classes: dict[str, str],
) -> str:
    custom_imports = []
    for prop in properties:
        if prop.iris_type in known_classes and prop.iris_type != class_info.name:
            module_name = prop.iris_type.split(".")[-1].lower()
            class_name = known_classes[prop.iris_type]
            custom_imports.append(f"from {module_name} import {class_name}")

    lines = [
        "from __future__ import annotations",
        "",
        "import datetime",
        "from typing import Annotated, Any",
        "",
        (
            "from iris_orm import Field, IRISModel, Index, StorageDefinition, "
            "StorageData, StorageProperty, StorageSQLMap, StorageSQLMapData, "
            "StorageSQLMapRowIdSpec, StorageSQLMapSub, StorageSQLMapSubAccessVar, "
            "StorageSQLMapSubInvalidCondition"
        ),
    ]
    if custom_imports:
        lines.extend(["", *sorted(set(custom_imports))])
    lines.extend(["", f"class {class_info.name.split('.')[-1]}(IRISModel):"])

    if not properties:
        lines.append("    pass")
    else:
        for prop in properties:
            type_name = known_classes.get(prop.iris_type, prop.python_type)
            field_args = [
                f'iris_type="{prop.iris_type}"',
                f"required={'True' if prop.required else 'False'}",
            ]
            if prop.maxlen:
                field_args.append(f"maxlen={prop.maxlen}")
            if prop.readonly:
                field_args.append("readonly=True")
            if prop.collection:
                field_args.append(f"collection={prop.collection!r}")
            if prop.sql_field_name:
                field_args.append(f"sql_field_name={prop.sql_field_name!r}")
            default_arg, default_value = _default_literal(prop.default)
            if default_arg:
                field_args.append(default_arg)
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
        if storage.data_location:
            lines.append(f'            data_location="{storage.data_location}",')
        if storage.default_data:
            lines.append(f'            default_data="{storage.default_data}",')
        if storage.id_location:
            lines.append(f'            id_location="{storage.id_location}",')
        if storage.index_location:
            lines.append(f'            index_location="{storage.index_location}",')
        if storage.state:
            lines.append(f'            state="{storage.state}",')
        if storage.stream_location:
            lines.append(f'            stream_location="{storage.stream_location}",')
        if storage.storage_type:
            lines.append(f'            type="{storage.storage_type}",')
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
        if storage_properties:
            lines.append("            properties=(")
            for item in storage_properties:
                property_args = [f'name="{item.name}"']
                if item.average_field_size is not None:
                    property_args.append(
                        f'average_field_size="{item.average_field_size}"'
                    )
                if item.selectivity is not None:
                    property_args.append(f'selectivity="{item.selectivity}"')
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
        classes = reader.list_classes(pattern)
        known_classes = {item.name: item.name.split(".")[-1] for item in classes}
        for class_info in classes:
            properties = reader.list_properties(class_info.name)

            parameters: list[_CompiledParameter] = []
            indexes: list[_CompiledIndex] = []
            storage: _CompiledStorage | None = None
            storage_data: list[_CompiledStorageData] = []
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
                    storage = reader.get_storage(class_info.name)
                    if storage:
                        storage_parent = f"{class_info.name}||{storage.name}"
                        storage_data = reader.list_storage_data(storage_parent)
                        storage_properties = reader.list_storage_properties(storage_parent)
                        if scaffold_selectivity:
                            storage_properties = _merge_storage_properties(
                                storage_properties,
                                reader.list_storage_property_definitions(storage_parent),
                            )
                        storage_sql_maps = reader.list_storage_sql_maps(storage_parent)
                except Exception as exc:
                    _record_warning(result, "storage", class_info.name, exc)

            module_path = output_path / f"{class_info.name.split('.')[-1].lower()}.py"
            module_text = _render_model(
                class_info=class_info,
                properties=properties,
                mode=mode,
                parameters=parameters,
                indexes=indexes,
                storage=storage,
                storage_data=storage_data,
                storage_properties=storage_properties,
                storage_sql_maps=storage_sql_maps,
                known_classes=known_classes,
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
