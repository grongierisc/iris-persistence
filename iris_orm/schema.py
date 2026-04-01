from __future__ import annotations

import copy
import fnmatch
import re
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any

from .fields import _SENTINEL

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
    storage: dict[str, Any] | None = None
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
            "storage": copy.deepcopy(self.storage),
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
            storage=copy.deepcopy(payload.get("storage")),
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
    if value is _SENTINEL or value is None or value == "" or value == [] or value == {}:
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
        return _SENTINEL
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
                    default=default_literal(field_def.default, iris_type),
                    maxlen=field_def.maxlen,
                    description=str(field_def.description or ""),
                )
            )
        indexes = tuple(
            SchemaIndex.from_dict(item if isinstance(item, dict) else item.to_dict())
            for item in getattr(model_class, "_iris_indexes", [])
        )
        parameters = {str(k): str(v) for k, v in dict(getattr(model_class, "_iris_parameters", {})).items()}
        storage = copy.deepcopy(getattr(model_class, "_iris_storage", None))
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
        root = Path(cls_root)
        classes: list[SchemaClass] = []
        for path in sorted(root.rglob("*.cls")):
            classes.append(parse_cls(path.read_text(encoding="utf-8"), source_path=str(path)))
        return classes


def parse_cls(source: str, *, source_path: str = "") -> SchemaClass:
    header = re.search(r"Class\s+([A-Za-z0-9_.%]+)\s+Extends\s+([^\{\[]+?)(?:\s*\[|\s*\{)", source, re.DOTALL)
    if not header:
        raise ValueError("Unable to parse class header")
    classname = header.group(1)
    superclasses = normalize_superclasses(header.group(2))

    properties: list[SchemaProperty] = []
    for match in re.finditer(
        r"Property\s+([A-Za-z0-9_%]+)\s+As\s+([A-Za-z0-9_.%]+)(?:\(([^)]*)\))?\s*(?:\[(.*?)\])?\s*;",
        source,
        re.DOTALL,
    ):
        name, iris_type, args, opts = match.groups()
        maxlen = None
        required = False
        default = ""
        description = ""
        if args:
            maxlen_match = re.search(r"MAXLEN\s*=\s*([0-9]+)", args, re.IGNORECASE)
            if maxlen_match:
                maxlen = int(maxlen_match.group(1))
        if opts:
            required = "required" in opts.lower()
            default_match = re.search(r"InitialExpression\s*=\s*([^,\]]+)", opts, re.IGNORECASE)
            if default_match:
                value = default_match.group(1).strip()
                if value == "{}":
                    value = ""
                default = value if value != '""' else ""
        properties.append(
            SchemaProperty(
                name=name,
                iris_type=iris_type,
                required=required,
                default=default,
                maxlen=maxlen,
                description=description,
            )
        )

    indexes: list[SchemaIndex] = []
    for match in re.finditer(
        r"Index\s+([A-Za-z0-9_%]+)\s+On\s+\(([^)]*)\)\s*(?:\[(.*?)\])?\s*;",
        source,
        re.DOTALL,
    ):
        name, props, opts = match.groups()
        opts_lower = (opts or "").lower()
        indexes.append(
            SchemaIndex(
                name=name,
                properties=",".join(item.strip() for item in props.split(",") if item.strip()),
                unique="unique" in opts_lower,
                primary_key="primarykey" in opts_lower or "primary_key" in opts_lower,
            )
        )

    parameters: dict[str, str] = {}
    for match in re.finditer(r"Parameter\s+([A-Za-z0-9_%]+)\s*=\s*([^;]+);", source):
        parameters[match.group(1)] = match.group(2).strip().strip('"')

    storage = parse_storage_block(source)
    return SchemaClass(
        name=classname,
        superclasses=superclasses,
        properties=tuple(properties),
        indexes=tuple(indexes),
        parameters=parameters,
        storage=storage,
        source={"kind": "cls", "path": source_path},
    )


def parse_storage_block(source: str) -> dict[str, Any] | None:
    match = re.search(r"Storage\s+([A-Za-z0-9_%]+)\s*\{(.*)\n\}", source, re.DOTALL)
    if not match:
        return None
    name, body = match.groups()

    def extract(tag: str) -> str:
        found = re.search(rf"<{tag}>(.*?)</{tag}>", body, re.DOTALL)
        return found.group(1).strip() if found else ""

    data_items: list[dict[str, Any]] = []
    for data_match in re.finditer(r'<Data name="([^"]+)">(.*?)</Data>', body, re.DOTALL):
        data_name, data_body = data_match.groups()
        structure = extract_from(data_body, "Structure")
        values: list[dict[str, str]] = []
        for value_match in re.finditer(r'<Value name="([^"]+)">\s*<Value>(.*?)</Value>\s*</Value>', data_body, re.DOTALL):
            values.append({"name": value_match.group(1), "value": value_match.group(2).strip()})
        data_items.append({"name": data_name, "structure": structure, "values": values})

    properties = _parse_storage_named_sections(body, "Property")
    sql_maps = _parse_storage_named_sections(body, "SQLMap")

    storage: dict[str, Any] = {
        "name": name,
        "counter_location": extract("CounterLocation"),
        "type": extract("Type"),
        "data_location": extract("DataLocation"),
        "default_data": extract("DefaultData"),
        "description": extract("Description"),
        "extent_location": extract("ExtentLocation"),
        "extent_size": extract("ExtentSize"),
        "id_expression": extract("IdExpression"),
        "id_function": extract("IdFunction"),
        "id_location": extract("IdLocation"),
        "index_location": extract("IndexLocation"),
        "sql_child_sub": extract("SqlChildSub"),
        "sql_id_expression": extract("SqlIdExpression"),
        "sql_row_id_name": extract("SqlRowIdName"),
        "sql_row_id_property": extract("SqlRowIdProperty"),
        "stream_location": extract("StreamLocation"),
        "version_location": extract("VersionLocation"),
        "data": data_items,
        "properties": properties,
        "sql_maps": sql_maps,
    }
    return {key: value for key, value in storage.items() if value != "" and value != [] and value is not None}


def extract_from(source: str, tag: str) -> str:
    found = re.search(rf"<{tag}>(.*?)</{tag}>", source, re.DOTALL)
    return found.group(1).strip() if found else ""


def _parse_storage_named_sections(source: str, tag: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for match in re.finditer(rf'<{tag} name="([^"]+)">(.*?)</{tag}>', source, re.DOTALL):
        name, body = match.groups()
        item: dict[str, Any] = {"name": name}
        for child_tag, value in re.findall(r"<([A-Za-z0-9_]+)>(.*?)</\1>", body, re.DOTALL):
            normalized = _tag_to_key(child_tag)
            item[normalized] = value.strip()
        items.append(item)
    return items


def _tag_to_key(tag: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", tag).lower()


def _key_to_tag(key: str) -> str:
    return "".join(part.capitalize() for part in str(key).split("_"))


def match_classnames(classnames: list[str], pattern: str) -> list[str]:
    return [name for name in classnames if fnmatch.fnmatch(name, pattern)]
