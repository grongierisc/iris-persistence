from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from iris_persistence.catalog import DictionarySession, item_belongs_to_class
from iris_persistence.field_utils import (
    coerce_bool,
    python_annotation_for_iris_type,
)
from iris_persistence.runtime import get_runtime


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
