from __future__ import annotations

from pathlib import Path

from iris_orm import scaffold_from_cls, scaffold_from_iris


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generated_root = project_root / "generated_models"

    print("Scaffold typed proxy models from exported .cls files:")
    cls_paths = scaffold_from_cls(project_root / "cls", generated_root / "from_cls", style="proxy")
    for path in cls_paths:
        print(" ", path)

    print("\nScaffold python-first starting points from exported .cls files:")
    python_paths = scaffold_from_cls(project_root / "cls", generated_root / "from_cls_python", style="python")
    for path in python_paths:
        print(" ", path)

    try:
        print("\nScaffold typed proxy models from live IRIS:")
        iris_paths = scaffold_from_iris("Demo.*", generated_root / "from_iris", style="proxy")
        for path in iris_paths:
            print(" ", path)
    except Exception as exc:
        print(" live IRIS scaffold skipped:", exc)


if __name__ == "__main__":
    main()
