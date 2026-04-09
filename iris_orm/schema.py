from __future__ import annotations

import copy
import datetime as datetime_module
import fnmatch
import json
from dataclasses import dataclass, field as dataclass_field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .storage import StorageDefinition

_IRIS_EPOCH = datetime_module.date(1840, 12, 31)

PYTHON_TO_IRIS: dict[type, str] = {
    str: "%String",
    int: "%Integer",
    float: "%Float",
    bool: "%Boolean",
    bytes: "%Stream.GlobalBinary",
    dict: "%DynamicObject",
    list: "%DynamicArray",
    datetime_module.date: "%Date",
    datetime_module.time: "%Time",
    datetime_module.datetime: "%TimeStamp",
    Decimal: "%Decimal",
}

IRIS_TO_PYTHON: dict[str, type] = {
    "%String": str,
    "%Integer": int,
    "%SmallInt": int,
    "%BigInt": int,
    "%Float": float,
    "%Double": float,
    "%Numeric": float,
    "%Decimal": Decimal,
    "%Boolean": bool,
    "%Date": datetime_module.date,
    "%Time": datetime_module.time,
    "%TimeStamp": datetime_module.datetime,
    "%Stream.GlobalBinary": bytes,
    "%Stream.GlobalCharacter": str,
    "%DynamicObject": dict,
    "%DynamicArray": list,
}

SUPPORTED_PROPERTY_PARAMETERS: tuple[str, ...] = (
    "VALUELIST",
    "DISPLAYLIST",
    "SCALE",
    "PRECISION",
    "MINVAL",
    "MAXVAL",
    "TRUNCATE",
    "COLLATION",
)


@dataclass(frozen=True)
class SchemaProperty:
    name: str
    iris_type: str
    required: bool = False
    default: str = ""
    maxlen: int | None = None
    description: str = ""
    parameters: dict[str, str] = dataclass_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "iris_type": self.iris_type,
            "required": self.required,
            "default": self.default,
            "maxlen": self.maxlen,
            "description": self.description,
            "parameters": dict(sorted(self.parameters.items())),
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
            parameters={str(k): str(v) for k, v in dict(payload.get("parameters", {})).items()},
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
    origin = getattr(annotation, "__origin__", None)
    if origin in PYTHON_TO_IRIS:
        return PYTHON_TO_IRIS[origin]
    if origin is None and annotation in PYTHON_TO_IRIS:
        return PYTHON_TO_IRIS[annotation]
    return "%String"


def iris_type_to_python(iris_type: str) -> type:
    return IRIS_TO_PYTHON.get(iris_type, str)


def coerce_to_iris_logical(value: Any, iris_type: str) -> Any:
    if value is None:
        return None
    if is_dynamic_type(iris_type):
        return serialize_dynamic_json(value)
    if is_stream_type(iris_type):
        if is_binary_stream_type(iris_type):
            if isinstance(value, bytearray):
                return bytes(value)
            if isinstance(value, memoryview):
                return value.tobytes()
        return value
    if iris_type == "%Boolean":
        if isinstance(value, str):
            return 1 if value.strip().lower() in {"1", "true"} else 0
        return 1 if bool(value) else 0
    if iris_type in {"%Integer", "%SmallInt", "%BigInt"}:
        return int(value)
    if iris_type in {"%Float", "%Double", "%Numeric"}:
        return float(value)
    if iris_type == "%Decimal":
        return _decimal_to_string(value)
    if iris_type == "%Date":
        return _date_to_logical(value)
    if iris_type == "%Time":
        return _time_to_logical(value)
    if iris_type == "%TimeStamp":
        return _timestamp_to_logical(value)
    return value


def coerce_to_python(value: Any, iris_type: str) -> Any:
    if value is None:
        return None
    if value == "":
        if iris_type in {"%String", "%Stream.GlobalCharacter"}:
            return ""
        return None
    if is_dynamic_type(iris_type):
        return read_dynamic_value(value)
    if is_stream_type(iris_type):
        return read_stream_value(value, iris_type)
    if iris_type == "%Boolean":
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true"}
        return bool(value)
    if iris_type in {"%Integer", "%SmallInt", "%BigInt"}:
        return int(value)
    if iris_type in {"%Float", "%Double", "%Numeric"}:
        return float(value)
    if iris_type == "%Decimal":
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    if iris_type == "%Date":
        if isinstance(value, datetime_module.datetime):
            return value.date()
        if isinstance(value, datetime_module.date):
            return value
        return _parse_date_logical(value)
    if iris_type == "%Time":
        if isinstance(value, datetime_module.datetime):
            return value.timetz().replace(tzinfo=None)
        if isinstance(value, datetime_module.time):
            return value
        return _parse_time_logical(value)
    if iris_type == "%TimeStamp":
        if isinstance(value, datetime_module.datetime):
            return value
        return _parse_timestamp_logical(value)
    return value


def default_literal(value: Any, iris_type: str) -> str:
    if value is None or value == "":
        return ""
    if is_dynamic_type(iris_type):
        escaped = serialize_dynamic_json(value).replace('"', '""')
        return f'"{escaped}"'
    if value == [] or value == {}:
        return ""
    if iris_type in {
        "%Boolean",
        "%Integer",
        "%SmallInt",
        "%BigInt",
        "%Float",
        "%Double",
        "%Numeric",
        "%Decimal",
        "%Date",
        "%Time",
        "%TimeStamp",
    }:
        logical = coerce_to_iris_logical(value, iris_type)
        return "" if logical is None else str(logical)
    if isinstance(value, str):
        escaped = value.replace('"', '""')
        return f'"{escaped}"'
    return str(value)


def python_default_source(default: str, iris_type: str) -> str | None:
    if default == "":
        return None
    if is_dynamic_type(iris_type):
        return repr(coerce_to_python(default, iris_type))
    if iris_type == "%Boolean":
        return "True" if default.strip().lower() in {"1", "true"} else "False"
    if iris_type in {"%Integer", "%SmallInt", "%BigInt"}:
        return str(int(default))
    if iris_type in {"%Float", "%Double", "%Numeric"}:
        return repr(float(default))
    if iris_type == "%Decimal":
        return f"Decimal({default!r})"
    if iris_type == "%Date":
        value = coerce_to_python(default, iris_type)
        return f"date({value.year}, {value.month}, {value.day})"
    if iris_type == "%Time":
        value = coerce_to_python(default, iris_type)
        return (
            f"time({value.hour}, {value.minute}, {value.second}, {value.microsecond})"
            if value.microsecond
            else f"time({value.hour}, {value.minute}, {value.second})"
        )
    if iris_type == "%TimeStamp":
        value = coerce_to_python(default, iris_type)
        return (
            f"datetime({value.year}, {value.month}, {value.day}, {value.hour}, {value.minute}, {value.second}, {value.microsecond})"
            if value.microsecond
            else f"datetime({value.year}, {value.month}, {value.day}, {value.hour}, {value.minute}, {value.second})"
        )
    if len(default) >= 2 and default.startswith('"') and default.endswith('"'):
        return repr(default[1:-1].replace('""', '"'))
    return repr(default)


def python_default_value(default: str, iris_type: str) -> Any:
    if default == "":
        return None
    if is_dynamic_type(iris_type):
        return coerce_to_python(default, iris_type)
    if iris_type in {
        "%Boolean",
        "%Integer",
        "%SmallInt",
        "%BigInt",
        "%Float",
        "%Double",
        "%Numeric",
        "%Decimal",
        "%Date",
        "%Time",
        "%TimeStamp",
    }:
        return coerce_to_python(default, iris_type)
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
                    parameters={str(k): str(v) for k, v in dict(getattr(field_def, "parameters", {})).items()},
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
            source={"kind": "python", "mode": getattr(model_class, "_iris_mode", "extend")},
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
        source={"kind": "python", "mode": "extend"},
    )


def _decimal_to_string(value: Any) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return format(Decimal(str(value)), "f")


def is_stream_type(iris_type: str) -> bool:
    return str(iris_type or "").startswith("%Stream.")


def is_binary_stream_type(iris_type: str) -> bool:
    return "binary" in str(iris_type or "").lower()


def is_list_of_datatypes(iris_type: str) -> bool:
    return str(iris_type or "").startswith("%ListOfDataTypes")


def is_array_of_datatypes(iris_type: str) -> bool:
    return str(iris_type or "").startswith("%ArrayOfDataTypes")


def is_dynamic_object_type(iris_type: str) -> bool:
    return str(iris_type or "") == "%DynamicObject"


def is_dynamic_array_type(iris_type: str) -> bool:
    return str(iris_type or "") == "%DynamicArray"


def is_dynamic_type(iris_type: str) -> bool:
    return is_dynamic_object_type(iris_type) or is_dynamic_array_type(iris_type)


def serialize_dynamic_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def read_dynamic_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8")
    if isinstance(value, str):
        text = value
        if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
            text = text[1:-1].replace('""', '"')
        return json.loads(text)

    for reader_name in ("_ToJSON", "ToJSON"):
        reader = getattr(value, reader_name, None)
        if callable(reader):
            return json.loads(reader())

    invoke_string = getattr(value, "invokeString", None)
    if callable(invoke_string):
        return json.loads(invoke_string("%ToJSON"))

    invoke = getattr(value, "invoke", None)
    if callable(invoke):
        return json.loads(invoke("%ToJSON"))

    return copy.deepcopy(value)


def read_stream_value(value: Any, iris_type: str) -> str | bytes | None | Any:
    if value is None:
        return None
    if is_binary_stream_type(iris_type):
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value)
    elif isinstance(value, str):
        return value

    for reader_name in ("ReadAll",):
        reader = getattr(value, reader_name, None)
        if callable(reader):
            try:
                payload = reader()
                return _normalize_stream_payload(payload, iris_type)
            except Exception:
                pass

    invoke = getattr(value, "invoke", None)
    if callable(invoke):
        try:
            payload = invoke("ReadAll")
            return _normalize_stream_payload(payload, iris_type)
        except Exception:
            pass

    invoke_string = getattr(value, "invokeString", None)
    if callable(invoke_string):
        try:
            payload = invoke_string("ReadAll")
            return _normalize_stream_payload(payload, iris_type)
        except Exception:
            pass

    read_sql = getattr(value, "ReadSQL", None)
    if callable(read_sql):
        try:
            payload = read_sql()
            return _normalize_stream_payload(payload, iris_type)
        except Exception:
            pass

    if callable(invoke):
        try:
            payload = invoke("ReadSQL")
            return _normalize_stream_payload(payload, iris_type)
        except Exception:
            pass

    if callable(invoke_string):
        try:
            payload = invoke_string("ReadSQL")
            return _normalize_stream_payload(payload, iris_type)
        except Exception:
            pass

    read = getattr(value, "Read", None)
    if callable(read):
        size = None
        size_get = getattr(value, "SizeGet", None)
        if callable(size_get):
            try:
                size = int(size_get())
            except Exception:
                size = None
        if size is None:
            raw_size = getattr(value, "Size", None)
            if raw_size not in {None, ""}:
                try:
                    size = int(raw_size)
                except Exception:
                    size = None
        if size is not None:
            try:
                payload = read(size)
                return _normalize_stream_payload(payload, iris_type)
            except Exception:
                pass
        chunks: list[Any] = []
        while True:
            try:
                payload = read()
            except Exception:
                break
            if payload in {"", b"", None}:
                break
            chunks.append(payload)
        if chunks:
            if is_binary_stream_type(iris_type):
                return b"".join(
                    item if isinstance(item, bytes) else _normalize_stream_payload(item, iris_type)
                    for item in chunks
                )
            return "".join(str(item) for item in chunks)

    return _normalize_stream_payload(value, iris_type)


def _normalize_stream_payload(value: Any, iris_type: str) -> str | bytes | Any:
    if is_binary_stream_type(iris_type):
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value)
        if isinstance(value, str):
            return value.encode("latin-1")
    else:
        if isinstance(value, bytes):
            return value.decode("utf-8")
    return value


def _date_to_logical(value: Any) -> int:
    if isinstance(value, datetime_module.datetime):
        value = value.date()
    if isinstance(value, datetime_module.date):
        return (value - _IRIS_EPOCH).days
    if isinstance(value, str):
        return _date_to_logical(_parse_date_logical(value))
    return int(value)


def _time_to_logical(value: Any) -> int | str:
    if isinstance(value, datetime_module.datetime):
        value = value.timetz().replace(tzinfo=None)
    if isinstance(value, datetime_module.time):
        _reject_timezone_aware_time(value)
        total_seconds = value.hour * 3600 + value.minute * 60 + value.second
        if value.microsecond:
            return f"{total_seconds}.{value.microsecond:06d}".rstrip("0").rstrip(".")
        return total_seconds
    if isinstance(value, str):
        return _time_to_logical(_parse_time_logical(value))
    return int(value) if float(value).is_integer() else str(value)


def _timestamp_to_logical(value: Any) -> str:
    if isinstance(value, datetime_module.date) and not isinstance(value, datetime_module.datetime):
        value = datetime_module.datetime.combine(value, datetime_module.time())
    if isinstance(value, datetime_module.datetime):
        if value.tzinfo is not None and value.utcoffset() is not None:
            raise ValueError("Timezone-aware datetime values are not supported for %TimeStamp fields")
        text = value.strftime("%Y-%m-%d %H:%M:%S")
        if value.microsecond:
            text += f".{value.microsecond:06d}".rstrip("0")
        return text
    if isinstance(value, str):
        return _timestamp_to_logical(_parse_timestamp_logical(value))
    return str(value)


def _parse_date_logical(value: Any) -> datetime_module.date:
    text = str(value).strip().strip('"')
    if _looks_like_int(text):
        return _IRIS_EPOCH + datetime_module.timedelta(days=int(text))
    if " " in text:
        text = text.split(" ", 1)[0]
    return datetime_module.date.fromisoformat(text)


def _parse_time_logical(value: Any) -> datetime_module.time:
    text = str(value).strip().strip('"')
    if ":" in text:
        if "." in text:
            return datetime_module.time.fromisoformat(text)
        if text.count(":") == 1:
            text = f"{text}:00"
        return datetime_module.time.fromisoformat(text)
    seconds_decimal = Decimal(text)
    whole_seconds = int(seconds_decimal)
    microseconds = int((seconds_decimal - whole_seconds) * Decimal("1000000"))
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return datetime_module.time(hour=hours, minute=minutes, second=seconds, microsecond=microseconds)


def _parse_timestamp_logical(value: Any) -> datetime_module.datetime:
    text = str(value).strip().strip('"')
    if "T" in text:
        text = text.replace("T", " ", 1)
    if len(text) == 10:
        text = f"{text} 00:00:00"
    return datetime_module.datetime.fromisoformat(text)


def _reject_timezone_aware_time(value: datetime_module.time) -> None:
    if value.tzinfo is not None and value.utcoffset() is not None:
        raise ValueError("Timezone-aware time values are not supported for %Time fields")


def _looks_like_int(value: str) -> bool:
    if not value:
        return False
    if value[0] in {"-", "+"}:
        return value[1:].isdigit()
    return value.isdigit()
