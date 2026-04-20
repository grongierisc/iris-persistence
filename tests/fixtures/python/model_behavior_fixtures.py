from __future__ import annotations

from typing import Annotated

from iris_orm import ClassMetadata, Field, Index, IRISModel


class Product(IRISModel):
    Name: Annotated[str, Field(required=True, maxlen=200)]
    Price: Annotated[float, Field(default=0.0)]
    InStock: Annotated[bool, Field(default=True)]
    Docs: dict[str, str]
    Thumbnail: bytes

    class Meta:
        classname = "Demo.Product"
        mode = "replace"
        indexes = [Index("NameIdx", properties="Name", unique=True)]


class QueryAliasModel(IRISModel):
    Payload: Annotated[str | None, Field(sql_field_name="payload_json")] = None

    class Meta:
        classname = "Demo.QueryAliasModel"
        mode = "observe"


class ReadonlyModel(IRISModel):
    Code: Annotated[str | None, Field(readonly=True)] = None
    Name: Annotated[str | None, Field()] = None

    class Meta:
        classname = "Demo.ReadonlyModel"
        mode = "replace"


class AutoSyncModel(IRISModel):
    Name: Annotated[str | None, Field()] = None

    class Meta:
        classname = "Demo.AutoSyncModel"
        mode = "extend"
        auto_sync = True


class ObserveAutoSyncModel(IRISModel):
    Name: Annotated[str | None, Field()] = None

    class Meta:
        classname = "Demo.ObserveAutoSyncModel"
        mode = "observe"
        auto_sync = True


class ReplaceAutoSyncModel(IRISModel):
    Name: Annotated[str | None, Field()] = None

    class Meta:
        classname = "Demo.ReplaceAutoSyncModel"
        mode = "replace"
        auto_sync = True


class FailingSaveModel(IRISModel):
    Name: Annotated[str | None, Field()] = None

    class Meta:
        classname = "Demo.FailingSaveModel"
        mode = "observe"


class ClassMetadataModel(IRISModel):
    Name: Annotated[str | None, Field()] = None

    class Meta:
        classname = "Demo.ClassMetadataModel"
        metadata = ClassMetadata(
            description="class-level description",
            deprecated=True,
            final=True,
            sql_table_name="Demo_ClassMetadataModel",
            procedure_block=True,
        )
