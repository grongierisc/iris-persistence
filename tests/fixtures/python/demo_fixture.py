from __future__ import annotations

from uuid import uuid4

from iris_persistence import Field, Model


class DemoFixture(Model, persistent=True):
    Titi: int | None = None
    Toto: str = Field(required=True, unique=True)
    bytes: bytes | None = None
    dickt: dict | None = None
    snake_case: str | None = None

    class Meta:
        classname = "Demo.Demo"
        mode = "managed"
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
