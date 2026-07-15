from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from iris_persistence.advanced_storage import (
    STORAGE_DEFINITION_SCALAR_KEYS,
    STORAGE_SQL_MAP_DATA_SCALAR_KEYS,
    STORAGE_SQL_MAP_ROW_ID_SPEC_SCALAR_KEYS,
    STORAGE_SQL_MAP_SCALAR_KEYS,
    STORAGE_SQL_MAP_SUB_ACCESS_VAR_SCALAR_KEYS,
    STORAGE_SQL_MAP_SUB_INVALID_CONDITION_SCALAR_KEYS,
    STORAGE_SQL_MAP_SUB_SCALAR_KEYS,
    StorageData,
    StorageDefinition,
    StorageIndex,
    StorageProperty,
    StorageSQLMap,
)
from iris_persistence.field_utils import (
    collection_kind_from_iris_type,
    is_application_iris_class,
)
from iris_persistence.scaffold.imports import _collect_model_imports
from iris_persistence.scaffold.reader import (
    _CompiledClass,
    _CompiledIndex,
    _CompiledParameter,
    _CompiledProperty,
)
from iris_persistence.scaffold.specs import ModelRenderSpec, RenderContext


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
        value = getattr(item, attr_name, None)
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
        if (arg := _format_arg(arg_name, getattr(item, attr_name, None), style)) is not None
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

_STORAGE_RENDER_KEYS = ("name", *STORAGE_DEFINITION_SCALAR_KEYS)


_STORAGE_DATA_ARG_SPECS: tuple[tuple[str, str, str], ...] = (
    ("name", "name", "double"),
    ("structure", "structure", "double"),
    ("attribute", "attribute", "repr"),
    ("subscript", "subscript", "repr"),
    ("values", "values", "repr"),
)


def _render_storage_lines(
    storage: StorageDefinition,
    storage_data: list[StorageData],
    storage_indices: list[StorageIndex],
    storage_properties: list[StorageProperty],
    storage_sql_maps: list[StorageSQLMap],
) -> list[str]:
    lines = ["        custom_storage = StorageDefinition("]
    for attr_name in _STORAGE_RENDER_KEYS:
        value = getattr(storage, attr_name, None)
        if value is not None:
            lines.append(f"            {attr_name}={_double_quoted_literal(str(value))},")

    _append_storage_data(lines, storage_data)
    _append_storage_items(
        lines, "indices", "StorageIndex", storage_indices, _STORAGE_INDEX_ARG_SPECS
    )
    _append_storage_items(
        lines, "properties", "StorageProperty", storage_properties, _STORAGE_PROPERTY_ARG_SPECS
    )
    _append_storage_sql_maps(lines, storage_sql_maps)
    lines.append("        )")
    return lines


def _append_storage_data(lines: list[str], items: list[StorageData]) -> None:
    if not items:
        return
    lines.append("            data=(")
    for item in items:
        lines.append("                StorageData(")
        lines.extend(
            f"                    {arg}," for arg in _render_args(item, _STORAGE_DATA_ARG_SPECS)
        )
        lines.append("                ),")
    lines.append("            ),")


def _append_storage_items(lines, field_name, type_name, items, specs) -> None:
    if not items:
        return
    lines.append(f"            {field_name}=(")
    for item in items:
        lines.append(f"                {type_name}({', '.join(_render_args(item, specs))}),")
    lines.append("            ),")


def _append_storage_sql_maps(lines: list[str], items: list[StorageSQLMap]) -> None:
    if not items:
        return
    lines.append("            sql_maps=(")
    for item in items:
        rendered = _render_storage_sql_map(item)
        if len(rendered) == 1:
            lines.append(f"                {rendered[0]},")
        else:
            lines.append(f"                {rendered[0]}")
            lines.extend(f"                {line}" for line in rendered[1:-1])
            lines.append(f"                {rendered[-1]},")
    lines.append("            ),")


def _render_meta_lines(
    spec: ModelRenderSpec,
    context: RenderContext,
    emit_meta_superclasses: bool,
) -> list[str]:
    class_info = spec.class_info
    lines = [
        "",
        "    class Meta:",
        f'        classname = "{class_info.name}"',
        f'        mode = "{context.mode}"',
    ]
    if emit_meta_superclasses:
        lines.append(f'        superclasses = "{class_info.superclasses}"')
    if _has_class_metadata(class_info):
        lines.extend(_render_class_metadata_lines(class_info))
    if spec.parameters:
        lines.extend(_render_parameter_lines(spec.parameters))
    if spec.indexes:
        lines.extend(_render_index_lines(spec.indexes))
    if spec.storage:
        lines.extend(
            _render_storage_lines(
                spec.storage,
                spec.storage_data,
                spec.storage_indices,
                spec.storage_properties,
                spec.storage_sql_maps,
            )
        )
    return lines


def _render_model(
    spec: ModelRenderSpec,
    context: RenderContext,
) -> str:
    class_info = spec.class_info
    custom_imports, typing_imports, needs_datetime, iris_imports = _collect_model_imports(
        spec, context
    )

    model_declaration, emit_meta_superclasses = _render_model_declaration(
        class_info,
        context.python_class_names[class_info.name],
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

    if not spec.properties:
        lines.append("    pass")
    else:
        lines.extend(
            _render_property_field(prop, context.python_class_names) for prop in spec.properties
        )

    lines.extend(
        _render_meta_lines(
            spec,
            context,
            emit_meta_superclasses,
        )
    )

    return "\n".join(lines) + "\n"
