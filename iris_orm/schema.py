from __future__ import annotations

import copy
import fnmatch
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

from .storage import StorageDefinition

PYTHON_TO_IRIS: dict[type, str] = {
    str: "%String",
    int: "%Integer",
    float: "%Float",
    bool: "%Boolean",
    bytes: "%Stream.GlobalBinary",
}

IRIS_TO_PYTHON: dict[str, type] = {
    "%String": str,
    "%Integer": int,
    "%SmallInt": int,
    "%BigInt": int,
    "%Float": float,
    "%Double": float,
    "%Numeric": float,
    "%Decimal": float,
    "%Boolean": bool,
    "%Stream.GlobalBinary": bytes,
    "%Stream.GlobalCharacter": str,
}


@dataclass(frozen=True)
class SchemaProperty:
    name: str
    iris_type: str
    required: bool = False
    default: str = ""
    maxlen: int | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "iris_type": self.iris_type,
            "required": self.required,
            "default": self.default,
            "maxlen": self.maxlen,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchemaProperty":
        return cls(
            name=str(payload["name"]),
            iris_type=str(payload.get("iris_type") or "%String"),
            required=bool(payload.get("required", False)),
            default=str(payload.get("default", "") or ""),
            maxlen=payload.get("maxlen"),
            description=str(payload.get("description", "") or ""),
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
            properties=str(payload.get("properties", "") or ""),
            unique=bool(payload.get("unique", False)),
            primary_key=bool(payload.get("primary_key", False)),
        )


@dataclass(frozen=True)
class SchemaClass:
    name: str
    superclasses: tuple[str, ...]
    properties: tuple[SchemaProperty, ...]
    indexes: tuple[SchemaIndex, ...] = ()
    parameters: dict[str, str] = dataclass_field(default_factory=dict)
    storage: StorageDefinition | None = None
    source: dict[str, Any] | None = None

    @property
    def property_map(self) -> dict[str, SchemaProperty]:
        return {item.name: item for item in self.properties}

    @property
    def index_map(self) -> dict[str, SchemaIndex]:
        return {item.name: item for item in self.indexes}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "superclasses": list(self.superclasses),
            "properties": [item.to_dict() for item in self.properties],
            "indexes": [item.to_dict() for item in self.indexes],
            "parameters": dict(sorted(self.parameters.items())),
            "storage": None if self.storage is None else self.storage.to_dict(),
            "source": copy.deepcopy(self.source),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SchemaClass":
        return cls(
            name=str(payload["name"]),
            superclasses=normalize_superclasses(payload.get("superclasses", "%Persistent")),
            properties=tuple(SchemaProperty.from_dict(item) for item in payload.get("properties", [])),
            indexes=tuple(SchemaIndex.from_dict(item) for item in payload.get("indexes", [])),
            parameters={str(k): str(v) for k, v in dict(payload.get("parameters", {})).items()},
            storage=StorageDefinition.from_dict(payload.get("storage")),
            source=copy.deepcopy(payload.get("source")),
        )


@dataclass(frozen=True)
class SchemaPlan:
    classname: str
    desired: SchemaClass
    live: SchemaClass | None

    @property
    def differs(self) -> bool:
        if self.live is None:
            return True
        return schema_equals(self.live, self.desired) is False


def _canonicalize(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: _canonicalize(payload[key]) for key in sorted(payload)}
    if isinstance(payload, list):
        return [_canonicalize(item) for item in payload]
    return payload


def schema_identity(payload: SchemaClass | dict[str, Any]) -> Any:
    data = payload.to_dict() if isinstance(payload, SchemaClass) else copy.deepcopy(payload)
    data.pop("source", None)
    return _canonicalize(data)


def schema_equals(left: SchemaClass | dict[str, Any], right: SchemaClass | dict[str, Any]) -> bool:
    return schema_identity(left) == schema_identity(right)


def normalize_superclasses(value: Any) -> tuple[str, ...]:
    if value is None:
        return ("%Persistent",)
    if isinstance(value, str):
        if value == "":
            return ("%Persistent",)
        parts = [item.strip() for item in value.split(",") if item.strip()]
        return tuple(parts or ["%Persistent"])
    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return tuple(parts or ["%Persistent"])
    raise TypeError(f"Unsupported _iris_superclasses value: {type(value)!r}")


def python_type_to_iris(annotation: Any) -> str:
    if isinstance(annotation, str):
        return annotation
    if getattr(annotation, "__origin__", None) is None and annotation in PYTHON_TO_IRIS:
        return PYTHON_TO_IRIS[annotation]
    return "%String"


def iris_type_to_python(iris_type: str) -> type:
    return IRIS_TO_PYTHON.get(iris_type, str)


def default_literal(value: Any, iris_type: str) -> str:
    if value is None or value == "" or value == [] or value == {}:
        return ""
    if iris_type == "%Boolean":
        if isinstance(value, str):
            return "1" if value.strip().lower() in {"1", "true"} else "0"
        return "1" if bool(value) else "0"
    if iris_type in {"%Integer", "%SmallInt", "%BigInt"}:
        return str(int(value))
    if iris_type in {"%Float", "%Double", "%Numeric", "%Decimal"}:
        return str(float(value))
    if isinstance(value, str):
        escaped = value.replace('"', '""')
        return f'"{escaped}"'
    return str(value)


def python_default_source(default: str, iris_type: str) -> str | None:
    if default == "":
        return None
    if iris_type == "%Boolean":
        return "True" if default.strip().lower() in {"1", "true"} else "False"
    if iris_type in {"%Integer", "%SmallInt", "%BigInt"}:
        return str(int(default))
    if iris_type in {"%Float", "%Double", "%Numeric", "%Decimal"}:
        return repr(float(default))
    if len(default) >= 2 and default.startswith('"') and default.endswith('"'):
        return repr(default[1:-1].replace('""', '"'))
    return repr(default)


def python_default_value(default: str, iris_type: str) -> Any:
    if default == "":
        return None
    if iris_type == "%Boolean":
        return default.strip().lower() in {"1", "true"}
    if iris_type in {"%Integer", "%SmallInt", "%BigInt"}:
        return int(default)
    if iris_type in {"%Float", "%Double", "%Numeric", "%Decimal"}:
        return float(default)
    if len(default) >= 2 and default.startswith('"') and default.endswith('"'):
        return default[1:-1].replace('""', '"')
    return default


class SchemaCompiler:
    def __init__(self, adapter: Any | None = None) -> None:
        self.adapter = adapter

    def compile_model(self, model_class: type) -> SchemaClass:
        properties: list[SchemaProperty] = []
        for name, field_def in sorted(getattr(model_class, "_iris_declared_fields", {}).items()):
            python_type = getattr(field_def, "python_type", None)
            iris_type = str(field_def.iris_type or python_type_to_iris(python_type))
            properties.append(
                SchemaProperty(
                    name=name,
                    iris_type=iris_type,
                    required=bool(field_def.required),
                    default=default_literal(field_def.default, iris_type) if field_def.has_default else "",
                    maxlen=field_def.maxlen,
                    description=str(field_def.description or ""),
                )
            )
        indexes = tuple(
            SchemaIndex.from_dict(item if isinstance(item, dict) else item.to_dict())
            for item in getattr(model_class, "_iris_indexes", [])
        )
        parameters = {str(k): str(v) for k, v in dict(getattr(model_class, "_iris_parameters", {})).items()}
        storage = StorageDefinition.from_dict(getattr(model_class, "_iris_storage", None))
        return SchemaClass(
            name=str(model_class._iris_classname),
            superclasses=normalize_superclasses(getattr(model_class, "_iris_superclasses", "%Persistent")),
            properties=tuple(properties),
            indexes=indexes,
            parameters=parameters,
            storage=storage,
            source={"kind": "python", "mode": getattr(model_class, "_iris_mode", "python")},
        )

    def class_from_iris(self, classname: str) -> SchemaClass:
        if self.adapter is None:
            raise RuntimeError("An adapter is required to introspect IRIS")
        payload = self.adapter.load_schema(classname)
        if payload is None:
            raise LookupError(f"IRIS class not found: {classname}")
        return SchemaClass.from_dict(payload)

    def catalog_from_iris(self, classnames: list[str]) -> list[SchemaClass]:
        return [self.class_from_iris(name) for name in classnames]

    def catalog_from_cls_path(self, cls_root: str | Path) -> list[SchemaClass]:
        from .scaffold import parse_cls

        root = Path(cls_root)
        classes: list[SchemaClass] = []
        for path in sorted(root.rglob("*.cls")):
            classes.append(parse_cls(path.read_text(encoding="utf-8"), source_path=str(path)))
        return classes


def match_classnames(classnames: list[str], pattern: str) -> list[str]:
    return [name for name in classnames if fnmatch.fnmatch(name, pattern)]


def merge_additive_schema(live: SchemaClass, desired: SchemaClass) -> SchemaClass:
    property_names = {item.name for item in live.properties}
    properties = list(live.properties)
    for item in desired.properties:
        if item.name in property_names:
            properties = [item if current.name == item.name else current for current in properties]
        else:
            properties.append(item)

    index_names = {item.name for item in live.indexes}
    indexes = list(live.indexes)
    for item in desired.indexes:
        if item.name in index_names:
            indexes = [item if current.name == item.name else current for current in indexes]
        else:
            indexes.append(item)

    parameters = dict(live.parameters)
    parameters.update(desired.parameters)

    return SchemaClass(
        name=desired.name,
        superclasses=desired.superclasses,
        properties=tuple(properties),
        indexes=tuple(indexes),
        parameters=parameters,
        storage=desired.storage if desired.storage is not None else live.storage,
        source={"kind": "python", "mode": "additive"},
    )
