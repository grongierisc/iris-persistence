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


@dataclass(frozen=True)
class _CompiledParameter:
    name: str
    default: str


@dataclass(frozen=True)
class _CompiledIndex:
    name: str
    properties: str
    unique: bool


@dataclass(frozen=True)
class _CompiledStorage:
    name: str
    data_location: str | None
    default_data: str | None
    storage_type: str | None


@dataclass(frozen=True)
class _CompiledStorageData:
    name: str
    structure: str | None
    values: dict[str, str]


@dataclass(frozen=True)
class _CompiledStorageProperty:
    name: str
    average_field_size: str | None


@dataclass(frozen=True)
class _CompiledStorageSQLMap:
    name: str
    block_count: str | None


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
                "SELECT Name, Type, Required, InitialExpression, Parameters "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            (classname,),
        )
        properties = []
        for prop_name, prop_type, required, init_exp, params_raw in rows:
            if str(prop_name).startswith("%"):
                continue
            parsed_params = _parse_iris_dict(params_raw) if params_raw else {}
            properties.append(
                _CompiledProperty(
                    name=prop_name,
                    iris_type=prop_type,
                    python_type=_map_iris_type_to_python(prop_type),
                    required=bool(required) and str(required) != "0",
                    default=init_exp if init_exp != '""' and init_exp else None,
                    maxlen=parsed_params.get("MAXLEN"),
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
            "SELECT Name, Properties, _Unique FROM %Dictionary.CompiledIndex WHERE parent = ?",
            (classname,),
        )
        indexes = []
        for name, properties, is_unique in rows:
            if str(name).startswith("%") or name in ("IDKEY", "$Product"):
                continue
            unique = is_unique == 1 or is_unique == "1" or str(is_unique).lower() == "true"
            indexes.append(_CompiledIndex(name=name, properties=properties, unique=unique))
        return sorted(indexes, key=lambda item: item.name)

    def get_storage(self, classname: str) -> _CompiledStorage | None:
        row = self._fetchone(
            (
                "SELECT Name, DataLocation, DefaultData, Type "
                "FROM %Dictionary.CompiledStorage WHERE parent = ?"
            ),
            (classname,),
        )
        if row is None:
            return None
        return _CompiledStorage(
            name=row[0], data_location=row[1], default_data=row[2], storage_type=row[3]
        )

    def list_storage_data(self, storage_parent: str) -> list[_CompiledStorageData]:
        rows = self._fetchall(
            "SELECT Name, Structure FROM %Dictionary.CompiledStorageData WHERE parent = ?",
            (storage_parent,),
        )
        data_rows = []
        for name, structure in rows:
            values_parent = f"{storage_parent}||{name}"
            value_rows = self._fetchall(
                "SELECT Name, Value FROM %Dictionary.CompiledStorageDataValue WHERE parent = ?",
                (values_parent,),
            )
            values = dict(
                sorted(((str(key), str(val)) for key, val in value_rows), key=_sort_storage_key)
            )
            data_rows.append(_CompiledStorageData(name=name, structure=structure, values=values))
        return sorted(data_rows, key=lambda item: item.name)

    def list_storage_properties(self, storage_parent: str) -> list[_CompiledStorageProperty]:
        rows = self._fetchall(
            (
                "SELECT Name, AverageFieldSize "
                "FROM %Dictionary.CompiledStorageProperty WHERE parent = ?"
            ),
            (storage_parent,),
        )
        properties = [
            _CompiledStorageProperty(name=name, average_field_size=str(avg))
            for name, avg in rows
            if not str(name).startswith("%")
        ]
        return sorted(properties, key=lambda item: item.name)

    def list_storage_sql_maps(self, storage_parent: str) -> list[_CompiledStorageSQLMap]:
        rows = self._fetchall(
            "SELECT Name, BlockCount FROM %Dictionary.CompiledStorageSQLMap WHERE parent = ?",
            (storage_parent,),
        )
        return sorted(
            (
                _CompiledStorageSQLMap(name=name, block_count=str(block_count))
                for name, block_count in rows
            ),
            key=lambda item: item.name,
        )


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
            "StorageData, StorageProperty, StorageSQLMap"
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
            field_args = [f"required={'True' if prop.required else 'False'}"]
            if prop.maxlen:
                field_args.append(f"maxlen={prop.maxlen}")
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
            f'Index("{index.name}", properties="{index.properties}", '
            f'unique={"True" if index.unique else "False"}),'
            for index in indexes
        )
        lines.append("        ]")
    if storage:
        lines.append("        storage = StorageDefinition(")
        if storage.data_location:
            lines.append(f'            data_location="{storage.data_location}",')
        if storage.default_data:
            lines.append(f'            default_data="{storage.default_data}",')
        if storage.storage_type:
            lines.append(f'            type="{storage.storage_type}",')
        if storage_data:
            lines.append("            data=(")
            for item in storage_data:
                lines.append("                StorageData(")
                lines.append(f'                    name="{item.name}",')
                if item.structure:
                    lines.append(f'                    structure="{item.structure}",')
                lines.append(f"                    values={item.values!r},")
                lines.append("                ),")
            lines.append("            ),")
        if storage_properties:
            lines.append("            properties=(")
            for item in storage_properties:
                lines.append(
                    "                "
                    f'StorageProperty(name="{item.name}", '
                    f'average_field_size="{item.average_field_size}"),'
                )
            lines.append("            ),")
        if storage_sql_maps:
            lines.append("            sql_maps=(")
            for item in storage_sql_maps:
                lines.append(
                    "                "
                    f'StorageSQLMap(name="{item.name}", '
                    f'block_count="{item.block_count}"),'
                )
            lines.append("            ),")
        lines.append("        )")

    return "\n".join(lines) + "\n"


def _record_warning(result: ScaffoldResult, code: str, classname: str, exc: Exception) -> None:
    message = f"Failed to scaffold {code} for {classname}: {exc}"
    result.warnings.append(ScaffoldWarning(code=code, message=message, classname=classname))
    py_warnings.warn(message, RuntimeWarning, stacklevel=2)


def scaffold_from_iris(
    pattern: str,
    output_dir: str,
    mode: str = "observe",
    extract_meta: bool = False,
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
