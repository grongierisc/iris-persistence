# ruff: noqa: E402, I001
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iris_orm import Field, IRISModel

from examples.demo.support import configure_demo_runtime, maybe_sync_schema, unique_suffix


class DemoCustomer(IRISModel):
    Name: Annotated[str, Field(required=True, maxlen=120)]
    Tier: Annotated[str | None, Field(required=False, maxlen=20)] = None

    class Meta:
        classname = "Demo.ExampleDemoCustomer"
        mode = "replace"


class DemoAddress(IRISModel):
    Street: Annotated[str, Field(required=True, maxlen=120)]
    City: Annotated[str, Field(required=True, maxlen=80)]

    class Meta:
        classname = "Demo.ExampleDemoAddress"
        superclasses = "%Library.SerialObject"
        mode = "replace"


class DemoOrderLine(IRISModel):
    SKU: Annotated[str, Field(required=True, maxlen=40)]
    Qty: Annotated[int, Field(default=1)]

    class Meta:
        classname = "Demo.ExampleDemoOrderLine"
        superclasses = "%Library.SerialObject"
        mode = "replace"


class DemoOrder(IRISModel):
    OrderNumber: Annotated[str, Field(required=True, maxlen=40)]
    Customer: Annotated[DemoCustomer | None, Field(required=False)] = None
    ShipTo: Annotated[DemoAddress | None, Field(required=False)] = None
    Lines: Annotated[
        list[DemoOrderLine] | None,
        Field(iris_type="Demo.ExampleDemoOrderLine", collection="list"),
    ] = None
    LineLookup: Annotated[
        dict[str, DemoOrderLine] | None,
        Field(iris_type="Demo.ExampleDemoOrderLine", collection="array"),
    ] = None

    class Meta:
        classname = "Demo.ExampleDemoOrder"
        mode = "replace"


def run_demo(*, backend: str | None = None) -> dict[str, Any]:
    runtime_backend = configure_demo_runtime(backend)
    maybe_sync_schema(DemoCustomer, backend=runtime_backend)
    maybe_sync_schema(DemoAddress, backend=runtime_backend)
    maybe_sync_schema(DemoOrderLine, backend=runtime_backend)
    maybe_sync_schema(DemoOrder, backend=runtime_backend)

    order = DemoOrder(
        OrderNumber=unique_suffix("ORD"),
        Customer=DemoCustomer(Name="Acme Clinic", Tier="gold"),
        ShipTo=DemoAddress(Street="1 Main Street", City="Paris"),
        Lines=[
            DemoOrderLine(SKU="WIDGET-1", Qty=2),
            DemoOrderLine(SKU="WIDGET-2", Qty=1),
        ],
        LineLookup={
            "primary": DemoOrderLine(SKU="WIDGET-1", Qty=2),
            "bonus": DemoOrderLine(SKU="WIDGET-2", Qty=1),
        },
    )
    order.save()

    loaded = DemoOrder.get(order.pk)
    if loaded is None:
        raise RuntimeError("Unable to reload saved DemoOrder row")

    return {
        "backend": runtime_backend,
        "saved_pk": order.pk,
        "loaded": loaded,
        "matching": DemoOrder.where(OrderNumber=order.OrderNumber).all(),
    }


def main() -> None:
    result = run_demo()
    loaded = result["loaded"]
    print(f"Backend: {result['backend']}")
    print(f"Saved DemoOrder with pk={result['saved_pk']}")
    print(f"Customer: {loaded.Customer.Name} ({loaded.Customer.Tier})")
    print(f"ShipTo: {loaded.ShipTo.Street}, {loaded.ShipTo.City}")
    print(f"Lines: {[(line.SKU, line.Qty) for line in loaded.Lines]}")
    print(
        "Line lookup: "
        f"{ {key: (line.SKU, line.Qty) for key, line in loaded.LineLookup.items()} }"
    )
    print(f"Matching orders returned by query API: {len(result['matching'])}")


if __name__ == "__main__":
    main()
