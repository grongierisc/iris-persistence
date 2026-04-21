import os
import sys

import pytest

# Add the project root to the python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def pytest_addoption(parser):
    parser.addoption(
        "--iris-backend",
        action="store",
        default="embedded",
        choices=("embedded", "remote"),
        help="Select live IRIS backend for integration tests.",
    )


def _selected_iris_backends(config) -> list[str]:
    return [config.getoption("--iris-backend")]


def pytest_generate_tests(metafunc):
    if "configured_iris_runtime" not in metafunc.fixturenames:
        return
    if metafunc.definition.get_closest_marker("integration") is None:
        return

    backends = _selected_iris_backends(metafunc.config)
    metafunc.parametrize("configured_iris_runtime", backends, indirect=True)


@pytest.fixture
def configured_iris_runtime(request):
    import iris
    import iris_orm

    backend = getattr(request, "param", "embedded")
    if backend == "remote":
        host = os.environ.get("IRIS_HOST", "localhost")
        port = os.environ.get("IRIS_PORT", "1972")
        namespace = os.environ.get("IRIS_NAMESPACE", "IRISAPP")
        username = os.environ.get("IRISUSERNAME")
        password = os.environ.get("IRISPASSWORD")
        missing = [
            name
            for name, value in (
                ("IRIS_HOST", host),
                ("IRIS_PORT", port),
                ("IRIS_NAMESPACE", namespace),
                ("IRISUSERNAME", username),
                ("IRISPASSWORD", password),
            )
            if not value
        ]
        if missing:
            pytest.skip(
                "remote IRIS backend requires env vars: " + ", ".join(missing)
            )
        connection = iris.connect(host, int(port), namespace, username, password)
        iris_orm.configure(connection)
        try:
            yield "remote"
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()
            try:
                iris_orm.configure()
            except Exception:
                pass
        return

    iris_orm.configure()
    yield "embedded"
