from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any

from iris_orm.introspection import parse_storage_definition
from iris_orm.schema import SchemaStorage


class FakeParameterBag:
    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._values = dict(initial or {})

    def SetAt(self, value: str, key: str) -> None:
        self._values[str(key)] = str(value)

    def GetAt(self, key: str) -> str:
        return self._values.get(str(key), "")

    def to_dict(self) -> dict[str, str]:
        return dict(self._values)


class FakeCollection:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def Count(self) -> int:
        return len(self._items)

    def GetAt(self, index: int) -> Any:
        return self._items[index - 1]


@dataclass
class FakeStorageValue:
    Name: str
    Value: str


@dataclass
class FakeStorageData:
    Name: str
    Structure: str
    Subscript: str
    Values: FakeCollection


class FakeStorageDefinition:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.Name = payload.get("name", "Default")
        self.Type = payload.get("type", "")
        self.DataLocation = payload.get("data_location", "")
        self.DefaultData = payload.get("default_data", "")
        self.ExtentLocation = payload.get("extent_location", "")
        self.IdLocation = payload.get("id_location", "")
        self.IndexLocation = payload.get("index_location", "")
        self.StreamLocation = payload.get("stream_location", "")
        self.IdFunction = payload.get("id_function", "")
        self.Data = FakeCollection(
            [
                FakeStorageData(
                    Name=item.get("name", ""),
                    Structure=item.get("structure", ""),
                    Subscript=item.get("subscript", ""),
                    Values=FakeCollection(
                        [FakeStorageValue(Name=value.get("name", ""), Value=value.get("value", "")) for value in item.get("values", [])]
                    ),
                )
                for item in payload.get("data", [])
            ]
        )


class FakePropertyDefinition:
    def __init__(self, adapter: "FakeAdapter", classname: str, name: str, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        self._adapter = adapter
        self._classname = classname
        self.Name = name
        self.Type = payload.get("iris_type", "%String")
        self.Required = int(payload.get("required", False))
        self.Collection = payload.get("collection", "")
        self.InitialExpression = payload.get("default", "")
        self.Description = payload.get("description", "")
        self.Relationship = int(payload.get("relationship", False))
        self.Cardinality = payload.get("cardinality", "")
        self.Inverse = payload.get("inverse", "")
        self.Private = 0
        self.Internal = 0
        self.parent = None
        self.Parameters = FakeParameterBag(
            {"MAXLEN": str(payload["maxlen"])} if payload.get("maxlen") is not None else {}
        )

    def _Save(self) -> int:
        classname = self._classname or getattr(self.parent, "Name", "")
        self._classname = classname
        schema = self._adapter.schemas.setdefault(classname, self._adapter.empty_schema(classname))
        if self.Relationship:
            schema["relationships"][self.Name] = {
                "related_classname": self.Type,
                "cardinality": self.Cardinality,
                "inverse": self.Inverse,
                "description": self.Description,
            }
        else:
            schema["properties"][self.Name] = {
                "iris_type": self.Type,
                "required": bool(self.Required),
                "collection": str(self.Collection).lower(),
                "default": self.InitialExpression,
                "maxlen": _as_int(self.Parameters.GetAt("MAXLEN")),
                "description": self.Description,
            }
        return 1


class FakeRelationshipDefinition(FakePropertyDefinition):
    def __init__(self, adapter: "FakeAdapter", classname: str, name: str, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        payload["relationship"] = True
        if "related_classname" in payload and "iris_type" not in payload:
            payload["iris_type"] = payload["related_classname"]
        super().__init__(adapter, classname, name, payload)


class FakeIndexDefinition:
    def __init__(self, adapter: "FakeAdapter", classname: str, name: str, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        self._adapter = adapter
        self._classname = classname
        self.Name = name
        self.Properties = payload.get("properties", "")
        self.Unique = int(payload.get("unique", False))
        self.PrimaryKey = int(payload.get("primary_key", False))
        self.parent = None

    def _Save(self) -> int:
        classname = self._classname or getattr(self.parent, "Name", "")
        self._classname = classname
        schema = self._adapter.schemas.setdefault(classname, self._adapter.empty_schema(classname))
        schema["indexes"][self.Name] = {
            "properties": self.Properties,
            "unique": bool(self.Unique),
            "primary_key": bool(self.PrimaryKey),
        }
        return 1


class FakeParameterDefinition:
    def __init__(self, adapter: "FakeAdapter", classname: str, name: str, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        self._adapter = adapter
        self._classname = classname
        self.Name = name
        self.Default = payload.get("value", "")
        self.parent = None

    def _Save(self) -> int:
        classname = self._classname or getattr(self.parent, "Name", "")
        self._classname = classname
        schema = self._adapter.schemas.setdefault(classname, self._adapter.empty_schema(classname))
        schema["parameters"][self.Name] = self.Default
        return 1


class FakeClassDefinition:
    def __init__(self, adapter: "FakeAdapter", classname: str, schema: dict[str, Any] | None = None) -> None:
        self._adapter = adapter
        self.Name = classname
        self.Super = "%Persistent" if schema is None else schema.get("superclass", "%Persistent")
        self.Storage = ""
        self.StorageDefinition = ""

    @property
    def Properties(self) -> FakeCollection:
        schema = self._adapter.schemas.get(self.Name, self._adapter.empty_schema(self.Name))
        props = [
            FakePropertyDefinition(self._adapter, self.Name, name, payload)
            for name, payload in sorted(schema["properties"].items())
        ]
        rels = [
            FakeRelationshipDefinition(self._adapter, self.Name, name, payload)
            for name, payload in sorted(schema["relationships"].items())
        ]
        return FakeCollection(props + rels)

    @property
    def Indices(self) -> FakeCollection:
        schema = self._adapter.schemas.get(self.Name, self._adapter.empty_schema(self.Name))
        return FakeCollection(
            [
                FakeIndexDefinition(self._adapter, self.Name, name, payload)
                for name, payload in sorted(schema["indexes"].items())
            ]
        )

    @property
    def Parameters(self) -> FakeCollection:
        schema = self._adapter.schemas.get(self.Name, self._adapter.empty_schema(self.Name))
        return FakeCollection(
            [
                FakeParameterDefinition(self._adapter, self.Name, name, {"value": value})
                for name, value in sorted(schema["parameters"].items())
            ]
        )

    @property
    def Storages(self) -> FakeCollection:
        schema = self._adapter.schemas.get(self.Name, self._adapter.empty_schema(self.Name))
        storage = schema.get("storage")
        if storage is None:
            return FakeCollection([])
        return FakeCollection([FakeStorageDefinition(storage)])

    def _Save(self) -> int:
        schema = self._adapter.schemas.setdefault(self.Name, self._adapter.empty_schema(self.Name))
        schema["superclass"] = self.Super
        if self.StorageDefinition:
            parsed = parse_storage_definition(self.StorageDefinition)
            schema["storage"] = parsed
        return 1


class FakeDictionaryProxy:
    def __init__(self, adapter: "FakeAdapter", kind: str) -> None:
        self._adapter = adapter
        self._kind = kind

    def _New(self) -> Any:
        if self._kind == "class":
            return FakeClassDefinition(self._adapter, "")
        if self._kind == "property":
            return FakePropertyDefinition(self._adapter, "", "")
        if self._kind == "relationship":
            return FakeRelationshipDefinition(self._adapter, "", "")
        if self._kind == "index":
            return FakeIndexDefinition(self._adapter, "", "")
        if self._kind == "parameter":
            return FakeParameterDefinition(self._adapter, "", "")
        raise ValueError(self._kind)

    def _OpenId(self, identifier: str) -> Any:
        if self._kind == "class":
            schema = self._adapter.schemas.get(identifier)
            return None if schema is None else FakeClassDefinition(self._adapter, identifier, schema)
        classname, name = identifier.split("||", 1)
        schema = self._adapter.schemas.get(classname)
        if schema is None:
            return None
        if self._kind == "property":
            payload = schema["properties"].get(name)
            return None if payload is None else FakePropertyDefinition(self._adapter, classname, name, payload)
        if self._kind == "relationship":
            payload = schema["relationships"].get(name)
            return None if payload is None else FakeRelationshipDefinition(self._adapter, classname, name, payload)
        if self._kind == "index":
            payload = schema["indexes"].get(name)
            return None if payload is None else FakeIndexDefinition(self._adapter, classname, name, payload)
        if self._kind == "parameter":
            if name not in schema["parameters"]:
                return None
            return FakeParameterDefinition(self._adapter, classname, name, {"value": schema["parameters"][name]})
        return None

    def _DeleteId(self, identifier: str) -> None:
        if self._kind == "class":
            self._adapter.schemas.pop(identifier, None)
            self._adapter.objects.pop(identifier, None)
            return
        classname, name = identifier.split("||", 1)
        schema = self._adapter.schemas.setdefault(classname, self._adapter.empty_schema(classname))
        mapping_name = {
            "property": "properties",
            "relationship": "relationships",
            "index": "indexes",
            "parameter": "parameters",
        }[self._kind]
        schema[mapping_name].pop(name, None)

    def _ExistsId(self, identifier: str) -> int:
        return int(identifier in self._adapter.schemas)


class FakeSystemObj:
    def __init__(self, adapter: "FakeAdapter") -> None:
        self._adapter = adapter
        self.compiled: list[tuple[str, str]] = []

    def Compile(self, classname: str, flags: str) -> int:
        self.compiled.append((classname, flags))
        return 1


class FakePersistentObject:
    def __init__(self, adapter: "FakeAdapter", classname: str) -> None:
        self._adapter = adapter
        self._classname = classname
        self._id: str | None = None

    def _Save(self) -> int:
        if self._id is None:
            self._id = str(self._adapter.next_id(self._classname))
        self._adapter.objects.setdefault(self._classname, {})[self._id] = self
        return 1

    def _Id(self) -> str:
        if self._id is None:
            raise RuntimeError("Object not saved")
        return self._id


class FakeDomainProxy:
    def __init__(self, adapter: "FakeAdapter", classname: str) -> None:
        self._adapter = adapter
        self._classname = classname

    def _New(self) -> FakePersistentObject:
        return FakePersistentObject(self._adapter, self._classname)

    def _OpenId(self, identifier: str) -> Any:
        return self._adapter.objects.get(self._classname, {}).get(str(identifier))

    def _DeleteId(self, identifier: str) -> None:
        self._adapter.objects.get(self._classname, {}).pop(str(identifier), None)


class FakeAdapter:
    def __init__(self) -> None:
        self.schemas: dict[str, dict[str, Any]] = {}
        self.objects: dict[str, dict[str, FakePersistentObject]] = {}
        self._id_counters: dict[str, int] = {}
        self.system_obj = FakeSystemObj(self)

    def empty_schema(self, classname: str) -> dict[str, Any]:
        return {
            "name": classname,
            "superclass": "%Persistent",
            "properties": {},
            "relationships": {},
            "indexes": {},
            "parameters": {},
            "storage": None,
        }

    def next_id(self, classname: str) -> int:
        self._id_counters[classname] = self._id_counters.get(classname, 0) + 1
        return self._id_counters[classname]

    def class_exists(self, classname: str) -> bool:
        return classname in self.schemas

    def iris_cls(self, classname: str) -> Any:
        mapping = {
            "%Dictionary.ClassDefinition": FakeDictionaryProxy(self, "class"),
            "%Dictionary.PropertyDefinition": FakeDictionaryProxy(self, "property"),
            "%Dictionary.RelationshipDefinition": FakeDictionaryProxy(self, "relationship"),
            "%Dictionary.IndexDefinition": FakeDictionaryProxy(self, "index"),
            "%Dictionary.ParameterDefinition": FakeDictionaryProxy(self, "parameter"),
            "%SYSTEM.OBJ": self.system_obj,
        }
        return mapping.get(classname, FakeDomainProxy(self, classname))

    def new_object(self, classname: str) -> Any:
        return self.iris_cls(classname)._New()

    def open_object(self, classname: str, obj_id: str) -> Any:
        return self.iris_cls(classname)._OpenId(obj_id)

    def delete_object(self, classname: str, obj_id: str) -> None:
        self.iris_cls(classname)._DeleteId(obj_id)

    def compile_class(self, classname: str, flags: str = "ck") -> None:
        self.system_obj.Compile(classname, flags)

    def begin(self) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def is_success_status(self, status: Any) -> bool:
        return status in (None, 1, True) or str(status).strip() == "1"

    def looks_like_iris_object(self, value: Any) -> bool:
        return value is not None and hasattr(value, "_Save")

    def save(self, item: Any, *, kind: str, identifier: str) -> None:
        status = item._Save()
        if not self.is_success_status(status):
            raise RuntimeError(f"Failed to save {kind} {identifier!r}: {status!r}")

    def sql_exec(self, sql: str, params: list[Any] | None = None) -> Any:
        params = list(params or [])
        if "%Dictionary.ClassDefinition" in sql and "LIKE ?" in sql:
            pattern = str(params[0]).replace("%", "*")
            return [(name,) for name in sorted(self.schemas) if fnmatch(name, pattern)]
        if "%Dictionary.ClassDefinition" in sql and "WHERE Name = ?" in sql:
            classname = str(params[0])
            return [(classname,)] if classname in self.schemas else []
        if sql.startswith("SELECT Revision FROM IrisORM.MigrationHistory"):
            rows = sorted(self.objects.get("IrisORM.MigrationHistory", {}).values(), key=lambda item: getattr(item, "AppliedAt", ""))
            return [(getattr(item, "Revision", ""),) for item in rows]
        if sql.startswith("SELECT %ID FROM IrisORM.MigrationHistory WHERE Revision = ?"):
            revision = str(params[0])
            results = []
            for obj_id, item in self.objects.get("IrisORM.MigrationHistory", {}).items():
                if getattr(item, "Revision", "") == revision:
                    results.append((obj_id,))
            return results
        return self._select_domain(sql, params)

    def _select_domain(self, sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
        match = re.match(r"SELECT (COUNT\(\*\)|%ID) FROM ([A-Za-z0-9_.%]+)(.*)", sql)
        if match is None:
            return []
        select_expr, classname, rest = match.groups()
        rows = list(self.objects.get(classname, {}).items())
        where_match = re.search(r" WHERE (.*?)(?: ORDER BY | LIMIT | OFFSET |$)", rest)
        if where_match:
            condition_text = where_match.group(1)
            rows = self._apply_conditions(rows, condition_text, params)
        order_match = re.search(r" ORDER BY ([A-Za-z0-9_]+) (ASC|DESC)", rest)
        if order_match:
            field_name, direction = order_match.groups()
            rows.sort(key=lambda item: getattr(item[1], field_name, None))
            if direction == "DESC":
                rows.reverse()
        limit_match = re.search(r" LIMIT \?", rest)
        offset_match = re.search(r" OFFSET \?", rest)
        extras = params[-((1 if limit_match else 0) + (1 if offset_match else 0)) :] if (limit_match or offset_match) else []
        if limit_match:
            limit_value = int(extras[0])
            rows = rows[:limit_value]
        if offset_match:
            offset_value = int(extras[-1])
            rows = rows[offset_value:]
        if select_expr == "COUNT(*)":
            return [(len(rows),)]
        return [(obj_id,) for obj_id, _obj in rows]

    def _apply_conditions(self, rows: list[tuple[str, FakePersistentObject]], text: str, params: list[Any]) -> list[tuple[str, FakePersistentObject]]:
        fragments = [item.strip() for item in text.split(" AND ")]
        position = 0
        filtered = rows
        for fragment in fragments:
            if fragment == "1 = 0":
                return []
            if " IN (" in fragment:
                field_name = fragment.split(" IN ", 1)[0]
                placeholders = fragment.count("?")
                values = params[position : position + placeholders]
                position += placeholders
                filtered = [(obj_id, obj) for obj_id, obj in filtered if getattr(obj, field_name, None) in values]
            else:
                field_name = fragment.split(" = ?", 1)[0]
                value = params[position]
                position += 1
                filtered = [(obj_id, obj) for obj_id, obj in filtered if getattr(obj, field_name, None) == value]
        return filtered


def preload_schema(adapter: FakeAdapter, schema: dict[str, Any]) -> None:
    payload = copy.deepcopy(schema)
    if payload.get("storage") is not None and isinstance(payload["storage"], SchemaStorage):
        payload["storage"] = payload["storage"].to_dict()
    adapter.schemas[payload["name"]] = {
        "name": payload["name"],
        "superclass": payload.get("superclass", "%Persistent"),
        "properties": payload.get("properties", {}),
        "relationships": payload.get("relationships", {}),
        "indexes": payload.get("indexes", {}),
        "parameters": payload.get("parameters", {}),
        "storage": payload.get("storage"),
    }


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
