from __future__ import annotations

from iris_persistence import Field, Model
from iris_persistence.advanced_storage import StorageDefinition, StorageProperty


class DemoProductFixture(Model, persistent=True):
    Name: str = Field(required=True, max_length=200, unique=True)
    Price: float = 0.0
    InStock: bool = True
    Docs: dict[str, str]
    Thumbnail: bytes

    class Meta:
        classname = "Demo.Product"
        mode = "managed"
        custom_storage = StorageDefinition(
            extent_size="2",
            properties=(
                StorageProperty(
                    name="InStock",
                    outlier_selectivity=".999999:1",
                ),
                StorageProperty(
                    name="Name",
                    outlier_selectivity='.999999:"Widget"',
                ),
                StorageProperty(
                    name="Price",
                    outlier_selectivity=".999999:12.5",
                ),
            ),
        )


FIXTURE_MODELS = [DemoProductFixture]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
