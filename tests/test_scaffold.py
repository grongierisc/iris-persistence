from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

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
        result = self._rows_by_query.get((sql, tuple(params)), [])
        if isinstance(result, Exception):
            raise result
        self._rows = list(result)

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
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.StubFixture",),
        ): [
            ("Title", "%Library.String", 1, None, _iris_dict({"MAXLEN": "120"}), "", "Title", 0),
            (
                "Enabled",
                "%Library.Boolean",
                0,
                "1",
                None,
                "",
                "Enabled",
                0,
            ),
            (
                "Payload",
                "%Library.DynamicObject",
                0,
                None,
                None,
                "",
                "payload_json",
                1,
            ),
            ("Tags", "%Library.String", 0, None, None, "list", "Tags", 0),
            ("%Internal", "%Library.String", 0, None, None, "", "%Internal", 0),
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
            "SELECT Name, Properties, _Unique, Type, PrimaryKey "
            "FROM %Dictionary.CompiledIndex WHERE parent = ?",
            ("Demo.StubFixture",),
        ): [
            ("TitleIdx", "Title", 1, "bitmap", 1),
            ("IDKEY", "ID", 1, "key", 0),
        ],
        (
            (
                "SELECT Name, DataLocation, DefaultData, IdLocation, IndexLocation, "
                "State, StreamLocation, Type "
                "FROM %Dictionary.CompiledStorage WHERE parent = ?"
            ),
            ("Demo.StubFixture",),
        ): [
            (
                "Default",
                "^Demo.StubFixtureD",
                "StubDefaultData",
                "^Demo.StubFixtureD",
                "^Demo.StubFixtureI",
                "StubState",
                "^Demo.StubFixtureS",
                "%Storage.Persistent",
            ),
        ],
        (
            "SELECT Name, Structure, Attribute, Subscript "
            "FROM %Dictionary.CompiledStorageData WHERE parent = ?",
            ("Demo.StubFixture||Default",),
        ): [
            ("StubDefaultData", "listnode", None, "\"Stub\""),
            ("Payload", "node", "Payload", "\"Payload\""),
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
            (
                "SELECT Name, AverageFieldSize, Selectivity "
                "FROM %Dictionary.CompiledStorageProperty WHERE parent = ?"
            ),
            ("Demo.StubFixture||Default",),
        ): [
            ("Title", "10", "0.001%"),
            ("%Internal", "999", "1"),
        ],
        (
            (
                "SELECT Name, BlockCount, Condition, ConditionFields, ConditionalWithHostVars, "
                "Global, PopulationPct, PopulationType, RowReference, Structure, Type "
                "FROM %Dictionary.CompiledStorageSQLMap WHERE parent = ?"
            ),
            ("Demo.StubFixture||Default",),
        ): [
            (
                "PrimaryMap",
                "-4",
                "x>0",
                "Title",
                1,
                "^Demo.MapI",
                "100",
                "FULL",
                "RowRef",
                "tree",
                "index",
            ),
        ],
        (
            "SELECT Name, Node, Piece, Delimiter, RetrievalCode "
            "FROM %Dictionary.CompiledStorageSQLMapData WHERE parent = ?",
            ("Demo.StubFixture||Default||PrimaryMap",),
        ): [
            ("TitleData", "1", "2", "^", "set {*}=$piece(x,^,2)"),
        ],
        (
            "SELECT Name, Field, Expression "
            "FROM %Dictionary.CompiledStorageSQLMapRowIdSpec WHERE parent = ?",
            ("Demo.StubFixture||Default||PrimaryMap",),
        ): [
            ("1", "ID", "{ID}"),
        ],
        (
            "SELECT Name, AccessType, DataAccess, Delimiter, Expression, "
            "LoopInitValue, NextCode, NullMarker, StartValue, StopExpression, StopValue "
            "FROM %Dictionary.CompiledStorageSQLMapSub WHERE parent = ?",
            ("Demo.StubFixture||Default||PrimaryMap",),
        ): [
            ("1", "piece", "Read", "^", "{Title}", "1", "set i=i+1", "", "1", "i>10", "10"),
        ],
        (
            "SELECT Name, Variable, Code "
            "FROM %Dictionary.CompiledStorageSQLMapSubAccessvar WHERE parent = ?",
            ("Demo.StubFixture||Default||PrimaryMap||1",),
        ): [
            ("1", "i", "set i=1"),
        ],
        (
            "SELECT Name, Expression "
            "FROM %Dictionary.CompiledStorageSQLMapSubInvalidcondition "
            "WHERE parent = ?",
            ("Demo.StubFixture||Default||PrimaryMap||1",),
        ): [
            ("1", "i<1"),
        ],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    result = scaffold_module.scaffold_from_iris(
        "Demo.*", str(tmp_path), extract_meta=True, return_result=True
    )
    assert result.files == [str(tmp_path / "stubfixture.py")]
    assert result.warnings == []

    module = _load_module(tmp_path / "stubfixture.py")
    StubFixture = module.StubFixture

    assert StubFixture._classname == "Demo.StubFixture"
    assert StubFixture._sync_mode == "observe"
    assert StubFixture._superclasses == "%Persistent"
    assert StubFixture._parameters == {"CUSTOM": "demo"}

    enabled_field = StubFixture._fields["Enabled"]
    assert enabled_field.default is True
    assert enabled_field.iris_type == "%Library.Boolean"
    assert StubFixture._fields["Title"].iris_type == "%Library.String"
    assert StubFixture._fields["Payload"].iris_type == "%Library.DynamicObject"
    assert StubFixture._fields["Payload"].readonly is True
    assert StubFixture._fields["Payload"].sql_field_name == "payload_json"
    assert StubFixture._fields["Tags"].collection == "list"

    storage = StubFixture._storage
    assert storage is not None
    assert storage.data_location == "^Demo.StubFixtureD"
    assert storage.default_data == "StubDefaultData"
    assert storage.id_location == "^Demo.StubFixtureD"
    assert storage.index_location == "^Demo.StubFixtureI"
    assert storage.state == "StubState"
    assert storage.stream_location == "^Demo.StubFixtureS"

    storage_data = {item.name: item for item in storage.data}
    assert storage_data["StubDefaultData"].subscript == '"Stub"'
    assert storage_data["StubDefaultData"].values == {
        "1": "%%CLASSNAME",
        "2": "Title",
        "3": "Enabled",
    }
    assert storage_data["Payload"].attribute == "Payload"
    assert storage_data["Payload"].subscript == '"Payload"'
    assert storage_data["Payload"].values == {}

    assert len(storage.properties) == 1
    assert storage.properties[0].name == "Title"
    assert storage.properties[0].average_field_size == "10"
    assert storage.properties[0].selectivity == "0.001%"
    assert len(storage.sql_maps) == 1
    assert storage.sql_maps[0].name == "PrimaryMap"
    assert storage.sql_maps[0].condition == "x>0"
    assert storage.sql_maps[0].condition_fields == "Title"
    assert storage.sql_maps[0].conditional_with_host_vars is True
    assert storage.sql_maps[0].global_name == "^Demo.MapI"
    assert storage.sql_maps[0].population_pct == "100"
    assert storage.sql_maps[0].population_type == "FULL"
    assert storage.sql_maps[0].row_reference == "RowRef"
    assert storage.sql_maps[0].structure == "tree"
    assert storage.sql_maps[0].type == "index"
    assert storage.sql_maps[0].data is not None
    assert storage.sql_maps[0].data[0].name == "TitleData"
    assert storage.sql_maps[0].data[0].node == "1"
    assert storage.sql_maps[0].data[0].piece == "2"
    assert storage.sql_maps[0].data[0].delimiter == "^"
    assert storage.sql_maps[0].data[0].retrieval_code == "set {*}=$piece(x,^,2)"
    assert storage.sql_maps[0].row_id_specs[0].name == "1"
    assert storage.sql_maps[0].row_id_specs[0].field == "ID"
    assert storage.sql_maps[0].row_id_specs[0].expression == "{ID}"
    assert storage.sql_maps[0].subscripts[0].name == "1"
    assert storage.sql_maps[0].subscripts[0].access_type == "piece"
    assert storage.sql_maps[0].subscripts[0].data_access == "Read"
    assert storage.sql_maps[0].subscripts[0].expression == "{Title}"
    assert storage.sql_maps[0].subscripts[0].access_vars[0].variable == "i"
    assert storage.sql_maps[0].subscripts[0].invalid_conditions[0].expression == "i<1"

    assert len(StubFixture._indexes) == 1
    assert StubFixture._indexes[0].name == "TitleIdx"
    assert StubFixture._indexes[0].unique is True
    assert StubFixture._indexes[0].type == "bitmap"
    assert StubFixture._indexes[0].primary_key is True

    generated_text = (tmp_path / "stubfixture.py").read_text(encoding="utf-8")
    assert 'Field(iris_type="%Library.String", required=True, maxlen=120)' in generated_text
    assert 'Field(iris_type="%Library.Boolean", required=False, default=True)' in generated_text
    assert (
        "Field(iris_type=\"%Library.DynamicObject\", required=False, readonly=True, "
        "sql_field_name='payload_json')"
        in generated_text
    )
    assert (
        'Field(iris_type="%Library.String", required=False, collection=\'list\')'
        in generated_text
    )
    assert 'id_location="^Demo.StubFixtureD"' in generated_text
    assert 'index_location="^Demo.StubFixtureI"' in generated_text
    assert 'state="StubState"' in generated_text
    assert 'stream_location="^Demo.StubFixtureS"' in generated_text
    assert 'subscript=\'"Stub"\'' in generated_text
    assert "attribute='Payload'" in generated_text
    assert (
        'StorageProperty(name="Title", average_field_size="10", selectivity="0.001%")'
        in generated_text
    )
    assert (
        'Index("TitleIdx", properties="Title", unique=True, type="bitmap", primary_key=True)'
        in generated_text
    )
    assert (
        "StorageSQLMapData(name='TitleData', node='1', piece='2', delimiter='^'"
        in generated_text
    )
    assert "StorageSQLMapRowIdSpec(name='1', field='ID', expression='{ID}')" in generated_text
    assert "StorageSQLMapSub(name='1', access_type='piece', data_access='Read'" in generated_text
    assert "StorageSQLMapSubAccessVar(name='1', variable='i', code='set i=1')" in generated_text
    assert "StorageSQLMapSubInvalidCondition(name='1', expression='i<1')" in generated_text
    assert "StorageData(" in generated_text
    assert "values={}" in generated_text


def test_scaffold_from_iris_reports_metadata_warnings(monkeypatch, tmp_path: Path):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.%",),
        ): [
            ("Demo.WarnFixture", "%Persistent"),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.WarnFixture",),
        ): [
            ("Title", "%Library.String", 1, None, None, "", "Title", 0),
        ],
        (
            "SELECT Name, Default FROM %Dictionary.CompiledParameter WHERE parent = ?",
            ("Demo.WarnFixture",),
        ): RuntimeError("parameter lookup failed"),
        (
            "SELECT Name, Properties, _Unique, Type, PrimaryKey "
            "FROM %Dictionary.CompiledIndex WHERE parent = ?",
            ("Demo.WarnFixture",),
        ): [],
        (
            (
                "SELECT Name, DataLocation, DefaultData, IdLocation, IndexLocation, "
                "State, StreamLocation, Type "
                "FROM %Dictionary.CompiledStorage WHERE parent = ?"
            ),
            ("Demo.WarnFixture",),
        ): [],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    with pytest.warns(RuntimeWarning, match="Failed to scaffold parameters"):
        result = scaffold_module.scaffold_from_iris(
            "Demo.*", str(tmp_path), extract_meta=True, return_result=True
        )

    assert result.files == [str(tmp_path / "warnfixture.py")]
    assert len(result.warnings) == 1
    assert result.warnings[0].code == "parameters"
    assert result.warnings[0].classname == "Demo.WarnFixture"

    module = _load_module(tmp_path / "warnfixture.py")
    assert module.WarnFixture._parameters == {}


def test_scaffold_selectivity_merges_storage_property_definitions(monkeypatch, tmp_path: Path):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.SelectivityFixture",),
        ): [
            ("Demo.SelectivityFixture", "%Persistent"),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.SelectivityFixture",),
        ): [
            ("Title", "%Library.String", 1, None, _iris_dict({"MAXLEN": "120"}), "", "Title", 0),
            ("Count", "%Library.Integer", 0, None, None, "", "Count", 0),
        ],
        (
            "SELECT Name, Default FROM %Dictionary.CompiledParameter WHERE parent = ?",
            ("Demo.SelectivityFixture",),
        ): [],
        (
            "SELECT Name, Properties, _Unique, Type, PrimaryKey "
            "FROM %Dictionary.CompiledIndex WHERE parent = ?",
            ("Demo.SelectivityFixture",),
        ): [],
        (
            (
                "SELECT Name, DataLocation, DefaultData, IdLocation, IndexLocation, "
                "State, StreamLocation, Type "
                "FROM %Dictionary.CompiledStorage WHERE parent = ?"
            ),
            ("Demo.SelectivityFixture",),
        ): [
            (
                "Default",
                "^Demo.SelectivityFixtureD",
                "SelectivityFixtureDefaultData",
                "^Demo.SelectivityFixtureD",
                "^Demo.SelectivityFixtureI",
                None,
                "^Demo.SelectivityFixtureS",
                "%Storage.Persistent",
            ),
        ],
        (
            "SELECT Name, Structure, Attribute, Subscript "
            "FROM %Dictionary.CompiledStorageData WHERE parent = ?",
            ("Demo.SelectivityFixture||Default",),
        ): [
            ("SelectivityFixtureDefaultData", "listnode", None, None),
        ],
        (
            "SELECT Name, Value FROM %Dictionary.CompiledStorageDataValue WHERE parent = ?",
            ("Demo.SelectivityFixture||Default||SelectivityFixtureDefaultData",),
        ): [
            ("1", "%%CLASSNAME"),
            ("2", "Title"),
            ("3", "Count"),
        ],
        (
            (
                "SELECT Name, AverageFieldSize, Selectivity "
                "FROM %Dictionary.CompiledStorageProperty WHERE parent = ?"
            ),
            ("Demo.SelectivityFixture||Default",),
        ): [
            ("Count", "", ""),
        ],
        (
            (
                "SELECT Name, AverageFieldSize, Selectivity "
                "FROM %Dictionary.StoragePropertyDefinition WHERE parent = ?"
            ),
            ("Demo.SelectivityFixture||Default",),
        ): [
            ("%%CLASSNAME", "2", "0.0001%"),
            ("Title", "7.09", "9.3220%"),
            ("Count", "2.73", "13.5593%"),
        ],
        (
            "SELECT Name, BlockCount, Condition, ConditionFields, ConditionalWithHostVars, "
            "Global, PopulationPct, PopulationType, RowReference, Structure, Type "
            "FROM %Dictionary.CompiledStorageSQLMap WHERE parent = ?",
            ("Demo.SelectivityFixture||Default",),
        ): [],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    result = scaffold_module.scaffold_from_iris(
        "Demo.SelectivityFixture",
        str(tmp_path),
        extract_meta=True,
        scaffold_selectivity=True,
        return_result=True,
    )

    module = _load_module(tmp_path / "selectivityfixture.py")
    SelectivityFixture = module.SelectivityFixture

    assert result.warnings == []
    assert SelectivityFixture._storage is not None
    properties = {item.name: item for item in SelectivityFixture._storage.properties}
    assert properties["Title"].average_field_size == "7.09"
    assert properties["Title"].selectivity == "9.3220%"
    assert properties["Count"].average_field_size == "2.73"
    assert properties["Count"].selectivity == "13.5593%"


def test_scaffold_preserves_objectscript_initial_expression_and_can_follow_related_classes(
    monkeypatch,
    tmp_path: Path,
):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.Interop.Request",),
        ): [
            ("Demo.Interop.Request", "%Persistent"),
        ],
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name = ?",
            ("Demo.API.Request",),
        ): [
            ("Demo.API.Request", "%SerialObject"),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.Interop.Request",),
        ): [
            (
                "GeneratedAt",
                "%Library.String",
                0,
                '##class(Demo.Util.Clock).NowUTC()',
                _iris_dict({"MAXLEN": "50"}),
                "",
                "GeneratedAt",
                0,
            ),
            ("Request", "Demo.API.Request", 0, None, None, "", "Request", 0),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.API.Request",),
        ): [
            ("Path", "%Library.String", 1, None, _iris_dict({"MAXLEN": "128"}), "", "Path", 0),
        ],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    basic_dir = tmp_path / "basic"
    basic_result = scaffold_module.scaffold_from_iris(
        "Demo.Interop.Request",
        str(basic_dir),
        return_result=True,
    )
    assert basic_result.warnings == []
    assert basic_result.files == [str(basic_dir / "request.py")]
    basic_text = (basic_dir / "request.py").read_text(encoding="utf-8")
    basic_request_line = (
        'Request: Annotated[Any | None, Field(iris_type="Demo.API.Request", required=False)]'
    )
    assert basic_request_line in basic_text
    assert "initial_expression='##class(Demo.Util.Clock).NowUTC()'" in basic_text
    assert "= ##class(Demo.Util.Clock).NowUTC()" not in basic_text

    follow_dir = tmp_path / "follow"
    follow_result = scaffold_module.scaffold_from_iris(
        "Demo.Interop.Request",
        str(follow_dir),
        include_related=True,
        return_result=True,
    )
    assert follow_result.warnings == []
    assert {Path(path).name for path in follow_result.files} == {"request.py", "api_request.py"}

    generated_text = (follow_dir / "request.py").read_text(encoding="utf-8")
    assert "from api_request import APIRequest" in generated_text
    assert (
        'Request: Annotated[APIRequest | None, Field(iris_type="Demo.API.Request", required=False)]'
        in generated_text
    )
    assert "initial_expression='##class(Demo.Util.Clock).NowUTC()'" in generated_text
    assert "= ##class(Demo.Util.Clock).NowUTC()" not in generated_text

    sys.path.insert(0, str(follow_dir))
    try:
        module = _load_module(follow_dir / "request.py")
        generated_class = module.Request
        assert generated_class._fields["GeneratedAt"].default is None
        assert (
            generated_class._fields["GeneratedAt"].initial_expression
            == "##class(Demo.Util.Clock).NowUTC()"
        )
        assert generated_class._fields["Request"].iris_type == "Demo.API.Request"
    finally:
        sys.path.remove(str(follow_dir))
        sys.modules.pop("api_request", None)


def test_scaffold_include_related_uses_unique_names_for_same_basename_classes(
    monkeypatch,
    tmp_path: Path,
):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.Request",),
        ): [
            ("Demo.Request", "%Persistent"),
        ],
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name = ?",
            ("VendorA.Request",),
        ): [
            ("VendorA.Request", "%SerialObject"),
        ],
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name = ?",
            ("VendorB.Request",),
        ): [
            ("VendorB.Request", "%SerialObject"),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.Request",),
        ): [
            ("Primary", "VendorA.Request", 0, None, None, "", "Primary", 0),
            ("Secondary", "VendorB.Request", 0, None, None, "", "Secondary", 0),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("VendorA.Request",),
        ): [
            ("Path", "%Library.String", 1, None, _iris_dict({"MAXLEN": "64"}), "", "Path", 0),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("VendorB.Request",),
        ): [
            ("Id", "%Library.String", 1, None, _iris_dict({"MAXLEN": "64"}), "", "Id", 0),
        ],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    result = scaffold_module.scaffold_from_iris(
        "Demo.Request",
        str(tmp_path),
        include_related=True,
        return_result=True,
    )

    assert result.warnings == []
    assert {Path(path).name for path in result.files} == {
        "request.py",
        "vendora_request.py",
        "vendorb_request.py",
    }

    generated_text = (tmp_path / "request.py").read_text(encoding="utf-8")
    assert "from vendora_request import VendorARequest" in generated_text
    assert "from vendorb_request import VendorBRequest" in generated_text
    assert (
        'Primary: Annotated[VendorARequest | None, '
        'Field(iris_type="VendorA.Request", required=False)]'
        in generated_text
    )
    assert (
        'Secondary: Annotated[VendorBRequest | None, '
        'Field(iris_type="VendorB.Request", required=False)]'
        in generated_text
    )


def test_scaffold_collection_object_properties_are_typed_as_collections(
    monkeypatch,
    tmp_path: Path,
):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.Batch",),
        ): [
            ("Demo.Batch", "%Persistent"),
        ],
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name = ?",
            ("Demo.Item",),
        ): [
            ("Demo.Item", "%SerialObject"),
        ],
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name = ?",
            ("Demo.LookupEntry",),
        ): [
            ("Demo.LookupEntry", "%SerialObject"),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.Batch",),
        ): [
            ("Items", "Demo.Item", 0, None, None, "list", "Items", 0),
            ("Entries", "Demo.LookupEntry", 0, None, None, "array", "Entries", 0),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.Item",),
        ): [
            ("Code", "%Library.String", 1, None, _iris_dict({"MAXLEN": "32"}), "", "Code", 0),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.LookupEntry",),
        ): [
            ("Label", "%Library.String", 1, None, _iris_dict({"MAXLEN": "32"}), "", "Label", 0),
        ],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    result = scaffold_module.scaffold_from_iris(
        "Demo.Batch",
        str(tmp_path),
        include_related=True,
        return_result=True,
    )

    assert result.warnings == []
    generated_text = (tmp_path / "batch.py").read_text(encoding="utf-8")
    assert "from item import Item" in generated_text
    assert "from lookupentry import LookupEntry" in generated_text
    assert (
        'Items: Annotated[list[Item] | None, '
        'Field(iris_type="Demo.Item", required=False, collection=\'list\')] = None'
        in generated_text
    )
    assert (
        'Entries: Annotated[dict[str, LookupEntry] | None, '
        'Field(iris_type="Demo.LookupEntry", required=False, collection=\'array\')] = None'
        in generated_text
    )


def test_scaffold_preserves_multiple_non_python_initial_expression_variants(
    monkeypatch,
    tmp_path: Path,
):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.InitialExpressionFixture",),
        ): [
            ("Demo.InitialExpressionFixture", "%Persistent"),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.InitialExpressionFixture",),
        ): [
            ("ClockValue", "%Library.String", 0, "$zu(115,10)", None, "", "ClockValue", 0),
            ("BuiltList", "%Library.String", 0, '$listbuild("A","B")', None, "", "BuiltList", 0),
            ("MacroFlag", "%Library.Boolean", 0, "$$$YES", None, "", "MacroFlag", 0),
            (
                "QuotedText",
                "%Library.String",
                0,
                '"hello ""iris"""',
                None,
                "",
                "QuotedText",
                0,
            ),
            ("RetryCount", "%Library.Integer", 0, "42", None, "", "RetryCount", 0),
        ],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    result = scaffold_module.scaffold_from_iris(
        "Demo.InitialExpressionFixture",
        str(tmp_path),
        return_result=True,
    )

    assert result.warnings == []
    generated_text = (tmp_path / "initialexpressionfixture.py").read_text(encoding="utf-8")
    assert "initial_expression='$zu(115,10)'" in generated_text
    assert 'initial_expression=\'$listbuild("A","B")\'' in generated_text
    assert "initial_expression='$$$YES'" in generated_text
    assert "default='hello \"iris\"'" in generated_text
    assert "default=42" in generated_text
    assert " = $zu(115,10)" not in generated_text
    assert ' = $listbuild("A","B")' not in generated_text
    assert " = $$$YES" not in generated_text

    module = _load_module(tmp_path / "initialexpressionfixture.py")
    Fixture = module.InitialExpressionFixture
    assert Fixture._fields["ClockValue"].initial_expression == "$zu(115,10)"
    assert Fixture._fields["BuiltList"].initial_expression == '$listbuild("A","B")'
    assert Fixture._fields["MacroFlag"].initial_expression == "$$$YES"
    assert Fixture._fields["QuotedText"].default == 'hello "iris"'
    assert Fixture._fields["RetryCount"].default == 42


def test_scaffold_include_related_recurses_two_levels(
    monkeypatch,
    tmp_path: Path,
):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.RootFixture",),
        ): [
            ("Demo.RootFixture", "%Persistent"),
        ],
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name = ?",
            ("Demo.ChildNode",),
        ): [
            ("Demo.ChildNode", "%SerialObject"),
        ],
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name = ?",
            ("Demo.GrandchildNode",),
        ): [
            ("Demo.GrandchildNode", "%SerialObject"),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.RootFixture",),
        ): [
            ("Child", "Demo.ChildNode", 0, None, None, "", "Child", 0),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.ChildNode",),
        ): [
            ("Grandchild", "Demo.GrandchildNode", 0, None, None, "", "Grandchild", 0),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.GrandchildNode",),
        ): [
            ("Value", "%Library.String", 1, None, _iris_dict({"MAXLEN": "24"}), "", "Value", 0),
        ],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    result = scaffold_module.scaffold_from_iris(
        "Demo.RootFixture",
        str(tmp_path),
        include_related=True,
        return_result=True,
    )

    assert result.warnings == []
    assert {Path(path).name for path in result.files} == {
        "rootfixture.py",
        "childnode.py",
        "grandchildnode.py",
    }

    root_text = (tmp_path / "rootfixture.py").read_text(encoding="utf-8")
    child_text = (tmp_path / "childnode.py").read_text(encoding="utf-8")
    assert "from childnode import ChildNode" in root_text
    assert (
        'Child: Annotated[ChildNode | None, Field(iris_type="Demo.ChildNode", required=False)]'
        in root_text
    )
    assert "from grandchildnode import GrandchildNode" in child_text
    assert (
        'Grandchild: Annotated[GrandchildNode | None, '
        'Field(iris_type="Demo.GrandchildNode", required=False)]'
        in child_text
    )

    sys.path.insert(0, str(tmp_path))
    try:
        root_module = _load_module(tmp_path / "rootfixture.py")
        child_module = _load_module(tmp_path / "childnode.py")
        assert root_module.RootFixture._fields["Child"].iris_type == "Demo.ChildNode"
        assert child_module.ChildNode._fields["Grandchild"].iris_type == "Demo.GrandchildNode"
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("childnode", None)
        sys.modules.pop("grandchildnode", None)
