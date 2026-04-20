from __future__ import annotations

import datetime
import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

import iris_orm
from iris_orm import scaffold_from_iris
from tests.fixtures.python.full_circle_fixture import FullCircleFixture
from tests.fixtures.python.round_trip_fixtures import (
    ClassMetadataRoundTripFixture,
    SQLProjectionRoundTripFixture,
)


def _has_iris_runtime() -> bool:
    return importlib.util.find_spec("iris") is not None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _has_iris_runtime(), reason="requires IRIS runtime"),
]


def _load_module(module_path: Path):
    module_name = f"generated_{module_path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module", autouse=True)
def configure_live_runtime():
    iris_orm.configure()


def test_full_circle_round_trip(tmp_path: Path):
    FullCircleFixture.sync_schema()

    source_created = FullCircleFixture(
        Title="source-created",
        Description="Created from the source model",
        Price=17.25,
        IsActive=False,
        Count=0,
        BlobData=b"\x00\x01\x02",
        Data={"origin": "source"},
        Tags=["alpha", "beta"],
        EventDate=datetime.date(2024, 1, 2),
        EventTime=datetime.time(3, 4, 5, 654321),
        CreatedAt=datetime.datetime(2024, 1, 2, 3, 4, 5, 123456),
    )
    source_created.save()
    assert source_created.pk is not None

    generated_files = scaffold_from_iris("Demo.FullCircleFixture", str(tmp_path), extract_meta=True)
    assert generated_files == [str(tmp_path / "fullcirclefixture.py")]

    scaffolded_module = _load_module(tmp_path / "fullcirclefixture.py")
    ScaffoldedFullCircleFixture = scaffolded_module.FullCircleFixture

    scaffolded_source = ScaffoldedFullCircleFixture.get(source_created.pk)
    assert scaffolded_source is not None
    assert scaffolded_source.Title == "source-created"
    assert scaffolded_source.Description == "Created from the source model"
    assert scaffolded_source.Price == 17.25
    assert scaffolded_source.IsActive is False
    assert scaffolded_source.Count == 0
    assert scaffolded_source.BlobData == b"\x00\x01\x02"
    assert scaffolded_source.Data == {"origin": "source"}
    assert scaffolded_source.Tags == ["alpha", "beta"]
    assert scaffolded_source.EventDate == datetime.date(2024, 1, 2)
    assert scaffolded_source.EventTime == datetime.time(3, 4, 5, 654321)
    assert scaffolded_source.CreatedAt == datetime.datetime(2024, 1, 2, 3, 4, 5, 123456)

    scaffold_created = ScaffoldedFullCircleFixture(
        Title="scaffold-created",
        Description="",
        Price=0.0,
        IsActive=False,
        Count=0,
        BlobData=b"",
        Data={},
        Tags=[],
        EventDate=datetime.date(2024, 6, 7),
        EventTime=datetime.time(8, 9, 10, 111222),
        CreatedAt=datetime.datetime(2024, 6, 7, 8, 9, 10, 111222),
    )
    scaffold_created.save()
    assert scaffold_created.pk is not None

    scaffold_defaulted = ScaffoldedFullCircleFixture(
        Title="scaffold-defaulted",
        Data={"origin": "scaffold"},
        Tags=["gamma"],
        CreatedAt=datetime.datetime(2024, 6, 7, 8, 9, 10),
    )
    assert scaffold_defaulted.Description == "No desc"
    assert scaffold_defaulted.Price == 15.5
    assert scaffold_defaulted.IsActive is True
    assert scaffold_defaulted.Count == 42
    scaffold_defaulted.save()
    assert scaffold_defaulted.pk is not None

    source_view = FullCircleFixture.get(scaffold_created.pk)
    assert source_view is not None
    assert source_view.Title == "scaffold-created"
    assert source_view.Description == ""
    assert source_view.Price == 0.0
    assert source_view.IsActive is False
    assert source_view.Count == 0
    assert source_view.BlobData == b""
    assert source_view.Data == {}
    assert source_view.Tags == []
    assert source_view.EventDate == datetime.date(2024, 6, 7)
    assert source_view.EventTime == datetime.time(8, 9, 10, 111222)
    assert source_view.CreatedAt == datetime.datetime(2024, 6, 7, 8, 9, 10, 111222)

    defaulted_view = FullCircleFixture.get(scaffold_defaulted.pk)
    assert defaulted_view is not None
    assert defaulted_view.Description == "No desc"
    assert defaulted_view.Price == 15.5
    assert defaulted_view.IsActive is True
    assert defaulted_view.Count == 42
    assert defaulted_view.Data == {"origin": "scaffold"}
    assert defaulted_view.Tags == ["gamma"]

    matching = ScaffoldedFullCircleFixture.where(Title="scaffold-created").all()
    assert any(row.pk == scaffold_created.pk for row in matching)

    assert ScaffoldedFullCircleFixture._classname == "Demo.FullCircleFixture"
    assert ScaffoldedFullCircleFixture._sync_mode == "observe"
    assert ScaffoldedFullCircleFixture._fields["Title"].iris_type == "%Library.String"
    assert ScaffoldedFullCircleFixture._fields["BlobData"].iris_type == "%Stream.GlobalBinary"
    assert ScaffoldedFullCircleFixture._fields["EventDate"].iris_type == "%Library.Date"
    assert ScaffoldedFullCircleFixture._fields["CreatedAt"].iris_type == "%Library.TimeStamp"
    assert any(index.name == "TitleIdx" for index in ScaffoldedFullCircleFixture._indexes)

    storage = ScaffoldedFullCircleFixture._storage
    assert storage is not None
    assert storage.data_location == "^Demo.FullCircleFixtureD"
    assert storage.default_data == "FullCircleFixtureDefaultData"
    default_data = next(
        item for item in storage.data if item.name == "FullCircleFixtureDefaultData"
    )
    assert default_data.structure == "listnode"
    assert default_data.values["9"] == "Title"


def test_class_metadata_round_trip(tmp_path: Path):
    ClassMetadataRoundTripFixture.sync_schema()

    generated_files = scaffold_from_iris(
        "Demo.ClassMetadataRoundTripFixture",
        str(tmp_path),
        extract_meta=True,
    )
    assert generated_files == [str(tmp_path / "classmetadataroundtripfixture.py")]

    scaffolded_module = _load_module(tmp_path / "classmetadataroundtripfixture.py")
    ScaffoldedFixture = scaffolded_module.ClassMetadataRoundTripFixture

    assert ScaffoldedFixture._class_metadata is not None
    assert ScaffoldedFixture._class_metadata.description == "round-trip class metadata"
    assert ScaffoldedFixture._class_metadata.deprecated is True
    assert ScaffoldedFixture._class_metadata.final is True
    assert (
        ScaffoldedFixture._class_metadata.sql_table_name
        == "Demo_ClassMetadataRoundTripFixture"
    )
    assert ScaffoldedFixture._class_metadata.procedure_block is True


def test_sql_projection_metadata_round_trip(tmp_path: Path):
    SQLProjectionRoundTripFixture.sync_schema()

    generated_files = scaffold_from_iris(
        "Demo.SQLProjectionRoundTripFixture",
        str(tmp_path),
        extract_meta=False,
    )
    assert generated_files == [str(tmp_path / "sqlprojectionroundtripfixture.py")]

    scaffolded_module = _load_module(tmp_path / "sqlprojectionroundtripfixture.py")
    ScaffoldedFixture = scaffolded_module.SQLProjectionRoundTripFixture

    assert ScaffoldedFixture._fields["Tags"].sql_list_delimiter == "|"
    assert ScaffoldedFixture._fields["Tags"].sql_list_type == "DELIMITED"
    assert ScaffoldedFixture._fields["TitleUpper"].sql_compute_code == "Set {*} = {Title}"
    assert ScaffoldedFixture._fields["TitleUpper"].sql_compute_on_change == "Title"
    assert ScaffoldedFixture._fields["TitleUpper"].sql_computed is True
