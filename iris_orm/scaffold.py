from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .runtime import EmbeddedRuntime
from .schema import (
    SchemaClass,
    SchemaCompiler,
    SchemaIndex,
    SchemaProperty,
    SUPPORTED_PROPERTY_PARAMETERS,
    normalize_superclasses,
    python_default_source,
)
from .storage import StorageDefinition


def scaffold_from_iris(
    pattern: str,
    output_root: str | Path,
    *,
    style: str = "observe",
    conn: Any | None = None,
) -> list[Path]:
    runtime = conn or EmbeddedRuntime()
    classnames = runtime.list_classes(pattern)
    classes = SchemaCompiler(runtime).catalog_from_iris(classnames)
    return [write_scaffold(item, output_root=output_root, style=style) for item in classes]


def scaffold_from_cls(
    cls_root: str | Path,
    output_root: str | Path,
    *,
    style: str = "observe",
) -> list[Path]:
    root = Path(cls_root)
    classes = [parse_cls(path.read_text(encoding="utf-8"), source_path=str(path)) for path in sorted(root.rglob("*.cls"))]
    return [write_scaffold(item, output_root=output_root, style=style) for item in classes]


def parse_cls(source: str, *, source_path: str = "") -> SchemaClass:
    header = re.search(r"Class\s+([A-Za-z0-9_.%]+)\s+Extends\s+([^\{\[]+?)(?:\s*\[|\s*\{)", source, re.DOTALL)
    if not header:
        raise ValueError("Unable to parse class header")
    classname = header.group(1)
    superclasses = normalize_superclasses(header.group(2))

    properties: list[SchemaProperty] = []
    for match in re.finditer(
        r"Property\s+([A-Za-z0-9_%]+)\s+As\s+([A-Za-z0-9_.%]+)(?:\(([^)]*)\))?\s*(?:\[(.*?)\])?\s*;",
        source,
        re.DOTALL,
    ):
        name, iris_type, args, opts = match.groups()
        maxlen = None
        required = False
        default = ""
        description = ""
        property_parameters: dict[str, str] = {}
        if args:
            maxlen_match = re.search(r"MAXLEN\s*=\s*([0-9]+)", args, re.IGNORECASE)
            if maxlen_match:
                maxlen = int(maxlen_match.group(1))
            property_parameters = _parse_property_parameters(args)
        if opts:
            required = "required" in opts.lower()
            default_match = re.search(r"InitialExpression\s*=\s*([^,\]]+)", opts, re.IGNORECASE)
            if default_match:
                value = default_match.group(1).strip()
                if value == "{}":
                    value = ""
                default = value if value != '""' else ""
        properties.append(
            SchemaProperty(
                name=name,
                iris_type=iris_type,
                required=required,
                default=default,
                maxlen=maxlen,
                description=description,
                parameters=property_parameters,
            )
        )

    indexes: list[SchemaIndex] = []
    for match in re.finditer(
        r"Index\s+([A-Za-z0-9_%]+)\s+On\s+\(([^)]*)\)\s*(?:\[(.*?)\])?\s*;",
        source,
        re.DOTALL,
    ):
        name, props, opts = match.groups()
        opts_lower = (opts or "").lower()
        indexes.append(
            SchemaIndex(
                name=name,
                properties=",".join(item.strip() for item in props.split(",") if item.strip()),
                unique="unique" in opts_lower,
                primary_key="primarykey" in opts_lower or "primary_key" in opts_lower,
            )
        )

    parameters: dict[str, str] = {}
    for match in re.finditer(r"Parameter\s+([A-Za-z0-9_%]+)\s*=\s*([^;]+);", source):
        parameters[match.group(1)] = match.group(2).strip().strip('"')

    storage = parse_storage_block(source)
    return SchemaClass(
        name=classname,
        superclasses=superclasses,
        properties=tuple(properties),
        indexes=tuple(indexes),
        parameters=parameters,
        storage=storage,
        source={"kind": "cls", "path": source_path},
    )


def parse_storage_block(source: str) -> StorageDefinition | None:
    match = re.search(r"Storage\s+([A-Za-z0-9_%]+)\s*\{(.*)\n\}", source, re.DOTALL)
    if not match:
        return None
    name, body = match.groups()

    def extract(tag: str) -> str:
        found = re.search(rf"<{tag}>(.*?)</{tag}>", body, re.DOTALL)
        return found.group(1).strip() if found else ""

    data_items: list[dict[str, Any]] = []
    for data_match in re.finditer(r'<Data name="([^"]+)">(.*?)</Data>', body, re.DOTALL):
        data_name, data_body = data_match.groups()
        structure = extract_from(data_body, "Structure")
        values: list[dict[str, str]] = []
        for value_match in re.finditer(r'<Value name="([^"]+)">\s*<Value>(.*?)</Value>\s*</Value>', data_body, re.DOTALL):
            values.append({"name": value_match.group(1), "value": value_match.group(2).strip()})
        data_items.append({"name": data_name, "structure": structure, "values": values})

    properties = _parse_storage_named_sections(body, "Property")
    sql_maps = _parse_storage_named_sections(body, "SQLMap")

    storage: dict[str, Any] = {
        "name": name,
        "counter_location": extract("CounterLocation"),
        "type": extract("Type"),
        "data_location": extract("DataLocation"),
        "default_data": extract("DefaultData"),
        "description": extract("Description"),
        "extent_location": extract("ExtentLocation"),
        "extent_size": extract("ExtentSize"),
        "id_expression": extract("IdExpression"),
        "id_function": extract("IdFunction"),
        "id_location": extract("IdLocation"),
        "index_location": extract("IndexLocation"),
        "sql_child_sub": extract("SqlChildSub"),
        "sql_id_expression": extract("SqlIdExpression"),
        "sql_row_id_name": extract("SqlRowIdName"),
        "sql_row_id_property": extract("SqlRowIdProperty"),
        "stream_location": extract("StreamLocation"),
        "version_location": extract("VersionLocation"),
        "data": data_items,
        "properties": properties,
        "sql_maps": sql_maps,
    }
    return StorageDefinition.from_dict({key: value for key, value in storage.items() if value != "" and value != [] and value is not None})


def render_model(schema_class: SchemaClass, *, style: str = "observe") -> str:
    mode = normalize_style(style)
    imports = ["from typing import Annotated"]
    extra_imports: list[str] = []
    iris_types = {prop.iris_type for prop in schema_class.properties}
    if iris_types & {"%Date", "%Time", "%TimeStamp"}:
        extra_imports.append("from datetime import date, datetime, time")
    if "%Decimal" in iris_types:
        extra_imports.append("from decimal import Decimal")
    iris_imports = ["Field", "IRISModel"]
    if schema_class.indexes:
        iris_imports.append("Index")
    if schema_class.storage is not None:
        iris_imports.append("StorageDefinition")
        if schema_class.storage.data:
            iris_imports.append("StorageData")
        if schema_class.storage.properties:
            iris_imports.append("StorageProperty")
        if schema_class.storage.sql_maps:
            iris_imports.append("StorageSQLMap")
    imports.extend(extra_imports)
    imports.append(f"from iris_orm import {', '.join(sorted(set(iris_imports)))}")
    lines = [*imports, ""]
    lines.append(f"class {schema_class.name.split('.')[-1]}(IRISModel):")
    lines.append("")
    meta_lines = _render_meta_block(schema_class, mode=mode, indent="    ")
    if meta_lines:
        lines.extend(meta_lines)
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
        if prop.parameters:
            parts.append(f"parameters={dict(sorted(prop.parameters.items()))!r}")
        parts.append(f'iris_type="{prop.iris_type}"')
        lines.append(f"    {prop.name}: Annotated[{_annotation(prop.iris_type)}, Field({', '.join(parts)})]")
    return "\n".join(lines) + "\n"


def write_scaffold(schema_class: SchemaClass, *, output_root: str | Path, style: str = "observe") -> Path:
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"{schema_class.name.split('.')[-1].lower()}.py"
    output_path.write_text(render_model(schema_class, style=style), encoding="utf-8")
    return output_path


def normalize_style(style: str) -> str:
    normalized = str(style or "observe").strip().lower()
    if normalized not in {"observe", "replace", "extend"}:
        raise ValueError(f"Unsupported scaffold style: {style!r}. Valid styles: 'observe', 'replace', 'extend'.")
    return normalized


def _annotation(iris_type: str) -> str:
    mapping = {
        "%String": "str",
        "%Integer": "int",
        "%Float": "float",
        "%Decimal": "Decimal",
        "%Boolean": "bool",
        "%Date": "date",
        "%Time": "time",
        "%TimeStamp": "datetime",
        "%DynamicObject": "dict",
        "%DynamicArray": "list",
        "%Stream.GlobalBinary": "bytes",
    }
    return mapping.get(iris_type, "str")


def extract_from(source: str, tag: str) -> str:
    found = re.search(rf"<{tag}>(.*?)</{tag}>", source, re.DOTALL)
    return found.group(1).strip() if found else ""


def _parse_storage_named_sections(source: str, tag: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for match in re.finditer(rf'<{tag} name="([^"]+)">(.*?)</{tag}>', source, re.DOTALL):
        name, body = match.groups()
        item: dict[str, Any] = {"name": name}
        for child_tag, value in re.findall(r"<([A-Za-z0-9_]+)>(.*?)</\1>", body, re.DOTALL):
            normalized = _tag_to_key(child_tag)
            item[normalized] = value.strip()
        items.append(item)
    return items


def _tag_to_key(tag: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", tag).lower()


def _render_storage_definition(storage: StorageDefinition, *, indent: str) -> list[str]:
    lines = [f"{indent}storage = StorageDefinition("]
    nested_indent = indent + "    "
    scalar_fields = storage.to_dict()
    for key in [
        "name",
        "counter_location",
        "data_location",
        "default_data",
        "description",
        "extent_location",
        "extent_size",
        "id_expression",
        "id_function",
        "id_location",
        "index_location",
        "sql_child_sub",
        "sql_id_expression",
        "sql_row_id_name",
        "sql_row_id_property",
        "stream_location",
        "type",
        "version_location",
    ]:
        if key in scalar_fields:
            lines.append(f"{nested_indent}{key}={scalar_fields[key]!r},")
    if storage.data:
        lines.append(f"{nested_indent}data=(")
        for item in storage.data:
            lines.append(
                f"{nested_indent}    StorageData(name={item.name!r}, structure={item.structure!r}, values={item.values!r}),"
            )
        lines.append(f"{nested_indent}),")
    if storage.properties:
        lines.append(f"{nested_indent}properties=(")
        for item in storage.properties:
            args = ", ".join(f"{key}={value!r}" for key, value in item.to_dict().items())
            lines.append(f"{nested_indent}    StorageProperty({args}),")
        lines.append(f"{nested_indent}),")
    if storage.sql_maps:
        lines.append(f"{nested_indent}sql_maps=(")
        for item in storage.sql_maps:
            args = ", ".join(f"{key if key != 'global' else 'global_'}={value!r}" for key, value in item.to_dict().items())
            lines.append(f"{nested_indent}    StorageSQLMap({args}),")
        lines.append(f"{nested_indent}),")
    lines.append(f"{indent})")
    return lines


def _render_meta_block(schema_class: SchemaClass, *, mode: str, indent: str) -> list[str]:
    lines = [f"{indent}class Meta:"]
    body_indent = indent + "    "
    lines.append(f'{body_indent}classname = "{schema_class.name}"')
    lines.append(f'{body_indent}mode = "{mode}"')
    if schema_class.superclasses != ("%Persistent",):
        if len(schema_class.superclasses) == 1:
            lines.append(f'{body_indent}superclasses = "{schema_class.superclasses[0]}"')
        else:
            lines.append(f"{body_indent}superclasses = {list(schema_class.superclasses)!r}")
    if schema_class.storage is not None:
        lines.extend(_render_storage_definition(schema_class.storage, indent=body_indent))
    if schema_class.indexes:
        lines.append(f"{body_indent}indexes = [")
        for item in schema_class.indexes:
            args = [f"{item.name!r}", f"properties={item.properties!r}"]
            if item.unique:
                args.append("unique=True")
            if item.primary_key:
                args.append("primary_key=True")
            lines.append(f"{body_indent}    Index({', '.join(args)}),")
        lines.append(f"{body_indent}]")
    if schema_class.parameters:
        lines.append(f"{body_indent}parameters = {dict(sorted(schema_class.parameters.items()))!r}")
    return lines


def _parse_property_parameters(args: str) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for name in SUPPORTED_PROPERTY_PARAMETERS:
        match = re.search(rf"{name}\s*=\s*(\"[^\"]*\"|'[^']*'|[^,]+)", args, re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        parameters[name] = value
    return parameters
