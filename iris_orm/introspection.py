"""
IRIS class introspection helpers backed by %Dictionary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .types import iris_type_to_python

if TYPE_CHECKING:
    from .connection import IRISConnection


@dataclass(frozen=True)
class PropertyInfo:
    name: str
    iris_type: str
    python_type: type
    required: bool
    collection: str   # "" | "list" | "array"
    default: str      # raw IRIS default expression
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
class UnsupportedFeatureInfo:
    kind: str
    name: str


@dataclass(frozen=True)
class ClassDetails:
    classname: str
    super: str
    properties: list[PropertyInfo]
    relationships: list[RelationshipInfo]
    class_parameters: dict[str, str]
    indexes: list[IndexInfo]
    storage_definition: str
    unsupported_features: list[UnsupportedFeatureInfo]


def _get_connection(connection: IRISConnection | None) -> IRISConnection:
    if connection is None:
        from .connection import IRISConnection as _Conn  # noqa: PLC0415
        return _Conn()
    return connection


def list_classes(
    pattern: str = "*",
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> list[str]:
    """Return IRIS class names matching *pattern*."""
    connection = _get_connection(connection)
    sql_pattern = pattern.replace("*", "%")
    rs = connection.sql_exec(
        "SELECT Name FROM %Dictionary.ClassDefinition WHERE Name LIKE ? ORDER BY Name",
        [sql_pattern],
    )
    return [str(row[0]) for row in rs]


def get_class_super(
    classname: str,
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> str:
    """Return the class' primary superclass."""
    connection = _get_connection(connection)
    rs = connection.sql_exec(
        "SELECT Super FROM %Dictionary.ClassDefinition WHERE Name = ?",
        [classname],
    )
    for row in rs:
        return str(row[0] or "%Persistent")
    return "%Persistent"


def get_class_properties(
    classname: str,
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> list[PropertyInfo]:
    """
    Query %Dictionary.PropertyDefinition to retrieve the public,
    non-relationship properties of an IRIS class.

    If *connection* is None an embedded :class:`IRISConnection` is used.
    """
    connection = _get_connection(connection)
    sql = (
        "SELECT Name, Type, Required, Collection, InitialExpression, Description "
        "FROM %Dictionary.PropertyDefinition "
        "WHERE parent = ? "
        "AND Relationship = 0 "
        "AND Private = 0 "
        "AND Internal = 0"
    )
    rs = connection.sql_exec(sql, [classname])
    props: list[PropertyInfo] = []
    for row in rs:
        name: str = row[0]
        iris_type: str = row[1] or "%String"
        required: bool = bool(row[2])
        collection: str = (row[3] or "").lower()
        default: str = row[4] or ""
        description: str = row[5] if len(row) > 5 else ""
        props.append(
            PropertyInfo(
                name=name,
                iris_type=iris_type,
                python_type=iris_type_to_python(iris_type),
                required=required,
                collection=collection,
                default=default,
                maxlen=_get_property_maxlen(classname, name, connection),
                description=description,
            )
        )
    return props


def _get_property_maxlen(
    classname: str,
    prop_name: str,
    connection: IRISConnection,
) -> int | None:
    """Return the MAXLEN parameter for a property if available."""
    try:
        prop_def = connection.iris_cls("%Dictionary.PropertyDefinition")._OpenId(
            f"{classname}||{prop_name}"
        )
    except Exception:
        return None
    try:
        value = prop_def.Parameters.GetAt("MAXLEN")
    except Exception:
        return None
    if value in (None, ""):
        return None
    if not isinstance(value, (int, str)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_class_relationships(
    classname: str,
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> list[RelationshipInfo]:
    """Return the public relationships defined on *classname*."""
    connection = _get_connection(connection)
    sql = (
        "SELECT Name, Type, Cardinality, Inverse, Description "
        "FROM %Dictionary.RelationshipDefinition "
        "WHERE parent = ? AND Private = 0 AND Internal = 0"
    )
    rs = connection.sql_exec(sql, [classname])
    rels: list[RelationshipInfo] = []
    for row in rs:
        rels.append(
            RelationshipInfo(
                name=str(row[0]),
                related_classname=str(row[1]),
                cardinality=_normalize_cardinality(str(row[2] or "")),
                inverse=str(row[3] or ""),
                description=str(row[4] or ""),
            )
        )
    return rels


def _normalize_cardinality(value: str) -> str:
    lowered = value.lower()
    if lowered == "child":
        return "children"
    if lowered in {"parent", "children", "one", "many"}:
        return lowered
    return lowered or "one"


def get_class_parameters(
    classname: str,
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> dict[str, str]:
    """Return class parameters as a mapping."""
    connection = _get_connection(connection)
    sql = (
        "SELECT Name, Default "
        "FROM %Dictionary.ParameterDefinition "
        "WHERE parent = ? ORDER BY Name"
    )
    rs = connection.sql_exec(sql, [classname])
    return {str(row[0]): str(row[1] or "") for row in rs}


def get_class_indexes(
    classname: str,
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> list[IndexInfo]:
    """Return indexes defined on *classname*."""
    connection = _get_connection(connection)
    sql = (
        "SELECT Name, Properties, Unique, PrimaryKey "
        "FROM %Dictionary.IndexDefinition "
        "WHERE parent = ? ORDER BY Name"
    )
    rs = connection.sql_exec(sql, [classname])
    indexes: list[IndexInfo] = []
    for row in rs:
        indexes.append(
            IndexInfo(
                name=str(row[0]),
                properties=str(row[1] or ""),
                unique=bool(row[2]),
                primary_key=bool(row[3]),
            )
        )
    return indexes


def get_storage_definition(
    classname: str,
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> str:
    """Best-effort retrieval of the class' storage definition text."""
    connection = _get_connection(connection)
    try:
        cls_def = connection.iris_cls("%Dictionary.ClassDefinition")._OpenId(classname)
    except Exception:
        return ""

    for attr in ("Storage", "StorageDefinition", "StorageXML"):
        value = getattr(cls_def, attr, "")
        if isinstance(value, str) and value.strip():
            return value
    return ""


def get_unsupported_features(
    classname: str,
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> list[UnsupportedFeatureInfo]:
    """Return unsupported feature markers for methods, triggers, projections."""
    connection = _get_connection(connection)
    checks = [
        ("%Dictionary.MethodDefinition", "method"),
        ("%Dictionary.TriggerDefinition", "trigger"),
        ("%Dictionary.ProjectionDefinition", "projection"),
    ]
    features: list[UnsupportedFeatureInfo] = []
    for table_name, kind in checks:
        rs = connection.sql_exec(
            f"SELECT Name FROM {table_name} WHERE parent = ? ORDER BY Name",
            [classname],
        )
        for row in rs:
            features.append(UnsupportedFeatureInfo(kind=kind, name=str(row[0])))
    return features


def get_class_details(
    classname: str,
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> ClassDetails:
    """Return scaffold-oriented class metadata for *classname*."""
    connection = _get_connection(connection)
    return ClassDetails(
        classname=classname,
        super=get_class_super(classname, connection),
        properties=get_class_properties(classname, connection),
        relationships=get_class_relationships(classname, connection),
        class_parameters=get_class_parameters(classname, connection),
        indexes=get_class_indexes(classname, connection),
        storage_definition=get_storage_definition(classname, connection),
        unsupported_features=get_unsupported_features(classname, connection),
    )
