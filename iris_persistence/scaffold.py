from __future__ import annotations

import re
import warnings as py_warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iris_persistence.advanced_storage import (
    StorageDefinition,
    inspect_existing_storage,
)
from iris_persistence.field_utils import (
    is_application_iris_class,
)
from iris_persistence.runtime import get_runtime
from iris_persistence.scaffold_reader import (
    ScaffoldResult,
    ScaffoldWarning,
    _CompiledClass,
    _CompiledDictionaryReader,
    _CompiledIndex,
    _CompiledParameter,
    _CompiledProperty,
)
from iris_persistence.scaffold_render import _render_model


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


def _record_warning(result: ScaffoldResult, code: str, classname: str, exc: Exception) -> None:
    message = f"Failed to scaffold {code} for {classname}: {exc}"
    result.warnings.append(ScaffoldWarning(code=code, message=message, classname=classname))
    py_warnings.warn(message, RuntimeWarning, stacklevel=2)


@dataclass(frozen=True)
class _ScaffoldClassSpec:
    class_info: _CompiledClass
    properties: list[_CompiledProperty]
    parameters: list[_CompiledParameter]
    indexes: list[_CompiledIndex]
    storage: StorageDefinition | None


def _validate_scaffold_options(mode: str, storage: str) -> None:
    if mode not in {"managed", "observe"}:
        raise ValueError("mode must be 'managed' or 'observe'")
    if storage not in {"ignore", "custom"}:
        raise ValueError("storage must be 'ignore' or 'custom'")
    if storage == "custom" and mode != "managed":
        raise ValueError("storage='custom' requires mode='managed'")


def _read_optional(
    result: ScaffoldResult,
    code: str,
    classname: str,
    read: Any,
    default: Any,
    best_effort: bool,
) -> Any:
    try:
        return read()
    except Exception as exc:
        if not best_effort:
            raise
        _record_warning(result, code, classname, exc)
        return default


def _class_with_metadata(
    reader: _CompiledDictionaryReader, class_info: _CompiledClass
) -> _CompiledClass:
    metadata = reader.get_class_metadata(class_info.name)
    if metadata is None:
        return class_info
    return _CompiledClass(
        name=class_info.name,
        superclasses=class_info.superclasses,
        description=metadata.description,
        deprecated=metadata.deprecated,
        final=metadata.final,
        sql_table_name=metadata.sql_table_name,
        procedure_block=metadata.procedure_block,
    )


def _build_class_spec(
    reader: _CompiledDictionaryReader,
    runtime: Any,
    result: ScaffoldResult,
    class_info: _CompiledClass,
    properties: list[_CompiledProperty] | None,
    *,
    extract_meta: bool,
    storage: str,
    best_effort: bool,
) -> _ScaffoldClassSpec:
    if extract_meta:
        class_info = _class_with_metadata(reader, class_info)
    properties = properties if properties is not None else reader.list_properties(class_info.name)
    parameters = (
        _read_optional(
            result,
            "parameters",
            class_info.name,
            lambda: reader.list_parameters(class_info.name),
            [],
            best_effort,
        )
        if extract_meta
        else []
    )
    indexes = (
        _read_optional(
            result,
            "indexes",
            class_info.name,
            lambda: reader.list_indexes(class_info.name),
            [],
            best_effort,
        )
        if extract_meta
        else []
    )
    storage_definition = (
        _read_optional(
            result,
            "storage",
            class_info.name,
            lambda: inspect_existing_storage(class_info.name, _runtime=runtime),
            None,
            best_effort,
        )
        if storage == "custom"
        else None
    )
    return _ScaffoldClassSpec(class_info, properties, parameters, indexes, storage_definition)


def _write_scaffold_module(
    spec: _ScaffoldClassSpec,
    output_path: Path,
    mode: str,
    python_class_names: dict[str, str],
    module_names: dict[str, str],
) -> str:
    storage = spec.storage
    module_path = output_path / f"{module_names[spec.class_info.name]}.py"
    module_path.write_text(
        _render_model(
            class_info=spec.class_info,
            properties=spec.properties,
            mode=mode,
            parameters=spec.parameters,
            indexes=spec.indexes,
            storage=storage,
            storage_data=list(storage.data) if storage else [],
            storage_indices=list(storage.indices) if storage else [],
            storage_properties=list(storage.properties) if storage else [],
            storage_sql_maps=list(storage.sql_maps) if storage else [],
            python_class_names=python_class_names,
            module_names=module_names,
        ),
        encoding="utf-8",
    )
    return str(module_path)


def scaffold_from_iris(
    pattern: str,
    output_dir: str,
    mode: str = "observe",
    extract_meta: bool = False,
    include_related: bool = False,
    storage: str = "ignore",
    return_result: bool = False,
    best_effort: bool = False,
) -> list[str] | ScaffoldResult:
    """Scaffold typed models from live IRIS classes."""
    _validate_scaffold_options(mode, storage)
    runtime = get_runtime()
    reader = _CompiledDictionaryReader(runtime.get_dbapi_connection(), runtime)
    result = ScaffoldResult(files=[], warnings=[])
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    try:
        classes, properties_by_class, seeds = _collect_classes(
            reader, pattern.replace("*", "%"), include_related
        )
        classnames = [item.name for item in classes]
        class_names = _assign_generated_names(classnames, seeds, _camel_case)
        module_names = _assign_generated_names(classnames, seeds, _snake_case)
        for class_info in classes:
            spec = _build_class_spec(
                reader,
                runtime,
                result,
                class_info,
                properties_by_class.get(class_info.name),
                extract_meta=extract_meta,
                storage=storage,
                best_effort=best_effort,
            )
            result.files.append(
                _write_scaffold_module(spec, output_path, mode, class_names, module_names)
            )
    finally:
        reader.close()
    return result if return_result else result.files
    """Roadmap placeholder for scaffolding from exported .cls files."""
    raise NotImplementedError("scaffold_from_cls is roadmap-only and is not implemented yet.")
