"""
Migration operation dataclasses for iris_orm.

Each Operation has:
  apply(conn)  — forward migration step
  revert(conn) — rollback step

Operations use %Dictionary exclusively — no .cls files.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# MigrationConnection — thin wrapper so migration files use a clean API
# ---------------------------------------------------------------------------

class MigrationConnection:
    """
    Thin facade over IRISConnection exposed to upgrade()/downgrade() functions
    inside migration files.  Provides a stable, high-level API so migration
    files don't import iris_orm internals directly.
    """

    def __init__(self, iris_conn: Any) -> None:
        self._conn = iris_conn

    # -- Class-level ops --------------------------------------------------

    def create_class(self, classname: str, extends: str = "%Persistent") -> None:
        CreateClass(classname=classname, extends=extends).apply(self._conn)

    def drop_class(self, classname: str) -> None:
        DropClass(classname=classname).apply(self._conn)

    # -- Property ops -----------------------------------------------------

    def add_property(
        self,
        classname: str,
        name: str,
        iris_type: str = "%String",
        *,
        required: bool = False,
        maxlen: Optional[int] = None,
        collection: str = "",
        description: str = "",
    ) -> None:
        AddProperty(
            classname=classname,
            name=name,
            iris_type=iris_type,
            required=required,
            maxlen=maxlen,
            collection=collection,
            description=description,
        ).apply(self._conn)

    def alter_property(
        self,
        classname: str,
        name: str,
        new_type: str,
        *,
        required: Optional[bool] = None,
        maxlen: Optional[int] = None,
    ) -> None:
        AlterProperty(
            classname=classname,
            name=name,
            new_type=new_type,
            required=required,
            maxlen=maxlen,
        ).apply(self._conn)

    def drop_property(self, classname: str, name: str) -> None:
        DropProperty(classname=classname, name=name).apply(self._conn)

    # -- Relationship ops -------------------------------------------------

    def add_relationship(
        self,
        classname: str,
        name: str,
        related_classname: str,
        *,
        cardinality: str,
        inverse: str,
        description: str = "",
    ) -> None:
        AddRelationship(
            classname=classname,
            name=name,
            related_classname=related_classname,
            cardinality=cardinality,
            inverse=inverse,
            description=description,
        ).apply(self._conn)

    def drop_relationship(self, classname: str, name: str) -> None:
        DropRelationship(classname=classname, name=name).apply(self._conn)

    # -- Compile ----------------------------------------------------------

    def compile(self, classname: str, flags: str = "ck") -> None:
        """Recompile a class after a batch of operations."""
        try:
            self._conn.iris_cls("%SYSTEM.OBJ").Compile(classname, flags)
        except Exception as exc:
            import warnings
            warnings.warn(f"Recompile of {classname!r} failed: {exc}", stacklevel=2)


# ---------------------------------------------------------------------------
# Operation base
# ---------------------------------------------------------------------------

class Operation:
    """Abstract base for all migration operations."""

    def apply(self, conn: Any) -> None:
        raise NotImplementedError

    def revert(self, conn: Any) -> None:
        raise NotImplementedError

    def as_code(self) -> str:
        """Return the Python source line for upgrade()."""
        raise NotImplementedError

    def revert_code(self) -> str:
        """Return the Python source line for downgrade()."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Class-level operations
# ---------------------------------------------------------------------------

@dataclass
class CreateClass(Operation):
    classname: str
    extends: str = "%Persistent"

    def apply(self, conn: Any) -> None:
        from iris_orm.schema import _class_exists_in_iris  # noqa: PLC0415
        if _class_exists_in_iris(self.classname, conn):
            return
        cls_def = conn.iris_cls("%Dictionary.ClassDefinition")._New()
        cls_def.Name = self.classname
        cls_def.Super = self.extends
        cls_def._Save()

    def revert(self, conn: Any) -> None:
        DropClass(classname=self.classname).apply(conn)

    def as_code(self) -> str:
        return f'    conn.create_class({self.classname!r}, extends={self.extends!r})'

    def revert_code(self) -> str:
        return f'    conn.drop_class({self.classname!r})'


@dataclass
class DropClass(Operation):
    classname: str

    def apply(self, conn: Any) -> None:
        try:
            conn.iris_cls("%Dictionary.ClassDefinition")._DeleteId(self.classname)
        except Exception as exc:
            raise RuntimeError(f"Failed to drop class {self.classname!r}: {exc}") from exc

    def revert(self, conn: Any) -> None:
        # Cannot restore a dropped class automatically — user must add CreateClass back.
        raise NotImplementedError(
            f"Cannot auto-revert DropClass({self.classname!r}). "
            "Add a CreateClass + AddProperty sequence to downgrade() manually."
        )

    def as_code(self) -> str:
        return f'    conn.drop_class({self.classname!r})'

    def revert_code(self) -> str:
        return f'    # TODO: recreate {self.classname!r} manually if needed'


# ---------------------------------------------------------------------------
# Property operations
# ---------------------------------------------------------------------------

@dataclass
class AddProperty(Operation):
    classname: str
    name: str
    iris_type: str = "%String"
    required: bool = False
    maxlen: Optional[int] = None
    collection: str = ""
    description: str = ""

    def apply(self, conn: Any) -> None:
        prop_def_cls = conn.iris_cls("%Dictionary.PropertyDefinition")
        prop_id = f"{self.classname}||{self.name}"
        try:
            prop_def = prop_def_cls._OpenId(prop_id)
        except Exception:
            prop_def = prop_def_cls._New()
            prop_def.Name = self.name
            prop_def.parent = self.classname

        prop_def.Type = self.iris_type
        prop_def.Required = int(self.required)
        if self.collection:
            prop_def.Collection = self.collection.capitalize()
        if self.description:
            prop_def.Description = self.description
        if self.maxlen is not None:
            prop_def.Parameters.SetAt(str(self.maxlen), "MAXLEN")
        prop_def._Save()
        _recompile(conn, self.classname)

    def revert(self, conn: Any) -> None:
        DropProperty(classname=self.classname, name=self.name).apply(conn)

    def as_code(self) -> str:
        args = [repr(self.classname), repr(self.name), repr(self.iris_type)]
        if self.required:
            args.append(f"required={self.required!r}")
        if self.maxlen is not None:
            args.append(f"maxlen={self.maxlen!r}")
        if self.collection:
            args.append(f"collection={self.collection!r}")
        if self.description:
            args.append(f"description={self.description!r}")
        return f'    conn.add_property({", ".join(args)})'

    def revert_code(self) -> str:
        return f'    conn.drop_property({self.classname!r}, {self.name!r})'


@dataclass
class AlterProperty(Operation):
    classname: str
    name: str
    new_type: str
    old_type: str = ""        # recorded for downgrade
    required: Optional[bool] = None
    maxlen: Optional[int] = None

    def apply(self, conn: Any) -> None:
        prop_def_cls = conn.iris_cls("%Dictionary.PropertyDefinition")
        prop_id = f"{self.classname}||{self.name}"
        prop_def = prop_def_cls._OpenId(prop_id)
        prop_def.Type = self.new_type
        if self.required is not None:
            prop_def.Required = int(self.required)
        if self.maxlen is not None:
            prop_def.Parameters.SetAt(str(self.maxlen), "MAXLEN")
        prop_def._Save()
        _recompile(conn, self.classname)

    def revert(self, conn: Any) -> None:
        if not self.old_type:
            raise NotImplementedError(
                f"Cannot revert AlterProperty({self.name!r}): old_type not recorded."
            )
        AlterProperty(
            classname=self.classname,
            name=self.name,
            new_type=self.old_type,
            old_type=self.new_type,
        ).apply(conn)

    def as_code(self) -> str:
        args = [repr(self.classname), repr(self.name), repr(self.new_type)]
        if self.required is not None:
            args.append(f"required={self.required!r}")
        if self.maxlen is not None:
            args.append(f"maxlen={self.maxlen!r}")
        return f'    conn.alter_property({", ".join(args)})'

    def revert_code(self) -> str:
        if self.old_type:
            return f'    conn.alter_property({self.classname!r}, {self.name!r}, {self.old_type!r})'
        return f'    # TODO: revert AlterProperty {self.name!r} manually'


@dataclass
class DropProperty(Operation):
    classname: str
    name: str

    def apply(self, conn: Any) -> None:
        prop_id = f"{self.classname}||{self.name}"
        try:
            conn.iris_cls("%Dictionary.PropertyDefinition")._DeleteId(prop_id)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to drop property {self.name!r} from {self.classname!r}: {exc}"
            ) from exc
        _recompile(conn, self.classname)

    def revert(self, conn: Any) -> None:
        raise NotImplementedError(
            f"Cannot auto-revert DropProperty({self.name!r}). "
            "Add an AddProperty call to downgrade() manually."
        )

    def as_code(self) -> str:
        return f'    conn.drop_property({self.classname!r}, {self.name!r})'

    def revert_code(self) -> str:
        return f'    # TODO: recreate property {self.name!r} in {self.classname!r} manually'


# ---------------------------------------------------------------------------
# Relationship operations
# ---------------------------------------------------------------------------

_CARD_MAP: dict[str, str] = {
    "children": "many",
    "parent": "one",
    "one": "one",
    "many": "many",
}


@dataclass
class AddRelationship(Operation):
    classname: str
    name: str
    related_classname: str
    cardinality: str
    inverse: str
    description: str = ""

    def apply(self, conn: Any) -> None:
        rel_def_cls = conn.iris_cls("%Dictionary.RelationshipDefinition")
        rel_id = f"{self.classname}||{self.name}"
        try:
            rel_iris = rel_def_cls._OpenId(rel_id)
        except Exception:
            rel_iris = rel_def_cls._New()
            rel_iris.Name = self.name
            rel_iris.parent = self.classname

        rel_iris.Type = self.related_classname
        rel_iris.Cardinality = _CARD_MAP.get(self.cardinality, self.cardinality)
        rel_iris.Inverse = self.inverse
        if self.description:
            rel_iris.Description = self.description
        rel_iris._Save()
        _recompile(conn, self.classname)

    def revert(self, conn: Any) -> None:
        DropRelationship(classname=self.classname, name=self.name).apply(conn)

    def as_code(self) -> str:
        args = [
            repr(self.classname), repr(self.name), repr(self.related_classname),
            f"cardinality={self.cardinality!r}", f"inverse={self.inverse!r}",
        ]
        if self.description:
            args.append(f"description={self.description!r}")
        return f'    conn.add_relationship({", ".join(args)})'

    def revert_code(self) -> str:
        return f'    conn.drop_relationship({self.classname!r}, {self.name!r})'


@dataclass
class DropRelationship(Operation):
    classname: str
    name: str

    def apply(self, conn: Any) -> None:
        rel_id = f"{self.classname}||{self.name}"
        try:
            conn.iris_cls("%Dictionary.RelationshipDefinition")._DeleteId(rel_id)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to drop relationship {self.name!r} from {self.classname!r}: {exc}"
            ) from exc
        _recompile(conn, self.classname)

    def revert(self, conn: Any) -> None:
        raise NotImplementedError(
            f"Cannot auto-revert DropRelationship({self.name!r}). "
            "Add an AddRelationship call to downgrade() manually."
        )

    def as_code(self) -> str:
        return f'    conn.drop_relationship({self.classname!r}, {self.name!r})'

    def revert_code(self) -> str:
        return f'    # TODO: recreate relationship {self.name!r} in {self.classname!r} manually'


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _recompile(conn: Any, classname: str) -> None:
    import warnings  # noqa: PLC0415
    try:
        conn.iris_cls("%SYSTEM.OBJ").Compile(classname, "ck")
    except Exception as exc:
        warnings.warn(f"Recompile of {classname!r} failed: {exc}", stacklevel=3)
