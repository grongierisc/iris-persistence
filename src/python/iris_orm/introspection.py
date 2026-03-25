"""
Introspects an IRIS class via %Dictionary.PropertyDefinition.

Each PropertyInfo describes one persistent property as seen by the ORM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .types import iris_type_to_python

if TYPE_CHECKING:
    import iris  # type: ignore[import]


@dataclass(frozen=True)
class PropertyInfo:
    """Metadata for a single IRIS class property."""

    name: str
    iris_type: str
    python_type: type
    required: bool
    collection: str  # "" | "list" | "array"
    default: str     # raw IRIS default expression (may be empty)


def get_class_properties(classname: str) -> list[PropertyInfo]:
    """Query ``%Dictionary.PropertyDefinition`` and return a list of
    :class:`PropertyInfo` for every non-system property of *classname*.

    Requires a live IRIS connection (``import iris``).
    """
    import iris  # type: ignore[import]

    sql = (
        "SELECT Name, Type, Required, Collection, InitialExpression "
        "FROM %Dictionary.PropertyDefinition "
        "WHERE parent = ? "
        "AND Relationship = 0 "
        "AND Private = 0 "
        "AND Internal = 0"
    )
    rs = iris.sql.exec(sql, [classname])

    properties: list[PropertyInfo] = []
    for row in rs:
        name: str = row[0]
        iris_type: str = row[1] or "%String"
        required: bool = bool(row[2])
        collection: str = (row[3] or "").lower()
        default: str = row[4] or ""

        properties.append(
            PropertyInfo(
                name=name,
                iris_type=iris_type,
                python_type=iris_type_to_python(iris_type),
                required=required,
                collection=collection,
                default=default,
            )
        )

    return properties
