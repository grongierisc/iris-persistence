from __future__ import annotations

from iris_persistence import Field, Model
from iris_persistence.advanced_storage import StorageDefinition, StorageProperty


class DemoBaseFixture(Model, persistent=True):
    class Meta:
        classname = "Demo.DemoBase"
        mode = "managed"
        parameters = {"BASEONLY": "BASE"}


class DemoNamespaceFixture(Model):
    Toto: str = Field(required=True, max_length=64, unique=True)
    Titi: int | None = None
    bytes: bytes | None = None
    dickt: dict | None = None
    snake_case: str | None = None

    class Meta:
        classname = "Demo.Demo"
        superclasses = "Demo.DemoBase"
        mode = "managed"
        parameters = {"TITI": "TOTO"}
        custom_storage = StorageDefinition(
            extent_size="5",
            properties=(
                StorageProperty(name="Titi", selectivity="50.0000%"),
                StorageProperty(
                    name="Toto",
                    selectivity="25.0000%",
                    outlier_selectivity='.999999:"HELLO"',
                ),
            ),
        )


FIXTURE_MODELS = [DemoBaseFixture, DemoNamespaceFixture]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
