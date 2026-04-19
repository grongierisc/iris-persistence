from __future__ import annotations

from typing import Annotated

from iris_orm import Field, Index, IRISModel


class SourcePersistentFixture(IRISModel):
    Title: Annotated[str, Field(required=True, maxlen=120)]
    Enabled: Annotated[bool | None, Field(required=False, default=True)] = True
    Score: Annotated[int | None, Field(required=False, default=3)] = 3

    class Meta:
        classname = "Demo.SourcePersistentFixture"
        superclasses = "%Library.Persistent"
        mode = "replace"
        indexes = [Index("TitleIdx", properties="Title")]


FIXTURE_MODELS = [SourcePersistentFixture]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
