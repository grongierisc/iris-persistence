# ruff: noqa: E402, I001
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iris_orm import Field, IRISModel, scaffold_from_iris

from examples.demo.support import (
    configure_demo_runtime,
    load_module,
    maybe_sync_schema,
    output_dir,
    unique_suffix,
)


class ExampleScaffoldCustomer(IRISModel):
    Name: Annotated[str, Field(required=True, maxlen=120)]

    class Meta:
        classname = "Demo.ExampleScaffoldCustomer"
        mode = "replace"


class ExampleScaffoldAddress(IRISModel):
    Street: Annotated[str, Field(required=True, maxlen=120)]
    City: Annotated[str, Field(required=True, maxlen=80)]

    class Meta:
        classname = "Demo.ExampleScaffoldAddress"
        superclasses = "%Library.SerialObject"
        mode = "replace"


class ExampleScaffoldOrder(IRISModel):
    OrderNumber: Annotated[str, Field(required=True, maxlen=40)]
    Customer: Annotated[ExampleScaffoldCustomer | None, Field(required=False)] = None
    ShipTo: Annotated[ExampleScaffoldAddress | None, Field(required=False)] = None
    Tags: Annotated[list[str] | None, Field(iris_type="%List")] = None

    class Meta:
        classname = "Demo.ExampleScaffoldOrder"
        mode = "replace"


def run_demo(*, backend: str | None = None) -> dict[str, Any]:
    runtime_backend = configure_demo_runtime(backend)
    if runtime_backend == "fake":
        return {
            "backend": runtime_backend,
            "skipped": True,
            "reason": "scaffold_from_iris needs live IRIS dictionary access",
        }

    maybe_sync_schema(ExampleScaffoldCustomer, backend=runtime_backend)
    maybe_sync_schema(ExampleScaffoldAddress, backend=runtime_backend)
    maybe_sync_schema(ExampleScaffoldOrder, backend=runtime_backend)

    source = ExampleScaffoldOrder(
        OrderNumber=unique_suffix("SCAFFOLD"),
        Customer=ExampleScaffoldCustomer(Name="Northwind"),
        ShipTo=ExampleScaffoldAddress(Street="42 Rue de Demo", City="Paris"),
        Tags=["generated", "observe"],
    )
    source.save()

    generated_root = output_dir("examples_demo_scaffold")
    generated_files = scaffold_from_iris(
        "Demo.ExampleScaffoldOrder",
        str(generated_root),
        mode="observe",
        extract_meta=True,
        include_related=True,
    )

    order_path = next(
        Path(path)
        for path in generated_files
        if Path(path).stem == "examplescaffoldorder"
    )
    module = load_module(order_path)
    scaffolded_cls = module.ExampleScaffoldOrder

    loaded = scaffolded_cls.get(source.pk)
    if loaded is None:
        raise RuntimeError("Unable to load row through scaffolded observe model")

    return {
        "backend": runtime_backend,
        "skipped": False,
        "saved_pk": source.pk,
        "generated_files": generated_files,
        "loaded": loaded,
        "matching": scaffolded_cls.where(OrderNumber=source.OrderNumber).all(),
    }


def main() -> None:
    result = run_demo()
    print(f"Backend: {result['backend']}")
    if result["skipped"]:
        print(f"Skipped: {result['reason']}")
        return

    loaded = result["loaded"]
    print(f"Saved source row with pk={result['saved_pk']}")
    print(f"Generated files: {result['generated_files']}")
    print(
        "Scaffolded observe model loaded: "
        f"OrderNumber={loaded.OrderNumber}, Customer={loaded.Customer.Name}, "
        f"ShipTo={loaded.ShipTo.City}, Tags={loaded.Tags}"
    )
    print(f"Matching rows returned by scaffolded query API: {len(result['matching'])}")


if __name__ == "__main__":
    main()
