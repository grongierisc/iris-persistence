from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, ClassVar


def _string(value: Any) -> str:
    return "" if value in {None, ""} else str(value)


def _unknown_storage_keys(payload: dict[str, Any], valid_keys: set[str]) -> list[str]:
    return sorted(set(payload) - valid_keys)


def validate_storage_definition_dict(
    payload: "StorageDefinition | dict[str, Any] | None",
    *,
    source_name: str = "_iris_storage",
) -> None:
    if payload is None or isinstance(payload, StorageDefinition):
        return
    unexpected = _unknown_storage_keys(payload, _STORAGE_TOP_LEVEL_FIELDS)
    if unexpected:
        keys = ", ".join(unexpected)
        raise TypeError(f"Unknown storage keys for {source_name}: {keys}")


@dataclass(frozen=True)
class StorageData:
    name: str
    structure: str = ""
    values: dict[str, str] = dataclass_field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StorageData":
        raw_values = payload.get("values", {})
        values: dict[str, str]
        if isinstance(raw_values, dict):
            values = {str(key): _string(value) for key, value in raw_values.items()}
        else:
            values = {
                str(item.get("name", "")): _string(item.get("value", ""))
                for item in raw_values
                if str(item.get("name", ""))
            }
        return cls(
            name=str(payload.get("name", "") or ""),
            structure=_string(payload.get("structure", "")),
            values=values,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name}
        if self.structure:
            payload["structure"] = self.structure
        if self.values:
            payload["values"] = [{"name": name, "value": value} for name, value in sorted(self.values.items())]
        return payload


@dataclass(frozen=True)
class StorageProperty:
    name: str
    average_field_size: str = ""
    bias_queries_as_outlier: str = ""
    child_block_count: str = ""
    child_extent_size: str = ""
    histogram: str = ""
    outlier_selectivity: str = ""
    selectivity: str = ""
    stream_location: str = ""

    _FIELD_NAMES: ClassVar[tuple[str, ...]] = (
        "average_field_size",
        "bias_queries_as_outlier",
        "child_block_count",
        "child_extent_size",
        "histogram",
        "outlier_selectivity",
        "selectivity",
        "stream_location",
    )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StorageProperty":
        data = {"name": str(payload.get("name", "") or "")}
        for name in cls._FIELD_NAMES:
            data[name] = _string(payload.get(name, ""))
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        payload = {"name": self.name}
        for name in self._FIELD_NAMES:
            value = getattr(self, name)
            if value:
                payload[name] = value
        return payload


@dataclass(frozen=True)
class StorageSQLMap:
    name: str
    block_count: str = ""
    condition: str = ""
    condition_fields: str = ""
    conditional_with_host_vars: str = ""
    global_: str = ""
    population_pct: str = ""
    population_type: str = ""
    row_reference: str = ""
    structure: str = ""
    type: str = ""

    _FIELD_NAMES: ClassVar[tuple[str, ...]] = (
        "block_count",
        "condition",
        "condition_fields",
        "conditional_with_host_vars",
        "global_",
        "population_pct",
        "population_type",
        "row_reference",
        "structure",
        "type",
    )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StorageSQLMap":
        data = {"name": str(payload.get("name", "") or "")}
        for name in cls._FIELD_NAMES:
            source_name = "global" if name == "global_" else name
            data[name] = _string(payload.get(source_name, ""))
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        payload = {"name": self.name}
        for name in self._FIELD_NAMES:
            value = getattr(self, name)
            if not value:
                continue
            payload["global" if name == "global_" else name] = value
        return payload


@dataclass(frozen=True)
class StorageDefinition:
    name: str = "Default"
    counter_location: str = ""
    data_location: str = ""
    default_data: str = ""
    description: str = ""
    extent_location: str = ""
    extent_size: str = ""
    id_expression: str = ""
    id_function: str = ""
    id_location: str = ""
    index_location: str = ""
    sql_child_sub: str = ""
    sql_id_expression: str = ""
    sql_row_id_name: str = ""
    sql_row_id_property: str = ""
    stream_location: str = ""
    type: str = ""
    version_location: str = ""
    data: tuple[StorageData, ...] = ()
    properties: tuple[StorageProperty, ...] = ()
    sql_maps: tuple[StorageSQLMap, ...] = ()

    _SCALAR_FIELDS: ClassVar[tuple[str, ...]] = (
        "name",
        "counter_location",
        "data_location",
        "default_data",
        "description",
        "extent_location",
        "extent_size",
        "id_expression",
        "id_function",
        "id_location",
        "index_location",
        "sql_child_sub",
        "sql_id_expression",
        "sql_row_id_name",
        "sql_row_id_property",
        "stream_location",
        "type",
        "version_location",
    )

    @classmethod
    def from_dict(cls, payload: "StorageDefinition | dict[str, Any] | None") -> "StorageDefinition | None":
        if payload is None:
            return None
        if isinstance(payload, StorageDefinition):
            return payload
        validate_storage_definition_dict(payload)
        scalars = {name: _string(payload.get(name, "Default" if name == "name" else "")) for name in cls._SCALAR_FIELDS}
        if not scalars["name"]:
            scalars["name"] = "Default"
        return cls(
            **scalars,
            data=tuple(StorageData.from_dict(item) for item in payload.get("data", []) or []),
            properties=tuple(StorageProperty.from_dict(item) for item in payload.get("properties", []) or []),
            sql_maps=tuple(StorageSQLMap.from_dict(item) for item in payload.get("sql_maps", []) or []),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name}
        for name in self._SCALAR_FIELDS:
            if name == "name":
                continue
            value = getattr(self, name)
            if value:
                payload[name] = value
        if self.data:
            payload["data"] = [item.to_dict() for item in self.data]
        if self.properties:
            payload["properties"] = [item.to_dict() for item in self.properties]
        if self.sql_maps:
            payload["sql_maps"] = [item.to_dict() for item in self.sql_maps]
        return payload


_STORAGE_TOP_LEVEL_FIELDS = set(StorageDefinition._SCALAR_FIELDS) | {"data", "properties", "sql_maps"}
