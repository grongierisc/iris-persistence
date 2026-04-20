from __future__ import annotations

import demo_list
from iris_orm.runtime import configure_default_runtime
from iris_orm.testing import FakeAdapter


def test_demo_list_round_trip_with_fake_runtime():
    configure_default_runtime(FakeAdapter())

    result = demo_list.run_demo()
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
    configure_default_runtime(FakeAdapter())

    first = demo_list.run_demo()
    second = demo_list.run_demo()

    assert len(first["all_fixtures"]) == 1
    assert len(second["all_fixtures"]) == 1
    assert second["all_fixtures"][0].pk == second["saved_pk"]


def test_demo_list_configure_demo_runtime_falls_back_to_fake(monkeypatch):
    monkeypatch.setattr(demo_list.iris_orm, "configure", lambda: None)
    monkeypatch.setattr(
        demo_list,
        "get_runtime",
        lambda: type("BrokenRuntime", (), {"get_dbapi_connection": lambda self: (_ for _ in ()).throw(RuntimeError("no dbapi"))})(),
    )

    backend = demo_list.configure_demo_runtime()

    assert backend == "fake"
