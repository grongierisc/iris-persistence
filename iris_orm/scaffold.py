from __future__ import annotations

from pathlib import Path
from pprint import pformat
from typing import Any

from .adapter import IRISAdapter
from .schema import SchemaClass, SchemaCompiler, match_classnames, parse_cls, python_default_source


def scaffold_from_iris(
    pattern: str,
    output_root: str | Path,
    *,
    style: str = "proxy",
    conn: Any | None = None,
) -> list[Path]:
    adapter = conn or IRISAdapter()
    classnames = adapter.list_classes(pattern)
    classes = SchemaCompiler(adapter).catalog_from_iris(classnames)
    return [write_scaffold(item, output_root=output_root, style=style) for item in classes]


def scaffold_from_cls(
    cls_root: str | Path,
    output_root: str | Path,
    *,
    style: str = "proxy",
) -> list[Path]:
    root = Path(cls_root)
    classes = [parse_cls(path.read_text(encoding="utf-8"), source_path=str(path)) for path in sorted(root.rglob("*.cls"))]
    return [write_scaffold(item, output_root=output_root, style=style) for item in classes]


def render_model(schema_class: SchemaClass, *, style: str = "proxy") -> str:
    mode = normalize_style(style)
    imports = "from iris_orm import IRISModel, field"
    if mode == "python":
        imports += ", index, parameter"
    lines = [imports, ""]
    if mode == "python":
        for key in sorted(schema_class.parameters):
            lines.append(f"@parameter({key!r}, {schema_class.parameters[key]!r})")
        for item in schema_class.indexes:
            args = [f'"{item.name}"', f'properties="{item.properties}"']
            if item.unique:
                args.append("unique=True")
            if item.primary_key:
                args.append("primary_key=True")
            lines.append(f"@index({', '.join(args)})")
    lines.append(f"class {schema_class.name.split('.')[-1]}(IRISModel):")
    lines.append(f'    _iris_classname = "{schema_class.name}"')
    lines.append(f'    _iris_mode = "{mode}"')
    if schema_class.superclasses != ("%Persistent",):
        if len(schema_class.superclasses) == 1:
            lines.append(f'    _iris_superclasses = "{schema_class.superclasses[0]}"')
        else:
            lines.append(f"    _iris_superclasses = {list(schema_class.superclasses)!r}")
    if schema_class.storage is not None:
        rendered = pformat(schema_class.storage, width=100, sort_dicts=True).splitlines()
        lines.append(f"    _iris_storage = {rendered[0]}")
        for line in rendered[1:]:
            lines.append(f"    {line}")
    lines.append("")
    if not schema_class.properties:
        lines.append("    pass")
    for prop in schema_class.properties:
        parts: list[str] = []
        if prop.required:
            parts.append("required=True")
        if prop.maxlen is not None:
            parts.append(f"maxlen={prop.maxlen}")
        default_src = python_default_source(prop.default, prop.iris_type)
        if default_src is not None:
            parts.append(f"default={default_src}")
        parts.append(f'iris_type="{prop.iris_type}"')
        lines.append(f"    {prop.name}: {_annotation(prop.iris_type)} = field({', '.join(parts)})")
    return "\n".join(lines) + "\n"


def write_scaffold(schema_class: SchemaClass, *, output_root: str | Path, style: str = "proxy") -> Path:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{schema_class.name.split('.')[-1].lower()}.py"
    output_path.write_text(render_model(schema_class, style=style), encoding="utf-8")
    return output_path


def normalize_style(style: str) -> str:
    normalized = str(style or "proxy").strip().lower()
    if normalized not in {"proxy", "python"}:
        raise ValueError(f"Unsupported scaffold style: {style!r}")
    return normalized


def _annotation(iris_type: str) -> str:
    mapping = {
        "%String": "str",
        "%Integer": "int",
        "%Float": "float",
        "%Boolean": "bool",
        "%Stream.GlobalBinary": "bytes",
    }
    return mapping.get(iris_type, "str")
