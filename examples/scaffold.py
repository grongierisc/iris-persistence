from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iris_orm import scaffold_from_cls, scaffold_from_iris


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generated_root = project_root / "generated_models"

    try:
        print("\nScaffold typed proxy models from live IRIS:")
        iris_paths = scaffold_from_iris("Demo.*", generated_root / "from_iris", style="proxy")
        for path in iris_paths:
            print(" ", path)
    except Exception as exc:
        print(" live IRIS scaffold skipped:", exc)


if __name__ == "__main__":
    main()
