from __future__ import annotations

from dataclasses import dataclass
from inspect import Parameter, Signature
from typing import Any, Dict

from iris_persistence.types import UNSET, ModelField


@dataclass(frozen=True)
class FieldPlan:
    name: str
    model_field: ModelField
    read_kind: str
    save_kind: str


class _FactoryDefault:
    def __repr__(self) -> str:
        return "<factory>"


FACTORY_DEFAULT = _FactoryDefault()


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
