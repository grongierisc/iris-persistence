from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iris_persistence.scaffold import scaffold_from_iris


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    generated_root = project_root / "generated_models"

    try:
        print("\nScaffold typed proxy models from live IRIS:")
        for path in scaffold_from_iris(
            "User.Simple",
            generated_root / "from_iris",
            mode="managed",
            extract_meta=True,
            include_related=True,
            storage="custom",
        ):
            print(" ", path)
        # scaffold HS.FHIRServer.Interop.Request
        # scaffold_from_iris(
        #     "HS.FHIRServer.Interop.Request",
        #     generated_root / "from_iris",
        #     mode="observe",
        #     extract_meta=True,
        #     include_related=True,
        # )
    except Exception as exc:
        print(" live IRIS scaffold skipped:", exc)


if __name__ == "__main__":
    main()
