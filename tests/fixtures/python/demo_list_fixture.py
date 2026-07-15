from __future__ import annotations

from typing import Any

import iris_persistence
from iris_persistence.runtime import get_runtime, install_runtime
from iris_persistence.testing import InMemoryAdapter
from tests.fixtures.python.demo_list_models import DemoListFixture, DemoListFixtureItem


def configure_fixture_runtime(*, backend: str = "auto") -> str:
    if backend == "fake":
        install_runtime(InMemoryAdapter())
        return "fake"

    try:
        iris_persistence.configure_runtime()
        get_runtime().get_dbapi_connection()
        return "iris"
    except Exception:
        install_runtime(InMemoryAdapter())
        return "fake"


def reset_fixture_data() -> None:
    runtime = get_runtime()

    db = getattr(runtime, "db", None)
    if isinstance(db, dict):
        db.clear()
        return

    conn = runtime.get_dbapi_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"DELETE FROM {DemoListFixture._classname}")
    except Exception:
        pass
    try:
        cursor.execute(f"DELETE FROM {DemoListFixtureItem._classname}")
    except Exception:
        pass
    commit = getattr(conn, "commit", None)
    if callable(commit):
        commit()
    close = getattr(cursor, "close", None)
    if callable(close):
        close()


def run_list_fixture_round_trip(*, sync_schema: bool = False) -> dict[str, Any]:
    if sync_schema:
        DemoListFixtureItem.sync_schema()
        DemoListFixture.sync_schema()

    reset_fixture_data()

    fixture = DemoListFixture(
        ListAttributes=["a", "b", "c"],
        ListDataType=["foo", 1],
        ArrayDataType={"key1": "foo", "key2": 1},
        ListOfObjects=[DemoListFixtureItem(Value="test")],
        ArrayOfObjects={"item1": DemoListFixtureItem(Value="test")},
    )
    fixture.save()

    loaded = DemoListFixture.get(fixture.pk)
    if loaded is None:
        raise RuntimeError("Unable to reload saved DemoListFixture row")

    return {
        "saved_pk": fixture.pk,
        "loaded": loaded,
        "all_fixtures": list(DemoListFixture.all()),
    }
