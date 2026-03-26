"""
Git-style schema sync for IRIS ORM (Plan C).

API
---
Post.schema.status()   → 3-way diff (snapshot ↔ Python, snapshot ↔ IRIS)
Post.schema.fetch()    → read IRIS schema into cache, no changes applied
Post.schema.pull()     → fetch + apply IRIS additions to Python snapshot; ConflictError on conflicts
Post.schema.push()     → apply Python additions to IRIS via %Dictionary; ConflictError on conflicts
Post.schema.commit()   → snapshot current Python definition as new baseline

Storage preservation
--------------------
The Storage block is NEVER modified by any schema operation.
Priority: _iris_storage class attr > existing .cls file > omit (IRIS auto-generates).

Connection
----------
Uses the model's _iris_engine (None = embedded iris module, or SQLAlchemy engine).
"""
from __future__ import annotations

import os
import re
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Cardinality mapping from Python strings → ObjectScript keywords
_CARD_MAP: dict[str, str] = {
    "children": "many",
    "parent": "one",
    "one": "one",
    "many": "many",
}

_STORAGE_RE = re.compile(r"(Storage\s+\w+\s*\{.*?\}\s*\n?)", re.DOTALL)


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

    @property
    def in_sync(self) -> bool:
        return not (
            self.python_added or self.python_removed or self.python_changed
            or self.iris_added or self.iris_removed or self.iris_changed
            or self.conflicts
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

        engine = getattr(self._cls, "_iris_engine", None)
        conn = IRISConnection(engine)
        props = get_class_properties(self._cls._iris_classname, conn)
        return {p.name: p.iris_type for p in props}

    # ------------------------------------------------------------------
    def status(self) -> SchemaDiff:
        """3-way diff: snapshot vs Python, snapshot vs IRIS."""
        snapshot: dict[str, str] = dict(getattr(self._cls, "_iris_schema_snapshot", {}))
        python_props: dict[str, str] = {
            p.name: p.iris_type for p in self._cls._iris_properties
        }
        iris_props: dict[str, str] = self.fetch()

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
        )

    # ------------------------------------------------------------------
    def commit(self) -> None:
        """Snapshot current Python definition as new baseline."""
        python_props = {p.name: p.iris_type for p in self._cls._iris_properties}
        self._cls._iris_schema_snapshot = python_props
        print(
            f"Committed snapshot for {self._cls._iris_classname} "
            f"({len(python_props)} properties)"
        )

    # ------------------------------------------------------------------
    def push(self) -> SchemaDiff:
        """Apply Python additions to IRIS. Raises ConflictError on conflicts."""
        d = self.status()
        if d.conflicts:
            raise ConflictError(d.conflicts)

        if d.python_added:
            from .connection import IRISConnection  # noqa: PLC0415

            engine = getattr(self._cls, "_iris_engine", None)
            conn = IRISConnection(engine)
            prop_def_cls = conn.iris_cls("%Dictionary.PropertyDefinition")
            for name in d.python_added:
                prop = next(
                    (p for p in self._cls._iris_properties if p.name == name), None
                )
                if prop is None:
                    continue
                prop_def = prop_def_cls._New()
                prop_def.Name = name
                prop_def.parent = self._cls._iris_classname
                prop_def.Type = prop.iris_type
                prop_def._Save()
            # Recompile the class in IRIS.
            try:
                conn.iris_cls("%SYSTEM.OBJ").Compile(self._cls._iris_classname, "ck")
            except Exception as exc:
                warnings.warn(f"Recompile failed: {exc}", stacklevel=2)

        for name in d.python_removed:
            warnings.warn(
                f"Property {name!r} removed from Python model but NOT deleted from "
                f"IRIS class {self._cls._iris_classname!r} "
                "(destructive operations are not performed automatically).",
                UserWarning,
                stacklevel=2,
            )

        return d

    # ------------------------------------------------------------------
    def pull(self, output_root: str = ".") -> SchemaDiff:
        """Apply IRIS additions to Python model snapshot. Raises ConflictError on conflicts."""
        d = self.status()
        if d.conflicts:
            raise ConflictError(d.conflicts)

        if d.iris_added:
            from .connection import IRISConnection  # noqa: PLC0415
            from .descriptors import IRISDescriptor  # noqa: PLC0415
            from .introspection import get_class_properties  # noqa: PLC0415

            engine = getattr(self._cls, "_iris_engine", None)
            conn = IRISConnection(engine)
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
    # .cls file generation (same as old schema.py, with storage preservation)
    # ------------------------------------------------------------------

    def generate_cls(self, storage: str | None = None) -> str:
        """Generate an ObjectScript .cls source string."""
        return _generate_cls_impl(self._cls, storage=storage)

    def write_cls(self, output_root: str) -> Path:
        """Write the generated .cls source to disk and return the path."""
        return _write_cls_impl(self._cls, output_root)

    def compile_to_iris(self, flags: str = "ck") -> None:
        """Compile the generated .cls source into a running IRIS instance."""
        _compile_to_iris_impl(self._cls, flags=flags)


# ---------------------------------------------------------------------------
# Internal generation helpers
# ---------------------------------------------------------------------------

def _generate_cls_impl(model_class: type, storage: str | None = None) -> str:
    if not getattr(model_class, "_iris_python_first", False):
        raise ValueError(
            f"generate_cls() requires a Python-first (Plan C) model class; "
            f"{model_class.__name__!r} was created in Plan A (introspection) mode."
        )

    classname: str = model_class._iris_classname  # type: ignore[attr-defined]
    field_defs = getattr(model_class, "_iris_field_defs", {})
    rel_defs = getattr(model_class, "_iris_rel_defs", {})
    iris_properties = getattr(model_class, "_iris_properties", [])

    lines: list[str] = []
    lines.append(f"Class {classname} Extends %Persistent")
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

    # Storage block: class attr → explicit arg → omit.
    storage_text = storage or getattr(model_class, "_iris_storage", "") or ""
    if storage_text:
        source = _STORAGE_RE.sub("", source)
        source = source.rstrip()
        if source.endswith("}"):
            source = source[:-1].rstrip() + "\n\n" + storage_text.strip() + "\n}\n"

    return source


def _write_cls_impl(model_class: type, output_root: str) -> Path:
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


def _compile_to_iris_impl(model_class: type, flags: str = "ck") -> None:
    import iris  # noqa: PLC0415

    source = _generate_cls_impl(model_class)
    sys_obj = iris.cls("%SYSTEM.OBJ")

    try:
        stream = iris.cls("%Stream.GlobalCharacter")._New()
        stream.Write(source)
        result = sys_obj.LoadStream(stream, flags)
        print(f"compile_to_iris: LoadStream result = {result!r}")
        return
    except Exception as exc:
        print(f"compile_to_iris: LoadStream failed ({exc}), trying file-based Load …")

    with tempfile.NamedTemporaryFile(
        suffix=".cls", mode="w", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(source)
        tmp_path = tmp.name

    try:
        result = sys_obj.Load(tmp_path, flags)
        print(f"compile_to_iris: Load result = {result!r}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Backward-compatible module-level functions
# ---------------------------------------------------------------------------

def generate_cls(model_class: type) -> str:
    """Generate an ObjectScript .cls source string (backward-compatible wrapper)."""
    return _generate_cls_impl(model_class)


def write_cls(model_class: type, output_root: str) -> Path:
    """Write the generated .cls source to disk (backward-compatible wrapper)."""
    return _write_cls_impl(model_class, output_root)


def compile_to_iris(model_class: type) -> None:
    """Compile the generated .cls source into IRIS (backward-compatible wrapper)."""
    _compile_to_iris_impl(model_class)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    import importlib
    import sys

    parser = argparse.ArgumentParser(
        description="Generate ObjectScript .cls from an iris_orm model class.",
    )
    parser.add_argument(
        "iris_classname",
        help="IRIS class name of the registered Python-first model, e.g. Demo.Post",
    )
    parser.add_argument(
        "output_root",
        help="Directory root to write the .cls file into.",
    )
    parser.add_argument(
        "--compile",
        action="store_true",
        default=False,
        help="Also compile the generated class into the connected IRIS instance.",
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

    path = _write_cls_impl(model_class, args.output_root)
    print(f"Written: {path}")

    if args.compile:
        _compile_to_iris_impl(model_class)


if __name__ == "__main__":
    main()
