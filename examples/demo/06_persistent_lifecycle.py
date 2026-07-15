# ruff: noqa: E402, I001
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iris_persistence import Field, Index, Model, apply_plan, create_plan, verify_plan

from examples.demo.support import configure_demo_runtime, unique_suffix


CLASSNAME = "Demo.ExamplePersonLifecycle"


class PersonV1(Model, persistent=True):
    Name: str = Field(required=True, max_length=120)
    Age: int | None = None

    class Meta:
        classname = CLASSNAME
        mode = "managed"
        indexes = [Index("NameIdx", properties="Name")]
        # Prefer compiler parameters over an explicit Storage block.
        parameters = {"DEFAULTGLOBAL": "^Demo.ExamplePersonLifecycleD"}


class PersonV2(Model, persistent=True):
    Name: str = Field(required=True, max_length=120)
    Age: int | None = None
    Email: str | None = Field(default=None, max_length=200)

    class Meta:
        classname = CLASSNAME
        mode = "managed"
        indexes = [
            Index("NameIdx", properties="Name"),
            Index("EmailIdx", properties="Email"),
        ]
        parameters = {"DEFAULTGLOBAL": "^Demo.ExamplePersonLifecycleD"}


def run_demo(*, backend: str | None = None) -> dict[str, Any]:
    runtime_backend = configure_demo_runtime(backend)

    # 1. Create the first class version. IRIS generates Storage Default on compile.
    if runtime_backend != "fake":
        PersonV1.sync_schema()

    # 2. Create and save an object.
    name = unique_suffix("Ada")
    person = PersonV1(Name=name, Age=36)
    person.save()
    if person.pk is None:
        raise RuntimeError("PersonV1 was saved without an ID")
    person_id = person.pk

    # 3. Load, modify, and save the same persistent object.
    loaded = PersonV1.get(person_id)
    if loaded is None:
        raise RuntimeError("Unable to reload PersonV1")
    loaded.Age = 37
    loaded.save()

    # 4. Evolve Python-owned members without rebuilding the class or storage.
    migration_status = "skipped on fake backend"
    migration_verified = False
    if runtime_backend != "fake":
        plan = create_plan([PersonV2], target_revision="person-v2")
        migration_status = apply_plan(plan).status
        migration_verified = verify_plan(plan).converged

    evolved = PersonV2.get(person_id)
    if evolved is None:
        raise RuntimeError("Unable to reload PersonV2")
    evolved.Email = f"{name.lower()}@example.com"
    evolved.save()

    # 5. Query through IRIS SQL projection.
    matches = PersonV2.where(Name=name).order_by("Name").all()

    # 6. Delete the persistent object.
    deleted = evolved.delete()
    missing_after_delete = PersonV2.get(person_id) is None

    return {
        "backend": runtime_backend,
        "person_id": person_id,
        "updated_age": evolved.Age,
        "email": evolved.Email,
        "matches_before_delete": len(matches),
        "migration_status": migration_status,
        "migration_verified": migration_verified,
        "deleted": deleted,
        "missing_after_delete": missing_after_delete,
    }


def main() -> None:
    result = run_demo()
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
