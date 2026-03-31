"""
Lockfile helpers for canonical schema snapshots.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import SchemaCatalog

_LOCKFILE_SUFFIX = ".iris.lock.json"
_LOCKFILE_VERSION = 2


def _normalize_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize_for_json(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_for_json(item) for item in value]
    return value


def compute_hash(value: Any) -> str:
    normalized = _normalize_for_json(value)
    encoded = json.dumps(
        normalized,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def timestamp_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def lockfile_path_for_module(module_path: str | Path) -> Path:
    path = Path(module_path)
    return path.with_name(f"{path.stem}{_LOCKFILE_SUFFIX}")


@dataclass(frozen=True)
class IRISLockfile:
    schema: SchemaCatalog
    schema_hash: str
    generated_at: str
    source: dict[str, Any]
    version: int = _LOCKFILE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "schema": self.schema.to_dict(),
            "schema_hash": self.schema_hash,
            "generated_at": self.generated_at,
            "source": _normalize_for_json(self.source),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "IRISLockfile":
        schema = SchemaCatalog.from_dict(dict(payload.get("schema", {})))
        schema_hash = str(payload.get("schema_hash", "")) or compute_hash(schema.to_dict())
        return cls(
            schema=schema,
            schema_hash=schema_hash,
            generated_at=str(payload.get("generated_at", "")),
            source={str(key): value for key, value in dict(payload.get("source", {})).items()},
            version=int(payload.get("version", _LOCKFILE_VERSION)),
        )


def build_lockfile(
    schema: SchemaCatalog,
    *,
    source: dict[str, Any],
) -> IRISLockfile:
    payload = schema.to_dict()
    return IRISLockfile(
        schema=schema,
        schema_hash=compute_hash(payload),
        generated_at=timestamp_utc(),
        source=source,
    )


def load_lockfile(path: str | Path) -> IRISLockfile:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return IRISLockfile.from_dict(payload)


def write_lockfile(path: str | Path, lockfile: IRISLockfile) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(lockfile.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path
