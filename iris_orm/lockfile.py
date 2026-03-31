"""
Lockfile helpers for scaffolded and declared IRIS ORM models.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCAFFOLD_STYLES = {"existing", "typed"}
_LOCKFILE_SUFFIX = ".iris.lock.json"


def _normalize_for_json(value: Any) -> Any:
    """Return a recursively normalized value suitable for canonical JSON hashing."""
    if isinstance(value, dict):
        return {
            str(key): _normalize_for_json(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list):
        return [_normalize_for_json(item) for item in value]
    return value


def compute_hash(value: Any) -> str:
    """Return a stable SHA256 hash for *value*."""
    if isinstance(value, str):
        encoded = value.encode("utf-8")
    else:
        encoded = json.dumps(
            _normalize_for_json(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_indexes(indexes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return indexes sorted by name for stable comparisons/serialization."""
    return sorted(indexes, key=lambda item: item.get("name", ""))


def lockfile_path_for_class(state_root: str | Path, classname: str) -> Path:
    """Return a lockfile path rooted under *state_root* for *classname*."""
    return Path(state_root) / f"{classname}.json"


def lockfile_path_for_module(module_path: str | Path) -> Path:
    """Return the default adjacent lockfile path for a Python module."""
    path = Path(module_path)
    return path.with_name(f"{path.stem}{_LOCKFILE_SUFFIX}")

def timestamp_utc() -> str:
    """Return the current UTC timestamp as an ISO8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_scaffold_style(style: str) -> str:
    value = str(style or "typed").strip().lower()
    if value not in _SCAFFOLD_STYLES:
        raise ValueError(f"Unsupported scaffold style: {value!r}")
    return value


def _resolve_storage_path(lockfile_path: Path, storage_path: str) -> Path:
    path = Path(storage_path)
    if path.is_absolute():
        return path
    return (lockfile_path.parent / path).resolve()

@dataclass
class IRISLockfile:
    classname: str
    super: str
    storage_mode: str
    storage_hash: str
    class_parameters: dict[str, str]
    indexes: list[dict[str, Any]]
    source: dict[str, Any]
    scaffold_style: str
    generated_at: str
    storage_path: str = ""
    generated_region_hash: str = ""
    unsupported_features: list[dict[str, str]] | None = None
    storage_definition: str = ""
    storage: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "classname": self.classname,
            "super": self.super,
            "storage_mode": self.storage_mode,
            "storage_hash": self.storage_hash,
            "class_parameters": dict(sorted(self.class_parameters.items())),
            "indexes": normalize_indexes(self.indexes),
            "source": self.source,
            "scaffold_style": _validate_scaffold_style(self.scaffold_style),
            "generated_at": self.generated_at,
            "generated_region_hash": self.generated_region_hash,
        }
        if self.storage_path:
            payload["storage_path"] = self.storage_path
        if self.storage is not None:
            payload["storage"] = _normalize_for_json(self.storage)
        if self.unsupported_features is not None:
            payload["unsupported_features"] = self.unsupported_features
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any], *, lockfile_path: str | Path | None = None) -> "IRISLockfile":
        resolved_lockfile_path = Path(lockfile_path).resolve() if lockfile_path is not None else None
        storage_rel = str(payload.get("storage_path", ""))
        storage = payload.get("storage")
        if storage is not None:
            storage = _normalize_for_json(storage)
        storage_definition = ""
        if storage is not None:
            from .introspection import render_storage_definition  # noqa: PLC0415

            storage_definition = render_storage_definition(storage)
        elif "storage_definition" in payload:
            storage_definition = str(payload.get("storage_definition", "") or "")
        elif resolved_lockfile_path is not None and storage_rel:
            storage_file = _resolve_storage_path(resolved_lockfile_path, storage_rel)
            if storage_file.exists():
                storage_definition = storage_file.read_text(encoding="utf-8")
        if storage is None and storage_definition:
            from .introspection import parse_storage_definition  # noqa: PLC0415

            storage = parse_storage_definition(storage_definition)
            if storage is not None:
                storage = _normalize_for_json(storage)
                from .introspection import render_storage_definition  # noqa: PLC0415

                storage_definition = render_storage_definition(storage)

        storage_hash = str(payload.get("storage_hash", ""))
        if not storage_hash:
            storage_hash = compute_hash(storage if storage is not None else storage_definition)

        return cls(
            classname=str(payload["classname"]),
            super=str(payload.get("super", "%Persistent")),
            storage_mode=str(payload.get("storage_mode", "preserve")),
            storage_path=storage_rel,
            storage_hash=storage_hash,
            class_parameters={
                str(key): str(value) for key, value in dict(payload.get("class_parameters", {})).items()
            },
            indexes=[
                {str(key): value for key, value in dict(item).items()}
                for item in list(payload.get("indexes", []))
            ],
            source=dict(payload.get("source", {})),
            scaffold_style=_validate_scaffold_style(str(payload.get("scaffold_style", "typed"))),
            generated_at=str(payload.get("generated_at", "")),
            generated_region_hash=str(payload.get("generated_region_hash", "")),
            unsupported_features=[
                {str(key): str(value) for key, value in dict(item).items()}
                for item in list(payload.get("unsupported_features", []))
            ] or None,
            storage_definition=storage_definition,
            storage=storage,
        )


def load_lockfile(path: str | Path) -> IRISLockfile:
    """Load a lockfile from disk."""
    lockfile_path = Path(path).resolve()
    payload = json.loads(lockfile_path.read_text(encoding="utf-8"))
    return IRISLockfile.from_dict(payload, lockfile_path=lockfile_path)


def write_lockfile(path: str | Path, lockfile: IRISLockfile) -> Path:
    """Write lock metadata with canonical structured storage embedded in JSON."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    from .introspection import parse_storage_definition, render_storage_definition  # noqa: PLC0415

    if lockfile.storage is None and lockfile.storage_definition:
        lockfile.storage = parse_storage_definition(lockfile.storage_definition)
    if lockfile.storage is not None:

        lockfile.storage = _normalize_for_json(lockfile.storage)
        lockfile.storage_definition = render_storage_definition(lockfile.storage)
        lockfile.storage_hash = compute_hash(lockfile.storage)
    else:
        lockfile.storage_hash = compute_hash(lockfile.storage_definition or "")
    lockfile.storage_path = ""

    output_path.write_text(
        json.dumps(lockfile.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path
