from __future__ import annotations

from iris_persistence import (
    ClassMetadata,
    Field,
    Index,
    Model,
    StorageData,
    StorageDefinition,
    StorageIndex,
    StorageProperty,
    StorageSQLMap,
    StorageSQLMapData,
    StorageSQLMapRowIdSpec,
    StorageSQLMapSub,
    StorageSQLMapSubAccessVar,
    StorageSQLMapSubInvalidCondition,
)


class SchemaMetadataFixture(Model, persistent=True):
    Payload: str | None = Field(
        default=None,
        max_length=50,
        readonly=True,
        collection="list",
        sql_field_name="payload_json",
    )

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
            indices=(
                StorageIndex(
                    name="PayloadStorageIdx",
                    location='^Demo.SchemaMetadataFixtureI("Payload")',
                    small_chunk_size="64",
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


class ExtendIndexFixture(Model, persistent=True):
    Payload: str | None = None

    class Meta:
        classname = "Demo.ExtendIndexFixture"
        mode = "extend"
        indexes = [
            Index("ExistingIdx", properties="Payload"),
            Index("PayloadIdx", properties="Payload", unique=True),
        ]


class ParameterFixture(Model, persistent=True):
    Payload: str | None = None

    class Meta:
        classname = "Demo.ParameterFixture"
        mode = "replace"
        parameters = {"TITI": "TOTO"}


class RelationshipMetadataFixture(Model, persistent=True):
    Owner: str | None = Field(
        default=None,
        iris_type="Demo.RelatedFixture",
        identity=True,
        relationship="parent",
        on_delete="cascade",
        inverse="Children",
        transient=True,
        storable=False,
        multi_dimensional=True,
    )

    class Meta:
        classname = "Demo.RelationshipMetadataFixture"
        mode = "replace"


class SQLProjectionMetadataFixture(Model, persistent=True):
    Tags: list[str] | None = Field(
        default=None,
        iris_type="%List",
        sql_list_delimiter="|",
        sql_list_type="DELIMITED",
    )
    TitleUpper: str | None = Field(
        default=None,
        sql_compute_code="Set {*} = {Title}",
        sql_compute_on_change="Title",
        sql_computed=True,
    )

    class Meta:
        classname = "Demo.SQLProjectionMetadataFixture"
        mode = "replace"


class ClassMetadataFixture(Model, persistent=True):
    Payload: str | None = None

    class Meta:
        classname = "Demo.ClassMetadataFixture"
        mode = "replace"
        metadata = ClassMetadata(
            description="schema metadata fixture",
            deprecated=True,
            final=True,
            sql_table_name="Demo_ClassMetadataFixture",
            procedure_block=True,
        )
