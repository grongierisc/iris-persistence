from __future__ import annotations

import re
import warnings as py_warnings
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from iris_persistence.field_utils import (
    collection_kind_from_iris_type,
    is_application_iris_class,
)
from iris_persistence.runtime import get_runtime
from iris_persistence.scaffold_reader import (
    STORAGE_SCALAR_KEYS,
    ScaffoldResult,
    ScaffoldWarning,
    _CompiledClass,
    _CompiledDictionaryReader,
    _CompiledIndex,
    _CompiledParameter,
    _CompiledProperty,
    _CompiledStorage,
)
from iris_persistence.types import (
    STORAGE_PROPERTY_SCALAR_KEYS,
    STORAGE_SQL_MAP_DATA_SCALAR_KEYS,
    STORAGE_SQL_MAP_ROW_ID_SPEC_SCALAR_KEYS,
    STORAGE_SQL_MAP_SCALAR_KEYS,
    STORAGE_SQL_MAP_SUB_ACCESS_VAR_SCALAR_KEYS,
    STORAGE_SQL_MAP_SUB_INVALID_CONDITION_SCALAR_KEYS,
    STORAGE_SQL_MAP_SUB_SCALAR_KEYS,
    StorageData,
    StorageIndex,
    StorageProperty,
    StorageSQLMap,
)


def _python_default_literal(prop: _CompiledProperty) -> tuple[str | None, str | None]:
    default = prop.default
    if default is None:
        return (None, None)
    if prop.iris_type == "%Library.Boolean" and default in {"1", "0"}:
        literal = "True" if default == "1" else "False"
        return (f"default={literal}", literal)
    if prop.python_type == "int" and re.fullmatch(r"-?\d+", default):
        return (f"default={default}", default)
    if prop.python_type == "float" and re.fullmatch(r"-?(?:\d+\.\d*|\d*\.\d+|\d+)", default):
        return (f"default={default}", default)
    if default.startswith('"') and default.endswith('"'):
        value = default[1:-1].replace('""', '"')
        literal = repr(value)
        return (f"default={literal}", literal)
    return (None, None)


def _safe_identifier_part(part: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z]+", "_", part).strip("_")
    return cleaned or "model"


def _camel_case(parts: list[str]) -> str:
    tokens: list[str] = []
    for part in parts:
        cleaned = _safe_identifier_part(part)
        if not cleaned:
            continue
        for token in cleaned.split("_"):
            if not token:
                continue
            tokens.append(token[:1].upper() + token[1:])
    return "".join(tokens)


def _snake_case(parts: list[str]) -> str:
    cleaned_parts = [cleaned.lower() for part in parts if (cleaned := _safe_identifier_part(part))]
    return "_".join(cleaned_parts)


def _assign_generated_names(
    classnames: list[str],
    preferred: list[str],
    formatter: Any,
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    used: set[str] = set()
    ordered = preferred + [
        classname for classname in sorted(classnames) if classname not in preferred
    ]

    for classname in ordered:
        parts = classname.split(".")
        for depth in range(1, len(parts) + 1):
            candidate = formatter(parts[-depth:])
            if candidate and candidate not in used:
                resolved[classname] = candidate
                used.add(candidate)
                break
        else:
            candidate = formatter(parts)
            resolved[classname] = candidate
            used.add(candidate)

    return resolved


def _collect_classes(
    reader: _CompiledDictionaryReader,
    pattern: str,
    include_related: bool,
) -> tuple[list[_CompiledClass], dict[str, list[_CompiledProperty]], list[str]]:
    seed_classes = reader.list_classes(pattern)
    seed_names = [item.name for item in seed_classes]
    classes_by_name = {item.name: item for item in seed_classes}
    properties_by_class: dict[str, list[_CompiledProperty]] = {}

    if not include_related:
        return (seed_classes, properties_by_class, seed_names)

    queue = list(seed_names)
    visited = set()
    while queue:
        classname = queue.pop(0)
        if classname in visited:
            continue
        visited.add(classname)
        properties = properties_by_class.setdefault(classname, reader.list_properties(classname))
        for prop in properties:
            if not is_application_iris_class(prop.iris_type):
                continue
            if prop.iris_type in classes_by_name:
                if prop.iris_type not in visited:
                    queue.append(prop.iris_type)
                continue
            class_info = reader.get_class(prop.iris_type)
            if class_info is None:
                continue
            classes_by_name[class_info.name] = class_info
            queue.append(class_info.name)

    return (
        sorted(classes_by_name.values(), key=lambda item: item.name),
        properties_by_class,
        seed_names,
    )


def _render_call(
    class_name: str,
    item: Any,
    fields: tuple[str, ...],
    *,
    aliases: dict[str, str] | None = None,
    true_flags: tuple[str, ...] = (),
) -> str:
    args = [f"name={item.name!r}"]
    aliases = aliases or {}
    for field_name in fields:
        attr_name = aliases.get(field_name, field_name)
        value = getattr(item, attr_name)
        if field_name in true_flags:
            if value:
                args.append(f"{field_name}=True")
        elif value is not None:
            if isinstance(value, bool):
                args.append(f"{field_name}={'True' if value else 'False'}")
            else:
                args.append(f"{field_name}={value!r}")
    return f"{class_name}({', '.join(args)})"


def _double_quoted_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_arg(name: str, value: Any, style: str) -> str | None:
    if style == "true":
        return f"{name}=True" if value else None
    if style == "false":
        return f"{name}=False" if value is False else None
    if value is None or value == "":
        return None
    if style == "double":
        value = _double_quoted_literal(str(value))
    elif style == "raw":
        value = str(value)
    elif isinstance(value, bool):
        value = "True" if value else "False"
    else:
        value = repr(value)
    return f"{name}={value}"


def _render_args(item: Any, specs: tuple[tuple[str, str, str], ...]) -> list[str]:
    return [
        arg
        for attr_name, arg_name, style in specs
        if (arg := _format_arg(arg_name, getattr(item, attr_name), style)) is not None
    ]


def _render_property_type(
    prop: _CompiledProperty,
    python_class_names: dict[str, str],
) -> str:
    if prop.iris_type in python_class_names:
        base_type = python_class_names[prop.iris_type]
    elif is_application_iris_class(prop.iris_type):
        base_type = "Any"
    else:
        base_type = prop.python_type

    collection = prop.collection or collection_kind_from_iris_type(prop.iris_type)
    if collection == "list":
        return f"list[{base_type}]"
    if collection == "array":
        return f"dict[str, {base_type}]"
    return base_type


@dataclass(frozen=True)
class _RenderNode:
    class_name: str
    fields: tuple[str, ...]
    true_flags: tuple[str, ...] = ()
    children: tuple[tuple[str, "_RenderNode"], ...] = ()


def _render_node(item: Any, spec: _RenderNode) -> list[str]:
    populated_children = [
        (attr_name, child_spec, getattr(item, attr_name))
        for attr_name, child_spec in spec.children
        if getattr(item, attr_name)
    ]
    call = _render_call(
        spec.class_name,
        item,
        spec.fields,
        true_flags=spec.true_flags,
    )
    if not populated_children:
        return [call]
    lines = [call[:-1] + ","]
    for attr_name, child_spec, children in populated_children:
        lines.append(f"    {attr_name}=(")
        for child in children:
            rendered = _render_node(child, child_spec)
            lines.extend(f"        {line}" for line in rendered[:-1])
            lines.append(f"        {rendered[-1]},")
        lines.append("    ),")
    lines.append(")")
    return lines


_ACCESS_VAR_NODE = _RenderNode(
    "StorageSQLMapSubAccessVar", STORAGE_SQL_MAP_SUB_ACCESS_VAR_SCALAR_KEYS
)
_INVALID_CONDITION_NODE = _RenderNode(
    "StorageSQLMapSubInvalidCondition", STORAGE_SQL_MAP_SUB_INVALID_CONDITION_SCALAR_KEYS
)
_SUBSCRIPT_NODE = _RenderNode(
    "StorageSQLMapSub",
    STORAGE_SQL_MAP_SUB_SCALAR_KEYS,
    children=(("access_vars", _ACCESS_VAR_NODE), ("invalid_conditions", _INVALID_CONDITION_NODE)),
)
_SQL_MAP_NODE = _RenderNode(
    "StorageSQLMap",
    STORAGE_SQL_MAP_SCALAR_KEYS,
    true_flags=("conditional_with_host_vars",),
    children=(
        ("data", _RenderNode("StorageSQLMapData", STORAGE_SQL_MAP_DATA_SCALAR_KEYS)),
        (
            "row_id_specs",
            _RenderNode("StorageSQLMapRowIdSpec", STORAGE_SQL_MAP_ROW_ID_SPEC_SCALAR_KEYS),
        ),
        ("subscripts", _SUBSCRIPT_NODE),
    ),
)


def _render_storage_sql_map(item: StorageSQLMap) -> list[str]:
    return _render_node(item, _SQL_MAP_NODE)


_STORAGE_INDEX_ARG_SPECS: tuple[tuple[str, str, str], ...] = (
    ("name", "name", "double"),
    ("location", "location", "double"),
    ("small_chunk_size", "small_chunk_size", "double"),
)


def _has_class_metadata(class_info: _CompiledClass) -> bool:
    return any(
        (
            class_info.description is not None,
            class_info.deprecated,
            class_info.final,
            class_info.sql_table_name is not None,
            class_info.procedure_block,
        )
    )


def _render_model_declaration(
    class_info: _CompiledClass,
    class_name: str,
) -> tuple[str, bool]:
    if class_info.superclasses == "%Persistent":
        return (f"class {class_name}(Model, persistent=True):", False)
    if class_info.superclasses == "%SerialObject":
        return (f"class {class_name}(Model, serial=True):", False)
    return (f"class {class_name}(Model):", class_info.superclasses is not None)


def _collect_model_imports(
    class_info: _CompiledClass,
    properties: list[_CompiledProperty],
    indexes: list[_CompiledIndex],
    storage: _CompiledStorage | None,
    storage_data: list[StorageData],
    storage_indices: list[StorageIndex],
    storage_properties: list[StorageProperty],
    storage_sql_maps: list[StorageSQLMap],
    python_class_names: dict[str, str],
    module_names: dict[str, str],
) -> tuple[list[str], set[str], bool, set[str]]:
    custom_imports: list[str] = []
    typing_imports: set[str] = set()
    needs_datetime = False

    for prop in properties:
        if prop.iris_type in python_class_names and prop.iris_type != class_info.name:
            custom_imports.append(
                f"from {module_names[prop.iris_type]} import {python_class_names[prop.iris_type]}"
            )
        rendered_type = _render_property_type(prop, python_class_names)
        if "Any" in rendered_type:
            typing_imports.add("Any")
        if "datetime." in rendered_type:
            needs_datetime = True

    iris_imports = {"Field", "Model"}
    if _has_class_metadata(class_info):
        iris_imports.add("ClassMetadata")
    if indexes:
        iris_imports.add("Index")
    if storage is not None:
        iris_imports.add("StorageDefinition")
    if storage_data:
        iris_imports.add("StorageData")
    if storage_indices:
        iris_imports.add("StorageIndex")
    if storage_properties:
        iris_imports.add("StorageProperty")
    if storage_sql_maps:
        iris_imports.update(
            {
                "StorageSQLMap",
                "StorageSQLMapData",
                "StorageSQLMapRowIdSpec",
                "StorageSQLMapSub",
                "StorageSQLMapSubAccessVar",
                "StorageSQLMapSubInvalidCondition",
            }
        )

    return (sorted(set(custom_imports)), typing_imports, needs_datetime, iris_imports)


_PROPERTY_FIELD_ARG_SPECS: tuple[tuple[str, str, str], ...] = (
    ("required", "required", "true"),
    ("maxlen", "max_length", "raw"),
    ("readonly", "readonly", "true"),
    ("collection", "collection", "repr"),
    ("sql_field_name", "sql_field_name", "repr"),
    ("identity", "identity", "true"),
    ("relationship", "relationship", "repr"),
    ("on_delete", "on_delete", "repr"),
    ("inverse", "inverse", "repr"),
    ("transient", "transient", "true"),
    ("storable", "storable", "false"),
    ("multi_dimensional", "multi_dimensional", "true"),
    ("sql_list_delimiter", "sql_list_delimiter", "repr"),
    ("sql_list_type", "sql_list_type", "repr"),
    ("sql_compute_code", "sql_compute_code", "repr"),
    ("sql_compute_on_change", "sql_compute_on_change", "repr"),
    ("sql_computed", "sql_computed", "true"),
)


def _render_property_field(
    prop: _CompiledProperty,
    python_class_names: dict[str, str],
) -> str:
    type_name = _render_property_type(prop, python_class_names)
    field_args = [f'iris_type="{prop.iris_type}"']
    for attr_name, arg_name, style in _PROPERTY_FIELD_ARG_SPECS:
        if attr_name == "sql_field_name" and prop.sql_field_name == prop.name:
            continue
        arg = _format_arg(arg_name, getattr(prop, attr_name), style)
        if arg is not None:
            field_args.append(arg)
    default_arg, _default_value = _python_default_literal(prop)
    if default_arg:
        field_args.append(default_arg)
    elif prop.default is not None:
        field_args.append(f"initial_expression={prop.default!r}")
    if not prop.required and default_arg is None:
        field_args.append("default=None")

    annotation = type_name if prop.required else f"{type_name} | None"
    return f"    {prop.name}: {annotation} = Field({', '.join(field_args)})"


_CLASS_METADATA_ARG_SPECS: tuple[tuple[str, str, str], ...] = (
    ("description", "description", "double"),
    ("deprecated", "deprecated", "true"),
    ("final", "final", "true"),
    ("sql_table_name", "sql_table_name", "double"),
    ("procedure_block", "procedure_block", "true"),
)


def _render_class_metadata_lines(class_info: _CompiledClass) -> list[str]:
    lines = ["        metadata = ClassMetadata("]
    lines.extend(
        f"            {arg}," for arg in _render_args(class_info, _CLASS_METADATA_ARG_SPECS)
    )
    lines.append("        )")
    return lines


def _render_parameter_lines(parameters: list[_CompiledParameter]) -> list[str]:
    lines = ["        parameters = {"]
    lines.extend(f'            "{param.name}": "{param.default}",' for param in parameters)
    lines.append("        }")
    return lines


def _render_index_lines(indexes: list[_CompiledIndex]) -> list[str]:
    lines = ["        indexes = ["]
    lines.extend(
        "            "
        + f'Index("{index.name}", properties="{index.properties}", '
        + f"unique={'True' if index.unique else 'False'}"
        + (f', type="{index.index_type}"' if index.index_type else "")
        + (", primary_key=True" if index.primary_key else "")
        + "),"
        for index in indexes
    )
    lines.append("        ]")
    return lines


_STORAGE_PROPERTY_ARG_SPECS: tuple[tuple[str, str, str], ...] = (
    ("name", "name", "double"),
    ("average_field_size", "average_field_size", "double"),
    ("selectivity", "selectivity", "double"),
    ("outlier_selectivity", "outlier_selectivity", "double"),
    ("histogram", "histogram", "double"),
    ("child_block_count", "child_block_count", "double"),
    ("child_extent_size", "child_extent_size", "double"),
    ("bias_queries_as_outlier", "bias_queries_as_outlier", "repr"),
    ("stream_location", "stream_location", "double"),
)

_STORAGE_RENDER_KEYS = (*STORAGE_SCALAR_KEYS[1:], "type")


_STORAGE_DATA_ARG_SPECS: tuple[tuple[str, str, str], ...] = (
    ("name", "name", "double"),
    ("structure", "structure", "double"),
    ("attribute", "attribute", "repr"),
    ("subscript", "subscript", "repr"),
    ("values", "values", "repr"),
)


def _render_storage_lines(
    storage: _CompiledStorage,
    storage_data: list[StorageData],
    storage_indices: list[StorageIndex],
    storage_properties: list[StorageProperty],
    storage_sql_maps: list[StorageSQLMap],
) -> list[str]:
    lines = ["        storage = StorageDefinition("]
    for attr_name in _STORAGE_RENDER_KEYS:
        value = getattr(storage, attr_name)
        if value is not None:
            lines.append(f"            {attr_name}={_double_quoted_literal(value)},")

    if storage_data:
        lines.append("            data=(")
        for item in storage_data:
            lines.append("                StorageData(")
            lines.extend(
                f"                    {arg}," for arg in _render_args(item, _STORAGE_DATA_ARG_SPECS)
            )
            lines.append("                ),")
        lines.append("            ),")
    if storage_indices:
        lines.append("            indices=(")
        for storage_index in storage_indices:
            lines.append(
                "                StorageIndex("
                f"{', '.join(_render_args(storage_index, _STORAGE_INDEX_ARG_SPECS))}),"
            )
        lines.append("            ),")
    if storage_properties:
        lines.append("            properties=(")
        for storage_property in storage_properties:
            lines.append(
                "                StorageProperty("
                f"{', '.join(_render_args(storage_property, _STORAGE_PROPERTY_ARG_SPECS))}),"
            )
        lines.append("            ),")
    if storage_sql_maps:
        lines.append("            sql_maps=(")
        for storage_sql_map in storage_sql_maps:
            rendered_map = _render_storage_sql_map(storage_sql_map)
            lines.append(f"                {rendered_map[0]}")
            for map_line in rendered_map[1:-1]:
                lines.append(f"                {map_line}")
            lines.append(f"                {rendered_map[-1]},")
        lines.append("            ),")
    lines.append("        )")
    return lines


def _render_meta_lines(
    class_info: _CompiledClass,
    mode: str,
    emit_meta_superclasses: bool,
    parameters: list[_CompiledParameter],
    indexes: list[_CompiledIndex],
    storage: _CompiledStorage | None,
    storage_data: list[StorageData],
    storage_indices: list[StorageIndex],
    storage_properties: list[StorageProperty],
    storage_sql_maps: list[StorageSQLMap],
) -> list[str]:
    lines = [
        "",
        "    class Meta:",
        f'        classname = "{class_info.name}"',
        f'        mode = "{mode}"',
    ]
    if emit_meta_superclasses:
        lines.append(f'        superclasses = "{class_info.superclasses}"')
    if _has_class_metadata(class_info):
        lines.extend(_render_class_metadata_lines(class_info))
    if parameters:
        lines.extend(_render_parameter_lines(parameters))
    if indexes:
        lines.extend(_render_index_lines(indexes))
    if storage:
        lines.extend(
            _render_storage_lines(
                storage,
                storage_data,
                storage_indices,
                storage_properties,
                storage_sql_maps,
            )
        )
    return lines


def _render_model(
    class_info: _CompiledClass,
    properties: list[_CompiledProperty],
    mode: str,
    parameters: list[_CompiledParameter],
    indexes: list[_CompiledIndex],
    storage: _CompiledStorage | None,
    storage_data: list[StorageData],
    storage_indices: list[StorageIndex],
    storage_properties: list[StorageProperty],
    storage_sql_maps: list[StorageSQLMap],
    python_class_names: dict[str, str],
    module_names: dict[str, str],
) -> str:
    custom_imports, typing_imports, needs_datetime, iris_imports = _collect_model_imports(
        class_info,
        properties,
        indexes,
        storage,
        storage_data,
        storage_indices,
        storage_properties,
        storage_sql_maps,
        python_class_names,
        module_names,
    )

    model_declaration, emit_meta_superclasses = _render_model_declaration(
        class_info,
        python_class_names[class_info.name],
    )

    lines = ["from __future__ import annotations"]
    if needs_datetime:
        lines.extend(["", "import datetime"])
    if typing_imports:
        lines.extend(["", f"from typing import {', '.join(sorted(typing_imports))}"])
    lines.extend(["", f"from iris_persistence import {', '.join(sorted(iris_imports))}"])
    if custom_imports:
        lines.extend(["", *custom_imports])
    lines.extend(["", model_declaration])

    if not properties:
        lines.append("    pass")
    else:
        lines.extend(_render_property_field(prop, python_class_names) for prop in properties)

    lines.extend(
        _render_meta_lines(
            class_info,
            mode,
            emit_meta_superclasses,
            parameters,
            indexes,
            storage,
            storage_data,
            storage_indices,
            storage_properties,
            storage_sql_maps,
        )
    )

    return "\n".join(lines) + "\n"


def _merge_storage_properties(
    compiled_properties: list[StorageProperty],
    defined_properties: list[StorageProperty],
) -> list[StorageProperty]:
    merged = {item.name: item for item in compiled_properties}
    for item in defined_properties:
        current = merged.get(item.name)
        if current is None:
            merged[item.name] = item
            continue
        merged[item.name] = replace(
            current,
            **{
                name: value
                if (value := getattr(item, name)) not in (None, "")
                else getattr(current, name)
                for name in STORAGE_PROPERTY_SCALAR_KEYS
            },
        )
    return sorted(merged.values(), key=lambda item: item.name)


def _record_warning(result: ScaffoldResult, code: str, classname: str, exc: Exception) -> None:
    message = f"Failed to scaffold {code} for {classname}: {exc}"
    result.warnings.append(ScaffoldWarning(code=code, message=message, classname=classname))
    py_warnings.warn(message, RuntimeWarning, stacklevel=2)


def scaffold_from_iris(
    pattern: str,
    output_dir: str,
    mode: str = "observe",
    extract_meta: bool = False,
    extract_hidden_meta: bool = False,
    include_related: bool = False,
    scaffold_selectivity: bool = False,
    return_result: bool = False,
) -> list[str] | ScaffoldResult:
    """Scaffold typed models from live IRIS classes."""
    runtime = get_runtime()
    conn = runtime.get_dbapi_connection()
    reader = _CompiledDictionaryReader(conn, runtime)
    result = ScaffoldResult(files=[], warnings=[])

    if "*" in pattern:
        pattern = pattern.replace("*", "%")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        classes, properties_by_class, seed_names = _collect_classes(
            reader,
            pattern,
            include_related,
        )
        classnames = [item.name for item in classes]
        python_class_names = _assign_generated_names(classnames, seed_names, _camel_case)
        module_names = _assign_generated_names(classnames, seed_names, _snake_case)
        for class_info in classes:
            if extract_meta:
                metadata = reader.get_class_metadata(class_info.name)
                if metadata is not None:
                    class_info = _CompiledClass(
                        name=class_info.name,
                        superclasses=class_info.superclasses,
                        description=metadata.description,
                        deprecated=metadata.deprecated,
                        final=metadata.final,
                        sql_table_name=metadata.sql_table_name,
                        procedure_block=metadata.procedure_block,
                    )
            properties = properties_by_class.get(class_info.name)
            if properties is None:
                properties = reader.list_properties(class_info.name)

            parameters: list[_CompiledParameter] = []
            indexes: list[_CompiledIndex] = []
            storage: _CompiledStorage | None = None
            storage_data: list[StorageData] = []
            storage_indices: list[StorageIndex] = []
            storage_properties: list[StorageProperty] = []
            storage_sql_maps: list[StorageSQLMap] = []

            if extract_meta:
                try:
                    parameters = reader.list_parameters(class_info.name)
                except Exception as exc:
                    _record_warning(result, "parameters", class_info.name, exc)
                try:
                    indexes = reader.list_indexes(class_info.name)
                except Exception as exc:
                    _record_warning(result, "indexes", class_info.name, exc)
                try:
                    storage = reader.get_storage(
                        class_info.name,
                        include_hidden=extract_hidden_meta,
                    )
                    if storage:
                        storage_parent = f"{class_info.name}||{storage.name}"
                        storage_data = reader.list_storage_data(storage_parent)
                        storage_indices = reader.list_storage_indices(storage_parent)
                        storage_properties = reader.list_storage_properties(
                            storage_parent,
                            include_hidden=extract_hidden_meta,
                        )
                        if scaffold_selectivity:
                            storage_properties = _merge_storage_properties(
                                storage_properties,
                                reader.list_storage_property_definitions(
                                    storage_parent,
                                    include_hidden=extract_hidden_meta,
                                ),
                            )
                        storage_sql_maps = reader.list_storage_sql_maps(storage_parent)
                except Exception as exc:
                    _record_warning(result, "storage", class_info.name, exc)

            module_path = output_path / f"{module_names[class_info.name]}.py"
            module_text = _render_model(
                class_info=class_info,
                properties=properties,
                mode=mode,
                parameters=parameters,
                indexes=indexes,
                storage=storage,
                storage_data=storage_data,
                storage_indices=storage_indices,
                storage_properties=storage_properties,
                storage_sql_maps=storage_sql_maps,
                python_class_names=python_class_names,
                module_names=module_names,
            )
            module_path.write_text(module_text, encoding="utf-8")
            result.files.append(str(module_path))
    finally:
        reader.close()

    if return_result:
        return result
    return result.files


def scaffold_from_cls(cls_dir: str, output_dir: str, mode: str = "observe") -> None:
    """Roadmap placeholder for scaffolding from exported .cls files."""
    raise NotImplementedError("scaffold_from_cls is roadmap-only and is not implemented yet.")
