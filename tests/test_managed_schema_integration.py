from __future__ import annotations

import importlib.util

import pytest

from iris_persistence import Field, Index, Model, StorageMigrationRequired, StorageTuning
from iris_persistence.advanced_storage import (
    StorageProperty,
    inspect_existing_storage,
    tune_existing_storage_statistics,
)
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
TUNED_CLASSNAME = "Demo.ManagedTunedStorageFixture"


class ManagedCollisionBefore(Model, persistent=True):
    my_field: str | None = None
    barr: str | None = None
    titi: str | None = None
    tata: str | None = Field(default="tata", max_length=10)

    class Meta:
        classname = CLASSNAME
        mode = "managed"


class ManagedCollisionAfter(Model, persistent=True):
    my_field: str | None = None

    class Meta:
        classname = CLASSNAME
        mode = "managed"


class ManagedCollectionBefore(Model, persistent=True):
    toto: str = Field(default="toto", max_length=10, required=True)

    class Meta:
        classname = COLLECTION_CLASSNAME
        mode = "managed"


class ManagedCollectionAfter(Model, persistent=True):
    toto: list[str] = Field(default_factory=list)

    class Meta:
        classname = COLLECTION_CLASSNAME
        mode = "managed"


class ManagedTunedStorage(Model, persistent=True):
    Name: str | None = None

    class Meta:
        classname = TUNED_CLASSNAME
        mode = "managed"
        indexes = [Index("NameIdx", properties="Name")]
        storage_tuning = StorageTuning(
            data_location="^Demo.ManagedTunedD",
            id_location="^Demo.ManagedTunedD",
            index_location="^Demo.ManagedTunedI",
            index_locations={"NameIdx": '^Demo.ManagedTunedI("NameIdx")'},
        )


class ManagedRelocatedStorage(Model, persistent=True):
    Name: str | None = None

    class Meta:
        classname = TUNED_CLASSNAME
        mode = "managed"
        storage_tuning = StorageTuning(data_location="^Demo.RelocatedD")


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


def test_tuned_default_is_completed_by_compiler_and_then_immutable():
    delete_iris_classes([TUNED_CLASSNAME])
    try:
        ManagedTunedStorage.sync_schema()
        cursor = get_runtime().get_dbapi_connection().cursor()
        cursor.execute(
            "SELECT Name, DataLocation, IdLocation, IndexLocation "
            "FROM %Dictionary.StorageDefinition WHERE parent = ?",
            (TUNED_CLASSNAME,),
        )
        assert cursor.fetchone() == (
            "Default",
            "^Demo.ManagedTunedD",
            "^Demo.ManagedTunedD",
            "^Demo.ManagedTunedI",
        )
        cursor.execute(
            "SELECT COUNT(*) FROM %Dictionary.StorageDataDefinition WHERE parent = ?",
            (f"{TUNED_CLASSNAME}||Default",),
        )
        assert cursor.fetchone()[0] > 0

        tune_existing_storage_statistics(
            TUNED_CLASSNAME,
            properties=(StorageProperty(name="Name", selectivity="5.0000%"),),
        )
        cursor.execute(
            "SELECT Selectivity FROM %Dictionary.StoragePropertyDefinition WHERE parent = ? "
            "AND Name = ?",
            (f"{TUNED_CLASSNAME}||Default", "Name"),
        )
        assert cursor.fetchone()[0] == "5.0000%"
        snapshot = inspect_existing_storage(TUNED_CLASSNAME)
        assert snapshot.name == "Default"
        assert snapshot.data_location == "^Demo.ManagedTunedD"
        assert {item.name: item for item in snapshot.properties}["Name"].selectivity == "5.0000%"

        repeated_diff = ManagedTunedStorage.diff_schema()
        assert repeated_diff.has_changes is False, repeated_diff.to_unified_diff()
        ManagedTunedStorage.sync_schema()
        with pytest.raises(StorageMigrationRequired):
            ManagedRelocatedStorage.sync_schema()
    finally:
        delete_iris_classes([TUNED_CLASSNAME])
