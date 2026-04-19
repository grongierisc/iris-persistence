from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import iris_orm.scaffold as scaffold_module


def _load_module(module_path: Path):
    module_name = f"generated_{module_path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _iris_list(parts: list[bytes]) -> bytes:
    return b"".join(bytes((len(part) + 2, 0)) + part for part in parts)


def _iris_dict(items: dict[str, str]) -> bytes:
    encoded_items = []
    for key, value in items.items():
        encoded_items.append(_iris_list([key.encode("utf-8"), value.encode("utf-8")]))
    return _iris_list(encoded_items)


class _StubCursor:
    def __init__(self, rows_by_query):
        self._rows_by_query = rows_by_query
        self._rows = []

    def execute(self, sql, params=()):
        self._rows = list(self._rows_by_query.get((sql, tuple(params)), []))

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)

    def close(self):
        return None


class _StubConnection:
    def __init__(self, rows_by_query):
        self._rows_by_query = rows_by_query

    def cursor(self):
        return _StubCursor(self._rows_by_query)

    def close(self):
        return None


class _StubRuntime:
    def __init__(self, rows_by_query):
        self._rows_by_query = rows_by_query

    def get_dbapi_connection(self):
        return _StubConnection(self._rows_by_query)


def test_scaffold_from_iris_with_stubbed_dictionary(monkeypatch, tmp_path: Path):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.%",),
        ): [
            ("Demo.StubFixture", "%Persistent"),
        ],
        (
            "SELECT Name, Type, Required, InitialExpression, Parameters FROM %Dictionary.CompiledProperty WHERE parent = ?",
            ("Demo.StubFixture",),
        ): [
            ("Title", "%Library.String", 1, None, _iris_dict({"MAXLEN": "120"})),
            ("Enabled", "%Library.Boolean", 0, "1", None),
            ("Payload", "%Library.DynamicObject", 0, None, None),
            ("%Internal", "%Library.String", 0, None, None),
        ],
        (
            "SELECT Name, Default FROM %Dictionary.CompiledParameter WHERE parent = ?",
            ("Demo.StubFixture",),
        ): [
            ("CUSTOM", "demo"),
            ("GUID", "skip-me"),
            ("%INTERNAL", "skip-me-too"),
        ],
        (
            "SELECT Name, Properties, _Unique FROM %Dictionary.CompiledIndex WHERE parent = ?",
            ("Demo.StubFixture",),
        ): [
            ("TitleIdx", "Title", 1),
            ("IDKEY", "ID", 1),
        ],
        (
            "SELECT Name, DataLocation, DefaultData, Type FROM %Dictionary.CompiledStorage WHERE parent = ?",
            ("Demo.StubFixture",),
        ): [
            ("Default", "^Demo.StubFixtureD", "StubDefaultData", "%Storage.Persistent"),
        ],
        (
            "SELECT Name, Structure FROM %Dictionary.CompiledStorageData WHERE parent = ?",
            ("Demo.StubFixture||Default",),
        ): [
            ("StubDefaultData", "listnode"),
            ("Payload", "node"),
        ],
        (
            "SELECT Name, Value FROM %Dictionary.CompiledStorageDataValue WHERE parent = ?",
            ("Demo.StubFixture||Default||StubDefaultData",),
        ): [
            ("1", "%%CLASSNAME"),
            ("2", "Title"),
            ("3", "Enabled"),
        ],
        (
            "SELECT Name, Value FROM %Dictionary.CompiledStorageDataValue WHERE parent = ?",
            ("Demo.StubFixture||Default||Payload",),
        ): [],
        (
            "SELECT Name, AverageFieldSize FROM %Dictionary.CompiledStorageProperty WHERE parent = ?",
            ("Demo.StubFixture||Default",),
        ): [
            ("Title", "10"),
            ("%Internal", "999"),
        ],
        (
            "SELECT Name, BlockCount FROM %Dictionary.CompiledStorageSQLMap WHERE parent = ?",
            ("Demo.StubFixture||Default",),
        ): [
            ("PrimaryMap", "-4"),
        ],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    generated_files = scaffold_module.scaffold_from_iris("Demo.*", str(tmp_path), extract_meta=True)
    assert generated_files == [str(tmp_path / "stubfixture.py")]

    module = _load_module(tmp_path / "stubfixture.py")
    StubFixture = module.StubFixture

    assert StubFixture._classname == "Demo.StubFixture"
    assert StubFixture._sync_mode == "observe"
    assert StubFixture._superclasses == "%Persistent"
    assert StubFixture._parameters == {"CUSTOM": "demo"}

    enabled_field = StubFixture._fields["Enabled"]
    assert enabled_field.default is True

    storage = StubFixture._storage
    assert storage is not None
    assert storage.data_location == "^Demo.StubFixtureD"
    assert storage.default_data == "StubDefaultData"

    storage_data = {item.name: item for item in storage.data}
    assert storage_data["StubDefaultData"].values == {
        "1": "%%CLASSNAME",
        "2": "Title",
        "3": "Enabled",
    }
    assert storage_data["Payload"].values == {}

    assert len(storage.properties) == 1
    assert storage.properties[0].name == "Title"
    assert len(storage.sql_maps) == 1
    assert storage.sql_maps[0].name == "PrimaryMap"

    assert len(StubFixture._indexes) == 1
    assert StubFixture._indexes[0].name == "TitleIdx"
    assert StubFixture._indexes[0].unique is True

    generated_text = (tmp_path / "stubfixture.py").read_text(encoding="utf-8")
    assert "StorageData(" in generated_text
    assert "values={}" in generated_text
