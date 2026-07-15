from __future__ import annotations

from iris_persistence import Field, Model


class SourceRequestFixture(Model):
    CorrelationId: str = Field(required=True, max_length=64)
    RetryCount: int | None = 0
    SourceSystem: str | None = Field(default="ERP", max_length=32)

    class Meta:
        classname = "Demo.SourceRequestFixture"
        superclasses = "Ens.Request"
        mode = "managed"


FIXTURE_MODELS = [SourceRequestFixture]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
