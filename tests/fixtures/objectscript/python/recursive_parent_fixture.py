from __future__ import annotations

from iris_persistence import Field, Model
from tests.fixtures.objectscript.python.recursive_address_fixture import SourceRecursiveAddress
from tests.fixtures.objectscript.python.recursive_child_fixture import SourceRecursiveChild


class SourceRecursiveParent(Model, persistent=True):
    Title: str = Field(required=True, max_length=120)
    Child: SourceRecursiveChild | None = None
    Address: SourceRecursiveAddress | None = None

    class Meta:
        classname = "Demo.SourceRecursiveParent"
        mode = "managed"


FIXTURE_MODELS = [SourceRecursiveParent]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
