"""
IRIS class introspection via %Dictionary.PropertyDefinition.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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


def get_class_properties(
    classname: str,
    connection: IRISConnection = None,  # type: ignore[assignment]
) -> list[PropertyInfo]:
    """
    Query %Dictionary.PropertyDefinition to retrieve the public,
    non-relationship properties of an IRIS class.

    If *connection* is None an embedded :class:`IRISConnection` is used.
    """
    if connection is None:
        from .connection import IRISConnection as _Conn  # noqa: PLC0415
        connection = _Conn()

    sql = (
        "SELECT Name, Type, Required, Collection, InitialExpression "
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
        props.append(
            PropertyInfo(
                name=name,
                iris_type=iris_type,
                python_type=iris_type_to_python(iris_type),
                required=required,
                collection=collection,
                default=default,
            )
        )
    return props
