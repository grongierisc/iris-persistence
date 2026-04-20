from __future__ import annotations

from typing import Annotated

from iris_orm import ClassMetadata, Field, IRISModel


class SourceMetaFixture(IRISModel):
    Title: Annotated[str, Field(required=True, maxlen=120)]

    class Meta:
        classname = "Demo.SourceMetaFixture"
        superclasses = "%Library.Persistent"
        mode = "replace"
        metadata = ClassMetadata(
            deprecated=True,
            final=True,
            sql_table_name="SourceMetaFixtureTable",
            procedure_block=True,
        )


FIXTURE_MODELS = [SourceMetaFixture]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
