# ruff: noqa: E402, I001
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iris_orm import IRISModel

from examples.demo.support import configure_demo_runtime, maybe_sync_schema


class HelloRecord(IRISModel):
    Message: str

    class Meta:
        classname = "Demo.ExampleHelloRecord"
        mode = "extend"


def run_demo(*, backend: str | None = None) -> dict[str, Any]:
    runtime_backend = configure_demo_runtime(backend)
    maybe_sync_schema(HelloRecord, backend=runtime_backend)

    row = HelloRecord(Message="Hello from iris_orm")
    row.save()

    loaded = HelloRecord.get(row.pk)
    if loaded is None:
        raise RuntimeError("Unable to reload saved HelloRecord row")

    return {
        "backend": runtime_backend,
        "saved_pk": row.pk,
        "loaded": loaded,
        "all_rows": list(HelloRecord.all()),
    }


def main() -> None:
    result = run_demo()
    print(f"Backend: {result['backend']}")
    print(f"Saved HelloRecord with pk={result['saved_pk']}")
    print(f"Loaded row: {result['loaded']}")
    print(f"Total rows visible through ORM: {len(result['all_rows'])}")


if __name__ == "__main__":
    main()
