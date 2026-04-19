from __future__ import annotations

from typing import Annotated

from iris_orm import Field, IRISModel


class SourceRecursiveChild(IRISModel):
    Name: Annotated[str, Field(required=True, maxlen=80)]
    Importance: Annotated[int | None, Field(required=False, default=5)] = 5

    class Meta:
        classname = "Demo.SourceRecursiveChild"
        superclasses = "%Library.Persistent"
        mode = "replace"


FIXTURE_MODELS = [SourceRecursiveChild]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
