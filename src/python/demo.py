from iris_orm import IRISModel

class DemoModel(IRISModel):
    _iris_classname = "Demo.Test"

print("Getting existing object...")
existing = DemoModel.get(1)
print(existing.Foo)

demo = DemoModel(Foo="bar")
demo.save()
print(demo.pk)