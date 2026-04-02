from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Self, TypeVar, get_type_hints

from .fields import FieldDefinition, _SENTINEL
from .schema import (
    SchemaCompiler,
    SchemaPlan,
    iris_type_to_python,
    python_default_value,
    python_type_to_iris,
    schema_equals,
)

_MODEL_REGISTRY: dict[str, type] = {}
_ModelT = TypeVar("_ModelT", bound="IRISModel")


def _clone_field_definition(value: FieldDefinition) -> FieldDefinition:
    cloned = copy.deepcopy(value)
    if value.default is _SENTINEL:
        cloned.default = _SENTINEL
    return cloned


class IRISMeta(type):
    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type:
        annotations = dict(namespace.get("__annotations__", {}))
        cleaned = dict(namespace)
        declared_fields: dict[str, FieldDefinition] = {}
        for attr_name, value in list(cleaned.items()):
            if isinstance(value, FieldDefinition):
                declared_fields[attr_name] = _clone_field_definition(value)
                cleaned.pop(attr_name, None)

        cls = super().__new__(mcs, name, bases, cleaned, **kwargs)

        if not hasattr(cls, "_iris_indexes"):
            cls._iris_indexes = []  # type: ignore[attr-defined]
        if not hasattr(cls, "_iris_parameters"):
            cls._iris_parameters = {}  # type: ignore[attr-defined]
        if not hasattr(cls, "_iris_storage"):
            cls._iris_storage = None  # type: ignore[attr-defined]

        classname = str(getattr(cls, "_iris_classname", "") or "")
        if not classname:
            return cls

        resolved = _safe_type_hints(cls, annotations)
        normalized_fields: dict[str, FieldDefinition] = {}
        for attr_name, annotation in annotations.items():
            if attr_name.startswith("_"):
                continue
            field_def = _clone_field_definition(declared_fields.get(attr_name, FieldDefinition()))
            python_type = resolved.get(attr_name, annotation)
            field_def.prop_name = attr_name
            field_def.python_type = python_type
            if not field_def.iris_type:
                field_def.iris_type = python_type_to_iris(python_type)
            normalized_fields[attr_name] = field_def

        for attr_name, field_def in declared_fields.items():
            if attr_name in normalized_fields:
                continue
            extra = _clone_field_definition(field_def)
            extra.prop_name = attr_name
            extra.python_type = extra.python_type or str
            if not extra.iris_type:
                extra.iris_type = python_type_to_iris(extra.python_type)
            normalized_fields[attr_name] = extra

        cls._iris_declared_fields = normalized_fields  # type: ignore[attr-defined]
        cls._iris_bound = False  # type: ignore[attr-defined]
        cls._iris_bound_schema = None  # type: ignore[attr-defined]
        cls._iris_prepared_state = None  # type: ignore[attr-defined]
        _MODEL_REGISTRY[classname] = cls
        return cls

    def __getattr__(cls, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            cls._prepare()
            native_class = cls._runtime().native_class(cls._iris_classname)
            native_attr = getattr(native_class, name)
        except Exception as exc:
            raise AttributeError(name) from exc
        if callable(native_attr):

            def _class_method_proxy(*args: Any, **kwargs: Any) -> Any:
                return native_attr(*args, **kwargs)

            _class_method_proxy.__name__ = name
            return _class_method_proxy
        return native_attr


def _safe_type_hints(cls: type, annotations: dict[str, Any]) -> dict[str, Any]:
    try:
        return get_type_hints(cls)
    except Exception:
        return annotations


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
        return Query(self.model_class, merged, self.order_field, self.limit_value, self.offset_value)

    def order_by(self, field: str) -> "Query[_ModelT]":
        return Query(self.model_class, dict(self.filters), field, self.limit_value, self.offset_value)

    def limit(self, value: int) -> "Query[_ModelT]":
        return Query(self.model_class, dict(self.filters), self.order_field, value, self.offset_value)

    def offset(self, value: int) -> "Query[_ModelT]":
        return Query(self.model_class, dict(self.filters), self.order_field, self.limit_value, value)

    def all(self) -> list[_ModelT]:
        self.model_class._prepare()
        schema = self.model_class._iris_bound_schema
        valid_fields = set(schema.property_map)
        for key in self.filters:
            if key not in valid_fields:
                raise ValueError(f"Unknown field for {self.model_class.__name__}: {key}")
        if self.order_field and self.order_field not in valid_fields:
            raise ValueError(f"Unknown order_by field for {self.model_class.__name__}: {self.order_field}")
        rows = self.model_class._runtime().query_rows(
            self.model_class._iris_classname,
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


class IRISModel(metaclass=IRISMeta):
    _iris_classname: ClassVar[str] = ""
    _iris_superclasses: ClassVar[str | list[str]] = "%Persistent"
    _iris_mode: ClassVar[str] = "python"
    _iris_storage: ClassVar[dict[str, Any] | None] = None
    _iris_indexes: ClassVar[list[dict[str, Any]]] = []
    _iris_parameters: ClassVar[dict[str, str]] = {}
    _iris_engine: ClassVar[Any] = None  # SQLAlchemy engine; overrides the default runtime
    _iris_declared_fields: ClassVar[dict[str, FieldDefinition]]
    _iris_bound_schema: ClassVar[Any]
    _iris_bound: ClassVar[bool]
    _iris_prepared_state: ClassVar[tuple[int, dict[str, Any]] | None]

    def __init__(self, **kwargs: Any) -> None:
        model_class = type(self)
        if str(getattr(model_class, "_iris_mode", "python") or "python").strip().lower() == "proxy" and not getattr(
            model_class, "_iris_bound", False
        ):
            model_class._prepare()
        object.__setattr__(self, "_iris_id", kwargs.pop("id", None))
        object.__setattr__(self, "_iris_data", {})
        for name, field_def in model_class._iris_declared_fields.items():
            if field_def.default is _SENTINEL:
                continue
            object.__getattribute__(self, "_iris_data")[name] = copy.deepcopy(field_def.default)
        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def pk(self) -> Any:
        return object.__getattribute__(self, "_iris_id")

    @classmethod
    def _runtime(cls) -> Any:
        engine = getattr(cls, "_iris_engine", None)
        if engine is not None:
            # Build and cache a dedicated runtime for this model's engine.
            # Stored in the class's own __dict__ so subclasses don't share it.
            cached = cls.__dict__.get("_iris_engine_runtime")
            if cached is None:
                from .runtime import IRISRuntime
                cached = IRISRuntime(engine=engine)
                cls._iris_engine_runtime = cached  # type: ignore[attr-defined]
            return cached
        from .runtime import _get_runtime
        return _get_runtime()

    @classmethod
    def _runtime_version(cls) -> int:
        engine = getattr(cls, "_iris_engine", None)
        if engine is not None:
            # Use the engine's identity as a stable version token.
            # The engine is kept alive by the class reference so id() won't be reused.
            return id(engine)
        from .runtime import _runtime_version
        return _runtime_version()

    @classmethod
    def _prepare(cls) -> None:
        classname = str(cls._iris_classname)
        mode = str(getattr(cls, "_iris_mode", "python") or "python").strip().lower()
        runtime = cls._runtime()
        generation = cls._runtime_version()
        compiler = SchemaCompiler(runtime)

        if mode == "python":
            desired = SchemaCompiler().compile_model(cls)
            desired_dict = desired.to_dict()
            cached = getattr(cls, "_iris_prepared_state", None)
            if cached == (generation, {"mode": "python", "schema": desired_dict}):
                return
            try:
                live = compiler.class_from_iris(classname)
            except LookupError:
                live = None
            if live is None or not schema_equals(live, desired):
                runtime.replace_class(desired)
            bind_schema(cls, desired)
            cls._iris_prepared_state = (generation, {"mode": "python", "schema": desired_dict})
            return

        live = compiler.class_from_iris(classname)
        live_dict = live.to_dict()
        cached = getattr(cls, "_iris_prepared_state", None)
        if cached == (generation, {"mode": "proxy", "schema": live_dict}):
            return
        bind_schema(cls, live)
        cls._iris_prepared_state = (generation, {"mode": "proxy", "schema": live_dict})

    @classmethod
    def bind(cls) -> type[Self]:
        cls._prepare()
        return cls

    @classmethod
    def plan(cls) -> SchemaPlan:
        desired = SchemaCompiler().compile_model(cls)
        try:
            live = SchemaCompiler(cls._runtime()).class_from_iris(cls._iris_classname)
        except LookupError:
            live = None
        return SchemaPlan(classname=desired.name, desired=desired, live=live)

    @classmethod
    def sync(cls) -> SchemaPlan:
        desired = SchemaCompiler().compile_model(cls)
        plan = cls.plan()
        cls._runtime().replace_class(desired)
        bind_schema(cls, desired)
        cls._iris_prepared_state = (cls._runtime_version(), {"mode": "python", "schema": desired.to_dict()})
        return plan

    @classmethod
    def get(cls, obj_id: Any) -> Self | None:
        cls._prepare()
        row = cls._runtime().open_object(cls._iris_classname, obj_id)
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
        obj_id = model_class._runtime().save_object(model_class._iris_classname, dict(self._iris_data), self.pk)
        object.__setattr__(self, "_iris_id", obj_id)
        return self

    def delete(self) -> None:
        model_class = type(self)
        model_class._prepare()
        if self.pk is not None:
            model_class._runtime().delete_object(model_class._iris_classname, self.pk)

    def __getattr__(self, name: str) -> Any:
        declared = type(self)._iris_declared_fields
        if name in declared:
            return object.__getattribute__(self, "_iris_data").get(name)
        if name.startswith("_"):
            raise AttributeError(name)
        obj_id = object.__getattribute__(self, "_iris_id")
        if obj_id is None:
            raise AttributeError(name)
        try:
            model_class = type(self)
            model_class._prepare()
            native_obj = model_class._runtime().open_native_object(model_class._iris_classname, obj_id)
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
        declared = type(self)._iris_declared_fields
        if name in declared:
            object.__getattribute__(self, "_iris_data")[name] = value
            return
        object.__setattr__(self, name, value)

    @classmethod
    def _instance_from_row(cls: type[Self], row: dict[str, Any]) -> Self:
        obj = cls()
        schema = getattr(cls, "_iris_bound_schema", None)
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
        if value is None:
            return None
        if iris_type == "%Boolean":
            return bool(value)
        if iris_type in {"%Integer", "%SmallInt", "%BigInt"}:
            return int(value)
        if iris_type in {"%Float", "%Double", "%Numeric", "%Decimal"}:
            return float(value)
        return value


def bind_schema(model_class: type, schema_class: Any) -> type:
    existing: dict[str, FieldDefinition] = {}
    for prop in schema_class.properties:
        field_def = FieldDefinition()
        field_def.prop_name = prop.name
        field_def.required = prop.required
        field_def.maxlen = prop.maxlen
        field_def.description = prop.description
        field_def.iris_type = prop.iris_type
        field_def.python_type = iris_type_to_python(prop.iris_type)
        field_def.default = python_default_value(prop.default, prop.iris_type)
        existing[prop.name] = field_def
    model_class._iris_declared_fields = existing  # type: ignore[attr-defined]
    model_class._iris_indexes = [item.to_dict() for item in schema_class.indexes]  # type: ignore[attr-defined]
    model_class._iris_parameters = dict(schema_class.parameters)  # type: ignore[attr-defined]
    model_class._iris_storage = copy.deepcopy(schema_class.storage)  # type: ignore[attr-defined]
    model_class._iris_superclasses = list(schema_class.superclasses) if len(schema_class.superclasses) > 1 else schema_class.superclasses[0]  # type: ignore[attr-defined]
    model_class._iris_bound_schema = schema_class  # type: ignore[attr-defined]
    model_class._iris_bound = True  # type: ignore[attr-defined]
    return model_class
