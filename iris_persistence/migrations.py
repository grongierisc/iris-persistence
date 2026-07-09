from __future__ import annotations

import datetime as _datetime
import getpass
import hashlib
import importlib
import json
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from iris_persistence.models import Model
from iris_persistence.runtime import get_runtime
from iris_persistence.schema import (
    SchemaOperation,
    SchemaState,
    _collect_live_schema_state,
    _run_with_schema_transaction,
    _sync_schema_model,
    _sync_schema_state,
    diff_schema,
)


class MigrationError(RuntimeError):
    pass


class UnsafeMigrationError(MigrationError):
    pass


class StaleMigrationPlanError(MigrationError):
    pass


class BackupRestoreError(MigrationError):
    pass


def _payload_from_fields(
    obj: Any,
    fields: tuple[str, ...],
    *,
    list_fields: tuple[str, ...] = (),
    operation_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    data = {name: getattr(obj, name) for name in fields}
    for name in list_fields:
        data[name] = list(data[name])
    for name in operation_fields:
        data[name] = [operation.to_dict() for operation in data[name]]
    return data


@dataclass(frozen=True)
class MigrationOperation:
    op_type: str
    classname: str = ""
    path: str = ""
    before: Any = None
    after: Any = None
    safety: str = "safe"
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_schema(cls, operation: SchemaOperation) -> "MigrationOperation":
        return cls(
            op_type=operation.op_type,
            classname=operation.classname,
            path=operation.path,
            before=operation.before,
            after=operation.after,
            safety=operation.safety,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MigrationOperation":
        return cls(
            op_type=str(data["op_type"]),
            classname=str(data.get("classname", "")),
            path=str(data.get("path", "")),
            before=data.get("before"),
            after=data.get("after"),
            safety=str(data.get("safety", "safe")),
            payload=dict(data.get("payload", {}) or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return _payload_from_fields(
            self,
            ("op_type", "classname", "path", "before", "after", "safety", "payload"),
        )


@dataclass(frozen=True)
class DriftReport:
    has_drift: bool
    diffs: tuple[str, ...]
    live_schema_fingerprint: str
    expected_schema_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return _payload_from_fields(
            self,
            ("has_drift", "diffs", "live_schema_fingerprint", "expected_schema_fingerprint"),
            list_fields=("diffs",),
        )


@dataclass(frozen=True)
class ApplyResult:
    status: str
    target_revision: str
    applied_operations: tuple[MigrationOperation, ...] = ()
    skipped_operations: tuple[MigrationOperation, ...] = ()
    backup_dir: str | None = None

    @property
    def applied(self) -> bool:
        return self.status == "applied"

    def to_dict(self) -> dict[str, Any]:
        return _payload_from_fields(
            self,
            (
                "status",
                "target_revision",
                "applied_operations",
                "skipped_operations",
                "backup_dir",
            ),
            operation_fields=("applied_operations", "skipped_operations"),
        )


@dataclass(frozen=True)
class VerifyResult:
    converged: bool
    live_schema_fingerprint: str
    target_schema_fingerprint: str
    diffs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _payload_from_fields(
            self,
            ("converged", "live_schema_fingerprint", "target_schema_fingerprint", "diffs"),
            list_fields=("diffs",),
        )


@dataclass(frozen=True)
class RollbackResult:
    status: str
    backup_dir: str
    restored_classes: tuple[str, ...] = ()
    deleted_classes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return _payload_from_fields(
            self,
            ("status", "backup_dir", "restored_classes", "deleted_classes"),
            list_fields=("restored_classes", "deleted_classes"),
        )


@dataclass(frozen=True)
class MigrationPlan:
    operations: tuple[MigrationOperation, ...]
    model_specs: tuple[str, ...]
    current_revision: str | None
    target_revision: str
    live_schema_fingerprint: str = ""
    target_schema_fingerprint: str = ""
    fail_on_drift: bool = True
    models: tuple[type[Model], ...] = field(default_factory=tuple, repr=False, compare=False)

    @property
    def plan_fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(include_fingerprint=False), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, Any]:
        data = {
            "operations": [operation.to_dict() for operation in self.operations],
            "model_specs": list(self.model_specs),
            "current_revision": self.current_revision,
            "target_revision": self.target_revision,
            "live_schema_fingerprint": self.live_schema_fingerprint,
            "target_schema_fingerprint": self.target_schema_fingerprint,
            "fail_on_drift": self.fail_on_drift,
        }
        if include_fingerprint:
            data["plan_fingerprint"] = self.plan_fingerprint
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=2, default=str)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json() + "\n", encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MigrationPlan":
        specs = tuple(str(item) for item in data.get("model_specs", ()))
        return cls(
            operations=tuple(
                MigrationOperation.from_dict(item) for item in data.get("operations", ())
            ),
            model_specs=specs,
            current_revision=data.get("current_revision"),
            target_revision=str(data["target_revision"]),
            live_schema_fingerprint=str(data.get("live_schema_fingerprint", "")),
            target_schema_fingerprint=str(data.get("target_schema_fingerprint", "")),
            fail_on_drift=bool(data.get("fail_on_drift", True)),
            models=tuple(_load_model_spec(spec) for spec in specs),
        )

    @classmethod
    def from_json(cls, payload: str) -> "MigrationPlan":
        return cls.from_dict(json.loads(payload))

    @classmethod
    def load(cls, path: str | Path) -> "MigrationPlan":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


def _model_spec(model_cls: type[Model]) -> str:
    return f"{model_cls.__module__}:{model_cls.__qualname__}"


def _load_model_spec(spec: str) -> type[Model]:
    module_name, _, qualname = spec.partition(":")
    if not module_name or not qualname:
        raise MigrationError(f"Invalid model spec {spec!r}; expected module:Class")
    obj: Any = importlib.import_module(module_name)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    if not isinstance(obj, type) or not issubclass(obj, Model):
        raise MigrationError(f"Model spec {spec!r} did not resolve to an iris_persistence.Model")
    return obj


def _states_fingerprint(states: Sequence[SchemaState]) -> str:
    payload = json.dumps(
        [state.to_dict() for state in sorted(states, key=lambda item: item.classname)],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat()


def _backup_id(plan: MigrationPlan) -> str:
    timestamp = _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{plan.plan_fingerprint[:12]}"


def _backup_root(backup_dir: str | Path, plan: MigrationPlan) -> Path:
    return Path(backup_dir) / _backup_id(plan)


def _call_status(runtime: Any, class_name: str, method_name: str, *args: Any) -> Any:
    status = runtime.call_classmethod(class_name, method_name, *args)
    if not runtime.is_ok(status):
        raise BackupRestoreError(runtime.format_status(status))
    return status


def _write_apply_backup(
    *,
    runtime: Any,
    plan: MigrationPlan,
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


def _resolve_models(models: Iterable[type[Model]] | None) -> tuple[type[Model], ...]:
    if models is None:
        return ()
    resolved = tuple(models)
    for model_cls in resolved:
        if not isinstance(model_cls, type) or not issubclass(model_cls, Model):
            raise TypeError("create_plan() expects iris_persistence.Model subclasses")
    return resolved


def create_plan(
    models: Iterable[type[Model]],
    target_revision: str | None = None,
    from_revision: str | None = None,
    fail_on_drift: bool = True,
) -> MigrationPlan:
    model_tuple = _resolve_models(models)
    diffs = [diff_schema(model_cls) for model_cls in model_tuple]
    operations = tuple(
        MigrationOperation.from_schema(operation)
        for diff in diffs
        for operation in diff.operations
    )
    live_states = tuple(diff.before_state for diff in diffs if diff.before_state is not None)
    target_states = tuple(diff.after_state for diff in diffs if diff.after_state is not None)
    live_fingerprint = _states_fingerprint(live_states)
    target_fingerprint = _states_fingerprint(target_states)
    resolved_target_revision = target_revision or f"schema-{target_fingerprint[:12]}"
    return MigrationPlan(
        operations=operations,
        model_specs=tuple(_model_spec(model_cls) for model_cls in model_tuple),
        current_revision=from_revision,
        target_revision=resolved_target_revision,
        live_schema_fingerprint=live_fingerprint,
        target_schema_fingerprint=target_fingerprint,
        fail_on_drift=fail_on_drift,
        models=model_tuple,
    )


def _plan_models(plan: MigrationPlan) -> tuple[type[Model], ...]:
    if plan.models:
        return plan.models
    return tuple(_load_model_spec(spec) for spec in plan.model_specs)


def _assert_plan_is_fresh(plan: MigrationPlan) -> tuple[type[Model], ...]:
    models = _plan_models(plan)
    live_states = tuple(
        _collect_live_schema_state(get_runtime(), model._classname) for model in models
    )
    live_fingerprint = _states_fingerprint(live_states)
    if plan.fail_on_drift and live_fingerprint != plan.live_schema_fingerprint:
        raise StaleMigrationPlanError("Live schema changed since planning")
    return models


def apply_plan(
    plan: MigrationPlan | dict[str, Any],
    *,
    backup_dir: str | Path = ".iris_persistence/backups",
    allow_destructive: bool = False,
    yes: bool | None = None,
) -> ApplyResult:
    if isinstance(plan, dict):
        plan = MigrationPlan.from_dict(plan)
    if yes is not None:
        allow_destructive = yes

    unsafe = tuple(
        operation
        for operation in plan.operations
        if operation.safety in {"destructive", "manual-review"}
    )
    if unsafe and not allow_destructive:
        return ApplyResult(
            status="blocked",
            target_revision=plan.target_revision,
            skipped_operations=unsafe,
        )
    if not plan.operations:
        return ApplyResult(status="noop", target_revision=plan.target_revision)

    models = _assert_plan_is_fresh(plan)
    runtime = get_runtime()
    backup_path = _write_apply_backup(
        runtime=runtime,
        plan=plan,
        models=models,
        backup_dir=backup_dir,
    )
    _run_with_schema_transaction(
        runtime,
        lambda: _apply_plan_without_transaction(runtime, models),
    )
    return ApplyResult(
        status="applied",
        target_revision=plan.target_revision,
        applied_operations=plan.operations,
        backup_dir=str(backup_path),
    )


def _apply_plan_without_transaction(
    runtime: Any,
    models: Sequence[type[Model]],
) -> None:
    seen: set[str] = set()
    for model_cls in models:
        _sync_schema_model(runtime, model_cls, seen)


def check_drift(models: Iterable[type[Model]]) -> DriftReport:
    model_tuple = _resolve_models(models)
    diffs = [diff_schema(model_cls) for model_cls in model_tuple]
    live_states = tuple(diff.before_state for diff in diffs if diff.before_state is not None)
    expected_states = tuple(diff.after_state for diff in diffs if diff.after_state is not None)
    rendered_diffs = tuple(diff.to_unified_diff() for diff in diffs if diff.has_changes)
    return DriftReport(
        has_drift=bool(rendered_diffs),
        diffs=rendered_diffs,
        live_schema_fingerprint=_states_fingerprint(live_states),
        expected_schema_fingerprint=_states_fingerprint(expected_states),
    )


def verify_plan(plan: MigrationPlan | dict[str, Any]) -> VerifyResult:
    if isinstance(plan, dict):
        plan = MigrationPlan.from_dict(plan)
    models = _plan_models(plan)
    diffs = [diff_schema(model_cls) for model_cls in models]
    live_states = tuple(diff.before_state for diff in diffs if diff.before_state is not None)
    live_fingerprint = _states_fingerprint(live_states)
    rendered_diffs = tuple(diff.to_unified_diff() for diff in diffs if diff.has_changes)
    return VerifyResult(
        converged=live_fingerprint == plan.target_schema_fingerprint and not rendered_diffs,
        live_schema_fingerprint=live_fingerprint,
        target_schema_fingerprint=plan.target_schema_fingerprint,
        diffs=rendered_diffs,
    )


def rollback_backup(
    backup_dir: str | Path,
    *,
    allow_destructive: bool = False,
) -> RollbackResult:
    if not allow_destructive:
        raise UnsafeMigrationError("Backup rollback is destructive; pass allow_destructive=True")

    root = Path(backup_dir)
    metadata_path = root / "metadata.json"
    if not metadata_path.exists():
        raise BackupRestoreError(f"Backup metadata not found: {metadata_path}")

    json.loads(metadata_path.read_text(encoding="utf-8"))
    states_path = root / "schema_states.json"
    if not states_path.exists():
        raise BackupRestoreError(f"Backup schema states not found: {states_path}")
    states = tuple(
        SchemaState.from_dict(item)
        for item in json.loads(states_path.read_text(encoding="utf-8"))
    )

    runtime = get_runtime()
    restored, deleted = _run_with_schema_transaction(
        runtime,
        lambda: _rollback_backup_without_transaction(runtime, states),
    )

    return RollbackResult(
        status="rolled_back",
        backup_dir=str(root),
        restored_classes=tuple(restored),
        deleted_classes=tuple(deleted),
    )


def _rollback_backup_without_transaction(
    runtime: Any,
    states: Sequence[SchemaState],
) -> tuple[list[str], list[str]]:
    restored: list[str] = []
    deleted: list[str] = []
    for state in states:
        if state.superclasses:
            _sync_schema_state(runtime, state)
            restored.append(state.classname)
        else:
            _call_status(runtime, "%SYSTEM.OBJ", "Delete", state.classname, "-d")
            deleted.append(state.classname)
    return restored, deleted


__all__ = [
    "DriftReport",
    "ApplyResult",
    "BackupRestoreError",
    "MigrationError",
    "MigrationOperation",
    "MigrationPlan",
    "RollbackResult",
    "StaleMigrationPlanError",
    "UnsafeMigrationError",
    "VerifyResult",
    "apply_plan",
    "check_drift",
    "create_plan",
    "rollback_backup",
    "verify_plan",
]
