import pytest
from typing import Annotated

from iris_orm import Field, IRISModel, Index, configure, StorageDefinition
from iris_orm.testing import FakeAdapter
from iris_orm.runtime import configure_default_runtime

@pytest.fixture(autouse=True)
def setup_fake_backend():
    adapter = FakeAdapter()
    configure_default_runtime(adapter)

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

def test_save_and_get():
    p = Product(Name="Widget", Price=12.5, InStock=True, Docs={"key": "value"}, Thumbnail=b"bytes")
    p.save()
    
    assert p.pk is not None
    
    p2 = Product.get(p.pk)
    assert p2 is not None
    assert p2.Name == "Widget"
    assert p2.Price == 12.5
    assert p2.InStock is True
    assert p2.Docs == {"key": "value"}
    assert p2.Thumbnail == b"bytes"

def test_query_all():
    p1 = Product(Name="A", Price=1)
    p2 = Product(Name="B", Price=2)
    p1.save()
    p2.save()
    
    products = list(Product.all())
    assert len(products) >= 2
    names = [x.Name for x in products]
    assert "A" in names
    assert "B" in names
