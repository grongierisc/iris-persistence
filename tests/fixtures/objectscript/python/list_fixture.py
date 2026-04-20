from __future__ import annotations

from typing import Annotated, Any

from iris_orm import Field, IRISModel


class ListFixtureItem(IRISModel):
    Value: Annotated[str | None, Field(maxlen=120)] = None

    class Meta:
        classname = "Demo.ListFixtureItem"
        superclasses = "%Library.SerialObject"
        mode = "replace"


class ListFixture(IRISModel):
    ListAttributes: Annotated[list[Any] | None, Field(iris_type="%List")] = None
    ListDataType: Annotated[list[Any] | None, Field(iris_type="%ListOfDataTypes")] = None
    ArrayDataType: Annotated[dict[str, Any] | None, Field(iris_type="%ArrayOfDataTypes")] = None
    ListOfObjects: Annotated[
        list[ListFixtureItem] | None,
        Field(iris_type="Demo.ListFixtureItem", collection="list"),
    ] = None
    ArrayOfObjects: Annotated[
        dict[str, ListFixtureItem] | None,
        Field(iris_type="Demo.ListFixtureItem", collection="array"),
    ] = None

    class Meta:
        classname = "Demo.ListFixture"
        superclasses = "%Library.Persistent"
        mode = "replace"


FIXTURE_MODELS = [ListFixtureItem, ListFixture]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
