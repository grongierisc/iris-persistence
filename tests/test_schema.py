import pytest

import iris_persistence.schema as schema_module
from iris_persistence import Field, Model
from iris_persistence.schema import _map_python_type_to_iris
from tests.fixtures.python.schema_mapping_fixtures import (
    ClassMetadataFixture,
    ExtendIndexFixture,
    ParameterFixture,
    RelationshipMetadataFixture,
    SchemaMetadataFixture,
    SQLProjectionMetadataFixture,
)


def test_field_iris_type_overrides_python_mapping():
    field = Field(iris_type="%Library.Numeric")

    assert _map_python_type_to_iris(str, field) == "%Library.Numeric"


def test_field_sql_type_alias_maps_to_iris_type():
    field = Field(sql_type="%Library.Currency")

    assert field.iris_type == "%Library.Currency"
    assert _map_python_type_to_iris(float, field) == "%Library.Currency"


class _ListWrapper:
    def __init__(self):
        self.items = []

    def Count(self):
        return len(self.items)

    def GetAt(self, index):
        return self.items[index - 1]

    def Insert(self, value):
        self.items.append(value)

    def SetAt(self, value, key):
        setattr(self, str(key), value)


class _RecordingObject:
    def __init__(self, class_name):
        self.__class_name = class_name
        if class_name == "%Dictionary.ClassDefinition":
            self.Parameters = _ListWrapper()
            self.Properties = _ListWrapper()
            self.Indices = _ListWrapper()
            self.Storages = _ListWrapper()
        elif class_name == "%Dictionary.PropertyDefinition":
            self.Parameters = _ListWrapper()
        elif class_name == "%Dictionary.StorageDefinition":
            self.Data = _ListWrapper()
            self.Indices = _ListWrapper()
            self.Properties = _ListWrapper()
            self.SQLMaps = _ListWrapper()
        elif class_name == "%Dictionary.StorageDataDefinition":
            self.Values = _ListWrapper()
        elif class_name == "%Dictionary.StorageSQLMapDefinition":
            self.Data = _ListWrapper()
            self.RowIdSpecs = _ListWrapper()
            self.Subscripts = _ListWrapper()
        elif class_name == "%Dictionary.StorageSQLMapSubDefinition":
            self.Accessvars = _ListWrapper()
            self.Invalidconditions = _ListWrapper()


class _RecordingRuntime:
    def __init__(self):
        self.created = []
        self.saved = []
        self.calls = []
        self.class_definition = None

    def call_classmethod(self, class_name, method_name, *args):
        self.calls.append((class_name, method_name, args))
        if class_name == "%Dictionary.ClassDefinition" and method_name == "_ExistsId":
            return False
        return 1

    def create_object(self, class_name):
        obj = _RecordingObject(class_name)
        self.created.append((class_name, obj))
        if class_name == "%Dictionary.ClassDefinition":
            self.class_definition = obj
        return obj

    def save_object(self, obj):
        self.saved.append(obj)
        return 1

    def get_object(self, class_name, obj_id):
        raise AssertionError("get_object should not be used in replace-mode schema test")

    def delete_object(self, class_name, obj_id):
        return True

    def get_dbapi_connection(self):
        raise AssertionError("dbapi connection not needed for schema sync test")

    def set_property(self, obj, prop_name, value):
        setattr(obj, prop_name, value)

    def get_property(self, obj, prop_name):
        return getattr(obj, prop_name)

    def invoke_method(self, obj, method_name, *args):
        return getattr(obj, method_name)(*args)

    def get_object_id(self, obj):
        return "1"

    def is_ok(self, status):
        return bool(status)

    def format_status(self, status):
        return str(status)

    def extract_python_value(self, val):
        return val

    def inject_iris_value(self, obj, field_name, val):
        setattr(obj, field_name, val)

    def decode_percent_list(self, value):
        return value


class _ExistingClassRuntime(_RecordingRuntime):
    def __init__(self):
        super().__init__()
        self.class_definition = _RecordingObject("%Dictionary.ClassDefinition")

    def call_classmethod(self, class_name, method_name, *args):
        self.calls.append((class_name, method_name, args))
        if class_name == "%Dictionary.ClassDefinition" and method_name == "_ExistsId":
            return True
        return 1

    def create_object(self, class_name):
        obj = _RecordingObject(class_name)
        self.created.append((class_name, obj))
        return obj

    def get_object(self, class_name, obj_id):
        if class_name == "%Dictionary.ClassDefinition":
            return self.class_definition
        raise AssertionError(f"unexpected get_object({class_name!r}, {obj_id!r})")


class _ExistingUserClassRuntime(_RecordingRuntime):
    def __init__(self, classname):
        super().__init__()
        self.existing_classname = classname
        self.class_definition = _RecordingObject("%Dictionary.ClassDefinition")
        self.class_definition.Name = classname

    def call_classmethod(self, class_name, method_name, *args):
        self.calls.append((class_name, method_name, args))
        if class_name == "%Dictionary.ClassDefinition" and method_name == "_ExistsId":
            return args[0] == self.existing_classname
        return 1

    def create_object(self, class_name):
        obj = _RecordingObject(class_name)
        self.created.append((class_name, obj))
        return obj

    def get_object(self, class_name, obj_id):
        if class_name == "%Dictionary.ClassDefinition" and obj_id == self.existing_classname:
            return self.class_definition
        raise AssertionError(f"unexpected get_object({class_name!r}, {obj_id!r})")


class _TransactionalRuntime(_RecordingRuntime):
    def __init__(self, fail_save_for=None):
        super().__init__()
        self.fail_save_for = fail_save_for
        self.transaction_events = []

    def begin_transaction(self):
        self.transaction_events.append("begin")

    def commit_transaction(self):
        self.transaction_events.append("commit")

    def rollback_transaction(self):
        self.transaction_events.append("rollback")

    def save_object(self, obj):
        self.saved.append(obj)
        if getattr(obj, "Name", None) == self.fail_save_for:
            return 0
        return 1


def test_sync_schema_writes_extended_metadata(monkeypatch):
    runtime = _RecordingRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    SchemaMetadataFixture.sync_schema()

    class_def = runtime.class_definition
    assert class_def is not None

    prop = class_def.Properties.items[0]
    assert prop.Name == "Payload"
    assert prop.Type == "%Library.String"
    assert prop.ReadOnly == 1
    assert prop.Collection == "list"
    assert prop.SqlFieldName == "payload_json"
    assert prop.Parameters.MAXLEN == "50"

    index = class_def.Indices.items[0]
    assert index.Name == "PayloadIdx"
    assert index.Properties == "Payload"
    assert index.Unique == 1
    assert index.Type == "bitmap"
    assert index.PrimaryKey == 1

    storage = class_def.Storages.items[0]
    assert storage.DataLocation == "^Demo.SchemaMetadataFixtureD"
    assert storage.DefaultData == "SchemaMetadataFixtureDefaultData"
    assert storage.ExtentLocation == "^Demo.SchemaMetadataFixtureExtent"
    assert storage.ExtentSize == "17"
    assert storage.CounterLocation == "^Demo.SchemaMetadataFixtureCounter"
    assert storage.VersionLocation == "^Demo.SchemaMetadataFixtureVersion"
    assert storage.IdLocation == "^Demo.SchemaMetadataFixtureD"
    assert storage.IdExpression == "{Payload}"
    assert storage.IdFunction == "Demo.SchemaMetadataFixtureId"
    assert storage.IndexLocation == "^Demo.SchemaMetadataFixtureI"
    assert storage.State == "SchemaMetadataFixtureState"
    assert storage.StreamLocation == "^Demo.SchemaMetadataFixtureS"
    assert storage.SqlChildSub == "child"
    assert storage.SqlIdExpression == "{%%ID}+1000"
    assert storage.SqlRowIdName == "RowID"
    assert storage.SqlRowIdProperty == "Payload"
    assert storage.SqlTableNumber == "42"
    assert storage.SequenceNumber == "9"

    storage_data = storage.Data.items[0]
    assert storage_data.Attribute == "Payload"
    assert storage_data.Subscript == '"Payload"'

    storage_index = storage.Indices.items[0]
    assert storage_index.Name == "PayloadStorageIdx"
    assert storage_index.Location == '^Demo.SchemaMetadataFixtureI("Payload")'
    assert storage_index.SmallChunkSize == "64"

    storage_property = storage.Properties.items[0]
    assert storage_property.Name == "Payload"
    assert storage_property.AverageFieldSize == "10"
    assert storage_property.Selectivity == "0.001%"
    assert storage_property.OutlierSelectivity == '.999999:"payload"'
    assert storage_property.Histogram == "1:4,2:8"
    assert storage_property.ChildBlockCount == "3"
    assert storage_property.ChildExtentSize == "11"
    assert storage_property.BiasQueriesAsOutlier == 1
    assert storage_property.StreamLocation == "^Demo.SchemaMetadataFixturePayloadS"

    sql_map = storage.SQLMaps.items[0]
    assert sql_map.Name == "PayloadMap"
    assert sql_map.BlockCount == "-4"
    assert sql_map.Condition == "{Payload}'=''"
    assert sql_map.ConditionFields == "Payload"
    assert sql_map.ConditionalWithHostVars == 1
    assert sql_map.Global == "^Demo.PayloadMapI"
    assert sql_map.PopulationPct == "100"
    assert sql_map.PopulationType == "FULL"
    assert sql_map.RowReference == "RowRef"
    assert sql_map.Structure == "delimited"
    assert sql_map.Type == "index"
    sql_map_data = sql_map.Data.items[0]
    assert sql_map_data.Name == "PayloadData"
    assert sql_map_data.Node == "1"
    assert sql_map_data.Piece == "2"
    assert sql_map_data.Delimiter == "^"
    assert sql_map_data.RetrievalCode == "set {*}=$piece(x,^,2)"
    row_id_spec = sql_map.RowIdSpecs.items[0]
    assert row_id_spec.Name == "1"
    assert row_id_spec.Field == "ID"
    assert row_id_spec.Expression == "{ID}"
    subscript = sql_map.Subscripts.items[0]
    assert subscript.Name == "1"
    assert subscript.AccessType == "piece"
    assert subscript.DataAccess == "Read"
    assert subscript.Delimiter == "^"
    assert subscript.Expression == "{Payload}"
    assert subscript.LoopInitValue == "1"
    assert subscript.NextCode == "set i=i+1"
    assert subscript.NullMarker == ""
    assert subscript.StartValue == "1"
    assert subscript.StopExpression == "i>10"
    assert subscript.StopValue == "10"
    access_var = subscript.Accessvars.items[0]
    assert access_var.Name == "1"
    assert access_var.Variable == "i"
    assert access_var.Code == "set i=1"
    invalid_condition = subscript.Invalidconditions.items[0]
    assert invalid_condition.Name == "1"
    assert invalid_condition.Expression == "i<1"

    assert (
        "%SYSTEM.OBJ",
        "Compile",
        ("Demo.SchemaMetadataFixture", "fc /display=none"),
    ) in runtime.calls


def test_sync_schema_writes_relationship_property_metadata(monkeypatch):
    runtime = _RecordingRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    RelationshipMetadataFixture.sync_schema()

    prop = runtime.class_definition.Properties.items[0]
    assert prop.Name == "Owner"
    assert prop.Type == "Demo.RelatedFixture"
    assert prop.Identity == 1
    assert prop.Relationship == "parent"
    assert prop.OnDelete == "cascade"
    assert prop.Inverse == "Children"
    assert prop.Transient == 1
    assert prop.Storable == 0
    assert prop.MultiDimensional == 1


def test_sync_schema_writes_class_parameters(monkeypatch):
    runtime = _RecordingRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    ParameterFixture.sync_schema()

    parameter = runtime.class_definition.Parameters.items[0]
    assert parameter.Name == "TITI"
    assert parameter.Default == "TOTO"


def test_sync_schema_writes_sql_projection_property_metadata(monkeypatch):
    runtime = _RecordingRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    SQLProjectionMetadataFixture.sync_schema()

    tags_prop = runtime.class_definition.Properties.items[0]
    title_upper_prop = runtime.class_definition.Properties.items[1]

    assert tags_prop.Name == "Tags"
    assert tags_prop.Type == "%List"
    assert tags_prop.SqlListDelimiter == "|"
    assert tags_prop.SqlListType == "DELIMITED"

    assert title_upper_prop.Name == "TitleUpper"
    assert title_upper_prop.Type == "%Library.String"
    assert title_upper_prop.SqlComputeCode == "Set {*} = {Title}"
    assert title_upper_prop.SqlComputeOnChange == "Title"
    assert title_upper_prop.SqlComputed == 1


def test_sync_schema_writes_class_metadata(monkeypatch):
    runtime = _RecordingRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    ClassMetadataFixture.sync_schema()

    class_def = runtime.class_definition
    assert class_def.Description == "schema metadata fixture"
    assert class_def.Deprecated == 1
    assert class_def.Final == 1
    assert class_def.SqlTableName == "Demo_ClassMetadataFixture"
    assert class_def.ProcedureBlock == 1


def test_sync_schema_extend_adds_missing_indexes_without_duplication(monkeypatch):
    runtime = _ExistingClassRuntime()
    existing_index = _RecordingObject("%Dictionary.IndexDefinition")
    existing_index.Name = "ExistingIdx"
    existing_index.Properties = "Payload"
    runtime.class_definition.Indices.Insert(existing_index)

    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    ExtendIndexFixture.sync_schema()

    indices = runtime.class_definition.Indices.items
    assert [index.Name for index in indices] == ["ExistingIdx", "PayloadIdx"]

    new_index = indices[1]
    assert new_index.Properties == "Payload"
    assert new_index.Unique == 1


def test_sync_schema_creates_unqualified_class_in_user_package(monkeypatch):
    class NewUnqualifiedSchemaFixture(Model, serial=True):
        Payload: str | None = None

    runtime = _RecordingRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    NewUnqualifiedSchemaFixture.sync_schema()

    assert runtime.class_definition.Name == "User.NewUnqualifiedSchemaFixture"
    prop = runtime.class_definition.Properties.items[0]
    assert prop.Name == "Payload"
    assert prop.parent == "User.NewUnqualifiedSchemaFixture"
    assert (
        "%SYSTEM.OBJ",
        "Compile",
        ("User.NewUnqualifiedSchemaFixture", "fc /display=none"),
    ) in runtime.calls


def test_sync_schema_extend_opens_existing_user_class_for_unqualified_model(monkeypatch):
    class ExistingUnqualifiedSchemaFixture(Model, serial=True):
        Payload: str | None = None

    runtime = _ExistingUserClassRuntime("User.ExistingUnqualifiedSchemaFixture")
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    ExistingUnqualifiedSchemaFixture.sync_schema()

    assert "%Dictionary.ClassDefinition" not in [
        class_name for class_name, _obj in runtime.created
    ]
    prop = runtime.class_definition.Properties.items[0]
    assert prop.Name == "Payload"
    assert prop.parent == "User.ExistingUnqualifiedSchemaFixture"
    assert (
        "%SYSTEM.OBJ",
        "Compile",
        ("User.ExistingUnqualifiedSchemaFixture", "fc /display=none"),
    ) in runtime.calls


def test_sync_schema_commits_top_level_transaction(monkeypatch):
    runtime = _TransactionalRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    ParameterFixture.sync_schema()

    assert runtime.transaction_events == ["begin", "commit"]


def test_sync_schema_rolls_back_recursive_sync_on_failure(monkeypatch):
    class SchemaRollbackChild(Model, serial=True):
        Payload: str | None = None

        class Meta:
            classname = "Demo.SchemaRollbackChild"

    class SchemaRollbackParent(Model, persistent=True):
        Child: SchemaRollbackChild | None = None

        class Meta:
            classname = "Demo.SchemaRollbackParent"

    runtime = _TransactionalRuntime(fail_save_for="Demo.SchemaRollbackParent")
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    with pytest.raises(RuntimeError, match="Schema save failed for Demo.SchemaRollbackParent"):
        SchemaRollbackParent.sync_schema()

    assert runtime.transaction_events == ["begin", "rollback"]
    assert [obj.Name for obj in runtime.saved] == [
        "Demo.SchemaRollbackChild",
        "Demo.SchemaRollbackParent",
    ]
    assert (
        "%SYSTEM.OBJ",
        "Compile",
        ("Demo.SchemaRollbackChild", "fc /display=none"),
    ) in runtime.calls
    assert (
        "%SYSTEM.OBJ",
        "Compile",
        ("Demo.SchemaRollbackParent", "fc /display=none"),
    ) not in runtime.calls


def test_diff_schema_reports_planned_changes_without_writing(monkeypatch):
    runtime = _RecordingRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    diff = ParameterFixture.sync_schema(dry_run=True)

    assert isinstance(diff, schema_module.SchemaDiff)
    assert diff.has_changes is True
    assert runtime.saved == []
    assert runtime.class_definition is None
    rendered = diff.to_unified_diff()
    assert "class Demo.ParameterFixture" in rendered
    assert "+super %Persistent" in rendered
    assert "+parameter TITI='TOTO'" in rendered
    assert "+property Payload type='%Library.String'" in rendered


def test_diff_schema_includes_storage_property_metadata(monkeypatch):
    runtime = _RecordingRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    diff = SchemaMetadataFixture.diff_schema()

    rendered = diff.to_unified_diff()
    assert "+storage data_location='^Demo.SchemaMetadataFixtureD'" in rendered
    assert "+storage_property Payload average_field_size='10'" in rendered
    assert "selectivity='0.001%'" in rendered
