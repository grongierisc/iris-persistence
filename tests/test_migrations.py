from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from iris_persistence.migrations import (
    BackupRestoreError,
    MigrationOperation,
    MigrationPlan,
    StaleMigrationPlanError,
    apply_plan,
    create_plan,
    rollback_backup,
    verify_plan,
)
from iris_persistence.runtime import configure_default_runtime
from tests.fixtures.python.schema_mapping_fixtures import ParameterFixture, SchemaMetadataFixture
from tests.test_schema import _TransactionalRuntime


@pytest.fixture
def recording_runtime():
    runtime = _TransactionalRuntime()
    configure_default_runtime(runtime)
    try:
        yield runtime
    finally:
        configure_default_runtime(None)


def test_migration_plan_json_is_deterministic(recording_runtime, tmp_path):
    plan = create_plan([ParameterFixture], target_revision="001")
    plan_path = tmp_path / "plan.json"
    plan.save(plan_path)

    assert plan.to_json() == MigrationPlan.from_dict(plan.to_dict()).to_json()
    assert MigrationPlan.load(plan_path).to_json() == plan.to_json()
    assert plan.target_revision == "001"
    assert [operation.op_type for operation in plan.operations] == [
        "create_class",
        "update_super",
        "add_parameter",
        "add_property",
        "compile_class",
    ]


def test_apply_plan_uses_transaction_and_writes_backup(
    recording_runtime,
    tmp_path,
):
    plan = create_plan([ParameterFixture], target_revision="001")

    result = apply_plan(plan, backup_dir=tmp_path)

    assert result.status == "applied"
    assert result.target_revision == "001"
    assert result.backup_dir is not None
    backup_path = Path(result.backup_dir)
    assert (backup_path / "plan.json").exists()
    assert (backup_path / "metadata.json").exists()
    assert (backup_path / "schema_states.json").exists()
    assert not (backup_path / "classes").exists()
    assert recording_runtime.transaction_events == ["begin", "commit"]
    assert any(
        getattr(obj, "Name", None) == "Demo.ParameterFixture" for obj in recording_runtime.saved
    )


def test_apply_plan_rejects_stale_live_schema_fingerprint(recording_runtime):
    plan = create_plan([ParameterFixture], target_revision="001")
    stale = replace(plan, live_schema_fingerprint="not-the-live-fingerprint")

    with pytest.raises(StaleMigrationPlanError, match="Live schema changed"):
        apply_plan(stale)

    assert recording_runtime.transaction_events == []


def test_apply_plan_creates_custom_storage_with_new_class(recording_runtime, tmp_path):
    plan = create_plan([SchemaMetadataFixture], target_revision="storage")

    result = apply_plan(plan, backup_dir=tmp_path)

    assert result.status == "applied"
    assert any(operation.op_type == "add_storage" for operation in plan.operations)


def test_blocked_storage_change_cannot_be_bypassed(recording_runtime, tmp_path):
    plan = create_plan([ParameterFixture], target_revision="storage-move")
    blocked = MigrationOperation(
        op_type="blocked_storage_change",
        classname="Demo.ParameterFixture",
        path="storage",
        safety="blocked",
    )
    plan = replace(plan, operations=(blocked,))

    result = apply_plan(plan, backup_dir=tmp_path)

    assert result.status == "blocked"
    assert result.skipped_operations == (blocked,)
    assert result.backup_dir is None
    assert recording_runtime.transaction_events == []


def test_verify_plan_reports_not_converged_before_apply(recording_runtime):
    plan = create_plan([ParameterFixture], target_revision="001")

    result = verify_plan(plan)

    assert result.converged is False
    assert result.diffs


def test_rollback_backup_deletes_classes_created_by_apply(recording_runtime, tmp_path):
    plan = create_plan([ParameterFixture], target_revision="001")
    apply_result = apply_plan(plan, backup_dir=tmp_path)

    assert apply_result.backup_dir is not None
    result = rollback_backup(apply_result.backup_dir)

    assert result.status == "rolled_back"
    assert result.deleted_classes == ("Demo.ParameterFixture",)
    assert (
        "%SYSTEM.OBJ",
        "Delete",
        ("Demo.ParameterFixture", "-d"),
    ) in recording_runtime.calls


def test_rollback_backup_restores_existing_class_from_schema_state(recording_runtime, tmp_path):
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()
    (backup_dir / "metadata.json").write_text(
        json.dumps({"backup_id": "backup", "class_states": []}),
        encoding="utf-8",
    )
    (backup_dir / "schema_states.json").write_text(
        json.dumps(
            [
                {
                    "classname": "Demo.RestoreFixture",
                    "super": "%Persistent",
                    "metadata": {"description": "before"},
                    "parameters": {"P": "1"},
                    "properties": {
                        "Payload": {
                            "type": "%Library.String",
                            "required": True,
                            "max_length": "50",
                        }
                    },
                    "indexes": {
                        "PayloadIdx": {
                            "properties": "Payload",
                            "unique": True,
                        }
                    },
                    "storage": None,
                }
            ]
        ),
        encoding="utf-8",
    )

    result = rollback_backup(backup_dir)

    assert result.restored_classes == ("Demo.RestoreFixture",)
    restored = recording_runtime.saved[-1]
    assert restored.Name == "Demo.RestoreFixture"
    assert restored.Super == "%Persistent"
    assert restored.Description == "before"
    assert restored.Parameters.items[0].Name == "P"
    assert restored.Properties.items[0].Name == "Payload"
    assert restored.Properties.items[0].Parameters.MAXLEN == "50"
    assert restored.Indices.items[0].Name == "PayloadIdx"
    assert all(call[1] != "Load" for call in recording_runtime.calls)


def test_rollback_backup_requires_metadata(recording_runtime, tmp_path):
    with pytest.raises(BackupRestoreError, match="metadata"):
        rollback_backup(tmp_path)
