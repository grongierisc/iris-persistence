from __future__ import annotations

import re
import warnings as py_warnings
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iris_persistence.advanced_storage import inspect_existing_storage
from iris_persistence.field_utils import (
    is_application_iris_class,
)
from iris_persistence.runtime import get_runtime
from iris_persistence.scaffold.reader import (
    ScaffoldResult,
    ScaffoldWarning,
    _CompiledClass,
    _CompiledDictionaryReader,
    _CompiledProperty,
)
from iris_persistence.scaffold.render import _render_model
from iris_persistence.scaffold.specs import (
    ModelRenderSpec,
    RenderContext,
    ScaffoldBuildContext,
)


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


@dataclass(frozen=True)
class _CollectedClasses:
    classes: list[_CompiledClass]
    properties_by_class: dict[str, list[_CompiledProperty]]
    seed_names: list[str]


@dataclass
class _ClassCollectionState:
    reader: _CompiledDictionaryReader
    classes_by_name: dict[str, _CompiledClass]
    properties_by_class: dict[str, list[_CompiledProperty]]
    queue: deque[str]
    visited: set[str]


def _related_class_names(properties: list[_CompiledProperty]) -> tuple[str, ...]:
    return tuple(
        prop.iris_type for prop in properties if is_application_iris_class(prop.iris_type)
    )


def _resolve_related_class(
    reader: _CompiledDictionaryReader,
    classname: str,
    classes_by_name: dict[str, _CompiledClass],
) -> _CompiledClass | None:
    existing = classes_by_name.get(classname)
    if existing is not None:
        return existing
    class_info = reader.get_class(classname)
    if class_info is not None:
        classes_by_name[class_info.name] = class_info
    return class_info


def _collect_related_classes(state: _ClassCollectionState, classname: str) -> None:
    properties = state.properties_by_class.setdefault(
        classname, state.reader.list_properties(classname)
    )
    for related_name in _related_class_names(properties):
        class_info = _resolve_related_class(
            state.reader, related_name, state.classes_by_name
        )
        if class_info is not None and class_info.name not in state.visited:
            state.queue.append(class_info.name)


def _collect_classes(
    reader: _CompiledDictionaryReader,
    pattern: str,
    include_related: bool,
) -> _CollectedClasses:
    seed_classes = reader.list_classes(pattern)
    seed_names = [item.name for item in seed_classes]
    classes_by_name = {item.name: item for item in seed_classes}
    properties_by_class: dict[str, list[_CompiledProperty]] = {}

    if not include_related:
        return _CollectedClasses(seed_classes, properties_by_class, seed_names)

    state = _ClassCollectionState(
        reader,
        classes_by_name,
        properties_by_class,
        deque(seed_names),
        set(),
    )
    while state.queue:
        classname = state.queue.popleft()
        if classname in state.visited:
            continue
        state.visited.add(classname)
        _collect_related_classes(state, classname)

    return _CollectedClasses(
        sorted(classes_by_name.values(), key=lambda item: item.name),
        properties_by_class,
        seed_names,
    )


def _record_warning(result: ScaffoldResult, code: str, classname: str, exc: Exception) -> None:
    message = f"Failed to scaffold {code} for {classname}: {exc}"
    result.warnings.append(ScaffoldWarning(code=code, message=message, classname=classname))
    py_warnings.warn(message, RuntimeWarning, stacklevel=2)


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
    context: ScaffoldBuildContext,
    class_info: _CompiledClass,
    properties: list[_CompiledProperty] | None,
) -> ModelRenderSpec:
    if context.extract_meta:
        class_info = _class_with_metadata(context.reader, class_info)
    properties = (
        properties
        if properties is not None
        else context.reader.list_properties(class_info.name)
    )
    parameters = (
        _read_optional(
            context.result,
            "parameters",
            class_info.name,
            lambda: context.reader.list_parameters(class_info.name),
            [],
            context.best_effort,
        )
        if context.extract_meta
        else []
    )
    indexes = (
        _read_optional(
            context.result,
            "indexes",
            class_info.name,
            lambda: context.reader.list_indexes(class_info.name),
            [],
            context.best_effort,
        )
        if context.extract_meta
        else []
    )
    storage_definition = (
        _read_optional(
            context.result,
            "storage",
            class_info.name,
            lambda: inspect_existing_storage(class_info.name, _runtime=context.runtime),
            None,
            context.best_effort,
        )
        if context.storage == "custom"
        else None
    )
    return ModelRenderSpec(class_info, properties, parameters, indexes, storage_definition)


def _write_scaffold_module(
    spec: ModelRenderSpec,
    output_path: Path,
    context: RenderContext,
) -> str:
    module_path = output_path / f"{context.module_names[spec.class_info.name]}.py"
    module_path.write_text(
        _render_model(spec, context),
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
    result = ScaffoldResult(files=[], warnings=[])
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with runtime.connection() as connection:
        reader = _CompiledDictionaryReader(connection, runtime)
        try:
            collected = _collect_classes(
                reader, pattern.replace("*", "%"), include_related
            )
            classes = collected.classes
            properties_by_class = collected.properties_by_class
            seeds = collected.seed_names
            classnames = [item.name for item in classes]
            class_names = _assign_generated_names(classnames, seeds, _camel_case)
            module_names = _assign_generated_names(classnames, seeds, _snake_case)
            render_context = RenderContext(mode, class_names, module_names)
            build_context = ScaffoldBuildContext(
                reader, runtime, result, extract_meta, storage, best_effort
            )
            for class_info in classes:
                spec = _build_class_spec(
                    build_context,
                    class_info,
                    properties_by_class.get(class_info.name),
                )
                result.files.append(
                    _write_scaffold_module(spec, output_path, render_context)
                )
        finally:
            reader.close()
    return result if return_result else result.files
    """Roadmap placeholder for scaffolding from exported .cls files."""
    raise NotImplementedError("scaffold_from_cls is roadmap-only and is not implemented yet.")
