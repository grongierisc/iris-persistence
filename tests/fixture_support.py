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


@dataclass(frozen=True)
class ObjectScriptFixtureSpec:
    name: str
    classnames: list[str]
    source_files: list[str]
    models: list[type]


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
    from iris_orm.runtime import get_runtime

    get_runtime()
    system_obj = iris.cls("%SYSTEM.OBJ")
    for classname in classnames:
        try:
            system_obj.Delete(classname, "-d")
        except Exception:
            pass


def _load_objectscript_fixture_spec(name: str) -> ObjectScriptFixtureSpec:
    cls_path = OBJECTSCRIPT_CLS_FIXTURES / f"{name}.cls"
    sidecar_path = OBJECTSCRIPT_PYTHON_FIXTURES / f"{name}.py"
    sidecar = load_module_from_path(sidecar_path)
    return ObjectScriptFixtureSpec(
        name=name,
        classnames=list(sidecar.FIXTURE_CLASSNAMES),
        source_files=list(getattr(sidecar, "FIXTURE_SOURCE_FILES", [cls_path.name])),
        models=list(sidecar.FIXTURE_MODELS),
    )


def load_objectscript_fixtures(names: list[str]) -> list[LoadedObjectScriptFixture]:
    import iris
    from iris_orm.runtime import get_runtime

    specs = [_load_objectscript_fixture_spec(name) for name in names]
    all_classnames = [classname for spec in specs for classname in spec.classnames]
    delete_iris_classes(all_classnames)

    try:
        get_runtime()
        system_obj = iris.cls("%SYSTEM.OBJ")
        status = system_obj.LoadDir(str(OBJECTSCRIPT_CLS_FIXTURES), "cuk")
        if not status:
            raise RuntimeError("failed to batch-load ObjectScript fixture sources")
        return [
            LoadedObjectScriptFixture(
                name=spec.name,
                classnames=spec.classnames,
                source=(
                    "cls"
                    if all(
                        iris.cls("%Dictionary.ClassDefinition")._ExistsId(classname)
                        for classname in spec.classnames
                    )
                    else "python"
                ),
            )
            for spec in specs
        ]
    except Exception:
        loaded: list[LoadedObjectScriptFixture] = []
        for spec in specs:
            for model_cls in spec.models:
                model_cls.sync_schema()
            loaded.append(
                LoadedObjectScriptFixture(
                    name=spec.name,
                    classnames=spec.classnames,
                    source="python",
                )
            )
        return loaded


def load_objectscript_fixture(name: str) -> LoadedObjectScriptFixture:
    from iris_orm.runtime import get_runtime

    spec = _load_objectscript_fixture_spec(name)
    classnames = spec.classnames
    source_files = spec.source_files

    delete_iris_classes(classnames)

    try:
        import iris

        get_runtime()
        system_obj = iris.cls("%SYSTEM.OBJ")
        for source_name in source_files:
            source_path = OBJECTSCRIPT_CLS_FIXTURES / source_name
            try:
                status = system_obj.Load(str(source_path), "cuk")
            except Exception:
                status = system_obj.LoadDir(str(source_path.parent), "cuk")
            if not status:
                raise RuntimeError(f"failed to load ObjectScript fixture source: {source_path}")
        missing = [
            classname
            for classname in classnames
            if not iris.cls("%Dictionary.ClassDefinition")._ExistsId(classname)
        ]
        if missing:
            raise RuntimeError(
                "missing compiled ObjectScript fixture classes: " + ", ".join(missing)
            )
        return LoadedObjectScriptFixture(name=name, classnames=classnames, source="cls")
    except Exception as e:
        print(f"Error loading ObjectScript fixture {name}: {e}")
        for model_cls in spec.models:
            model_cls.sync_schema()
        return LoadedObjectScriptFixture(name=name, classnames=classnames, source="python")
