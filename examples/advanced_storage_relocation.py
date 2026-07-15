"""Side-by-side physical storage relocation blueprint for a known model shape.

This intentionally creates a new class and copies through object APIs. It does not edit
the occupied source class's Storage Default or perform application cutover for you.
"""

from __future__ import annotations

import argparse

from iris_persistence import Field, Model, StorageTuning


class ExistingPerson(Model, persistent=True):
    Name: str = Field(required=True, max_length=120)
    Email: str | None = Field(default=None, max_length=200)

    class Meta:
        classname = "App.Person"
        mode = "observe"


class RelocatedPerson(Model, persistent=True):
    Name: str = Field(required=True, max_length=120)
    Email: str | None = Field(default=None, max_length=200)

    class Meta:
        classname = "App.PersonRelocated"
        mode = "managed"
        storage_tuning = StorageTuning(
            data_location="^App.Relocated.PersonD",
            id_location="^App.Relocated.PersonD",
            index_location="^App.Relocated.PersonI",
            stream_location="^App.Relocated.PersonS",
        )


def copy_to_relocated_class() -> dict[str, str]:
    """Copy rows and return an old-ID to new-ID map; source data remains untouched."""
    RelocatedPerson.sync_schema()
    id_map: dict[str, str] = {}
    source_rows = ExistingPerson.all()
    for source in source_rows:
        target = RelocatedPerson(Name=source.Name, Email=source.Email)
        target.save()
        if source.pk is None or target.pk is None:
            raise RuntimeError("A copied object is missing its persistent ID")
        id_map[source.pk] = target.pk

    if len(RelocatedPerson.all()) != len(source_rows):
        raise RuntimeError("Validation failed: source and target row counts differ")
    return id_map


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute-copy",
        action="store_true",
        help="Create the target class and copy all source objects",
    )
    args = parser.parse_args()
    if not args.execute_copy:
        print("Dry run only. Review class fields and locations, then pass --execute-copy.")
        return

    id_map = copy_to_relocated_class()
    print(f"Copied {len(id_map)} objects. Source class was not modified.")
    print("Validate references, streams, indexes, and application cutover before retiring source.")


if __name__ == "__main__":
    main()
