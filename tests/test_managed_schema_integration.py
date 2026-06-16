from __future__ import annotations

import importlib.util

import pytest

from iris_persistence import Field, Model
from iris_persistence.migrations import apply_plan, create_plan
from iris_persistence.runtime import get_runtime
from tests.fixture_support import delete_iris_classes


def _has_iris_runtime() -> bool:
    return importlib.util.find_spec("iris") is not None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("configured_iris_runtime"),
    pytest.mark.skipif(not _has_iris_runtime(), reason="requires IRIS runtime"),
]


CLASSNAME = "Demo.ManagedCollisionFixture"


class ManagedCollisionBefore(Model, persistent=True):
    my_field: str | None = None
    barr: str | None = None
    titi: str | None = None
    tata: str | None = Field(default="tata", max_length=10)

    class Meta:
        classname = CLASSNAME
        mode = "replace"


class ManagedCollisionAfter(Model, persistent=True):
    my_field: str | None = None

    class Meta:
        classname = CLASSNAME
        mode = "managed"


def _property_names(classname: str) -> set[str]:
    cursor = get_runtime().get_dbapi_connection().cursor()
    cursor.execute(
        "SELECT Name FROM %Dictionary.PropertyDefinition WHERE parent = ?",
        (classname,),
    )
    return {str(row[0]) for row in cursor.fetchall()}


def test_managed_migration_updates_existing_properties_and_deletes_removed_ones(tmp_path):
    delete_iris_classes([CLASSNAME])
    try:
        ManagedCollisionBefore.sync_schema()
        before_names = _property_names(CLASSNAME)
        assert {"my_field", "barr", "titi", "tata"}.issubset(before_names)

        plan = create_plan([ManagedCollisionAfter], target_revision="managed-drop")
        managed_delete_paths = {
            operation.path
            for operation in plan.operations
            if operation.safety == "managed-delete"
        }
        assert {
            "properties.barr",
            "properties.titi",
            "properties.tata",
        }.issubset(managed_delete_paths)
        assert "properties.my_field" not in managed_delete_paths
        assert all(operation.safety != "destructive" for operation in plan.operations)

        result = apply_plan(plan, backup_dir=tmp_path)

        assert result.status == "applied"
        after_names = _property_names(CLASSNAME)
        assert "my_field" in after_names
        assert not {"barr", "titi", "tata"} & after_names
    finally:
        delete_iris_classes([CLASSNAME])
