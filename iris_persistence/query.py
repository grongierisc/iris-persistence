from __future__ import annotations

import warnings
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar, get_args, get_origin

import iris_persistence.models
from iris_persistence.codecs import (
    coerce_value_for_load,
    coerce_value_for_save,
    resolve_declared_type,
)
from iris_persistence.runtime import get_runtime

TModel = TypeVar("TModel", bound="iris_persistence.models.Model")


def _is_model_type(value: Any) -> bool:
    return isinstance(value, type) and issubclass(value, iris_persistence.models.Model)


def _is_serial_type(model_cls: Type[iris_persistence.models.Model]) -> bool:
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

    # Use the per-class code-gen loader when available (direct LOAD_ATTR, 2-3× faster
    # than getattr() for IRIS C-extension objects).
    fast_load = model_cls._fast_load
    if fast_load is not None:
        return fast_load(iris_obj, known_pk)

    d: dict = {}

    # str fields: direct getattr, normalise None/0 → "" (IRIS can return 0 for empty string props)
    for field_name in model_cls._read_str_fields:
        val = getattr(iris_obj, field_name, None)
        d[field_name] = None if val == chr(0) else (val if val else "")

    # int/float fields: direct getattr, IRIS already returns correct Python type
    for field_name in model_cls._read_primitive_fields:
        d[field_name] = getattr(iris_obj, field_name, None)

    # bool fields: IRIS stores as int 0/1, convert without calling coerce_value_for_load
    for field_name in model_cls._read_bool_fields:
        d[field_name] = bool(getattr(iris_obj, field_name, None) or 0)

    # Scalar fields needing full coercion (e.g. datetime): still skip get_property dispatch
    if model_cls._read_coerce_fields:
        runtime = get_runtime()
        for field_name, declared_type in model_cls._read_coerce_fields:
            raw_val = getattr(iris_obj, field_name, None)
            python_val = runtime.extract_python_value(raw_val)
            d[field_name] = coerce_value_for_load(declared_type, python_val)

    # Complex fields: percent_list, collections, related models — full runtime path
    if model_cls._read_complex_fields:
        runtime = get_runtime()
        for field_name, model_field in model_cls._read_complex_fields:
            raw_val = runtime.get_property(iris_obj, field_name)
            if model_field._is_percent_list:
                d[field_name] = runtime.decode_percent_list(raw_val)
            else:
                python_val = runtime.extract_python_value(raw_val)
                if python_val in (None, 0) and (
                    model_field._is_scalar_string or model_field.declared_type is str
                ):
                    python_val = ""
                elif python_val == chr(0) and (
                    model_field._is_scalar_string or model_field.declared_type is str
                ):
                    python_val = None
                if model_field._collection_kind is not None:
                    d[field_name] = _coerce_collection_for_load(
                        model_field._collection_kind, model_field._element_type, python_val
                    )
                else:
                    d[field_name] = _build_model_from_iris_obj(
                        model_field.declared_type,
                        python_val,
                    )

    # Build instance directly — bypass _from_loaded_values + per-field setattr loop
    instance = model_cls.__new__(model_cls)
    instance_dict = instance.__dict__
    instance_dict.update(d)
    instance_dict["_iris_obj"] = iris_obj
    if not model_cls._is_serial_class:
        if known_pk is not None:
            instance_dict["_pk"] = known_pk
        else:
            runtime = get_runtime()
            obj_id = runtime.get_object_id(iris_obj)
            instance_dict["_pk"] = str(obj_id) if obj_id else None
    else:
        instance_dict["_pk"] = None
    return instance


def _new_iris_object(runtime: Any, classname: str) -> Any:
    cls_factory = getattr(runtime, "_cls", None)
    return (
        cls_factory(classname)._New()
        if cls_factory is not None
        else runtime.create_object(classname)
    )


def _materialize_related_value(
    runtime: Any,
    declared_type: Any,
    value: Any,
    *,
    persist_related: bool,
    auto_sync: bool,
    validate: bool,
) -> Any:
    if value is None:
        return None
    collection_kind, element_type = _collection_value_type(declared_type)
    if collection_kind == "list" and isinstance(value, list):
        if _is_model_type(element_type):
            return [
                _materialize_related_value(
                    runtime,
                    element_type,
                    item,
                    persist_related=persist_related,
                    auto_sync=auto_sync,
                    validate=validate,
                )
                for item in value
            ]
        return [coerce_value_for_save(element_type, item) for item in value]
    if collection_kind == "array" and isinstance(value, dict):
        if _is_model_type(element_type):
            return {
                str(key): _materialize_related_value(
                    runtime,
                    element_type,
                    item,
                    persist_related=persist_related,
                    auto_sync=auto_sync,
                    validate=validate,
                )
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
                    _materialize_related_value(
                        runtime,
                        nested_type,
                        nested_value,
                        persist_related=persist_related,
                        auto_sync=auto_sync,
                        validate=validate,
                    ),
                )
        value._iris_obj = iris_obj
        return iris_obj

    if not persist_related:
        return _materialize_model(
            value,
            auto_sync=auto_sync,
            validate=validate,
            persist_related=False,
        )

    save_model(value)
    if value._iris_obj is not None:
        return value._iris_obj
    if value.pk is not None:
        return runtime.get_object(declared_type._classname, value.pk)
    return value


def _resolve_sql_field_name(model_cls: Type[TModel], field_name: str) -> str:
    field_meta = model_cls._fields.get(field_name)
    if field_meta is None:
        valid_fields = ", ".join(sorted(model_cls._fields))
        raise ValueError(
            f"Unknown field {field_name!r} for {model_cls.__name__}. "
            f"Expected one of: {valid_fields}"
        )
    return str(getattr(field_meta, "sql_field_name", None) or field_name)


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
    except Exception as exc:
        warnings.warn(
            f"Could not resolve SQL table name for {model_cls._classname!r} "
            f"from IRIS metadata: {exc}. Falling back to model metadata.",
            RuntimeWarning,
            stacklevel=2,
        )
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
            f"{model_cls.__name__} enables `Meta.auto_sync`, but mode='observe' "
            "never writes schema. "
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
        try:
            cursor.execute(sql, params)

            results = []
            for row in cursor:
                row_id = row[0]
                obj = self.model_cls.get(str(row_id))
                if obj is not None:
                    results.append(obj)
        finally:
            close = getattr(cursor, "close", None)
            if callable(close):
                close()
            close = getattr(conn, "close", None)
            if callable(close):
                close()

        return results


def _populate_iris_object(
    instance: TModel,
    iris_obj: Any,
    runtime: Any,
    *,
    is_update: bool,
    persist_related: bool,
    auto_sync: bool,
    validate: bool,
) -> None:
    cls = instance.__class__
    inst_dict = instance.__dict__

    # Hot path: code-gen field setter avoids set_property() overhead + isinstance checks.
    # Only present for models where all fields are primitive scalars (no coerce/complex).
    if cls._fast_save:
        cls._fast_save(iris_obj, inst_dict)
    else:
        # Fast path: primitive scalar fields (str/int/float/bool) — no coercion needed,
        # bypass inject_iris_value dispatch and call set_property directly.
        for field_name in cls._scalar_fast_fields:
            if field_name not in inst_dict:
                continue
            val = inst_dict.get(field_name)
            if val is None and cls.__model_fields__[field_name].declared_type is str:
                runtime.set_property(iris_obj, field_name, chr(0))
            elif val is not None:
                runtime.set_property(iris_obj, field_name, val)

        # Scalar fields that require coercion (e.g. datetime types).
        if cls._scalar_coerce_fields:
            for field_name, declared_type in cls._scalar_coerce_fields:
                val = inst_dict.get(field_name)
                if val is not None:
                    runtime.inject_iris_value(
                        iris_obj,
                        field_name,
                        coerce_value_for_save(declared_type, val),
                    )

        # Complex fields: collections, related models, readonly.
        if cls._complex_save_fields:
            for field_name, model_field in cls._complex_save_fields:
                if getattr(model_field.field_info, "readonly", False) and is_update:
                    continue
                val = inst_dict.get(field_name)
                if val is None:
                    continue
                materialized = _materialize_related_value(
                    runtime,
                    model_field.declared_type,
                    val,
                    persist_related=persist_related,
                    auto_sync=auto_sync,
                    validate=validate,
                )
                runtime.inject_iris_value(
                    iris_obj,
                    field_name,
                    materialized,
                    field_meta=model_field.field_info,
                )


def _materialize_model(
    instance: TModel,
    *,
    auto_sync: bool,
    validate: bool,
    persist_related: bool,
) -> Any:
    runtime = get_runtime()
    cls = instance.__class__
    classname = instance._classname

    if auto_sync and cls._auto_sync:
        _maybe_auto_sync_schema(cls)
    if validate and cls._validate_on_init:
        instance._validate_for_save()

    pk = instance._pk
    is_update = bool(pk)
    iris_obj = instance._iris_obj
    if iris_obj is None:
        if is_update:
            assert pk is not None
            iris_obj = runtime.get_object(classname, pk)
        else:
            iris_obj = _new_iris_object(runtime, classname)

    instance._iris_obj = iris_obj
    _populate_iris_object(
        instance,
        iris_obj,
        runtime,
        is_update=is_update,
        persist_related=persist_related,
        auto_sync=auto_sync,
        validate=validate,
    )
    return iris_obj


def materialize(
    instance: TModel,
    *,
    auto_sync: bool = True,
    validate: bool = True,
) -> Any:
    """Populate and return an IRIS object for a model without saving it."""

    return _materialize_model(
        instance,
        auto_sync=auto_sync,
        validate=validate,
        persist_related=False,
    )


def from_iris(
    model_cls: Type[TModel],
    iris_obj: Any,
    known_pk: Optional[str] = None,
) -> Optional[TModel]:
    """Build a model instance around an existing IRIS object handle."""

    return _build_model_from_iris_obj(model_cls, iris_obj, known_pk=known_pk)


def save_model(instance: TModel) -> None:
    runtime = get_runtime()
    classname = instance._classname

    iris_obj = _materialize_model(
        instance,
        auto_sync=True,
        validate=True,
        persist_related=True,
    )

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

    return from_iris(cls, iris_obj, known_pk=pk)


def delete_model(instance: TModel) -> bool:
    if not instance._pk:
        return False
    runtime = get_runtime()
    return runtime.delete_object(instance._classname, instance._pk)
