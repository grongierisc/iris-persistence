from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from difflib import unified_diff
from typing import Any


@dataclass(frozen=True)
class SchemaOperation:
    classname: str
    op_type: str
    path: str
    before: Any = None
    after: Any = None
    safety: str = "safe"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SchemaState:
    classname: str
    superclasses: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    properties: dict[str, dict[str, Any]] = field(default_factory=dict)
    indexes: dict[str, dict[str, Any]] = field(default_factory=dict)
    storage: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, state: dict[str, Any]) -> "SchemaState":
        return cls(
            classname=str(state["classname"]),
            superclasses=state.get("super"),
            metadata=deepcopy(state.get("metadata", {})),
            parameters=deepcopy(state.get("parameters", {})),
            properties=deepcopy(state.get("properties", {})),
            indexes=deepcopy(state.get("indexes", {})),
            storage=deepcopy(state.get("storage")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "classname": self.classname,
            "super": self.superclasses,
            "metadata": deepcopy(self.metadata),
            "parameters": deepcopy(self.parameters),
            "properties": deepcopy(self.properties),
            "indexes": deepcopy(self.indexes),
            "storage": deepcopy(self.storage),
        }

    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def __getitem__(self, key: str) -> Any:
        if key == "super":
            return self.superclasses
        return getattr(self, key)


@dataclass(frozen=True)
class SchemaDiff:
    classname: str
    before: tuple[str, ...]
    after: tuple[str, ...]
    before_state: SchemaState | None = None
    after_state: SchemaState | None = None
    operations: tuple[SchemaOperation, ...] = ()

    @property
    def has_changes(self) -> bool:
        return self.before != self.after

    def to_unified_diff(self) -> str:
        if not self.has_changes:
            return ""
        return "\n".join(
            unified_diff(
                self.before,
                self.after,
                fromfile=f"{self.classname}:live",
                tofile=f"{self.classname}:planned",
                lineterm="",
            )
        )

    def __str__(self) -> str:
        return self.to_unified_diff() or "No schema changes."
