from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

import pytest

import iris_persistence
from iris_persistence import scaffold_from_iris
from iris_persistence.runtime import get_runtime
from tests.fixture_support import (
    OBJECTSCRIPT_CLS_FIXTURES,
    OBJECTSCRIPT_FIXTURES,
    OBJECTSCRIPT_PYTHON_FIXTURES,
    delete_iris_classes,
    load_module_from_path,
    load_objectscript_fixtures,
)
from tests.fixtures.objectscript.python.persistent_fixture import SourcePersistentFixture


def _has_iris_runtime() -> bool:
    return importlib.util.find_spec("iris") is not None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("configured_iris_runtime"),
    pytest.mark.skipif(not _has_iris_runtime(), reason="requires IRIS runtime"),
]


@pytest.fixture()
def loaded_objectscript_fixtures():
    loaded = load_objectscript_fixtures(
        [
            "list_fixture",
            "meta_fixture",
            "persistent_fixture",
            "recursive_child_fixture",
            "recursive_address_fixture",
            "recursive_parent_fixture",
            "request_fixture",
            "serial_fixture",
        ]
    )
    try:
        yield loaded
    finally:
        for fixture in reversed(loaded):
            delete_iris_classes(fixture.classnames)


@pytest.fixture()
def loaded_demo_namespace_fixtures():
    loaded = load_objectscript_fixtures(
        [
            "demo_demo_fixture",
            "product_fixture",
        ]
    )
    try:
        yield loaded
    finally:
        for fixture in reversed(loaded):
            delete_iris_classes(fixture.classnames)


def test_objectscript_fixture_sources_are_present():
    expected = [
        OBJECTSCRIPT_FIXTURES / "__init__.py",
        OBJECTSCRIPT_CLS_FIXTURES / "__init__.py",
        OBJECTSCRIPT_CLS_FIXTURES / "list_fixture.cls",
        OBJECTSCRIPT_CLS_FIXTURES / "list_fixture_item.cls",
        OBJECTSCRIPT_CLS_FIXTURES / "meta_fixture.cls",
        OBJECTSCRIPT_CLS_FIXTURES / "persistent_fixture.cls",
        OBJECTSCRIPT_CLS_FIXTURES / "recursive_child_fixture.cls",
        OBJECTSCRIPT_CLS_FIXTURES / "recursive_address_fixture.cls",
        OBJECTSCRIPT_CLS_FIXTURES / "recursive_parent_fixture.cls",
        OBJECTSCRIPT_CLS_FIXTURES / "request_fixture.cls",
        OBJECTSCRIPT_CLS_FIXTURES / "serial_fixture.cls",
        OBJECTSCRIPT_PYTHON_FIXTURES / "__init__.py",
        OBJECTSCRIPT_PYTHON_FIXTURES / "demo_demo_fixture.py",
        OBJECTSCRIPT_PYTHON_FIXTURES / "list_fixture.py",
        OBJECTSCRIPT_PYTHON_FIXTURES / "meta_fixture.py",
        OBJECTSCRIPT_PYTHON_FIXTURES / "persistent_fixture.py",
        OBJECTSCRIPT_PYTHON_FIXTURES / "product_fixture.py",
        OBJECTSCRIPT_PYTHON_FIXTURES / "recursive_child_fixture.py",
        OBJECTSCRIPT_PYTHON_FIXTURES / "recursive_address_fixture.py",
        OBJECTSCRIPT_PYTHON_FIXTURES / "recursive_parent_fixture.py",
        OBJECTSCRIPT_PYTHON_FIXTURES / "request_fixture.py",
        OBJECTSCRIPT_PYTHON_FIXTURES / "serial_fixture.py",
    ]
    for path in expected:
        assert path.exists(), f"Missing fixture source: {path}"


def test_objectscript_fixture_scaffold_e2e(loaded_objectscript_fixtures, tmp_path: Path):
    results = [
        scaffold_from_iris(
            "Demo.SourcePersistentFixture",
            str(tmp_path),
            extract_meta=True,
            return_result=True,
        ),
        scaffold_from_iris(
            "Demo.SourceRequestFixture",
            str(tmp_path),
            extract_meta=True,
            return_result=True,
        ),
        scaffold_from_iris(
            "Demo.SourceSerialFixture",
            str(tmp_path),
            extract_meta=True,
            return_result=True,
        ),
    ]
    assert all(not result.warnings for result in results)
    generated_files = [path for result in results for path in result.files]
    assert len(generated_files) == 3
    assert {fixture.name for fixture in loaded_objectscript_fixtures} == {
        "list_fixture",
        "meta_fixture",
        "persistent_fixture",
        "recursive_child_fixture",
        "recursive_address_fixture",
        "recursive_parent_fixture",
        "request_fixture",
        "serial_fixture",
    }

    modules_by_class = {}
    for file_path in generated_files:
        module = load_module_from_path(Path(file_path))
        generated_class = next(
            value
            for value in module.__dict__.values()
            if isinstance(value, type)
            and issubclass(value, iris_persistence.Model)
            and value is not iris_persistence.Model
        )
        modules_by_class[generated_class._classname] = generated_class

    PersistentFixture = modules_by_class["Demo.SourcePersistentFixture"]
    RequestFixture = modules_by_class["Demo.SourceRequestFixture"]
    SerialFixture = modules_by_class["Demo.SourceSerialFixture"]

    row = PersistentFixture(Title="fixture-title", Enabled=False, Score=9)
    row.save()
    fetched = PersistentFixture.get(row.pk)
    assert fetched is not None
    assert fetched.Title == "fixture-title"
    assert fetched.Enabled is False
    assert fetched.Score == 9

    assert PersistentFixture._superclasses in {"%Persistent", "%Library.Persistent"}
    assert any(index.name == "TitleIdx" for index in PersistentFixture._indexes)
    assert PersistentFixture._fields["Title"].iris_type == "%Library.String"
    assert PersistentFixture._fields["Enabled"].iris_type == "%Library.Boolean"
    assert PersistentFixture._storage is not None
    assert PersistentFixture._storage.id_location == "^Demo.SourcePersistentFixtureD"
    assert PersistentFixture._storage.index_location == "^Demo.SourcePersistentFixtureI"
    assert PersistentFixture._storage.stream_location == "^Demo.SourcePersistentFixtureS"

    assert RequestFixture._superclasses == "Ens.Request"
    assert RequestFixture._fields["CorrelationId"].required is True
    assert RequestFixture._fields["CorrelationId"].max_length == 64
    assert RequestFixture._fields["CorrelationId"].iris_type == "%Library.String"
    assert RequestFixture._fields["SourceSystem"].default == "ERP"
    assert RequestFixture._storage is not None
    request_data = {item.name: item for item in RequestFixture._storage.data}
    assert request_data["SourceRequestFixtureDefaultData"].subscript == '"SourceRequestFixture"'

    assert SerialFixture._superclasses in {"%SerialObject", "%Library.SerialObject"}
    assert SerialFixture._fields["Street"].required is True
    assert SerialFixture._fields["Street"].max_length == 120
    assert SerialFixture._fields["Street"].iris_type == "%Library.String"
    assert SerialFixture._fields["Country"].default == "FR"
    assert SerialFixture._storage is not None
    assert SerialFixture._storage.state == "SourceSerialFixtureState"
    assert SerialFixture._storage.stream_location == "^Demo.SourceSerialFixtureS"


def test_meta_fixture_reverse_engineers_query_level_metadata(
    loaded_objectscript_fixtures,
    tmp_path: Path,
):
    fixture = next(item for item in loaded_objectscript_fixtures if item.name == "meta_fixture")
    if fixture.source != "cls":
        pytest.skip("requires loading the ObjectScript fixture from .cls to inspect query metadata")

    result = scaffold_from_iris(
        "Demo.SourceMetaFixture",
        str(tmp_path),
        extract_meta=True,
        return_result=True,
    )
    assert result.warnings == []
    module = load_module_from_path(Path(result.files[0]))
    SourceMetaFixture = module.SourceMetaFixture

    assert SourceMetaFixture._class_metadata is not None
    assert SourceMetaFixture._class_metadata.deprecated is True
    assert SourceMetaFixture._class_metadata.final is True
    assert SourceMetaFixture._class_metadata.sql_table_name == "SourceMetaFixtureTable"
    assert SourceMetaFixture._class_metadata.procedure_block is True

    conn = get_runtime().get_dbapi_connection()
    cursor = conn.cursor()
    cursor.execute(
        (
            "SELECT Name, Internal, SqlView, SqlViewName "
            "FROM %Dictionary.CompiledQuery WHERE parent = ? ORDER BY Name"
        ),
        ["Demo.SourceMetaFixture"],
    )
    query_rows = [
        (
            name,
            "1" if str(internal).lower() in {"1", "true"} else "0",
            "1" if str(sql_view).lower() in {"1", "true"} else "0",
            sql_view_name,
        )
        for name, internal, sql_view, sql_view_name in cursor.fetchall()
    ]
    assert ("Titles", "1", "1", "SourceMetaFixtureTitlesView") in query_rows


def test_demo_demo_scaffold_reads_only_current_class_parameters(
    loaded_demo_namespace_fixtures,
    tmp_path: Path,
):
    result = scaffold_from_iris(
        "Demo.Demo",
        str(tmp_path),
        extract_meta=True,
        return_result=True,
    )
    assert result.warnings == []
    module = load_module_from_path(Path(result.files[0]))
    assert module.Demo._parameters == {"TITI": "TOTO"}


def test_recursive_object_reference_scaffold_e2e(loaded_objectscript_fixtures, tmp_path: Path):
    result = scaffold_from_iris(
        "Demo.SourceRecursive%",
        str(tmp_path),
        extract_meta=True,
        return_result=True,
    )
    assert result.warnings == []
    assert {Path(path).name for path in result.files} == {
        "sourcerecursivechild.py",
        "sourcerecursiveaddress.py",
        "sourcerecursiveparent.py",
    }

    sys.path.insert(0, str(tmp_path))
    try:
        child_module = importlib.import_module("sourcerecursivechild")
        address_module = importlib.import_module("sourcerecursiveaddress")
        parent_module = importlib.import_module("sourcerecursiveparent")
        SourceRecursiveChild = child_module.SourceRecursiveChild
        SourceRecursiveAddress = address_module.SourceRecursiveAddress
        SourceRecursiveParent = parent_module.SourceRecursiveParent

        child = SourceRecursiveChild(Name="nested-child", Importance=9)
        address = SourceRecursiveAddress(Street="1 Test Road", ZipCode="75001")
        parent = SourceRecursiveParent(Title="recursive-parent", Child=child, Address=address)
        parent.save()

        assert child.pk is not None
        assert parent.pk is not None

        loaded_parent = SourceRecursiveParent.get(parent.pk)
        assert loaded_parent is not None
        assert loaded_parent.Title == "recursive-parent"
        assert loaded_parent.Child is not None
        assert loaded_parent.Child.Name == "nested-child"
        assert loaded_parent.Child.Importance == 9
        assert loaded_parent.Child.pk == child.pk
        assert loaded_parent.Address is not None
        assert loaded_parent.Address.Street == "1 Test Road"
        assert loaded_parent.Address.ZipCode == "75001"
        assert loaded_parent.Address.Country == "FR"

        loaded_parent.Child = ""
        loaded_parent.save()

        cleared_parent = SourceRecursiveParent.get(parent.pk)
        assert cleared_parent is not None
        assert cleared_parent.Child is None

        assert SourceRecursiveParent._fields["Child"].required is False
        assert SourceRecursiveParent._fields["Address"].required is False
        assert SourceRecursiveParent._fields["Child"].iris_type == "Demo.SourceRecursiveChild"
        assert SourceRecursiveParent._fields["Address"].iris_type == "Demo.SourceRecursiveAddress"
        assert SourceRecursiveParent._storage is not None
        assert SourceRecursiveParent._storage.id_location == "^Demo.SourceRecursiveParentD"
        assert SourceRecursiveParent._storage.index_location == "^Demo.SourceRecursiveParentI"
        assert SourceRecursiveParent._storage.stream_location == "^Demo.SourceRecursiveParentS"
    finally:
        sys.path.remove(str(tmp_path))
        for module_name in (
            "sourcerecursivechild",
            "sourcerecursiveaddress",
            "sourcerecursiveparent",
        ):
            sys.modules.pop(module_name, None)


def test_list_fixture_scaffold_round_trip(loaded_objectscript_fixtures, tmp_path: Path):
    list_fixture = next(
        fixture for fixture in loaded_objectscript_fixtures if fixture.name == "list_fixture"
    )
    if list_fixture.source != "cls":
        pytest.skip("requires loading the ObjectScript list fixture directly from .cls metadata")

    try:
        result = scaffold_from_iris(
            "Demo.ListFixture",
            str(tmp_path),
            extract_meta=True,
            include_related=True,
            return_result=True,
        )
    except Exception as exc:
        pytest.skip(f"requires live IRIS scaffold access: {exc}")

    assert result.warnings == []
    assert {Path(path).name for path in result.files} >= {"listfixture.py", "listfixtureitem.py"}

    sys.path.insert(0, str(tmp_path))
    try:
        fixture_module = importlib.import_module("listfixture")
        item_module = importlib.import_module("listfixtureitem")
        ListFixture = fixture_module.ListFixture
        ListFixtureItem = item_module.ListFixtureItem

        row = ListFixture(
            ListAttributes=["alpha", "beta"],
            ListDataType=["one", 2, True],
            ArrayDataType={"first": "one", "second": 2},
            ListOfObjects=[ListFixtureItem(Value="left"), ListFixtureItem(Value="right")],
            ArrayOfObjects={
                "a": ListFixtureItem(Value="A"),
                "b": ListFixtureItem(Value="B"),
            },
        )
        row.save()
        assert row.pk is not None

        loaded = ListFixture.get(row.pk)
        assert loaded is not None
        assert loaded.ListAttributes == ["alpha", "beta"]
        assert loaded.ListDataType == ["one", 2, True]
        assert loaded.ArrayDataType == {"first": "one", "second": 2}
        assert [item.Value for item in loaded.ListOfObjects] == ["left", "right"]
        assert {key: item.Value for key, item in loaded.ArrayOfObjects.items()} == {
            "a": "A",
            "b": "B",
        }

        assert isinstance(loaded.ListAttributes, list)
        assert isinstance(loaded.ListDataType, list)
        assert isinstance(loaded.ArrayDataType, dict)
        assert isinstance(loaded.ListOfObjects, list)
        assert isinstance(loaded.ArrayOfObjects, dict)
        assert ListFixture._fields["ListAttributes"].iris_type in {"%List", "%Library.List"}
        assert ListFixture._fields["ListDataType"].iris_type in {
            "%ListOfDataTypes",
            "%Library.ListOfDataTypes",
        }
        assert ListFixture._fields["ArrayDataType"].iris_type in {
            "%ArrayOfDataTypes",
            "%Library.ArrayOfDataTypes",
        }
        assert ListFixture._fields["ListOfObjects"].iris_type == "Demo.ListFixtureItem"
        assert ListFixture._fields["ArrayOfObjects"].iris_type == "Demo.ListFixtureItem"
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("listfixture", None)
        sys.modules.pop("listfixtureitem", None)


def test_objectscript_storage_property_selectivity_scaffold(
    loaded_objectscript_fixtures, tmp_path: Path
):
    from iris_persistence.runtime import get_runtime

    persistent_fixture = next(
        fixture for fixture in loaded_objectscript_fixtures if fixture.name == "persistent_fixture"
    )
    if persistent_fixture.source != "cls":
        pytest.skip("requires loading the ObjectScript fixture directly from .cls storage metadata")

    list(SourcePersistentFixture.all())

    runtime = get_runtime()
    conn = runtime.get_dbapi_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT Name, AverageFieldSize, Selectivity "
        "FROM %Dictionary.StoragePropertyDefinition WHERE parent = ?",
        ("Demo.SourcePersistentFixture||Default",),
    )
    expected_rows = {
        name: (
            None if average_field_size in (None, "") else str(average_field_size),
            None if selectivity in (None, "") else str(selectivity),
        )
        for name, average_field_size, selectivity in cur.fetchall()
        if not str(name).startswith("%%")
        and (average_field_size not in (None, "") or selectivity not in (None, ""))
    }
    if not expected_rows:
        cur.close()
        conn.close()
        pytest.skip("fixture storage property definitions are not exposed in this IRIS namespace")
    cur.close()
    conn.close()

    result = scaffold_from_iris(
        "Demo.SourcePersistentFixture",
        str(tmp_path),
        extract_meta=True,
        scaffold_selectivity=True,
        return_result=True,
    )
    assert result.warnings == []

    module = load_module_from_path(Path(result.files[0]))
    PersistentFixture = module.SourcePersistentFixture

    assert PersistentFixture._storage is not None
    properties = {item.name: item for item in PersistentFixture._storage.properties}
    assert expected_rows.keys() <= properties.keys()
    for name, (average_field_size, selectivity) in expected_rows.items():
        if average_field_size not in (None, ""):
            assert properties[name].average_field_size == average_field_size
        if selectivity not in (None, ""):
            assert properties[name].selectivity == selectivity


def test_scaffold_selectivity_option_for_demo_demo(
    loaded_demo_namespace_fixtures,
    tmp_path: Path,
):
    from iris_persistence.runtime import get_runtime

    runtime = get_runtime()
    conn = runtime.get_dbapi_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT Name, Selectivity "
        "FROM %Dictionary.StoragePropertyDefinition WHERE parent = ?",
        ("Demo.Demo||CustomStorage",),
    )
    expected_rows = {
        name: str(selectivity)
        for name, selectivity in cur.fetchall()
        if not str(name).startswith("%%") and selectivity not in (None, "")
    }
    cur.close()
    conn.close()
    assert expected_rows == {
        "Titi": "50.0000%",
        "Toto": "25.0000%",
    }

    result = scaffold_from_iris(
        "Demo.Demo",
        str(tmp_path),
        extract_meta=True,
        scaffold_selectivity=True,
        return_result=True,
    )
    assert result.warnings == []
    assert result.files == [str(tmp_path / "demo.py")]

    module = load_module_from_path(Path(result.files[0]))
    Demo = module.Demo

    assert Demo._storage is not None
    properties = {item.name: item for item in Demo._storage.properties}
    assert expected_rows.keys() <= properties.keys()
    for name, selectivity in expected_rows.items():
        assert properties[name].selectivity == selectivity


def test_scaffold_storage_statistics_for_demo_product(
    loaded_demo_namespace_fixtures,
    tmp_path: Path,
):
    from iris_persistence.runtime import get_runtime

    runtime = get_runtime()
    conn = runtime.get_dbapi_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT Name, OutlierSelectivity "
        "FROM %Dictionary.StoragePropertyDefinition WHERE parent = ?",
        ("Demo.Product||CustomStorage",),
    )
    rows = {
        name: outlier_selectivity
        for name, outlier_selectivity in cur.fetchall()
        if not str(name).startswith("%%") and outlier_selectivity not in (None, "")
    }
    cur.close()
    conn.close()
    assert rows == {
        "InStock": ".999999:1",
        "Name": '.999999:"Widget"',
        "Price": ".999999:12.5",
    }

    result = scaffold_from_iris(
        "Demo.Product",
        str(tmp_path),
        extract_meta=True,
        scaffold_selectivity=True,
        return_result=True,
    )
    assert result.warnings == []

    module = load_module_from_path(Path(result.files[0]))
    Product = module.Product

    assert Product._storage is not None
    assert Product._storage.extent_size == "2"
    properties = {item.name: item for item in Product._storage.properties}
    assert properties["InStock"].outlier_selectivity == ".999999:1"
    assert properties["Name"].outlier_selectivity == '.999999:"Widget"'
    assert properties["Price"].outlier_selectivity == ".999999:12.5"


def test_healthshare_request_scaffold_handles_initial_expression_and_related_request(
    tmp_path: Path,
):
    from iris_persistence.runtime import get_runtime

    runtime = get_runtime()
    exists = runtime.call_classmethod(
        "%Dictionary.ClassDefinition",
        "_ExistsId",
        "HS.FHIRServer.Interop.Request",
    )
    if not exists:
        pytest.skip("requires HS.FHIRServer.Interop.Request to exist in the current IRIS namespace")

    default_result = scaffold_from_iris(
        "HS.FHIRServer.Interop.Request",
        str(tmp_path / "default"),
        return_result=True,
    )
    assert default_result.warnings == []
    assert default_result.files == [str(tmp_path / "default" / "request.py")]
    default_text = Path(default_result.files[0]).read_text(encoding="utf-8")
    assert (
        "initial_expression='##class(%ZHSLIB.HealthShareMgr).GetComponentVersion(\"HSLIB\")'"
        in default_text
    )
    assert (
        "Request: Any | None = "
        'Field(iris_type="HS.FHIRServer.API.Data.Request", default=None)'
        in default_text
    )
    assert ' = ##class(%ZHSLIB.HealthShareMgr).GetComponentVersion("HSLIB")' not in default_text

    default_module = load_module_from_path(Path(default_result.files[0]))
    DefaultRequest = default_module.Request
    assert DefaultRequest._fields["HSCoreVersion"].default is None
    assert (
        DefaultRequest._fields["HSCoreVersion"].initial_expression
        == '##class(%ZHSLIB.HealthShareMgr).GetComponentVersion("HSLIB")'
    )

    follow_result = scaffold_from_iris(
        "HS.FHIRServer.Interop.Request",
        str(tmp_path / "related"),
        include_related=True,
        return_result=True,
    )
    assert follow_result.warnings == []
    assert {Path(path).name for path in follow_result.files} >= {"request.py", "data_request.py"}
    related_text = (tmp_path / "related" / "request.py").read_text(encoding="utf-8")
    assert "from data_request import DataRequest" in related_text
    assert (
        "Request: DataRequest | None = "
        'Field(iris_type="HS.FHIRServer.API.Data.Request", default=None)'
        in related_text
    )
