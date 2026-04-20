from __future__ import annotations

from typing import Any

import iris_orm
from iris_orm.runtime import configure_default_runtime, get_runtime
from iris_orm.testing import FakeAdapter
from tests.fixtures.objectscript.python.list_fixture import ListFixture, ListFixtureItem


def configure_fixture_runtime(*, backend: str = "auto") -> str:
    if backend == "fake":
        configure_default_runtime(FakeAdapter())
        return "fake"

    try:
        iris_orm.configure()
        get_runtime().get_dbapi_connection()
        return "iris"
    except Exception:
        configure_default_runtime(FakeAdapter())
        return "fake"


def reset_fixture_data() -> None:
    runtime = get_runtime()

    db = getattr(runtime, "db", None)
    if isinstance(db, dict):
        db.clear()
        return

    conn = runtime.get_dbapi_connection()
    cursor = conn.cursor()
    cursor.execute(f"DELETE FROM {ListFixture._classname}")
    try:
        cursor.execute(f"DELETE FROM {ListFixtureItem._classname}")
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
        ListFixtureItem.sync_schema()
        ListFixture.sync_schema()

    reset_fixture_data()

    fixture = ListFixture(
        ListAttributes=["a", "b", "c"],
        ListDataType=["foo", 1],
        ArrayDataType={"key1": "foo", "key2": 1},
        ListOfObjects=[ListFixtureItem(Value="test")],
        ArrayOfObjects={"item1": ListFixtureItem(Value="test")},
    )
    fixture.save()

    loaded = ListFixture.get(fixture.pk)
    if loaded is None:
        raise RuntimeError("Unable to reload saved ListFixture row")

    return {
        "saved_pk": fixture.pk,
        "loaded": loaded,
        "all_fixtures": list(ListFixture.all()),
    }
