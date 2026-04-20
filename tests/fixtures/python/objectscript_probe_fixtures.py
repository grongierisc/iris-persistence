from __future__ import annotations

from iris_orm import IRISModel


class DemoProductProbe(IRISModel):
    class Meta:
        classname = "Demo.Product"
        mode = "observe"
