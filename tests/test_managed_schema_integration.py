from __future__ import annotations

import importlib.util

import pytest

from iris_persistence import Field, Model
from iris_persistence.migrations import apply_plan, create_plan, verify_plan
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
COLLECTION_CLASSNAME = "Demo.ManagedCollectionFixture"


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


class ManagedCollectionBefore(Model, persistent=True):
    toto: str = Field(default="toto", max_length=10, required=True)

    class Meta:
        classname = COLLECTION_CLASSNAME
        mode = "replace"


class ManagedCollectionAfter(Model, persistent=True):
    toto: list[str] = Field(default_factory=list)

    class Meta:
        classname = COLLECTION_CLASSNAME
        mode = "managed"


def _property_names(classname: str) -> set[str]:
    cursor = get_runtime().get_dbapi_connection().cursor()
    cursor.execute(
        "SELECT Name FROM %Dictionary.PropertyDefinition WHERE parent = ?",
        (classname,),
    )
    return {str(row[0]) for row in cursor.fetchall()}


def _property_collection(classname: str, property_name: str) -> str:
    cursor = get_runtime().get_dbapi_connection().cursor()
    cursor.execute(
        "SELECT Collection FROM %Dictionary.PropertyDefinition WHERE parent = ? AND Name = ?",
        (classname, property_name),
    )
    row = cursor.fetchone()
    return "" if row is None or row[0] is None else str(row[0])


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


def test_managed_migration_updates_scalar_property_to_list_collection(tmp_path):
    delete_iris_classes([COLLECTION_CLASSNAME])
    try:
        ManagedCollectionBefore.sync_schema()
        assert _property_collection(COLLECTION_CLASSNAME, "toto") == ""

        plan = create_plan([ManagedCollectionAfter], target_revision="managed-list")
        collection_update = next(
            operation
            for operation in plan.operations
            if operation.op_type == "update_property"
            and operation.path == "properties.toto"
        )
        assert collection_update.safety == "managed-update"
        assert collection_update.after["collection"] == "list"

        result = apply_plan(plan, backup_dir=tmp_path)

        assert result.status == "applied"
        assert _property_collection(COLLECTION_CLASSNAME, "toto") == "list"
        assert verify_plan(plan).converged is True
    finally:
        delete_iris_classes([COLLECTION_CLASSNAME])
