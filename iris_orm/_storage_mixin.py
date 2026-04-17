from __future__ import annotations

import dataclasses
from typing import Any

from .storage import StorageDefinition, StorageProperty, StorageSQLMap


def _snake_to_iris_name(name: str) -> str:
    """Convert a snake_case Python field name to the corresponding IRIS TitleCase setter name.

    Trailing underscores (used to avoid Python keyword conflicts, e.g. ``global_``) are
    stripped before conversion, so ``global_`` → ``"Global"``.
    """
    return "".join(part.capitalize() for part in name.rstrip("_").split("_"))


# Ordered (python_attr_name, IRIS_setter_name) pairs derived from the dataclass definitions
# so there is a single source of truth and no manual list to keep in sync.
_STORAGE_TOP_LEVEL_FIELDS: list[tuple[str, str]] = [
    (f.name, _snake_to_iris_name(f.name))
    for f in dataclasses.fields(StorageDefinition)
    if f.name not in {"name", "data", "properties", "sql_maps"}
]

_STORAGE_PROPERTY_FIELDS: list[tuple[str, str]] = [
    (f.name, _snake_to_iris_name(f.name))
    for f in dataclasses.fields(StorageProperty)
    if f.name != "name"
]

_STORAGE_SQL_MAP_FIELDS: list[tuple[str, str]] = [
    (f.name, _snake_to_iris_name(f.name))
    for f in dataclasses.fields(StorageSQLMap)
    if f.name != "name"
]


class _StorageMixin:
    """IRIS storage-definition CRUD.

    Depends on ``_IRISObjectMixin`` (``_check_status``, ``looks_like_iris_object``),
    ``_SchemaMixin`` (``_schema_new``, ``_schema_get``, ``_schema_set``,
    ``_schema_set_parent``, ``_schema_save``), and ``_SqlMixin`` (``sql``).
    """

    # ------------------------------------------------------------------ Top-level helpers

    def _delete_all_storage(self, classname: str) -> None:
        try:
            self.sql("DELETE FROM %Dictionary.StorageDefinition WHERE parent = ?", [classname])  # type: ignore[attr-defined]
        except Exception:
            return

    def _replace_storage(self, class_def: Any, storage: StorageDefinition | dict[str, Any]) -> None:
        storage_defn = StorageDefinition.from_dict(storage)
        if storage_defn is None:
            return
        classname = str(self._schema_get(class_def, "Name"))  # type: ignore[attr-defined]
        self._delete_all_storage(classname)
        storage_def = self._schema_new("%Dictionary.StorageDefinition")  # type: ignore[attr-defined]
        self._schema_set_parent(storage_def, class_def)  # type: ignore[attr-defined]
        self._schema_set(storage_def, "Name", storage_defn.name)  # type: ignore[attr-defined]
        for key, setter_name in _STORAGE_TOP_LEVEL_FIELDS:
            self._schema_set(storage_def, setter_name, getattr(storage_defn, key))  # type: ignore[attr-defined]
        self._check_status(self._schema_save(storage_def), schema=True)  # type: ignore[attr-defined]
        self._replace_storage_children(storage_def, storage_defn)

    def _extract_storage(self, classname: str, storage_def: Any) -> StorageDefinition:
        storage_name = str(self._schema_get(storage_def, "Name") or "")  # type: ignore[attr-defined]
        storage: dict[str, Any] = {"name": storage_name}
        definition_rows = self.sql(  # type: ignore[attr-defined]
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
        data_rows = self.sql(  # type: ignore[attr-defined]
            "SELECT Name, Structure FROM %Dictionary.StorageDataDefinition WHERE parent = ?",
            [storage_id],
        )
        if data_rows:
            data_items: list[dict[str, Any]] = []
            for row in data_rows:
                data_name = str(row[0])
                values = self.sql(  # type: ignore[attr-defined]
                    "SELECT Name, Value FROM %Dictionary.StorageDataValueDefinition WHERE parent = ?",
                    [f"{storage_id}||{data_name}"],
                )

                def _sort_key(item: tuple[Any, ...]) -> tuple[int, str]:
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
                            {"name": str(v[0]), "value": str(v[1])}
                            for v in sorted(values, key=_sort_key)
                        ],
                    }
                )
            storage["data"] = data_items
        property_rows = self.sql(  # type: ignore[attr-defined]
            "SELECT Name, AverageFieldSize, BiasQueriesAsOutlier, ChildBlockCount, ChildExtentSize, "
            "Histogram, OutlierSelectivity, Selectivity, StreamLocation "
            "FROM %Dictionary.StoragePropertyDefinition WHERE parent = ?",
            [storage_id],
        )
        if property_rows:
            props: list[dict[str, Any]] = []
            for row in property_rows:
                item: dict[str, Any] = {"name": str(row[0])}
                for index, (key, _) in enumerate(_STORAGE_PROPERTY_FIELDS, start=1):
                    v = row[index]
                    if v not in {"", None}:
                        item[key] = str(v)
                props.append(item)
            storage["properties"] = props
        sql_map_rows = self.sql(  # type: ignore[attr-defined]
            'SELECT Name, BlockCount, Condition, ConditionFields, ConditionalWithHostVars, "_Global", '
            "PopulationPct, PopulationType, RowReference, Structure, Type "
            "FROM %Dictionary.StorageSQLMapDefinition WHERE parent = ?",
            [storage_id],
        )
        if sql_map_rows:
            sql_maps: list[dict[str, Any]] = []
            for row in sql_map_rows:
                item = {"name": str(row[0])}
                for index, (key, _) in enumerate(_STORAGE_SQL_MAP_FIELDS, start=1):
                    v = row[index]
                    if v not in {"", None}:
                        item[key] = str(v)
                sql_maps.append(item)
            storage["sql_maps"] = sql_maps
        return (
            StorageDefinition.from_dict({k: v for k, v in storage.items() if v != "" and v is not None})
            or StorageDefinition(name=storage_name)
        )

    def _replace_storage_children(self, storage_def: Any, storage: StorageDefinition) -> None:
        storage_name = str(storage.name or "Default")
        parent = self._schema_get(storage_def, "parent", as_object=True)  # type: ignore[attr-defined]
        classname = str(self._schema_get(parent, "Name") or "") if parent is not None else ""  # type: ignore[attr-defined]
        storage_id = f"{classname}||{storage_name}" if classname else ""
        if storage_id:
            for stmt, params in [
                ("DELETE FROM %Dictionary.StorageDataValueDefinition WHERE parent %STARTSWITH ?", [f"{storage_id}||"]),
                ("DELETE FROM %Dictionary.StorageDataDefinition WHERE parent = ?", [storage_id]),
                ("DELETE FROM %Dictionary.StoragePropertyDefinition WHERE parent = ?", [storage_id]),
                ("DELETE FROM %Dictionary.StorageSQLMapDefinition WHERE parent = ?", [storage_id]),
            ]:
                try:
                    self.sql(stmt, params)  # type: ignore[attr-defined]
                except Exception:
                    continue
        for item in storage.data:
            data_def = self._schema_new("%Dictionary.StorageDataDefinition")  # type: ignore[attr-defined]
            self._schema_set_parent(data_def, storage_def)  # type: ignore[attr-defined]
            self._schema_set(data_def, "Name", item.name)  # type: ignore[attr-defined]
            self._schema_set(data_def, "Structure", item.structure)  # type: ignore[attr-defined]
            self._check_status(self._schema_save(data_def), schema=True)  # type: ignore[attr-defined]
            for name, value in sorted(item.values.items()):
                value_def = self._schema_new("%Dictionary.StorageDataValueDefinition")  # type: ignore[attr-defined]
                self._schema_set_parent(value_def, data_def)  # type: ignore[attr-defined]
                self._schema_set(value_def, "Name", name)  # type: ignore[attr-defined]
                self._schema_set(value_def, "Value", value)  # type: ignore[attr-defined]
                self._check_status(self._schema_save(value_def), schema=True)  # type: ignore[attr-defined]
        for item in storage.properties:
            prop_def = self._schema_new("%Dictionary.StoragePropertyDefinition")  # type: ignore[attr-defined]
            self._schema_set_parent(prop_def, storage_def)  # type: ignore[attr-defined]
            self._schema_set(prop_def, "Name", item.name)  # type: ignore[attr-defined]
            for key, setter_name in _STORAGE_PROPERTY_FIELDS:
                self._schema_set(prop_def, setter_name, getattr(item, key))  # type: ignore[attr-defined]
            self._check_status(self._schema_save(prop_def), schema=True)  # type: ignore[attr-defined]
        for item in storage.sql_maps:
            sql_map_def = self._schema_new("%Dictionary.StorageSQLMapDefinition")  # type: ignore[attr-defined]
            self._schema_set_parent(sql_map_def, storage_def)  # type: ignore[attr-defined]
            self._schema_set(sql_map_def, "Name", item.name)  # type: ignore[attr-defined]
            for key, setter_name in _STORAGE_SQL_MAP_FIELDS:
                self._schema_set(sql_map_def, setter_name, getattr(item, key))  # type: ignore[attr-defined]
            self._check_status(self._schema_save(sql_map_def), schema=True)  # type: ignore[attr-defined]
