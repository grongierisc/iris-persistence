"""
Autogenerate migration operations by diffing Python models against
the state snapshot recorded in the last applied migration file.

Only safe (non-destructive) operations are generated automatically:
  - CreateClass
  - AddProperty
  - AlterProperty  (type change)
  - AddRelationship

Destructive operations (DropClass, DropProperty, DropRelationship) are
NEVER auto-generated.  The user must add them manually to a migration
file when intentional.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .migration import (
    AddProperty,
    AddRelationship,
    AlterProperty,
    CreateClass,
    Operation,
)

if TYPE_CHECKING:
    from iris_orm.connection import IRISConnection


def diff_models(
    models: list[type],
    applied_state: dict[str, dict],
    conn: "IRISConnection",
) -> list[Operation]:
    """
    Compare *models* (Python-first IRISModel subclasses) against
    *applied_state* (the property/relationship snapshot from the last
    applied migration) and return the list of Operations needed to
    bring IRIS up to date.

    Parameters
    ----------
    models:
        List of IRISModel (Plan C) class objects to inspect.
    applied_state:
        ``{ classname: { "properties": {name: iris_type}, "relationships": {name: {...}} } }``
        Built by :func:`load_state_from_migrations`.
    conn:
        Live IRISConnection used to check whether the IRIS class already exists.

    Returns
    -------
    list[Operation]
        Ordered list of non-destructive operations.
    """
    from iris_orm.schema import _class_exists_in_iris  # noqa: PLC0415

    ops: list[Operation] = []

    for model in models:
        if not getattr(model, "_iris_python_first", False):
            continue

        classname: str = model._iris_classname
        is_serial: bool = getattr(model, "_iris_serial", False)
        state = applied_state.get(classname, {})
        known_props: dict[str, str] = state.get("properties", {})
        known_rels: dict[str, dict] = state.get("relationships", {})

        # 1. Create class if unknown to migrations AND not yet in IRIS.
        if classname not in applied_state and not _class_exists_in_iris(classname, conn):
            extends = "%SerialObject" if is_serial else "%Persistent"
            ops.append(CreateClass(classname=classname, extends=extends))

        # 2. Properties
        field_defs = getattr(model, "_iris_field_defs", {})
        for prop in getattr(model, "_iris_properties", []):
            fd = field_defs.get(prop.name)
            iris_type = prop.iris_type or "%String"

            if prop.name not in known_props:
                ops.append(
                    AddProperty(
                        classname=classname,
                        name=prop.name,
                        iris_type=iris_type,
                        required=fd.required if fd else False,
                        maxlen=fd.maxlen if fd else None,
                        collection=fd.collection if fd else "",
                        description=fd.description if fd else "",
                    )
                )
            elif known_props[prop.name] != iris_type:
                ops.append(
                    AlterProperty(
                        classname=classname,
                        name=prop.name,
                        new_type=iris_type,
                        old_type=known_props[prop.name],
                    )
                )

        # 3. Relationships (skip for serial objects)
        if not is_serial:
            rel_defs = getattr(model, "_iris_rel_defs", {})
            for rel_name, rd in rel_defs.items():
                if rel_name not in known_rels:
                    ops.append(
                        AddRelationship(
                            classname=classname,
                            name=rel_name,
                            related_classname=rd.related_classname,
                            cardinality=rd.cardinality,
                            inverse=rd.inverse,
                            description=rd.description,
                        )
                    )

    return ops


def load_state_from_migrations(migration_files: list[Any]) -> dict[str, dict]:
    """
    Replay all migration modules (in order) to build the cumulative state
    snapshot: ``{ classname: { "properties": {name: type}, "relationships": {name: {...}} } }``.

    This is a pure-Python replay — no IRIS connection needed.
    """
    state: dict[str, dict] = {}
    recorder = _StateRecorder(state)

    for mf in migration_files:
        upgrade_fn = getattr(mf.module, "upgrade", None)
        if upgrade_fn is not None:
            upgrade_fn(recorder)

    return state


class _StateRecorder:
    """
    Drop-in replacement for MigrationConnection used during state replay.
    Records property/relationship additions without hitting IRIS.
    """

    def __init__(self, state: dict[str, dict]) -> None:
        self._state = state

    def _ensure(self, classname: str) -> None:
        self._state.setdefault(classname, {"properties": {}, "relationships": {}})

    def create_class(self, classname: str, extends: str = "%Persistent") -> None:
        self._ensure(classname)

    def drop_class(self, classname: str) -> None:
        self._state.pop(classname, None)

    def add_property(
        self,
        classname: str,
        name: str,
        iris_type: str = "%String",
        **kwargs: Any,
    ) -> None:
        self._ensure(classname)
        self._state[classname]["properties"][name] = iris_type

    def alter_property(
        self,
        classname: str,
        name: str,
        new_type: str,
        **kwargs: Any,
    ) -> None:
        self._ensure(classname)
        self._state[classname]["properties"][name] = new_type

    def drop_property(self, classname: str, name: str) -> None:
        self._ensure(classname)
        self._state[classname]["properties"].pop(name, None)

    def add_relationship(
        self,
        classname: str,
        name: str,
        related_classname: str,
        *,
        cardinality: str,
        inverse: str,
        **kwargs: Any,
    ) -> None:
        self._ensure(classname)
        self._state[classname]["relationships"][name] = {
            "related": related_classname,
            "cardinality": cardinality,
            "inverse": inverse,
        }

    def drop_relationship(self, classname: str, name: str) -> None:
        self._ensure(classname)
        self._state[classname]["relationships"].pop(name, None)

    def compile(self, classname: str, flags: str = "ck") -> None:
        pass  # no-op during state replay
