from __future__ import annotations

from iris_orm import ClassMetadata, Field, Model


class ClassMetadataRoundTripFixture(Model, persistent=True):
    Title: str = Field(required=True)

    class Meta:
        classname = "Demo.ClassMetadataRoundTripFixture"
        mode = "replace"
        metadata = ClassMetadata(
            description="round-trip class metadata",
            deprecated=True,
            final=True,
            sql_table_name="Demo_ClassMetadataRoundTripFixture",
            procedure_block=True,
        )


class SQLProjectionRoundTripFixture(Model, persistent=True):
    Title: str = Field(required=True)
    Tags: list[str] | None = Field(
        default=None,
        iris_type="%List",
        sql_list_delimiter="|",
        sql_list_type="DELIMITED",
    )
    TitleUpper: str | None = Field(
        default=None,
        sql_compute_code="Set {*} = {Title}",
        sql_compute_on_change="Title",
        sql_computed=True,
    )

    class Meta:
        classname = "Demo.SQLProjectionRoundTripFixture"
        mode = "replace"
