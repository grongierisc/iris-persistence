"""
01_existing_class.py — Explicit binding to an existing IRIS class.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm import Binder, IRISAdapter, Registry, Session


def main() -> None:
    registry = Registry()
    Article = registry.bind_existing("Demo.Article")

    adapter = IRISAdapter()
    binder = Binder(registry, adapter)
    binder.bind_all()
    session = Session(binder, adapter)

    print("Bound existing class:", Article._iris_classname)
    print("Known fields:", [item.name for item in binder.schema_for(Article).properties])

    first = session.query(Article).limit(1).first()
    if first is not None:
        print("First row id:", first.pk)


if __name__ == "__main__":
    main()
