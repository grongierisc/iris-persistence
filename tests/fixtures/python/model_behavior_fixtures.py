from __future__ import annotations

from iris_persistence import ClassMetadata, Field, Model


class Product(Model, persistent=True):
    Name: str = Field(required=True, max_length=200, unique=True)
    Price: float = 0.0
    InStock: bool = True
    Docs: dict[str, str]
    Thumbnail: bytes

    class Meta:
        classname = "Demo.Product"
        mode = "managed"


class QueryAliasModel(Model):
    Payload: str | None = Field(default=None, sql_field_name="payload_json")

    class Meta:
        classname = "Demo.QueryAliasModel"
        mode = "observe"


class ReadonlyModel(Model, persistent=True):
    Code: str | None = Field(default=None, readonly=True)
    Name: str | None = None

    class Meta:
        classname = "Demo.ReadonlyModel"
        mode = "managed"


class AutoSyncModel(Model, persistent=True):
    Name: str | None = None

    class Meta:
        classname = "Demo.AutoSyncModel"
        mode = "managed"
        auto_sync = True


class ObserveAutoSyncModel(Model):
    Name: str | None = None

    class Meta:
        classname = "Demo.ObserveAutoSyncModel"
        mode = "observe"
        auto_sync = True


class ManagedAutoSyncModel(Model, persistent=True):
    Name: str | None = None

    class Meta:
        classname = "Demo.ManagedAutoSyncModel"
        mode = "managed"
        auto_sync = True


class FailingSaveModel(Model):
    Name: str | None = None

    class Meta:
        classname = "Demo.FailingSaveModel"
        mode = "observe"


class ClassMetadataModel(Model, persistent=True):
    Name: str | None = None

    class Meta:
        classname = "Demo.ClassMetadataModel"
        metadata = ClassMetadata(
            description="class-level description",
            deprecated=True,
            final=True,
            sql_table_name="Demo_ClassMetadataModel",
            procedure_block=True,
        )
