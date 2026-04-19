from __future__ import annotations

from typing import Annotated

from iris_orm import Field, IRISModel


class SourceRecursiveAddress(IRISModel):
    Street: Annotated[str, Field(required=True, maxlen=120)]
    ZipCode: Annotated[str | None, Field(required=False, maxlen=12)] = None
    Country: Annotated[str | None, Field(required=False, default="FR", maxlen=2)] = "FR"

    class Meta:
        classname = "Demo.SourceRecursiveAddress"
        superclasses = "%Library.SerialObject"
        mode = "replace"


FIXTURE_MODELS = [SourceRecursiveAddress]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
