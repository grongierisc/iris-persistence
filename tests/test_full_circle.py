from __future__ import annotations

import datetime
import importlib.util
import sys
import uuid
from pathlib import Path
from typing import Annotated

import pytest

import iris_orm
from iris_orm import Field, Index, IRISModel, StorageData, StorageDefinition, scaffold_from_iris


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


class FullCircleFixture(IRISModel):
    Title: Annotated[str, Field(required=True, maxlen=350)]
    Description: Annotated[str | None, Field(required=False, default="No desc", maxlen=500)] = (
        "No desc"
    )
    Price: Annotated[float | None, Field(required=False, default=15.5)] = 15.5
    IsActive: Annotated[bool | None, Field(required=False, default=True)] = True
    Count: Annotated[int | None, Field(required=False, default=42)] = 42
    BlobData: Annotated[bytes | None, Field(required=False)] = None
    Data: Annotated[dict | None, Field(required=False)] = None
    Tags: Annotated[list | None, Field(required=False)] = None
    EventDate: Annotated[datetime.date | None, Field(required=False)] = None
    EventTime: Annotated[datetime.time | None, Field(required=False)] = None
    CreatedAt: Annotated[datetime.datetime | None, Field(required=False)] = None

    class Meta:
        classname = "Demo.FullCircleFixture"
        mode = "replace"
        indexes = [Index("TitleIdx", properties="Title")]
        storage = StorageDefinition(
            data_location="^Demo.FullCircleFixtureD",
            default_data="FullCircleFixtureDefaultData",
            type="%Storage.Persistent",
            data=(
                StorageData(
                    name="FullCircleFixtureDefaultData",
                    structure="listnode",
                    values={
                        "1": "%%CLASSNAME",
                        "2": "Count",
                        "3": "CreatedAt",
                        "4": "Description",
                        "5": "EventDate",
                        "6": "EventTime",
                        "7": "IsActive",
                        "8": "Price",
                        "9": "Title",
                    },
                ),
            ),
        )


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
