"""Explicitly tune optimizer statistics on an existing IRIS storage definition."""

from __future__ import annotations

import argparse

from iris_persistence.advanced_storage import (
    StorageProperty,
    tune_existing_storage_statistics,
)


def tune_existing_class(classname: str, property_name: str) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("classname", help="Existing persistent IRIS class")
    parser.add_argument("property", help="Stored property whose optimizer statistics are tuned")
    args = parser.parse_args()
    tune_existing_class(args.classname, args.property)


if __name__ == "__main__":
    main()
