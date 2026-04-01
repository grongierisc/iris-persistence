"""
Canonical schema AST plus compiler, planner, and live applier for IRIS.
"""
from __future__ import annotations

import inspect
import re
import datetime
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .adapter import IRISAdapter
from .fields import FieldDefinition, RelationshipDefinition
from .types import iris_type_to_python, python_type_to_iris, unwrap_optional

if TYPE_CHECKING:
    from .registry import Registry


@dataclass(frozen=True)
class SchemaProperty:
    name: str
    iris_type: str
    required: bool = False
    collection: str = ""
    default: str = ""
    maxlen: int | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "iris_type": self.iris_type,
            "required": self.required,
            "collection": self.collection,
            "default": self.default,
            "description": self.description,
        }
        if self.maxlen is not None:
            payload["maxlen"] = self.maxlen
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchemaProperty":
        return cls(
            name=str(payload["name"]),
            iris_type=str(payload.get("iris_type", "%String")),
            required=bool(payload.get("required", False)),
            collection=str(payload.get("collection", "")),
            default=str(payload.get("default", "")),
            maxlen=_as_int(payload.get("maxlen")),
            description=str(payload.get("description", "")),
        )


@dataclass(frozen=True)
class SchemaRelationship:
    name: str
    related_classname: str
    cardinality: str
    inverse: str
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "related_classname": self.related_classname,
            "cardinality": self.cardinality,
            "inverse": self.inverse,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchemaRelationship":
        return cls(
            name=str(payload["name"]),
            related_classname=str(payload.get("related_classname", "")),
            cardinality=str(payload.get("cardinality", "one")),
            inverse=str(payload.get("inverse", "")),
            description=str(payload.get("description", "")),
        )


@dataclass(frozen=True)
class SchemaIndex:
    name: str
    properties: str
    unique: bool = False
    primary_key: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "properties": self.properties,
            "unique": self.unique,
            "primary_key": self.primary_key,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchemaIndex":
        return cls(
            name=str(payload["name"]),
            properties=str(payload.get("properties", "")),
            unique=bool(payload.get("unique", False)),
            primary_key=bool(payload.get("primary_key", False)),
        )


@dataclass(frozen=True)
class SchemaTrigger:
    name: str
    event: str
    time: str
    code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "event": self.event,
            "time": self.time,
            "code": self.code,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchemaTrigger":
        return cls(
            name=str(payload["name"]),
            event=str(payload.get("event", "")).upper(),
            time=str(payload.get("time", "")).upper(),
            code=str(payload.get("code", "")),
        )


@dataclass(frozen=True)
class SchemaStorageValue:
    name: str
    value: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchemaStorageValue":
        return cls(name=str(payload.get("name", "")), value=str(payload.get("value", "")))


@dataclass(frozen=True)
class SchemaStorageData:
    name: str
    structure: str = ""
    subscript: str = ""
    values: tuple[SchemaStorageValue, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = {"name": self.name, "values": [item.to_dict() for item in self.values]}
        if self.structure:
            payload["structure"] = self.structure
        if self.subscript:
            payload["subscript"] = self.subscript
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchemaStorageData":
        return cls(
            name=str(payload.get("name", "")),
            structure=str(payload.get("structure", "")),
            subscript=str(payload.get("subscript", "")),
            values=tuple(
                SchemaStorageValue.from_dict(dict(item))
                for item in list(payload.get("values", []))
            ),
        )


@dataclass(frozen=True)
class SchemaStorage:
    name: str = "Default"
    storage_type: str = ""
    data_location: str = ""
    default_data: str = ""
    extent_location: str = ""
    id_location: str = ""
    index_location: str = ""
    stream_location: str = ""
    id_function: str = ""
    data: tuple[SchemaStorageData, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = {"name": self.name, "data": [item.to_dict() for item in self.data]}
        scalar_fields = {
            "type": self.storage_type,
            "data_location": self.data_location,
            "default_data": self.default_data,
            "extent_location": self.extent_location,
            "id_location": self.id_location,
            "index_location": self.index_location,
            "stream_location": self.stream_location,
            "id_function": self.id_function,
        }
        for key, value in scalar_fields.items():
            if value:
                payload[key] = value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchemaStorage":
        return cls(
            name=str(payload.get("name", "Default")),
            storage_type=str(payload.get("type", "")),
            data_location=str(payload.get("data_location", "")),
            default_data=str(payload.get("default_data", "")),
            extent_location=str(payload.get("extent_location", "")),
            id_location=str(payload.get("id_location", "")),
            index_location=str(payload.get("index_location", "")),
            stream_location=str(payload.get("stream_location", "")),
            id_function=str(payload.get("id_function", "")),
            data=tuple(
                SchemaStorageData.from_dict(dict(item))
                for item in list(payload.get("data", []))
            ),
        )


@dataclass(frozen=True)
class SchemaClass:
    name: str
    superclass: str
    kind: str
    properties: tuple[SchemaProperty, ...] = ()
    relationships: tuple[SchemaRelationship, ...] = ()
    indexes: tuple[SchemaIndex, ...] = ()
    triggers: tuple[SchemaTrigger, ...] = ()
    parameters: dict[str, str] = dataclass_field(default_factory=dict)
    storage: SchemaStorage | None = None
    source: dict[str, Any] = dataclass_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "superclass": self.superclass,
            "kind": self.kind,
            "properties": [item.to_dict() for item in sorted(self.properties, key=lambda item: item.name)],
            "relationships": [
                item.to_dict() for item in sorted(self.relationships, key=lambda item: item.name)
            ],
            "indexes": [item.to_dict() for item in sorted(self.indexes, key=lambda item: item.name)],
            "triggers": [item.to_dict() for item in sorted(self.triggers, key=lambda item: item.name)],
            "parameters": {key: self.parameters[key] for key in sorted(self.parameters)},
            "source": dict(sorted(self.source.items())),
        }
        if self.storage is not None:
            payload["storage"] = self.storage.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchemaClass":
        return cls(
            name=str(payload["name"]),
            superclass=str(payload.get("superclass", "%Persistent")),
            kind=str(payload.get("kind", "persistent")),
            properties=tuple(
                SchemaProperty.from_dict(dict(item))
                for item in list(payload.get("properties", []))
            ),
            relationships=tuple(
                SchemaRelationship.from_dict(dict(item))
                for item in list(payload.get("relationships", []))
            ),
            indexes=tuple(
                SchemaIndex.from_dict(dict(item))
                for item in list(payload.get("indexes", []))
            ),
            triggers=tuple(
                SchemaTrigger.from_dict(dict(item))
                for item in list(payload.get("triggers", []))
            ),
            parameters={
                str(key): str(value)
                for key, value in dict(payload.get("parameters", {})).items()
            },
            storage=(
                SchemaStorage.from_dict(dict(payload["storage"]))
                if payload.get("storage") is not None
                else None
            ),
            source={str(key): value for key, value in dict(payload.get("source", {})).items()},
        )

    @property
    def property_map(self) -> dict[str, SchemaProperty]:
        return {item.name: item for item in self.properties}

    @property
    def relationship_map(self) -> dict[str, SchemaRelationship]:
        return {item.name: item for item in self.relationships}

    @property
    def index_map(self) -> dict[str, SchemaIndex]:
        return {item.name: item for item in self.indexes}

    @property
    def trigger_map(self) -> dict[str, SchemaTrigger]:
        return {item.name: item for item in self.triggers}


@dataclass(frozen=True)
class SchemaCatalog:
    classes: tuple[SchemaClass, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "classes": [item.to_dict() for item in sorted(self.classes, key=lambda item: item.name)]
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchemaCatalog":
        return cls(
            classes=tuple(
                SchemaClass.from_dict(dict(item))
                for item in list(payload.get("classes", []))
            )
        )

    @property
    def class_map(self) -> dict[str, SchemaClass]:
        return {item.name: item for item in self.classes}

    def get_class(self, classname: str) -> SchemaClass | None:
        return self.class_map.get(classname)

    def select(self, classnames: list[str]) -> "SchemaCatalog":
        wanted = set(classnames)
        return SchemaCatalog(classes=tuple(item for item in self.classes if item.name in wanted))


@dataclass(frozen=True)
class SchemaOperation:
    kind: str
    classname: str
    payload: dict[str, Any] = dataclass_field(default_factory=dict)
    manual_only: bool = False


@dataclass(frozen=True)
class SchemaPlan:
    operations: tuple[SchemaOperation, ...] = ()

    @property
    def manual_operations(self) -> tuple[SchemaOperation, ...]:
        return tuple(item for item in self.operations if item.manual_only)

    @property
    def executable_operations(self) -> tuple[SchemaOperation, ...]:
        return tuple(item for item in self.operations if not item.manual_only)

    def is_empty(self) -> bool:
        return not self.operations


class SchemaCompiler:
    """Compile Python declarations, live IRIS metadata, and .cls input into AST."""

    def __init__(self, adapter: IRISAdapter | None = None) -> None:
        self.adapter = adapter or IRISAdapter()

    def compile_model(self, model_class: type) -> SchemaClass:
        fields = []
        for name, field_def in sorted(
            getattr(model_class, "_iris_declared_fields", {}).items(),
            key=lambda item: item[0],
        ):
            python_type = getattr(field_def, "python_type", None)
            iris_type = field_def.iris_type or _iris_type_for_python_field(python_type)
            fields.append(
                SchemaProperty(
                    name=name,
                    iris_type=iris_type,
                    required=bool(field_def.required),
                    collection=str(field_def.collection or ""),
                    default=_default_literal(
                        field_def.default,
                        iris_type=iris_type,
                        python_type=python_type,
                    ),
                    maxlen=field_def.maxlen,
                    description=str(field_def.description or ""),
                )
            )

        relationships = [
            SchemaRelationship(
                name=name,
                related_classname=rel.related_classname,
                cardinality=rel.cardinality,
                inverse=rel.inverse,
                description=rel.description,
            )
            for name, rel in sorted(
                getattr(model_class, "_iris_declared_relationships", {}).items(),
                key=lambda item: item[0],
            )
        ]

        kind = "serial" if getattr(model_class, "_iris_serial", False) else "persistent"
        superclass = getattr(
            model_class,
            "_iris_superclass",
            "%SerialObject" if kind == "serial" else "%Persistent",
        )
        source = {"kind": "declared", "origin": _model_origin(model_class)}
        return SchemaClass(
            name=model_class._iris_classname,  # type: ignore[attr-defined]
            superclass=superclass,
            kind=kind,
            properties=tuple(fields),
            relationships=tuple(relationships),
            indexes=tuple(
                SchemaIndex.from_dict(dict(item))
                for item in list(getattr(model_class, "_iris_indexes", []))
            ),
            triggers=tuple(
                SchemaTrigger.from_dict(dict(item))
                for item in list(getattr(model_class, "_iris_triggers", []))
            ),
            parameters={
                str(key): str(value)
                for key, value in dict(getattr(model_class, "_iris_class_parameters", {})).items()
            },
            storage=_storage_from_mapping(getattr(model_class, "_iris_storage", None)),
            source=source,
        )

    def catalog_from_registry(self, registry: "Registry") -> SchemaCatalog:
        return SchemaCatalog(classes=tuple(self.compile_model(model) for model in registry.declared_models()))

    def class_from_iris(self, classname: str) -> SchemaClass:
        class_def = self.adapter.iris_cls("%Dictionary.ClassDefinition")._OpenId(classname)
        if not self.adapter.looks_like_iris_object(class_def):
            raise LookupError(f"Unable to open %Dictionary.ClassDefinition for {classname!r}")

        superclass = str(getattr(class_def, "Super", "") or "%Persistent")
        kind = "serial" if superclass == "%SerialObject" else "persistent"
        properties: list[SchemaProperty] = []
        relationships: list[SchemaRelationship] = []
        indexes: list[SchemaIndex] = []
        triggers: list[SchemaTrigger] = []
        parameters: dict[str, str] = {}

        for prop_def in _iter_collection(getattr(class_def, "Properties", None)):
            if bool(getattr(prop_def, "Private", False)) or bool(getattr(prop_def, "Internal", False)):
                continue
            if bool(getattr(prop_def, "Relationship", False)):
                relationships.append(
                    SchemaRelationship(
                        name=str(getattr(prop_def, "Name", "") or ""),
                        related_classname=str(getattr(prop_def, "Type", "") or ""),
                        cardinality=_normalize_cardinality(str(getattr(prop_def, "Cardinality", "") or "")),
                        inverse=str(getattr(prop_def, "Inverse", "") or ""),
                        description=str(getattr(prop_def, "Description", "") or ""),
                    )
                )
                continue
            name = str(getattr(prop_def, "Name", "") or "")
            if not name:
                continue
            properties.append(
                SchemaProperty(
                    name=name,
                    iris_type=str(getattr(prop_def, "Type", "") or "%String"),
                    required=bool(getattr(prop_def, "Required", False)),
                    collection=str(getattr(prop_def, "Collection", "") or "").lower(),
                    default=_normalize_initial_expression(getattr(prop_def, "InitialExpression", "")),
                    maxlen=_property_maxlen(prop_def),
                    description=str(getattr(prop_def, "Description", "") or ""),
                )
            )

        for index_def in _iter_collection(getattr(class_def, "Indices", None)):
            name = str(getattr(index_def, "Name", "") or "")
            if not name:
                continue
            indexes.append(
                SchemaIndex(
                    name=name,
                    properties=str(getattr(index_def, "Properties", "") or ""),
                    unique=bool(getattr(index_def, "Unique", False)),
                    primary_key=bool(getattr(index_def, "PrimaryKey", False)),
                )
            )

        for trigger_def in _iter_collection(getattr(class_def, "Triggers", None)):
            name = str(getattr(trigger_def, "Name", "") or "")
            if not name:
                continue
            triggers.append(
                SchemaTrigger(
                    name=name,
                    event=str(getattr(trigger_def, "Event", "") or "").upper(),
                    time=str(getattr(trigger_def, "Time", "") or "").upper(),
                    code=str(getattr(trigger_def, "Code", "") or ""),
                )
            )

        for param_def in _iter_collection(getattr(class_def, "Parameters", None)):
            name = str(getattr(param_def, "Name", "") or "")
            if not name:
                continue
            parameters[name] = str(getattr(param_def, "Default", "") or "")

        storage = None
        storages = _iter_collection(getattr(class_def, "Storages", None))
        if storages:
            storage = _storage_from_dictionary_object(storages[0])

        return SchemaClass(
            name=classname,
            superclass=superclass,
            kind=kind,
            properties=tuple(sorted(properties, key=lambda item: item.name)),
            relationships=tuple(sorted(relationships, key=lambda item: item.name)),
            indexes=tuple(sorted(indexes, key=lambda item: item.name)),
            triggers=tuple(sorted(triggers, key=lambda item: item.name)),
            parameters={key: parameters[key] for key in sorted(parameters)},
            storage=storage,
            source={"kind": "iris", "origin": classname},
        )

    def catalog_from_iris(self, classnames: list[str]) -> SchemaCatalog:
        classes = []
        for classname in sorted(set(classnames)):
            if not self.adapter.class_exists(classname):
                continue
            classes.append(self.class_from_iris(classname))
        return SchemaCatalog(classes=tuple(classes))

    def catalog_from_cls_path(self, path: str | Path) -> SchemaCatalog:
        root = Path(path)
        if root.is_dir():
            classes = [
                self.class_from_cls_source(item.read_text(encoding="utf-8"), source_path=item)
                for item in sorted(root.rglob("*.cls"))
            ]
            return SchemaCatalog(classes=tuple(classes))
        return SchemaCatalog(classes=(self.class_from_cls_source(root.read_text(encoding="utf-8"), source_path=root),))

    def class_from_cls_source(self, source: str, *, source_path: str | Path = "") -> SchemaClass:
        class_match = re.search(
            r"Class\s+([A-Za-z0-9_.]+)\s+Extends\s+([A-Za-z0-9_,%.]+)",
            source,
        )
        if class_match is None:
            raise ValueError(f"Unable to discover class header in {source_path or '<memory>'}")
        classname = class_match.group(1)
        superclass = class_match.group(2).split(",")[0].strip()
        kind = "serial" if superclass == "%SerialObject" else "persistent"
        properties = tuple(_parse_properties_from_cls(source))
        relationships = tuple(_parse_relationships_from_cls(source))
        indexes = tuple(_parse_indexes_from_cls(source))
        parameters = _parse_parameters_from_cls(source)
        storage = _parse_storage_from_cls(source)
        return SchemaClass(
            name=classname,
            superclass=superclass,
            kind=kind,
            properties=properties,
            relationships=relationships,
            indexes=indexes,
            parameters=parameters,
            storage=storage,
            source={"kind": "cls", "origin": str(source_path)},
        )


class SchemaPlanner:
    """Diff two schema snapshots and emit ordered schema operations."""

    def diff(self, before: SchemaCatalog, after: SchemaCatalog) -> SchemaPlan:
        ops: list[SchemaOperation] = []
        before_map = before.class_map
        after_map = after.class_map

        for classname in sorted(set(before_map) | set(after_map)):
            old_class = before_map.get(classname)
            new_class = after_map.get(classname)
            if old_class is None and new_class is not None:
                ops.append(
                    SchemaOperation(
                        kind="create_class",
                        classname=classname,
                        payload={"class": new_class.to_dict()},
                    )
                )
                ops.extend(self._class_delta(None, new_class))
                continue
            if old_class is not None and new_class is None:
                ops.append(
                    SchemaOperation(
                        kind="drop_class",
                        classname=classname,
                        manual_only=True,
                    )
                )
                continue
            if old_class is None or new_class is None:
                continue
            if old_class.superclass != new_class.superclass:
                ops.append(
                    SchemaOperation(
                        kind="set_superclass",
                        classname=classname,
                        payload={"superclass": new_class.superclass},
                    )
                )
            ops.extend(self._class_delta(old_class, new_class))
        return SchemaPlan(operations=tuple(ops))

    def _class_delta(
        self,
        before_class: SchemaClass | None,
        after_class: SchemaClass,
    ) -> list[SchemaOperation]:
        ops: list[SchemaOperation] = []

        before_props = before_class.property_map if before_class is not None else {}
        after_props = after_class.property_map
        for name in sorted(set(before_props) | set(after_props)):
            old_prop = before_props.get(name)
            new_prop = after_props.get(name)
            if old_prop is None and new_prop is not None:
                ops.append(
                    SchemaOperation(
                        kind="add_property",
                        classname=after_class.name,
                        payload={"property": new_prop.to_dict()},
                    )
                )
            elif old_prop is not None and new_prop is None:
                ops.append(
                    SchemaOperation(
                        kind="drop_property",
                        classname=after_class.name,
                        payload={"name": name},
                        manual_only=True,
                    )
                )
            elif old_prop is not None and new_prop is not None and old_prop != new_prop:
                ops.append(
                    SchemaOperation(
                        kind="alter_property",
                        classname=after_class.name,
                        payload={"property": new_prop.to_dict()},
                    )
                )

        before_rels = before_class.relationship_map if before_class is not None else {}
        after_rels = after_class.relationship_map
        for name in sorted(set(before_rels) | set(after_rels)):
            old_rel = before_rels.get(name)
            new_rel = after_rels.get(name)
            if old_rel is None and new_rel is not None:
                ops.append(
                    SchemaOperation(
                        kind="add_relationship",
                        classname=after_class.name,
                        payload={"relationship": new_rel.to_dict()},
                    )
                )
            elif old_rel is not None and new_rel is None:
                ops.append(
                    SchemaOperation(
                        kind="drop_relationship",
                        classname=after_class.name,
                        payload={"name": name},
                        manual_only=True,
                    )
                )
            elif old_rel is not None and new_rel is not None and old_rel != new_rel:
                ops.append(
                    SchemaOperation(
                        kind="alter_relationship",
                        classname=after_class.name,
                        payload={"relationship": new_rel.to_dict()},
                    )
                )

        before_indexes = before_class.index_map if before_class is not None else {}
        after_indexes = after_class.index_map
        for name in sorted(set(before_indexes) | set(after_indexes)):
            old_index = before_indexes.get(name)
            new_index = after_indexes.get(name)
            if old_index is None and new_index is not None:
                ops.append(
                    SchemaOperation(
                        kind="add_index",
                        classname=after_class.name,
                        payload={"index": new_index.to_dict()},
                    )
                )
            elif old_index is not None and new_index is None:
                ops.append(
                    SchemaOperation(
                        kind="drop_index",
                        classname=after_class.name,
                        payload={"name": name},
                        manual_only=True,
                    )
                )
            elif old_index is not None and new_index is not None and old_index != new_index:
                ops.append(
                    SchemaOperation(
                        kind="alter_index",
                        classname=after_class.name,
                        payload={"index": new_index.to_dict()},
                    )
                )

        before_triggers = before_class.trigger_map if before_class is not None else {}
        after_triggers = after_class.trigger_map
        for name in sorted(set(before_triggers) | set(after_triggers)):
            old_trigger = before_triggers.get(name)
            new_trigger = after_triggers.get(name)
            if old_trigger is None and new_trigger is not None:
                ops.append(
                    SchemaOperation(
                        kind="add_trigger",
                        classname=after_class.name,
                        payload={"trigger": new_trigger.to_dict()},
                    )
                )
            elif old_trigger is not None and new_trigger is None:
                ops.append(
                    SchemaOperation(
                        kind="drop_trigger",
                        classname=after_class.name,
                        payload={"name": name},
                        manual_only=True,
                    )
                )
            elif old_trigger is not None and new_trigger is not None and old_trigger != new_trigger:
                ops.append(
                    SchemaOperation(
                        kind="alter_trigger",
                        classname=after_class.name,
                        payload={"trigger": new_trigger.to_dict()},
                    )
                )

        before_params = dict(before_class.parameters) if before_class is not None else {}
        after_params = dict(after_class.parameters)
        for name in sorted(set(before_params) | set(after_params)):
            old_value = before_params.get(name)
            new_value = after_params.get(name)
            if old_value == new_value:
                continue
            if new_value is None:
                ops.append(
                    SchemaOperation(
                        kind="drop_parameter",
                        classname=after_class.name,
                        payload={"name": name},
                        manual_only=True,
                    )
                )
            else:
                ops.append(
                    SchemaOperation(
                        kind="set_parameter",
                        classname=after_class.name,
                        payload={"name": name, "value": new_value},
                    )
                )

        if after_class.storage is None:
            if before_class is not None and before_class.storage is not None:
                ops.append(
                    SchemaOperation(
                        kind="clear_storage",
                        classname=after_class.name,
                        manual_only=True,
                    )
                )
        elif before_class is None or before_class.storage != after_class.storage:
            ops.append(
                SchemaOperation(
                    kind="set_storage",
                    classname=after_class.name,
                    payload={"storage": after_class.storage.to_dict()},
                )
            )

        return ops


class SchemaApplier:
    """Apply schema operations to a live IRIS namespace via %Dictionary."""

    def __init__(self, adapter: IRISAdapter | None = None) -> None:
        self.adapter = adapter or IRISAdapter()

    def apply(self, plan: SchemaPlan, *, allow_manual: bool = False) -> None:
        changed_classes: set[str] = set()
        manual = [item for item in plan.operations if item.manual_only]
        if manual and not allow_manual:
            names = ", ".join(f"{item.kind}:{item.classname}" for item in manual)
            raise RuntimeError(f"Manual operations required before apply: {names}")

        for op in plan.operations:
            if op.manual_only and not allow_manual:
                continue
            if op.kind == "create_class":
                self._create_class(SchemaClass.from_dict(dict(op.payload["class"])))
                changed_classes.add(op.classname)
            elif op.kind == "drop_class":
                self.adapter.iris_cls("%Dictionary.ClassDefinition")._DeleteId(op.classname)
            elif op.kind == "set_superclass":
                class_def = self._open_class_definition(op.classname)
                class_def.Super = op.payload["superclass"]
                self.adapter.save(class_def, kind="class", identifier=op.classname)
                changed_classes.add(op.classname)
            elif op.kind in {"add_property", "alter_property"}:
                self._upsert_property(op.classname, SchemaProperty.from_dict(dict(op.payload["property"])))
                changed_classes.add(op.classname)
            elif op.kind == "drop_property":
                self.adapter.iris_cls("%Dictionary.PropertyDefinition")._DeleteId(
                    f"{op.classname}||{op.payload['name']}"
                )
                changed_classes.add(op.classname)
            elif op.kind in {"add_relationship", "alter_relationship"}:
                self._upsert_relationship(
                    op.classname,
                    SchemaRelationship.from_dict(dict(op.payload["relationship"])),
                )
                changed_classes.add(op.classname)
            elif op.kind == "drop_relationship":
                deleted = False
                for dictionary_class in ("%Dictionary.RelationshipDefinition", "%Dictionary.PropertyDefinition"):
                    try:
                        self.adapter.iris_cls(dictionary_class)._DeleteId(
                            f"{op.classname}||{op.payload['name']}"
                        )
                        deleted = True
                        break
                    except Exception:
                        continue
                if not deleted:
                    raise RuntimeError(
                        f"Unable to delete relationship {op.payload['name']!r} on {op.classname!r}"
                    )
                changed_classes.add(op.classname)
            elif op.kind in {"add_index", "alter_index"}:
                self._upsert_index(op.classname, SchemaIndex.from_dict(dict(op.payload["index"])))
                changed_classes.add(op.classname)
            elif op.kind == "drop_index":
                self.adapter.iris_cls("%Dictionary.IndexDefinition")._DeleteId(
                    f"{op.classname}||{op.payload['name']}"
                )
                changed_classes.add(op.classname)
            elif op.kind in {"add_trigger", "alter_trigger"}:
                self._upsert_trigger(op.classname, SchemaTrigger.from_dict(dict(op.payload["trigger"])))
                changed_classes.add(op.classname)
            elif op.kind == "drop_trigger":
                self.adapter.iris_cls("%Dictionary.TriggerDefinition")._DeleteId(
                    f"{op.classname}||{op.payload['name']}"
                )
                changed_classes.add(op.classname)
            elif op.kind == "set_parameter":
                self._set_parameter(op.classname, str(op.payload["name"]), str(op.payload["value"]))
                changed_classes.add(op.classname)
            elif op.kind == "drop_parameter":
                self.adapter.iris_cls("%Dictionary.ParameterDefinition")._DeleteId(
                    f"{op.classname}||{op.payload['name']}"
                )
                changed_classes.add(op.classname)
            elif op.kind == "set_storage":
                self._set_storage(op.classname, SchemaStorage.from_dict(dict(op.payload["storage"])))
                changed_classes.add(op.classname)
            elif op.kind == "clear_storage":
                cleared = False
                try:
                    class_def = self._open_class_definition(op.classname)
                    for storage_def in _iter_collection(getattr(class_def, "Storages", None)):
                        storage_name = str(getattr(storage_def, "Name", "") or "")
                        if not storage_name:
                            continue
                        self.adapter.iris_cls("%Dictionary.StorageDefinition")._DeleteId(
                            f"{op.classname}||{storage_name}"
                        )
                        cleared = True
                except Exception:
                    pass
                if not cleared:
                    class_def = self._open_class_definition(op.classname)
                    if hasattr(class_def, "Storage"):
                        class_def.Storage = ""
                    if hasattr(class_def, "StorageDefinition"):
                        class_def.StorageDefinition = ""
                    self.adapter.save(class_def, kind="class", identifier=op.classname)
                changed_classes.add(op.classname)

        for classname in sorted(changed_classes):
            self.adapter.compile_class(classname)

    def _create_class(self, schema_class: SchemaClass) -> None:
        if self.adapter.class_exists(schema_class.name):
            return
        class_def = self.adapter.iris_cls("%Dictionary.ClassDefinition")._New()
        class_def.Name = schema_class.name
        class_def.Super = schema_class.superclass
        self.adapter.save(class_def, kind="class", identifier=schema_class.name)

    def _open_class_definition(self, classname: str) -> Any:
        class_def = self.adapter.iris_cls("%Dictionary.ClassDefinition")._OpenId(classname)
        if not self.adapter.looks_like_iris_object(class_def):
            raise RuntimeError(f"Unable to open %Dictionary.ClassDefinition for {classname!r}")
        return class_def

    def _open_or_new(self, definition_cls: Any, item_id: str, *, name: str, parent: Any) -> Any:
        try:
            item = definition_cls._OpenId(item_id)
        except Exception:
            item = None
        if not self.adapter.looks_like_iris_object(item):
            item = definition_cls._New()
            item.Name = name
            item.parent = parent
        return item

    def _upsert_property(self, classname: str, prop: SchemaProperty) -> None:
        class_def = self._open_class_definition(classname)
        prop_def_cls = self.adapter.iris_cls("%Dictionary.PropertyDefinition")
        prop_id = f"{classname}||{prop.name}"
        prop_def = self._open_or_new(prop_def_cls, prop_id, name=prop.name, parent=class_def)
        prop_def.Type = prop.iris_type
        prop_def.Required = int(prop.required)
        prop_def.Collection = prop.collection.capitalize() if prop.collection else ""
        if prop.default:
            prop_def.InitialExpression = prop.default
        else:
            prop_def.InitialExpression = ""
        prop_def.Description = prop.description
        if prop.maxlen is not None:
            prop_def.Parameters.SetAt(str(prop.maxlen), "MAXLEN")
        self.adapter.save(prop_def, kind="property", identifier=prop_id)

    def _upsert_relationship(self, classname: str, rel: SchemaRelationship) -> None:
        class_def = self._open_class_definition(classname)
        use_property_definition = False
        try:
            rel_def_cls = self.adapter.iris_cls("%Dictionary.RelationshipDefinition")
        except Exception:
            rel_def_cls = self.adapter.iris_cls("%Dictionary.PropertyDefinition")
            use_property_definition = True
        rel_id = f"{classname}||{rel.name}"
        rel_def = self._open_or_new(rel_def_cls, rel_id, name=rel.name, parent=class_def)
        rel_def.Type = rel.related_classname
        rel_def.Cardinality = _relationship_cardinality_keyword(rel.cardinality)
        rel_def.Inverse = rel.inverse
        rel_def.Description = rel.description
        if use_property_definition:
            rel_def.Relationship = 1
        self.adapter.save(rel_def, kind="relationship", identifier=rel_id)

    def _upsert_index(self, classname: str, index: SchemaIndex) -> None:
        class_def = self._open_class_definition(classname)
        index_def_cls = self.adapter.iris_cls("%Dictionary.IndexDefinition")
        index_id = f"{classname}||{index.name}"
        index_def = self._open_or_new(index_def_cls, index_id, name=index.name, parent=class_def)
        index_def.Properties = index.properties
        index_def.Unique = int(index.unique)
        index_def.PrimaryKey = int(index.primary_key)
        self.adapter.save(index_def, kind="index", identifier=index_id)

    def _upsert_trigger(self, classname: str, trigger: SchemaTrigger) -> None:
        class_def = self._open_class_definition(classname)
        trigger_def_cls = self.adapter.iris_cls("%Dictionary.TriggerDefinition")
        trigger_id = f"{classname}||{trigger.name}"
        trigger_def = self._open_or_new(trigger_def_cls, trigger_id, name=trigger.name, parent=class_def)
        trigger_def.Event = trigger.event
        trigger_def.Time = trigger.time
        trigger_def.Code = trigger.code
        self.adapter.save(trigger_def, kind="trigger", identifier=trigger_id)

    def _set_parameter(self, classname: str, name: str, value: str) -> None:
        class_def = self._open_class_definition(classname)
        param_def_cls = self.adapter.iris_cls("%Dictionary.ParameterDefinition")
        param_id = f"{classname}||{name}"
        param_def = self._open_or_new(param_def_cls, param_id, name=name, parent=class_def)
        param_def.Default = value
        self.adapter.save(param_def, kind="parameter", identifier=param_id)

    def _set_storage(self, classname: str, storage: SchemaStorage) -> None:
        class_def = self._open_class_definition(classname)
        rendered = render_storage(storage)
        class_def.Storage = rendered
        class_def.StorageDefinition = rendered
        self.adapter.save(class_def, kind="class", identifier=classname)


def render_storage(storage: SchemaStorage | None) -> str:
    if storage is None:
        return ""
    lines = [f"Storage {storage.name}", "{"]
    scalar_fields = [
        ("Type", storage.storage_type),
        ("DataLocation", storage.data_location),
        ("DefaultData", storage.default_data),
        ("ExtentLocation", storage.extent_location),
        ("IdLocation", storage.id_location),
        ("IndexLocation", storage.index_location),
        ("StreamLocation", storage.stream_location),
        ("IdFunction", storage.id_function),
    ]
    for tag, value in scalar_fields:
        if value:
            lines.append(f"<{tag}>{value}</{tag}>")
    for data_item in storage.data:
        if data_item.name:
            lines.append(f'<Data name="{data_item.name}">')
        else:
            lines.append("<Data>")
        if data_item.structure:
            lines.append(f"<Structure>{data_item.structure}</Structure>")
        if data_item.subscript:
            lines.append(f"<Subscript>{data_item.subscript}</Subscript>")
        for value in data_item.values:
            if value.name:
                lines.append(f'<Value name="{value.name}">{value.value}</Value>')
            else:
                lines.append(f"<Value>{value.value}</Value>")
        lines.append("</Data>")
    lines.append("}")
    return "\n".join(lines)


def _model_origin(model_class: type) -> str:
    try:
        return str(Path(inspect.getfile(model_class)).resolve())
    except (OSError, TypeError):
        return model_class.__name__


def _iter_collection(collection: Any) -> list[Any]:
    if collection is None:
        return []
    try:
        count = int(collection.Count())
    except Exception:
        return []
    items: list[Any] = []
    for index in range(1, count + 1):
        try:
            items.append(collection.GetAt(index))
        except Exception:
            continue
    return items


def _property_maxlen(prop_def: Any) -> int | None:
    try:
        value = prop_def.Parameters.GetAt("MAXLEN")
    except Exception:
        return None
    return _as_int(value)


def _storage_from_dictionary_object(storage_def: Any) -> SchemaStorage:
    return SchemaStorage(
        name=str(getattr(storage_def, "Name", "") or "Default"),
        storage_type=str(getattr(storage_def, "Type", "") or ""),
        data_location=str(getattr(storage_def, "DataLocation", "") or ""),
        default_data=str(getattr(storage_def, "DefaultData", "") or ""),
        extent_location=str(getattr(storage_def, "ExtentLocation", "") or ""),
        id_location=str(getattr(storage_def, "IdLocation", "") or ""),
        index_location=str(getattr(storage_def, "IndexLocation", "") or ""),
        stream_location=str(getattr(storage_def, "StreamLocation", "") or ""),
        id_function=str(getattr(storage_def, "IdFunction", "") or ""),
        data=tuple(
            SchemaStorageData(
                name=str(getattr(data_def, "Name", "") or ""),
                structure=str(getattr(data_def, "Structure", "") or ""),
                subscript=str(getattr(data_def, "Subscript", "") or ""),
                values=tuple(
                    SchemaStorageValue(
                        name=str(getattr(value_def, "Name", "") or ""),
                        value=str(getattr(value_def, "Value", "") or ""),
                    )
                    for value_def in _iter_collection(getattr(data_def, "Values", None))
                ),
            )
            for data_def in _iter_collection(getattr(storage_def, "Data", None))
        ),
    )


def _storage_from_mapping(value: Any) -> SchemaStorage | None:
    if value is None or value == "":
        return None
    if isinstance(value, SchemaStorage):
        return value
    if isinstance(value, dict):
        return SchemaStorage.from_dict(dict(value))
    raise TypeError(f"Unsupported storage payload: {type(value)!r}")


def _iris_type_for_python_field(python_type: Any) -> str:
    if isinstance(python_type, type) and getattr(python_type, "_iris_serial", False):
        return python_type._iris_classname  # type: ignore[attr-defined]
    return python_type_to_iris(python_type)


def _default_literal(
    value: Any,
    *,
    iris_type: str = "",
    python_type: Any = None,
) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set, dict)) and not value:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, datetime.datetime):
        return _quote_iris_string(value.strftime("%Y-%m-%d %H:%M:%S"))
    if isinstance(value, datetime.date):
        return _quote_iris_string(value.strftime("%Y-%m-%d"))
    if isinstance(value, datetime.time):
        return _quote_iris_string(value.strftime("%H:%M:%S"))
    if isinstance(value, str):
        raw = value.strip()
        if raw == "":
            return ""
        if _is_boolean_type(iris_type, python_type):
            normalized = raw.lower()
            if normalized in {"1", "true", "t", "yes"}:
                return "1"
            if normalized in {"0", "false", "f", "no"}:
                return "0"
        if _is_numeric_type(iris_type, python_type):
            return raw
        if _is_string_type(iris_type, python_type):
            if _is_iris_string_literal(raw):
                return raw
            return _quote_iris_string(raw)
        return raw
    return str(value)


def _normalize_initial_expression(value: Any) -> str:
    raw = str(value or "")
    if raw in {"", '""'}:
        return ""
    return raw


def _is_boolean_type(iris_type: str, python_type: Any) -> bool:
    return iris_type in {"%Boolean", "%Library.Boolean"} or python_type is bool


def _is_numeric_type(iris_type: str, python_type: Any) -> bool:
    return iris_type in {
        "%Integer",
        "%SmallInt",
        "%BigInt",
        "%Float",
        "%Double",
        "%Numeric",
        "%Decimal",
        "%Library.Integer",
        "%Library.Numeric",
        "%Library.Float",
        "%Library.Double",
    } or python_type in {int, float}


def _is_string_type(iris_type: str, python_type: Any) -> bool:
    return iris_type in {"%String", "%Library.String"} or python_type is str


def _is_iris_string_literal(value: str) -> bool:
    return len(value) >= 2 and value.startswith('"') and value.endswith('"')


def _quote_iris_string(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _normalize_cardinality(value: str) -> str:
    lowered = str(value or "").lower()
    if lowered == "child":
        return "children"
    if lowered == "one":
        return "parent"
    if lowered == "many":
        return "children"
    if lowered in {"parent", "children"}:
        return lowered
    return lowered or "parent"


def _relationship_cardinality_keyword(value: str) -> str:
    mapping = {"children": "many", "many": "many", "parent": "one", "one": "one"}
    return mapping.get(value, value)


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _parse_assignment_list(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    if not value.strip():
        return result
    for part in [piece.strip() for piece in value.split(",") if piece.strip()]:
        if "=" in part:
            key, raw_value = part.split("=", 1)
            result[key.strip().lower()] = raw_value.strip().strip('"')
        else:
            result[part.strip().lower()] = "1"
    return result


def _parse_flag_list(value: str) -> set[str]:
    return {piece.strip().lower() for piece in value.split(",") if piece.strip()}


def _parse_properties_from_cls(source: str) -> list[SchemaProperty]:
    props: list[SchemaProperty] = []
    pattern = re.compile(
        r"Property\s+([A-Za-z][A-Za-z0-9_]*)\s+As\s+([A-Za-z0-9_.%]+)"
        r"(?:\s*\(\s*([^)]+)\s*\))?"
        r"(?:\s*\[\s*([^\]]+)\s*\])?;"
    )
    for match in pattern.finditer(source):
        params = _parse_assignment_list(match.group(3) or "")
        qualifiers = _parse_flag_list(match.group(4) or "")
        props.append(
            SchemaProperty(
                name=match.group(1),
                iris_type=match.group(2),
                required="required" in qualifiers,
                collection=str(params.get("collection", "")).lower(),
                default=str(params.get("initialexpression", "")),
                maxlen=_as_int(params.get("maxlen")),
            )
        )
    return props


def _parse_relationships_from_cls(source: str) -> list[SchemaRelationship]:
    rels: list[SchemaRelationship] = []
    pattern = re.compile(
        r"Relationship\s+([A-Za-z][A-Za-z0-9_]*)\s+As\s+([A-Za-z0-9_.%]+)"
        r"\s*\[\s*([^\]]+)\s*\]\s*;"
    )
    for match in pattern.finditer(source):
        attrs = _parse_assignment_list(match.group(3))
        rels.append(
            SchemaRelationship(
                name=match.group(1),
                related_classname=match.group(2),
                cardinality=_normalize_cardinality(str(attrs.get("cardinality", "one"))),
                inverse=str(attrs.get("inverse", "")),
            )
        )
    return rels


def _parse_parameters_from_cls(source: str) -> dict[str, str]:
    params: dict[str, str] = {}
    pattern = re.compile(r"Parameter\s+([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.+?);")
    for match in pattern.finditer(source):
        params[match.group(1)] = match.group(2).strip()
    return params


def _parse_indexes_from_cls(source: str) -> list[SchemaIndex]:
    indexes: list[SchemaIndex] = []
    pattern = re.compile(
        r"Index\s+([A-Za-z][A-Za-z0-9_]*)\s+On\s+\(([^)]*)\)"
        r"(?:\s*\[\s*([^\]]+)\s*\])?;"
    )
    for match in pattern.finditer(source):
        attrs = _parse_assignment_list(match.group(3) or "")
        indexes.append(
            SchemaIndex(
                name=match.group(1),
                properties=match.group(2).strip(),
                unique=str(attrs.get("unique", "")).lower() in {"1", "true", "yes"},
                primary_key=str(attrs.get("primarykey", "")).lower() in {"1", "true", "yes"},
            )
        )
    return indexes


def _parse_storage_from_cls(source: str) -> SchemaStorage | None:
    match = re.search(r"Storage\s+([A-Za-z0-9_]+)\s*\{(.*)\}\s*$", source, re.DOTALL | re.MULTILINE)
    if match is None:
        return None
    body = match.group(2)
    scalar_tags = {
        "Type": "type",
        "DataLocation": "data_location",
        "DefaultData": "default_data",
        "ExtentLocation": "extent_location",
        "IdLocation": "id_location",
        "IndexLocation": "index_location",
        "StreamLocation": "stream_location",
        "IdFunction": "id_function",
    }
    payload: dict[str, Any] = {"name": match.group(1), "data": []}
    for tag, key in scalar_tags.items():
        value_match = re.search(fr"<{tag}>(.*?)</{tag}>", body, re.DOTALL)
        if value_match is not None:
            payload[key] = value_match.group(1).strip()

    for data_match in re.finditer(r"<Data(?:\s+name=\"([^\"]*)\")?\s*>(.*?)</Data>", body, re.DOTALL):
        data_payload: dict[str, Any] = {"name": data_match.group(1) or "", "values": []}
        inner = data_match.group(2)
        structure_match = re.search(r"<Structure>(.*?)</Structure>", inner, re.DOTALL)
        if structure_match is not None:
            data_payload["structure"] = structure_match.group(1).strip()
        subscript_match = re.search(r"<Subscript>(.*?)</Subscript>", inner, re.DOTALL)
        if subscript_match is not None:
            data_payload["subscript"] = subscript_match.group(1).strip()
        for value_match in re.finditer(r"<Value(?:\s+name=\"([^\"]*)\")?>(.*?)</Value>", inner, re.DOTALL):
            data_payload["values"].append(
                {"name": value_match.group(1) or "", "value": value_match.group(2).strip()}
            )
        payload["data"].append(data_payload)
    return SchemaStorage.from_dict(payload)


def python_annotation_for_property(prop: SchemaProperty) -> str:
    python_type = iris_type_to_python(prop.iris_type)
    if python_type is Any:
        return "Any"
    if python_type.__module__ == "datetime":
        return f"datetime.{python_type.__name__}"
    return python_type.__name__


def compile_declared_model_schema(model_class: type) -> SchemaClass:
    return SchemaCompiler().compile_model(model_class)
