from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Optional, Type, TypeVar

import iris_persistence.models
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
from iris_persistence.persistence.queryset import (
    QuerySet as QuerySet,
)
from iris_persistence.persistence.queryset import (
    _resolve_sql_field_name as _resolve_sql_field_name,
)
from iris_persistence.persistence.queryset import (
    _resolve_sql_table_name as _resolve_sql_table_name,
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

    values: dict[str, Any] = {}
    _load_direct_fields(model_cls, iris_obj, values)
    _load_coerced_fields(model_cls, iris_obj, values)
    _load_complex_fields(model_cls, iris_obj, values)
    return _new_loaded_instance(model_cls, iris_obj, values, known_pk)


def _load_direct_fields(model_cls: Type[TModel], iris_obj: Any, values: dict[str, Any]) -> None:
    for plan in model_cls._read_fields["str"]:
        values[plan.name] = load_scalar_str(getattr(iris_obj, plan.name, None))
    for plan in model_cls._read_fields["primitive"]:
        values[plan.name] = load_scalar_number(
            getattr(iris_obj, plan.name, None), plan.model_field.nullable
        )
    for plan in model_cls._read_fields["bool"]:
        values[plan.name] = load_scalar_bool(
            getattr(iris_obj, plan.name, None), plan.model_field.nullable
        )


def _load_coerced_fields(model_cls: Type[TModel], iris_obj: Any, values: dict[str, Any]) -> None:
    plans = model_cls._read_fields["coerce"]
    if not plans:
        return
    runtime = get_runtime()
    for plan in plans:
        raw_value = getattr(iris_obj, plan.name, None)
        python_value = runtime.extract_python_value(raw_value)
        values[plan.name] = coerce_value_for_load(plan.model_field.declared_type, python_value)


def _load_complex_value(model_field: Any, raw_value: Any, runtime: Any) -> Any:
    if model_field._is_percent_list:
        return runtime.decode_percent_list(raw_value)
    python_value = runtime.extract_typed_python_value(raw_value, model_field._collection_kind)
    if python_value in (None, 0) and (
        model_field._is_scalar_string or model_field.declared_type is str
    ):
        python_value = ""
    elif python_value == NULL_STRING and (
        model_field._is_scalar_string or model_field.declared_type is str
    ):
        python_value = None
    if model_field._collection_kind is None:
        return _build_model_from_iris_obj(model_field.declared_type, python_value)
    return walk_declared_value(
        python_value,
        model_field.declared_type,
        lambda item, item_type: (
            _build_model_from_iris_obj(item_type, item)
            if is_model_type(item_type)
            else coerce_value_for_load(item_type, item)
        ),
        stringify_keys=True,
    )


def _load_complex_fields(model_cls: Type[TModel], iris_obj: Any, values: dict[str, Any]) -> None:
    plans = model_cls._read_fields["complex"]
    if not plans:
        return
    runtime = get_runtime()
    for plan in plans:
        raw_value = runtime.get_property(iris_obj, plan.name)
        values[plan.name] = _load_complex_value(plan.model_field, raw_value, runtime)


def _new_loaded_instance(
    model_cls: Type[TModel],
    iris_obj: Any,
    values: dict[str, Any],
    known_pk: Optional[str],
) -> TModel:
    instance = model_cls.__new__(model_cls)
    instance.__dict__.update(values)
    instance.__dict__["_iris_obj"] = iris_obj
    if model_cls._is_serial_class:
        instance.__dict__["_pk"] = None
        return instance
    object_id = known_pk if known_pk is not None else get_runtime().get_object_id(iris_obj)
    instance.__dict__["_pk"] = str(object_id) if object_id else None
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


@dataclass(frozen=True)
class _SaveContext:
    instance: Any
    iris_obj: Any
    runtime: Any
    is_update: bool
    had_existing_iris_obj: bool
    persist_related: bool
    auto_sync: bool
    validate: bool


_SKIP_SCALAR_WRITE = object()


def _resolve_scalar_write(model_field: Any, value: Any) -> Any:
    if value is not None:
        return value
    if model_field.declared_type is str:
        return NULL_STRING
    if model_field.nullable:
        return save_scalar_null(model_field.declared_type)
    return _SKIP_SCALAR_WRITE


def _save_fast_scalar_fields(context: _SaveContext) -> None:
    cls = context.instance.__class__
    values = context.instance.__dict__
    for plan in cls._save_fields["scalar_fast"]:
        if plan.name not in values:
            continue
        value = _resolve_scalar_write(plan.model_field, values.get(plan.name))
        if value is _SKIP_SCALAR_WRITE:
            continue
        context.runtime.set_property(context.iris_obj, plan.name, value)


def _save_coerced_scalar_fields(context: _SaveContext) -> None:
    cls = context.instance.__class__
    values = context.instance.__dict__
    for plan in cls._save_fields["scalar_coerce"]:
        if plan.name not in values:
            continue
        value = values.get(plan.name)
        model_field = plan.model_field
        if value is None and not model_field.nullable:
            continue
        if value is None and model_field.declared_type in (
            datetime.date,
            datetime.datetime,
            datetime.time,
        ):
            context.runtime.set_property(context.iris_obj, plan.name, "")
            continue
        coerced = None if value is None else coerce_value_for_save(model_field.declared_type, value)
        context.runtime.inject_iris_value(
            context.iris_obj, plan.name, coerced, field_meta=model_field.field_info
        )


def _clear_nullable_reference(context: _SaveContext, plan: Any, value: Any) -> bool:
    model_field = plan.model_field
    if not iris_persistence.models._is_object_reference_field(model_field):
        return False
    if not model_field.nullable or value not in (None, ""):
        return False
    if (
        not context.is_update
        and not context.had_existing_iris_obj
        and _nullable_reference_has_no_initial_value(model_field)
    ):
        return True
    context.runtime.clear_reference(
        context.iris_obj,
        plan.name,
        serial=is_serial_model_type(model_field.declared_type),
    )
    return True


def _save_complex_field(context: _SaveContext, plan: Any) -> None:
    values = context.instance.__dict__
    model_field = plan.model_field
    if getattr(model_field.field_info, "readonly", False) and context.is_update:
        return
    if plan.name not in values:
        return
    value = values.get(plan.name)
    if _clear_nullable_reference(context, plan, value):
        return
    if value is None:
        if model_field.nullable:
            context.runtime.inject_iris_value(
                context.iris_obj, plan.name, None, field_meta=model_field.field_info
            )
        return
    materialized = _materialize_related_value(
        context.runtime,
        model_field.declared_type,
        value,
        persist_related=context.persist_related,
        auto_sync=context.auto_sync,
        validate=context.validate,
    )
    context.runtime.inject_iris_value(
        context.iris_obj, plan.name, materialized, field_meta=model_field.field_info
    )


def _save_complex_fields(context: _SaveContext) -> None:
    for plan in context.instance.__class__._save_fields["complex"]:
        _save_complex_field(context, plan)


def _populate_iris_object(context: _SaveContext) -> None:
    _save_fast_scalar_fields(context)
    _save_coerced_scalar_fields(context)
    _save_complex_fields(context)


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
        _SaveContext(
            instance,
            iris_obj,
            runtime,
            is_update,
            had_existing_iris_obj,
            persist_related,
            auto_sync,
            validate,
        )
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

    status = runtime.save_object(iris_obj)
    runtime.check_status(status, f"save {classname}")

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
