"""
IRIS class introspection helpers backed by %Dictionary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape

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
    storage: dict[str, Any] | None = None


def _get_connection(connection: IRISConnection | None) -> IRISConnection:
    if connection is None:
        from .connection import IRISConnection as _Conn  # noqa: PLC0415
        return _Conn()
    return connection


def _safe_sql_exec(
    connection: IRISConnection,
    sql: str,
    params: list[Any] | None = None,
) -> Any:
    """Best-effort SQL execution for optional %Dictionary metadata queries."""
    try:
        return connection.sql_exec(sql, params)
    except Exception:
        return []


def _iter_dictionary_collection(collection: Any) -> list[Any]:
    """Return items from an IRIS dictionary collection."""
    try:
        raw_count = collection.Count()
    except Exception:
        return []
    if not isinstance(raw_count, (int, str)):
        return []
    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        return []
    items: list[Any] = []
    for index in range(1, count + 1):
        try:
            items.append(collection.GetAt(index))
        except Exception:
            continue
    return items


def _get_class_definition(classname: str, connection: IRISConnection) -> Any | None:
    """Return a live %Dictionary.ClassDefinition object when available."""
    try:
        cls_def = connection.iris_cls("%Dictionary.ClassDefinition")._OpenId(classname)
    except Exception:
        return None
    return cls_def if hasattr(cls_def, "_Save") else None


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
    try:
        rs = connection.sql_exec(
            "SELECT Super FROM %Dictionary.ClassDefinition WHERE Name = ?",
            [classname],
        )
    except Exception:
        rs = []
    for row in rs:
        return str(row[0] or "%Persistent")
    try:
        cls_def = connection.iris_cls("%Dictionary.ClassDefinition")._OpenId(classname)
        value = getattr(cls_def, "Super", "")
        if isinstance(value, (str, int)) and value:
            return str(value)
    except Exception:
        pass
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
    try:
        rs = connection.sql_exec(sql, [classname])
    except Exception:
        rs = None
    props: list[PropertyInfo] = []
    if rs is not None:
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
        if props:
            return props

    cls_def = _get_class_definition(classname, connection)
    collection = getattr(cls_def, "Properties", None) if cls_def is not None else None
    if collection is None:
        return props

    for prop_def in _iter_dictionary_collection(collection):
        if bool(getattr(prop_def, "Relationship", False)):
            continue
        if bool(getattr(prop_def, "Private", False)):
            continue
        if bool(getattr(prop_def, "Internal", False)):
            continue
        name = str(getattr(prop_def, "Name", "") or "")
        if not name:
            continue
        iris_type = str(getattr(prop_def, "Type", "") or "%String")
        collection_name = str(getattr(prop_def, "Collection", "") or "").lower()
        props.append(
            PropertyInfo(
                name=name,
                iris_type=iris_type,
                python_type=iris_type_to_python(iris_type),
                required=bool(getattr(prop_def, "Required", False)),
                collection=collection_name,
                default=str(getattr(prop_def, "InitialExpression", "") or ""),
                maxlen=_maxlen_from_property_definition(prop_def),
                description=str(getattr(prop_def, "Description", "") or ""),
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
    return _maxlen_from_property_definition(prop_def)


def _maxlen_from_property_definition(prop_def: Any) -> int | None:
    """Return the MAXLEN parameter for a property definition object."""
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
    rs = _safe_sql_exec(connection, sql, [classname])
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
    if rels:
        return rels

    cls_def = _get_class_definition(classname, connection)
    collection = getattr(cls_def, "Properties", None) if cls_def is not None else None
    if collection is None:
        return rels
    for prop_def in _iter_dictionary_collection(collection):
        if not bool(getattr(prop_def, "Relationship", False)):
            continue
        if bool(getattr(prop_def, "Private", False)):
            continue
        if bool(getattr(prop_def, "Internal", False)):
            continue
        name = str(getattr(prop_def, "Name", "") or "")
        if not name:
            continue
        rels.append(
            RelationshipInfo(
                name=name,
                related_classname=str(getattr(prop_def, "Type", "") or ""),
                cardinality=_normalize_cardinality(
                    str(getattr(prop_def, "Cardinality", "") or "")
                ),
                inverse=str(getattr(prop_def, "Inverse", "") or ""),
                description=str(getattr(prop_def, "Description", "") or ""),
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
    rs = _safe_sql_exec(connection, sql, [classname])
    params = {str(row[0]): str(row[1] or "") for row in rs}
    if params:
        return params

    cls_def = _get_class_definition(classname, connection)
    collection = getattr(cls_def, "Parameters", None) if cls_def is not None else None
    if collection is None:
        return params
    for param_def in _iter_dictionary_collection(collection):
        name = str(getattr(param_def, "Name", "") or "")
        if not name:
            continue
        params[name] = str(getattr(param_def, "Default", "") or "")
    return params


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
    rs = _safe_sql_exec(connection, sql, [classname])
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
    if indexes:
        return indexes

    cls_def = _get_class_definition(classname, connection)
    collection = getattr(cls_def, "Indices", None) if cls_def is not None else None
    if collection is None:
        return indexes
    for index_def in _iter_dictionary_collection(collection):
        name = str(getattr(index_def, "Name", "") or "")
        if not name:
            continue
        indexes.append(
            IndexInfo(
                name=name,
                properties=str(getattr(index_def, "Properties", "") or ""),
                unique=bool(getattr(index_def, "Unique", False)),
                primary_key=bool(getattr(index_def, "PrimaryKey", False)),
            )
        )
    return indexes


def _extract_storage_object(storage_def: Any) -> dict[str, Any]:
    """Return canonical structured storage metadata from a storage definition object."""
    payload: dict[str, Any] = {
        "name": str(getattr(storage_def, "Name", "") or "Default"),
        "type": str(getattr(storage_def, "Type", "") or ""),
        "data_location": str(getattr(storage_def, "DataLocation", "") or ""),
        "default_data": str(getattr(storage_def, "DefaultData", "") or ""),
        "extent_location": str(getattr(storage_def, "ExtentLocation", "") or ""),
        "id_location": str(getattr(storage_def, "IdLocation", "") or ""),
        "index_location": str(getattr(storage_def, "IndexLocation", "") or ""),
        "stream_location": str(getattr(storage_def, "StreamLocation", "") or ""),
        "id_function": str(getattr(storage_def, "IdFunction", "") or ""),
        "data": [],
    }
    data_items: list[dict[str, Any]] = []
    for data_def in _iter_dictionary_collection(getattr(storage_def, "Data", None)):
        values: list[dict[str, str]] = []
        for value_def in _iter_dictionary_collection(getattr(data_def, "Values", None)):
            values.append(
                {
                    "name": str(getattr(value_def, "Name", "") or ""),
                    "value": str(getattr(value_def, "Value", "") or ""),
                }
            )
        data_items.append(
            {
                "name": str(getattr(data_def, "Name", "") or ""),
                "structure": str(getattr(data_def, "Structure", "") or ""),
                "subscript": str(getattr(data_def, "Subscript", "") or ""),
                "values": values,
            }
        )
    payload["data"] = data_items
    return payload


def render_storage_definition(storage: dict[str, Any] | None) -> str:
    """Render a storage block from canonical structured storage metadata."""
    if not storage:
        return ""
    name = str(storage.get("name", "") or "Default")
    lines = [f"Storage {name}", "{"]
    scalar_attrs = [
        ("type", "Type"),
        ("data_location", "DataLocation"),
        ("default_data", "DefaultData"),
        ("extent_location", "ExtentLocation"),
        ("id_location", "IdLocation"),
        ("index_location", "IndexLocation"),
        ("stream_location", "StreamLocation"),
        ("id_function", "IdFunction"),
    ]
    for key, tag in scalar_attrs:
        value = str(storage.get(key, "") or "")
        if value:
            lines.append(f"<{tag}>{escape(value)}</{tag}>")

    for data_def in list(storage.get("data", [])):
        data_name = str(data_def.get("name", "") or "")
        lines.append(
            f'<Data name="{escape(data_name)}">' if data_name else "<Data>"
        )
        structure = str(data_def.get("structure", "") or "")
        if structure:
            lines.append(f"<Structure>{escape(structure)}</Structure>")
        subscript = str(data_def.get("subscript", "") or "")
        if subscript:
            lines.append(f"<Subscript>{escape(subscript)}</Subscript>")
        for value_def in list(data_def.get("values", [])):
            value_name = str(value_def.get("name", "") or "")
            value_text = str(value_def.get("value", "") or "")
            if value_name:
                lines.append(
                    f'<Value name="{escape(value_name)}">{escape(value_text)}</Value>'
                )
            else:
                lines.append(f"<Value>{escape(value_text)}</Value>")
        lines.append("</Data>")

    lines.append("}")
    return "\n".join(lines)


def parse_storage_definition(storage_definition: str) -> dict[str, Any] | None:
    """Parse a storage block string into canonical structured storage metadata."""
    source = str(storage_definition or "").strip()
    if not source:
        return None
    match = re.match(r"Storage\s+([A-Za-z0-9_]+)\s*\{(.*)\}\s*$", source, re.DOTALL)
    if match is None:
        return None
    payload: dict[str, Any] = {
        "name": match.group(1),
        "type": "",
        "data_location": "",
        "default_data": "",
        "extent_location": "",
        "id_location": "",
        "index_location": "",
        "stream_location": "",
        "id_function": "",
        "data": [],
    }
    body = match.group(2)
    scalar_attrs = [
        ("Type", "type"),
        ("DataLocation", "data_location"),
        ("DefaultData", "default_data"),
        ("ExtentLocation", "extent_location"),
        ("IdLocation", "id_location"),
        ("IndexLocation", "index_location"),
        ("StreamLocation", "stream_location"),
        ("IdFunction", "id_function"),
    ]
    for tag, key in scalar_attrs:
        value_match = re.search(fr"<{tag}>(.*?)</{tag}>", body, re.DOTALL)
        if value_match is not None:
            payload[key] = unescape(value_match.group(1).strip())

    data_items: list[dict[str, Any]] = []
    data_pattern = re.compile(
        r"<Data(?:\s+name=\"([^\"]*)\")?\s*(?:/>\s*|>(.*?)</Data>)",
        re.DOTALL,
    )
    for data_match in data_pattern.finditer(body):
        data_name = unescape((data_match.group(1) or "").strip())
        data_body = data_match.group(2) or ""
        data_item: dict[str, Any] = {
            "name": data_name,
            "structure": "",
            "subscript": "",
            "values": [],
        }
        if data_body:
            structure_match = re.search(r"<Structure>(.*?)</Structure>", data_body, re.DOTALL)
            if structure_match is not None:
                data_item["structure"] = unescape(structure_match.group(1).strip())
            subscript_match = re.search(r"<Subscript>(.*?)</Subscript>", data_body, re.DOTALL)
            if subscript_match is not None:
                data_item["subscript"] = unescape(subscript_match.group(1).strip())
            values: list[dict[str, str]] = []
            value_pattern = re.compile(r"<Value(?:\s+name=\"([^\"]*)\")?\s*>(.*?)</Value>", re.DOTALL)
            for value_match in value_pattern.finditer(data_body):
                values.append(
                    {
                        "name": unescape((value_match.group(1) or "").strip()),
                        "value": unescape((value_match.group(2) or "").strip()),
                    }
                )
            data_item["values"] = values
        data_items.append(data_item)
    payload["data"] = data_items
    return payload


def get_storage_object(
    classname: str,
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> dict[str, Any] | None:
    """Best-effort retrieval of the class' canonical structured storage metadata."""
    connection = _get_connection(connection)
    cls_def = _get_class_definition(classname, connection)
    if cls_def is None:
        return None
    storages = getattr(cls_def, "Storages", None)
    storage_items = _iter_dictionary_collection(storages) if storages is not None else []
    if not storage_items:
        return None
    return _extract_storage_object(storage_items[0])


def get_storage_definition(
    classname: str,
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> str:
    """Best-effort retrieval of the class' storage definition text."""
    connection = _get_connection(connection)
    cls_def = _get_class_definition(classname, connection)
    if cls_def is None:
        return ""

    for attr in ("Storage", "StorageDefinition", "StorageXML"):
        value = getattr(cls_def, attr, "")
        if isinstance(value, str) and value.strip():
            return value
    return render_storage_definition(get_storage_object(classname, connection))


def get_unsupported_features(
    classname: str,
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> list[UnsupportedFeatureInfo]:
    """Return unsupported feature markers for methods, triggers, projections."""
    connection = _get_connection(connection)
    checks = [
        ("%Dictionary.MethodDefinition", "method", "Methods"),
        ("%Dictionary.TriggerDefinition", "trigger", "Triggers"),
        ("%Dictionary.ProjectionDefinition", "projection", "Projections"),
    ]
    features: list[UnsupportedFeatureInfo] = []
    for table_name, kind, collection_name in checks:
        found = False
        rs = _safe_sql_exec(
            connection,
            f"SELECT Name FROM {table_name} WHERE parent = ? ORDER BY Name",
            [classname],
        )
        for row in rs:
            found = True
            features.append(UnsupportedFeatureInfo(kind=kind, name=str(row[0])))
        if found:
            continue
        cls_def = _get_class_definition(classname, connection)
        collection = getattr(cls_def, collection_name, None) if cls_def is not None else None
        if collection is None:
            continue
        for item in _iter_dictionary_collection(collection):
            name = str(getattr(item, "Name", "") or "")
            if not name:
                continue
            features.append(UnsupportedFeatureInfo(kind=kind, name=name))
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
        storage=get_storage_object(classname, connection),
    )
