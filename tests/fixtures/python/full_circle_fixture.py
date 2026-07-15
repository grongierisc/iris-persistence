from __future__ import annotations

import datetime

from iris_persistence import Field, Model
from iris_persistence.advanced_storage import StorageData, StorageDefinition


class FullCircleFixture(Model, persistent=True):
    Title: str = Field(required=True, max_length=350, index=True)
    Description: str | None = Field(default="No desc", max_length=500)
    Price: float | None = 15.5
    IsActive: bool | None = True
    Count: int | None = 42
    BlobData: bytes | None = None
    Data: dict | None = None
    Tags: list | None = None
    EventDate: datetime.date | None = None
    EventTime: datetime.time | None = None
    CreatedAt: datetime.datetime | None = None

    class Meta:
        classname = "Demo.FullCircleFixture"
        mode = "managed"
        custom_storage = StorageDefinition(
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
