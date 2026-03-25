"""
ObjectScript .cls source generator and IRIS compiler (Plan C).

Usage:
    python -m iris_orm.schema Demo.Post ./src/cls/
    python -m iris_orm.schema Demo.Post ./src/cls/ --compile
"""
from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Cardinality mapping from Python strings → ObjectScript keywords
_CARD_MAP: dict[str, str] = {
    "children": "many",
    "parent": "one",
    "one": "one",
    "many": "many",
}


def generate_cls(model_class: type) -> str:
    """
    Generate an ObjectScript .cls source string from a Python-first IRISModel subclass.

    Raises ValueError if model_class is not a Python-first (Plan C) class.
    """
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

    # Properties
    for prop in iris_properties:
        fd = field_defs.get(prop.name)

        # Description comment
        description = (fd.description if fd else "") or ""
        if description:
            lines.append(f"/// {description}")

        iris_type = prop.iris_type or "%String"
        constraints: list[str] = []

        if fd:
            if fd.required:
                constraints.append("Required")
            if fd.collection:
                collection_keyword = fd.collection.capitalize()
                constraints.append(f"Collection = {collection_keyword}")

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

    # Relationships
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
    return "\n".join(lines) + "\n"


def write_cls(model_class: type, output_root: str) -> Path:
    """
    Write the generated .cls source to disk.

    "Demo.Post" → <output_root>/Demo/Post.cls
    Returns the Path that was written.
    """
    source = generate_cls(model_class)
    classname: str = model_class._iris_classname  # type: ignore[attr-defined]
    parts = classname.split(".")
    rel_path = Path(*parts[:-1], parts[-1] + ".cls") if len(parts) > 1 else Path(parts[0] + ".cls")
    output_path = Path(output_root) / rel_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(source, encoding="utf-8")
    return output_path


def compile_to_iris(model_class: type) -> None:
    """
    Compile the generated .cls source into a running IRIS instance.

    Tries LoadStream first; falls back to writing a temp file and Load.
    """
    import iris  # noqa: PLC0415

    source = generate_cls(model_class)
    sys_obj = iris.cls("%SYSTEM.OBJ")

    # Attempt 1: LoadStream
    try:
        stream = iris.cls("%Stream.GlobalCharacter")._New()
        stream.Write(source)
        result = sys_obj.LoadStream(stream, "ck")
        print(f"compile_to_iris: LoadStream result = {result!r}")
        return
    except Exception as exc:
        print(f"compile_to_iris: LoadStream failed ({exc}), trying file-based Load …")

    # Attempt 2: write temp file and Load
    with tempfile.NamedTemporaryFile(
        suffix=".cls", mode="w", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(source)
        tmp_path = tmp.name

    try:
        result = sys_obj.Load(tmp_path, "ck")
        print(f"compile_to_iris: Load result = {result!r}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


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

    path = write_cls(model_class, args.output_root)
    print(f"Written: {path}")

    if args.compile:
        compile_to_iris(model_class)


if __name__ == "__main__":
    main()
