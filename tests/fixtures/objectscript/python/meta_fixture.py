from __future__ import annotations

from iris_persistence import ClassMetadata, Field, Model


class SourceMetaFixture(Model, persistent=True):
    Title: str = Field(required=True, max_length=120)

    class Meta:
        classname = "Demo.SourceMetaFixture"
        mode = "managed"
        metadata = ClassMetadata(
            deprecated=True,
            final=True,
            sql_table_name="SourceMetaFixtureTable",
            procedure_block=True,
        )


FIXTURE_MODELS = [SourceMetaFixture]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
