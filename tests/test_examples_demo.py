from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path


def _load_module(module_path: Path):
    module_name = f"test_demo_{module_path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_progressive_examples_run_with_fake_backend():
    demo_root = Path(__file__).resolve().parents[1] / "examples" / "demo"

    minimal = _load_module(demo_root / "01_minimal_save.py")
    basic = _load_module(demo_root / "02_python_first_crud.py")
    related = _load_module(demo_root / "03_related_objects.py")
    advanced = _load_module(demo_root / "04_advanced_schema.py")

    minimal_result = minimal.run_demo(backend="fake")
    basic_result = basic.run_demo(backend="fake")
    related_result = related.run_demo(backend="fake")
    advanced_result = advanced.run_demo(backend="fake")

    assert minimal_result["backend"] == "fake"
    assert minimal_result["loaded"].Message == "Hello from iris_orm"
    assert len(minimal_result["all_rows"]) == 1

    assert basic_result["backend"] == "fake"
    assert basic_result["loaded"].Payload == {"origin": "python-first"}
    assert basic_result["loaded"].Tags == ["demo", "crud"]
    assert basic_result["matching"][0].pk == basic_result["saved_pk"]
    assert "WHERE Name = ?" in basic_result["last_sql"]
    assert "ORDER BY Name" in basic_result["last_sql"]

    assert related_result["backend"] == "fake"
    assert related_result["loaded"].Customer.Name == "Acme Clinic"
    assert related_result["loaded"].ShipTo.City == "Paris"
    assert [line.SKU for line in related_result["loaded"].Lines] == [
        "WIDGET-1",
        "WIDGET-2",
    ]
    assert related_result["loaded"].LineLookup["primary"].Qty == 2

    assert advanced_result["backend"] == "fake"
    assert advanced_result["loaded"].Payload == {"origin": "advanced-demo"}
    assert advanced_result["metadata"].sql_table_name == "Demo_ExampleShowcaseRecord"
    assert advanced_result["storage"].data_location == "^Demo.ExampleShowcaseRecordD"


def test_scaffold_demo_reports_skip_with_fake_backend():
    demo_root = Path(__file__).resolve().parents[1] / "examples" / "demo"
    scaffold = _load_module(demo_root / "05_scaffold_round_trip.py")

    result = scaffold.run_demo(backend="fake")

    assert result == {
        "backend": "fake",
        "skipped": True,
        "reason": "scaffold_from_iris needs live IRIS dictionary access",
    }
