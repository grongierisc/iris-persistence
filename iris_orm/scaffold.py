"""
Scaffold Python ORM models and sidecar lockfiles from existing IRIS classes.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import LockfileDriftError, UnsupportedClassFeatureError
from .introspection import IndexInfo, PropertyInfo, RelationshipInfo, UnsupportedFeatureInfo, get_class_details, list_classes
from .lockfile import IRISLockfile, compute_hash, lockfile_path_for_class, timestamp_utc, write_lockfile
from .types import iris_type_to_annotation

GENERATED_START = "# <iris_orm:generated>"
GENERATED_END = "# </iris_orm:generated>"
STATE_DIR = ".iris_orm/state"


@dataclass(frozen=True)
class SourceInfo:
    kind: str
    origin: str


@dataclass(frozen=True)
class ParsedClassSource:
    classname: str
    super: str
    properties: list[PropertyInfo]
    relationships: list[RelationshipInfo]
    class_parameters: dict[str, str]
    indexes: list[IndexInfo]
    storage_definition: str
    unsupported_features: list[UnsupportedFeatureInfo]
    source_path: str


def scaffold_from_iris(
    pattern: str,
    output_root: str | Path,
    *,
    style: str = "plan-c",
    refresh: bool = False,
    state_root: str | Path = STATE_DIR,
    conn: Any = None,
) -> list[Path]:
    """Scaffold models for classes matching *pattern* from a live IRIS namespace."""
    classnames = list_classes(pattern, conn)
    infos = [get_class_details(classname, conn) for classname in classnames]
    return _write_scaffold_batch(
        infos,
        output_root=output_root,
        state_root=state_root,
        style=style,
        refresh=refresh,
        source_builder=lambda info: SourceInfo(kind="iris", origin=pattern),
    )


def scaffold_from_cls(
    cls_root: str | Path,
    output_root: str | Path,
    *,
    style: str = "plan-c",
    refresh: bool = False,
    state_root: str | Path = STATE_DIR,
) -> list[Path]:
    """Scaffold models from exported .cls files."""
    parsed = parse_cls_tree(cls_root)
    return _write_scaffold_batch(
        parsed,
        output_root=output_root,
        state_root=state_root,
        style=style,
        refresh=refresh,
        source_builder=lambda info: SourceInfo(kind="cls", origin=getattr(info, "source_path", str(cls_root))),
    )


def refresh_from_iris(
    pattern: str,
    output_root: str | Path,
    *,
    style: str = "plan-c",
    state_root: str | Path = STATE_DIR,
    conn: Any = None,
) -> list[Path]:
    """Refresh scaffolded models from a live IRIS namespace."""
    return scaffold_from_iris(
        pattern,
        output_root,
        style=style,
        refresh=True,
        state_root=state_root,
        conn=conn,
    )


def discover_classnames_from_cls(root: str | Path) -> list[tuple[str, Path]]:
    """Return ``(classname, path)`` pairs discovered in a .cls tree."""
    results: list[tuple[str, Path]] = []
    for path in sorted(Path(root).rglob("*.cls")):
        source = path.read_text(encoding="utf-8")
        match = re.search(r"Class\s+([A-Za-z0-9_.]+)\s+Extends\s+([A-Za-z0-9_,%.]+)", source)
        if match:
            results.append((match.group(1), path))
    return results


def parse_cls_tree(root: str | Path) -> list[ParsedClassSource]:
    """Parse all discoverable .cls files under *root*."""
    infos: list[ParsedClassSource] = []
    for classname, path in discover_classnames_from_cls(root):
        infos.append(parse_cls_file(path, classname=classname))
    return infos


def parse_cls_file(path: str | Path, *, classname: str | None = None) -> ParsedClassSource:
    """Parse a single exported .cls file."""
    source_path = Path(path)
    source = source_path.read_text(encoding="utf-8")
    class_match = re.search(
        r"Class\s+([A-Za-z0-9_.]+)\s+Extends\s+([A-Za-z0-9_,%.]+)",
        source,
    )
    if class_match is None:
        raise UnsupportedClassFeatureError(f"Unable to discover class header in {source_path}")

    parsed_classname = classname or class_match.group(1)
    super_value = class_match.group(2).split(",")[0].strip()
    properties = _parse_properties_from_cls(source)
    relationships = _parse_relationships_from_cls(source)
    class_parameters = _parse_parameters_from_cls(source)
    indexes = _parse_indexes_from_cls(source)
    storage = _parse_storage_from_cls(source)
    unsupported = _detect_unsupported_in_cls(source)
    return ParsedClassSource(
        classname=parsed_classname,
        super=super_value,
        properties=properties,
        relationships=relationships,
        class_parameters=class_parameters,
        indexes=indexes,
        storage_definition=storage,
        unsupported_features=unsupported,
        source_path=str(source_path),
    )


def _parse_properties_from_cls(source: str) -> list[PropertyInfo]:
    props: list[PropertyInfo] = []
    pattern = re.compile(
        r"Property\s+([A-Za-z][A-Za-z0-9_]*)\s+As\s+([A-Za-z0-9_.%]+)"
        r"(?:\s*\(\s*([^)]+)\s*\))?"
        r"(?:\s*\[\s*([^\]]+)\s*\])?;"
    )
    for match in pattern.finditer(source):
        name = match.group(1)
        iris_type = match.group(2)
        params = _parse_assignment_list(match.group(3) or "")
        qualifiers = _parse_flag_list(match.group(4) or "")
        props.append(
            PropertyInfo(
                name=name,
                iris_type=iris_type,
                python_type=_python_type_for_iris(iris_type),
                required="required" in qualifiers,
                collection=str(params.get("collection", "")).lower(),
                default=str(params.get("initialexpression", "")),
                maxlen=_as_int(params.get("maxlen")),
                description="",
            )
        )
    return props


def _parse_relationships_from_cls(source: str) -> list[RelationshipInfo]:
    rels: list[RelationshipInfo] = []
    pattern = re.compile(
        r"Relationship\s+([A-Za-z][A-Za-z0-9_]*)\s+As\s+([A-Za-z0-9_.%]+)"
        r"\s*\[\s*([^\]]+)\s*\]\s*;"
    )
    for match in pattern.finditer(source):
        attrs = _parse_assignment_list(match.group(3))
        rels.append(
            RelationshipInfo(
                name=match.group(1),
                related_classname=match.group(2),
                cardinality=str(attrs.get("cardinality", "one")).lower(),
                inverse=str(attrs.get("inverse", "")),
                description="",
            )
        )
    return rels


def _parse_parameters_from_cls(source: str) -> dict[str, str]:
    params: dict[str, str] = {}
    pattern = re.compile(r"Parameter\s+([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.+?);")
    for match in pattern.finditer(source):
        params[match.group(1)] = match.group(2).strip()
    return params


def _parse_indexes_from_cls(source: str) -> list[IndexInfo]:
    indexes: list[IndexInfo] = []
    pattern = re.compile(
        r"Index\s+([A-Za-z][A-Za-z0-9_]*)\s+On\s+\(([^)]*)\)"
        r"(?:\s*\[\s*([^\]]+)\s*\])?;"
    )
    for match in pattern.finditer(source):
        attrs = _parse_assignment_list(match.group(3) or "")
        indexes.append(
            IndexInfo(
                name=match.group(1),
                properties=match.group(2).strip(),
                unique=_as_bool(attrs.get("unique")),
                primary_key=_as_bool(attrs.get("primarykey")),
            )
        )
    return indexes


def _parse_storage_from_cls(source: str) -> str:
    match = re.search(r"(Storage\s+\w+\s*\{.*?\n\})", source, re.DOTALL)
    if match is None:
        return ""
    return match.group(1).strip()


def _detect_unsupported_in_cls(source: str) -> list[UnsupportedFeatureInfo]:
    unsupported: list[UnsupportedFeatureInfo] = []
    patterns = [
        ("method", r"Method\s+([A-Za-z][A-Za-z0-9_]*)"),
        ("trigger", r"Trigger\s+([A-Za-z][A-Za-z0-9_]*)"),
        ("projection", r"Projection\s+([A-Za-z][A-Za-z0-9_]*)"),
    ]
    for kind, pattern in patterns:
        for match in re.finditer(pattern, source):
            unsupported.append(UnsupportedFeatureInfo(kind=kind, name=match.group(1)))
    return unsupported


def _parse_assignment_list(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if not value.strip():
        return result
    for part in [piece.strip() for piece in value.split(",") if piece.strip()]:
        if "=" in part:
            key, raw_value = part.split("=", 1)
            result[key.strip().lower()] = raw_value.strip().strip('"')
        else:
            result[part.strip().lower()] = "1"
    return result


def _parse_flag_list(value: str) -> set[str]:
    return {piece.strip().lower() for piece in value.split(",") if piece.strip()}


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _python_type_for_iris(iris_type: str) -> type:
    from .types import iris_type_to_python  # noqa: PLC0415
    return iris_type_to_python(iris_type)


def _write_scaffold_batch(
    infos: list[Any],
    *,
    output_root: str | Path,
    state_root: str | Path,
    style: str,
    refresh: bool,
    source_builder: Any,
) -> list[Path]:
    output_root_path = Path(output_root)
    output_root_path.mkdir(parents=True, exist_ok=True)
    _ensure_package_init(output_root_path, stop_at=output_root_path)

    class_map = {info.classname: info for info in infos}
    paths: list[Path] = []
    for info in infos:
        source = source_builder(info)
        paths.append(
            write_scaffold(
                info,
                output_root=output_root_path,
                state_root=state_root,
                style=style,
                refresh=refresh,
                class_map=class_map,
                source=source,
            )
        )
    return paths


def write_scaffold(
    info: Any,
    *,
    output_root: str | Path,
    state_root: str | Path = STATE_DIR,
    style: str = "plan-c",
    refresh: bool = False,
    class_map: dict[str, Any] | None = None,
    source: SourceInfo | None = None,
) -> Path:
    """Write scaffolded Python + lockfile for *info*."""
    class_map = class_map or {info.classname: info}
    output_path = python_path_for_class(output_root, info.classname)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _ensure_package_init(output_path.parent, stop_at=Path(output_root))
    generated_block = render_model(
        info,
        style=style,
        class_map=class_map,
        output_path=output_path,
        state_root=state_root,
    )
    generated_hash = compute_hash(generated_block)
    existing_manual = ""
    if output_path.exists():
        existing_manual = _read_manual_content(output_path)
        if refresh:
            _assert_refresh_safe(output_path, state_root, info.classname, generated_hash=None)
    file_source = _assemble_scaffold_file(generated_block, existing_manual)
    output_path.write_text(file_source, encoding="utf-8")

    lockfile = IRISLockfile(
        classname=info.classname,
        super=getattr(info, "super", "%Persistent"),
        storage_mode="preserve",
        storage_definition=getattr(info, "storage_definition", ""),
        storage_hash=compute_hash(getattr(info, "storage_definition", "")),
        class_parameters=dict(getattr(info, "class_parameters", {})),
        indexes=[
            {
                "name": idx.name,
                "properties": idx.properties,
                "unique": idx.unique,
                "primary_key": idx.primary_key,
            }
            for idx in list(getattr(info, "indexes", []))
        ],
        source={
            "kind": source.kind if source is not None else "iris",
            "origin": source.origin if source is not None else info.classname,
        },
        scaffold_style=style,
        generated_at=timestamp_utc(),
        generated_region_hash=generated_hash,
        unsupported_features=[
            {"kind": item.kind, "name": item.name}
            for item in list(getattr(info, "unsupported_features", []))
        ],
    )
    write_lockfile(
        lockfile_path_for_class(state_root, info.classname),
        lockfile,
    )
    return output_path


def render_model(
    info: Any,
    *,
    style: str = "plan-c",
    class_map: dict[str, Any] | None = None,
    output_path: str | Path | None = None,
    state_root: str | Path = STATE_DIR,
) -> str:
    """Render the generated section for a scaffolded model."""
    class_map = class_map or {info.classname: info}
    lines: list[str] = [GENERATED_START]
    imports = _render_imports(info, style=style, class_map=class_map)
    lines.extend(imports)
    if imports:
        lines.append("")

    base_class = "IRISSerial" if getattr(info, "super", "") == "%SerialObject" else "IRISModel"
    class_name = python_class_name(info.classname)
    lines.append(f"class {class_name}({base_class}):")
    lines.append(f'    _iris_classname = "{info.classname}"')
    lines.append('    _iris_storage_mode = "preserve"')
    lockfile_ref = _render_lockfile_reference(
        info.classname,
        output_path=output_path,
        state_root=state_root,
    )
    lines.append(
        f'    _iris_lockfile_path = "{lockfile_ref}"'
    )

    if getattr(info, "super", "") not in {"", "%Persistent", "%SerialObject"}:
        lines.append(f'    # Preserved IRIS superclass in sidecar: {getattr(info, "super", "")}')

    if style == "plan-a":
        lines.append(GENERATED_END)
        return "\n".join(lines)

    lines.append("")
    props = list(getattr(info, "properties", []))
    rels = list(getattr(info, "relationships", []))
    if not props and not rels:
        lines.append("    pass")
    else:
        for prop in props:
            lines.append(_render_property_line(prop, class_map))
        if props and rels:
            lines.append("")
        for rel in rels:
            lines.append(_render_relationship_line(rel))
    lines.append(GENERATED_END)
    return "\n".join(lines)


def _render_imports(
    info: Any,
    *,
    style: str,
    class_map: dict[str, Any],
) -> list[str]:
    base_class = "IRISSerial" if getattr(info, "super", "") == "%SerialObject" else "IRISModel"
    names = {base_class}
    if style == "plan-c":
        names.add("field")
        if getattr(info, "relationships", []):
            names.add("relationship")
    lines = [f"from iris_orm import {', '.join(sorted(names))}"]
    annotations = [_annotation_for_property(prop, class_map) for prop in getattr(info, "properties", [])]
    if any(annotation == "Any" for annotation in annotations):
        lines.append("from typing import Any")
    if any(annotation.startswith("datetime.") for annotation in annotations):
        lines.append("import datetime")

    serial_imports = []
    for prop in getattr(info, "properties", []):
        related_info = class_map.get(prop.iris_type)
        if related_info is None or getattr(related_info, "super", "") != "%SerialObject":
            continue
        serial_imports.append(
            _render_relative_import(
                current_classname=info.classname,
                target_classname=prop.iris_type,
            )
        )
    for import_line in sorted(set(filter(None, serial_imports))):
        lines.append(import_line)
    return lines


def _render_relative_import(*, current_classname: str, target_classname: str) -> str:
    current_packages = [part.lower() for part in current_classname.split(".")[:-1]]
    target_packages = [part.lower() for part in target_classname.split(".")[:-1]]
    current_module = python_module_name(current_classname)
    target_module = python_module_name(target_classname)
    target_class = python_class_name(target_classname)

    common = 0
    for current_part, target_part in zip(current_packages, target_packages):
        if current_part != target_part:
            break
        common += 1

    up_levels = len(current_packages) - common
    down_parts = target_packages[common:]
    prefix = "." * (up_levels + 1)
    suffix_parts = down_parts + [target_module]
    suffix = ".".join(part for part in suffix_parts if part)
    if suffix:
        return f"from {prefix}{suffix} import {target_class}"
    if target_module == current_module:
        return ""
    return f"from {prefix}{target_module} import {target_class}"


def _render_lockfile_reference(
    classname: str,
    *,
    output_path: str | Path | None,
    state_root: str | Path,
) -> str:
    if output_path is None:
        return lockfile_path_for_class(state_root, classname).as_posix()
    output_dir = Path(output_path).parent
    target = lockfile_path_for_class(state_root, classname)
    rel = Path(os.path.relpath(target, output_dir))
    return rel.as_posix()


def _render_property_line(prop: PropertyInfo, class_map: dict[str, Any]) -> str:
    annotation = _annotation_for_property(prop, class_map)
    args = []
    if prop.required:
        args.append("required=True")
    if prop.maxlen is not None:
        args.append(f"maxlen={prop.maxlen}")
    if prop.collection:
        args.append(f'collection="{prop.collection}"')
    if prop.description:
        args.append(f"description={prop.description!r}")
    default_literal = _literal_default(prop.default)
    if default_literal is not None:
        args.append(f"default={default_literal}")
    if prop.iris_type.startswith("%") is False or prop.iris_type not in _KNOWN_IRIS_TYPES:
        args.append(f'iris_type="{prop.iris_type}"')
    joined = ", ".join(args)
    return f"    {prop.name}: {annotation} = field({joined})" if joined else f"    {prop.name}: {annotation} = field()"


def _render_relationship_line(rel: RelationshipInfo) -> str:
    args = [
        f'"{rel.related_classname}"',
        f'inverse="{rel.inverse}"',
        f'cardinality="{rel.cardinality}"',
    ]
    if rel.description:
        args.append(f"description={rel.description!r}")
    return f"    {rel.name} = relationship({', '.join(args)})"


_KNOWN_IRIS_TYPES = {
    "%String",
    "%Library.String",
    "%Integer",
    "%Library.Integer",
    "%Float",
    "%Library.Float",
    "%Numeric",
    "%Double",
    "%Library.Double",
    "%Boolean",
    "%Library.Boolean",
    "%Date",
    "%Library.Date",
    "%Time",
    "%Library.Time",
    "%TimeStamp",
    "%Library.TimeStamp",
    "%PosixTime",
    "%List",
    "%Library.List",
    "%Stream.GlobalCharacter",
    "%Library.GlobalCharacter",
    "%Stream.GlobalBinary",
    "%Library.GlobalBinary",
}


def _annotation_for_property(prop: PropertyInfo, class_map: dict[str, Any]) -> str:
    related_info = class_map.get(prop.iris_type)
    if related_info is not None and getattr(related_info, "super", "") == "%SerialObject":
        return python_class_name(prop.iris_type)
    annotation = iris_type_to_annotation(prop.iris_type)
    if annotation == "Any":
        return "Any"
    return annotation.removeprefix("Optional[").removesuffix("]")


def _literal_default(value: str) -> str | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = ast.literal_eval(raw)
    except Exception:
        lowered = raw.lower()
        if lowered in {"true", "false"}:
            return "True" if lowered == "true" else "False"
        if re.fullmatch(r"-?\d+", raw):
            return raw
        if re.fullmatch(r"-?\d+\.\d+", raw):
            return raw
        return None
    return repr(parsed)


def _assemble_scaffold_file(generated_block: str, manual_content: str) -> str:
    lines = [
        "# Auto-generated by iris_orm.scaffold. Manual edits outside the generated block are preserved.",
        "from __future__ import annotations",
        "",
        generated_block,
    ]
    if manual_content.strip():
        lines.extend(["", manual_content.rstrip()])
    else:
        lines.extend(["", "# Add manual helpers below."])
    return "\n".join(lines) + "\n"


def _read_manual_content(path: str | Path) -> str:
    content = Path(path).read_text(encoding="utf-8")
    if GENERATED_START not in content or GENERATED_END not in content:
        raise LockfileDriftError(
            f"{path} is missing iris_orm generated markers; refusing to overwrite"
        )
    _, tail = content.split(GENERATED_END, 1)
    return tail.lstrip("\n")


def _assert_refresh_safe(
    output_path: str | Path,
    state_root: str | Path,
    classname: str,
    generated_hash: str | None,
) -> None:
    lock_path = lockfile_path_for_class(state_root, classname)
    if not lock_path.exists():
        raise LockfileDriftError(f"Missing scaffold lockfile: {lock_path}")
    from .lockfile import load_lockfile  # noqa: PLC0415

    lockfile = load_lockfile(lock_path)
    current_block = extract_generated_block(Path(output_path).read_text(encoding="utf-8"))
    current_hash = compute_hash(current_block)
    if lockfile.generated_region_hash and current_hash != lockfile.generated_region_hash:
        raise LockfileDriftError(
            f"Generated block for {classname} was modified; refusing to refresh"
        )
    if generated_hash is not None and current_hash == generated_hash:
        return


def extract_generated_block(content: str) -> str:
    """Return the generated block from a scaffolded file."""
    if GENERATED_START not in content or GENERATED_END not in content:
        raise LockfileDriftError("Missing generated markers")
    start_idx = content.index(GENERATED_START)
    end_idx = content.index(GENERATED_END) + len(GENERATED_END)
    return content[start_idx:end_idx]


def python_path_for_class(output_root: str | Path, classname: str) -> Path:
    parts = classname.split(".")
    module_name = python_module_name(classname)
    if len(parts) == 1:
        return Path(output_root) / f"{module_name}.py"
    package_parts = [part.lower() for part in parts[:-1]]
    return Path(output_root).joinpath(*package_parts, f"{module_name}.py")


def python_module_name(classname: str) -> str:
    return _snake_case(classname.split(".")[-1])


def python_class_name(classname: str) -> str:
    return classname.split(".")[-1]


def _snake_case(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = value.replace("-", "_")
    return value.lower()


def _ensure_package_init(directory: Path, *, stop_at: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    current = directory
    while True:
        init_path = current / "__init__.py"
        if not init_path.exists():
            init_path.write_text("", encoding="utf-8")
        if current == stop_at or current.parent == current or current.name == "":
            break
        current = current.parent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m iris_orm.scaffold",
        description="Scaffold Python ORM models and sidecar lockfiles from IRIS classes.",
    )
    parser.add_argument("--out", required=True, metavar="PATH", help="Output root for generated Python modules.")
    parser.add_argument(
        "--state-dir",
        default=STATE_DIR,
        metavar="PATH",
        help=f"Directory for scaffold lockfiles (default: {STATE_DIR})",
    )
    parser.add_argument(
        "--style",
        default="plan-c",
        choices=["plan-a", "plan-c"],
        help="Scaffold style (default: plan-c)",
    )
    parser.add_argument(
        "--module",
        default=None,
        metavar="MODULE",
        help="Optional Python module to import before running.",
    )

    sub = parser.add_subparsers(dest="command")
    sub.required = False
    refresh = sub.add_parser("refresh", help="Refresh existing scaffold output.")
    refresh.add_argument("--from-iris", dest="from_iris", default=None, metavar="PATTERN")
    refresh.add_argument("--from-cls", dest="from_cls", default=None, metavar="PATH")

    parser.add_argument("--from-iris", dest="from_iris", default=None, metavar="PATTERN")
    parser.add_argument("--from-cls", dest="from_cls", default=None, metavar="PATH")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.module:
        importlib.import_module(args.module)

    refresh = args.command == "refresh"
    from_iris = getattr(args, "from_iris", None)
    from_cls = getattr(args, "from_cls", None)
    if bool(from_iris) == bool(from_cls):
        parser.error("Provide exactly one of --from-iris or --from-cls.")

    if from_iris:
        paths = scaffold_from_iris(
            from_iris,
            args.out,
            style=args.style,
            refresh=refresh,
            state_root=args.state_dir,
        )
    else:
        paths = scaffold_from_cls(
            from_cls,
            args.out,
            style=args.style,
            refresh=refresh,
            state_root=args.state_dir,
        )

    for path in paths:
        print(f"Written: {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
