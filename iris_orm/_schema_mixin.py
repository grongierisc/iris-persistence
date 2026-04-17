from __future__ import annotations

from typing import Any

from .schema import (
    SchemaClass,
    match_classnames,
    normalize_superclasses,
)
from .storage import StorageDefinition


class _SchemaMixin:
    """IRIS Dictionary CRUD: load/replace class definitions, compile.

    Depends on ``_IRISObjectMixin`` (``_check_status``, ``looks_like_iris_object``,
    ``_object_invoke``), ``_SqlMixin`` (``sql``), ``_StorageMixin``
    (``_extract_storage``, ``_replace_storage``, ``_delete_all_storage``), and
    ``_PropertyValueMixin`` (``_read_maxlen``, ``_extract_property_parameters``,
    ``_replace_property_parameters``, ``_write_maxlen``).
    """

    # ------------------------------------------------------------------ Schema-object primitives

    def _schema_new(self, classname: str) -> Any:
        return self._object_new(classname)  # type: ignore[attr-defined]

    def _schema_open(self, classname: str, obj_id: Any) -> Any:
        return self._object_open(classname, obj_id)  # type: ignore[attr-defined]

    def _schema_get(self, obj: Any, name: str, *, as_object: bool = False) -> Any:  # noqa: ARG002
        return getattr(obj, name, None)

    def _schema_set(self, obj: Any, name: str, value: Any) -> None:
        self._set_value(obj, name, value)  # type: ignore[attr-defined]

    def _schema_set_parent(self, obj: Any, parent: Any) -> None:
        try:
            self._object_invoke(obj, "parentSet", parent)  # type: ignore[attr-defined]
        except Exception:
            self._object_set(obj, "parent", parent)  # type: ignore[attr-defined]

    def _schema_save(self, obj: Any) -> Any:
        return self._object_invoke(obj, "%Save")  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ Collection iteration

    def _iter_collection(self, collection: Any) -> list[Any]:
        if collection is None:
            return []
        try:
            count = int(self._object_invoke(collection, "Count"))  # type: ignore[attr-defined]
        except Exception:
            try:
                return list(collection)
            except Exception:
                return []
        return [self._object_invoke_object(collection, "GetAt", i) for i in range(1, count + 1)]  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ Utility statics

    @staticmethod
    def _normalize_default(value: str) -> str:
        return "" if value in {"", '""', "{}"} else value

    # ------------------------------------------------------------------ IRISRuntimeProtocol: schema

    def load_schema(self, classname: str) -> dict[str, Any] | None:
        class_def = self._schema_open("%Dictionary.ClassDefinition", classname)
        if not self.looks_like_iris_object(class_def):  # type: ignore[attr-defined]
            return None
        properties = []
        for prop in self._iter_collection(self._schema_get(class_def, "Properties", as_object=True)):
            if (bool(self._schema_get(prop, "Private"))
                    or bool(self._schema_get(prop, "Internal"))
                    or bool(self._schema_get(prop, "Relationship"))):
                continue
            properties.append(
                {
                    "name": str(self._schema_get(prop, "Name") or ""),
                    "iris_type": str(self._schema_get(prop, "Type") or "%String"),
                    "required": bool(self._schema_get(prop, "Required") or False),
                    "default": self._normalize_default(str(self._schema_get(prop, "InitialExpression") or "")),
                    "maxlen": self._read_maxlen(prop),  # type: ignore[attr-defined]
                    "description": str(self._schema_get(prop, "Description") or ""),
                    "parameters": self._extract_property_parameters(prop),  # type: ignore[attr-defined]
                }
            )
        indexes = []
        idx_names: list[str] = []
        try:
            idx_rows = self.sql("SELECT Name FROM %Dictionary.IndexDefinition WHERE parent = ?", [classname])  # type: ignore[attr-defined]
            idx_names = [str(row[0]) for row in idx_rows if row[0]]
        except Exception:
            pass
        if not idx_names:
            idx_names = [
                str(self._schema_get(idx, "Name") or "")
                for idx in self._iter_collection(self._schema_get(class_def, "Indexes", as_object=True))
            ]
            idx_names = [n for n in idx_names if n]
        for name in idx_names:
            idx = self._schema_open("%Dictionary.IndexDefinition", f"{classname}||{name}")
            if not self.looks_like_iris_object(idx):  # type: ignore[attr-defined]
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
        storage: StorageDefinition | None = None
        storages = list(self._iter_collection(self._schema_get(class_def, "Storages", as_object=True)))
        if storages:
            storage = self._extract_storage(classname, storages[0])  # type: ignore[attr-defined]
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
        rows = self.sql("SELECT Name FROM %Dictionary.ClassDefinition")  # type: ignore[attr-defined]
        all_names = [str(row[0]) for row in rows]
        return sorted(match_classnames(all_names, pattern))

    def replace_class(self, schema_class: SchemaClass) -> None:
        classname = schema_class.name
        class_def = self._schema_open("%Dictionary.ClassDefinition", classname)
        if not self.looks_like_iris_object(class_def):  # type: ignore[attr-defined]
            class_def = self._schema_new("%Dictionary.ClassDefinition")
            self._schema_set(class_def, "Name", classname)
        self._schema_set(class_def, "Super", ",".join(schema_class.superclasses))

        self._delete_missing(classname, "%Dictionary.PropertyDefinition", schema_class.property_map)  # type: ignore[attr-defined]
        self._delete_missing(classname, "%Dictionary.IndexDefinition", schema_class.index_map)  # type: ignore[attr-defined]
        self._delete_missing(classname, "%Dictionary.ParameterDefinition", schema_class.parameters)  # type: ignore[attr-defined]
        if schema_class.storage is None:
            self._delete_all_storage(classname)  # type: ignore[attr-defined]

        for prop in schema_class.properties:
            prop_def = self._schema_open("%Dictionary.PropertyDefinition", f"{classname}||{prop.name}")
            if not self.looks_like_iris_object(prop_def):  # type: ignore[attr-defined]
                prop_def = self._schema_new("%Dictionary.PropertyDefinition")
                self._schema_set_parent(prop_def, class_def)
                self._schema_set(prop_def, "Name", prop.name)
            self._schema_set(prop_def, "Type", prop.iris_type)
            self._schema_set(prop_def, "Required", prop.required)
            self._schema_set(prop_def, "InitialExpression", prop.default)
            self._schema_set(prop_def, "Description", prop.description)
            self._replace_property_parameters(prop_def, prop.parameters)  # type: ignore[attr-defined]
            self._write_maxlen(prop_def, prop.maxlen)  # type: ignore[attr-defined]
            self._check_status(self._schema_save(prop_def), schema=True)  # type: ignore[attr-defined]

        for idx in schema_class.indexes:
            idx_def = self._schema_open("%Dictionary.IndexDefinition", f"{classname}||{idx.name}")
            if not self.looks_like_iris_object(idx_def):  # type: ignore[attr-defined]
                idx_def = self._schema_new("%Dictionary.IndexDefinition")
                self._schema_set_parent(idx_def, class_def)
                self._schema_set(idx_def, "Name", idx.name)
            self._schema_set(idx_def, "Properties", idx.properties)
            self._schema_set(idx_def, "Unique", idx.unique)
            self._schema_set(idx_def, "PrimaryKey", idx.primary_key)
            self._check_status(self._schema_save(idx_def), schema=True)  # type: ignore[attr-defined]

        for name, value in schema_class.parameters.items():
            param_def = self._schema_open("%Dictionary.ParameterDefinition", f"{classname}||{name}")
            if not self.looks_like_iris_object(param_def):  # type: ignore[attr-defined]
                param_def = self._schema_new("%Dictionary.ParameterDefinition")
                self._schema_set_parent(param_def, class_def)
                self._schema_set(param_def, "Name", name)
            self._schema_set(param_def, "Default", value)
            self._check_status(self._schema_save(param_def), schema=True)  # type: ignore[attr-defined]

        if schema_class.storage is not None:
            self._replace_storage(class_def, schema_class.storage)  # type: ignore[attr-defined]

        self._check_status(self._schema_save(class_def), schema=True)  # type: ignore[attr-defined]
        self.compile(classname)

    def compile(self, classname: str) -> None:
        status = self.runtime.cls("%SYSTEM.OBJ").Compile(classname, "ck")  # type: ignore[attr-defined]
        self._check_status(status, compile=True)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ Dictionary diff helper

    def _delete_missing(self, classname: str, dictionary_class: str, expected: Any) -> None:
        try:
            rows = self.sql(f"SELECT Name FROM {dictionary_class} WHERE parent = ?", [classname])  # type: ignore[attr-defined]
        except Exception:
            return
        names = {str(row[0]) for row in rows}
        expected_names = set(expected.keys()) if isinstance(expected, dict) else set(expected)
        for name in names - expected_names:
            try:
                self.sql(f"DELETE FROM {dictionary_class} WHERE parent = ? AND Name = ?", [classname, name])  # type: ignore[attr-defined]
            except Exception:
                continue
