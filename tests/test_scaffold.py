from __future__ import annotations

import importlib.util
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

import iris_persistence.scaffold as scaffold_module
from iris_persistence.advanced_storage import StorageData, StorageDefinition


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
        self._rows_by_query = {
            self._query_key(sql, params): rows for (sql, params), rows in rows_by_query.items()
        }
        self._rows = []

    @staticmethod
    def _query_key(sql, params):
        select, remainder = sql.split(" FROM ", 1)
        columns = tuple(column.strip() for column in select.removeprefix("SELECT ").split(","))
        table = remainder.split(None, 1)[0]
        return (table, columns, tuple(params))

    def execute(self, sql, params=()):
        key = self._query_key(sql, params)
        result = self._rows_by_query.get(key, [])
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

    @contextmanager
    def connection(self):
        connection = self.get_dbapi_connection()
        try:
            yield connection
        finally:
            connection.close()


class _StubCollection:
    def __init__(self, items):
        self._items = list(items)

    def Count(self):
        return len(self._items)

    def GetAt(self, index):
        return self._items[index - 1]


class _StubRuntimeWithParameters(_StubRuntime):
    def __init__(self, rows_by_query, parameters_by_class):
        super().__init__(rows_by_query)
        self._parameters_by_class = parameters_by_class

    def get_object(self, class_name: str, obj_id: str):
        if class_name != "%Dictionary.ClassDefinition":
            return None
        params = self._parameters_by_class.get(obj_id)
        if params is None:
            return None
        return {"Parameters": _StubCollection(params)}

    def get_property(self, obj, prop_name: str):
        if isinstance(obj, dict):
            return obj.get(prop_name)
        return obj.get(prop_name)

    def invoke_method(self, obj, method_name: str, *args):
        return getattr(obj, method_name)(*args)


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
            "SELECT Name, _Default, Origin FROM %Dictionary.CompiledParameter WHERE parent = ?",
            ("Demo.StubFixture",),
        ): [
            ("CUSTOM", "demo", "Demo.StubFixture"),
            ("GUID", "skip-me", "Demo.StubFixture"),
            ("%INTERNAL", "skip-me-too", "Demo.StubFixture"),
        ],
        (
            "SELECT Name, Properties, _Unique, Type, PrimaryKey "
            "FROM %Dictionary.CompiledIndex WHERE parent = ?",
            ("Demo.StubFixture",),
        ): [
            ("TitleIdx", "Title", 1, "bitmap", 1),
            ("IDKEY", "ID", 1, "key", 0),
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

    assert StubFixture._custom_storage is None
    generated = (tmp_path / "stubfixture.py").read_text(encoding="utf-8")
    assert "StorageDefinition" not in generated


def test_scaffold_reads_property_relationship_metadata(monkeypatch, tmp_path: Path):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.RelationshipFixture",),
        ): [
            ("Demo.RelationshipFixture", "%Persistent"),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.RelationshipFixture",),
        ): [
            ("Owner", "Demo.RelatedFixture", 0, None, None, "", "Owner", 0),
            ("TransientValue", "%Library.String", 0, None, None, "", "TransientValue", 0),
            ("IdentityCode", "%Library.Integer", 1, None, None, "", "IdentityCode", 0),
        ],
        (
            (
                    "SELECT Name, _Identity, Relationship, OnDelete, Inverse, Transient, "
                "Storable, MultiDimensional "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.RelationshipFixture",),
        ): [
            ("Owner", 0, "parent", "cascade", "Children", 0, 1, 0),
            ("TransientValue", 0, None, None, None, 1, 0, 1),
            ("IdentityCode", 1, None, None, None, 0, 1, 0),
        ],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    result = scaffold_module.scaffold_from_iris(
        "Demo.RelationshipFixture",
        str(tmp_path),
        return_result=True,
    )

    assert result.warnings == []
    module_path = Path(result.files[0])
    generated_text = module_path.read_text(encoding="utf-8")
    assert (
        "Field(iris_type=\"Demo.RelatedFixture\", relationship='parent', "
        "on_delete='cascade', inverse='Children', default=None)" in generated_text
    )
    assert (
        'Field(iris_type="%Library.String", transient=True, '
        "storable=False, multi_dimensional=True, default=None)" in generated_text
    )
    assert 'Field(iris_type="%Library.Integer", required=True, identity=True)' in generated_text

    module = _load_module(module_path)
    assert module.RelationshipFixture._fields["Owner"].relationship == "parent"
    assert module.RelationshipFixture._fields["Owner"].on_delete == "cascade"
    assert module.RelationshipFixture._fields["Owner"].inverse == "Children"
    assert module.RelationshipFixture._fields["TransientValue"].transient is True
    assert module.RelationshipFixture._fields["TransientValue"].storable is False
    assert module.RelationshipFixture._fields["TransientValue"].multi_dimensional is True
    assert module.RelationshipFixture._fields["IdentityCode"].identity is True


def test_scaffold_reads_property_sql_projection_metadata(monkeypatch, tmp_path: Path):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.SqlProjectionFixture",),
        ): [
            ("Demo.SqlProjectionFixture", "%Persistent"),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.SqlProjectionFixture",),
        ): [
            ("Tags", "%List", 0, None, None, "", "Tags", 0),
            ("TitleUpper", "%Library.String", 0, None, None, "", "TitleUpper", 0),
        ],
        (
            (
                "SELECT Name, SqlListDelimiter, SqlListType, SqlComputeCode, "
                "SqlComputeOnChange, SqlComputed "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.SqlProjectionFixture",),
        ): [
            ("Tags", "|", "DELIMITED", None, None, 0),
            (
                "TitleUpper",
                None,
                None,
                "Set {*} = {Title}",
                "Title",
                1,
            ),
        ],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    result = scaffold_module.scaffold_from_iris(
        "Demo.SqlProjectionFixture",
        str(tmp_path),
        return_result=True,
    )

    assert result.warnings == []
    module_path = Path(result.files[0])
    generated_text = module_path.read_text(encoding="utf-8")
    assert (
        "Field(iris_type=\"%List\", sql_list_delimiter='|', "
        "sql_list_type='DELIMITED', default=None)" in generated_text
    )
    assert (
        "Field(iris_type=\"%Library.String\", sql_compute_code='Set {*} = {Title}', "
        "sql_compute_on_change='Title', sql_computed=True, default=None)" in generated_text
    )

    module = _load_module(module_path)
    assert module.SqlProjectionFixture._fields["Tags"].sql_list_delimiter == "|"
    assert module.SqlProjectionFixture._fields["Tags"].sql_list_type == "DELIMITED"
    assert module.SqlProjectionFixture._fields["TitleUpper"].sql_compute_code == "Set {*} = {Title}"
    assert module.SqlProjectionFixture._fields["TitleUpper"].sql_compute_on_change == "Title"
    assert module.SqlProjectionFixture._fields["TitleUpper"].sql_computed is True


def test_scaffold_reads_class_metadata(monkeypatch, tmp_path: Path):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.MetaFixture",),
        ): [
            ("Demo.MetaFixture", "%Persistent"),
        ],
        (
            (
                "SELECT Description, Deprecated, Final, SqlTableName, ProcedureBlock "
                "FROM %Dictionary.CompiledClass WHERE Name = ?"
            ),
            ("Demo.MetaFixture",),
        ): [
            (
                "scaffolded class metadata",
                1,
                1,
                "Demo_MetaFixture",
                1,
            ),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.MetaFixture",),
        ): [
            ("Title", "%Library.String", 1, None, None, "", "Title", 0),
        ],
        (
            (
                "SELECT Name, Identity, Relationship, OnDelete, Inverse, Transient, "
                "Storable, MultiDimensional "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.MetaFixture",),
        ): [
            ("Title", 0, None, None, None, 0, 1, 0),
        ],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    result = scaffold_module.scaffold_from_iris(
        "Demo.MetaFixture",
        str(tmp_path),
        extract_meta=True,
        return_result=True,
    )

    assert result.warnings == []
    module_path = Path(result.files[0])
    generated_text = module_path.read_text(encoding="utf-8")
    assert "from iris_persistence import ClassMetadata, Field, Model" in generated_text
    assert "metadata = ClassMetadata(" in generated_text
    assert 'description="scaffolded class metadata"' in generated_text
    assert "deprecated=True" in generated_text
    assert "final=True" in generated_text
    assert 'sql_table_name="Demo_MetaFixture"' in generated_text
    assert "procedure_block=True" in generated_text

    module = _load_module(module_path)
    assert module.MetaFixture._class_metadata is not None
    assert module.MetaFixture._class_metadata.description == "scaffolded class metadata"
    assert module.MetaFixture._class_metadata.deprecated is True
    assert module.MetaFixture._class_metadata.final is True
    assert module.MetaFixture._class_metadata.sql_table_name == "Demo_MetaFixture"
    assert module.MetaFixture._class_metadata.procedure_block is True


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
            "SELECT Name, _Default, Origin FROM %Dictionary.CompiledParameter WHERE parent = ?",
            ("Demo.WarnFixture",),
        ): RuntimeError("parameter lookup failed"),
        (
            "SELECT Name, Properties, _Unique, Type, PrimaryKey "
            "FROM %Dictionary.CompiledIndex WHERE parent = ?",
            ("Demo.WarnFixture",),
        ): [],
        (
            (
                "SELECT Name, DataLocation, DefaultData, ExtentSize, IdLocation, "
                "IndexLocation, State, StreamLocation, Type "
                "FROM %Dictionary.CompiledStorage WHERE parent = ?"
            ),
            ("Demo.WarnFixture",),
        ): [],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    with pytest.raises(RuntimeError, match="parameter lookup failed"):
        scaffold_module.scaffold_from_iris(
            "Demo.*", str(tmp_path), extract_meta=True, return_result=True
        )

    with pytest.warns(RuntimeWarning, match="Failed to scaffold parameters"):
        result = scaffold_module.scaffold_from_iris(
            "Demo.*",
            str(tmp_path),
            extract_meta=True,
            return_result=True,
            best_effort=True,
        )

    assert result.files == [str(tmp_path / "warnfixture.py")]
    assert len(result.warnings) == 1
    assert result.warnings[0].code == "parameters"
    assert result.warnings[0].classname == "Demo.WarnFixture"

    module = _load_module(tmp_path / "warnfixture.py")
    assert module.WarnFixture._parameters == {}


def test_scaffold_parameter_fallback_excludes_inherited_parameters(monkeypatch, tmp_path: Path):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.ParamFixture",),
        ): [
            ("Demo.ParamFixture", "%Persistent"),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.ParamFixture",),
        ): [
            ("Title", "%Library.String", 1, None, None, "", "Title", 0),
        ],
        (
            "SELECT Name, _Default, Origin FROM %Dictionary.CompiledParameter WHERE parent = ?",
            ("Demo.ParamFixture",),
        ): [],
        (
            "SELECT Name, Default FROM %Dictionary.ParameterDefinition WHERE parent = ?",
            ("Demo.ParamFixture",),
        ): [],
    }
    runtime = _StubRuntimeWithParameters(
        rows_by_query,
        {
            "Demo.ParamFixture": [
                {"Name": "LOCAL_ONLY", "Default": "local", "Origin": "Demo.ParamFixture"},
                {"Name": "INHERITED", "Default": "base", "Origin": "Demo.BaseFixture"},
                {"Name": "GUID", "Default": "skip-guid", "Origin": "Demo.ParamFixture"},
                {"Name": "%INTERNAL", "Default": "skip-internal", "Origin": "Demo.ParamFixture"},
            ]
        },
    )

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: runtime)

    result = scaffold_module.scaffold_from_iris(
        "Demo.ParamFixture",
        str(tmp_path),
        extract_meta=True,
        return_result=True,
    )

    assert result.warnings == []
    module = _load_module(Path(result.files[0]))
    assert module.ParamFixture._parameters == {"LOCAL_ONLY": "local"}
    generated_text = Path(result.files[0]).read_text(encoding="utf-8")
    assert '"LOCAL_ONLY": "local"' in generated_text
    assert "INHERITED" not in generated_text


def test_scaffold_custom_storage_snapshots_writable_definition(monkeypatch, tmp_path: Path):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.CustomFixture",),
        ): [("Demo.CustomFixture", "%Persistent")],
        (
            "SELECT Name, Type, Required, InitialExpression, Parameters, Collection, "
            "SqlFieldName, ReadOnly FROM %Dictionary.CompiledProperty WHERE parent = ?",
            ("Demo.CustomFixture",),
        ): [
            (
                "Title",
                "%Library.String",
                1,
                None,
                _iris_dict({"MAXLEN": "120"}),
                "",
                "Title",
                0,
            )
        ],
        (
            "SELECT Name, _Default, Origin FROM %Dictionary.CompiledParameter WHERE parent = ?",
            ("Demo.CustomFixture",),
        ): [],
        (
            "SELECT Name, Properties, _Unique, Type, PrimaryKey "
            "FROM %Dictionary.CompiledIndex WHERE parent = ?",
            ("Demo.CustomFixture",),
        ): [],
    }
    runtime = _StubRuntime(rows_by_query)
    storage = StorageDefinition(
        name="CustomStorage",
        data_location="^Demo.CustomD",
        data=(
            StorageData(
                name="DefaultData",
                structure="listnode",
                values={"1": "Title"},
            ),
        ),
    )
    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: runtime)
    monkeypatch.setattr(
        scaffold_module,
        "inspect_existing_storage",
        lambda *_args, **_kwargs: storage,
    )

    result = scaffold_module.scaffold_from_iris(
        "Demo.CustomFixture", str(tmp_path), mode="managed", storage="custom", return_result=True
    )

    module = _load_module(Path(result.files[0]))
    assert module.CustomFixture._custom_storage.name == "CustomStorage"
    assert module.CustomFixture._custom_storage.data_location == "^Demo.CustomD"
    generated = Path(result.files[0]).read_text(encoding="utf-8")
    assert "from iris_persistence.advanced_storage import" in generated
    assert "custom_storage = StorageDefinition(" in generated


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
                "##class(Demo.Util.Clock).NowUTC()",
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
    basic_request_line = 'Request: Any | None = Field(iris_type="Demo.API.Request", default=None)'
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
        'Request: APIRequest | None = Field(iris_type="Demo.API.Request", default=None)'
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
        "Primary: VendorARequest | None = "
        'Field(iris_type="VendorA.Request", default=None)' in generated_text
    )
    assert (
        "Secondary: VendorBRequest | None = "
        'Field(iris_type="VendorB.Request", default=None)' in generated_text
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
        "Items: list[Item] | None = "
        "Field(iris_type=\"Demo.Item\", collection='list', default=None)" in generated_text
    )
    assert (
        "Entries: dict[str, LookupEntry] | None = "
        "Field(iris_type=\"Demo.LookupEntry\", collection='array', default=None)" in generated_text
    )


def test_scaffold_collection_class_types_are_typed_as_collections_without_collection_flag(
    monkeypatch,
    tmp_path: Path,
):
    rows_by_query = {
        (
            "SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?",
            ("Demo.ListFixture",),
        ): [
            ("Demo.ListFixture", "%Persistent"),
        ],
        (
            (
                "SELECT Name, Type, Required, InitialExpression, Parameters, "
                "Collection, SqlFieldName, ReadOnly "
                "FROM %Dictionary.CompiledProperty WHERE parent = ?"
            ),
            ("Demo.ListFixture",),
        ): [
            ("ListAttributes", "%List", 0, None, None, "", "ListAttributes", 0),
            ("ListDataType", "%ListOfDataTypes", 0, None, None, "", "ListDataType", 0),
            ("ArrayDataType", "%ArrayOfDataTypes", 0, None, None, "", "ArrayDataType", 0),
            ("ListOfObjects", "%ListOfObjects", 0, None, None, "", "ListOfObjects", 0),
            ("ArrayOfObjects", "%ArrayOfObjects", 0, None, None, "", "ArrayOfObjects", 0),
        ],
    }

    monkeypatch.setattr(scaffold_module, "get_runtime", lambda: _StubRuntime(rows_by_query))

    result = scaffold_module.scaffold_from_iris(
        "Demo.ListFixture",
        str(tmp_path),
        return_result=True,
    )

    assert result.warnings == []
    generated_text = (tmp_path / "listfixture.py").read_text(encoding="utf-8")
    assert (
        'ListAttributes: list[Any] | None = Field(iris_type="%List", default=None)'
        in generated_text
    )
    assert (
        "ListDataType: list[Any] | None = "
        'Field(iris_type="%ListOfDataTypes", default=None)' in generated_text
    )
    assert (
        "ArrayDataType: dict[str, Any] | None = "
        'Field(iris_type="%ArrayOfDataTypes", default=None)' in generated_text
    )
    assert (
        "ListOfObjects: list[Any] | None = "
        'Field(iris_type="%ListOfObjects", default=None)' in generated_text
    )
    assert (
        "ArrayOfObjects: dict[str, Any] | None = "
        'Field(iris_type="%ArrayOfObjects", default=None)' in generated_text
    )

    module = _load_module(tmp_path / "listfixture.py")
    ListFixture = module.ListFixture
    assert ListFixture._fields["ListAttributes"].iris_type == "%List"
    assert ListFixture._fields["ListDataType"].iris_type == "%ListOfDataTypes"
    assert ListFixture._fields["ArrayDataType"].iris_type == "%ArrayOfDataTypes"
    assert ListFixture._fields["ListOfObjects"].iris_type == "%ListOfObjects"
    assert ListFixture._fields["ArrayOfObjects"].iris_type == "%ArrayOfObjects"


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
    assert 'Child: ChildNode | None = Field(iris_type="Demo.ChildNode", default=None)' in root_text
    assert "from grandchildnode import GrandchildNode" in child_text
    assert (
        "Grandchild: GrandchildNode | None = "
        'Field(iris_type="Demo.GrandchildNode", default=None)' in child_text
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
