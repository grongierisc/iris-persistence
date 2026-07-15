from __future__ import annotations

from typing import Any

from iris_persistence import Field, Model


class DemoListFixtureItem(Model, serial=True):
    Value: str | None = Field(default=None, max_length=120)

    class Meta:
        classname = "Demo.DemoListFixtureItem"
        mode = "managed"


class DemoListFixture(Model, persistent=True):
    ListAttributes: list[Any] = Field(default_factory=list, iris_type="%List")
    ListDataType: list[Any] = Field(default_factory=list, iris_type="%ListOfDataTypes")
    ArrayDataType: dict[str, Any] = Field(
        default_factory=dict,
        iris_type="%ArrayOfDataTypes",
    )
    ListOfObjects: list[DemoListFixtureItem] = Field(
        default_factory=list,
        iris_type="Demo.DemoListFixtureItem",
        collection="list",
    )
    ArrayOfObjects: dict[str, DemoListFixtureItem] = Field(
        default_factory=dict,
        iris_type="Demo.DemoListFixtureItem",
        collection="array",
    )

    class Meta:
        classname = "Demo.DemoListFixture"
        mode = "managed"
