"""Explicitly tune optimizer statistics on an existing IRIS storage definition."""

from __future__ import annotations

import argparse

from iris_persistence.advanced_storage import (
    StorageProperty,
    inspect_existing_storage,
    tune_existing_storage_statistics,
)


def tune_existing_class(classname: str, property_name: str) -> None:
    before = inspect_existing_storage(classname)
    print(f"Existing storage for {classname}||{before}")
    previous = {item.name: item for item in before.properties}.get(property_name)
    print(f"Before: selectivity={getattr(previous, 'selectivity', None)}")

    result = tune_existing_storage_statistics(
        classname,
        properties=(
            StorageProperty(
                name=property_name,
                average_field_size="32",
                selectivity="5.0000%",
                outlier_selectivity='.999999:"UNKNOWN"',
            ),
        ),
    )
    print(
        f"Updated {', '.join(result.updated_properties)} on "
        f"{result.classname}||{result.storage_name}"
    )
    after = inspect_existing_storage(classname)
    current = {item.name: item for item in after.properties}[property_name]
    print(f"After: selectivity={current.selectivity}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("classname", help="Existing persistent IRIS class")
    parser.add_argument("property", help="Stored property whose optimizer statistics are tuned")
    args = parser.parse_args()
    tune_existing_class(args.classname, args.property)


if __name__ == "__main__":
    main()
