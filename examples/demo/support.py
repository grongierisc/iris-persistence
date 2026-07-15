# ruff: noqa: E402
from __future__ import annotations

import importlib.util
import os
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import iris_persistence
from iris_persistence.runtime import install_runtime
from iris_persistence.testing import InMemoryAdapter


def configure_demo_runtime(backend: str | None = None) -> str:
    selected = (backend or os.environ.get("IRIS_DEMO_BACKEND", "auto")).strip().lower()

    if selected == "fake":
        install_runtime(InMemoryAdapter())
        return "fake"

    if selected == "remote":
        import iris

        host = os.environ.get("IRIS_HOST", "localhost")
        port = int(os.environ.get("IRIS_PORT", "1972"))
        namespace = os.environ.get("IRIS_NAMESPACE", "IRISAPP")
        username = os.environ.get("IRISUSERNAME")
        password = os.environ.get("IRISPASSWORD")
        if not username or not password:
            raise RuntimeError(
                "Remote demos require IRISUSERNAME and IRISPASSWORD in the environment."
            )
        connection = iris.connect(host, port, namespace, username, password)
        iris_persistence.configure_runtime(
            iris_persistence.RuntimeConfig(native_connection=connection)
        )
        return "remote"

    if selected not in {"auto", "embedded"}:
        raise ValueError(
            "backend must be one of: auto, embedded, remote, fake"
        )

    try:
        iris_persistence.configure_runtime()
        import iris

        return str(getattr(iris.runtime, "mode", "embedded"))
    except Exception:
        if selected != "auto":
            raise
        install_runtime(InMemoryAdapter())
        return "fake"


def maybe_sync_schema(*models: type[Any], backend: str) -> None:
    if backend == "fake":
        return
    for model in models:
        model.sync_schema()


def unique_suffix(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def load_module(module_path: Path) -> ModuleType:
    if str(module_path.parent) not in sys.path:
        sys.path.insert(0, str(module_path.parent))

    module_name = f"demo_{module_path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def output_dir(name: str) -> Path:
    target = REPO_ROOT / "output" / name
    target.mkdir(parents=True, exist_ok=True)
    return target
