from __future__ import annotations

import importlib.util
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

FIXTURES_ROOT = Path(__file__).parent / "fixtures"
OBJECTSCRIPT_FIXTURES = FIXTURES_ROOT / "objectscript"
OBJECTSCRIPT_CLS_FIXTURES = OBJECTSCRIPT_FIXTURES / "cls"
OBJECTSCRIPT_PYTHON_FIXTURES = OBJECTSCRIPT_FIXTURES / "python"
PYTHON_FIXTURES = FIXTURES_ROOT / "python"


@dataclass(frozen=True)
class LoadedObjectScriptFixture:
    name: str
    classnames: list[str]
    source: str


def load_module_from_path(module_path: Path) -> ModuleType:
    module_name = f"fixture_{module_path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def delete_iris_classes(classnames: list[str]) -> None:
    import iris

    iris.runtime.configure()
    system_obj = iris.cls("%SYSTEM.OBJ")
    for classname in classnames:
        try:
            system_obj.Delete(classname, "-d")
        except Exception:
            pass


def load_objectscript_fixture(name: str) -> LoadedObjectScriptFixture:
    cls_path = OBJECTSCRIPT_CLS_FIXTURES / f"{name}.cls"
    sidecar_path = OBJECTSCRIPT_PYTHON_FIXTURES / f"{name}.py"
    sidecar = load_module_from_path(sidecar_path)
    classnames = list(sidecar.FIXTURE_CLASSNAMES)

    delete_iris_classes(classnames)

    try:
        import iris

        iris.runtime.configure()
        iris.cls("%SYSTEM.OBJ").LoadDir(str(cls_path.parent), "uk")
        for classname in classnames:
            iris.cls("%SYSTEM.OBJ").Compile(classname, "cb")
        return LoadedObjectScriptFixture(name=name, classnames=classnames, source="cls")
    except Exception as e:
        print(f"Error loading ObjectScript fixture {name}: {e}")
        for model_cls in sidecar.FIXTURE_MODELS:
            model_cls.sync_schema()
        return LoadedObjectScriptFixture(name=name, classnames=classnames, source="python")
