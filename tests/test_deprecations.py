from __future__ import annotations

import warnings

import iris_persistence


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
