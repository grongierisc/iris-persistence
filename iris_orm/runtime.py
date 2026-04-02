from __future__ import annotations

import importlib
from typing import Any

from .schema import SchemaClass, match_classnames, normalize_superclasses

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

    def load_schema(self, classname: str) -> dict[str, Any] | None:
        class_def = self.runtime.cls("%Dictionary.ClassDefinition")._OpenId(classname)
        if not self.looks_like_iris_object(class_def):
            return None
        properties = []
        for prop in self._iter_collection(getattr(class_def, "Properties", None)):
            if bool(getattr(prop, "Private", False)) or bool(getattr(prop, "Internal", False)) or bool(getattr(prop, "Relationship", False)):
                continue
            properties.append(
                {
                    "name": str(getattr(prop, "Name", "") or ""),
                    "iris_type": str(getattr(prop, "Type", "") or "%String"),
                    "required": bool(getattr(prop, "Required", False)),
                    "default": self._normalize_default(str(getattr(prop, "InitialExpression", "") or "")),
                    "maxlen": self._to_int(getattr(prop, "MaxLen", None)),
                    "description": str(getattr(prop, "Description", "") or ""),
                }
            )
        indexes = []
        for idx in self._iter_collection(getattr(class_def, "Indexes", None)):
            name = str(getattr(idx, "Name", "") or "")
            if not name:
                continue
            indexes.append(
                {
                    "name": name,
                    "properties": str(getattr(idx, "Properties", "") or ""),
                    "unique": bool(getattr(idx, "Unique", False)),
                    "primary_key": bool(getattr(idx, "PrimaryKey", False)),
                }
            )
        parameters: dict[str, str] = {}
        for item in self._iter_collection(getattr(class_def, "Parameters", None)):
            name = str(getattr(item, "Name", "") or "")
            if name:
                parameters[name] = str(getattr(item, "Default", "") or "")
        storage = None
        storages = list(self._iter_collection(getattr(class_def, "Storages", None)))
        if storages:
            storage = self._extract_storage(classname, storages[0])
        return {
            "name": classname,
            "superclasses": list(normalize_superclasses(str(getattr(class_def, "Super", "") or "%Persistent"))),
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
        class_def = self.runtime.cls("%Dictionary.ClassDefinition")._OpenId(classname)
        if not self.looks_like_iris_object(class_def):
            class_def = self.runtime.cls("%Dictionary.ClassDefinition")._New()
            self._set_value(class_def, "Name", classname)
        self._set_value(class_def, "Super", ",".join(schema_class.superclasses))

        self._delete_missing(classname, "%Dictionary.PropertyDefinition", schema_class.property_map)
        self._delete_missing(classname, "%Dictionary.IndexDefinition", schema_class.index_map)
        self._delete_missing(classname, "%Dictionary.ParameterDefinition", schema_class.parameters)
        if schema_class.storage is None:
            self._delete_all_storage(classname)

        for prop in schema_class.properties:
            prop_def = self.runtime.cls("%Dictionary.PropertyDefinition")._OpenId(f"{classname}||{prop.name}")
            if not self.looks_like_iris_object(prop_def):
                prop_def = self.runtime.cls("%Dictionary.PropertyDefinition")._New()
                prop_def.parent = class_def
                self._set_value(prop_def, "Name", prop.name)
            self._set_value(prop_def, "Type", prop.iris_type)
            self._set_value(prop_def, "Required", prop.required)
            self._set_value(prop_def, "InitialExpression", prop.default)
            self._set_value(prop_def, "Description", prop.description)
            self._check_status(prop_def._Save())

        for idx in schema_class.indexes:
            idx_def = self.runtime.cls("%Dictionary.IndexDefinition")._OpenId(f"{classname}||{idx.name}")
            if not self.looks_like_iris_object(idx_def):
                idx_def = self.runtime.cls("%Dictionary.IndexDefinition")._New()
                idx_def.parent = class_def
                self._set_value(idx_def, "Name", idx.name)
            self._set_value(idx_def, "Properties", idx.properties)
            self._set_value(idx_def, "Unique", idx.unique)
            self._set_value(idx_def, "PrimaryKey", idx.primary_key)
            self._check_status(idx_def._Save())

        for name, value in schema_class.parameters.items():
            param_def = self.runtime.cls("%Dictionary.ParameterDefinition")._OpenId(f"{classname}||{name}")
            if not self.looks_like_iris_object(param_def):
                param_def = self.runtime.cls("%Dictionary.ParameterDefinition")._New()
                param_def.parent = class_def
                self._set_value(param_def, "Name", name)
            self._set_value(param_def, "Default", value)
            self._check_status(param_def._Save())

        if schema_class.storage is not None:
            self._replace_storage(class_def, schema_class.storage)

        self._check_status(class_def._Save())
        self.compile(classname)

    def save_object(self, classname: str, data: dict[str, Any], obj_id: Any | None = None) -> Any:
        cls = self.runtime.cls(classname)
        obj = cls._OpenId(obj_id) if obj_id is not None else cls._New()
        schema = self.load_schema(classname) or {"properties": []}
        property_types = {item["name"]: item.get("iris_type", "%String") for item in schema.get("properties", [])}
        for key, value in data.items():
            setattr(obj, key, self._coerce_runtime_value(value, property_types.get(key, "%String")))
        self._check_status(obj._Save())
        try:
            return obj._Id()
        except Exception:
            return obj_id

    def open_native_object(self, classname: str, obj_id: Any) -> Any | None:
        cls = self.runtime.cls(classname)
        obj = cls._OpenId(obj_id)
        if not self.looks_like_iris_object(obj):
            return None
        return obj

    def native_class(self, classname: str) -> Any:
        return self.runtime.cls(classname)

    def open_object(self, classname: str, obj_id: Any) -> dict[str, Any] | None:
        cls = self.runtime.cls(classname)
        obj = cls._OpenId(obj_id)
        if not self.looks_like_iris_object(obj):
            return None
        schema = self.load_schema(classname)
        if schema is None:
            return None
        return {
            "id": obj_id,
            "data": {prop["name"]: getattr(obj, prop["name"], None) for prop in schema["properties"]},
        }

    def delete_object(self, classname: str, obj_id: Any) -> None:
        cls = self.runtime.cls(classname)
        self._check_status(cls._DeleteId(obj_id))

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
        sql = f"SELECT {', '.join(select_fields)} FROM {classname}"
        params: list[Any] = []
        if filters:
            clauses = []
            for key, value in filters.items():
                clauses.append(f"{key} = ?")
                params.append(value)
            sql += " WHERE " + " AND ".join(clauses)
        if order_by:
            sql += f" ORDER BY {order_by}"
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
        return value not in {None, "", 0}

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

    def _replace_storage(self, class_def: Any, storage: dict[str, Any]) -> None:
        classname = str(getattr(class_def, "Name"))
        self._delete_all_storage(classname)
        storage_def = self.runtime.cls("%Dictionary.StorageDefinition")._New()
        storage_def.parent = class_def
        self._set_value(storage_def, "Name", storage.get("name", "Default"))
        for key, setter_name in _STORAGE_TOP_LEVEL_FIELDS:
            self._set_value(storage_def, setter_name, storage.get(key, ""))
        self._check_status(storage_def._Save())
        self._replace_storage_children(storage_def, storage)

    def _extract_storage(self, classname: str, storage_def: Any) -> dict[str, Any]:
        storage_name = str(getattr(storage_def, "Name", "") or "")
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
        return {key: value for key, value in storage.items() if value != "" and value is not None}

    def _replace_storage_children(self, storage_def: Any, storage: dict[str, Any]) -> None:
        storage_name = str(storage.get("name", "Default"))
        classname = str(getattr(getattr(storage_def, "parent", None), "Name", "") or "")
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

        for item in storage.get("data", []):
            data_def = self.runtime.cls("%Dictionary.StorageDataDefinition")._New()
            data_def.parent = storage_def
            self._set_value(data_def, "Name", item.get("name", ""))
            self._set_value(data_def, "Structure", item.get("structure", ""))
            self._check_status(data_def._Save())
            for value in item.get("values", []):
                value_def = self.runtime.cls("%Dictionary.StorageDataValueDefinition")._New()
                value_def.parent = data_def
                self._set_value(value_def, "Name", value.get("name", ""))
                self._set_value(value_def, "Value", value.get("value", ""))
                self._check_status(value_def._Save())

        for item in storage.get("properties", []):
            property_def = self.runtime.cls("%Dictionary.StoragePropertyDefinition")._New()
            property_def.parent = storage_def
            self._set_value(property_def, "Name", item.get("name", ""))
            for key, setter_name in _STORAGE_PROPERTY_FIELDS:
                self._set_value(property_def, setter_name, item.get(key, ""))
            self._check_status(property_def._Save())

        for item in storage.get("sql_maps", []):
            sql_map_def = self.runtime.cls("%Dictionary.StorageSQLMapDefinition")._New()
            sql_map_def.parent = storage_def
            self._set_value(sql_map_def, "Name", item.get("name", ""))
            for key, setter_name in _STORAGE_SQL_MAP_FIELDS:
                self._set_value(sql_map_def, setter_name, item.get(key, ""))
            self._check_status(sql_map_def._Save())

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
        if value is None:
            return None
        if iris_type == "%Boolean":
            return 1 if bool(value) else 0
        if iris_type in {"%Integer", "%SmallInt", "%BigInt"}:
            return int(value)
        if iris_type in {"%Float", "%Double", "%Numeric", "%Decimal"}:
            return float(value)
        return value


def _sort_storage_value_name(value: Any) -> tuple[int, str]:
    text = str(value)
    try:
        return (0, f"{int(text):020d}")
    except Exception:
        return (1, text)


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


class NetworkRuntime(_BaseRuntime):
    """Backend for InterSystems IRIS accessed via the ``intersystems_iris``
    (Python Gateway / native-API) driver.

    Mirrors ``iris_global.IRISGref``: extracts ``driver_connection`` from the
    SQLAlchemy raw connection and wraps it with the ``IRIS`` native-API object.
    SQL is executed through the raw DBAPI cursor so ``?`` placeholders work
    identically to the embedded backend.
    """

    def __init__(self, engine: Any) -> None:
        from intersystems_iris import IRIS  # type: ignore[import]

        self._raw_conn = engine.raw_connection()
        self.runtime = IRIS(self._raw_conn.driver_connection)

    def sql(self, statement: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        cursor = self._raw_conn.cursor()
        cursor.execute(statement, params or [])
        rows = cursor.fetchall()
        return [tuple(row) for row in rows]


class OfficialRuntime(_BaseRuntime):
    """Backend for InterSystems IRIS accessed via the official ``iris``
    (``iris+intersystems``) driver.

    Mirrors ``iris_global.IRISOfficial``: extracts ``driver_connection`` from
    the SQLAlchemy raw connection and wraps it with the ``IRIS`` native-API
    object.  SQL is executed through the raw DBAPI cursor.
    """

    def __init__(self, engine: Any) -> None:
        from iris import IRIS  # type: ignore[import]

        self._raw_conn = engine.raw_connection()
        self.runtime = IRIS(self._raw_conn.driver_connection)

    def sql(self, statement: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        cursor = self._raw_conn.cursor()
        cursor.execute(statement, params or [])
        rows = cursor.fetchall()
        return [tuple(row) for row in rows]


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


# ---------------------------------------------------------------------------
# Module-level default-runtime management (unchanged public API)
# ---------------------------------------------------------------------------

_DEFAULT_RUNTIME: IRISRuntime | None = None
_RUNTIME_GENERATION = 0


def _get_runtime() -> IRISRuntime:
    global _DEFAULT_RUNTIME
    if _DEFAULT_RUNTIME is None:
        _DEFAULT_RUNTIME = IRISRuntime()
    return _DEFAULT_RUNTIME


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
    global _DEFAULT_RUNTIME, _RUNTIME_GENERATION
    if runtime is not None:
        _DEFAULT_RUNTIME = runtime
    elif engine is not None:
        _DEFAULT_RUNTIME = IRISRuntime(engine=engine)
    else:
        _DEFAULT_RUNTIME = _DEFAULT_RUNTIME or IRISRuntime()
    _RUNTIME_GENERATION += 1
    return _DEFAULT_RUNTIME


def reset_default_runtime() -> None:
    global _DEFAULT_RUNTIME, _RUNTIME_GENERATION
    _DEFAULT_RUNTIME = None
    _RUNTIME_GENERATION += 1
