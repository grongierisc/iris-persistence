from __future__ import annotations

import re

import demo
from iris_orm.runtime import configure_default_runtime
from iris_orm.testing import FakeAdapter


def test_make_demo_toto_is_unique_and_prefixed():
    first = demo.make_demo_toto()
    second = demo.make_demo_toto()

    assert first != second
    assert re.fullmatch(r"Hello-[0-9A-F]{8}", first)
    assert re.fullmatch(r"Hello-[0-9A-F]{8}", second)


def test_run_demo_round_trip_with_fake_runtime():
    configure_default_runtime(FakeAdapter())

    result = demo.run_demo(toto="Hello-UNIT0001", sync_schema=False)
    loaded = result["loaded"]
    all_demos = result["all_demos"]

    assert result["saved_pk"] is not None
    assert loaded is not None
    assert loaded.Toto == "Hello-UNIT0001"
    assert loaded.Titi == 42
    assert loaded.bytes == b"\x00\x01\x02"
    assert loaded.dickt == {"key": "value"}
    assert loaded.snake_case == "snake_case_value"
    assert len(all_demos) == 1
    assert all_demos[0].pk == result["saved_pk"]
