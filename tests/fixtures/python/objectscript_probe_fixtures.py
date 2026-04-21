from __future__ import annotations

from iris_orm import Model


class DemoProductProbe(Model):
    class Meta:
        classname = "Demo.Product"
        mode = "observe"
