from __future__ import annotations

import datetime
from typing import Annotated

from iris_orm import Field, Index, IRISModel, StorageData, StorageDefinition


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
