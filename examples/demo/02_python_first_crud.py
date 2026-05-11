# ruff: noqa: E402, I001
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iris_persistence import Field, Model
from iris_persistence.runtime import get_runtime

from examples.demo.support import configure_demo_runtime, maybe_sync_schema, unique_suffix


class ProductDemo(Model, persistent=True):
    Name: str = Field(required=True, max_length=200, unique=True)
    Price: Annotated[float, Field(default=0.0)]
    InStock: bool = True
    Payload: dict[str, str] | None = None
    Bytes: bytes | None = None
    Tags: list[str] = Field(default_factory=list, iris_type="%List")

    class Meta:
        classname = "Demo.Demo"
        mode = "extend"
        parameters = {"OWNER": "examples/demo"}


def run_demo(*, backend: str | None = None) -> dict[str, Any]:
    runtime_backend = configure_demo_runtime(backend)
    maybe_sync_schema(ProductDemo, backend=runtime_backend)

    name = unique_suffix("widget")
    product = ProductDemo(
        Name=name,
        Price=12.5,
        InStock=True,
        Payload={"origin": "python-first"},
        Bytes=b"\x00\x01\x02",
        Tags=["demo", "crud"],
    )
    product.save()

    loaded = ProductDemo.get(product.pk)
    if loaded is None:
        raise RuntimeError("Unable to reload saved ProductDemo row")

    matching = ProductDemo.where(Name=name).order_by("Name").all()
    runtime = get_runtime()

    return {
        "backend": runtime_backend,
        "saved_pk": product.pk,
        "loaded": loaded,
        "matching": matching,
        "last_sql": getattr(runtime, "last_sql", None),
    }


def main() -> None:
    result = run_demo()
    loaded = result["loaded"]
    print(f"Backend: {result['backend']}")
    print(f"Saved ProductDemo with pk={result['saved_pk']}")
    print(
        "Loaded row: "
        f"Name={loaded.Name}, Price={loaded.Price}, InStock={loaded.InStock}, "
        f"Tags={loaded.Tags}, Payload={loaded.Payload}"
    )
    print(f"Matching rows returned by query API: {len(result['matching'])}")
    if result["last_sql"]:
        print(f"SQL built by QuerySet: {result['last_sql']}")


if __name__ == "__main__":
    main()
