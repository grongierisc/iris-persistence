"""
01_existing_class.py — Convenience binding to an existing IRIS class.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm import bind_existing


def main() -> None:
    Article = bind_existing("Demo.Article")
    Article.bind()

    print("Bound existing class:", Article._iris_classname)
    print("Known fields:", [item.name for item in Article._iris_bound_schema.properties])

    first = Article.query().limit(1).first()
    if first is not None:
        print("First row id:", first.pk)


if __name__ == "__main__":
    main()
