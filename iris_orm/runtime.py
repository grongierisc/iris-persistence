from __future__ import annotations

from contextvars import ContextVar
import importlib
from typing import Any

from .protocol import IRISRuntimeProtocol
from .schema import (
    SchemaClass,
    coerce_to_iris_logical,
    is_dynamic_type,
    is_array_of_datatypes,
    is_list_of_datatypes,
    is_stream_type,
    match_classnames,
    normalize_superclasses,
    read_dynamic_value,
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

    def _class_method_object(self, classname: str, method_name: str, *args: Any) -> Any:
        target = self.runtime.cls(classname)
        resolved_name = f"_{method_name[1:]}" if method_name.startswith("%") else method_name
        method = getattr(target, resolved_name, None)
        if not callable(method):
            raise AttributeError(f"{classname}.{method_name}")
        return method(*args)

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
                    "maxlen": self._read_maxlen(prop),
                    "description": str(self._schema_get(prop, "Description") or ""),
                    "parameters": self._extract_property_parameters(prop),
                }
            )
        indexes = []
        idx_names: list[str] = []
        try:
            idx_rows = self.sql("SELECT Name FROM %Dictionary.IndexDefinition WHERE parent = ?", [classname])
            idx_names = [str(row[0]) for row in idx_rows if row[0]]
        except Exception:
            pass
        if not idx_names:
            # Fallback: relationship collection (works in gateway/test runtimes; returns
            # None in embedded IRIS where Indexes is not exposed as a Python attribute)
            idx_names = [
                str(self._schema_get(idx, "Name") or "")
                for idx in self._iter_collection(self._schema_get(class_def, "Indexes", as_object=True))
            ]
            idx_names = [n for n in idx_names if n]
        for name in idx_names:
            idx = self._schema_open("%Dictionary.IndexDefinition", f"{classname}||{name}")
            if not self.looks_like_iris_object(idx):
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
            self._write_maxlen(prop_def, prop.maxlen)
            self._check_status(self._schema_save(prop_def), schema=True)

        for idx in schema_class.indexes:
            idx_def = self._schema_open("%Dictionary.IndexDefinition", f"{classname}||{idx.name}")
            if not self.looks_like_iris_object(idx_def):
                idx_def = self._schema_new("%Dictionary.IndexDefinition")
                self._schema_set_parent(idx_def, class_def)
                self._schema_set(idx_def, "Name", idx.name)
            self._schema_set(idx_def, "Properties", idx.properties)
            self._schema_set(idx_def, "Unique", idx.unique)
            self._schema_set(idx_def, "PrimaryKey", idx.primary_key)
            self._check_status(self._schema_save(idx_def), schema=True)

        for name, value in schema_class.parameters.items():
            param_def = self._schema_open("%Dictionary.ParameterDefinition", f"{classname}||{name}")
            if not self.looks_like_iris_object(param_def):
                param_def = self._schema_new("%Dictionary.ParameterDefinition")
                self._schema_set_parent(param_def, class_def)
                self._schema_set(param_def, "Name", name)
            self._schema_set(param_def, "Default", value)
            self._check_status(self._schema_save(param_def), schema=True)

        if schema_class.storage is not None:
            self._replace_storage(class_def, schema_class.storage)

        self._check_status(self._schema_save(class_def), schema=True)
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
            if is_dynamic_type(iris_type):
                self._write_dynamic_property(obj, key, value, iris_type)
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
            data[prop["name"]] = self._read_property_value(obj, prop["name"], iris_type)
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
        self._check_status(status, compile=True)

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
        self._check_status(self._schema_save(storage_def), schema=True)
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

                def _storage_value_sort_key(item: tuple[Any, ...]) -> tuple[int, str]:
                    text = str(item[0])
                    try:
                        return (0, f"{int(text):020d}")
                    except Exception:
                        return (1, text)

                data_items.append(
                    {
                        "name": data_name,
                        "structure": str(row[1] or ""),
                        "values": [
                            {"name": str(value_row[0]), "value": str(value_row[1])}
                            for value_row in sorted(values, key=_storage_value_sort_key)
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
            self._check_status(self._schema_save(data_def), schema=True)
            for name, value in sorted(item.values.items()):
                value_def = self._schema_new("%Dictionary.StorageDataValueDefinition")
                self._schema_set_parent(value_def, data_def)
                self._schema_set(value_def, "Name", name)
                self._schema_set(value_def, "Value", value)
                self._check_status(self._schema_save(value_def), schema=True)

        for item in storage.properties:
            property_def = self._schema_new("%Dictionary.StoragePropertyDefinition")
            self._schema_set_parent(property_def, storage_def)
            self._schema_set(property_def, "Name", item.name)
            for key, setter_name in _STORAGE_PROPERTY_FIELDS:
                self._schema_set(property_def, setter_name, getattr(item, key))
            self._check_status(self._schema_save(property_def), schema=True)

        for item in storage.sql_maps:
            sql_map_def = self._schema_new("%Dictionary.StorageSQLMapDefinition")
            self._schema_set_parent(sql_map_def, storage_def)
            self._schema_set(sql_map_def, "Name", item.name)
            for key, setter_name in _STORAGE_SQL_MAP_FIELDS:
                attr_name = "global_" if key == "global" else key
                self._schema_set(sql_map_def, setter_name, getattr(item, attr_name))
            self._check_status(self._schema_save(sql_map_def), schema=True)

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

    def _check_status(self, status: Any, *, compile: bool = False, schema: bool = False) -> None:
        if status in {None, "", 1, True}:
            return
        try:
            ok = bool(self.runtime.cls("%SYSTEM.Status").IsOK(status))
        except Exception:
            ok = bool(status)
        if not ok:
            try:
                error_text = str(self.runtime.cls("%SYSTEM.Status").GetErrorText(status))
            except Exception:
                error_text = repr(status)
            from .exceptions import IRISCompileError, IRISConcurrencyError, IRISSchemaError, IRISStatusError
            if compile:
                raise IRISCompileError(error_text, status=status)
            if schema:
                raise IRISSchemaError(error_text, status=status)
            lower = error_text.lower()
            if "lock" in lower or "concurr" in lower:
                raise IRISConcurrencyError(error_text, status=status)
            raise IRISStatusError(error_text, status=status)

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

    def _write_dynamic_property(self, obj: Any, prop_name: str, value: Any, iris_type: str) -> None:
        if value is None:
            self._object_set(obj, prop_name, None)
            return
        payload = self._coerce_runtime_value(value, iris_type)
        self._object_set(obj, prop_name, self._class_method_object(iris_type, "%FromJSON", payload))

    def _read_property_value(self, obj: Any, prop_name: str, iris_type: str) -> Any:
        if is_list_of_datatypes(iris_type) and self._use_iris_list_for_datatypes():
            value = self._object_get(obj, prop_name, iris_type)
            return None if value is None else self._python_from_iris_list(value)
        value = self._object_get(obj, prop_name, iris_type)
        if is_stream_type(iris_type):
            return read_stream_value(value, iris_type)
        if is_dynamic_type(iris_type):
            return read_dynamic_value(value)
        return value

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

    # -------------------------------------------------------------- property parameters
    # These three primitives encapsulate how a runtime reads/writes/removes a single
    # named entry from a %Dictionary.PropertyDefinition's Parameters collection.
    # _BaseRuntime implements the embedded IRIS pattern (ParametersGetAt / ParametersSetAt).
    # _GatewayRuntimeBase overrides them for the gateway object model.

    def _prop_param_get(self, prop: Any, key: str) -> str | None:
        """Return the value of property parameter *key*, or None if absent."""
        # Embedded test fakes expose ParametersGetAt directly on the property object
        getter = getattr(prop, "ParametersGetAt", None)
        if callable(getter):
            try:
                value = getter(key)
                return str(value) if value not in {"", None} else None
            except Exception:
                return None
        # Real embedded IRIS: parameters live in prop.Parameters (iris.%Collection.ArrayOfDT)
        collection = self._schema_get(prop, "Parameters", as_object=True)
        if collection is None:
            return None
        get_at = getattr(collection, "GetAt", None)
        if callable(get_at):
            try:
                value = get_at(key)
                return str(value) if value not in {"", None} else None
            except Exception:
                return None
        return None

    def _prop_param_set(self, prop: Any, key: str, value: str) -> None:
        """Write *value* for property parameter *key*."""
        setter = getattr(prop, "ParametersSetAt", None)
        if callable(setter):
            setter(value, key)
            return
        collection = self._schema_get(prop, "Parameters", as_object=True)
        if collection is None:
            return
        set_at = getattr(collection, "SetAt", None)
        if callable(set_at):
            set_at(value, key)

    def _prop_param_remove(self, prop: Any, key: str) -> None:
        """Remove property parameter *key* (no-op if absent)."""
        remover = getattr(prop, "ParametersRemoveAt", None)
        if callable(remover):
            try:
                remover(key)
            except Exception:
                pass
            return
        collection = self._schema_get(prop, "Parameters", as_object=True)
        if collection is None:
            return
        remove_at = getattr(collection, "RemoveAt", None)
        if callable(remove_at):
            try:
                remove_at(key)
            except Exception:
                pass

    def _read_maxlen(self, prop: Any) -> int | None:
        value = self._prop_param_get(prop, "MAXLEN")
        return self._to_int(value) or None

    def _extract_property_parameters(self, prop: Any) -> dict[str, str]:
        result: dict[str, str] = {}
        for name in SUPPORTED_PROPERTY_PARAMETERS:
            value = self._prop_param_get(prop, name)
            if value is not None:
                result[name] = value
        return result

    def _write_maxlen(self, prop_def: Any, maxlen: int | None) -> None:
        if maxlen is not None:
            self._prop_param_set(prop_def, "MAXLEN", str(maxlen))
        else:
            self._prop_param_remove(prop_def, "MAXLEN")

    def _replace_property_parameters(self, prop_def: Any, parameters: dict[str, str]) -> None:
        normalized = {k: v for k, v in parameters.items() if k in SUPPORTED_PROPERTY_PARAMETERS}
        for name in SUPPORTED_PROPERTY_PARAMETERS:
            if name in normalized:
                self._prop_param_set(prop_def, name, normalized[name])
            else:
                self._prop_param_remove(prop_def, name)

def _quote_sql_identifier(name: str) -> str:
    # %ID is a special IRIS pseudo-column — must not be quoted
    if name.startswith("%"):
        return str(name)
    # Double-quote to protect reserved words and mixed-case names
    return '"' + str(name).replace('"', '""') + '"'


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

class EmbeddedRuntime(_BaseRuntime, IRISRuntimeProtocol):
    """Backend for the embedded InterSystems IRIS Python runtime.

    Uses the ``iris`` module imported directly. Pass a custom *iris_module* to
    inject a mock in tests.
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
                payload[field] = self._read_property_value(obj, field, iris_type)
            result.append(payload)
        return result

class _GatewayRuntimeBase(_BaseRuntime):
    class _NativeProxy:
        def __init__(self, runtime: "_GatewayRuntimeBase", classname: str, obj: Any) -> None:
            self._runtime = runtime
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

    def __init__(self, engine: Any, iris_type: Any, iris_list_type: Any) -> None:
        self._engine = engine
        self._iris_list_type = iris_list_type
        self._native_raw_conn = engine.raw_connection()
        self.runtime = iris_type(self._native_raw_conn.driver_connection)

    def _class_method(self, classname: str, method_name: str, *args: Any) -> Any:
        runtime = self.runtime
        for method in ("classMethodObject", "classMethodValue", "classMethodString"):
            caller = getattr(runtime, method, None)
            if callable(caller):
                return caller(classname, method_name, *args)
        raise AttributeError(f"Runtime does not support class method dispatch for {classname}.{method_name}")

    def _class_method_object(self, classname: str, method_name: str, *args: Any) -> Any:
        return self._class_method(classname, method_name, *args)

    def _object_new(self, classname: str) -> Any:
        return self._class_method(classname, "%New")

    def _object_open(self, classname: str, obj_id: Any) -> Any:
        return self._class_method(classname, "%OpenId", obj_id)

    def _object_delete_id(self, classname: str, obj_id: Any) -> Any:
        return self._class_method(classname, "%DeleteId", obj_id)

    def _object_get(self, obj: Any, prop_name: str, iris_type: str | None = None) -> Any:
        if iris_type and (is_stream_type(iris_type) or is_dynamic_type(iris_type)):
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
        return self._NativeProxy(self, classname, obj)

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

    def _prop_param_get(self, prop: Any, key: str) -> str | None:
        """Read property parameter *key* via the gateway Parameters collection."""
        collection = self._schema_get(prop, "Parameters", as_object=True)
        if collection is None:
            return None
        # Prefer direct GetAt (test fakes, embedded-like objects)
        get_at = getattr(collection, "GetAt", None)
        if callable(get_at):
            try:
                value = get_at(key)
                return str(value) if value not in {"", None} else None
            except Exception:
                return None
        # Fallback for real IRISObject (invoke gateway)
        try:
            value = self._object_invoke(collection, "GetAt", key)
            return str(value) if value not in {"", None} else None
        except Exception:
            return None

    def _prop_param_set(self, prop: Any, key: str, value: str) -> None:
        """Write property parameter *key* via the gateway Parameters collection."""
        collection = self._schema_get(prop, "Parameters", as_object=True)
        if collection is None:
            return
        set_at = getattr(collection, "SetAt", None)
        if callable(set_at):
            try:
                set_at(value, key)
            except Exception:
                pass
            return
        try:
            self._object_invoke(collection, "SetAt", value, key)
        except Exception:
            pass

    def _prop_param_remove(self, prop: Any, key: str) -> None:
        """Remove property parameter *key* via the gateway Parameters collection."""
        collection = self._schema_get(prop, "Parameters", as_object=True)
        if collection is None:
            return
        remove_at = getattr(collection, "RemoveAt", None)
        if callable(remove_at):
            try:
                remove_at(key)
            except Exception:
                pass
            return
        try:
            self._object_invoke(collection, "RemoveAt", key)
        except Exception:
            pass

    def sql(self, statement: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        raw_conn = self._engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.execute(statement, params or [])
            rows = cursor.fetchall()
            return [tuple(row) for row in rows]
        finally:
            raw_conn.close()

    def begin(self) -> None:
        self.runtime.tStart()

    def commit(self) -> None:
        self.runtime.tCommit()

    def rollback(self) -> None:
        self.runtime.tRollback()


class CommunityRuntime(_GatewayRuntimeBase, IRISRuntimeProtocol):
    """Backend for InterSystems IRIS accessed via the community
    ``intersystems_iris`` (Python Gateway / native-API) driver.
    """

    def __init__(self, engine: Any) -> None:
        from intersystems_iris import IRIS, IRISList  # type: ignore[import]

        super().__init__(engine, IRIS, IRISList)


class OfficialRuntime(_GatewayRuntimeBase, IRISRuntimeProtocol):
    """Backend for InterSystems IRIS accessed via the official ``iris``
    (``iris+intersystems``) driver.
    """

    def __init__(self, engine: Any) -> None:
        from iris import IRIS, IRISList  # type: ignore[import]

        super().__init__(engine, IRIS, IRISList)


def _runtime_from_engine(engine: Any | None = None) -> IRISRuntimeProtocol:
    drivername = getattr(getattr(engine, "url", None), "drivername", "") or ""
    if engine is None or drivername in {"", "iris+emb"}:
        return EmbeddedRuntime()
    if drivername == "iris":
        return CommunityRuntime(engine)
    if drivername == "iris+intersystems":
        return OfficialRuntime(engine)
    raise ValueError(
        f"Unsupported SQLAlchemy drivername: {drivername!r}. "
        "Expected one of: 'iris+emb', 'iris', 'iris+intersystems'."
    )


# ---------------------------------------------------------------------------
# Module-level default-runtime management (unchanged public API)
# ---------------------------------------------------------------------------

_DEFAULT_RUNTIME: ContextVar[IRISRuntimeProtocol | None] = ContextVar("iris_orm_default_runtime", default=None)
_RUNTIME_GENERATION = 0


def _get_runtime() -> IRISRuntimeProtocol:
    runtime = _DEFAULT_RUNTIME.get()
    if runtime is None:
        runtime = EmbeddedRuntime()
        _DEFAULT_RUNTIME.set(runtime)
    return runtime


def _runtime_version() -> int:
    return _RUNTIME_GENERATION


def configure_default_runtime(
    *,
    runtime: IRISRuntimeProtocol | None = None,
    engine: Any | None = None,
) -> IRISRuntimeProtocol:
    """Set (or create) the process-wide default runtime.

    Pass *runtime* to supply a pre-built backend implementing
    ``IRISRuntimeProtocol``.
    Pass *engine* to build a new backend from a SQLAlchemy engine.
    When neither is given the existing default is kept (or a new
    ``EmbeddedRuntime`` is created).
    """
    global _RUNTIME_GENERATION
    if runtime is not None:
        configured = runtime
    elif engine is not None:
        configured = _runtime_from_engine(engine)
    else:
        configured = _DEFAULT_RUNTIME.get() or EmbeddedRuntime()
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
    runtime: IRISRuntimeProtocol | None = None,
) -> IRISRuntimeProtocol:
    """Primary public entry point for connecting ``iris_orm`` to IRIS.

    Call this once at application start, before any model is used::

        import iris_orm
        from sqlalchemy import create_engine

        iris_orm.configure(create_engine("iris://user:pass@host:1972/USER"))

    *engine* may also be passed as a keyword argument.  Pass *runtime* instead
    to supply a fully constructed runtime backend (or a ``FakeAdapter`` in
    tests)::

        iris_orm.configure(runtime=FakeAdapter())

    Returns the runtime backend that was registered as the default.
    """
    return configure_default_runtime(runtime=runtime, engine=engine)
