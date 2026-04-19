from __future__ import annotations

from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, get_type_hints

import iris_orm.models
from iris_orm.codecs import coerce_value_for_load, coerce_value_for_save, resolve_declared_type
from iris_orm.runtime import get_runtime

TModel = TypeVar("TModel", bound="iris_orm.models.IRISModel")


def _is_model_type(value: Any) -> bool:
    return isinstance(value, type) and issubclass(value, iris_orm.models.IRISModel)


def _is_serial_type(model_cls: Type[iris_orm.models.IRISModel]) -> bool:
    superclasses = getattr(model_cls, "_superclasses", "") or ""
    return "SerialObject" in superclasses


def _build_model_from_iris_obj(
    model_cls: Type[TModel],
    iris_obj: Any,
) -> Optional[TModel]:
    if iris_obj is None:
        return None

    runtime = get_runtime()
    params = {}
    hints = get_type_hints(model_cls, include_extras=True)
    for field_name in model_cls._fields:
        raw_val = runtime.get_property(iris_obj, field_name)
        python_val = runtime.extract_python_value(raw_val)
        declared_type = resolve_declared_type(hints.get(field_name))
        if _is_model_type(declared_type):
            params[field_name] = _build_model_from_iris_obj(declared_type, python_val)
        else:
            params[field_name] = coerce_value_for_load(declared_type, python_val)

    instance = model_cls(**params)
    instance._iris_obj = iris_obj
    if not _is_serial_type(model_cls):
        obj_id = runtime.get_object_id(iris_obj)
        if obj_id:
            instance._pk = str(obj_id)
    return instance


def _materialize_related_value(runtime: Any, declared_type: Any, value: Any) -> Any:
    if value is None:
        return None
    if not _is_model_type(declared_type):
        return coerce_value_for_save(declared_type, value)

    if not isinstance(value, declared_type):
        raise TypeError(
            f"Expected {declared_type.__name__} for related object, got {type(value).__name__}"
        )

    if _is_serial_type(declared_type):
        iris_obj = value._iris_obj
        if iris_obj is None:
            iris_obj = runtime.create_object(declared_type._classname)
        hints = get_type_hints(declared_type, include_extras=True)
        for field_name in declared_type._fields:
            if field_name in value.__dict__:
                nested_value = getattr(value, field_name)
                nested_type = resolve_declared_type(hints.get(field_name))
                runtime.inject_iris_value(
                    iris_obj,
                    field_name,
                    _materialize_related_value(runtime, nested_type, nested_value),
                )
        value._iris_obj = iris_obj
        return iris_obj

    save_model(value)
    if value._iris_obj is not None:
        return value._iris_obj
    if value.pk is not None:
        return runtime.get_object(declared_type._classname, value.pk)
    return value


class QuerySet(Generic[TModel]):
    def __init__(
        self,
        model_cls: Type[TModel],
        filter_kwargs: Optional[Dict[str, Any]] = None,
        order_by_keys: Optional[List[str]] = None,
    ):
        self.model_cls = model_cls
        self.filter_kwargs = filter_kwargs or {}
        self.order_by_keys = order_by_keys or []

    def where(self, **kwargs) -> QuerySet[TModel]:
        new_kwargs = self.filter_kwargs.copy()
        new_kwargs.update(kwargs)
        return QuerySet(self.model_cls, new_kwargs, self.order_by_keys)

    def order_by(self, *keys: str) -> QuerySet[TModel]:
        new_keys = self.order_by_keys.copy()
        new_keys.extend(keys)
        return QuerySet(self.model_cls, self.filter_kwargs, new_keys)

    def all(self) -> List[TModel]:
        runtime = get_runtime()

        table_name = self.model_cls._classname  # Schema.Table
        sql = f"SELECT ID FROM {table_name}"
        params = []
        if self.filter_kwargs:
            conditions = []
            for k, v in self.filter_kwargs.items():
                conditions.append(f"{k} = ?")
                params.append(v)
            sql += " WHERE " + " AND ".join(conditions)

        if self.order_by_keys:
            sql += " ORDER BY " + ", ".join(self.order_by_keys)

        conn = runtime.get_dbapi_connection()
        cursor = conn.cursor()
        cursor.execute(sql, params)

        results = []
        for row in cursor:
            row_id = row[0]
            obj = self.model_cls.get(str(row_id))
            if obj is not None:
                results.append(obj)

        return results


def save_model(instance: TModel) -> None:
    runtime = get_runtime()
    classname = instance._classname
    hints = get_type_hints(instance.__class__, include_extras=True)

    if instance._pk:
        iris_obj = runtime.get_object(classname, instance._pk)
    else:
        iris_obj = runtime.create_object(classname)
    instance._iris_obj = iris_obj

    for field_name in instance._fields:
        if field_name in instance.__dict__:
            val = getattr(instance, field_name)
            declared_type = resolve_declared_type(hints.get(field_name))
            runtime.inject_iris_value(
                iris_obj,
                field_name,
                _materialize_related_value(runtime, declared_type, val),
            )

    st = runtime.save_object(iris_obj)

    if not runtime.is_ok(st):
        raise RuntimeError(f"Save failed: {st}")

    pk = runtime.get_object_id(iris_obj)
    if pk:
        instance._pk = str(pk)
    instance._iris_obj = iris_obj


def get_model(cls: Type[TModel], pk: str) -> Optional[TModel]:
    runtime = get_runtime()
    iris_obj = runtime.get_object(cls._classname, pk)

    return _build_model_from_iris_obj(cls, iris_obj)


def delete_model(instance: TModel) -> bool:
    if not instance._pk:
        return False
    runtime = get_runtime()
    return runtime.delete_object(instance._classname, instance._pk)
