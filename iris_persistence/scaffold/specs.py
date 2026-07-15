from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelRenderSpec:
    class_info: Any
    properties: list[Any]
    parameters: list[Any]
    indexes: list[Any]
    storage: Any | None

    @property
    def storage_data(self) -> list[Any]:
        return list(self.storage.data) if self.storage else []

    @property
    def storage_indices(self) -> list[Any]:
        return list(self.storage.indices) if self.storage else []

    @property
    def storage_properties(self) -> list[Any]:
        return list(self.storage.properties) if self.storage else []

    @property
    def storage_sql_maps(self) -> list[Any]:
        return list(self.storage.sql_maps) if self.storage else []


@dataclass(frozen=True)
class RenderContext:
    mode: str
    python_class_names: dict[str, str]
    module_names: dict[str, str]


@dataclass(frozen=True)
class ScaffoldBuildContext:
    reader: Any
    runtime: Any
    result: Any
    extract_meta: bool
    storage: str
    best_effort: bool
