from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from iris_orm import Field, IRISModel, Index


class DemoFixture(IRISModel):
    Titi: Annotated[int, Field(required=False)]
    Toto: Annotated[str, Field(required=True)]
    bytes: Annotated[bytes, Field(required=False)]
    dickt: Annotated[dict, Field(required=False)]
    snake_case: Annotated[str, Field(required=False)]

    class Meta:
        classname = "Demo.Demo"
        mode = "extend"
        superclasses = "%Library.Persistent"
        indexes = [Index("TotoIdx", properties="Toto", unique=True)]
        parameters = {"TITI": "TOTO"}


def make_demo_toto() -> str:
    return f"Hello-{uuid4().hex[:8].upper()}"


def run_demo_fixture(
    toto: str | None = None, *, sync_schema: bool = True
) -> dict[str, object]:
    demo = DemoFixture(
        Toto=make_demo_toto() if toto is None else toto,
        Titi=42,
        bytes=b"\x00\x01\x02",
        dickt={"key": "value"},
        snake_case="snake_case_value",
    )
    if sync_schema:
        DemoFixture.sync_schema()
    demo.save()

    loaded = DemoFixture.get(demo.pk)
    if loaded is None:
        raise RuntimeError("Unable to reload saved Demo row")

    return {
        "saved_pk": demo.pk,
        "loaded": loaded,
        "all_demos": list(DemoFixture.all()),
    }
