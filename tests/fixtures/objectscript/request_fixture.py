from __future__ import annotations

from typing import Annotated

from iris_orm import Field, IRISModel


class SourceRequestFixture(IRISModel):
    CorrelationId: Annotated[str, Field(required=True, maxlen=64)]
    RetryCount: Annotated[int | None, Field(required=False, default=0)] = 0
    SourceSystem: Annotated[str | None, Field(required=False, default="ERP", maxlen=32)] = "ERP"

    class Meta:
        classname = "Demo.SourceRequestFixture"
        superclasses = "Ens.Request"
        mode = "replace"


FIXTURE_MODELS = [SourceRequestFixture]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
