"""
Git-style schema sync for declared IRIS ORM models.

API
---
Post.schema.status()           → 3-way diff (snapshot ↔ Python, snapshot ↔ IRIS)
Post.schema.fetch()            → read IRIS schema into cache, no changes applied
Post.schema.pull()             → fetch + apply IRIS additions to Python snapshot; ConflictError on conflicts
Post.schema.push()             → apply Python additions/changes to IRIS via %Dictionary; ConflictError on conflicts
Post.schema.commit()           → snapshot current Python definition as new baseline
Post.schema.ensure_iris_class() → create or update the IRIS class using %Dictionary (no .cls files)
Post.schema.delete_property(name) → permanently delete a property from IRIS via %Dictionary

Schema operations use %Dictionary exclusively — no .cls file generation or compilation is required.

"""
from __future__ import annotations

import re
import warnings
import inspect
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Optional

from .errors import LockfileDriftError, StorageConflictError
from .introspection import get_class_details
from .lockfile import (
    IRISLockfile,
    compute_hash,
    load_lockfile,
    lockfile_path_for_module,
    timestamp_utc,
    write_lockfile,
)

# Cardinality mapping from Python strings → ObjectScript keywords
_CARD_MAP: dict[str, str] = {
    "children": "many",
    "parent": "one",
    "one": "one",
    "many": "many",
}

_STORAGE_RE = re.compile(r"(Storage\s+\w+\s*\{.*?\}\s*\n?)", re.DOTALL)


# ---------------------------------------------------------------------------
# %Dictionary helpers
# ---------------------------------------------------------------------------

def _class_exists_in_iris(classname: str, conn: Any) -> bool:
    """Return True if the IRIS class already exists in %Dictionary."""
    try:
        rs = conn.sql_exec(
            "SELECT Name FROM %Dictionary.ClassDefinition WHERE Name = ?",
            [classname],
        )
    except Exception:
        rs = []
    for _ in rs:
        return True
    try:
        exists = conn.iris_cls("%Dictionary.ClassDefinition")._ExistsId(classname)
    except Exception:
        exists = 0
    return bool(exists)


def _looks_like_iris_object(value: Any) -> bool:
    """Return True when *value* behaves like an embedded IRIS object proxy."""
    return value is not None and hasattr(value, "_Save")


def _status_is_success(status: Any) -> bool:
    """Return True when an IRIS %Status value represents success."""
    return status in (None, 1, True) or str(status).strip() == "1"


def _save_dictionary_item(item: Any, *, kind: str, identifier: str) -> None:
    """Persist a %Dictionary object and raise on error statuses."""
    try:
        status = item._Save()
    except Exception as exc:
        raise RuntimeError(f"Failed to save {kind} {identifier!r}: {exc}") from exc
    if not _status_is_success(status):
        raise RuntimeError(f"Failed to save {kind} {identifier!r}: {status}")


def _open_or_new_dictionary_item(
    definition_cls: Any,
    item_id: str,
    *,
    name: str,
    parent: Any,
) -> Any:
    """Open a %Dictionary definition item or create a new one if unavailable."""
    try:
        item = definition_cls._OpenId(item_id)
    except Exception:
        item = None
    if not _looks_like_iris_object(item):
        item = definition_cls._New()
        item.Name = name
        item.parent = parent
    return item


def _upsert_property_via_dict(
    classname: str,
    class_def: Any,
    prop: Any,
    field_def: Any | None,
    conn: Any,
) -> None:
    """Create or update a single property in IRIS using %Dictionary.PropertyDefinition."""
    prop_def_cls = conn.iris_cls("%Dictionary.PropertyDefinition")
    prop_id = f"{classname}||{prop.name}"
    prop_def = _open_or_new_dictionary_item(
        prop_def_cls,
        prop_id,
        name=prop.name,
        parent=class_def,
    )

    prop_def.Type = prop.iris_type or "%String"
    if field_def is not None:
        prop_def.Required = int(field_def.required)
        if field_def.collection:
            prop_def.Collection = field_def.collection.capitalize()
        if field_def.description:
            prop_def.Description = field_def.description
        if field_def.maxlen is not None:
            prop_def.Parameters.SetAt(str(field_def.maxlen), "MAXLEN")
    _save_dictionary_item(prop_def, kind="property", identifier=prop_id)


def _upsert_relationship_via_dict(
    classname: str,
    class_def: Any,
    rel_name: str,
    rel_def: Any,
    conn: Any,
) -> None:
    """Create or update a single relationship in IRIS using %Dictionary.RelationshipDefinition."""
    rel_def_cls = conn.iris_cls("%Dictionary.RelationshipDefinition")
    rel_id = f"{classname}||{rel_name}"
    rel_iris = _open_or_new_dictionary_item(
        rel_def_cls,
        rel_id,
        name=rel_name,
        parent=class_def,
    )

    rel_iris.Type = rel_def.related_classname
    rel_iris.Cardinality = _CARD_MAP.get(rel_def.cardinality, rel_def.cardinality)
    rel_iris.Inverse = rel_def.inverse
    if rel_def.description:
        rel_iris.Description = rel_def.description
    _save_dictionary_item(rel_iris, kind="relationship", identifier=rel_id)


# ---------------------------------------------------------------------------
# Conflict types
# ---------------------------------------------------------------------------

@dataclass
class PropertyConflict:
    name: str
    snapshot_type: str   # type at last commit
    python_type: str     # current Python type
    iris_type: str       # current IRIS type


class ConflictError(Exception):
    def __init__(self, conflicts: list[PropertyConflict]) -> None:
        self.conflicts = conflicts
        super().__init__(
            f"{len(conflicts)} conflict(s): " + ", ".join(c.name for c in conflicts)
        )


def _load_model_lockfile(model_class: type) -> Any | None:
    """Load a scaffold lockfile for *model_class* if configured."""
    lockfile_path = getattr(model_class, "_iris_lockfile_path", "")
    path, explicit = _resolve_model_lockfile_path(model_class, lockfile_path)
    if path is None:
        return None
    if not path.exists():
        if explicit:
            raise LockfileDriftError(f"Missing scaffold lockfile: {path}")
        return None
    return load_lockfile(path)


def _resolve_lockfile_path(model_class: type, lockfile_path: str | Path) -> Path:
    """Resolve a model lockfile path relative to the model's module when needed."""
    path = Path(lockfile_path)
    if path.is_absolute():
        return path
    try:
        module_file = Path(inspect.getfile(model_class)).resolve()
    except (TypeError, OSError):
        return path
    return (module_file.parent / path).resolve()


def _resolve_model_module_path(model_class: type) -> Path | None:
    try:
        module_file = Path(inspect.getfile(model_class)).resolve()
    except (TypeError, OSError):
        return None
    return module_file


def _resolve_model_lockfile_path(
    model_class: type,
    lockfile_path: str | Path = "",
) -> tuple[Path | None, bool]:
    explicit = bool(str(lockfile_path or "").strip())
    if explicit:
        return (_resolve_lockfile_path(model_class, lockfile_path), True)
    module_file = _resolve_model_module_path(model_class)
    if module_file is None:
        return (None, False)
    return (lockfile_path_for_module(module_file), False)


def _ensure_model_lockfile_reference(model_class: type) -> Path:
    path, _explicit = _resolve_model_lockfile_path(
        model_class,
        getattr(model_class, "_iris_lockfile_path", ""),
    )
    if path is None:
        classname = str(getattr(model_class, "_iris_classname", model_class.__name__))
        fallback = Path.cwd() / f"{classname.split('.')[-1].lower()}.iris.lock.json"
        model_class._iris_lockfile_path = str(fallback)  # type: ignore[attr-defined]
        return fallback
    if not getattr(model_class, "_iris_lockfile_path", ""):
        module_file = _resolve_model_module_path(model_class)
        if module_file is not None and path.parent == module_file.parent:
            model_class._iris_lockfile_path = path.name  # type: ignore[attr-defined]
        else:
            model_class._iris_lockfile_path = str(path)  # type: ignore[attr-defined]
    return path


def _build_lockfile_for_model(
    model_class: type,
    *,
    details: Any,
    generated_region_hash: str = "",
) -> IRISLockfile:
    module_file = _resolve_model_module_path(model_class)
    storage = getattr(details, "storage", None)
    storage_definition = details.storage_definition or ""
    return IRISLockfile(
        classname=details.classname,
        super=details.super,
        storage_mode=_get_storage_mode(model_class) or "preserve",
        storage_hash=compute_hash(storage if storage is not None else storage_definition),
        class_parameters=dict(details.class_parameters),
        indexes=[
            {
                "name": idx.name,
                "properties": idx.properties,
                "unique": idx.unique,
                "primary_key": idx.primary_key,
            }
            for idx in list(details.indexes)
        ],
        source={"kind": "declared", "origin": str(module_file) if module_file is not None else model_class.__name__},
        scaffold_style="typed",
        generated_at=timestamp_utc(),
        generated_region_hash=generated_region_hash,
        unsupported_features=[
            {"kind": item.kind, "name": item.name}
            for item in list(getattr(details, "unsupported_features", []))
        ],
        storage_definition=storage_definition,
        storage=storage,
    )


def _write_model_lockfile(model_class: type, *, conn: Any, generated_region_hash: str = "") -> Path:
    details = get_class_details(model_class._iris_classname, conn)  # type: ignore[attr-defined]
    lockfile = _build_lockfile_for_model(
        model_class,
        details=details,
        generated_region_hash=generated_region_hash,
    )
    return write_lockfile(_ensure_model_lockfile_reference(model_class), lockfile)


def _normalized_index_payload(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "name": str(item.get("name", "")),
                "properties": str(item.get("properties", "")),
                "unique": bool(item.get("unique")),
                "primary_key": bool(item.get("primary_key")),
            }
            for item in items
        ],
        key=lambda item: item["name"],
    )


def _get_storage_mode(model_class: type, lockfile: Any | None = None) -> str:
    mode = getattr(model_class, "_iris_storage_mode", "")
    if mode:
        return str(mode)
    if lockfile is not None:
        return lockfile.storage_mode
    return ""


def _get_model_storage(model_class: type, lockfile: Any | None = None) -> str:
    value = getattr(model_class, "_iris_storage", "") or ""
    if value:
        return str(value)
    if lockfile is not None:
        return lockfile.storage_definition
    return ""


def _lockfile_drift_messages(model_class: type, conn: Any) -> tuple[list[str], list[str]]:
    """Return ``(lockfile_drift, storage_conflicts)`` for *model_class*."""
    try:
        lockfile = _load_model_lockfile(model_class)
    except LockfileDriftError as exc:
        return ([str(exc)], [])

    if lockfile is None:
        return ([], [])

    if not _class_exists_in_iris(model_class._iris_classname, conn):  # type: ignore[attr-defined]
        return ([], [])

    details = get_class_details(model_class._iris_classname, conn)  # type: ignore[attr-defined]
    drift: list[str] = []
    storage_conflicts: list[str] = []

    if lockfile.super and lockfile.super != details.super:
        drift.append(
            f"Superclass differs: lockfile={lockfile.super!r}, live={details.super!r}"
        )

    if dict(lockfile.class_parameters) != dict(details.class_parameters):
        drift.append("Class parameters differ from lockfile")

    live_indexes = _normalized_index_payload(
        [
            {
                "name": idx.name,
                "properties": idx.properties,
                "unique": idx.unique,
                "primary_key": idx.primary_key,
            }
            for idx in details.indexes
        ]
    )
    if _normalized_index_payload(lockfile.indexes) != live_indexes:
        drift.append("Indexes differ from lockfile")

    if lockfile.storage_mode == "preserve":
        live_storage = getattr(details, "storage", None)
        live_hash = compute_hash(live_storage if live_storage is not None else details.storage_definition or "")
        if live_hash != lockfile.storage_hash:
            storage_conflicts.append(
                f"Storage differs: lockfile hash={lockfile.storage_hash}, live hash={live_hash}"
            )

    return (drift, storage_conflicts)


def _assert_no_sidecar_drift(model_class: type, conn: Any) -> None:
    """Raise if a scaffold lockfile is missing or stale for *model_class*."""
    lock_drift, storage_conflicts = _lockfile_drift_messages(model_class, conn)
    if storage_conflicts:
        raise StorageConflictError("; ".join(storage_conflicts))
    if lock_drift:
        raise LockfileDriftError("; ".join(lock_drift))


# ---------------------------------------------------------------------------
# Schema diff
# ---------------------------------------------------------------------------

@dataclass
class SchemaDiff:
    classname: str
    # Python-side changes (vs snapshot):
    python_added:   list[str]
    python_removed: list[str]
    python_changed: list[tuple[str, str, str]]  # (name, snapshot_type, python_type)
    # IRIS-side changes (vs snapshot):
    iris_added:     list[str]
    iris_removed:   list[str]
    iris_changed:   list[tuple[str, str, str]]  # (name, snapshot_type, iris_type)
    # Conflicts: both sides changed the same prop differently
    conflicts:      list[PropertyConflict]
    lockfile_drift: list[str] = dataclass_field(default_factory=list)
    storage_conflicts: list[str] = dataclass_field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        return not (
            self.python_added or self.python_removed or self.python_changed
            or self.iris_added or self.iris_removed or self.iris_changed
            or self.conflicts or self.lockfile_drift or self.storage_conflicts
        )

    def __str__(self) -> str:
        lines: list[str] = [f"Schema status for {self.classname}:"]
        if self.in_sync:
            lines.append("  (up to date)")
            return "\n".join(lines)
        if self.conflicts:
            lines.append("Conflicts (both sides modified):")
            for c in self.conflicts:
                lines.append(
                    f"  ! {c.name}: snapshot={c.snapshot_type!r}, "
                    f"python={c.python_type!r}, iris={c.iris_type!r}"
                )
        if self.storage_conflicts:
            lines.append("Storage conflicts:")
            for item in self.storage_conflicts:
                lines.append(f"  ! {item}")
        if self.lockfile_drift:
            lines.append("Lockfile drift:")
            for item in self.lockfile_drift:
                lines.append(f"  ! {item}")
        if self.python_added:
            lines.append("Python added (not yet pushed to IRIS):")
            for name in self.python_added:
                lines.append(f"  + {name}")
        if self.python_removed:
            lines.append("Python removed (not deleted from IRIS):")
            for name in self.python_removed:
                lines.append(f"  - {name}")
        if self.python_changed:
            lines.append("Python changed:")
            for name, snap, py in self.python_changed:
                lines.append(f"  ~ {name}: {snap!r} → {py!r}")
        if self.iris_added:
            lines.append("IRIS added (not yet pulled to Python):")
            for name in self.iris_added:
                lines.append(f"  + {name}")
        if self.iris_removed:
            lines.append("IRIS removed (not yet reflected in Python):")
            for name in self.iris_removed:
                lines.append(f"  - {name}")
        if self.iris_changed:
            lines.append("IRIS changed:")
            for name, snap, ir in self.iris_changed:
                lines.append(f"  ~ {name}: {snap!r} → {ir!r}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# SchemaManager
# ---------------------------------------------------------------------------

class SchemaManager:
    def __init__(self, model_class: type) -> None:
        self._cls = model_class

    # ------------------------------------------------------------------
    def fetch(self) -> dict[str, str]:
        """Read live IRIS property types. Returns {name: iris_type}."""
        from .connection import IRISConnection  # noqa: PLC0415
        from .introspection import get_class_properties  # noqa: PLC0415

        conn = IRISConnection()
        props = get_class_properties(self._cls._iris_classname, conn)
        return {p.name: p.iris_type for p in props}

    # ------------------------------------------------------------------
    def status(self) -> SchemaDiff:
        """3-way diff: snapshot vs Python, snapshot vs IRIS."""
        if getattr(self._cls, "_iris_serial", False):
            raise RuntimeError(
                "Serial classes (%SerialObject) have no independent IRIS identity — "
                "sync the parent %Persistent class instead."
            )
        snapshot: dict[str, str] = dict(getattr(self._cls, "_iris_schema_snapshot", {}))
        python_props: dict[str, str] = {
            p.name: p.iris_type for p in self._cls._iris_properties
        }
        iris_props: dict[str, str] = self.fetch()
        from .connection import IRISConnection  # noqa: PLC0415

        conn = IRISConnection()
        lockfile_drift, storage_conflicts = _lockfile_drift_messages(self._cls, conn)

        python_added   = [k for k in python_props if k not in snapshot]
        python_removed = [k for k in snapshot if k not in python_props]
        python_changed = [
            (k, snapshot[k], python_props[k])
            for k in snapshot
            if k in python_props and snapshot[k] != python_props[k]
        ]
        iris_added   = [k for k in iris_props if k not in snapshot]
        iris_removed = [k for k in snapshot if k not in iris_props]
        iris_changed = [
            (k, snapshot[k], iris_props[k])
            for k in snapshot
            if k in iris_props and snapshot[k] != iris_props[k]
        ]

        # Conflicts: both sides changed the same property to *different* values.
        py_changed_dict = {name: py for name, _, py in python_changed}
        ir_changed_dict = {name: ir for name, _, ir in iris_changed}
        conflict_names: set[str] = set()
        conflicts: list[PropertyConflict] = []
        for name in set(py_changed_dict) & set(ir_changed_dict):
            py_type = py_changed_dict[name]
            ir_type = ir_changed_dict[name]
            if py_type != ir_type:
                snap_type = snapshot.get(name, "")
                conflicts.append(PropertyConflict(name, snap_type, py_type, ir_type))
                conflict_names.add(name)

        # Remove conflicted entries from changed lists (they belong only to conflicts).
        python_changed = [t for t in python_changed if t[0] not in conflict_names]
        iris_changed   = [t for t in iris_changed   if t[0] not in conflict_names]

        return SchemaDiff(
            classname=self._cls._iris_classname,
            python_added=python_added,
            python_removed=python_removed,
            python_changed=python_changed,
            iris_added=iris_added,
            iris_removed=iris_removed,
            iris_changed=iris_changed,
            conflicts=conflicts,
            lockfile_drift=lockfile_drift,
            storage_conflicts=storage_conflicts,
        )

    # ------------------------------------------------------------------
    def commit(self) -> None:
        """Snapshot current Python definition as new baseline."""
        if getattr(self._cls, "_iris_serial", False):
            raise RuntimeError(
                "Serial classes (%SerialObject) have no independent IRIS identity — "
                "sync the parent %Persistent class instead."
            )
        python_props = {p.name: p.iris_type for p in self._cls._iris_properties}
        self._cls._iris_schema_snapshot = python_props
        print(
            f"Committed snapshot for {self._cls._iris_classname} "
            f"({len(python_props)} properties)"
        )

    # ------------------------------------------------------------------
    def push(self) -> SchemaDiff:
        """Apply Python additions/changes to IRIS. Raises ConflictError on conflicts."""
        if getattr(self._cls, "_iris_serial", False):
            raise RuntimeError(
                "Serial classes (%SerialObject) have no independent IRIS identity — "
                "sync the parent %Persistent class instead."
            )
        d = self.status()
        if d.conflicts:
            raise ConflictError(d.conflicts)

        from .connection import IRISConnection  # noqa: PLC0415

        conn = IRISConnection()
        _assert_no_sidecar_drift(self._cls, conn)

        if d.python_added or d.python_changed:
            field_defs = getattr(self._cls, "_iris_field_defs", {})

            # Ensure the class exists in IRIS before adding properties.
            if not _class_exists_in_iris(self._cls._iris_classname, conn):
                self.ensure_iris_class()
                return d
            class_def = conn.iris_cls("%Dictionary.ClassDefinition")._OpenId(
                self._cls._iris_classname
            )
            if not _looks_like_iris_object(class_def):
                raise RuntimeError(
                    "Unable to open %Dictionary.ClassDefinition for "
                    f"{self._cls._iris_classname!r}"
                )

            prop_map = {p.name: p for p in self._cls._iris_properties}

            for name in d.python_added:
                prop = prop_map.get(name)
                if prop is None:
                    continue
                _upsert_property_via_dict(
                    self._cls._iris_classname,
                    class_def,
                    prop,
                    field_defs.get(name),
                    conn,
                )

            for name, _snap_type, _new_type in d.python_changed:
                prop = prop_map.get(name)
                if prop is None:
                    continue
                _upsert_property_via_dict(
                    self._cls._iris_classname,
                    class_def,
                    prop,
                    field_defs.get(name),
                    conn,
                )

            # Recompile the class in IRIS.
            try:
                conn.iris_cls("%SYSTEM.OBJ").Compile(self._cls._iris_classname, "ck")
            except Exception as exc:
                warnings.warn(f"Recompile failed: {exc}", stacklevel=2)

        for name in d.python_removed:
            warnings.warn(
                f"Property {name!r} removed from Python model but NOT deleted from "
                f"IRIS class {self._cls._iris_classname!r} "
                "(use Model.schema.delete_property(name) to delete explicitly).",
                UserWarning,
                stacklevel=2,
            )

        return d

    # ------------------------------------------------------------------
    def ensure_iris_class(self) -> None:
        """
        Create or update the IRIS class using %Dictionary — no .cls files.

        If the class does not yet exist in IRIS it is created with the correct
        superclass (%Persistent or %SerialObject).  All properties and
        relationships defined on the Python model are then created or updated
        via %Dictionary.PropertyDefinition / %Dictionary.RelationshipDefinition,
        and the class is recompiled with %SYSTEM.OBJ.Compile.

        This is the recommended replacement for compile_to_iris().
        """
        if not getattr(self._cls, "_iris_declared_model", False):
            raise ValueError(
                "ensure_iris_class() requires a declared model class; "
                f"{self._cls.__name__!r} is bound to an existing IRIS class."
            )
        from .connection import IRISConnection  # noqa: PLC0415

        conn = IRISConnection()
        _assert_no_sidecar_drift(self._cls, conn)
        _ensure_iris_class_impl(self._cls)

    # ------------------------------------------------------------------
    def delete_property(self, name: str) -> None:
        """
        Permanently delete a property from the IRIS class via %Dictionary.

        The property is removed from %Dictionary.PropertyDefinition, the class
        is recompiled, and the descriptor + metadata are removed from the Python
        model so the two sides stay in sync.

        .. warning::
            This operation is destructive and cannot be undone.  All data
            stored in this property will be lost once the class is recompiled
            and the storage is rebuilt.
        """
        from .connection import IRISConnection  # noqa: PLC0415

        conn = IRISConnection()
        prop_id = f"{self._cls._iris_classname}||{name}"
        try:
            conn.iris_cls("%Dictionary.PropertyDefinition")._DeleteId(prop_id)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to delete property {name!r} from "
                f"{self._cls._iris_classname!r}: {exc}"
            ) from exc

        try:
            conn.iris_cls("%SYSTEM.OBJ").Compile(self._cls._iris_classname, "ck")
        except Exception as exc:
            warnings.warn(f"Recompile after delete failed: {exc}", stacklevel=2)

        # Keep Python model in sync.
        self._cls._iris_properties = [
            p for p in self._cls._iris_properties if p.name != name
        ]
        field_defs = getattr(self._cls, "_iris_field_defs", {})
        field_defs.pop(name, None)
        snapshot = dict(getattr(self._cls, "_iris_schema_snapshot", {}))
        snapshot.pop(name, None)
        self._cls._iris_schema_snapshot = snapshot
        if hasattr(self._cls, name):
            try:
                delattr(self._cls, name)
            except AttributeError:
                pass

    # ------------------------------------------------------------------
    def pull(self, output_root: str = ".") -> SchemaDiff:
        """Apply IRIS additions to Python model snapshot. Raises ConflictError on conflicts."""
        if getattr(self._cls, "_iris_serial", False):
            raise RuntimeError(
                "Serial classes (%SerialObject) have no independent IRIS identity — "
                "sync the parent %Persistent class instead."
            )
        d = self.status()
        if d.conflicts:
            raise ConflictError(d.conflicts)

        if d.iris_added:
            from .connection import IRISConnection  # noqa: PLC0415
            from .descriptors import IRISDescriptor  # noqa: PLC0415
            from .introspection import get_class_properties  # noqa: PLC0415

            conn = IRISConnection()
            all_iris_props = get_class_properties(self._cls._iris_classname, conn)
            iris_prop_map = {p.name: p for p in all_iris_props}

            new_snapshot = dict(getattr(self._cls, "_iris_schema_snapshot", {}))
            for name in d.iris_added:
                prop = iris_prop_map.get(name)
                if prop is None:
                    continue
                new_snapshot[name] = prop.iris_type
                # Inject a typed descriptor if not already present on the class.
                if name not in self._cls.__dict__:
                    descriptor = IRISDescriptor(name, prop.python_type, prop.required)
                    descriptor.attr_name = name
                    setattr(self._cls, name, descriptor)
                    if not hasattr(self._cls, "__annotations__"):
                        self._cls.__annotations__ = {}
                    self._cls.__annotations__[name] = Optional[prop.python_type]  # type: ignore[valid-type]
                    # Append to _iris_properties so future status() calls see it.
                    self._cls._iris_properties = list(self._cls._iris_properties) + [prop]

            self._cls._iris_schema_snapshot = new_snapshot

        return d

    # ------------------------------------------------------------------
    # .cls file generation (kept for backward compatibility; deprecated)
    # ------------------------------------------------------------------

    def generate_cls(self, storage: str | None = None) -> str:
        """
        Generate an ObjectScript .cls source string.

        .. deprecated::
            Use :meth:`ensure_iris_class` to create or update the IRIS class
            directly via %Dictionary without generating intermediate files.
        """
        warnings.warn(
            "generate_cls() is deprecated. Use ensure_iris_class() to manage the "
            "IRIS class directly via %Dictionary without .cls files.",
            DeprecationWarning,
            stacklevel=2,
        )
        return _generate_cls_impl(self._cls, storage=storage)

    def write_cls(self, output_root: str) -> Path:
        """
        Write the generated .cls source to disk and return the path.

        .. deprecated::
            Use :meth:`ensure_iris_class` to create or update the IRIS class
            directly via %Dictionary without generating intermediate files.
        """
        warnings.warn(
            "write_cls() is deprecated. Use ensure_iris_class() to manage the "
            "IRIS class directly via %Dictionary without .cls files.",
            DeprecationWarning,
            stacklevel=2,
        )
        return _write_cls_impl(self._cls, output_root)

    def compile_to_iris(self, flags: str = "ck") -> None:
        """
        Create or update the IRIS class using %Dictionary — no .cls files.

        .. deprecated::
            Renamed to :meth:`ensure_iris_class`.  This alias calls
            ``ensure_iris_class()`` and will be removed in a future release.
        """
        warnings.warn(
            "compile_to_iris() is deprecated and will be removed in a future release. "
            "Use ensure_iris_class() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        _ensure_iris_class_impl(self._cls, flags=flags)


# ---------------------------------------------------------------------------
# Internal generation helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Internal implementation helpers
# ---------------------------------------------------------------------------

def _ensure_iris_class_impl(model_class: type, flags: str = "ck") -> None:
    """
    Create or update an IRIS class using %Dictionary — no .cls files needed.

    Steps:
    1. Create the %Dictionary.ClassDefinition if the class does not yet exist.
    2. Upsert every property via %Dictionary.PropertyDefinition.
    3. Upsert every relationship via %Dictionary.RelationshipDefinition.
    4. Recompile with %SYSTEM.OBJ.Compile.
    """
    if not getattr(model_class, "_iris_declared_model", False):
        raise ValueError(
            "ensure_iris_class() requires a declared model class; "
            f"{model_class.__name__!r} is bound to an existing IRIS class."
        )

    from .connection import IRISConnection  # noqa: PLC0415

    is_serial: bool = getattr(model_class, "_iris_serial", False)
    classname: str = model_class._iris_classname  # type: ignore[attr-defined]
    field_defs = getattr(model_class, "_iris_field_defs", {})
    rel_defs = getattr(model_class, "_iris_rel_defs", {})
    iris_properties = getattr(model_class, "_iris_properties", [])
    lockfile = None
    try:
        lockfile = _load_model_lockfile(model_class)
    except LockfileDriftError:
        lockfile = None

    conn = IRISConnection()

    # 1. Create the class definition if it does not already exist.
    class_def = None
    if not _class_exists_in_iris(classname, conn):
        class_def = conn.iris_cls("%Dictionary.ClassDefinition")._New()
        class_def.Name = classname
        class_def.Super = "%SerialObject" if is_serial else "%Persistent"
        _save_dictionary_item(class_def, kind="class", identifier=classname)
    else:
        try:
            class_def = conn.iris_cls("%Dictionary.ClassDefinition")._OpenId(classname)
        except Exception:
            class_def = None
        if not _looks_like_iris_object(class_def):
            class_def = None
    if class_def is None:
        raise RuntimeError(f"Unable to open %Dictionary.ClassDefinition for {classname!r}")

    storage_mode = _get_storage_mode(model_class, lockfile)
    storage_text = _get_model_storage(model_class, lockfile)
    if storage_mode == "managed" and storage_text and class_def is not None:
        try:
            setattr(class_def, "Storage", storage_text)
            setattr(class_def, "StorageDefinition", storage_text)
            _save_dictionary_item(class_def, kind="class", identifier=classname)
        except Exception as exc:
            warnings.warn(f"Managed storage apply failed: {exc}", stacklevel=2)

    # 2. Upsert all properties.
    for prop in iris_properties:
        _upsert_property_via_dict(classname, class_def, prop, field_defs.get(prop.name), conn)

    # 3. Upsert all relationships (not applicable to serial objects).
    if not is_serial:
        for rel_name, rd in rel_defs.items():
            _upsert_relationship_via_dict(classname, class_def, rel_name, rd, conn)

    # 4. Recompile.
    try:
        conn.iris_cls("%SYSTEM.OBJ").Compile(classname, flags)
    except Exception as exc:
        warnings.warn(f"Recompile failed: {exc}", stacklevel=2)

    _write_model_lockfile(model_class, conn=conn)


# ---------------------------------------------------------------------------
# Legacy .cls generation helpers (kept for backward compatibility)
# ---------------------------------------------------------------------------

def _generate_cls_impl(model_class: type, storage: str | None = None) -> str:
    """Generate an ObjectScript .cls source string (legacy; prefer ensure_iris_class)."""
    if not getattr(model_class, "_iris_declared_model", False):
        raise ValueError(
            f"generate_cls() requires a declared model class; "
            f"{model_class.__name__!r} is bound to an existing IRIS class."
        )

    is_serial: bool = getattr(model_class, "_iris_serial", False)
    classname: str = model_class._iris_classname  # type: ignore[attr-defined]
    field_defs = getattr(model_class, "_iris_field_defs", {})
    rel_defs = getattr(model_class, "_iris_rel_defs", {})
    iris_properties = getattr(model_class, "_iris_properties", [])

    lines: list[str] = []
    extends = "%SerialObject" if is_serial else "%Persistent"
    lines.append(f"Class {classname} Extends {extends}")
    lines.append("{")
    lines.append("")

    for prop in iris_properties:
        fd = field_defs.get(prop.name)
        description = (fd.description if fd else "") or ""
        if description:
            lines.append(f"/// {description}")

        iris_type = prop.iris_type or "%String"
        constraints: list[str] = []
        if fd:
            if fd.required:
                constraints.append("Required")
            if fd.collection:
                constraints.append(f"Collection = {fd.collection.capitalize()}")

        params: list[str] = []
        if fd and fd.maxlen is not None:
            params.append(f"MAXLEN = {fd.maxlen}")

        prop_line = f"Property {prop.name} As {iris_type}"
        if params:
            prop_line += f" (  {', '.join(params)} )"
        if constraints:
            prop_line += " [ " + ", ".join(constraints) + " ]"
        prop_line += ";"
        lines.append(prop_line)
        lines.append("")

    for rel_name, rd in rel_defs.items():
        description = rd.description or ""
        if description:
            lines.append(f"/// {description}")
        card_keyword = _CARD_MAP.get(rd.cardinality, rd.cardinality)
        lines.append(
            f"Relationship {rel_name} As {rd.related_classname} "
            f"[ Cardinality = {card_keyword}, Inverse = {rd.inverse} ];"
        )
        lines.append("")

    lines.append("}")
    source = "\n".join(lines) + "\n"

    # Storage block: class attr → explicit arg → omit. Skip entirely for serials.
    if not is_serial:
        lockfile = None
        try:
            lockfile = _load_model_lockfile(model_class)
        except LockfileDriftError:
            lockfile = None
        storage_text = storage or _get_model_storage(model_class, lockfile) or ""
        if storage_text:
            source = _STORAGE_RE.sub("", source)
            source = source.rstrip()
            if source.endswith("}"):
                source = source[:-1].rstrip() + "\n\n" + storage_text.strip() + "\n}\n"

    return source


def _write_cls_impl(model_class: type, output_root: str) -> Path:
    """Write .cls source to disk (legacy; prefer ensure_iris_class)."""
    source = _generate_cls_impl(model_class)
    classname: str = model_class._iris_classname  # type: ignore[attr-defined]
    parts = classname.split(".")
    rel_path = (
        Path(*parts[:-1], parts[-1] + ".cls") if len(parts) > 1 else Path(parts[0] + ".cls")
    )
    output_path = Path(output_root) / rel_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(source, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Backward-compatible module-level functions (deprecated)
# ---------------------------------------------------------------------------

def generate_cls(model_class: type) -> str:
    """
    Generate an ObjectScript .cls source string.

    .. deprecated::
        Use ``Model.schema.ensure_iris_class()`` to manage the IRIS class
        directly via %Dictionary without .cls files.
    """
    warnings.warn(
        "generate_cls() is deprecated. Use Model.schema.ensure_iris_class() "
        "to manage the IRIS class directly via %Dictionary without .cls files.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _generate_cls_impl(model_class)


def write_cls(model_class: type, output_root: str) -> Path:
    """
    Write the generated .cls source to disk.

    .. deprecated::
        Use ``Model.schema.ensure_iris_class()`` to manage the IRIS class
        directly via %Dictionary without .cls files.
    """
    warnings.warn(
        "write_cls() is deprecated. Use Model.schema.ensure_iris_class() "
        "to manage the IRIS class directly via %Dictionary without .cls files.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _write_cls_impl(model_class, output_root)


def compile_to_iris(model_class: type) -> None:
    """
    Create or update the IRIS class using %Dictionary (no .cls files).

    .. deprecated::
        Renamed to ``Model.schema.ensure_iris_class()``.  This module-level
        alias will be removed in a future release.
    """
    warnings.warn(
        "compile_to_iris() is deprecated. Use Model.schema.ensure_iris_class() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    _ensure_iris_class_impl(model_class)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import importlib
    import sys

    parser = argparse.ArgumentParser(
        description="Create or update an IRIS class via %Dictionary from an iris_orm model.",
    )
    parser.add_argument(
        "iris_classname",
        help="IRIS class name of the registered Python-first model, e.g. Demo.Post",
    )
    parser.add_argument(
        "--module",
        default=None,
        help="Python module to import before looking up the model (ensures registration).",
    )
    args = parser.parse_args()

    if args.module:
        importlib.import_module(args.module)

    from .metaclass import _MODEL_REGISTRY  # noqa: PLC0415

    model_class = _MODEL_REGISTRY.get(args.iris_classname)
    if model_class is None:
        print(
            f"Error: No model registered for IRIS class '{args.iris_classname}'. "
            "Did you import the module that defines it? Use --module.",
            file=sys.stderr,
        )
        sys.exit(1)

    _ensure_iris_class_impl(model_class)
    print(f"ensure_iris_class: {args.iris_classname} created/updated via %Dictionary.")


if __name__ == "__main__":
    main()
