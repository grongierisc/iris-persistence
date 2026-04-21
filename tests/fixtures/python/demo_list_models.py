from __future__ import annotations

from typing import Annotated, Any

from iris_orm import Field, IRISModel


class DemoListFixtureItem(IRISModel):
    Value: Annotated[str | None, Field(maxlen=120)] = None

    class Meta:
        classname = "Demo.DemoListFixtureItem"
        superclasses = "%Library.SerialObject"
        mode = "replace"


class DemoListFixture(IRISModel):
    ListAttributes: Annotated[list[Any] | None, Field(iris_type="%List")] = None
    ListDataType: Annotated[list[Any] | None, Field(iris_type="%ListOfDataTypes")] = None
    ArrayDataType: Annotated[dict[str, Any] | None, Field(iris_type="%ArrayOfDataTypes")] = None
    ListOfObjects: Annotated[
        list[DemoListFixtureItem] | None,
        Field(iris_type="Demo.DemoListFixtureItem", collection="list"),
    ] = None
    ArrayOfObjects: Annotated[
        dict[str, DemoListFixtureItem] | None,
        Field(iris_type="Demo.DemoListFixtureItem", collection="array"),
    ] = None

    class Meta:
        classname = "Demo.DemoListFixture"
        superclasses = "%Library.Persistent"
        mode = "replace"
