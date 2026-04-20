from __future__ import annotations

from typing import Annotated

from iris_orm import ClassMetadata, Field, IRISModel


class ClassMetadataRoundTripFixture(IRISModel):
    Title: str

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


class SQLProjectionRoundTripFixture(IRISModel):
    Title: str
    Tags: Annotated[
        list[str] | None,
        Field(
            iris_type="%List",
            sql_list_delimiter="|",
            sql_list_type="DELIMITED",
        ),
    ] = None
    TitleUpper: Annotated[
        str | None,
        Field(
            sql_compute_code="Set {*} = {Title}",
            sql_compute_on_change="Title",
            sql_computed=True,
        ),
    ] = None

    class Meta:
        classname = "Demo.SQLProjectionRoundTripFixture"
        mode = "replace"
