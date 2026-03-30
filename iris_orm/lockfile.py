"""
Lockfile helpers for scaffolded IRIS ORM models.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def compute_hash(value: str) -> str:
    """Return a stable SHA256 hash for *value*."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_indexes(indexes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return indexes sorted by name for stable comparisons/serialization."""
    return sorted(indexes, key=lambda item: item.get("name", ""))


def lockfile_path_for_class(state_root: str | Path, classname: str) -> Path:
    """Return the canonical lockfile path for *classname*."""
    return Path(state_root) / f"{classname}.json"


def timestamp_utc() -> str:
    """Return the current UTC timestamp as an ISO8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class IRISLockfile:
    classname: str
    super: str
    storage_mode: str
    storage_definition: str
    storage_hash: str
    class_parameters: dict[str, str]
    indexes: list[dict[str, Any]]
    source: dict[str, Any]
    scaffold_style: str
    generated_at: str
    generated_region_hash: str = ""
    unsupported_features: list[dict[str, str]] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "classname": self.classname,
            "super": self.super,
            "storage_mode": self.storage_mode,
            "storage_definition": self.storage_definition,
            "storage_hash": self.storage_hash,
            "class_parameters": dict(sorted(self.class_parameters.items())),
            "indexes": normalize_indexes(self.indexes),
            "source": self.source,
            "scaffold_style": self.scaffold_style,
            "generated_at": self.generated_at,
            "generated_region_hash": self.generated_region_hash,
        }
        if self.unsupported_features is not None:
            payload["unsupported_features"] = self.unsupported_features
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "IRISLockfile":
        scaffold_style = str(payload.get("scaffold_style", "typed")).strip().lower()
        if scaffold_style not in {"existing", "typed"}:
            raise ValueError(f"Unsupported scaffold style: {scaffold_style!r}")
        return cls(
            classname=str(payload["classname"]),
            super=str(payload.get("super", "%Persistent")),
            storage_mode=str(payload.get("storage_mode", "preserve")),
            storage_definition=str(payload.get("storage_definition", "")),
            storage_hash=str(payload.get("storage_hash", compute_hash(str(payload.get("storage_definition", ""))))),
            class_parameters={
                str(key): str(value) for key, value in dict(payload.get("class_parameters", {})).items()
            },
            indexes=[
                {str(key): value for key, value in dict(item).items()}
                for item in list(payload.get("indexes", []))
            ],
            source=dict(payload.get("source", {})),
            scaffold_style=scaffold_style,
            generated_at=str(payload.get("generated_at", "")),
            generated_region_hash=str(payload.get("generated_region_hash", "")),
            unsupported_features=[
                {str(key): str(value) for key, value in dict(item).items()}
                for item in list(payload.get("unsupported_features", []))
            ] or None,
        )


def load_lockfile(path: str | Path) -> IRISLockfile:
    """Load a scaffold lockfile from disk."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return IRISLockfile.from_dict(payload)


def write_lockfile(path: str | Path, lockfile: IRISLockfile) -> Path:
    """Write *lockfile* to *path*."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(lockfile.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path
