import decimal
from contextlib import contextmanager

import pytest

import iris_persistence.runtime as runtime_module
import iris_persistence.schema as schema_module
import iris_persistence.schema.inspection as schema_inspection_module
from iris_persistence import Field, Index, Model, StorageMigrationRequired, StorageTuning
from iris_persistence.advanced_storage import (
    StorageProperty,
    inspect_existing_storage,
    tune_existing_storage_statistics,
)
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
    field = Field(iris_type="%Library.Currency")

    assert field.iris_type == "%Library.Currency"
    assert _map_python_type_to_iris(float, field) == "%Library.Currency"


@pytest.mark.parametrize("py_type", [float, float | None])
def test_float_maps_to_double(py_type):
    assert _map_python_type_to_iris(py_type, Field()) == "%Library.Double"


@pytest.mark.parametrize("py_type", [decimal.Decimal, decimal.Decimal | None])
def test_decimal_maps_to_decimal(py_type):
    assert _map_python_type_to_iris(py_type, Field()) == "%Library.Decimal"


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

    def RemoveAt(self, index):
        del self.items[index - 1]

    def DeleteAt(self, index):
        self.RemoveAt(index)

    def Remove(self, index):
        self.RemoveAt(index)


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

    def new_object(self, class_name):
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

    def begin_transaction(self):
        pass

    def commit_transaction(self):
        pass

    def rollback_transaction(self):
        pass

    @contextmanager
    def transaction(self):
        self.begin_transaction()
        try:
            yield
        except Exception:
            self.rollback_transaction()
            raise
        self.commit_transaction()

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

    def check_status(self, status, operation):
        if not self.is_ok(status):
            raise RuntimeError(f"{operation} failed: {self.format_status(status)}")

    def compile_class(self, class_name, flags="fc /display=none"):
        status = self.call_classmethod("%SYSTEM.OBJ", "Compile", class_name, flags)
        self.check_status(status, f"compile {class_name}")

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

    def new_object(self, class_name):
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

    def new_object(self, class_name):
        obj = _RecordingObject(class_name)
        self.created.append((class_name, obj))
        return obj

    def get_object(self, class_name, obj_id):
        if class_name == "%Dictionary.ClassDefinition" and obj_id == self.existing_classname:
            return self.class_definition
        raise AssertionError(f"unexpected get_object({class_name!r}, {obj_id!r})")


class _TransactionalRuntime(_RecordingRuntime):
    def __init__(self, fail_save_for=None, fail_compile_for=None):
        super().__init__()
        self.fail_save_for = fail_save_for
        self.fail_compile_for = fail_compile_for
        self.transaction_events = []

    def call_classmethod(self, class_name, method_name, *args):
        self.calls.append((class_name, method_name, args))
        if class_name == "%Dictionary.ClassDefinition" and method_name == "_ExistsId":
            return False
        if (
            class_name == "%SYSTEM.OBJ"
            and method_name == "Compile"
            and args
            and args[0] == self.fail_compile_for
        ):
            return 0
        return 1

    def begin_transaction(self):
        self.transaction_events.append("begin")

    def commit_transaction(self):
        self.transaction_events.append("commit")

    def rollback_transaction(self):
        self.transaction_events.append("rollback")

    def save_object(self, obj):
        self.saved.append(obj)
        if self.fail_save_for is not None and getattr(obj, "Name", None) == self.fail_save_for:
            return 0
        return 1


def test_sync_schema_writes_decimal_scale_for_decimal(monkeypatch):
    class DecimalScaleModel(Model):
        Price: decimal.Decimal | None = None

        class Meta:
            classname = "Demo.DecimalScaleModel"
            mode = "managed"

    runtime = _RecordingRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    DecimalScaleModel.sync_schema()

    prop = runtime.class_definition.Properties.items[0]
    assert prop.Name == "Price"
    assert prop.Type == "%Library.Decimal"
    assert prop.Parameters.SCALE == "18"


def test_sync_schema_writes_decimal_scale_for_explicit_float_decimal(monkeypatch):
    class ExplicitFloatDecimalScaleModel(Model):
        Price: float | None = Field(default=None, iris_type="%Library.Decimal")

        class Meta:
            classname = "Demo.ExplicitFloatDecimalScaleModel"
            mode = "managed"

    runtime = _RecordingRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    ExplicitFloatDecimalScaleModel.sync_schema()

    prop = runtime.class_definition.Properties.items[0]
    assert prop.Name == "Price"
    assert prop.Type == "%Library.Decimal"
    assert prop.Parameters.SCALE == "18"


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
    assert storage.Name == "CustomStorage"
    assert class_def.StorageStrategy == "CustomStorage"
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


def test_sync_schema_preseeds_minimal_default_storage_tuning(monkeypatch):
    class TunedModel(Model, persistent=True):
        Name: str | None = None

        class Meta:
            classname = "Demo.TunedModel"
            mode = "managed"
            storage_tuning = StorageTuning(
                data_location="^Demo.TunedD",
                index_location="^Demo.TunedI",
                index_locations={"NameIdx": '^Demo.TunedI("NameIdx")'},
            )

    runtime = _RecordingRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    TunedModel.sync_schema()

    storage = runtime.class_definition.Storages.items[0]
    assert storage.Name == "Default"
    assert storage.Type == "%Storage.Persistent"
    assert storage.DataLocation == "^Demo.TunedD"
    assert storage.IndexLocation == "^Demo.TunedI"
    assert not hasattr(storage, "Data") or storage.Data.items == []
    assert storage.Indices.items[0].Name == "NameIdx"
    assert storage.Indices.items[0].Location == '^Demo.TunedI("NameIdx")'
    assert not hasattr(runtime.class_definition, "StorageStrategy")


def test_sync_schema_blocks_post_compile_storage_relocation_before_mutation(monkeypatch):
    class RelocatedModel(Model, persistent=True):
        Name: str | None = None

        class Meta:
            classname = "Demo.RelocatedModel"
            mode = "managed"
            storage_tuning = StorageTuning(data_location="^Demo.NewD")

    runtime = _ExistingClassRuntime()
    runtime.class_definition.Name = "Demo.RelocatedModel"
    runtime.class_definition.Super = "%Persistent"
    storage = _RecordingObject("%Dictionary.StorageDefinition")
    storage.Name = "Default"
    storage.Type = "%Storage.Persistent"
    storage.DataLocation = "^Demo.OldD"
    runtime.class_definition.Storages.Insert(storage)
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    with pytest.raises(StorageMigrationRequired, match="explicit data migration"):
        RelocatedModel.sync_schema()

    assert runtime.saved == []
    assert runtime.created == []
    diff = schema_module.diff_schema(RelocatedModel)
    assert any(operation.op_type == "blocked_storage_change" for operation in diff.operations)


def test_generated_default_storage_is_excluded_without_declaration(monkeypatch):
    class CompilerOwnedModel(Model, persistent=True):
        Name: str | None = None

        class Meta:
            classname = "Demo.CompilerOwnedModel"
            mode = "managed"

    runtime = _ExistingClassRuntime()
    runtime.class_definition.Name = "Demo.CompilerOwnedModel"
    runtime.class_definition.Super = "%Persistent"
    generated = _RecordingObject("%Dictionary.StorageDefinition")
    generated.Name = "Default"
    generated.DataLocation = "^Compiler.GeneratedD"
    runtime.class_definition.Storages.Insert(generated)
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    diff = schema_module.diff_schema(CompilerOwnedModel)

    assert diff.before_state.storage is None
    assert diff.after_state.storage is None
    assert all(operation.path != "storage" for operation in diff.operations)


def test_explicit_existing_storage_statistics_tuning(monkeypatch):
    runtime = _ExistingClassRuntime()
    runtime.class_definition.Name = "Demo.ExistingTuning"
    runtime.class_definition.Super = "%Persistent"
    storage = _RecordingObject("%Dictionary.StorageDefinition")
    storage.Name = "Default"
    runtime.class_definition.Storages.Insert(storage)
    monkeypatch.setattr(runtime_module, "get_runtime", lambda: runtime)

    result = tune_existing_storage_statistics(
        "Demo.ExistingTuning",
        properties=(
            StorageProperty(
                name="Name",
                average_field_size="32",
                selectivity="5.0000%",
            ),
        ),
    )

    tuned = storage.Properties.items[0]
    assert tuned.Name == "Name"
    assert tuned.AverageFieldSize == "32"
    assert tuned.Selectivity == "5.0000%"
    assert result.storage_name == "Default"
    assert result.updated_properties == ("Name",)
    assert ("%SYSTEM.OBJ", "Compile", ("Demo.ExistingTuning", "fc /display=none")) in runtime.calls


def test_existing_storage_statistics_reject_physical_locations():
    with pytest.raises(ValueError, match="physical storage"):
        tune_existing_storage_statistics(
            "Demo.ExistingTuning",
            properties=(StorageProperty(name="Name", stream_location="^Moved.Stream"),),
        )


def test_inspect_existing_storage_returns_typed_writable_snapshot(monkeypatch):
    state = schema_module.SchemaState.from_dict(
        {
            "classname": "Demo.ExistingTuning",
            "super": "%Persistent",
            "storage": {
                "name": "Default",
                "attrs": {
                    "type": "%Storage.Persistent",
                    "data_location": "^Demo.ExistingD",
                },
                "data": {
                    "DefaultData": {
                        "structure": "listnode",
                        "values": {"1": "Name"},
                    }
                },
                "properties": {"Name": {"selectivity": "5.0000%"}},
            },
        }
    )
    monkeypatch.setattr(runtime_module, "get_runtime", lambda: object())
    monkeypatch.setattr(
        schema_inspection_module,
        "_collect_live_schema_state",
        lambda *_args, **_kwargs: state,
    )

    snapshot = inspect_existing_storage("Demo.ExistingTuning")

    assert snapshot.name == "Default"
    assert snapshot.data_location == "^Demo.ExistingD"
    assert snapshot.data[0].values == {"1": "Name"}
    assert snapshot.properties[0].selectivity == "5.0000%"


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


class ManagedSchemaFixture(Model, persistent=True):
    NewName: str | None = None
    Items: list[str] = Field(default_factory=list)

    class Meta:
        classname = "Demo.ManagedSchemaFixture"
        mode = "managed"
        parameters = {"NEWPARAM": "new"}
        indexes = [Index("NewNameIdx", properties="NewName")]


def _managed_existing_runtime():
    runtime = _ExistingClassRuntime()
    runtime.class_definition.Name = "Demo.ManagedSchemaFixture"
    runtime.class_definition.Super = "%Persistent"

    old_parameter = _RecordingObject("%Dictionary.ParameterDefinition")
    old_parameter.Name = "OLDPARAM"
    old_parameter.Default = "old"
    runtime.class_definition.Parameters.Insert(old_parameter)

    old_property = _RecordingObject("%Dictionary.PropertyDefinition")
    old_property.Name = "OldName"
    old_property.Type = "%Library.String"
    runtime.class_definition.Properties.Insert(old_property)

    existing_property = _RecordingObject("%Dictionary.PropertyDefinition")
    existing_property.Name = "NewName"
    existing_property.Type = "%Library.Integer"
    runtime.class_definition.Properties.Insert(existing_property)

    existing_collection_property = _RecordingObject("%Dictionary.PropertyDefinition")
    existing_collection_property.Name = "Items"
    existing_collection_property.Type = "%Library.String"
    existing_collection_property.Required = 1
    existing_collection_property.InitialExpression = '"old"'
    existing_collection_property.Parameters.SetAt("10", "MAXLEN")
    runtime.class_definition.Properties.Insert(existing_collection_property)

    inherited_property = _RecordingObject("%Dictionary.PropertyDefinition")
    inherited_property.Name = "InheritedName"
    inherited_property.Type = "%Library.String"
    inherited_property.Inherited = 1
    runtime.class_definition.Properties.Insert(inherited_property)

    old_index = _RecordingObject("%Dictionary.IndexDefinition")
    old_index.Name = "OldIdx"
    old_index.Properties = "OldName"
    runtime.class_definition.Indices.Insert(old_index)
    return runtime


def test_diff_schema_managed_plans_targeted_member_deletes(monkeypatch):
    runtime = _managed_existing_runtime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    diff = schema_module.diff_schema(ManagedSchemaFixture)

    managed_delete_ops = {
        (operation.op_type, operation.path, operation.safety)
        for operation in diff.operations
        if operation.safety == "managed-delete"
    }
    assert ("delete_parameter", "parameters.OLDPARAM", "managed-delete") in managed_delete_ops
    assert ("delete_property", "properties.OldName", "managed-delete") in managed_delete_ops
    assert ("delete_index", "indexes.OldIdx", "managed-delete") in managed_delete_ops
    assert ("update_property", "properties.NewName", "managed-update") in {
        (operation.op_type, operation.path, operation.safety)
        for operation in diff.operations
        if operation.safety == "managed-update"
    }
    assert ("update_property", "properties.Items", "managed-update") in {
        (operation.op_type, operation.path, operation.safety)
        for operation in diff.operations
        if operation.safety == "managed-update"
    }
    items_operation = next(
        operation
        for operation in diff.operations
        if operation.op_type == "update_property" and operation.path == "properties.Items"
    )
    assert items_operation.after["collection"] == "list"
    assert all(operation.path != "properties.InheritedName" for operation in diff.operations)


def test_sync_schema_managed_removes_owned_members_without_rebuilding_class(monkeypatch):
    runtime = _managed_existing_runtime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    ManagedSchemaFixture.sync_schema()

    assert [parameter.Name for parameter in runtime.class_definition.Parameters.items] == [
        "NEWPARAM"
    ]
    existing_new_name = next(
        prop for prop in runtime.class_definition.Properties.items if prop.Name == "NewName"
    )
    assert [prop.Name for prop in runtime.class_definition.Properties.items] == [
        "NewName",
        "Items",
        "InheritedName",
    ]
    assert existing_new_name.Type == "%Library.String"
    existing_items = next(
        prop for prop in runtime.class_definition.Properties.items if prop.Name == "Items"
    )
    assert existing_items.Type == "%Library.String"
    assert existing_items.Collection == "list"
    assert existing_items.Required == 0
    assert existing_items.InitialExpression == ""
    assert existing_items.Parameters.MAXLEN == ""
    assert [index.Name for index in runtime.class_definition.Indices.items] == ["NewNameIdx"]
    assert (
        "%SYSTEM.OBJ",
        "Delete",
        ("Demo.ManagedSchemaFixture", "-d"),
    ) not in runtime.calls
    assert (
        "%SYSTEM.OBJ",
        "Compile",
        ("Demo.ManagedSchemaFixture", "fc /display=none"),
    ) in runtime.calls


def _property_snapshot(prop):
    params = prop.Parameters
    return {
        "Type": getattr(prop, "Type", None),
        "Required": getattr(prop, "Required", None),
        "ReadOnly": getattr(prop, "ReadOnly", None),
        "Collection": getattr(prop, "Collection", None),
        "SqlFieldName": getattr(prop, "SqlFieldName", None),
        "Identity": getattr(prop, "Identity", None),
        "Relationship": getattr(prop, "Relationship", None),
        "OnDelete": getattr(prop, "OnDelete", None),
        "Inverse": getattr(prop, "Inverse", None),
        "Transient": getattr(prop, "Transient", None),
        "Storable": getattr(prop, "Storable", None),
        "MultiDimensional": getattr(prop, "MultiDimensional", None),
        "SqlListDelimiter": getattr(prop, "SqlListDelimiter", None),
        "SqlListType": getattr(prop, "SqlListType", None),
        "SqlComputeCode": getattr(prop, "SqlComputeCode", None),
        "SqlComputeOnChange": getattr(prop, "SqlComputeOnChange", None),
        "SqlComputed": getattr(prop, "SqlComputed", None),
        "InitialExpression": getattr(prop, "InitialExpression", None),
        "MAXLEN": getattr(params, "MAXLEN", None),
        "SCALE": getattr(params, "SCALE", None),
    }


def test_property_definition_create_and_update_apply_same_state():
    runtime = _RecordingRuntime()
    property_state = {
        "type": "%Library.String",
        "required": True,
        "readonly": True,
        "collection": "list",
        "sql_field_name": "item_sql",
        "identity": True,
        "relationship": "children",
        "on_delete": "cascade",
        "inverse": "Parent",
        "transient": True,
        "storable": False,
        "multi_dimensional": True,
        "sql_list_delimiter": "|",
        "sql_list_type": "DELIMITED",
        "sql_compute_code": "Set {*} = {Name}",
        "sql_compute_on_change": "Name",
        "sql_computed": True,
        "initial_expression": '"new"',
        "max_length": "80",
        "scale": "2",
    }

    created = schema_module._build_property_definition_from_state(
        runtime,
        "Demo.PropertyParity",
        "Items",
        property_state,
    )
    updated = _RecordingObject("%Dictionary.PropertyDefinition")
    schema_module._apply_property_definition_state(runtime, updated, property_state, exact=True)

    assert _property_snapshot(created) == _property_snapshot(updated)


def test_property_definition_update_clears_absent_metadata_exactly():
    runtime = _RecordingRuntime()
    prop = _RecordingObject("%Dictionary.PropertyDefinition")
    prop.Type = "%Library.Integer"
    prop.Required = 1
    prop.ReadOnly = 1
    prop.Collection = "list"
    prop.SqlFieldName = "old_sql"
    prop.Identity = 1
    prop.Relationship = "children"
    prop.OnDelete = "cascade"
    prop.Inverse = "Parent"
    prop.Transient = 1
    prop.Storable = 0
    prop.MultiDimensional = 1
    prop.SqlListDelimiter = "|"
    prop.SqlListType = "DELIMITED"
    prop.SqlComputeCode = "Set {*} = {Name}"
    prop.SqlComputeOnChange = "Name"
    prop.SqlComputed = 1
    prop.InitialExpression = '"old"'
    prop.Parameters.SetAt("80", "MAXLEN")
    prop.Parameters.SetAt("2", "SCALE")

    schema_module._apply_property_definition_state(
        runtime,
        prop,
        {"type": "%Library.String"},
        exact=True,
    )

    assert prop.Type == "%Library.String"
    assert prop.Required == 0
    assert prop.ReadOnly == 0
    assert prop.Collection == ""
    assert prop.SqlFieldName == ""
    assert prop.Identity == 0
    assert prop.Relationship == ""
    assert prop.OnDelete == ""
    assert prop.Inverse == ""
    assert prop.Transient == 0
    assert prop.Storable == 1
    assert prop.MultiDimensional == 0
    assert prop.SqlListDelimiter == ""
    assert prop.SqlListType == ""
    assert prop.SqlComputeCode == ""
    assert prop.SqlComputeOnChange == ""
    assert prop.SqlComputed == 0
    assert prop.InitialExpression == ""
    assert prop.Parameters.MAXLEN == ""
    assert prop.Parameters.SCALE == ""


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

    assert "%Dictionary.ClassDefinition" not in [class_name for class_name, _obj in runtime.created]
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

    with pytest.raises(RuntimeError, match="schema save Demo.SchemaRollbackParent failed"):
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


def test_sync_schema_rolls_back_compile_failure(monkeypatch):
    runtime = _TransactionalRuntime(fail_compile_for="Demo.ParameterFixture")
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    with pytest.raises(RuntimeError, match="compile Demo.ParameterFixture failed"):
        ParameterFixture.sync_schema()

    assert runtime.transaction_events == ["begin", "rollback"]


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
    assert "+storage_data SchemaMetadataFixtureDefaultData" in rendered
    assert "+storage_data_value SchemaMetadataFixtureDefaultData.1='Payload'" in rendered
    assert "+storage_index PayloadStorageIdx" in rendered
    assert "+storage_property Payload average_field_size='10'" in rendered
    assert "+storage_sql_map PayloadMap" in rendered
    assert "+storage_sql_map_data PayloadMap.PayloadData" in rendered
    assert "+storage_sql_map_row_id_spec PayloadMap.1" in rendered
    assert "+storage_sql_map_subscript PayloadMap.1" in rendered
    assert "+storage_sql_map_sub_access_var PayloadMap.1.1" in rendered
    assert "+storage_sql_map_sub_invalid_condition PayloadMap.1.1" in rendered
    assert "selectivity='0.001%'" in rendered


def test_diff_schema_exposes_structured_operations(monkeypatch):
    runtime = _RecordingRuntime()
    monkeypatch.setattr(schema_module, "get_runtime", lambda: runtime)

    diff = ParameterFixture.diff_schema()

    assert diff.before_state is not None
    assert diff.after_state is not None
    assert [operation.op_type for operation in diff.operations] == [
        "create_class",
        "update_super",
        "add_parameter",
        "add_property",
        "compile_class",
    ]
    assert [operation.path for operation in diff.operations] == [
        "class",
        "super",
        "parameters.TITI",
        "properties.Payload",
        "compile",
    ]
