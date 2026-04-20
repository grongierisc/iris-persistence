from typing import Annotated

import iris_orm.schema as schema_module
from iris_orm import (
    Field,
    Index,
    IRISModel,
    StorageData,
    StorageDefinition,
    StorageProperty,
    StorageSQLMap,
    StorageSQLMapData,
    StorageSQLMapRowIdSpec,
    StorageSQLMapSub,
    StorageSQLMapSubAccessVar,
    StorageSQLMapSubInvalidCondition,
)
from iris_orm.schema import _map_python_type_to_iris


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
            self.Properties = _ListWrapper()
            self.Indices = _ListWrapper()
            self.Storages = _ListWrapper()
        elif class_name == "%Dictionary.PropertyDefinition":
            self.Parameters = _ListWrapper()
        elif class_name == "%Dictionary.StorageDefinition":
            self.Data = _ListWrapper()
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

    def extract_python_value(self, val):
        return val

    def inject_iris_value(self, obj, field_name, val):
        setattr(obj, field_name, val)


class SchemaMetadataFixture(IRISModel):
    Payload: Annotated[
        str | None,
        Field(
            required=False,
            maxlen=50,
            readonly=True,
            collection="list",
            sql_field_name="payload_json",
        ),
    ] = None

    class Meta:
        classname = "Demo.SchemaMetadataFixture"
        mode = "replace"
        indexes = [
            Index("PayloadIdx", properties="Payload", unique=True, primary_key=True, type="bitmap")
        ]
        storage = StorageDefinition(
            data_location="^Demo.SchemaMetadataFixtureD",
            default_data="SchemaMetadataFixtureDefaultData",
            extent_location="^Demo.SchemaMetadataFixtureExtent",
            extent_size="17",
            counter_location="^Demo.SchemaMetadataFixtureCounter",
            version_location="^Demo.SchemaMetadataFixtureVersion",
            id_location="^Demo.SchemaMetadataFixtureD",
            id_expression="{Payload}",
            id_function="Demo.SchemaMetadataFixtureId",
            index_location="^Demo.SchemaMetadataFixtureI",
            state="SchemaMetadataFixtureState",
            stream_location="^Demo.SchemaMetadataFixtureS",
            sql_child_sub="child",
            sql_id_expression="{%%ID}+1000",
            sql_row_id_name="RowID",
            sql_row_id_property="Payload",
            sql_table_number="42",
            sequence_number="9",
            data=(
                StorageData(
                    name="SchemaMetadataFixtureDefaultData",
                    structure="node",
                    attribute="Payload",
                    subscript='"Payload"',
                    values={"1": "Payload"},
                ),
            ),
            properties=(
                StorageProperty(
                    name="Payload",
                    average_field_size="10",
                    selectivity="0.001%",
                    outlier_selectivity='.999999:"payload"',
                    histogram="1:4,2:8",
                    child_block_count="3",
                    child_extent_size="11",
                    bias_queries_as_outlier=True,
                    stream_location="^Demo.SchemaMetadataFixturePayloadS",
                ),
            ),
            sql_maps=(
                StorageSQLMap(
                    name="PayloadMap",
                    block_count="-4",
                    condition="{Payload}'=''",
                    condition_fields="Payload",
                    conditional_with_host_vars=True,
                    global_name="^Demo.PayloadMapI",
                    population_pct="100",
                    population_type="FULL",
                    row_reference="RowRef",
                    structure="delimited",
                    type="index",
                    data=(
                        StorageSQLMapData(
                            name="PayloadData",
                            node="1",
                            piece="2",
                            delimiter="^",
                            retrieval_code="set {*}=$piece(x,^,2)",
                        ),
                    ),
                    row_id_specs=(
                        StorageSQLMapRowIdSpec(
                            name="1",
                            field="ID",
                            expression="{ID}",
                        ),
                    ),
                    subscripts=(
                        StorageSQLMapSub(
                            name="1",
                            access_type="piece",
                            data_access="Read",
                            delimiter="^",
                            expression="{Payload}",
                            loop_init_value="1",
                            next_code="set i=i+1",
                            null_marker="",
                            start_value="1",
                            stop_expression="i>10",
                            stop_value="10",
                            access_vars=(
                                StorageSQLMapSubAccessVar(
                                    name="1",
                                    variable="i",
                                    code="set i=1",
                                ),
                            ),
                            invalid_conditions=(
                                StorageSQLMapSubInvalidCondition(
                                    name="1",
                                    expression="i<1",
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )


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
