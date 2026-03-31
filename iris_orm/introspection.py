"""
Compatibility introspection helpers backed by the canonical schema compiler.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .adapter import IRISAdapter
from .schema import (
    SchemaClass,
    SchemaCompiler,
    SchemaIndex,
    SchemaProperty,
    SchemaRelationship,
    SchemaStorage,
    render_storage,
)
from .types import iris_type_to_python


@dataclass(frozen=True)
class PropertyInfo:
    name: str
    iris_type: str
    python_type: type
    required: bool
    collection: str
    default: str
    maxlen: int | None = None
    description: str = ""


@dataclass(frozen=True)
class RelationshipInfo:
    name: str
    related_classname: str
    cardinality: str
    inverse: str
    description: str = ""


@dataclass(frozen=True)
class IndexInfo:
    name: str
    properties: str
    unique: bool = False
    primary_key: bool = False


@dataclass(frozen=True)
class ClassDetails:
    classname: str
    super: str
    properties: list[PropertyInfo]
    relationships: list[RelationshipInfo]
    class_parameters: dict[str, str]
    indexes: list[IndexInfo]
    storage: dict[str, Any] | None = None
    storage_definition: str = ""


def list_classes(pattern: str = "*", connection: Any = None) -> list[str]:
    adapter = connection or IRISAdapter()
    sql_pattern = pattern.replace("*", "%")
    rows = adapter.sql_exec(
        "SELECT Name FROM %Dictionary.ClassDefinition WHERE Name LIKE ? ORDER BY Name",
        [sql_pattern],
    )
    return [str(row[0]) for row in rows]


def get_class_super(classname: str, connection: Any = None) -> str:
    schema_class = _compiler(connection).class_from_iris(classname)
    return schema_class.superclass


def get_class_properties(classname: str, connection: Any = None) -> list[PropertyInfo]:
    schema_class = _compiler(connection).class_from_iris(classname)
    return [_property_info(item) for item in schema_class.properties]


def get_class_relationships(classname: str, connection: Any = None) -> list[RelationshipInfo]:
    schema_class = _compiler(connection).class_from_iris(classname)
    return [_relationship_info(item) for item in schema_class.relationships]


def get_class_parameters(classname: str, connection: Any = None) -> dict[str, str]:
    return dict(_compiler(connection).class_from_iris(classname).parameters)


def get_class_indexes(classname: str, connection: Any = None) -> list[IndexInfo]:
    schema_class = _compiler(connection).class_from_iris(classname)
    return [_index_info(item) for item in schema_class.indexes]


def get_class_details(classname: str, connection: Any = None) -> ClassDetails:
    schema_class = _compiler(connection).class_from_iris(classname)
    storage = schema_class.storage.to_dict() if schema_class.storage is not None else None
    return ClassDetails(
        classname=schema_class.name,
        super=schema_class.superclass,
        properties=[_property_info(item) for item in schema_class.properties],
        relationships=[_relationship_info(item) for item in schema_class.relationships],
        class_parameters=dict(schema_class.parameters),
        indexes=[_index_info(item) for item in schema_class.indexes],
        storage=storage,
        storage_definition=render_storage(schema_class.storage),
    )


def render_storage_definition(storage: dict[str, Any] | SchemaStorage | None) -> str:
    if isinstance(storage, dict):
        storage = SchemaStorage.from_dict(storage)
    return render_storage(storage)


def parse_storage_definition(storage_definition: str) -> dict[str, Any] | None:
    compiler = SchemaCompiler()
    schema_class = compiler.class_from_cls_source(
        "Class Tmp.Storage Extends %Persistent\n{\n"
        f"{storage_definition}\n"
        "}\n"
    )
    if schema_class.storage is None:
        return None
    return schema_class.storage.to_dict()


def _compiler(connection: Any = None) -> SchemaCompiler:
    return SchemaCompiler(connection or IRISAdapter())


def _property_info(prop: SchemaProperty) -> PropertyInfo:
    return PropertyInfo(
        name=prop.name,
        iris_type=prop.iris_type,
        python_type=iris_type_to_python(prop.iris_type),
        required=prop.required,
        collection=prop.collection,
        default=prop.default,
        maxlen=prop.maxlen,
        description=prop.description,
    )


def _relationship_info(rel: SchemaRelationship) -> RelationshipInfo:
    return RelationshipInfo(
        name=rel.name,
        related_classname=rel.related_classname,
        cardinality=rel.cardinality,
        inverse=rel.inverse,
        description=rel.description,
    )


def _index_info(index: SchemaIndex) -> IndexInfo:
    return IndexInfo(
        name=index.name,
        properties=index.properties,
        unique=index.unique,
        primary_key=index.primary_key,
    )
