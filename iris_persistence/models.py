from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from dataclasses import fields as dataclass_fields
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Dict,
    List,
    Optional,
    Type,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from iris_persistence.advanced_storage import StorageDefinition
from iris_persistence.codecs import SCALAR_CODECS, resolve_declared_type
from iris_persistence.field_utils import (
    IRIS_COLLECTION_TYPES,
    collection_value_type,
    is_application_iris_class,
    is_model_type,
    is_percent_list_field,
    is_scalar_string_field,
    walk_declared_value,
)
from iris_persistence.model_codegen import (
    FieldPlan as _FieldPlan,
)
from iris_persistence.model_codegen import (
    build_fast_init as _build_fast_init,
)
from iris_persistence.model_codegen import (
    build_fast_load as _build_fast_load,
)
from iris_persistence.model_codegen import (
    build_fast_save as _build_fast_save,
)
from iris_persistence.model_codegen import (
    build_generated_init as _build_generated_init,
)
from iris_persistence.model_codegen import (
    build_signature as _build_signature,
)
from iris_persistence.types import (
    UNSET,
    ClassMetadata,
    FieldInfo,
    Index,
    ModelField,
    StorageTuning,
)

if TYPE_CHECKING:
    from iris_persistence.query import QuerySet

T = TypeVar("T", bound="Model")
TDataclass = TypeVar("TDataclass")


RESERVED_FIELD_NAMES = frozenset({"pk", "_pk", "_iris_obj"})
DEFAULT_SYNC_MODE = "managed"


@dataclass(frozen=True)
class SyncPolicy:
    auto_sync: bool
    merge: str
    cache_auto_sync: bool = False


SYNC_POLICIES = {
    "observe": SyncPolicy(False, "live"),
    "managed": SyncPolicy(True, "managed"),
}


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


def _is_object_reference_field(model_field: ModelField) -> bool:
    if model_field._is_model_field:
        return True
    if model_field._collection_kind is not None:
        return False
    if getattr(model_field.field_info, "collection", None) is not None:
        return False
    return is_application_iris_class(getattr(model_field.field_info, "iris_type", None))


def _value_matches_declared_type(declared_type: Any, value: Any) -> bool:
    origin = get_origin(declared_type)
    if declared_type is Any:
        return True
    if origin is None:
        if isinstance(declared_type, type):
            if (
                declared_type is float
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                return True
            if declared_type is int and isinstance(value, bool):
                return False
            return isinstance(value, declared_type)
        return True
    if origin in (list, List):
        if not isinstance(value, list):
            return False
        args = get_args(declared_type)
        if not args:
            return True
        return all(_value_matches_declared_type(args[0], item) for item in value)
    if origin in (dict, Dict):
        if not isinstance(value, dict):
            return False
        args = get_args(declared_type)
        if len(args) != 2:
            return True
        key_type, value_type = args
        return all(
            _value_matches_declared_type(key_type, key)
            and _value_matches_declared_type(value_type, item)
            for key, item in value.items()
        )
    union_args = [arg for arg in get_args(declared_type) if arg is not type(None)]
    if union_args:
        return any(_value_matches_declared_type(arg, value) for arg in union_args)
    return True


def _validate_field_value(model_field: ModelField, value: Any) -> Any:
    if value is None:
        if model_field.nullable or model_field.default is None:
            return value
        raise ValueError(f"Field '{model_field.name}' does not allow null values")
    if (
        isinstance(value, str)
        and value == ""
        and model_field.nullable
        and _is_object_reference_field(model_field)
    ):
        return None

    max_length = model_field.field_info.max_length
    if max_length is not None and hasattr(value, "__len__") and len(value) > max_length:
        raise ValueError(
            f"Field '{model_field.name}' exceeds max_length={max_length}: {len(value)}"
        )

    if not _value_matches_declared_type(model_field.declared_type, value):
        raise TypeError(
            f"Field '{model_field.name}' expected "
            f"{getattr(model_field.declared_type, '__name__', repr(model_field.declared_type))}, "
            f"got {type(value).__name__}"
        )

    return value


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
    except Exception:
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


def _model_value_to_dict(value: Any) -> Any:
    if isinstance(value, Model):
        return value.to_dict()
    if isinstance(value, list):
        return [_model_value_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: _model_value_to_dict(item) for key, item in value.items()}
    return value


def _convert_recursive_value(
    value: Any,
    declared_type: Any,
    mode: str,
) -> Any:
    def convert_leaf(leaf_value: Any, resolved_type: Any) -> Any:
        if (
            mode == "mapping_to_model"
            and is_model_type(resolved_type)
            and isinstance(leaf_value, dict)
        ):
            return resolved_type.from_dict(leaf_value)
        if (
            mode == "dataclass_to_model"
            and is_model_type(resolved_type)
            and is_dataclass(leaf_value)
            and not isinstance(leaf_value, type)
        ):
            return resolved_type.from_dataclass(leaf_value)
        if mode == "model_to_dataclass" and isinstance(leaf_value, Model):
            if isinstance(resolved_type, type) and is_dataclass(resolved_type):
                return leaf_value.to_dataclass(resolved_type)
            return leaf_value.to_dict()
        return leaf_value

    return walk_declared_value(value, declared_type, convert_leaf)


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

        setattr(cls, "__model_fields__", model_fields)
        setattr(
            cls,
            "_fields",
            {name: model_field.field_info for name, model_field in model_fields.items()},
        )
        generated_init = _build_generated_init(model_fields)
        if generated_init is not None:
            generated_init.__qualname__ = f"{cls.__qualname__}.__init__"
            setattr(cls, "__init__", generated_init)
        setattr(cls, "__signature__", _build_signature(model_fields))
        if hasattr(cls, "_declared_field_assignments__"):
            delattr(cls, "_declared_field_assignments__")

        # Parse inner Meta class
        meta_inner = namespace.get("Meta", None)
        declared_model_options = getattr(cls, "_declared_model_options__", {})
        if hasattr(cls, "_declared_model_options__"):
            delattr(cls, "_declared_model_options__")
        superclasses = _resolve_model_superclasses(meta_inner, declared_model_options)
        validate_on_init = getattr(meta_inner, "validate_on_init", True)
        sync_mode = getattr(meta_inner, "mode", DEFAULT_SYNC_MODE)
        if sync_mode not in SYNC_POLICIES:
            if sync_mode in {"extend", "replace"}:
                raise TypeError(
                    f"Schema sync mode {sync_mode!r} was removed in 0.3; "
                    "use 'managed' or 'observe'"
                )
            raise TypeError(f"Unknown schema sync mode: {sync_mode!r}")
        if meta_inner is not None and hasattr(meta_inner, "storage"):
            raise TypeError(
                "Meta.storage was removed in 0.3; use Meta.storage_tuning or "
                "Meta.custom_storage"
            )
        storage_tuning = getattr(meta_inner, "storage_tuning", None)
        custom_storage = getattr(meta_inner, "custom_storage", None)
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
        is_serial = "SerialObject" in (_normalize_superclasses(superclasses) or "")
        if is_serial and (storage_tuning is not None or custom_storage is not None):
            raise TypeError("Storage declarations are not supported for serial models")
        for attr_name, value in {
            "_classname": getattr(meta_inner, "classname", name),
            "_sync_mode": sync_mode,
            "_auto_sync": getattr(meta_inner, "auto_sync", False),
            "_validate_on_init": validate_on_init,
            "_superclasses": _normalize_superclasses(superclasses),
            "_class_metadata": _parse_class_metadata(meta_inner),
            "_storage_tuning": storage_tuning,
            "_custom_storage": custom_storage,
            "_parameters": getattr(meta_inner, "parameters", {}),
        }.items():
            setattr(cls, attr_name, value)
        if not validate_on_init:
            fast_init = _build_fast_init(model_fields)
            if fast_init is not None:
                fast_init.__qualname__ = f"{cls.__qualname__}.__init__"
                setattr(cls, "__init__", fast_init)
        declared_indexes = list(getattr(meta_inner, "indexes", []))
        setattr(cls, "_indexes", _synthesize_indexes(cls.__name__, model_fields, declared_indexes))

        field_plans = _build_field_plans(model_fields)
        for attr_name, value in {
            "_field_plans": field_plans,
            "_read_fields": {
                kind: tuple(plan for plan in field_plans if plan.read_kind == kind)
                for kind in ("str", "primitive", "bool", "coerce", "complex")
            },
            "_save_fields": {
                kind: tuple(plan for plan in field_plans if plan.save_kind == kind)
                for kind in ("scalar_fast", "scalar_coerce", "complex")
            },
        }.items():
            setattr(cls, attr_name, value)
        # Pre-compute serial-class flag to avoid re-checking per _build_model_from_iris_obj call.
        _superclasses_str = _normalize_superclasses(superclasses) or ""
        _is_serial = "SerialObject" in _superclasses_str
        setattr(cls, "_is_serial_class", _is_serial)

        # Generate per-class _fast_load if possible (only str/int/float/bool scalar fields).
        # None means fall back to the generic _build_model_from_iris_obj loop.
        _fast_load_fn = None
        if not any(plan.read_kind in {"coerce", "complex"} for plan in field_plans):
            _fast_load_fn = _build_fast_load(cls, field_plans, _is_serial)
        setattr(cls, "_fast_load", _fast_load_fn)

        # Generate per-class _fast_save for primitive scalar fields only.
        # None means fall back to the generic set_property loop in save_model.
        _fast_save_fn = None
        if not any(plan.save_kind != "scalar_fast" for plan in field_plans):
            _fast_save_fn = _build_fast_save(cls, field_plans)
        setattr(cls, "_fast_save", _fast_save_fn)


class Model(metaclass=ModelMeta):
    __model_fields__: dict[str, ModelField]
    _fields: dict[str, FieldInfo]
    _classname: str
    _sync_mode: str
    _auto_sync: bool
    _validate_on_init: bool
    _class_metadata: ClassMetadata | None
    _storage_tuning: StorageTuning | None
    _custom_storage: StorageDefinition | None
    _field_plans: tuple[_FieldPlan, ...]
    _read_fields: dict[str, tuple[_FieldPlan, ...]]
    _save_fields: dict[str, tuple[_FieldPlan, ...]]
    _is_serial_class: bool
    _fast_load: Any  # per-class code-gen loader, or None for generic path
    _fast_save: Any  # per-class code-gen field setter, or None for generic path

    @classmethod
    def __init_subclass__(
        cls,
        *,
        persistent: bool = False,
        serial: bool = False,
        superclasses: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__()

    def _initialize_model_state(self, provided_values: dict[str, Any]) -> None:
        self._pk: Optional[str] = None
        self._iris_obj: Any = None

        unknown = [name for name in provided_values if name not in self.__class__.__model_fields__]
        if unknown:
            unknown_fields = ", ".join(sorted(unknown))
            raise TypeError(
                f"Unknown field(s) for model {self.__class__.__name__}: {unknown_fields}"
            )

        for name, model_field in self.__class__.__model_fields__.items():
            value = provided_values.get(name, UNSET)
            if value is UNSET:
                value = model_field.get_default_value()
                if value is UNSET:
                    if model_field.required:
                        raise TypeError(
                            f"Missing required field '{name}' for model {self.__class__.__name__}"
                        )
                    continue
            if self.__class__._validate_on_init:
                setattr(self, name, _validate_field_value(model_field, value))
            else:
                setattr(self, name, value)

    def __init__(self, **kwargs):
        self._initialize_model_state(kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Return declared model fields as plain Python values."""
        values: dict[str, Any] = {}
        for name in self.__class__.__model_fields__:
            if hasattr(self, name):
                values[name] = _model_value_to_dict(getattr(self, name))
        return values

    @classmethod
    def from_dict(cls: Type[T], values: dict[str, Any]) -> T:
        """Build a model from a mapping of declared field names to Python values."""
        if not isinstance(values, dict):
            raise TypeError(f"{cls.__name__}.from_dict() expects a dict")

        converted = {
            name: value
            if (model_field := cls.__model_fields__.get(name)) is None
            else _convert_recursive_value(
                value,
                model_field.declared_type,
                "mapping_to_model",
            )
            for name, value in values.items()
        }
        return cls(**converted)

    def to_dataclass(self, dataclass_type: Type[TDataclass]) -> TDataclass:
        """Build a dataclass DTO from matching model field names."""
        if not (isinstance(dataclass_type, type) and is_dataclass(dataclass_type)):
            raise TypeError("to_dataclass() expects a dataclass type")

        values: dict[str, Any] = {}
        for dataclass_field in dataclass_fields(cast(Any, dataclass_type)):
            if not dataclass_field.init:
                continue
            name = dataclass_field.name
            if name in self.__class__.__model_fields__ and hasattr(self, name):
                values[name] = _convert_recursive_value(
                    getattr(self, name),
                    dataclass_field.type,
                    "model_to_dataclass",
                )
        return dataclass_type(**values)

    @classmethod
    def from_dataclass(cls: Type[T], value: Any) -> T:
        """Build a model from a dataclass DTO with matching field names."""
        if isinstance(value, type) or not is_dataclass(value):
            raise TypeError(f"{cls.__name__}.from_dataclass() expects a dataclass instance")

        values = {
            dataclass_field.name: _convert_recursive_value(
                getattr(value, dataclass_field.name),
                model_field.declared_type,
                "dataclass_to_model",
            )
            for dataclass_field in dataclass_fields(value)
            if (model_field := cls.__model_fields__.get(dataclass_field.name)) is not None
        }
        return cls.from_dict(values)

    def __repr__(self) -> str:
        fields = [f"pk={repr(self.pk)}"]
        for name in self.__class__.__model_fields__:
            if hasattr(self, name):
                fields.append(f"{name}={repr(getattr(self, name))}")
        return f"<{self.__class__.__name__} {', '.join(fields)}>"

    @property
    def pk(self) -> Optional[str]:
        return self._pk

    def save(self) -> None:
        from iris_persistence.query import save_model

        save_model(self)

    def to_iris(self, *, auto_sync: bool = True, validate: bool = True) -> Any:
        """Return a populated IRIS object handle without calling %Save()."""

        from iris_persistence.query import materialize

        return materialize(self, auto_sync=auto_sync, validate=validate)

    @classmethod
    def from_iris(
        cls: Type[T],
        iris_obj: Any,
        *,
        known_pk: Optional[str] = None,
    ) -> Optional[T]:
        """Build a model instance around an existing IRIS object handle."""

        from iris_persistence.query import from_iris

        return from_iris(cls, iris_obj, known_pk=known_pk)

    @classmethod
    def sync_schema(cls, *, dry_run: bool = False):
        from iris_persistence.schema import diff_schema as schema_diff
        from iris_persistence.schema import sync_schema as schema_sync

        if dry_run:
            return schema_diff(cls)
        schema_sync(cls)
        return None

    @classmethod
    def diff_schema(cls):
        from iris_persistence.schema import diff_schema as schema_diff

        return schema_diff(cls)

    @classmethod
    def get(cls: Type[T], pk: str) -> Optional[T]:
        from iris_persistence.query import get_model

        return get_model(cls, pk)

    @classmethod
    def all(cls: Type[T]) -> List[T]:
        from iris_persistence.query import QuerySet

        return QuerySet(cls).all()

    @classmethod
    def where(cls: Type[T], **kwargs) -> "QuerySet[T]":
        from iris_persistence.query import QuerySet

        return QuerySet(cls).where(**kwargs)

    def _validate_for_save(self) -> None:
        for name, model_field in self.__class__.__model_fields__.items():
            if hasattr(self, name):
                _validate_field_value(model_field, getattr(self, name))
            elif model_field.required:
                raise ValueError(f"Field '{name}' is required")
