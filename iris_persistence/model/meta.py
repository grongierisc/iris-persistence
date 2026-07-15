from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Dict, cast, get_args, get_origin, get_type_hints

from iris_persistence.advanced_storage import StorageDefinition
from iris_persistence.codecs import SCALAR_CODECS, resolve_declared_type
from iris_persistence.field_utils import (
    IRIS_COLLECTION_TYPES,
    collection_value_type,
    is_model_type,
    is_percent_list_field,
    is_scalar_string_field,
)
from iris_persistence.model.codegen import FieldPlan as _FieldPlan
from iris_persistence.model.codegen import build_fast_init as _build_fast_init
from iris_persistence.model.codegen import build_fast_load as _build_fast_load
from iris_persistence.model.codegen import build_fast_save as _build_fast_save
from iris_persistence.model.codegen import build_generated_init as _build_generated_init
from iris_persistence.model.codegen import build_signature as _build_signature
from iris_persistence.model.values import (
    _is_object_reference_field,
)
from iris_persistence.types import (
    UNSET,
    ClassMetadata,
    FieldInfo,
    Index,
    ModelField,
    StorageTuning,
)

DEFAULT_SYNC_MODE = "managed"
RESERVED_FIELD_NAMES = frozenset({"pk", "_pk", "_iris_obj"})


@dataclass(frozen=True)
class SyncPolicy:
    auto_sync: bool
    merge: str
    cache_auto_sync: bool = False


SYNC_POLICIES = {
    "observe": SyncPolicy(False, "live"),
    "managed": SyncPolicy(True, "managed"),
}


@dataclass(frozen=True)
class _ModelOptions:
    classname: str
    sync_mode: str
    auto_sync: bool
    validate_on_init: bool
    superclasses: str
    class_metadata: ClassMetadata | None
    storage_tuning: StorageTuning | None
    custom_storage: StorageDefinition | None
    parameters: dict[str, Any]
    indexes: list[Index]


def _is_empty_class_metadata(metadata: ClassMetadata | None) -> bool:
    if metadata is None:
        return True
    return (
        metadata.description is None
        and not metadata.deprecated
        and not metadata.final
        and metadata.sql_table_name is None
        and not metadata.procedure_block
    )


def _parse_class_metadata(meta_inner: Any) -> ClassMetadata | None:
    if meta_inner is None:
        return None

    metadata = getattr(meta_inner, "metadata", None)
    if metadata is None:
        metadata = ClassMetadata(
            description=getattr(meta_inner, "description", None),
            deprecated=getattr(meta_inner, "deprecated", False),
            final=getattr(meta_inner, "final", False),
            sql_table_name=getattr(meta_inner, "sql_table_name", None),
            procedure_block=getattr(meta_inner, "procedure_block", False),
        )

    return None if _is_empty_class_metadata(metadata) else metadata


def _extract_annotation_field(hint: Any) -> tuple[Any, FieldInfo | None]:
    origin = get_origin(hint)
    if origin is not Annotated:
        return (hint, None)

    args = get_args(hint)
    metadata = [item for item in args[1:] if isinstance(item, FieldInfo)]
    if len(metadata) > 1:
        raise TypeError("A field annotation may include at most one Field(...) metadata object")
    return (args[0], metadata[0] if metadata else None)


def _normalize_superclasses(value: Any) -> str:
    if value is None:
        return "%Persistent"
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


def _is_optional_type(hint: Any) -> bool:
    origin = get_origin(hint)
    if origin is None:
        return False
    return type(None) in get_args(hint)


def _build_model_field(
    field_name: str,
    hint: Any,
    assigned_value: Any,
    assigned_field: FieldInfo | Any,
) -> ModelField:
    declared_type, annotation_field = _extract_annotation_field(hint)
    if isinstance(assigned_field, FieldInfo) and annotation_field is not None:
        raise TypeError(
            f"Field '{field_name}' cannot declare Field(...) in both Annotated metadata and "
            "a class assignment"
        )

    if isinstance(assigned_field, FieldInfo):
        field_info = assigned_field
    elif annotation_field is not None:
        field_info = annotation_field
    else:
        field_info = FieldInfo()

    field_info = FieldInfo(**field_info.__dict__)

    if assigned_value is not UNSET:
        if field_info.default_factory is not UNSET:
            raise TypeError(
                f"Field '{field_name}' cannot define both default_factory and a class default"
            )
        field_info.default = assigned_value

    resolved_type = resolve_declared_type(declared_type)
    nullable = field_info.nullable
    if nullable is None:
        nullable = (
            _is_optional_type(declared_type)
            or field_info.default is None
            or not field_info.required
        )

    is_percent_list = is_percent_list_field(field_info)
    is_scalar_string = is_scalar_string_field(field_info)
    collection_kind, element_type = collection_value_type(resolved_type)
    if (
        field_info.collection is None
        and collection_kind is not None
        and field_info.iris_type not in IRIS_COLLECTION_TYPES
    ):
        field_info.collection = collection_kind
    is_model_field = is_model_type(resolved_type)

    return ModelField(
        name=field_name,
        declared_type=resolved_type,
        field_info=field_info,
        required=field_info.required,
        nullable=bool(nullable),
        sql_field_name=field_info.sql_field_name,
        _is_percent_list=is_percent_list,
        _is_scalar_string=is_scalar_string,
        _collection_kind=collection_kind,
        _element_type=element_type,
        _is_model_field=is_model_field,
    )


def _synthesize_indexes(
    model_name: str,
    model_fields: Dict[str, ModelField],
    declared_indexes: list[Index],
) -> list[Index]:
    indexes = list(declared_indexes)
    indexed_fields: dict[str, list[Index]] = {}
    used_names = set()

    for index in indexes:
        used_names.add(index.name)
        for field_name in (item.strip() for item in index.properties.split(",")):
            if not field_name:
                continue
            indexed_fields.setdefault(field_name, []).append(index)

    synthesized: list[Index] = []
    for field_name, model_field in model_fields.items():
        field_info = model_field.field_info
        if not (field_info.index or field_info.unique or field_info.primary_key):
            continue

        if field_name in indexed_fields:
            existing = ", ".join(sorted(index.name for index in indexed_fields[field_name]))
            raise TypeError(
                f"Field '{field_name}' on model {model_name} declares index metadata, "
                f"but Meta.indexes already defines index(es): {existing}"
            )

        index_name = field_info.index_name or f"{field_name}Idx"
        if index_name in used_names:
            raise TypeError(
                f"Field '{field_name}' on model {model_name} generated duplicate index name "
                f"'{index_name}'"
            )

        synthesized.append(
            Index(
                index_name,
                properties=field_name,
                unique=bool(field_info.unique or field_info.primary_key),
                primary_key=field_info.primary_key,
                type=field_info.index_type,
            )
        )
        used_names.add(index_name)

    return indexes + synthesized


def _collect_model_fields(cls: type, namespace: dict[str, Any]) -> dict[str, ModelField]:
    model_fields: dict[str, ModelField] = {}
    for base in reversed(cls.__mro__[1:]):
        model_fields.update(getattr(base, "__model_fields__", {}))

    try:
        hints = get_type_hints(cls, include_extras=True)
    except (NameError, TypeError):
        hints = {}

    declared_field_assignments = getattr(cls, "_declared_field_assignments__", {})
    annotations = namespace.get("__annotations__", {})
    for field_name in annotations:
        if field_name.startswith("_"):
            continue
        raw_default = namespace.get(field_name, UNSET)
        if isinstance(raw_default, FieldInfo):
            raw_default = UNSET
        model_fields[field_name] = _build_model_field(
            field_name,
            hints.get(field_name, Any),
            raw_default,
            declared_field_assignments.get(field_name, UNSET),
        )

    return model_fields


def _resolve_model_superclasses(meta_inner: Any, declared_model_options: dict[str, Any]) -> Any:
    declared_superclasses = declared_model_options.get("superclasses")
    persistent = bool(declared_model_options.get("persistent", False))
    serial = bool(declared_model_options.get("serial", False))
    if (
        persistent
        and serial
        and declared_superclasses is None
        and getattr(meta_inner, "superclasses", None) is None
    ):
        raise TypeError("Model cannot declare both persistent=True and serial=True")
    if getattr(meta_inner, "superclasses", None) is not None:
        return meta_inner.superclasses
    if declared_superclasses is not None:
        return declared_superclasses
    if serial:
        return "%SerialObject"
    if persistent:
        return "%Persistent"
    return "%Persistent"


def _build_field_plans(model_fields: dict[str, ModelField]) -> tuple[_FieldPlan, ...]:
    plans = []
    for field_name, model_field in model_fields.items():
        if (
            model_field._is_percent_list
            or model_field._collection_kind is not None
            or model_field._is_model_field
        ):
            read_kind = "complex"
        else:
            codec = SCALAR_CODECS.get(model_field.declared_type)
            read_kind = codec.read_kind if codec is not None else "coerce"

        if getattr(model_field.field_info, "readonly", False):
            save_kind = "complex"
        elif model_field._collection_kind is None and not _is_object_reference_field(model_field):
            codec = SCALAR_CODECS.get(model_field.declared_type)
            save_kind = codec.save_kind if codec is not None else "scalar_coerce"
        else:
            save_kind = "complex"

        plans.append(_FieldPlan(field_name, model_field, read_kind, save_kind))
    return tuple(plans)


def _validate_storage_options(
    sync_mode: str,
    superclasses: str,
    storage_tuning: Any,
    custom_storage: Any,
) -> None:
    if storage_tuning is not None and not isinstance(storage_tuning, StorageTuning):
        raise TypeError("Meta.storage_tuning must be a StorageTuning instance")
    if custom_storage is not None and not isinstance(custom_storage, StorageDefinition):
        raise TypeError(
            "Meta.custom_storage must be an advanced_storage.StorageDefinition instance"
        )
    if storage_tuning is not None and custom_storage is not None:
        raise TypeError("Meta.storage_tuning and Meta.custom_storage are mutually exclusive")
    if sync_mode == "observe" and (storage_tuning is not None or custom_storage is not None):
        raise TypeError("Storage declarations require mode='managed'")
    if "SerialObject" in superclasses and (
        storage_tuning is not None or custom_storage is not None
    ):
        raise TypeError("Storage declarations are not supported for serial models")


def _parse_model_options(cls: type, name: str, namespace: dict[str, Any]) -> _ModelOptions:
    meta_inner = namespace.get("Meta")
    declared = getattr(cls, "_declared_model_options__", {})
    if hasattr(cls, "_declared_model_options__"):
        delattr(cls, "_declared_model_options__")

    sync_mode = getattr(meta_inner, "mode", DEFAULT_SYNC_MODE)
    if sync_mode not in SYNC_POLICIES:
        if sync_mode in {"extend", "replace"}:
            raise TypeError(
                f"Schema sync mode {sync_mode!r} was removed in 0.3; use 'managed' or 'observe'"
            )
        raise TypeError(f"Unknown schema sync mode: {sync_mode!r}")
    if meta_inner is not None and hasattr(meta_inner, "storage"):
        raise TypeError(
            "Meta.storage was removed in 0.3; use Meta.storage_tuning or Meta.custom_storage"
        )

    superclasses = _normalize_superclasses(_resolve_model_superclasses(meta_inner, declared)) or ""
    storage_tuning = getattr(meta_inner, "storage_tuning", None)
    custom_storage = getattr(meta_inner, "custom_storage", None)
    _validate_storage_options(sync_mode, superclasses, storage_tuning, custom_storage)
    return _ModelOptions(
        classname=getattr(meta_inner, "classname", name),
        sync_mode=sync_mode,
        auto_sync=getattr(meta_inner, "auto_sync", False),
        validate_on_init=getattr(meta_inner, "validate_on_init", True),
        superclasses=superclasses,
        class_metadata=_parse_class_metadata(meta_inner),
        storage_tuning=storage_tuning,
        custom_storage=custom_storage,
        parameters=getattr(meta_inner, "parameters", {}),
        indexes=list(getattr(meta_inner, "indexes", [])),
    )


def _install_model_fields(cls: type, model_fields: dict[str, ModelField]) -> None:
    target = cast(Any, cls)
    target.__model_fields__ = model_fields
    target._fields = {name: field.field_info for name, field in model_fields.items()}
    generated_init = _build_generated_init(model_fields)
    if generated_init is not None:
        generated_init.__qualname__ = f"{cls.__qualname__}.__init__"
        target.__init__ = generated_init
    target.__signature__ = _build_signature(model_fields)
    if hasattr(cls, "_declared_field_assignments__"):
        delattr(cls, "_declared_field_assignments__")


def _install_model_options(
    cls: type,
    model_fields: dict[str, ModelField],
    options: _ModelOptions,
) -> None:
    target = cast(Any, cls)
    target._classname = options.classname
    target._sync_mode = options.sync_mode
    target._auto_sync = options.auto_sync
    target._validate_on_init = options.validate_on_init
    target._superclasses = options.superclasses
    target._class_metadata = options.class_metadata
    target._storage_tuning = options.storage_tuning
    target._custom_storage = options.custom_storage
    target._parameters = options.parameters
    target._indexes = _synthesize_indexes(cls.__name__, model_fields, options.indexes)
    if not options.validate_on_init:
        fast_init = _build_fast_init(model_fields)
        if fast_init is not None:
            fast_init.__qualname__ = f"{cls.__qualname__}.__init__"
            target.__init__ = fast_init


def _group_field_plans(
    field_plans: tuple[_FieldPlan, ...],
    attribute: str,
    kinds: tuple[str, ...],
) -> dict[str, tuple[_FieldPlan, ...]]:
    return {
        kind: tuple(plan for plan in field_plans if getattr(plan, attribute) == kind)
        for kind in kinds
    }


def _install_field_plans(cls: type, model_fields: dict[str, ModelField]) -> None:
    target = cast(Any, cls)
    field_plans = _build_field_plans(model_fields)
    target._field_plans = field_plans
    target._read_fields = _group_field_plans(
        field_plans, "read_kind", ("str", "primitive", "bool", "coerce", "complex")
    )
    target._save_fields = _group_field_plans(
        field_plans, "save_kind", ("scalar_fast", "scalar_coerce", "complex")
    )
    target._is_serial_class = "SerialObject" in target._superclasses
    target._fast_load = (
        None
        if any(plan.read_kind in {"coerce", "complex"} for plan in field_plans)
        else _build_fast_load(cls, field_plans, target._is_serial_class)
    )
    target._fast_save = (
        None
        if any(plan.save_kind != "scalar_fast" for plan in field_plans)
        else _build_fast_save(cls, field_plans)
    )


class ModelMeta(type):
    def __new__(mcs, name: str, bases: tuple, namespace: dict, **kwargs: Any):
        namespace_copy = dict(namespace)
        annotations = namespace.get("__annotations__", {})
        reserved = sorted(
            field_name for field_name in annotations if field_name in RESERVED_FIELD_NAMES
        )
        if reserved:
            reserved_fields = ", ".join(reserved)
            raise TypeError(f"Model {name} uses reserved field name(s): {reserved_fields}")
        declared_field_assignments = {}
        for field_name in annotations:
            value = namespace.get(field_name, UNSET)
            if isinstance(value, FieldInfo):
                declared_field_assignments[field_name] = value
                namespace_copy.pop(field_name, None)

        namespace_copy["_declared_field_assignments__"] = declared_field_assignments
        namespace_copy["_declared_model_options__"] = dict(kwargs)
        return super().__new__(mcs, name, bases, namespace_copy)

    def __init__(cls, name: str, bases: tuple, namespace: dict, **kwargs: Any):
        super().__init__(name, bases, namespace)
        if name == "Model":
            return
        model_fields = _collect_model_fields(cls, namespace)
        options = _parse_model_options(cls, name, namespace)
        _install_model_fields(cls, model_fields)
        _install_model_options(cls, model_fields, options)
        _install_field_plans(cls, model_fields)
