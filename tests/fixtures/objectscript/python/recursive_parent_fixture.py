from __future__ import annotations

from typing import Annotated

from iris_orm import Field, IRISModel
from tests.fixtures.objectscript.python.recursive_address_fixture import SourceRecursiveAddress
from tests.fixtures.objectscript.python.recursive_child_fixture import SourceRecursiveChild


class SourceRecursiveParent(IRISModel):
    Title: Annotated[str, Field(required=True, maxlen=120)]
    Child: Annotated[SourceRecursiveChild | None, Field(required=False)] = None
    Address: Annotated[SourceRecursiveAddress | None, Field(required=False)] = None

    class Meta:
        classname = "Demo.SourceRecursiveParent"
        superclasses = "%Library.Persistent"
        mode = "replace"


FIXTURE_MODELS = [SourceRecursiveParent]
FIXTURE_CLASSNAMES = [model._classname for model in FIXTURE_MODELS]
