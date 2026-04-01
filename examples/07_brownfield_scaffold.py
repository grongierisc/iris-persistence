"""
07_brownfield_scaffold.py — Generate Python models from IRIS or .cls input.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm.scaffold import scaffold_from_cls, scaffold_from_iris


def main() -> None:
    generated_root = PROJECT_ROOT / "generated_models"

    try:
        iris_paths = scaffold_from_iris("Demo.*", generated_root, style="proxy")
        print("Scaffolded typed proxy from IRIS:")
        for path in iris_paths:
            print(" ", path)
    except Exception as exc:
        print("Live IRIS scaffold skipped:", exc)

    cls_root = PROJECT_ROOT / "output" / "cls"
    if cls_root.exists():
        cls_paths = scaffold_from_cls(cls_root, generated_root)
        print("Scaffolded from .cls:")
        for path in cls_paths:
            print(" ", path)


if __name__ == "__main__":
    main()
