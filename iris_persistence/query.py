from __future__ import annotations

import datetime
import warnings
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

import iris_persistence.models
from iris_persistence.catalog import dbapi_cursor
from iris_persistence.codecs import (
    NULL_STRING,
    coerce_value_for_load,
    coerce_value_for_save,
    load_scalar_bool,
    load_scalar_number,
    load_scalar_str,
    save_scalar_null,
)
from iris_persistence.field_utils import (
    collection_value_type,
    is_model_type,
    is_serial_model_type,
    walk_declared_value,
)
from iris_persistence.runtime import get_runtime
from iris_persistence.types import UNSET

TModel = TypeVar("TModel", bound="iris_persistence.models.Model")

_AUTO_SYNCED: set[type[iris_persistence.models.Model]] = set()


def _is_null_object_reference(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value == 0
    return False


def _build_model_from_iris_obj(
    model_cls: Type[TModel],
    iris_obj: Any,
    known_pk: Optional[str] = None,
) -> Optional[TModel]:
    if _is_null_object_reference(iris_obj):
        return None

    # Use the per-class code-gen loader when available (direct LOAD_ATTR, 2-3× faster
    # than getattr() for IRIS C-extension objects).
    fast_load = model_cls._fast_load
    if fast_load is not None:
        return fast_load(iris_obj, known_pk)

    d: dict = {}

    # str fields: direct getattr, normalise None/0 → "" (IRIS can return 0 for empty string props)
    for plan in model_cls._read_fields["str"]:
        field_name = plan.name
        d[field_name] = load_scalar_str(getattr(iris_obj, field_name, None))

    # int/float fields: direct getattr, IRIS already returns correct Python type
    for plan in model_cls._read_fields["primitive"]:
        field_name = plan.name
        d[field_name] = load_scalar_number(
            getattr(iris_obj, field_name, None),
            model_cls.__model_fields__[field_name].nullable,
        )

    # bool fields: IRIS stores as int 0/1, convert without calling coerce_value_for_load
    for plan in model_cls._read_fields["bool"]:
        field_name = plan.name
        d[field_name] = load_scalar_bool(
            getattr(iris_obj, field_name, None),
            model_cls.__model_fields__[field_name].nullable,
        )

    # Scalar fields needing full coercion (e.g. datetime): still skip get_property dispatch
    if model_cls._read_fields["coerce"]:
        runtime = get_runtime()
        for plan in model_cls._read_fields["coerce"]:
            field_name, declared_type = plan.name, plan.model_field.declared_type
            raw_val = getattr(iris_obj, field_name, None)
            python_val = runtime.extract_python_value(raw_val)
            d[field_name] = coerce_value_for_load(declared_type, python_val)

    # Complex fields: percent_list, collections, related models — full runtime path
    if model_cls._read_fields["complex"]:
        runtime = get_runtime()
        for plan in model_cls._read_fields["complex"]:
            field_name, model_field = plan.name, plan.model_field
            raw_val = runtime.get_property(iris_obj, field_name)
            if model_field._is_percent_list:
                d[field_name] = runtime.decode_percent_list(raw_val)
            else:
                python_val = runtime.extract_typed_python_value(
                    raw_val,
                    model_field._collection_kind,
                )
                if python_val in (None, 0) and (
                    model_field._is_scalar_string or model_field.declared_type is str
                ):
                    python_val = ""
                elif python_val == NULL_STRING and (
                    model_field._is_scalar_string or model_field.declared_type is str
                ):
                    python_val = None
                if model_field._collection_kind is not None:
                    d[field_name] = walk_declared_value(
                        python_val,
                        model_field.declared_type,
                        lambda item, item_type: (
                            _build_model_from_iris_obj(item_type, item)
                            if is_model_type(item_type)
                            else coerce_value_for_load(item_type, item)
                        ),
                        stringify_keys=True,
                    )
                else:
                    d[field_name] = _build_model_from_iris_obj(
                        model_field.declared_type,
                        python_val,
                    )

        # Build the instance directly, bypassing the per-field setattr loop.
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
    collection_kind, _element_type = collection_value_type(declared_type)
    if (collection_kind == "list" and isinstance(value, list)) or (
        collection_kind == "array" and isinstance(value, dict)
    ):
        return walk_declared_value(
            value,
            declared_type,
            lambda item, item_type: _materialize_related_value(
                runtime,
                item_type,
                item,
                persist_related=persist_related,
                auto_sync=auto_sync,
                validate=validate,
            ),
            stringify_keys=True,
        )
    if not is_model_type(declared_type):
        return coerce_value_for_save(declared_type, value)

    if not isinstance(value, declared_type):
        raise TypeError(
            f"Expected {declared_type.__name__} for related object, got {type(value).__name__}"
        )

    if is_serial_model_type(declared_type):
        return _materialize_model(
            value,
            auto_sync=auto_sync,
            validate=validate,
            persist_related=persist_related,
        )

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


def _nullable_reference_has_no_initial_value(model_field: Any) -> bool:
    field_meta = model_field.field_info
    default = getattr(field_meta, "default", UNSET)
    return getattr(field_meta, "initial_expression", None) is None and (
        default is UNSET or default is None
    )


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
        with dbapi_cursor(runtime) as cursor:
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
                f"{sql_schema_name}.{sql_table_name}" if sql_schema_name else str(sql_table_name)
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

    mode = getattr(model_cls, "_sync_mode", iris_persistence.models.DEFAULT_SYNC_MODE)
    policy = iris_persistence.models.SYNC_POLICIES[mode]
    if not policy.auto_sync:
        reason = "never writes schema" if mode == "observe" else "is destructive"
        raise RuntimeError(
            f"{model_cls.__name__} enables `Meta.auto_sync`, but mode={mode!r} {reason}. "
            "Call `Model.sync_schema()` explicitly instead of auto-syncing on save."
        )

    if policy.cache_auto_sync and model_cls in _AUTO_SYNCED:
        return

    model_cls.sync_schema()
    if policy.cache_auto_sync:
        _AUTO_SYNCED.add(model_cls)


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

        results = []
        with dbapi_cursor(runtime) as cursor:
            cursor.execute(sql, params)
            for row in cursor:
                row_id = row[0]
                obj = self.model_cls.get(str(row_id))
                if obj is not None:
                    results.append(obj)

        return results


def _populate_iris_object(
    instance: TModel,
    iris_obj: Any,
    runtime: Any,
    *,
    is_update: bool,
    had_existing_iris_obj: bool,
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
        for plan in cls._save_fields["scalar_fast"]:
            field_name = plan.name
            if field_name not in inst_dict:
                continue
            val = inst_dict.get(field_name)
            model_field = cls.__model_fields__[field_name]
            if val is None and model_field.declared_type is str:
                runtime.set_property(iris_obj, field_name, NULL_STRING)
            elif val is None and model_field.nullable:
                runtime.set_property(
                    iris_obj,
                    field_name,
                    save_scalar_null(model_field.declared_type),
                )
            elif val is not None:
                runtime.set_property(iris_obj, field_name, val)

        # Scalar fields that require coercion (e.g. datetime types).
        if cls._save_fields["scalar_coerce"]:
            for plan in cls._save_fields["scalar_coerce"]:
                field_name, declared_type = plan.name, plan.model_field.declared_type
                if field_name not in inst_dict:
                    continue
                val = inst_dict.get(field_name)
                if val is None:
                    model_field = cls.__model_fields__[field_name]
                    if model_field.nullable:
                        if declared_type in (
                            datetime.date,
                            datetime.datetime,
                            datetime.time,
                        ):
                            runtime.set_property(iris_obj, field_name, "")
                        else:
                            runtime.inject_iris_value(
                                iris_obj,
                                field_name,
                                None,
                                field_meta=model_field.field_info,
                            )
                else:
                    runtime.inject_iris_value(
                        iris_obj,
                        field_name,
                        coerce_value_for_save(declared_type, val),
                        field_meta=cls.__model_fields__[field_name].field_info,
                    )

        # Complex fields: collections, related models, readonly.
        if cls._save_fields["complex"]:
            for plan in cls._save_fields["complex"]:
                field_name, model_field = plan.name, plan.model_field
                if getattr(model_field.field_info, "readonly", False) and is_update:
                    continue
                if field_name not in inst_dict:
                    continue
                val = inst_dict.get(field_name)
                if (
                    iris_persistence.models._is_object_reference_field(model_field)
                    and model_field.nullable
                    and (val is None or (isinstance(val, str) and val == ""))
                ):
                    if (
                        not is_update
                        and not had_existing_iris_obj
                        and _nullable_reference_has_no_initial_value(model_field)
                    ):
                        continue
                    if runtime.clear_reference(
                        iris_obj,
                        field_name,
                        serial=is_serial_model_type(model_field.declared_type),
                    ):
                        continue
                    raise RuntimeError(
                        f"Could not clear nullable object reference {field_name!r} "
                        f"on {cls.__name__}"
                    )
                if val is None:
                    if model_field.nullable:
                        runtime.inject_iris_value(
                            iris_obj,
                            field_name,
                            None,
                            field_meta=model_field.field_info,
                        )
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
    had_existing_iris_obj = iris_obj is not None
    if iris_obj is None:
        if is_update:
            assert pk is not None
            iris_obj = runtime.get_object(classname, pk)
        else:
            iris_obj = runtime.new_object(classname)

    instance._iris_obj = iris_obj
    _populate_iris_object(
        instance,
        iris_obj,
        runtime,
        is_update=is_update,
        had_existing_iris_obj=had_existing_iris_obj,
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
    """Populate and return an IRIS object for a model without calling %Save()."""

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
