from __future__ import annotations

from iris_persistence import Field, Model


class SourcePersistentFixture(Model, persistent=True):
    Title: str = Field(required=True, max_length=120, index=True)
    Enabled: bool | None = True
    Score: int | None = 3

    class Meta:
        classname = "Demo.SourcePersistentFixture"
        mode = "replace"


FIXTURE_MODELS = [SourcePersistentFixture]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
