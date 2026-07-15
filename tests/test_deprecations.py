from __future__ import annotations

import subprocess
import sys
import warnings

import pytest

import iris_persistence
from iris_persistence import migrations, scaffold

SECONDARY_ROOT_EXPORTS = {
    "ApplyResult": migrations.ApplyResult,
    "BackupRestoreError": migrations.BackupRestoreError,
    "MigrationOperation": migrations.MigrationOperation,
    "MigrationPlan": migrations.MigrationPlan,
    "RollbackResult": migrations.RollbackResult,
    "VerifyResult": migrations.VerifyResult,
    "apply_plan": migrations.apply_plan,
    "check_drift": migrations.check_drift,
    "create_plan": migrations.create_plan,
    "rollback_backup": migrations.rollback_backup,
    "verify_plan": migrations.verify_plan,
    "ScaffoldResult": scaffold.ScaffoldResult,
    "ScaffoldWarning": scaffold.ScaffoldWarning,
    "scaffold_from_iris": scaffold.scaffold_from_iris,
}


def _deprecated_call(call):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = call()
    assert len(caught) == 1
    assert caught[0].category is DeprecationWarning
    assert caught[0].filename == __file__
    return result


def test_root_configure_is_removed():
    assert not hasattr(iris_persistence, "configure")


def test_root_all_contains_only_core_product_surface():
    assert set(iris_persistence.__all__) == {
        "ClassMetadata",
        "Field",
        "Index",
        "Model",
        "Runtime",
        "RuntimeConfig",
        "SchemaDiff",
        "StorageMigrationRequired",
        "StorageTuning",
        "UNSET",
        "configure_runtime",
        "diff_schema",
        "get_runtime",
        "install_runtime",
    }
    assert set(SECONDARY_ROOT_EXPORTS).isdisjoint(iris_persistence.__all__)
    assert "materialize" not in iris_persistence.__all__
    assert "from_iris" not in iris_persistence.__all__


@pytest.mark.parametrize(("name", "canonical"), SECONDARY_ROOT_EXPORTS.items())
def test_secondary_root_exports_warn_and_resolve_to_canonical_object(name, canonical):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        legacy = getattr(iris_persistence, name)

    assert legacy is canonical
    assert len(caught) == 1
    assert caught[0].category is DeprecationWarning
    assert caught[0].filename == __file__
    assert f"iris_persistence.{name} is deprecated" in str(caught[0].message)
    assert f"import {name} from {canonical.__module__.split('.')[0]}." in str(caught[0].message)
    assert "removed in 0.4.0" in str(caught[0].message)


def test_importing_root_does_not_import_secondary_modules():
    code = (
        "import sys; import iris_persistence; "
        "assert 'iris_persistence.migrations' not in sys.modules; "
        "assert 'iris_persistence.scaffold' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_version_comes_from_distribution_metadata():
    from importlib.metadata import version

    assert iris_persistence.__version__ == version("iris-persistence")


def test_root_conversion_wrappers_warn_and_delegate(monkeypatch):
    monkeypatch.setattr(iris_persistence, "_materialize", lambda value, **kwargs: (value, kwargs))
    monkeypatch.setattr(
        iris_persistence, "_from_iris", lambda model, value, **kwargs: (model, value, kwargs)
    )

    assert _deprecated_call(lambda: iris_persistence.materialize("model", validate=False)) == (
        "model",
        {"validate": False},
    )
    assert _deprecated_call(lambda: iris_persistence.from_iris("type", "iris", known_pk="7")) == (
        "type",
        "iris",
        {"known_pk": "7"},
    )
