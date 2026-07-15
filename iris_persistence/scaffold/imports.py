from __future__ import annotations

from iris_persistence.field_utils import (
    collection_kind_from_iris_type,
    is_application_iris_class,
)
from iris_persistence.scaffold.reader import _CompiledClass, _CompiledProperty
from iris_persistence.scaffold.specs import ModelRenderSpec, RenderContext


def _rendered_property_type(prop: _CompiledProperty, python_class_names: dict[str, str]) -> str:
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


def _collect_model_imports(
    spec: ModelRenderSpec,
    context: RenderContext,
) -> tuple[list[str], set[str], bool, set[str]]:
    custom_imports, typing_imports, needs_datetime = _property_imports(
        spec.class_info,
        spec.properties,
        context.python_class_names,
        context.module_names,
    )
    iris_imports = {"Field", "Model"}
    if _has_class_metadata(spec.class_info):
        iris_imports.add("ClassMetadata")
    if spec.indexes:
        iris_imports.add("Index")
    advanced_imports = _advanced_storage_imports(
        spec.storage,
        spec.storage_data,
        spec.storage_indices,
        spec.storage_properties,
        spec.storage_sql_maps,
    )
    if advanced_imports:
        custom_imports.append(
            "from iris_persistence.advanced_storage import " + ", ".join(sorted(advanced_imports))
        )
    return (sorted(set(custom_imports)), typing_imports, needs_datetime, iris_imports)


def _property_imports(class_info, properties, class_names, module_names):
    custom: list[str] = []
    typing_imports: set[str] = set()
    needs_datetime = False
    for prop in properties:
        if prop.iris_type in class_names and prop.iris_type != class_info.name:
            custom.append(
                f"from {module_names[prop.iris_type]} import {class_names[prop.iris_type]}"
            )
        rendered = _rendered_property_type(prop, class_names)
        typing_imports.update({name for name in ("Any",) if name in rendered})
        needs_datetime = needs_datetime or "datetime." in rendered
    return custom, typing_imports, needs_datetime


def _advanced_storage_imports(storage, data, indices, properties, sql_maps):
    imports = {
        name
        for present, name in (
            (storage is not None, "StorageDefinition"),
            (data, "StorageData"),
            (indices, "StorageIndex"),
            (properties, "StorageProperty"),
        )
        if present
    }
    if sql_maps:
        imports.update(
            {
                "StorageSQLMap",
                "StorageSQLMapData",
                "StorageSQLMapRowIdSpec",
                "StorageSQLMapSub",
                "StorageSQLMapSubAccessVar",
                "StorageSQLMapSubInvalidCondition",
            }
        )
    return imports
