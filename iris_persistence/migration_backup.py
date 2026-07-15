from __future__ import annotations

import datetime as _datetime
import getpass
import json
import os
import socket
from pathlib import Path
from typing import Any, Sequence

from iris_persistence.models import Model
from iris_persistence.schema import _collect_live_schema_state


def _utc_now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


def _backup_id(plan: Any) -> str:
    timestamp = _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{plan.plan_fingerprint[:12]}"


def _backup_root(backup_dir: str | Path, plan: Any) -> Path:
    return Path(backup_dir) / _backup_id(plan)


def _write_apply_backup(
    *,
    runtime: Any,
    plan: Any,
    models: Sequence[type[Model]],
    backup_dir: str | Path,
) -> Path:
    root = _backup_root(backup_dir, plan)
    root.mkdir(parents=True, exist_ok=False)

    live_states = [
        _collect_live_schema_state(runtime, model._classname)
        for model in sorted(models, key=lambda item: item._classname)
    ]
    class_states = [
        {
            "classname": state.classname,
            "existed": bool(state.superclasses),
        }
        for state in live_states
    ]

    plan.save(root / "plan.json")
    (root / "schema_states.json").write_text(
        json.dumps(
            [state.to_dict() for state in live_states],
            sort_keys=True,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    metadata = {
        "backup_id": root.name,
        "created_at": _utc_now(),
        "user": getpass.getuser(),
        "host": socket.gethostname(),
        "cwd": os.getcwd(),
        "target_revision": plan.target_revision,
        "plan_fingerprint": plan.plan_fingerprint,
        "live_schema_fingerprint": plan.live_schema_fingerprint,
        "target_schema_fingerprint": plan.target_schema_fingerprint,
        "class_states": class_states,
    }
    (root / "metadata.json").write_text(
        json.dumps(metadata, sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return root
