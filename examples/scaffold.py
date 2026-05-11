from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iris_persistence import scaffold_from_iris


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generated_root = project_root / "generated_models"

    try:
        print("\nScaffold typed proxy models from live IRIS:")
        iris_paths = scaffold_from_iris(
            "User.Simple",
            generated_root / "from_iris",
            mode="observe",
            extract_meta=True,
            include_related=True,
            scaffold_selectivity=True,
            extract_hidden_meta=True,
        )
        # scaffold HS.FHIRServer.Interop.Request
        # scaffold_from_iris(
        #     "HS.FHIRServer.Interop.Request",
        #     generated_root / "from_iris",
        #     mode="observe",
        #     extract_meta=True,
        #     include_related=True,
        # )
        # for path in iris_paths:
        #     print(" ", path)
    except Exception as exc:
        print(" live IRIS scaffold skipped:", exc)


if __name__ == "__main__":
    main()
