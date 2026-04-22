from __future__ import annotations

from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, get_args, get_origin

import iris_orm.models
from iris_orm.codecs import coerce_value_for_load, coerce_value_for_save, resolve_declared_type
from iris_orm.runtime import get_runtime

TModel = TypeVar("TModel", bound="iris_orm.models.Model")


def _is_model_type(value: Any) -> bool:
    return isinstance(value, type) and issubclass(value, iris_orm.models.Model)


def _is_serial_type(model_cls: Type[iris_orm.models.Model]) -> bool:
    superclasses = getattr(model_cls, "_superclasses", "") or ""
    return "SerialObject" in superclasses


def _collection_value_type(declared_type: Any) -> tuple[str | None, Any]:
    origin = get_origin(declared_type)
    if origin in (list, List):
        args = get_args(declared_type)
        element_type = resolve_declared_type(args[0]) if args else Any
        return ("list", element_type)
    if origin in (dict, Dict):
        args = get_args(declared_type)
        element_type = resolve_declared_type(args[1]) if len(args) == 2 else Any
        return ("array", element_type)
    return (None, None)


def _is_percent_list_field(field_meta: Any | None) -> bool:
    return getattr(field_meta, "iris_type", None) in {"%List", "%Library.List"}


def _is_scalar_string_field(field_meta: Any | None) -> bool:
    if field_meta is None or getattr(field_meta, "collection", None):
        return False
    return getattr(field_meta, "iris_type", None) in {
        "%String",
        "%RawString",
        "%Library.String",
        "%Library.RawString",
    }


def _coerce_collection_for_load(
    collection_kind: str,
    element_type: Any,
    value: Any,
) -> Any:
    if collection_kind == "list" and isinstance(value, list):
        if _is_model_type(element_type):
            return [_build_model_from_iris_obj(element_type, item) for item in value]
        return [coerce_value_for_load(element_type, item) for item in value]
    if collection_kind == "array" and isinstance(value, dict):
        if _is_model_type(element_type):
            return {
                str(key): _build_model_from_iris_obj(element_type, item)
                for key, item in value.items()
            }
        return {str(key): coerce_value_for_load(element_type, item) for key, item in value.items()}
    return value


def _build_model_from_iris_obj(
    model_cls: Type[TModel],
    iris_obj: Any,
    known_pk: Optional[str] = None,
) -> Optional[TModel]:
    if iris_obj is None:
        return None

    runtime = get_runtime()
    params = {}
    for field_name, model_field in model_cls.__model_fields__.items():
        field_meta = model_field.field_info
        declared_type = model_field.declared_type
        raw_val = runtime.get_property(iris_obj, field_name)
        if model_field._is_percent_list:           # ← pre-computed
            python_val = runtime.decode_percent_list(raw_val)
        else:
            python_val = runtime.extract_python_value(raw_val)
            if python_val in (None, 0) and (
                model_field._is_scalar_string or declared_type is str
            ):
                python_val = ""
        collection_kind = model_field._collection_kind  # ← pre-computed
        if collection_kind is not None:
            params[field_name] = _coerce_collection_for_load(
                collection_kind, model_field._element_type, python_val   # ← pre-computed
            )
        elif model_field._is_model_field:          # ← new pre-computed flag
            params[field_name] = _build_model_from_iris_obj(declared_type, python_val)
        else:
            params[field_name] = coerce_value_for_load(declared_type, python_val)
    instance = model_cls._from_loaded_values(params)
    instance._iris_obj = iris_obj
    if not _is_serial_type(model_cls):
        if known_pk is not None:
            instance._pk = known_pk
        else:
            obj_id = runtime.get_object_id(iris_obj)
            if obj_id:
                instance._pk = str(obj_id)
    return instance


def _materialize_related_value(runtime: Any, declared_type: Any, value: Any) -> Any:
    if value is None:
        return None
    collection_kind, element_type = _collection_value_type(declared_type)
    if collection_kind == "list" and isinstance(value, list):
        if _is_model_type(element_type):
            return [
                _materialize_related_value(runtime, element_type, item)
                for item in value
            ]
        return [coerce_value_for_save(element_type, item) for item in value]
    if collection_kind == "array" and isinstance(value, dict):
        if _is_model_type(element_type):
            return {
                str(key): _materialize_related_value(runtime, element_type, item)
                for key, item in value.items()
            }
        return {str(key): coerce_value_for_save(element_type, item) for key, item in value.items()}
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
        for field_name, nested_model_field in declared_type.__model_fields__.items():
            if field_name in value.__dict__:
                nested_value = getattr(value, field_name)
                nested_type = nested_model_field.declared_type
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


def _resolve_sql_field_name(model_cls: Type[TModel], field_name: str) -> str:
    field_meta = model_cls._fields.get(field_name)
    if field_meta is not None and getattr(field_meta, "sql_field_name", None):
        return field_meta.sql_field_name
    return field_name


def _resolve_sql_table_name(model_cls: Type[TModel]) -> str:
    cached = getattr(model_cls, "_sql_table_name", None)
    if cached:
        return cached

    runtime = get_runtime()
    row = None
    try:
        conn = runtime.get_dbapi_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                (
                    "SELECT SqlTableName, SqlSchemaName "
                    "FROM %Dictionary.CompiledClass WHERE Name = ?"
                ),
                (model_cls._classname,),
            )
            if hasattr(cursor, "fetchone"):
                fetched_row = cursor.fetchone()
                row = tuple(fetched_row) if fetched_row is not None else None
            elif hasattr(cursor, "fetchall"):
                rows = cursor.fetchall()
                row = tuple(rows[0]) if rows else None
        finally:
            close = getattr(cursor, "close", None)
            if callable(close):
                close()
            close = getattr(conn, "close", None)
            if callable(close):
                close()
    except Exception:
        row = None

    if row is not None:
        sql_table_name, sql_schema_name = row
        if sql_table_name:
            resolved = (
                f"{sql_schema_name}.{sql_table_name}"
                if sql_schema_name
                else str(sql_table_name)
            )
            setattr(model_cls, "_sql_table_name", resolved)
            return resolved

    class_metadata = getattr(model_cls, "_class_metadata", None)
    if class_metadata is not None and getattr(class_metadata, "sql_table_name", None):
        resolved = class_metadata.sql_table_name
        setattr(model_cls, "_sql_table_name", resolved)
        return resolved

    resolved = model_cls._classname
    setattr(model_cls, "_sql_table_name", resolved)
    return resolved


def _maybe_auto_sync_schema(model_cls: Type[TModel]) -> None:
    if not getattr(model_cls, "_auto_sync", False):
        return

    mode = getattr(model_cls, "_sync_mode", "extend")
    if mode == "observe":
        raise RuntimeError(
            f"{model_cls.__name__} enables `Meta.auto_sync`, but mode='observe' never writes schema. "
            "Disable auto-sync or call `Model.sync_schema()` explicitly in a writable mode."
        )
    if mode == "replace":
        raise RuntimeError(
            f"{model_cls.__name__} enables `Meta.auto_sync`, but mode='replace' is destructive. "
            "Call `Model.sync_schema()` explicitly instead of auto-syncing on save."
        )

    model_cls.sync_schema()


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

        table_name = _resolve_sql_table_name(self.model_cls)
        sql = f"SELECT ID FROM {table_name}"
        params = []
        if self.filter_kwargs:
            conditions = []
            for k, v in self.filter_kwargs.items():
                conditions.append(f"{_resolve_sql_field_name(self.model_cls, k)} = ?")
                params.append(v)
            sql += " WHERE " + " AND ".join(conditions)

        if self.order_by_keys:
            sql += " ORDER BY " + ", ".join(
                _resolve_sql_field_name(self.model_cls, key) for key in self.order_by_keys
            )

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
    cls = instance.__class__
    classname = instance._classname

    if cls._auto_sync:
        _maybe_auto_sync_schema(cls)
    if cls._validate_on_init:
        # Only validate on save when the model also validates on init; models
        # that opt out of init-time validation (validate_on_init=False) are
        # trusted to be well-formed by the time save() is called.
        instance._validate_for_save()

    is_update = bool(instance._pk)
    if is_update:
        iris_obj = runtime.get_object(classname, instance._pk)
    else:
        iris_obj = runtime.create_object(classname)
    instance._iris_obj = iris_obj

    inst_dict = instance.__dict__

    # Fast path: primitive scalar fields (str/int/float/bool) — no coercion needed,
    # bypass inject_iris_value dispatch and call set_property directly.
    for field_name in cls._scalar_fast_fields:
        val = inst_dict.get(field_name)
        if val is not None:
            runtime.set_property(iris_obj, field_name, val)

    # Scalar fields that require coercion (e.g. datetime types).
    if cls._scalar_coerce_fields:
        for field_name, declared_type in cls._scalar_coerce_fields:
            val = inst_dict.get(field_name)
            if val is not None:
                runtime.inject_iris_value(iris_obj, field_name, coerce_value_for_save(declared_type, val))

    # Complex fields: collections, related models, readonly.
    if cls._complex_save_fields:
        for field_name, model_field in cls._complex_save_fields:
            if getattr(model_field.field_info, "readonly", False) and is_update:
                continue
            val = inst_dict.get(field_name)
            if val is None:
                continue
            materialized = _materialize_related_value(runtime, model_field.declared_type, val)
            runtime.inject_iris_value(iris_obj, field_name, materialized, field_meta=model_field.field_info)

    st = runtime.save_object(iris_obj)

    if not runtime.is_ok(st):
        raise RuntimeError(f"Save failed for {classname}: {runtime.format_status(st)}")

    pk = runtime.get_object_id(iris_obj)
    if pk:
        instance._pk = str(pk)
    instance._iris_obj = iris_obj


def get_model(cls: Type[TModel], pk: str) -> Optional[TModel]:
    runtime = get_runtime()
    iris_obj = runtime.get_object(cls._classname, pk)

    return _build_model_from_iris_obj(cls, iris_obj, known_pk=pk)


def delete_model(instance: TModel) -> bool:
    if not instance._pk:
        return False
    runtime = get_runtime()
    return runtime.delete_object(instance._classname, instance._pk)
