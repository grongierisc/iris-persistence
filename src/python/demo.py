"""
Quick demo — see src/python/examples/ for full examples.
"""
from iris_orm import IRISModel

class DemoModel(IRISModel):
    _iris_classname = "Demo.Test"

demo = DemoModel(Foo="bar")
demo.save()
print(f"pk={demo.pk}  Foo={demo.Foo!r}  Bar={demo.Bar}")
demo.delete()
