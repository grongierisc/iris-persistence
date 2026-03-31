from __future__ import annotations

from pathlib import Path

from iris_orm import IRISModel, Registry, SchemaCompiler, field
from iris_orm.migrations import MigrationRunner

from .fake_runtime import FakeAdapter


def test_generate_migration_contains_schema_snapshots(tmp_path: Path):
    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Name: str = field(required=True, maxlen=200)

    registry = Registry()
    registry.register(Product)
    runner = MigrationRunner(tmp_path / "migrations", adapter=FakeAdapter(), registry=registry)
    path = runner.generate("create product")

    content = path.read_text(encoding="utf-8")
    assert "schema_before" in content
    assert "schema_after" in content
    assert "SchemaPlanner" in content
    assert "SchemaApplier" in content


def test_upgrade_and_downgrade_apply_schema_snapshots(tmp_path: Path):
    adapter = FakeAdapter()

    class Product(IRISModel):
        _iris_classname = "Demo.Product"

        Name: str = field(required=True, maxlen=200)

    registry = Registry()
    registry.register(Product)
    runner = MigrationRunner(tmp_path / "migrations", adapter=adapter, registry=registry)
    runner.init()
    runner.generate("create product")
    runner.upgrade()

    live = SchemaCompiler(adapter).catalog_from_iris(["Demo.Product"])
    assert [item.name for item in live.classes] == ["Demo.Product"]

    runner.downgrade()
    after = SchemaCompiler(adapter).catalog_from_iris(["Demo.Product"])
    assert after.classes == ()
