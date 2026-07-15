from __future__ import annotations

import keyword
from dataclasses import dataclass
from inspect import Parameter, Signature
from typing import Any, Dict

from iris_persistence.codecs import NULL_STRING, SCALAR_CODECS
from iris_persistence.types import UNSET, ModelField


@dataclass(frozen=True)
class FieldPlan:
    name: str
    model_field: ModelField
    read_kind: str
    save_kind: str


@dataclass(frozen=True)
class _InitFieldCode:
    parameter: str
    statement: str
    namespace_entry: tuple[str, Any] | None = None


class _FactoryDefault:
    def __repr__(self) -> str:
        return "<factory>"


FACTORY_DEFAULT = _FactoryDefault()


def _safe_names(names: Any) -> bool:
    return all(name.isidentifier() and not keyword.iskeyword(name) for name in names)


def _compile_init(params: list[str], body: list[str], namespace: dict[str, Any]) -> Any:
    exec("def __init__(" + ", ".join(params) + "):\n" + "\n".join(body), namespace)
    return namespace["__init__"]


def build_signature(model_fields: Dict[str, ModelField]) -> Signature:
    parameters = []
    for field in model_fields.values():
        default: Any = Parameter.empty
        if field.default_factory is not UNSET:
            default = FACTORY_DEFAULT
        elif field.default is not UNSET:
            default = field.default
        elif not field.required:
            default = None
        parameters.append(
            Parameter(
                field.name,
                kind=Parameter.KEYWORD_ONLY,
                default=default,
                annotation=field.declared_type,
            )
        )
    return Signature(parameters=parameters)


def build_generated_init(model_fields: Dict[str, ModelField]) -> Any | None:
    if not _safe_names(model_fields):
        return None
    params = ["self", *(["*"] if model_fields else [])]
    body = ["    provided_values = {}"]
    for field in model_fields.values():
        params.append(field.name if field.required else f"{field.name}=UNSET")
        body.append(f"    provided_values[{field.name!r}] = {field.name}")
    body.append("    self._initialize_model_state(provided_values)")
    return _compile_init(params, body, {"UNSET": UNSET})


def build_fast_init(model_fields: Dict[str, ModelField]) -> Any | None:
    if not _safe_names(model_fields):
        return None
    params = ["self", *(["*"] if model_fields else [])]
    body = ["    self._pk = None", "    self._iris_obj = None"]
    if model_fields:
        body.append("    d = self.__dict__")
    namespace: dict[str, Any] = {"UNSET": UNSET}
    for index, (name, field) in enumerate(model_fields.items()):
        field_code = _fast_init_field_code(index, name, field)
        params.append(field_code.parameter)
        body.append(field_code.statement)
        if field_code.namespace_entry is not None:
            namespace.update((field_code.namespace_entry,))
    return _compile_init(params, body, namespace)


def _fast_init_field_code(index: int, name: str, field: ModelField) -> _InitFieldCode:
    if field.required:
        return _InitFieldCode(name, f"    d[{name!r}] = {name}")
    parameter = f"{name}=UNSET"
    if field.field_info.default_factory is not UNSET:
        factory = f"_dfact_{index}"
        statement = f"    d[{name!r}] = {name} if {name} is not UNSET else {factory}()"
        return _InitFieldCode(
            parameter,
            statement,
            (factory, field.field_info.default_factory),
        )
    if field.field_info.default is not UNSET:
        default = f"_dval_{index}"
        statement = f"    d[{name!r}] = {name} if {name} is not UNSET else {default}"
        return _InitFieldCode(parameter, statement, (default, field.field_info.default))
    return _InitFieldCode(parameter, f"    if {name} is not UNSET: d[{name!r}] = {name}")


def build_fast_load(model_cls: Any, plans: tuple[FieldPlan, ...], is_serial: bool) -> Any:
    if not _safe_names(plan.name for plan in plans):
        return None
    lines = [
        "def _fast_load(iris_obj, known_pk=None):",
        "    if iris_obj is None: return None",
        "    instance = _model_cls.__new__(_model_cls)",
        "    d = instance.__dict__",
        "    d['_iris_obj'] = iris_obj",
    ]
    if is_serial:
        lines.append("    d['_pk'] = None")
    else:
        lines.extend(
            (
                "    if known_pk is not None:",
                "        d['_pk'] = known_pk",
                "    else:",
                "        _oid = _get_runtime().get_object_id(iris_obj)",
                "        d['_pk'] = str(_oid) if _oid else None",
            )
        )
    for plan in plans:
        field = plan.model_field
        codec = SCALAR_CODECS.get(field.declared_type)
        if codec is None or codec.read_kind != plan.read_kind:
            return None
        lines.extend(
            (
                f"    _v = iris_obj.{plan.name}",
                f"    d[{plan.name!r}] = {codec.load_expression('_v', nullable=field.nullable)}",
            )
        )
    lines.append("    return instance")
    from iris_persistence.runtime import get_runtime

    namespace = {
        "_model_cls": model_cls,
        "_get_runtime": get_runtime,
        "_NULL_STRING": NULL_STRING,
    }
    exec("\n".join(lines), namespace)
    function = namespace["_fast_load"]
    function.__qualname__ = f"{model_cls.__qualname__}._fast_load"
    return function


def build_fast_save(model_cls: Any, plans: tuple[FieldPlan, ...]) -> Any:
    scalar_plans = [plan for plan in plans if plan.save_kind == "scalar_fast"]
    if not scalar_plans or len(scalar_plans) != len(plans):
        return None
    if not _safe_names(plan.name for plan in scalar_plans):
        return None
    lines = ["def _fast_save(iris_obj, inst_dict):"]
    for plan in scalar_plans:
        field = plan.model_field
        codec = SCALAR_CODECS[field.declared_type]
        lines.extend(
            (f"    if {plan.name!r} in inst_dict:", f"        _v = inst_dict.get({plan.name!r})")
        )
        assignment = (
            f"iris_obj.{plan.name} = {codec.save_expression('_v', nullable=field.nullable)}"
        )
        prefix = "if _v is not None: " if codec.skips_none_on_save(nullable=field.nullable) else ""
        lines.append(f"        {prefix}{assignment}")
    namespace: dict[str, Any] = {"_NULL_STRING": NULL_STRING}
    exec("\n".join(lines), namespace)
    function = namespace["_fast_save"]
    function.__qualname__ = f"{model_cls.__qualname__}._fast_save"
    return function
