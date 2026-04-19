from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import iris_orm
from iris_orm import scaffold_from_iris
from tests.fixture_support import (
    OBJECTSCRIPT_FIXTURES,
    delete_iris_classes,
    load_module_from_path,
    load_objectscript_fixture,
)


def _has_iris_runtime() -> bool:
    return importlib.util.find_spec("iris") is not None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _has_iris_runtime(), reason="requires IRIS runtime"),
]


@pytest.fixture(scope="module", autouse=True)
def configure_live_runtime():
    iris_orm.configure()


@pytest.fixture()
def loaded_objectscript_fixtures():
    loaded = [
        load_objectscript_fixture("persistent_fixture"),
        load_objectscript_fixture("request_fixture"),
        load_objectscript_fixture("serial_fixture"),
    ]
    try:
        yield loaded
    finally:
        for fixture in reversed(loaded):
            delete_iris_classes(fixture.classnames)


def test_objectscript_fixture_sources_are_present():
    expected = [
        OBJECTSCRIPT_FIXTURES / "persistent_fixture.cls",
        OBJECTSCRIPT_FIXTURES / "persistent_fixture.py",
        OBJECTSCRIPT_FIXTURES / "request_fixture.cls",
        OBJECTSCRIPT_FIXTURES / "request_fixture.py",
        OBJECTSCRIPT_FIXTURES / "serial_fixture.cls",
        OBJECTSCRIPT_FIXTURES / "serial_fixture.py",
    ]
    for path in expected:
        assert path.exists(), f"Missing fixture source: {path}"


def test_objectscript_fixture_scaffold_e2e(loaded_objectscript_fixtures, tmp_path: Path):
    result = scaffold_from_iris(
        "Demo.Source%",
        str(tmp_path),
        extract_meta=True,
        return_result=True,
    )
    assert result.warnings == []
    assert len(result.files) == 3
    assert {fixture.name for fixture in loaded_objectscript_fixtures} == {
        "persistent_fixture",
        "request_fixture",
        "serial_fixture",
    }

    modules_by_class = {}
    for file_path in result.files:
        module = load_module_from_path(Path(file_path))
        generated_class = next(
            value
            for value in module.__dict__.values()
            if isinstance(value, type)
            and issubclass(value, iris_orm.IRISModel)
            and value is not iris_orm.IRISModel
        )
        modules_by_class[generated_class._classname] = generated_class

    PersistentFixture = modules_by_class["Demo.SourcePersistentFixture"]
    RequestFixture = modules_by_class["Demo.SourceRequestFixture"]
    SerialFixture = modules_by_class["Demo.SourceSerialFixture"]

    row = PersistentFixture(Title="fixture-title", Enabled=False, Score=9)
    row.save()
    fetched = PersistentFixture.get(row.pk)
    assert fetched is not None
    assert fetched.Title == "fixture-title"
    assert fetched.Enabled is False
    assert fetched.Score == 9

    assert PersistentFixture._superclasses in {"%Persistent", "%Library.Persistent"}
    assert any(index.name == "TitleIdx" for index in PersistentFixture._indexes)

    assert RequestFixture._superclasses == "Ens.Request"
    assert RequestFixture._fields["CorrelationId"].required is True
    assert RequestFixture._fields["CorrelationId"].maxlen == 64
    assert RequestFixture._fields["SourceSystem"].default == "ERP"

    assert SerialFixture._superclasses in {"%SerialObject", "%Library.SerialObject"}
    assert SerialFixture._fields["Street"].required is True
    assert SerialFixture._fields["Street"].maxlen == 120
    assert SerialFixture._fields["Country"].default == "FR"
