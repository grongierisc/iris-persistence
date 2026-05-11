from __future__ import annotations

import importlib.util

import pytest
from iris_persistence.runtime import get_runtime
from tests.fixtures.python.demo_list_fixture import (
    configure_fixture_runtime,
    run_list_fixture_round_trip,
)
from tests.fixtures.python.demo_list_models import DemoListFixture


def test_demo_list_round_trip_with_fake_runtime():
    configure_fixture_runtime(backend="fake")
    result = run_list_fixture_round_trip()
    loaded = result["loaded"]
    all_fixtures = result["all_fixtures"]

    assert result["saved_pk"] is not None
    assert loaded.ListAttributes == ["a", "b", "c"]
    assert loaded.ListDataType == ["foo", 1]
    assert loaded.ArrayDataType == {"key1": "foo", "key2": 1}
    assert [item.Value for item in loaded.ListOfObjects] == ["test"]
    assert {key: item.Value for key, item in loaded.ArrayOfObjects.items()} == {
        "item1": "test",
    }
    assert len(all_fixtures) == 1
    assert all_fixtures[0].pk == result["saved_pk"]


def test_demo_list_run_demo_resets_previous_rows_in_fake_runtime():
    configure_fixture_runtime(backend="fake")
    first = run_list_fixture_round_trip()
    second = run_list_fixture_round_trip()

    assert len(first["all_fixtures"]) == 1
    assert len(second["all_fixtures"]) == 1
    assert second["all_fixtures"][0].pk == second["saved_pk"]


def test_demo_list_configure_demo_runtime_falls_back_to_fake(monkeypatch):
    import tests.fixtures.python.demo_list_fixture as demo_list_fixture

    monkeypatch.setattr(demo_list_fixture.iris_persistence, "configure", lambda: None)
    monkeypatch.setattr(
        demo_list_fixture,
        "get_runtime",
        lambda: type("BrokenRuntime", (), {"get_dbapi_connection": lambda self: (_ for _ in ()).throw(RuntimeError("no dbapi"))})(),
    )

    backend = configure_fixture_runtime()

    assert backend == "fake"


@pytest.mark.integration
@pytest.mark.skipif(importlib.util.find_spec("iris") is None, reason="requires IRIS runtime")
def test_demo_list_percent_list_persists_logical_value(configured_iris_runtime):
    assert configured_iris_runtime in {"embedded", "remote"}

    result = run_list_fixture_round_trip(sync_schema=True)
    conn = get_runtime().get_dbapi_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"SELECT ListAttributes FROM {DemoListFixture._classname} WHERE ID = ?",
        [result["saved_pk"]],
    )
    list_attributes = cursor.fetchall()[0][0]

    assert "%SYS.Python" not in list_attributes
    assert list_attributes != ""
