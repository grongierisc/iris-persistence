"""
Field and relationship definition helpers for declared model classes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

_SENTINEL = object()


@dataclass
class FieldDefinition:
    required: bool = False
    default: Any = None
    maxlen: Optional[int] = None
    collection: str = ""        # "" | "list" | "array"
    iris_type: Optional[str] = None
    description: str = ""
    # Set by metaclass after inspection:
    prop_name: str = ""
    python_type: type = None  # type: ignore[assignment]


@dataclass
class RelationshipDefinition:
    related_classname: str
    inverse: str
    cardinality: str   # "parent" | "children" | "one" | "many"
    on_delete: str = "cascade"
    description: str = ""
    # Set by metaclass after inspection:
    prop_name: str = ""


def field(
    *,
    required: bool = False,
    default: Any = _SENTINEL,
    maxlen: Optional[int] = None,
    collection: str = "",
    iris_type: Optional[str] = None,
    description: str = "",
) -> Any:
    """Declare a typed IRIS property with optional metadata."""
    return FieldDefinition(
        required=required,
        default=None if default is _SENTINEL else default,
        maxlen=maxlen,
        collection=collection,
        iris_type=iris_type,
        description=description,
    )


def relationship(
    related_classname: str,
    *,
    inverse: str,
    cardinality: str,
    on_delete: str = "cascade",
    description: str = "",
) -> Any:
    """Declare an IRIS Relationship property."""
    if cardinality not in ("parent", "children", "one", "many"):
        raise ValueError(
            f"cardinality must be parent/children/one/many, got {cardinality!r}"
        )
    return RelationshipDefinition(
        related_classname=related_classname,
        inverse=inverse,
        cardinality=cardinality,
        on_delete=on_delete,
        description=description,
    )
