# ruff: noqa: E402, I001
from __future__ import annotations

import datetime
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iris_persistence import ClassMetadata, Field, Index, Model
from iris_persistence.advanced_storage import StorageData, StorageDefinition

from examples.demo.support import configure_demo_runtime, maybe_sync_schema, unique_suffix


class ShowcaseRecord(Model, persistent=True):
    Title: str = Field(required=True, max_length=350)
    Description: str | None = Field(default="No desc", max_length=500)
    Price: float | None = 15.5
    IsActive: bool | None = True
    BlobData: bytes | None = None
    Payload: dict | None = None
    Tags: list | None = None
    CreatedAt: datetime.datetime | None = None

    class Meta:
        classname = "Demo.ExampleShowcaseRecord"
        mode = "managed"
        indexes = [Index("TitleIdx", properties="Title")]
        parameters = {"DEFAULTGLOBAL": "^Demo.ExampleShowcaseRecordD"}
        metadata = ClassMetadata(
            description="advanced schema example",
            final=True,
            sql_table_name="Demo_ExampleShowcaseRecord",
            procedure_block=True,
        )
        custom_storage = StorageDefinition(
            data_location="^Demo.ExampleShowcaseRecordD",
            default_data="ExampleShowcaseRecordDefaultData",
            type="%Storage.Persistent",
            data=(
                StorageData(
                    name="ExampleShowcaseRecordDefaultData",
                    structure="listnode",
                    values={
                        "1": "%%CLASSNAME",
                        "2": "CreatedAt",
                        "3": "Description",
                        "4": "IsActive",
                        "5": "Price",
                        "6": "Title",
                    },
                ),
            ),
        )


def run_demo(*, backend: str | None = None) -> dict[str, Any]:
    runtime_backend = configure_demo_runtime(backend)
    maybe_sync_schema(ShowcaseRecord, backend=runtime_backend)

    title = unique_suffix("advanced")
    record = ShowcaseRecord(
        Title=title,
        Description="Replace-mode model with explicit storage metadata",
        Price=17.25,
        IsActive=False,
        BlobData=b"\x01\x02",
        Payload={"origin": "advanced-demo"},
        Tags=["metadata", "storage"],
        CreatedAt=datetime.datetime(2024, 1, 2, 3, 4, 5),
    )
    record.save()

    loaded = ShowcaseRecord.get(record.pk)
    if loaded is None:
        raise RuntimeError("Unable to reload saved ShowcaseRecord row")

    return {
        "backend": runtime_backend,
        "saved_pk": record.pk,
        "loaded": loaded,
        "storage": ShowcaseRecord._custom_storage,
        "metadata": ShowcaseRecord._class_metadata,
        "matching": ShowcaseRecord.where(Title=title).all(),
    }


def main() -> None:
    result = run_demo()
    loaded = result["loaded"]
    storage = result["storage"]
    metadata = result["metadata"]
    print(f"Backend: {result['backend']}")
    print(f"Saved ShowcaseRecord with pk={result['saved_pk']}")
    print(
        "Loaded row: "
        f"Title={loaded.Title}, Price={loaded.Price}, IsActive={loaded.IsActive}, "
        f"CreatedAt={loaded.CreatedAt}"
    )
    print(
        "Schema metadata: "
        f"description={metadata.description!r}, sql_table_name={metadata.sql_table_name!r}"
    )
    print(
        "Storage metadata: "
        f"data_location={storage.data_location!r}, default_data={storage.default_data!r}"
    )
    print(f"Matching rows returned by query API: {len(result['matching'])}")


if __name__ == "__main__":
    main()
