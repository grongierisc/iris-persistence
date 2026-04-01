"""
Explicit runtime binder for declared and existing IRIS models.
"""
from __future__ import annotations

from typing import Any

from .adapter import IRISAdapter
from .descriptors import (
    IRISDescriptor,
    IRISRelationshipDescriptor,
    IRISSerialDescriptor,
    register_bound_model,
)
from .schema import SchemaClass, SchemaCompiler
from .types import iris_type_to_python


class Binder:
    """Resolve registry entries into runtime-bound model classes."""

    def __init__(self, registry: Any, adapter: IRISAdapter | None = None) -> None:
        self.registry = registry
        self.adapter = adapter or IRISAdapter()
        self.compiler = SchemaCompiler(self.adapter)
        self._bound: dict[str, type] = {}

    def bind_all(self) -> dict[str, type]:
        for model_class in self.registry.declared_models():
            self.bind_model(model_class)
        for model_class in self.registry.existing_models():
            self.bind_model(model_class)
        return dict(self._bound)

    def bind_model(self, model_class: type) -> type:
        classname = model_class._iris_classname  # type: ignore[attr-defined]
        if classname in self._bound:
            return self._bound[classname]

        mode = str(getattr(model_class, "_iris_mode", "python") or "python").strip().lower()
        if mode == "proxy":
            schema_class = self.compiler.class_from_iris(classname)
            self._populate_declared_metadata(model_class, schema_class)
        elif getattr(model_class, "_iris_declared_fields", None) or getattr(model_class, "_iris_declared_relationships", None):
            schema_class = self.compiler.compile_model(model_class)
        else:
            schema_class = self.compiler.class_from_iris(classname)
            self._populate_declared_metadata(model_class, schema_class)

        self._install_runtime_descriptors(model_class, schema_class)
        model_class._iris_bound_schema = schema_class  # type: ignore[attr-defined]
        model_class._iris_bound = True  # type: ignore[attr-defined]
        register_bound_model(model_class)
        self._bound[classname] = model_class
        return model_class

    def schema_for(self, model_class: type) -> SchemaClass:
        self.bind_model(model_class)
        return model_class._iris_bound_schema  # type: ignore[attr-defined]

    def _install_runtime_descriptors(self, model_class: type, schema_class: SchemaClass) -> None:
        annotations = getattr(model_class, "__annotations__", {})
        for prop in schema_class.properties:
            python_type = iris_type_to_python(prop.iris_type)
            if self.registry.get(prop.iris_type) is not None:
                related_model = self.registry.get(prop.iris_type)
                if related_model is not None and getattr(related_model, "_iris_serial", False):
                    descriptor = IRISSerialDescriptor(prop.name, prop.iris_type)
                    annotations[prop.name] = related_model
                else:
                    descriptor = IRISDescriptor(prop.name, python_type, prop.required)
                    annotations[prop.name] = python_type
            else:
                descriptor = IRISDescriptor(prop.name, python_type, prop.required)
                annotations[prop.name] = python_type
            setattr(model_class, prop.name, descriptor)

        for rel in schema_class.relationships:
            annotations[rel.name] = Any
            setattr(
                model_class,
                rel.name,
                IRISRelationshipDescriptor(
                    prop_name=rel.name,
                    related_classname=rel.related_classname,
                    cardinality=rel.cardinality,
                    inverse=rel.inverse,
                ),
            )
        model_class.__annotations__ = annotations

    def _populate_declared_metadata(self, model_class: type, schema_class: SchemaClass) -> None:
        from .fields import FieldDefinition, RelationshipDefinition

        model_class._iris_declared_fields = {  # type: ignore[attr-defined]
            prop.name: FieldDefinition(
                required=prop.required,
                default=prop.default,
                maxlen=prop.maxlen,
                collection=prop.collection,
                iris_type=prop.iris_type,
                description=prop.description,
                prop_name=prop.name,
                python_type=iris_type_to_python(prop.iris_type),
            )
            for prop in schema_class.properties
        }
        model_class._iris_declared_relationships = {  # type: ignore[attr-defined]
            rel.name: RelationshipDefinition(
                related_classname=rel.related_classname,
                inverse=rel.inverse,
                cardinality=rel.cardinality,
                description=rel.description,
            )
            for rel in schema_class.relationships
        }
