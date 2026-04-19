from iris_orm.scaffold import scaffold_from_iris
from iris_orm.runtime import configure_default_runtime, NativeProxyAdapter
import os
import pytest
import datetime
import iris_orm
from typing import Annotated
from iris_orm import IRISModel, Field, Index, StorageDefinition, StorageData

iris_orm.configure()

class FullFixture(IRISModel):
    Title: Annotated[str, Field(required=True, maxlen=350)]
    Description: Annotated[str | None, Field(required=False, default="No desc", maxlen=500)] = "No desc"
    Price: Annotated[float | None, Field(required=False, default=15.5)] = 15.5
    IsActive: Annotated[bool | None, Field(required=False, default=True)] = True
    Count: Annotated[int | None, Field(required=False, default=42)] = 42
    Data: Annotated[dict | None, Field(required=False)] = None
    Tags: Annotated[list | None, Field(required=False)] = None
    CreatedAt: Annotated[datetime.datetime | None, Field(required=False)] = None

    class Meta:
        classname = "Demo.FullFixture"
        mode = "replace"
        indexes = [
            Index("TitleIdx", properties="Title")
        ]
        storage = StorageDefinition(
            data_location="^Demo.FullFixtureD",
            default_data="FullFixtureDefaultData",
            type="%Storage.Persistent",
            data=(
                StorageData(
                    name="FullFixtureDefaultData",
                    structure="listnode",
                    values={'1': '%%CLASSNAME', '2': 'Count', '3': 'CreatedAt', '4': 'Description', '5': 'IsActive', '6': 'Price', '7': 'Title'}
                ),
            ),
        )

def test_full_circle():
    # Use real NativeProxyAdapter for the test
    configure_default_runtime(NativeProxyAdapter())
    
    print("Syncing FullFixture to IRIS...")
    FullFixture.sync_schema()
    
    print("Scaffolding FullFixture from IRIS...")
    scaffold_from_iris("Demo.FullFixture", "generated_test", extract_meta=True)
    
    with open("generated_test/fullfixture.py", "r") as f:
        res = f.read()
    
    print("\n--- Scaffolded Code ---")
    print(res)
    
    assert "Title: Annotated[str, Field(required=True, maxlen=350)]" in res
    assert 'Description: Annotated[str | None, Field(required=False, maxlen=500, default="No desc")] = "No desc"' in res
    assert "Price: Annotated[float | None, Field(required=False, default=15.5)] = 15.5" in res
    assert "IsActive: Annotated[bool | None, Field(required=False, default=True)] = True" in res
    assert "Count: Annotated[int | None, Field(required=False, default=42)] = 42" in res
    assert "Data: Annotated[dict | None, Field(required=False)]" in res
    assert "Tags: Annotated[list | None, Field(required=False)]" in res
    assert "CreatedAt: Annotated[datetime.datetime | None, Field(required=False)]" in res
    
    assert 'Index("TitleIdx", properties="Title"' in res
    
    assert 'StorageData(' in res


