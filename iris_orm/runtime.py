from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from .adapter import IRISAdapter
from .model import IRISModel, bind_schema
from .schema import SchemaCompiler, SchemaPlan, schema_equals

_ModelT = TypeVar("_ModelT", bound=IRISModel)


@dataclass
class Query(Generic[_ModelT]):
    runtime: "DefaultRuntime"
    model_class: type[_ModelT]
    filters: dict[str, Any]
    order_field: str | None = None
    limit_value: int | None = None
    offset_value: int | None = None

    def filter_eq(self, **kwargs: Any) -> "Query[_ModelT]":
        merged = dict(self.filters)
        merged.update(kwargs)
        return Query(self.runtime, self.model_class, merged, self.order_field, self.limit_value, self.offset_value)

    def order_by(self, field: str) -> "Query[_ModelT]":
        return Query(self.runtime, self.model_class, dict(self.filters), field, self.limit_value, self.offset_value)

    def limit(self, value: int) -> "Query[_ModelT]":
        return Query(self.runtime, self.model_class, dict(self.filters), self.order_field, value, self.offset_value)

    def offset(self, value: int) -> "Query[_ModelT]":
        return Query(self.runtime, self.model_class, dict(self.filters), self.order_field, self.limit_value, value)

    def all(self) -> list[_ModelT]:
        self.runtime.prepare(self.model_class)
        schema = self.model_class._iris_bound_schema
        valid_fields = set(schema.property_map)
        for key in self.filters:
            if key not in valid_fields:
                raise ValueError(f"Unknown field for {self.model_class.__name__}: {key}")
        if self.order_field and self.order_field not in valid_fields:
            raise ValueError(f"Unknown order_by field for {self.model_class.__name__}: {self.order_field}")
        rows = self.runtime.adapter.query_rows(
            self.model_class._iris_classname,
            list(valid_fields),
            self.filters,
            order_by=self.order_field,
            limit=self.limit_value,
            offset=self.offset_value,
        )
        return [self.runtime._instance_from_row(self.model_class, row) for row in rows]

    def first(self) -> _ModelT | None:
        rows = self.limit(1).all()
        return rows[0] if rows else None


class DefaultRuntime:
    def __init__(self) -> None:
        self._adapter: IRISAdapter | None = None
        self._prepared: dict[str, dict[str, Any]] = {}

    @property
    def adapter(self) -> IRISAdapter:
        if self._adapter is None:
            self._adapter = IRISAdapter()
        return self._adapter

    def bind_existing(self, classname: str, *, model_name: str | None = None) -> type[IRISModel]:
        name = model_name or classname.split(".")[-1]
        model_class = type(name, (IRISModel,), {"_iris_classname": classname, "_iris_mode": "proxy"})
        return self.bind(model_class)

    def bind(self, model_class: type[_ModelT]) -> type[_ModelT]:
        self.prepare(model_class)
        return model_class

    def plan(self, model_class: type[IRISModel]) -> SchemaPlan:
        desired = SchemaCompiler().compile_model(model_class)
        try:
            live = SchemaCompiler(self.adapter).class_from_iris(model_class._iris_classname)
        except LookupError:
            live = None
        return SchemaPlan(classname=desired.name, desired=desired, live=live)

    def sync(self, model_class: type[IRISModel]) -> SchemaPlan:
        desired = SchemaCompiler().compile_model(model_class)
        plan = self.plan(model_class)
        self.adapter.replace_class(desired)
        bind_schema(model_class, desired)
        self._prepared[desired.name] = {"mode": "python", "schema": desired.to_dict()}
        return plan

    def prepare(self, model_class: type[IRISModel]) -> None:
        classname = str(model_class._iris_classname)
        mode = str(getattr(model_class, "_iris_mode", "python") or "python").strip().lower()
        if mode == "python":
            desired = SchemaCompiler().compile_model(model_class)
            cached = self._prepared.get(classname)
            desired_dict = desired.to_dict()
            if cached != {"mode": "python", "schema": desired_dict}:
                try:
                    live = SchemaCompiler(self.adapter).class_from_iris(classname)
                except LookupError:
                    live = None
                if live is None or not schema_equals(live, desired):
                    self.adapter.replace_class(desired)
                bind_schema(model_class, desired)
                self._prepared[classname] = {"mode": "python", "schema": desired_dict}
            return

        live = SchemaCompiler(self.adapter).class_from_iris(classname)
        bind_schema(model_class, live)
        self._prepared[classname] = {"mode": "proxy", "schema": live.to_dict()}

    def get(self, model_class: type[_ModelT], obj_id: Any) -> _ModelT | None:
        self.prepare(model_class)
        row = self.adapter.open_object(model_class._iris_classname, obj_id)
        if row is None:
            return None
        return self._instance_from_row(model_class, {"id": row["id"], **row["data"]})

    def query(self, model_class: type[_ModelT]) -> Query[_ModelT]:
        return Query(self, model_class, {})

    def save(self, instance: Any) -> Any:
        self.prepare(type(instance))
        obj_id = self.adapter.save_object(type(instance)._iris_classname, dict(instance._iris_data), instance.pk)
        object.__setattr__(instance, "_iris_id", obj_id)
        return instance

    def delete(self, instance: Any) -> None:
        self.prepare(type(instance))
        if instance.pk is not None:
            self.adapter.delete_object(type(instance)._iris_classname, instance.pk)

    def _instance_from_row(self, model_class: type[_ModelT], row: dict[str, Any]) -> _ModelT:
        obj = model_class()
        schema = getattr(model_class, "_iris_bound_schema", None)
        converted: dict[str, Any] = {}
        for key, value in row.items():
            if key == "id":
                continue
            if schema is not None and key in schema.property_map:
                iris_type = schema.property_map[key].iris_type
                converted[key] = self._coerce_python_value(value, iris_type)
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


_DEFAULT_RUNTIME = DefaultRuntime()


def get_default_runtime() -> DefaultRuntime:
    return _DEFAULT_RUNTIME


def configure_default_runtime(*, adapter: IRISAdapter | None = None) -> DefaultRuntime:
    if adapter is not None:
        _DEFAULT_RUNTIME._adapter = adapter
    _DEFAULT_RUNTIME._prepared = {}
    return _DEFAULT_RUNTIME


def reset_default_runtime() -> DefaultRuntime:
    _DEFAULT_RUNTIME._adapter = None
    _DEFAULT_RUNTIME._prepared = {}
    return _DEFAULT_RUNTIME


def bind_existing(classname: str, *, model_name: str | None = None) -> type:
    return _DEFAULT_RUNTIME.bind_existing(classname, model_name=model_name)
