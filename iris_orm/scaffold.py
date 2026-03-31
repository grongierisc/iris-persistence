"""
Scaffold Python models and lockfiles from live IRIS or exported .cls files.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .introspection import list_classes
from .lockfile import build_lockfile, lockfile_path_for_module, write_lockfile
from .schema import (
    SchemaCatalog,
    SchemaClass,
    SchemaCompiler,
    python_annotation_for_property,
)

GENERATED_START = "# <iris_orm:generated>"
GENERATED_END = "# </iris_orm:generated>"


def scaffold_from_iris(
    pattern: str,
    output_root: str | Path,
    *,
    style: str = "typed",
    conn: Any = None,
) -> list[Path]:
    compiler = SchemaCompiler(conn)
    classnames = list_classes(pattern, conn)
    catalog = compiler.catalog_from_iris(classnames)
    return _write_catalog(catalog, output_root=output_root, style=style, source_kind="iris")


def scaffold_from_cls(
    cls_root: str | Path,
    output_root: str | Path,
    *,
    style: str = "typed",
) -> list[Path]:
    catalog = SchemaCompiler().catalog_from_cls_path(cls_root)
    return _write_catalog(catalog, output_root=output_root, style=style, source_kind="cls")


def render_model(schema_class: SchemaClass, *, style: str = "typed") -> str:
    class_name = python_class_name(schema_class.name)
    base_class = "IRISSerial" if schema_class.kind == "serial" else "IRISModel"
    lines = [GENERATED_START, f"from iris_orm import {base_class}, field, relationship", "", f"class {class_name}({base_class}):"]
    lines.append(f'    _iris_classname = "{schema_class.name}"')
    lines.append("")
    if style == "existing":
        lines.append("    pass")
        lines.append(GENERATED_END)
        return "\n".join(lines)

    if not schema_class.properties and not schema_class.relationships:
        lines.append("    pass")
    for prop in schema_class.properties:
        annotation = python_annotation_for_property(prop)
        extras = []
        if prop.required:
            extras.append("required=True")
        if prop.maxlen is not None:
            extras.append(f"maxlen={prop.maxlen}")
        if prop.collection:
            extras.append(f'collection="{prop.collection}"')
        if prop.description:
            extras.append(f'description="{prop.description}"')
        if prop.default:
            extras.append(f'default={prop.default!r}')
        if prop.iris_type.startswith("Demo.") or prop.iris_type.startswith("%"):
            extras.append(f'iris_type="{prop.iris_type}"')
        call = f"field({', '.join(extras)})" if extras else "field()"
        lines.append(f"    {prop.name}: {annotation} = {call}")
    if schema_class.properties and schema_class.relationships:
        lines.append("")
    for rel in schema_class.relationships:
        lines.append(
            f'    {rel.name} = relationship("{rel.related_classname}", inverse="{rel.inverse}", cardinality="{rel.cardinality}")'
        )
    lines.append(GENERATED_END)
    return "\n".join(lines)


def write_scaffold(
    schema_class: SchemaClass,
    *,
    output_root: str | Path,
    style: str = "typed",
    source_kind: str = "iris",
) -> Path:
    output_path = python_path_for_class(output_root, schema_class.name)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_package_init(output_path.parent, stop_at=Path(output_root))
    output_path.write_text(render_model(schema_class, style=style) + "\n", encoding="utf-8")
    lockfile = build_lockfile(
        SchemaCatalog(classes=(schema_class,)),
        source={"kind": source_kind, "origin": schema_class.source.get("origin", schema_class.name)},
    )
    write_lockfile(lockfile_path_for_module(output_path), lockfile)
    return output_path


def python_path_for_class(output_root: str | Path, classname: str) -> Path:
    parts = classname.split(".")
    return Path(output_root) / Path(*[item.lower() for item in parts[:-1]], f"{parts[-1].lower()}.py")


def python_class_name(classname: str) -> str:
    return classname.split(".")[-1]


def _write_catalog(
    catalog: SchemaCatalog,
    *,
    output_root: str | Path,
    style: str,
    source_kind: str,
) -> list[Path]:
    paths: list[Path] = []
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    _ensure_package_init(output_root_path, stop_at=output_root_path)
    for schema_class in catalog.classes:
        paths.append(write_scaffold(schema_class, output_root=output_root_path, style=style, source_kind=source_kind))
    return paths


def _ensure_package_init(path: Path, *, stop_at: Path) -> None:
    current = path
    while True:
        init_path = current / "__init__.py"
        if not init_path.exists():
            init_path.write_text("", encoding="utf-8")
        if current == stop_at:
            return
        if current.parent == current:
            return
        current = current.parent


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Scaffold Python IRIS models from live IRIS or .cls files.")
    parser.add_argument("source", help="IRIS class pattern or path to .cls root")
    parser.add_argument("--output", default="./generated_models", help="Output root")
    parser.add_argument("--style", default="typed", choices=["typed", "existing"])
    parser.add_argument("--from-cls", action="store_true", help="Treat source as .cls root instead of live IRIS pattern")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_cli()
    args = parser.parse_args(argv)
    if args.from_cls:
        paths = scaffold_from_cls(args.source, args.output, style=args.style)
    else:
        paths = scaffold_from_iris(args.source, args.output, style=args.style)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
