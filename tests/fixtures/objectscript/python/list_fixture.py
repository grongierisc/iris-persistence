from __future__ import annotations

from typing import Any

from iris_orm import Field, Model


class ListFixtureItem(Model, serial=True):
    Value: str | None = Field(default=None, max_length=120)

    class Meta:
        classname = "Demo.ListFixtureItem"
        mode = "replace"


class ListFixture(Model, persistent=True):
    ListAttributes: list[Any] = Field(default_factory=list, iris_type="%List")
    ListDataType: list[Any] = Field(default_factory=list, iris_type="%ListOfDataTypes")
    ArrayDataType: dict[str, Any] = Field(
        default_factory=dict,
        iris_type="%ArrayOfDataTypes",
    )
    ListOfObjects: list[ListFixtureItem] = Field(
        default_factory=list,
        iris_type="Demo.ListFixtureItem",
        collection="list",
    )
    ArrayOfObjects: dict[str, ListFixtureItem] = Field(
        default_factory=dict,
        iris_type="Demo.ListFixtureItem",
        collection="array",
    )

    class Meta:
        classname = "Demo.ListFixture"
        mode = "replace"


FIXTURE_MODELS = [ListFixtureItem, ListFixture]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
FIXTURE_SOURCE_FILES = ["list_fixture_item.cls", "list_fixture.cls"]
