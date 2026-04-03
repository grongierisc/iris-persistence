from __future__ import annotations

from contextvars import ContextVar
import importlib
from typing import Any

from .schema import (
    SchemaClass,
    coerce_to_iris_logical,
    is_array_of_datatypes,
    is_list_of_datatypes,
    is_stream_type,
    match_classnames,
    normalize_superclasses,
    read_stream_value,
    SUPPORTED_PROPERTY_PARAMETERS,
)
from .storage import StorageDefinition

_STORAGE_TOP_LEVEL_FIELDS: list[tuple[str, str]] = [
    ("counter_location", "CounterLocation"),
    ("data_location", "DataLocation"),
    ("default_data", "DefaultData"),
    ("description", "Description"),
    ("extent_location", "ExtentLocation"),
    ("extent_size", "ExtentSize"),
    ("id_expression", "IdExpression"),
    ("id_function", "IdFunction"),
    ("id_location", "IdLocation"),
    ("index_location", "IndexLocation"),
    ("sql_child_sub", "SqlChildSub"),
    ("sql_id_expression", "SqlIdExpression"),
    ("sql_row_id_name", "SqlRowIdName"),
    ("sql_row_id_property", "SqlRowIdProperty"),
    ("stream_location", "StreamLocation"),
    ("type", "Type"),
    ("version_location", "VersionLocation"),
]

_STORAGE_PROPERTY_FIELDS: list[tuple[str, str]] = [
    ("average_field_size", "AverageFieldSize"),
    ("bias_queries_as_outlier", "BiasQueriesAsOutlier"),
    ("child_block_count", "ChildBlockCount"),
    ("child_extent_size", "ChildExtentSize"),
    ("histogram", "Histogram"),
    ("outlier_selectivity", "OutlierSelectivity"),
    ("selectivity", "Selectivity"),
    ("stream_location", "StreamLocation"),
]

_STORAGE_SQL_MAP_FIELDS: list[tuple[str, str]] = [
    ("block_count", "BlockCount"),
    ("condition", "Condition"),
    ("condition_fields", "ConditionFields"),
    ("conditional_with_host_vars", "ConditionalWithHostVars"),
    ("global", "Global"),
    ("population_pct", "PopulationPct"),
    ("population_type", "PopulationType"),
    ("row_reference", "RowReference"),
    ("structure", "Structure"),
    ("type", "Type"),
]


# ---------------------------------------------------------------------------
# Internal base — shared ORM business logic
# ---------------------------------------------------------------------------

class _BaseRuntime:
    """All ORM business logic lives here.

    Subclasses set ``self.runtime`` to the IRIS native-API object and may
    override ``sql()`` (and optionally ``compile()``) to route SQL through
    a different transport (e.g. a SQLAlchemy raw connection).

    This class is an internal implementation detail.  The public contract is
    ``IRISRuntimeProtocol`` in ``iris_orm.protocol``.
    """

    # subclasses set this in __init__
    runtime: Any

    def _object_new(self, classname: str) -> Any:
        return self.runtime.cls(classname)._New()

    def _object_open(self, classname: str, obj_id: Any) -> Any:
        return self.runtime.cls(classname)._OpenId(obj_id)

    def _object_delete_id(self, classname: str, obj_id: Any) -> Any:
        return self.runtime.cls(classname)._DeleteId(obj_id)

    def _object_get(self, obj: Any, prop_name: str, iris_type: str | None = None) -> Any:
        return getattr(obj, prop_name, None)

    def _object_set(self, obj: Any, prop_name: str, value: Any) -> None:
        setattr(obj, prop_name, value)

    def _object_invoke(self, obj: Any, method_name: str, *args: Any) -> Any:
        if method_name.startswith("%"):
            method = getattr(obj, f"_{method_name[1:]}")
        else:
            method = getattr(obj, method_name)
        return method(*args)

    def _wrap_native_object(self, obj: Any, classname: str) -> Any:
        return obj

    def _schema_new(self, classname: str) -> Any:
        return self.runtime.cls(classname)._New()

    def _schema_open(self, classname: str, obj_id: Any) -> Any:
        return self.runtime.cls(classname)._OpenId(obj_id)

    def _schema_get(self, obj: Any, name: str, *, as_object: bool = False) -> Any:
        return getattr(obj, name, None)

    def _schema_set(self, obj: Any, name: str, value: Any) -> None:
        self._set_value(obj, name, value)

    def _schema_set_parent(self, obj: Any, parent: Any) -> None:
        self._set_value(obj, "parent", parent)

    def _schema_save(self, obj: Any) -> Any:
        return self._object_invoke(obj, "%Save")

    def _use_iris_list_for_datatypes(self) -> bool:
        return False

    def _new_iris_list(self) -> Any:
        raise TypeError("IRISList support is unavailable for this runtime")

    def _iris_list_from_python(self, value: list[Any]) -> Any:
        iris_list = self._new_iris_list()
        for item in value:
            append = getattr(iris_list, "append", None)
            if callable(append):
                append(item)
            else:
                raise TypeError("IRISList object does not support append()")
        return iris_list

    @staticmethod
    def _python_from_iris_list(value: Any) -> list[Any]:
        if value is None:
            return []
        size = getattr(value, "size", None)
        getter = getattr(value, "get", None)
        if callable(size) and callable(getter):
            return [getter(i) for i in range(1, int(size()) + 1)]
        return list(value)

    def load_schema(self, classname: str) -> dict[str, Any] | None:
        class_def = self._schema_open("%Dictionary.ClassDefinition", classname)
        if not self.looks_like_iris_object(class_def):
            return None
        properties = []
        for prop in self._iter_collection(self._schema_get(class_def, "Properties", as_object=True)):
            if bool(self._schema_get(prop, "Private")) or bool(self._schema_get(prop, "Internal")) or bool(self._schema_get(prop, "Relationship")):
                continue
            properties.append(
                {
                    "name": str(self._schema_get(prop, "Name") or ""),
                    "iris_type": str(self._schema_get(prop, "Type") or "%String"),
                    "required": bool(self._schema_get(prop, "Required") or False),
                    "default": self._normalize_default(str(self._schema_get(prop, "InitialExpression") or "")),
                    "maxlen": self._to_int(self._schema_get(prop, "MaxLen")),
                    "description": str(self._schema_get(prop, "Description") or ""),
                    "parameters": self._extract_property_parameters(prop),
                }
            )
        indexes = []
        for idx in self._iter_collection(self._schema_get(class_def, "Indexes", as_object=True)):
            name = str(self._schema_get(idx, "Name") or "")
            if not name:
                continue
            indexes.append(
                {
                    "name": name,
                    "properties": str(self._schema_get(idx, "Properties") or ""),
                    "unique": bool(self._schema_get(idx, "Unique") or False),
                    "primary_key": bool(self._schema_get(idx, "PrimaryKey") or False),
                }
            )
        parameters: dict[str, str] = {}
        for item in self._iter_collection(self._schema_get(class_def, "Parameters", as_object=True)):
            name = str(self._schema_get(item, "Name") or "")
            if name:
                parameters[name] = str(self._schema_get(item, "Default") or "")
        storage = None
        storages = list(self._iter_collection(self._schema_get(class_def, "Storages", as_object=True)))
        if storages:
            storage = self._extract_storage(classname, storages[0])
        return {
            "name": classname,
            "superclasses": list(normalize_superclasses(str(self._schema_get(class_def, "Super") or "%Persistent"))),
            "properties": properties,
            "indexes": indexes,
            "parameters": parameters,
            "storage": storage,
            "source": {"kind": "iris"},
        }

    def list_classes(self, pattern: str) -> list[str]:
        rows = self.sql("SELECT Name FROM %Dictionary.ClassDefinition")
        all_names = [str(row[0]) for row in rows]
        return sorted(match_classnames(all_names, pattern))

    def replace_class(self, schema_class: SchemaClass) -> None:
        classname = schema_class.name
        class_def = self._schema_open("%Dictionary.ClassDefinition", classname)
        if not self.looks_like_iris_object(class_def):
            class_def = self._schema_new("%Dictionary.ClassDefinition")
            self._schema_set(class_def, "Name", classname)
        self._schema_set(class_def, "Super", ",".join(schema_class.superclasses))

        self._delete_missing(classname, "%Dictionary.PropertyDefinition", schema_class.property_map)
        self._delete_missing(classname, "%Dictionary.IndexDefinition", schema_class.index_map)
        self._delete_missing(classname, "%Dictionary.ParameterDefinition", schema_class.parameters)
        if schema_class.storage is None:
            self._delete_all_storage(classname)

        for prop in schema_class.properties:
            prop_def = self._schema_open("%Dictionary.PropertyDefinition", f"{classname}||{prop.name}")
            if not self.looks_like_iris_object(prop_def):
                prop_def = self._schema_new("%Dictionary.PropertyDefinition")
                self._schema_set_parent(prop_def, class_def)
                self._schema_set(prop_def, "Name", prop.name)
            self._schema_set(prop_def, "Type", prop.iris_type)
            self._schema_set(prop_def, "Required", prop.required)
            self._schema_set(prop_def, "InitialExpression", prop.default)
            self._schema_set(prop_def, "Description", prop.description)
            self._replace_property_parameters(prop_def, prop.parameters)
            self._check_status(self._schema_save(prop_def))

        for idx in schema_class.indexes:
            idx_def = self._schema_open("%Dictionary.IndexDefinition", f"{classname}||{idx.name}")
            if not self.looks_like_iris_object(idx_def):
                idx_def = self._schema_new("%Dictionary.IndexDefinition")
                self._schema_set_parent(idx_def, class_def)
                self._schema_set(idx_def, "Name", idx.name)
            self._schema_set(idx_def, "Properties", idx.properties)
            self._schema_set(idx_def, "Unique", idx.unique)
            self._schema_set(idx_def, "PrimaryKey", idx.primary_key)
            self._check_status(self._schema_save(idx_def))

        for name, value in schema_class.parameters.items():
            param_def = self._schema_open("%Dictionary.ParameterDefinition", f"{classname}||{name}")
            if not self.looks_like_iris_object(param_def):
                param_def = self._schema_new("%Dictionary.ParameterDefinition")
                self._schema_set_parent(param_def, class_def)
                self._schema_set(param_def, "Name", name)
            self._schema_set(param_def, "Default", value)
            self._check_status(self._schema_save(param_def))

        if schema_class.storage is not None:
            self._replace_storage(class_def, schema_class.storage)

        self._check_status(self._schema_save(class_def))
        self.compile(classname)

    def save_object(self, classname: str, data: dict[str, Any], obj_id: Any | None = None) -> Any:
        obj = self._object_open(classname, obj_id) if obj_id is not None else self._object_new(classname)
        schema = self.load_schema(classname) or {"properties": []}
        property_types = {item["name"]: item.get("iris_type", "%String") for item in schema.get("properties", [])}
        for key, value in data.items():
            iris_type = property_types.get(key, "%String")
            if is_stream_type(iris_type):
                self._write_stream_property(obj, key, value, iris_type)
                continue
            if is_list_of_datatypes(iris_type) and self._use_iris_list_for_datatypes():
                self._object_set(obj, key, None if value is None else self._iris_list_from_python(list(value)))
                continue
            self._object_set(obj, key, self._coerce_runtime_value(value, iris_type))
        self._check_status(self._object_invoke(obj, "%Save"))
        try:
            return self._object_invoke(obj, "%Id")
        except Exception:
            return obj_id

    def open_native_object(self, classname: str, obj_id: Any) -> Any | None:
        obj = self._object_open(classname, obj_id)
        if not self.looks_like_iris_object(obj):
            return None
        return self._wrap_native_object(obj, classname)

    def native_class(self, classname: str) -> Any:
        return self.runtime.cls(classname)

    def open_object(self, classname: str, obj_id: Any) -> dict[str, Any] | None:
        obj = self._object_open(classname, obj_id)
        if not self.looks_like_iris_object(obj):
            return None
        schema = self.load_schema(classname)
        if schema is None:
            return None
        data: dict[str, Any] = {}
        for prop in schema["properties"]:
            iris_type = str(prop.get("iris_type", "%String") or "%String")
            if is_list_of_datatypes(iris_type) and self._use_iris_list_for_datatypes():
                value = self._object_get(obj, prop["name"], iris_type)
                value = None if value is None else self._python_from_iris_list(value)
                data[prop["name"]] = value
                continue
            value = self._object_get(obj, prop["name"], iris_type)
            if is_stream_type(iris_type):
                value = read_stream_value(value, iris_type)
            data[prop["name"]] = value
        return {
            "id": obj_id,
            "data": data,
        }

    def delete_object(self, classname: str, obj_id: Any) -> None:
        self._check_status(self._object_delete_id(classname, obj_id))

    def query_rows(
        self,
        classname: str,
        fields: list[str],
        filters: dict[str, Any],
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        select_fields = ["%ID"] + fields
        sql = f"SELECT {', '.join(_quote_sql_identifier(field) for field in select_fields)} FROM {_quote_sql_classname(classname)}"
        params: list[Any] = []
        if filters:
            clauses = []
            for key, value in filters.items():
                clauses.append(f"{_quote_sql_identifier(key)} = ?")
                params.append(value)
            sql += " WHERE " + " AND ".join(clauses)
        if order_by:
            sql += f" ORDER BY {_quote_sql_identifier(order_by)}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        if offset:
            sql += f" OFFSET {int(offset)}"
        rows = self.sql(sql, params)
        result: list[dict[str, Any]] = []
        for row in rows:
            payload = {"id": row[0]}
            for idx, field in enumerate(fields, start=1):
                payload[field] = row[idx]
            result.append(payload)
        return result

    def sql(self, statement: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        params = params or []
        result = self.runtime.sql.exec(statement, *params)
        return [tuple(row) for row in result]

    def compile(self, classname: str) -> None:
        status = self.runtime.cls("%SYSTEM.OBJ").Compile(classname, "ck")
        self._check_status(status)

    def looks_like_iris_object(self, value: Any) -> bool:
        return value is not None and value != ""

    def begin(self) -> None:
        self.runtime.tstart()

    def commit(self) -> None:
        self.runtime.tcommit()

    def rollback(self) -> None:
        self.runtime.trollback()

    def _delete_missing(self, classname: str, dictionary_class: str, expected: Any) -> None:
        try:
            rows = self.sql(f"SELECT Name FROM {dictionary_class} WHERE parent = ?", [classname])
        except Exception:
            return
        names = {str(row[0]) for row in rows}
        expected_names = set(expected.keys()) if isinstance(expected, dict) else set(expected)
        for name in names - expected_names:
            try:
                self.sql(f"DELETE FROM {dictionary_class} WHERE parent = ? AND Name = ?", [classname, name])
            except Exception:
                continue

    def _delete_all_storage(self, classname: str) -> None:
        try:
            self.sql("DELETE FROM %Dictionary.StorageDefinition WHERE parent = ?", [classname])
        except Exception:
            return

    def _replace_storage(self, class_def: Any, storage: StorageDefinition | dict[str, Any]) -> None:
        storage_defn = StorageDefinition.from_dict(storage)
        if storage_defn is None:
            return
        classname = str(self._schema_get(class_def, "Name"))
        self._delete_all_storage(classname)
        storage_def = self._schema_new("%Dictionary.StorageDefinition")
        self._schema_set_parent(storage_def, class_def)
        self._schema_set(storage_def, "Name", storage_defn.name)
        for key, setter_name in _STORAGE_TOP_LEVEL_FIELDS:
            self._schema_set(storage_def, setter_name, getattr(storage_defn, key))
        self._check_status(self._schema_save(storage_def))
        self._replace_storage_children(storage_def, storage_defn)

    def _extract_storage(self, classname: str, storage_def: Any) -> StorageDefinition:
        storage_name = str(self._schema_get(storage_def, "Name") or "")
        storage = {"name": storage_name}
        definition_rows = self.sql(
            "SELECT CounterLocation, DataLocation, DefaultData, Description, ExtentLocation, ExtentSize, "
            "IdExpression, IdFunction, IdLocation, IndexLocation, SqlChildSub, SqlIdExpression, "
            "SqlRowIdName, SqlRowIdProperty, StreamLocation, Type, VersionLocation "
            "FROM %Dictionary.StorageDefinition WHERE parent = ? AND Name = ?",
            [classname, storage_name],
        )
        if definition_rows:
            row = definition_rows[0]
            for index, (key, _) in enumerate(_STORAGE_TOP_LEVEL_FIELDS):
                value = row[index]
                if value not in {"", None}:
                    storage[key] = str(value)
        storage_id = f"{classname}||{storage_name}"
        data_rows = self.sql(
            "SELECT Name, Structure FROM %Dictionary.StorageDataDefinition WHERE parent = ?",
            [storage_id],
        )
        if data_rows:
            data_items: list[dict[str, Any]] = []
            for row in data_rows:
                data_name = str(row[0])
                values = self.sql(
                    "SELECT Name, Value FROM %Dictionary.StorageDataValueDefinition WHERE parent = ?",
                    [f"{storage_id}||{data_name}"],
                )
                data_items.append(
                    {
                        "name": data_name,
                        "structure": str(row[1] or ""),
                        "values": [
                            {"name": str(value_row[0]), "value": str(value_row[1])}
                            for value_row in sorted(values, key=lambda item: _sort_storage_value_name(item[0]))
                        ],
                    }
                )
            storage["data"] = data_items
        property_rows = self.sql(
            "SELECT Name, AverageFieldSize, BiasQueriesAsOutlier, ChildBlockCount, ChildExtentSize, "
            "Histogram, OutlierSelectivity, Selectivity, StreamLocation "
            "FROM %Dictionary.StoragePropertyDefinition WHERE parent = ?",
            [storage_id],
        )
        if property_rows:
            properties: list[dict[str, Any]] = []
            for row in property_rows:
                item: dict[str, Any] = {"name": str(row[0])}
                for index, (key, _) in enumerate(_STORAGE_PROPERTY_FIELDS, start=1):
                    value = row[index]
                    if value not in {"", None}:
                        item[key] = str(value)
                properties.append(item)
            storage["properties"] = properties
        sql_map_rows = self.sql(
            'SELECT Name, BlockCount, Condition, ConditionFields, ConditionalWithHostVars, "_Global", '
            "PopulationPct, PopulationType, RowReference, Structure, Type "
            "FROM %Dictionary.StorageSQLMapDefinition WHERE parent = ?",
            [storage_id],
        )
        if sql_map_rows:
            sql_maps: list[dict[str, Any]] = []
            for row in sql_map_rows:
                item: dict[str, Any] = {"name": str(row[0])}
                for index, (key, _) in enumerate(_STORAGE_SQL_MAP_FIELDS, start=1):
                    value = row[index]
                    if value not in {"", None}:
                        item[key] = str(value)
                sql_maps.append(item)
            storage["sql_maps"] = sql_maps
        return StorageDefinition.from_dict({key: value for key, value in storage.items() if value != "" and value is not None}) or StorageDefinition(name=storage_name)

    def _replace_storage_children(self, storage_def: Any, storage: StorageDefinition) -> None:
        storage_name = str(storage.name or "Default")
        parent = self._schema_get(storage_def, "parent", as_object=True)
        classname = str(self._schema_get(parent, "Name") or "") if parent is not None else ""
        storage_id = f"{classname}||{storage_name}" if classname else ""
        if storage_id:
            for sql, params in [
                ("DELETE FROM %Dictionary.StorageDataValueDefinition WHERE parent %STARTSWITH ?", [f"{storage_id}||"]),
                ("DELETE FROM %Dictionary.StorageDataDefinition WHERE parent = ?", [storage_id]),
                ("DELETE FROM %Dictionary.StoragePropertyDefinition WHERE parent = ?", [storage_id]),
                ("DELETE FROM %Dictionary.StorageSQLMapDefinition WHERE parent = ?", [storage_id]),
            ]:
                try:
                    self.sql(sql, params)
                except Exception:
                    continue

        for item in storage.data:
            data_def = self._schema_new("%Dictionary.StorageDataDefinition")
            self._schema_set_parent(data_def, storage_def)
            self._schema_set(data_def, "Name", item.name)
            self._schema_set(data_def, "Structure", item.structure)
            self._check_status(self._schema_save(data_def))
            for name, value in sorted(item.values.items()):
                value_def = self._schema_new("%Dictionary.StorageDataValueDefinition")
                self._schema_set_parent(value_def, data_def)
                self._schema_set(value_def, "Name", name)
                self._schema_set(value_def, "Value", value)
                self._check_status(self._schema_save(value_def))

        for item in storage.properties:
            property_def = self._schema_new("%Dictionary.StoragePropertyDefinition")
            self._schema_set_parent(property_def, storage_def)
            self._schema_set(property_def, "Name", item.name)
            for key, setter_name in _STORAGE_PROPERTY_FIELDS:
                self._schema_set(property_def, setter_name, getattr(item, key))
            self._check_status(self._schema_save(property_def))

        for item in storage.sql_maps:
            sql_map_def = self._schema_new("%Dictionary.StorageSQLMapDefinition")
            self._schema_set_parent(sql_map_def, storage_def)
            self._schema_set(sql_map_def, "Name", item.name)
            for key, setter_name in _STORAGE_SQL_MAP_FIELDS:
                attr_name = "global_" if key == "global" else key
                self._schema_set(sql_map_def, setter_name, getattr(item, attr_name))
            self._check_status(self._schema_save(sql_map_def))

    def _iter_collection(self, collection: Any) -> list[Any]:
        if collection is None:
            return []
        try:
            count = int(collection.Count())
        except Exception:
            try:
                return list(collection)
            except Exception:
                return []
        return [collection.GetAt(i) for i in range(1, count + 1)]

    @staticmethod
    def _normalize_default(value: str) -> str:
        return "" if value in {"", '""', "{}"} else value

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value in {None, ""}:
            return None
        try:
            return int(value)
        except Exception:
            return None

    def _check_status(self, status: Any) -> None:
        if status in {None, "", 1, True}:
            return
        try:
            ok = bool(self.runtime.cls("%SYSTEM.Status").IsOK(status))
        except Exception:
            ok = bool(status)
        if not ok:
            raise RuntimeError(f"IRIS status failure: {status!r}")

    @staticmethod
    def _set_value(obj: Any, name: str, value: Any) -> None:
        if isinstance(value, bool):
            value = 1 if value else 0
        setter = getattr(obj, f"{name}Set", None)
        if callable(setter):
            setter(value)
            return
        setattr(obj, name, value)

    @staticmethod
    def _coerce_runtime_value(value: Any, iris_type: str) -> Any:
        return coerce_to_iris_logical(value, iris_type)

    def _write_stream_property(self, obj: Any, prop_name: str, value: Any, iris_type: str) -> None:
        if value is None:
            self._object_set(obj, prop_name, None)
            return
        stream = self._new_stream_object(iris_type)
        payload = self._coerce_runtime_value(value, iris_type)
        self._stream_call(stream, "Write", payload)
        self._stream_call(stream, "Rewind")
        self._object_set(obj, prop_name, stream)

    def _new_stream_object(self, iris_type: str) -> Any:
        stream_class = self.runtime.cls(iris_type)
        constructor = getattr(stream_class, "_New", None)
        if not callable(constructor):
            raise TypeError(f"Unable to create stream object for {iris_type}")
        return constructor()

    @staticmethod
    def _stream_call(stream: Any, method_name: str, *args: Any) -> Any:
        method = getattr(stream, method_name, None)
        if callable(method):
            return method(*args)
        invoke = getattr(stream, "invoke", None)
        if callable(invoke):
            return invoke(method_name, *args)
        raise TypeError(f"Stream object does not support {method_name}()")

    def _extract_property_parameters(self, prop: Any) -> dict[str, str]:
        result: dict[str, str] = {}
        getter = getattr(prop, "ParametersGetAt", None)
        if callable(getter):
            for name in SUPPORTED_PROPERTY_PARAMETERS:
                try:
                    value = getter(name)
                except Exception:
                    continue
                if value not in {"", None}:
                    result[name] = str(value)
            return result

        collection = self._schema_get(prop, "Parameters", as_object=True)
        for name in SUPPORTED_PROPERTY_PARAMETERS:
            value = _collection_get_at(collection, name)
            if value not in {"", None}:
                result[name] = str(value)
        return result

    def _replace_property_parameters(self, prop_def: Any, parameters: dict[str, str]) -> None:
        normalized = {str(k): str(v) for k, v in dict(parameters).items() if str(k) in SUPPORTED_PROPERTY_PARAMETERS}
        remover = getattr(prop_def, "ParametersRemoveAt", None)
        setter = getattr(prop_def, "ParametersSetAt", None)
        if callable(setter):
            for name in SUPPORTED_PROPERTY_PARAMETERS:
                if callable(remover):
                    try:
                        remover(name)
                    except Exception:
                        pass
                elif name not in normalized:
                    try:
                        setter("", name)
                    except Exception:
                        pass
            for name, value in normalized.items():
                setter(value, name)
            return

        collection = self._schema_get(prop_def, "Parameters", as_object=True)
        if collection is None:
            return
        _collection_clear_supported(collection)
        for name, value in normalized.items():
            _collection_set_at(collection, name, value)


def _sort_storage_value_name(value: Any) -> tuple[int, str]:
    text = str(value)
    try:
        return (0, f"{int(text):020d}")
    except Exception:
        return (1, text)


def _collection_get_at(collection: Any, key: str) -> Any:
    if collection is None:
        return None
    getter = getattr(collection, "GetAt", None)
    if callable(getter):
        try:
            return getter(key)
        except Exception:
            return None
    if isinstance(collection, dict):
        return collection.get(key)
    try:
        return collection[key]
    except Exception:
        return None


def _collection_set_at(collection: Any, key: str, value: Any) -> None:
    setter = getattr(collection, "SetAt", None)
    if callable(setter):
        setter(value, key)
        return
    if isinstance(collection, dict):
        collection[key] = value
        return
    collection[key] = value


def _collection_clear_supported(collection: Any) -> None:
    clear = getattr(collection, "Clear", None)
    if callable(clear):
        clear()
        return
    remover = getattr(collection, "RemoveAt", None)
    if callable(remover):
        for name in SUPPORTED_PROPERTY_PARAMETERS:
            try:
                remover(name)
            except Exception:
                continue
        return
    if isinstance(collection, dict):
        for name in SUPPORTED_PROPERTY_PARAMETERS:
            collection.pop(name, None)


def _quote_sql_identifier(name: str) -> str:
    return str(name)


def _quote_sql_classname(name: str) -> str:
    parts = str(name).split(".", 1)
    if len(parts) == 2:
        schema_name, relation_name = parts
    else:
        schema_name, relation_name = "SQLUser", parts[0]
    if schema_name == "User":
        schema_name = "SQLUser"
    return f"{schema_name}.{relation_name}"


# ---------------------------------------------------------------------------
# Concrete backend implementations
# ---------------------------------------------------------------------------

class EmbeddedRuntime(_BaseRuntime):
    """Backend for the embedded InterSystems IRIS Python runtime.

    Uses the ``iris`` module imported directly, identical to the pre-refactor
    ``IRISRuntime`` behaviour.  Pass a custom *iris_module* to inject a mock
    in tests — or rely on ``FakeAdapter`` for full unit testing.
    """

    def __init__(self, iris_module: Any | None = None) -> None:
        self.runtime = iris_module or importlib.import_module("iris")

    def sql(self, statement: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        params = params or []
        result = self.runtime.sql.exec(statement, *params)
        return [tuple(row) for row in result]

    def query_rows(
        self,
        classname: str,
        fields: list[str],
        filters: dict[str, Any],
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = f"SELECT {_quote_sql_identifier('%ID')} FROM {_quote_sql_classname(classname)}"
        params: list[Any] = []
        if filters:
            clauses = []
            for key, value in filters.items():
                clauses.append(f"{_quote_sql_identifier(key)} = ?")
                params.append(value)
            sql += " WHERE " + " AND ".join(clauses)
        if order_by:
            sql += f" ORDER BY {_quote_sql_identifier(order_by)}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        if offset:
            sql += f" OFFSET {int(offset)}"

        rows = self.sql(sql, params)
        result: list[dict[str, Any]] = []
        schema = self.load_schema(classname) or {"properties": []}
        property_types = {item["name"]: item.get("iris_type", "%String") for item in schema.get("properties", [])}
        for row in rows:
            obj_id = row[0]
            obj = self._object_open(classname, obj_id)
            if not self.looks_like_iris_object(obj):
                continue
            payload = {"id": obj_id}
            for field in fields:
                iris_type = property_types.get(field, "%String")
                value = self._object_get(obj, field, iris_type)
                if is_stream_type(iris_type):
                    value = read_stream_value(value, iris_type)
                payload[field] = value
            result.append(payload)
        return result


class _IRISObjectNativeProxy:
    def __init__(self, runtime: "_IRISObjectRuntimeBase", classname: str, obj: Any) -> None:
        self._runtime = runtime
        self._classname = classname
        self._obj = obj

    def __getattr__(self, name: str) -> Any:
        try:
            return self._runtime._object_get(self._obj, name)
        except Exception:
            pass

        def _method_proxy(*args: Any, **kwargs: Any) -> Any:
            if kwargs:
                raise TypeError("IRIS native method proxies do not support keyword arguments")
            return self._runtime._object_invoke(self._obj, name, *args)

        _method_proxy.__name__ = name
        return _method_proxy


class _IRISObjectRuntimeBase(_BaseRuntime):
    def _class_method(self, classname: str, method_name: str, *args: Any) -> Any:
        runtime = self.runtime
        for method in ("classMethodObject", "classMethodValue", "classMethodString"):
            caller = getattr(runtime, method, None)
            if callable(caller):
                return caller(classname, method_name, *args)
        raise AttributeError(f"Runtime does not support class method dispatch for {classname}.{method_name}")

    def _object_new(self, classname: str) -> Any:
        return self._class_method(classname, "%New")

    def _object_open(self, classname: str, obj_id: Any) -> Any:
        return self._class_method(classname, "%OpenId", obj_id)

    def _object_delete_id(self, classname: str, obj_id: Any) -> Any:
        return self._class_method(classname, "%DeleteId", obj_id)

    def _object_get(self, obj: Any, prop_name: str, iris_type: str | None = None) -> Any:
        if iris_type and is_stream_type(iris_type):
            getter = getattr(obj, "getObject", None)
            if callable(getter):
                return getter(prop_name)
        if iris_type and is_list_of_datatypes(iris_type):
            list_getter = getattr(obj, "getIRISList", None)
            if callable(list_getter):
                return list_getter(prop_name)
        for getter_name in ("get", "getObject"):
            getter = getattr(obj, getter_name, None)
            if callable(getter):
                try:
                    return getter(prop_name)
                except Exception:
                    continue
        raise AttributeError(prop_name)

    def _object_set(self, obj: Any, prop_name: str, value: Any) -> None:
        setter = getattr(obj, "set", None)
        if not callable(setter):
            raise AttributeError("IRISObject.set")
        setter(prop_name, value)

    def _object_invoke(self, obj: Any, method_name: str, *args: Any) -> Any:
        for invoker_name in ("invoke", "invokeObject", "invokeString"):
            invoker = getattr(obj, invoker_name, None)
            if callable(invoker):
                return invoker(method_name, *args)
        raise AttributeError(method_name)

    def _wrap_native_object(self, obj: Any, classname: str) -> Any:
        return _IRISObjectNativeProxy(self, classname, obj)

    def _schema_new(self, classname: str) -> Any:
        return self._class_method(classname, "%New")

    def _schema_open(self, classname: str, obj_id: Any) -> Any:
        return self._class_method(classname, "%OpenId", obj_id)

    def _schema_get(self, obj: Any, name: str, *, as_object: bool = False) -> Any:
        if as_object:
            for getter_name in ("getObject", "invokeObject"):
                getter = getattr(obj, getter_name, None)
                if callable(getter):
                    try:
                        if getter_name == "invokeObject":
                            return getter(f"{name}GetObject")
                        return getter(name)
                    except Exception:
                        continue
        try:
            return self._object_get(obj, name)
        except Exception:
            return None

    def _schema_set(self, obj: Any, name: str, value: Any) -> None:
        self._object_set(obj, name, value)

    def _schema_set_parent(self, obj: Any, parent: Any) -> None:
        for method_name in ("parentSet",):
            try:
                self._object_invoke(obj, method_name, parent)
                return
            except Exception:
                continue
        self._object_set(obj, "parent", parent)

    def _schema_save(self, obj: Any) -> Any:
        return self._object_invoke(obj, "%Save")

    def _use_iris_list_for_datatypes(self) -> bool:
        return True

    def _new_iris_list(self) -> Any:
        iris_list_type = getattr(self, "_iris_list_type", None)
        if iris_list_type is None:
            raise TypeError("IRISList support is unavailable for this runtime")
        return iris_list_type()

    def _new_stream_object(self, iris_type: str) -> Any:
        return self._class_method(iris_type, "%New")

    def _iter_collection(self, collection: Any) -> list[Any]:
        if collection is None:
            return []
        try:
            count = int(self._object_invoke(collection, "Count"))
        except Exception:
            return []
        items: list[Any] = []
        for index in range(1, count + 1):
            invoker = getattr(collection, "invokeObject", None)
            if callable(invoker):
                items.append(invoker("GetAt", index))
                continue
            items.append(self._object_invoke(collection, "GetAt", index))
        return items

    def compile(self, classname: str) -> None:
        caller = getattr(self.runtime, "classMethodString", None)
        if callable(caller):
            status = caller("%SYSTEM.OBJ", "Compile", classname, "ck")
            self._check_status(status)
            return
        super().compile(classname)


class NetworkRuntime(_IRISObjectRuntimeBase):
    """Backend for InterSystems IRIS accessed via the ``intersystems_iris``
    (Python Gateway / native-API) driver.

    Mirrors ``iris_global.IRISGref``: extracts ``driver_connection`` from a
    dedicated raw connection for the native-API object (schema / class ops) and
    borrows a fresh pooled connection for every SQL call.
    """

    def __init__(self, engine: Any) -> None:
        from intersystems_iris import IRIS, IRISList  # type: ignore[import]

        self._engine = engine
        self._iris_list_type = IRISList
        # Dedicated stable connection for the native IRIS class-dictionary API.
        self._native_raw_conn = engine.raw_connection()
        self.runtime = IRIS(self._native_raw_conn.driver_connection)

    def sql(self, statement: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        raw_conn = self._engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.execute(statement, params or [])
            rows = cursor.fetchall()
            return [tuple(row) for row in rows]
        finally:
            raw_conn.close()  # returns connection to the pool

    def begin(self) -> None:
        self.runtime.tStart()

    def commit(self) -> None:
        self.runtime.tCommit()

    def rollback(self) -> None:
        self.runtime.tRollback()


class OfficialRuntime(_IRISObjectRuntimeBase):
    """Backend for InterSystems IRIS accessed via the official ``iris``
    (``iris+intersystems``) driver.

    Mirrors ``iris_global.IRISOfficial``: uses a dedicated stable connection for
    the native-API object and borrows a fresh pooled connection per SQL call.
    """

    def __init__(self, engine: Any) -> None:
        from iris import IRIS, IRISList  # type: ignore[import]

        self._engine = engine
        self._iris_list_type = IRISList
        # Dedicated stable connection for the native IRIS class-dictionary API.
        self._native_raw_conn = engine.raw_connection()
        self.runtime = IRIS(self._native_raw_conn.driver_connection)

    def sql(self, statement: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        raw_conn = self._engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.execute(statement, params or [])
            rows = cursor.fetchall()
            return [tuple(row) for row in rows]
        finally:
            raw_conn.close()  # returns connection to the pool

    def begin(self) -> None:
        self.runtime.tStart()

    def commit(self) -> None:
        self.runtime.tCommit()

    def rollback(self) -> None:
        self.runtime.tRollback()


# ---------------------------------------------------------------------------
# User-facing dispatcher — mirrors iris_global.GlobalReference
# ---------------------------------------------------------------------------

class IRISRuntime:
    """User-facing runtime dispatcher.

    Selects the correct backend (``EmbeddedRuntime``, ``NetworkRuntime``, or
    ``OfficialRuntime``) based on the SQLAlchemy engine's drivername, mirroring
    the way ``iris_global.GlobalReference.__post_init__`` selects a ``GrefABC``
    implementation.

    Usage::

        # Embedded (backward-compatible, no engine required)
        rt = IRISRuntime()

        # IRIS Python Gateway / intersystems_iris driver
        rt = IRISRuntime(engine=create_engine("iris://user:pass@host:port/namespace"))

        # Official InterSystems driver
        rt = IRISRuntime(engine=create_engine("iris+intersystems://user:pass@host:port/namespace"))

        # Embedded via explicit SQLAlchemy engine
        rt = IRISRuntime(engine=create_engine("iris+emb:///namespace"))
    """

    def __init__(
        self,
        runtime: Any | None = None,
        engine: Any | None = None,
    ) -> None:
        drivername: str = ""
        if engine is not None:
            drivername = getattr(getattr(engine, "url", None), "drivername", "") or ""

        if engine is None or drivername in {"", "iris+emb"}:
            self._impl: _BaseRuntime = EmbeddedRuntime(runtime)
        elif drivername == "iris":
            self._impl = NetworkRuntime(engine)
        elif drivername == "iris+intersystems":
            self._impl = OfficialRuntime(engine)
        else:
            raise ValueError(
                f"Unsupported SQLAlchemy drivername: {drivername!r}. "
                "Expected one of: 'iris+emb', 'iris', 'iris+intersystems'."
            )

    # ------------------------------------------------------------------ schema

    def load_schema(self, classname: str) -> dict[str, Any] | None:
        return self._impl.load_schema(classname)

    def list_classes(self, pattern: str) -> list[str]:
        return self._impl.list_classes(pattern)

    def replace_class(self, schema_class: SchemaClass) -> None:
        self._impl.replace_class(schema_class)

    # ------------------------------------------------------------------ objects

    def save_object(
        self,
        classname: str,
        data: dict[str, Any],
        obj_id: Any | None = None,
    ) -> Any:
        return self._impl.save_object(classname, data, obj_id)

    def open_object(self, classname: str, obj_id: Any) -> dict[str, Any] | None:
        return self._impl.open_object(classname, obj_id)

    def open_native_object(self, classname: str, obj_id: Any) -> Any | None:
        return self._impl.open_native_object(classname, obj_id)

    def native_class(self, classname: str) -> Any:
        return self._impl.native_class(classname)

    def delete_object(self, classname: str, obj_id: Any) -> None:
        self._impl.delete_object(classname, obj_id)

    # ------------------------------------------------------------------ queries

    def query_rows(
        self,
        classname: str,
        fields: list[str],
        filters: dict[str, Any],
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._impl.query_rows(classname, fields, filters, order_by, limit, offset)

    def sql(self, statement: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        return self._impl.sql(statement, params)

    # ------------------------------------------------------------------ utility

    def compile(self, classname: str) -> None:
        self._impl.compile(classname)

    def looks_like_iris_object(self, value: Any) -> bool:
        return self._impl.looks_like_iris_object(value)

    # ---------------------------------------------------------------- transactions

    def begin(self) -> None:
        self._impl.begin()

    def commit(self) -> None:
        self._impl.commit()

    def rollback(self) -> None:
        self._impl.rollback()


# ---------------------------------------------------------------------------
# Module-level default-runtime management (unchanged public API)
# ---------------------------------------------------------------------------

_DEFAULT_RUNTIME: ContextVar[IRISRuntime | Any | None] = ContextVar("iris_orm_default_runtime", default=None)
_RUNTIME_GENERATION = 0


def _get_runtime() -> IRISRuntime:
    runtime = _DEFAULT_RUNTIME.get()
    if runtime is None:
        runtime = IRISRuntime()
        _DEFAULT_RUNTIME.set(runtime)
    return runtime


def _runtime_version() -> int:
    return _RUNTIME_GENERATION


def configure_default_runtime(
    *,
    runtime: IRISRuntime | None = None,
    engine: Any | None = None,
) -> IRISRuntime:
    """Set (or create) the process-wide default runtime.

    Pass *runtime* to supply a pre-built ``IRISRuntime`` (or any object that
    satisfies ``IRISRuntimeProtocol``, such as ``FakeAdapter`` in tests).
    Pass *engine* to build a new ``IRISRuntime`` from a SQLAlchemy engine.
    When neither is given the existing default is kept (or a new
    ``EmbeddedRuntime``-backed ``IRISRuntime`` is created).
    """
    global _RUNTIME_GENERATION
    if runtime is not None:
        configured = runtime
    elif engine is not None:
        configured = IRISRuntime(engine=engine)
    else:
        configured = _DEFAULT_RUNTIME.get() or IRISRuntime()
    _DEFAULT_RUNTIME.set(configured)
    _RUNTIME_GENERATION += 1
    return configured


def reset_default_runtime() -> None:
    global _RUNTIME_GENERATION
    _DEFAULT_RUNTIME.set(None)
    _RUNTIME_GENERATION += 1


def configure(
    engine: Any | None = None,
    *,
    runtime: IRISRuntime | None = None,
) -> IRISRuntime:
    """Primary public entry point for connecting ``iris_orm`` to IRIS.

    Call this once at application start, before any model is used::

        import iris_orm
        from sqlalchemy import create_engine

        iris_orm.configure(create_engine("iris://user:pass@host:1972/USER"))

    *engine* may also be passed as a keyword argument.  Pass *runtime* instead
    to supply a fully constructed ``IRISRuntime`` (or a ``FakeAdapter`` in
    tests)::

        iris_orm.configure(runtime=FakeAdapter())

    Returns the ``IRISRuntime`` that was registered as the default.
    """
    return configure_default_runtime(runtime=runtime, engine=engine)
