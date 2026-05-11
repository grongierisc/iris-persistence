from __future__ import annotations

from iris_persistence import Field, Model


class SourceRecursiveAddress(Model, serial=True):
    Street: str = Field(required=True, max_length=120)
    ZipCode: str | None = Field(default=None, max_length=12)
    Country: str | None = Field(default="FR", max_length=2)

    class Meta:
        classname = "Demo.SourceRecursiveAddress"
        mode = "replace"


FIXTURE_MODELS = [SourceRecursiveAddress]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
