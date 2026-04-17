from __future__ import annotations

import contextlib
import copy
import dataclasses
from dataclasses import MISSING, dataclass, field as dataclass_field
import warnings
from typing import Annotated, Any, ClassVar, Generic, Self, TypeVar, get_args, get_origin, get_type_hints

from .fields import Field, FieldDefinition, IndexDefinition
from .schema import (
    SchemaCompiler,
    SchemaPlan,
    coerce_to_python,
    iris_type_to_python,
    merge_additive_schema,
    python_default_value,
    python_type_to_iris,
    schema_equals,
)
from .storage import StorageDefinition, validate_storage_definition_dict


# ---------------------------------------------------------------------------
# Per-subclass IRIS metadata consolidated into a single object
# ---------------------------------------------------------------------------

@dataclass
class _IrisClassState:
    """All per-subclass IRIS metadata in one place."""

    classname: str = ""
    superclasses: str | list[str] = "%Persistent"
    mode: str = "extend"
    storage: StorageDefinition | dict[str, Any] | None = None
    indexes: list[dict[str, Any]] = dataclass_field(default_factory=list)
    parameters: dict[str, str] = dataclass_field(default_factory=dict)
    declared_fields: dict[str, FieldDefinition] = dataclass_field(default_factory=dict)
    bound_schema: Any = None
    bound: bool = False
    prepared_state: tuple[int, dict[str, Any]] | None = None
    native_proxy_names: set[str] = dataclass_field(default_factory=set)
    native_proxy_version: int | None = None


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_MODEL_REGISTRY: dict[str, type] = {}
_ModelT = TypeVar("_ModelT", bound="IRISModel")
_VALID_MODES = {"replace", "extend", "observe"}

# Maps Meta attribute name → _IrisClassState field name
_META_TO_IRIS_ATTRS = {
    "classname": "classname",
    "mode": "mode",
    "superclasses": "superclasses",
    "storage": "storage",
    "indexes": "indexes",
    "parameters": "parameters",
}

# Legacy direct class-level attribute names that map to _IrisClassState fields
_LEGACY_ATTR_TO_STATE_FIELD: dict[str, str] = {
    "_iris_classname": "classname",
    "_iris_mode": "mode",
    "_iris_superclasses": "superclasses",
    "_iris_storage": "storage",
    "_iris_indexes": "indexes",
    "_iris_parameters": "parameters",
}

# Set of legacy direct-attribute names that trigger deprecation warnings
_DEPRECATED_CLASS_METADATA = set(_LEGACY_ATTR_TO_STATE_FIELD)


# ---------------------------------------------------------------------------
# Descriptors
# ---------------------------------------------------------------------------

class _ModelFieldDescriptor:
    def __init__(self, name: str) -> None:
        self.name = name

    def __get__(self, instance: "IRISModel | None", owner: type["IRISModel"]) -> Any:
        if instance is None:
            return owner._iris_state.declared_fields[self.name]
        return object.__getattribute__(instance, "_iris_data").get(self.name)

    def __set__(self, instance: "IRISModel", value: Any) -> None:
        object.__getattribute__(instance, "_iris_data")[self.name] = value


class _NativeClassAttributeProxy:
    def __init__(self, name: str) -> None:
        self.name = name

    def __get__(self, instance: Any, owner: type["IRISModel"]) -> Any:
        owner._prepare()
        native_class = owner._runtime().native_class(owner._iris_state.classname)
        native_attr = getattr(native_class, self.name)
        if callable(native_attr):

            def _class_method_proxy(*args: Any, **kwargs: Any) -> Any:
                return native_attr(*args, **kwargs)

            _class_method_proxy.__name__ = self.name
            return _class_method_proxy
        return native_attr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clone_field_definition(value: FieldDefinition) -> FieldDefinition:
    return value.copy()


def _safe_type_hints(cls: type) -> dict[str, Any]:
    try:
        return get_type_hints(cls, include_extras=True)
    except Exception:
        return dict(getattr(cls, "__annotations__", {}))


def _split_annotated(annotation: Any) -> tuple[Any, FieldDefinition | None]:
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        python_type = args[0]
        metadata = [item for item in args[1:] if isinstance(item, Field)]
        if len(metadata) > 1:
            raise TypeError("Only one iris_orm.Field metadata item is allowed per Annotated field")
        return python_type, _clone_field_definition(metadata[0]) if metadata else None
    return annotation, None


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

@dataclass
class Query(Generic[_ModelT]):
    model_class: type[_ModelT]
    filters: dict[str, Any]
    order_field: str | None = None
    limit_value: int | None = None
    offset_value: int | None = None

    def filter_eq(self, **kwargs: Any) -> "Query[_ModelT]":
        merged = dict(self.filters)
        merged.update(kwargs)
        # Validate field names eagerly when the schema is already bound so the
        # error points at the call site rather than `.all()`.
        if self.model_class._iris_state.bound:
            valid_fields = set(self.model_class._iris_state.bound_schema.property_map)
            unknown = set(kwargs) - valid_fields
            if unknown:
                raise ValueError(
                    f"Unknown field(s) for {self.model_class.__name__}: "
                    + ", ".join(sorted(unknown))
                )
        return Query(self.model_class, merged, self.order_field, self.limit_value, self.offset_value)

    def order_by(self, field: str) -> "Query[_ModelT]":
        return Query(self.model_class, dict(self.filters), field, self.limit_value, self.offset_value)

    def limit(self, value: int) -> "Query[_ModelT]":
        return Query(self.model_class, dict(self.filters), self.order_field, value, self.offset_value)

    def offset(self, value: int) -> "Query[_ModelT]":
        return Query(self.model_class, dict(self.filters), self.order_field, self.limit_value, value)

    def all(self) -> list[_ModelT]:
        self.model_class._prepare()
        schema = self.model_class._iris_state.bound_schema
        valid_fields = set(schema.property_map)
        for key in self.filters:
            if key not in valid_fields:
                raise ValueError(f"Unknown field for {self.model_class.__name__}: {key}")
        if self.order_field and self.order_field not in valid_fields:
            raise ValueError(f"Unknown order_by field for {self.model_class.__name__}: {self.order_field}")
        rows = self.model_class._runtime().query_rows(
            self.model_class._iris_state.classname,
            list(valid_fields),
            self.filters,
            order_by=self.order_field,
            limit=self.limit_value,
            offset=self.offset_value,
        )
        return [self.model_class._instance_from_row(row) for row in rows]

    def first(self) -> _ModelT | None:
        rows = self.limit(1).all()
        return rows[0] if rows else None


# ---------------------------------------------------------------------------
# IRISModel
# ---------------------------------------------------------------------------

class IRISModel:
    _iris_state: ClassVar[_IrisClassState] = _IrisClassState()  # type: ignore[assignment]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._initialize_iris_subclass()

    def __init__(self, **kwargs: Any) -> None:
        model_class = type(self)
        if model_class._normalized_mode() == "observe" and not model_class._iris_state.bound:
            model_class._prepare()
        object.__setattr__(self, "_iris_id", kwargs.pop("id", None))
        object.__setattr__(self, "_iris_data", {})
        for name, field_def in model_class._iris_state.declared_fields.items():
            if not field_def.has_default:
                continue
            object.__getattribute__(self, "_iris_data")[name] = copy.deepcopy(field_def.default)
        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def pk(self) -> Any:
        return object.__getattribute__(self, "_iris_id")

    @property
    def is_new(self) -> bool:
        """``True`` if this instance has not yet been saved to IRIS (no ``pk``)."""
        return object.__getattribute__(self, "_iris_id") is None

    def __repr__(self) -> str:
        cls_name = type(self).__name__
        pk = object.__getattribute__(self, "_iris_id")
        data = object.__getattribute__(self, "_iris_data")
        fields_str = ", ".join(f"{k}={v!r}" for k, v in data.items())
        pk_str = f"pk={pk!r}, " if pk is not None else ""
        return f"{cls_name}({pk_str}{fields_str})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IRISModel):
            return NotImplemented
        if type(self) is not type(other):
            return False
        self_pk = object.__getattribute__(self, "_iris_id")
        other_pk = object.__getattribute__(other, "_iris_id")
        if self_pk is None or other_pk is None:
            return self is other
        return self_pk == other_pk

    def __hash__(self) -> int:
        pk = object.__getattribute__(self, "_iris_id")
        if pk is None:
            return id(self)
        return hash((type(self), pk))

    @classmethod
    def _initialize_iris_subclass(cls) -> None:
        meta_options = _read_meta_options(cls)
        _warn_deprecated_class_metadata(cls, meta_options)

        # Find nearest ancestor state to inherit configurable defaults from.
        parent_state = next(
            (base.__dict__["_iris_state"] for base in cls.__mro__[1:] if "_iris_state" in base.__dict__),
            _IrisClassState(),
        )
        # Create a fresh state for this subclass, inheriting configurable fields
        # from the parent but resetting all runtime-only state.
        cls._iris_state = dataclasses.replace(
            parent_state,
            bound=False,
            bound_schema=None,
            prepared_state=None,
            native_proxy_names=set(),
            native_proxy_version=None,
            # Deep-copy mutable collections to avoid aliasing with parent
            indexes=list(parent_state.indexes),
            parameters=dict(parent_state.parameters),
            declared_fields={},  # rebuilt below from annotations
        )

        # Migrate any legacy direct-attribute definitions (e.g. _iris_classname = "User.Foo").
        for legacy_name, state_field in _LEGACY_ATTR_TO_STATE_FIELD.items():
            if legacy_name in cls.__dict__:
                setattr(cls._iris_state, state_field, cls.__dict__[legacy_name])

        cls._apply_meta_options(meta_options)
        cls._ensure_default_classname(meta_options)

        # Normalize mutable fields
        cls._iris_state.indexes = _normalize_indexes(cls._iris_state.indexes)
        cls._iris_state.parameters = {str(k): str(v) for k, v in dict(cls._iris_state.parameters).items()}
        if not isinstance(cls._iris_state.storage, StorageDefinition):
            validate_storage_definition_dict(cls._iris_state.storage)
            cls._iris_state.storage = StorageDefinition.from_dict(cls._iris_state.storage)
        cls._iris_state.mode = cls._normalized_mode()

        # Build declared_fields by inheriting parent declared_fields then adding own annotations.
        declared_fields: dict[str, FieldDefinition] = {}
        for base in reversed(cls.__mro__[1:]):
            base_state = base.__dict__.get("_iris_state")
            if base_state is not None and base_state.declared_fields:
                declared_fields.update(
                    {name: _clone_field_definition(item) for name, item in base_state.declared_fields.items()}
                )

        resolved = _safe_type_hints(cls)
        raw_annotations = dict(getattr(cls, "__annotations__", {}))
        for attr_name, raw_annotation in raw_annotations.items():
            if attr_name.startswith("_"):
                continue
            python_type, annotated_field = _split_annotated(resolved.get(attr_name, raw_annotation))
            class_value = cls.__dict__.get(attr_name, MISSING)
            if isinstance(class_value, Field):
                field_def = _clone_field_definition(class_value)
            elif annotated_field is not None:
                field_def = annotated_field
            else:
                field_def = Field(default=class_value) if class_value is not MISSING else Field()
            field_def.prop_name = attr_name
            field_def.python_type = python_type
            if not field_def.iris_type:
                field_def.iris_type = python_type_to_iris(python_type)
            declared_fields[attr_name] = field_def

        for attr_name, class_value in cls.__dict__.items():
            if attr_name.startswith("_") or attr_name in declared_fields or not isinstance(class_value, Field):
                continue
            field_def = _clone_field_definition(class_value)
            field_def.prop_name = attr_name
            field_def.python_type = field_def.python_type or str
            if not field_def.iris_type:
                field_def.iris_type = python_type_to_iris(field_def.python_type)
            declared_fields[attr_name] = field_def

        cls._iris_state.declared_fields = declared_fields
        cls._install_field_descriptors()

        classname = str(cls._iris_state.classname or "")
        if classname:
            _MODEL_REGISTRY[classname] = cls
            cls._install_native_class_proxies()

    @classmethod
    def _apply_meta_options(cls, meta_options: dict[str, Any]) -> None:
        for meta_name, state_field in _META_TO_IRIS_ATTRS.items():
            if meta_name not in meta_options:
                continue
            value = meta_options[meta_name]
            if meta_name == "indexes":
                value = _normalize_indexes(value)
            elif meta_name == "parameters":
                value = {str(k): str(v) for k, v in dict(value).items()}
            elif meta_name == "storage":
                validate_storage_definition_dict(value, source_name="Meta.storage")
                value = StorageDefinition.from_dict(value)
            setattr(cls._iris_state, state_field, value)

    @classmethod
    def _ensure_default_classname(cls, meta_options: dict[str, Any]) -> None:
        explicit_meta = "classname" in meta_options
        explicit_legacy = "_iris_classname" in cls.__dict__
        if explicit_meta or explicit_legacy or cls._iris_state.classname:
            return
        cls._iris_state.classname = f"User.{cls.__name__}"

    @classmethod
    def _install_field_descriptors(cls) -> None:
        for name in cls._iris_state.declared_fields:
            setattr(cls, name, _ModelFieldDescriptor(name))

    @classmethod
    def _install_native_class_proxies(cls) -> None:
        classname = str(cls._iris_state.classname or "")
        if not classname:
            return
        try:
            version = cls._runtime_version()
            runtime = cls._runtime()
            native_class = runtime.native_class(classname)
        except Exception:
            return

        if cls._iris_state.native_proxy_version == version and cls._iris_state.native_proxy_names:
            return

        for name in cls._iris_state.native_proxy_names:
            if isinstance(cls.__dict__.get(name), _NativeClassAttributeProxy):
                delattr(cls, name)
        cls._iris_state.native_proxy_names = set()

        for name in dir(native_class):
            if name.startswith("_") or hasattr(cls, name):
                continue
            try:
                getattr(native_class, name)
            except Exception:
                continue
            setattr(cls, name, _NativeClassAttributeProxy(name))
            cls._iris_state.native_proxy_names.add(name)
        cls._iris_state.native_proxy_version = version

    @classmethod
    def _normalized_mode(cls) -> str:
        raw = str(cls._iris_state.mode or "extend").strip()
        if raw not in _VALID_MODES:
            raise ValueError(
                f"Unsupported _iris_mode: {raw!r}. "
                f"Valid modes are: {', '.join(sorted(_VALID_MODES))}."
            )
        return raw

    @classmethod
    def _runtime(cls) -> Any:
        from .runtime import _get_runtime
        return _get_runtime()

    @classmethod
    def _runtime_version(cls) -> int:
        from .runtime import _runtime_version
        return _runtime_version()

    @classmethod
    def _prepare(cls) -> None:
        classname = str(cls._iris_state.classname)
        mode = cls._normalized_mode()
        runtime = cls._runtime()
        generation = cls._runtime_version()
        compiler = SchemaCompiler(runtime)

        if mode == "observe":
            live = compiler.class_from_iris(classname)
            live_dict = live.to_dict()
            cached = cls._iris_state.prepared_state
            if cached == (generation, {"mode": "observe", "schema": live_dict}):
                return
            bind_schema(cls, live)
            cls._iris_state.prepared_state = (generation, {"mode": "observe", "schema": live_dict})
            cls._install_native_class_proxies()
            return

        desired = SchemaCompiler().compile_model(cls)
        if mode == "replace":
            desired_dict = desired.to_dict()
            cached = cls._iris_state.prepared_state
            if cached == (generation, {"mode": "replace", "schema": desired_dict}):
                return
            try:
                live = compiler.class_from_iris(classname)
            except LookupError:
                live = None
            if live is None or not schema_equals(live, desired if desired.storage is not None else dataclasses.replace(desired, storage=live.storage)):
                runtime.replace_class(desired)
            bind_schema(cls, desired)
            cls._iris_state.prepared_state = (generation, {"mode": "replace", "schema": desired_dict})
            cls._install_native_class_proxies()
            return

        try:
            live = compiler.class_from_iris(classname)
        except LookupError:
            live = None
        extended = desired if live is None else merge_additive_schema(live, desired)
        extended_dict = extended.to_dict()
        cached = cls._iris_state.prepared_state
        if cached == (generation, {"mode": "extend", "schema": extended_dict}):
            return
        if live is None or not schema_equals(live, extended):
            runtime.replace_class(extended)
        bind_schema(cls, extended)
        cls._iris_state.prepared_state = (generation, {"mode": "extend", "schema": extended_dict})
        cls._install_native_class_proxies()

    @classmethod
    def bind(cls) -> type[Self]:
        cls._prepare()
        return cls

    @classmethod
    def plan(cls) -> SchemaPlan:
        compiled = SchemaCompiler().compile_model(cls)
        try:
            live = SchemaCompiler(cls._runtime()).class_from_iris(cls._iris_state.classname)
        except LookupError:
            live = None
        mode = cls._normalized_mode()
        if mode == "observe" and live is not None:
            desired = live
        elif mode == "extend" and live is not None:
            desired = merge_additive_schema(live, compiled)
        else:
            desired = compiled
        return SchemaPlan(classname=desired.name, desired=desired, live=live)

    @classmethod
    def sync(cls) -> SchemaPlan:
        plan = cls.plan()
        if cls._normalized_mode() != "observe":
            cls._runtime().replace_class(plan.desired)
        bind_schema(cls, plan.desired)
        cls._iris_state.prepared_state = (
            cls._runtime_version(),
            {"mode": cls._normalized_mode(), "schema": plan.desired.to_dict()},
        )
        cls._install_native_class_proxies()
        return plan

    @classmethod
    def get(cls, obj_id: Any) -> Self | None:
        cls._prepare()
        row = cls._runtime().open_object(cls._iris_state.classname, obj_id)
        if row is None:
            return None
        return cls._instance_from_row({"id": row["id"], **row["data"]})

    @classmethod
    def query(cls) -> Query[Self]:
        return Query(cls, {})

    @classmethod
    def where(cls, **kwargs: Any) -> Query[Self]:
        return cls.query().filter_eq(**kwargs)

    @classmethod
    def all(cls) -> list[Self]:
        return cls.query().all()

    def save(self) -> Self:
        model_class = type(self)
        model_class._prepare()
        obj_id = model_class._runtime().save_object(
            model_class._iris_state.classname, dict(self._iris_data), self.pk
        )
        object.__setattr__(self, "_iris_id", obj_id)
        return self

    def delete(self) -> None:
        model_class = type(self)
        model_class._prepare()
        if self.pk is not None:
            model_class._runtime().delete_object(model_class._iris_state.classname, self.pk)

    @classmethod
    def transaction(cls) -> contextlib.AbstractContextManager[None]:
        return _transaction_ctx(cls._runtime())

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        obj_id = object.__getattribute__(self, "_iris_id")
        if obj_id is None:
            raise AttributeError(name)
        try:
            model_class = type(self)
            model_class._prepare()
            native_obj = model_class._runtime().open_native_object(
                model_class._iris_state.classname, obj_id
            )
            if native_obj is None:
                raise AttributeError(name)
            native_attr = getattr(native_obj, name)
        except Exception as exc:
            raise AttributeError(name) from exc
        if callable(native_attr):

            def _instance_method_proxy(*args: Any, **kwargs: Any) -> Any:
                return native_attr(*args, **kwargs)

            _instance_method_proxy.__name__ = name
            return _instance_method_proxy
        return native_attr

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        declared = type(self)._iris_state.declared_fields
        if name in declared:
            object.__getattribute__(self, "_iris_data")[name] = value
            return
        object.__setattr__(self, name, value)

    @classmethod
    def _instance_from_row(cls: type[Self], row: dict[str, Any]) -> Self:
        obj = cls()
        schema = cls._iris_state.bound_schema
        converted: dict[str, Any] = {}
        for key, value in row.items():
            if key == "id":
                continue
            if schema is not None and key in schema.property_map:
                iris_type = schema.property_map[key].iris_type
                converted[key] = cls._coerce_python_value(value, iris_type)
            else:
                converted[key] = value
        object.__setattr__(obj, "_iris_id", row.get("id"))
        object.__setattr__(obj, "_iris_data", converted)
        return obj

    @staticmethod
    def _coerce_python_value(value: Any, iris_type: str) -> Any:
        return coerce_to_python(value, iris_type)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _transaction_ctx(runtime: Any):  # type: ignore[return]
    runtime.begin()
    try:
        yield
    except Exception:
        runtime.rollback()
        raise
    else:
        runtime.commit()


def bind_schema(model_class: type, schema_class: Any) -> type:
    existing: dict[str, FieldDefinition] = {}
    for prop in schema_class.properties:
        field_def = Field()
        field_def.prop_name = prop.name
        field_def.required = prop.required
        field_def.maxlen = prop.maxlen
        field_def.description = prop.description
        field_def.iris_type = prop.iris_type
        field_def.parameters = dict(prop.parameters)
        field_def.python_type = iris_type_to_python(prop.iris_type)
        field_def.has_default = prop.default != ""
        field_def.default = python_default_value(prop.default, prop.iris_type)
        existing[prop.name] = field_def
    state = model_class._iris_state  # type: ignore[attr-defined]
    state.declared_fields = existing
    model_class._install_field_descriptors()  # type: ignore[attr-defined]
    state.indexes = [item.to_dict() for item in schema_class.indexes]
    state.parameters = dict(schema_class.parameters)
    state.storage = copy.deepcopy(schema_class.storage)
    state.superclasses = (
        list(schema_class.superclasses)
        if len(schema_class.superclasses) > 1
        else schema_class.superclasses[0]
    )
    state.bound_schema = schema_class
    state.bound = True
    return model_class


class IRISMeta(type):
    pass


def _read_meta_options(cls: type) -> dict[str, Any]:
    meta = cls.__dict__.get("Meta")
    if meta is None:
        return {}
    return {
        name: getattr(meta, name)
        for name in _META_TO_IRIS_ATTRS
        if hasattr(meta, name)
    }


def _warn_deprecated_class_metadata(cls: type, meta_options: dict[str, Any]) -> None:
    for name in sorted(_DEPRECATED_CLASS_METADATA):
        if name not in cls.__dict__:
            continue
        state_field = _LEGACY_ATTR_TO_STATE_FIELD.get(name, name)
        if state_field in meta_options:
            continue  # Meta took precedence; no warning needed
        warnings.warn(
            f"{cls.__name__}.{name} is deprecated; use class Meta.{state_field} instead.",
            DeprecationWarning,
            stacklevel=3,
        )


def _normalize_indexes(values: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in list(values or []):
        if isinstance(item, IndexDefinition):
            items.append(item.to_dict())
        elif hasattr(item, "to_dict") and callable(item.to_dict):
            items.append(item.to_dict())
        elif isinstance(item, dict):
            items.append(copy.deepcopy(item))
        else:
            raise TypeError(f"Unsupported index definition: {item!r}")
    return items
