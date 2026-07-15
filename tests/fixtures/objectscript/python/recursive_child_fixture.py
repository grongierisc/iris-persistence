from __future__ import annotations

from iris_persistence import Field, Model


class SourceRecursiveChild(Model, persistent=True):
    Name: str = Field(required=True, max_length=80)
    Importance: int | None = 5

    class Meta:
        classname = "Demo.SourceRecursiveChild"
        mode = "managed"


FIXTURE_MODELS = [SourceRecursiveChild]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
