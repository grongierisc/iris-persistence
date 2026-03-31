"""
Declaration and binding registry for IRIS model classes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .metaclass import IRISModel, IRISSerial
from .schema import SchemaCatalog, SchemaCompiler


@dataclass(frozen=True)
class ExistingBinding:
    classname: str
    model_class: type


class Registry:
    """Collect declared models and explicit existing-class bindings."""

    def __init__(self) -> None:
        self._declared: dict[str, type] = {}
        self._existing: dict[str, ExistingBinding] = {}

    def register(self, model_class: type) -> type:
        classname = str(getattr(model_class, "_iris_classname", "") or "")
        if not classname:
            raise ValueError(f"{model_class.__name__} does not declare _iris_classname")
        self._declared[classname] = model_class
        return model_class

    def bind_existing(
        self,
        classname: str,
        *,
        model_name: str | None = None,
        serial: bool = False,
    ) -> type:
        base = IRISSerial if serial else IRISModel
        python_name = model_name or classname.split(".")[-1]
        model_class = type(
            python_name,
            (base,),
            {
                "_iris_classname": classname,
                "__module__": "iris_orm.registry",
            },
        )
        self._existing[classname] = ExistingBinding(classname=classname, model_class=model_class)
        return model_class

    def declared_models(self) -> list[type]:
        return [self._declared[key] for key in sorted(self._declared)]

    def existing_models(self) -> list[type]:
        return [self._existing[key].model_class for key in sorted(self._existing)]

    def all_models(self) -> list[type]:
        return self.declared_models() + self.existing_models()

    def classnames(self) -> list[str]:
        return sorted(set(self._declared) | set(self._existing))

    def export_schema(self) -> SchemaCatalog:
        compiler = SchemaCompiler()
        return compiler.catalog_from_registry(self)

    def get(self, classname: str) -> type | None:
        if classname in self._declared:
            return self._declared[classname]
        binding = self._existing.get(classname)
        return None if binding is None else binding.model_class

    def items(self) -> list[tuple[str, type]]:
        return [(classname, self.get(classname)) for classname in self.classnames() if self.get(classname) is not None]
