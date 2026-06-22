# Advanced Schema Mapping

This document maps `iris_persistence`'s Python model metadata to the IRIS class dictionary,
SQL projection, and physical storage metadata.

`iris_persistence` works across three layers:

- Python model definition: `Model`, `Field(...)`, `Index(...)`, `StorageDefinition(...)`
- IRIS class metadata: `%Dictionary.*Definition` and `%Dictionary.Compiled*`
- SQL/storage projection: projected SQL table/column/index shape plus global storage layout

## Mental Model

`iris_persistence` does not generate standalone SQL DDL directly.
It writes IRIS class metadata, and IRIS projects that metadata into SQL schema.

In practice:

- `Model.sync_schema()` writes `%Dictionary.ClassDefinition`, `%Dictionary.PropertyDefinition`,
  `%Dictionary.IndexDefinition`, and storage metadata
- IRIS compiles the class
- the compiled class becomes the source of truth for the SQL projection
- `scaffold_from_iris()` reads `%Dictionary.Compiled*` metadata back into Python
- `scaffold_from_iris(..., scaffold_selectivity=True)` also enriches storage-property statistics
  from `%Dictionary.StoragePropertyDefinition` when compiled storage-property rows are sparse
- `scaffold_from_iris(..., extract_hidden_meta=True)` also includes dictionary-only storage metadata
  that is not normally represented in the UDL/XML storage block

## Meta Mapping

| Python `Meta` attribute | IRIS metadata target | SQL / runtime effect |
| --- | --- | --- |
| `classname` | `%Dictionary.ClassDefinition.Name` | Defines the IRIS class name; SQL table naming is derived by IRIS from the class unless separately customized in IRIS |
| `mode` | no direct dictionary field | Controls ownership behavior in `iris_persistence`: `managed`, `extend`, `replace`, `observe`; default is `managed` |
| `auto_sync` | no direct dictionary field | When `True`, `save()` runs `sync_schema()` automatically before writing; blocked for `observe` and `replace` |
| `superclasses` | `%Dictionary.ClassDefinition.Super` | Controls whether the class is `%Persistent`, `%SerialObject`, `Ens.Request`, etc., which changes table projection and object behavior |
| `metadata=ClassMetadata(...)` | `%Dictionary.ClassDefinition` scalar flags | Class-level descriptive, compiler-facing, and SQL projection metadata |
| `parameters` | `%Dictionary.ParameterDefinition` and `%Dictionary.ClassDefinition.Parameters` | IRIS class parameters; some may affect SQL/storage behavior depending on IRIS semantics |
| `indexes` | `%Dictionary.IndexDefinition` | Projects SQL indexes and related access paths |
| `storage` | `%Dictionary.StorageDefinition` and children | Controls physical storage layout and custom SQL map projection |

## Mode Semantics

| Mode | IRIS write behavior | Use case |
| --- | --- | --- |
| `managed` | Adds/updates Python-declared members and removes omitted Python-owned parameters, properties, and indexes | Migration-controlled production classes |
| `extend` | Adds/updates Python-declared members, keeps unrelated IRIS metadata | Brownfield classes and auto-sync demos |
| `replace` | Rebuilds the class from Python metadata | Python-owned destructive rebuilds |
| `observe` | Never writes schema | Bind to existing IRIS classes |

## Auto Sync Semantics

`Meta.auto_sync = True` is an opt-in convenience for development and demos.
It only affects `save()`.

Behavior:

- `auto_sync=False`:
  `save()` never writes schema implicitly. If the IRIS class is missing, save fails with a
  runtime error that points you to `Model.sync_schema()`.
- default `mode="managed", auto_sync=True`:
  `save()` calls `Model.sync_schema()` before writing the row. This can add, update, or delete
  Python-owned schema members, so use it only where implicit schema ownership is acceptable.
- `mode="extend", auto_sync=True`:
  `save()` calls `Model.sync_schema()` before writing the row. This will create the class if
  needed and add missing Python-declared fields and indexes non-destructively.
- `mode="observe", auto_sync=True`:
  `save()` raises an error. `observe` is read-only from a schema-management perspective.
- `mode="replace", auto_sync=True`:
  `save()` raises an error. Destructive schema replacement must remain explicit via
  `Model.sync_schema()`.

Recommended user experience:

- demos and first-run developer workflows:
  default `mode="managed", auto_sync=True` for Python-owned schemas, or `mode="extend", auto_sync=True`
  when IRIS-only members must be preserved
- migration-controlled production classes:
  default `mode="managed"` with reviewed `plan -> apply -> verify`
- existing production classes:
  `mode="observe"` or explicit `sync_schema()`
- Python-owned destructive rebuilds:
  explicit `Model.sync_schema()` with `mode="replace"`

Example:

```python
class Demo(Model, persistent=True):
    Name: Annotated[str, Field(required=True)]

    class Meta:
        classname = "Demo.Demo"
        mode = "extend"
        auto_sync = True
```

## ClassMetadata Mapping

`Meta.metadata = ClassMetadata(...)` maps to scalar fields on `%Dictionary.ClassDefinition`.

| Python `ClassMetadata(...)` | IRIS metadata target | Meaning |
| --- | --- | --- |
| `description` | `Description` | Human-readable class description |
| `deprecated=True` | `Deprecated=1` | Marks the class as deprecated in IRIS metadata |
| `final=True` | `Final=1` | Marks the class as final/non-subclassable |
| `sql_table_name="..."` | `SqlTableName` | Overrides the projected SQL table name |
| `procedure_block=True` | `ProcedureBlock=1` | Enables IRIS procedure-block/compiler behavior |

Notes:

- `ClassMetadata` is optional; if absent, `iris_persistence` leaves those class-level flags alone in `managed` and `extend` modes.
- The scaffold only emits non-default class metadata fields.
- `managed` mode removes Python-owned properties, indexes, and parameters that disappear from the model without rebuilding the class.
- `replace` mode clears omitted class metadata naturally because the class is recreated.
- `Internal` and `SqlViewName` are intentionally not modeled yet because they are exposed by compiled metadata but are not writable reliably through `%Dictionary.ClassDefinition` in this environment.

## Parameter Mapping

`Meta.parameters = {...}` maps to IRIS class parameters.

Write path:

- `sync_schema()` writes Python parameters through `%Dictionary.ClassDefinition.Parameters`

Read path:

- `scaffold_from_iris(..., extract_meta=True)` first tries `%Dictionary.CompiledParameter`
  and keeps only rows owned by the current class
- if that returns nothing, scaffold tries `%Dictionary.ParameterDefinition`
- if that also returns nothing, scaffold may fall back to `%Dictionary.ClassDefinition.Parameters`
  but only keeps parameters owned by the current class

This fallback matters in some namespaces where custom class parameters are visible on the live
class definition object but do not appear through the SQL dictionary views.

Notes:

- parameter values are scaffolded as strings
- internal parameters such as `%...` and `GUID` are skipped
- inherited parameters are not scaffolded onto the subclass by default

## Field Mapping

Field metadata is written to `%Dictionary.PropertyDefinition` and then projected by IRIS.

| Python field / `Field(...)` | IRIS property metadata | SQL projection notes |
| --- | --- | --- |
| annotation type | `Type` | IRIS projects SQL type from the IRIS property type |
| `iris_type` | `Type` | Forces the IRIS property type directly |
| `required=True` | `Required=1` | IRIS projects required/non-nullable semantics for the property |
| `default=...` | `InitialExpression` | Object/property default; this is not the same as issuing raw SQL `DEFAULT` DDL yourself |
| `max_length=...` / `maxlen=...` | property parameter `MAXLEN` | Affects string length projection and validation |
| `readonly=True` | `ReadOnly=1` | Marks the IRIS property as read-only |
| `collection="list"` / `"array"` | `Collection` | Changes collection semantics and SQL/storage projection behavior |
| `sql_field_name="..."` | `SqlFieldName` | Overrides the projected SQL column name |
| `identity=True` | `Identity=1` | Marks the property as identity-bearing in IRIS metadata |
| `relationship="..."` | `Relationship` | Captures IRIS relationship semantics for object references and collections |
| `on_delete="..."` | `OnDelete` | Controls IRIS-side delete behavior for relationship properties |
| `inverse="..."` | `Inverse` | Names the inverse relationship property in IRIS metadata |
| `transient=True` | `Transient=1` | Keeps the property out of persistent storage |
| `storable=False` | `Storable=0` | Disables normal storage projection for the property |
| `multi_dimensional=True` | `MultiDimensional=1` | Enables multi-dimensional property metadata in IRIS |
| `sql_list_delimiter="..."` | `SqlListDelimiter` | Controls SQL list projection delimiter for list-backed fields |
| `sql_list_type="..."` | `SqlListType` | Controls SQL list projection type metadata, for example legacy values like `"LIST"` or `"DELIMITED"` |
| `sql_compute_code="..."` | `SqlComputeCode` | Defines SQL-compute code for projected fields |
| `sql_compute_on_change="..."` | `SqlComputeOnChange` | Declares which field changes should recompute the SQL value |
| `sql_computed=True` | `SqlComputed=1` | Marks the field as SQL-computed metadata |

Notes:

- `Field.default` is written as an IRIS initial expression.
- `Field.sql_type` is accepted as an alias for `Field.iris_type`.
- Plain `list[T]` and `dict[str, T]` annotations infer `Collection="list"` and
  `Collection="array"` respectively when no scalar collection `iris_type` such as `%List`,
  `%ListOfDataTypes`, or `%ArrayOfDataTypes` is supplied.
- `Field.storable` defaults to `True`; the scaffold only emits `storable=False` when IRIS marks the property as non-storable.
- The scaffold only emits non-default field flags, so `identity=False`, `transient=False`, and `multi_dimensional=False` are omitted.
- SQL-projection field metadata is scaffolded only when the compiled property exposes non-empty values for it.
- `%Persistent` references scaffold and sync as class-typed properties.
- `%SerialObject` references scaffold and sync as embedded serial properties.

## Type Projection Rules

Default Python-to-IRIS mapping:

| Python type | IRIS type |
| --- | --- |
| `str` | `%Library.String` |
| `int` | `%Library.Integer` |
| `float` | `%Library.Float` |
| `bool` | `%Library.Boolean` |
| `bytes` / `bytearray` | `%Stream.GlobalBinary` |
| unparameterized `dict` | `%Library.DynamicObject` |
| unparameterized `list` | `%Library.DynamicArray` |
| `dict[str, T]` | `T` with `Collection="array"` unless `iris_type` forces a scalar collection type |
| `list[T]` | `T` with `Collection="list"` unless `iris_type` forces a scalar collection type |
| `datetime.date` | `%Library.Date` |
| `datetime.time` | `%Library.Time` |
| `datetime.datetime` | `%Library.TimeStamp` |
| `Model` subclass | target class `Meta.classname` |

## Index Mapping

`Meta.indexes` entries map to `%Dictionary.IndexDefinition`.

| Python `Index(...)` | IRIS metadata | SQL projection notes |
| --- | --- | --- |
| `name` | `Name` | IRIS index name |
| `properties` | `Properties` | Indexed property/column list |
| `unique=True` | `Unique=1` | Projects a unique index |
| `type="..."` | `Type` | IRIS index type, for example `index`, `bitmap`, `key` |
| `primary_key=True` | `PrimaryKey=1` | Marks the index as a primary-key style index in IRIS metadata |

## StorageDefinition Mapping

`Meta.storage` maps to `%Dictionary.StorageDefinition`.

By default, `scaffold_from_iris(..., extract_meta=True)` keeps `Meta.storage` aligned with the
normal UDL/XML-visible storage definition. Use `extract_hidden_meta=True` to also include
dictionary-only storage scalars such as SQL row-ID helpers and internal location metadata.

| Python `StorageDefinition(...)` | IRIS metadata target | Meaning |
| --- | --- | --- |
| `type` | `Type` | Storage class type such as `%Storage.Persistent` or `%Storage.Serial` |
| `data_location` | `DataLocation` | Main data global |
| `default_data` | `DefaultData` | Default storage node name |
| `extent_location` | `ExtentLocation` | Extent global location |
| `extent_size` | `ExtentSize` | Recorded row extent size |
| `counter_location` | `CounterLocation` | Counter global location |
| `version_location` | `VersionLocation` | Version global location |
| `id_location` | `IdLocation` | Row ID location |
| `id_expression` | `IdExpression` | Row ID expression |
| `id_function` | `IdFunction` | Row ID function hook |
| `index_location` | `IndexLocation` | Index global location |
| `stream_location` | `StreamLocation` | Stream global location |
| `sql_child_sub` | `SqlChildSub` | Child-table subscript used by SQL projection |
| `sql_id_expression` | `SqlIdExpression` | SQL-facing row ID expression |
| `sql_row_id_name` | `SqlRowIdName` | SQL row ID column name |
| `sql_row_id_property` | `SqlRowIdProperty` | Property projected as the SQL row ID |
| `sql_table_number` | `SqlTableNumber` | Internal SQL table number metadata |
| `sequence_number` | `SequenceNumber` | Storage sequence number |
| `data` | `Data` child collection | Storage node definitions |
| `indices` | `Indices` child collection | Storage index definitions |
| `properties` | `Properties` child collection | Field-size/selectivity metadata |
| `sql_maps` | `SQLMaps` child collection | Custom SQL map metadata |

## StorageData Mapping

`StorageData(...)` maps to `%Dictionary.StorageDataDefinition`.

| Python `StorageData(...)` | IRIS metadata target | Meaning |
| --- | --- | --- |
| `name` | `Name` | Storage data node name |
| `structure` | `Structure` | Node structure such as `listnode` or `node` |
| `attribute` | `Attribute` | Direct attribute mapping for the node |
| `subscript` | `Subscript` | Explicit storage subscript expression |
| `values` | `Values` child definitions | Numbered storage value mapping |

Example:

```xml
<Data name="dickt">
<Attribute>dickt</Attribute>
<Structure>node</Structure>
<Subscript>"dickt"</Subscript>
</Data>
```

Scaffolds to:

```python
StorageData(
    name="dickt",
    structure="node",
    attribute="dickt",
    subscript='"dickt"',
    values={},
)
```

## StorageIndex Mapping

`StorageIndex(...)` maps to `%Dictionary.StorageIndexDefinition`.

These are storage-level index nodes, distinct from class-level SQL indexes in
`Meta.indexes`.

| Python `StorageIndex(...)` | IRIS metadata target | Meaning |
| --- | --- | --- |
| `name` | `Name` | Storage index name |
| `location` | `Location` | Storage index global location |
| `small_chunk_size` | `SmallChunkSize` | IRIS small-chunk size metadata |

## StorageProperty Mapping

`StorageProperty(...)` maps to `%Dictionary.StoragePropertyDefinition`.

By default, scaffolding includes the UDL/XML-visible storage property statistics:
`average_field_size`, `selectivity`, and `outlier_selectivity`.
Use `extract_hidden_meta=True` to also scaffold dictionary-only statistics such as histograms,
child block/extent metadata, outlier-bias flags, and storage-property stream locations.

| Python `StorageProperty(...)` | IRIS metadata target | Meaning |
| --- | --- | --- |
| `name` | `Name` | Property name |
| `average_field_size` | `AverageFieldSize` | IRIS storage sizing metadata |
| `selectivity` | `Selectivity` | IRIS selectivity metadata used by SQL/runtime heuristics |
| `outlier_selectivity` | `OutlierSelectivity` | Per-value outlier selectivity metadata |
| `histogram` | `Histogram` | Histogram/tuning statistics metadata |
| `child_block_count` | `ChildBlockCount` | Child block-count statistics |
| `child_extent_size` | `ChildExtentSize` | Child extent-size statistics |
| `bias_queries_as_outlier` | `BiasQueriesAsOutlier` | Outlier-bias flag used by IRIS heuristics |
| `stream_location` | `StreamLocation` | Storage-property stream location metadata |

### Selectivity Scaffolding

`scaffold_from_iris()` normally reads storage property rows from `%Dictionary.CompiledStorageProperty`.
Some classes expose incomplete data there. For example, `Demo.Demo` may only return a partial subset of
storage-property rows from the compiled view while `%Dictionary.StoragePropertyDefinition` still contains
per-property `AverageFieldSize`, `Selectivity`, `OutlierSelectivity`, and related statistics.

Use:

```python
scaffold_from_iris(
    "Demo.Demo",
    "./generated_models",
    extract_meta=True,
    scaffold_selectivity=True,
)
```

When `scaffold_selectivity=True`:

- scaffold still reads compiled storage properties first
- it then merges `%Dictionary.StoragePropertyDefinition` rows by property name
- definition-view storage-property statistics fill gaps or replace empty compiled values

This option only affects scaffold metadata extraction. It is most useful when you want generated
`StorageProperty(...)` entries to retain tuning statistics for existing IRIS classes.

### Hidden Storage Metadata

Some metadata exposed by `%Dictionary.CompiledStorage` and `%Dictionary.StoragePropertyDefinition`
does not normally appear in the UDL/XML storage block.

Use:

```python
scaffold_from_iris(
    "Demo.Product",
    "./generated_models",
    extract_meta=True,
    extract_hidden_meta=True,
)
```

This opt-in adds:

- storage-level hidden scalars such as `extent_location`, `counter_location`, `version_location`,
  `id_expression`, `id_function`, `sql_child_sub`, `sql_id_expression`, `sql_row_id_name`,
  `sql_row_id_property`, `sql_table_number`, and `sequence_number`
- storage-property hidden statistics such as `histogram`, `child_block_count`,
  `child_extent_size`, `bias_queries_as_outlier`, and property-level `stream_location`

## StorageSQLMap Mapping

`StorageSQLMap(...)` maps to `%Dictionary.StorageSQLMapDefinition`.

| Python `StorageSQLMap(...)` | IRIS metadata target | Meaning |
| --- | --- | --- |
| `name` | `Name` | SQL map name |
| `block_count` | `BlockCount` | IRIS SQL map sizing metadata |
| `condition` | `Condition` | SQL map condition |
| `condition_fields` | `ConditionFields` | Fields referenced by the condition |
| `conditional_with_host_vars` | `ConditionalWithHostVars` | Host-variable condition flag |
| `global_name` | `Global` | Global root for the map |
| `population_pct` | `PopulationPct` | Population percentage hint |
| `population_type` | `PopulationType` | Population strategy hint |
| `row_reference` | `RowReference` | Row reference expression |
| `structure` | `Structure` | SQL map structure |
| `type` | `Type` | SQL map type |
| `data` | `Data` child collection | Node/piece extraction metadata |
| `row_id_specs` | `RowIdSpecs` child collection | Row-ID extraction metadata |
| `subscripts` | `Subscripts` child collection | Subscript traversal metadata |

### StorageSQLMapData

`StorageSQLMapData(...)` maps to `%Dictionary.StorageSQLMapDataDefinition`.

| Python field | IRIS metadata target |
| --- | --- |
| `name` | `Name` |
| `node` | `Node` |
| `piece` | `Piece` |
| `delimiter` | `Delimiter` |
| `retrieval_code` | `RetrievalCode` |

### StorageSQLMapRowIdSpec

`StorageSQLMapRowIdSpec(...)` maps to `%Dictionary.StorageSQLMapRowIdSpecDefinition`.

| Python field | IRIS metadata target |
| --- | --- |
| `name` | `Name` |
| `field` | `Field` |
| `expression` | `Expression` |

### StorageSQLMapSub

`StorageSQLMapSub(...)` maps to `%Dictionary.StorageSQLMapSubDefinition`.

| Python field | IRIS metadata target |
| --- | --- |
| `name` | `Name` |
| `access_type` | `AccessType` |
| `data_access` | `DataAccess` |
| `delimiter` | `Delimiter` |
| `expression` | `Expression` |
| `loop_init_value` | `LoopInitValue` |
| `next_code` | `NextCode` |
| `null_marker` | `NullMarker` |
| `start_value` | `StartValue` |
| `stop_expression` | `StopExpression` |
| `stop_value` | `StopValue` |
| `access_vars` | `Accessvars` child collection |
| `invalid_conditions` | `Invalidconditions` child collection |

### StorageSQLMapSubAccessVar

`StorageSQLMapSubAccessVar(...)` maps to `%Dictionary.StorageSQLMapSubAccessvarDefinition`.

| Python field | IRIS metadata target |
| --- | --- |
| `name` | `Name` |
| `variable` | `Variable` |
| `code` | `Code` |

### StorageSQLMapSubInvalidCondition

`StorageSQLMapSubInvalidCondition(...)` maps to `%Dictionary.StorageSQLMapSubInvalidconditionDefinition`.

| Python field | IRIS metadata target |
| --- | --- |
| `name` | `Name` |
| `expression` | `Expression` |

## SQL Projection Notes

Important caveats when reading `iris_persistence` metadata as SQL schema:

- `classname` is not a raw SQL table name override by itself.
  IRIS derives SQL projection from the class definition and superclass behavior.
- `Field.default` writes `InitialExpression`; it should be treated as IRIS object/property default metadata,
  not as a promise of a raw SQL `DEFAULT` clause identical to hand-written DDL.
- `%SerialObject` classes are embedded/serial structures, not standalone persistent SQL tables.
- `%Persistent` and `Ens.Request` classes project persistent storage and SQL tables.
- `sql_field_name` is the explicit Python-side way to control the IRIS projected SQL column name.

## Migration Workflow

`iris_persistence.migrations` adds an explicit `plan -> apply -> verify -> rollback-backup`
workflow for production schemas.

- `create_plan([...])` compares live `%Dictionary` metadata with Python model metadata and returns
  deterministic structured operations plus the legacy human diff.
- `plan.save("plan.json")` writes the review artifact that should be applied later.
- `apply_plan(plan, backup_dir=...)` rechecks live schema fingerprints before writing and creates
  a pre-apply backup directory containing `plan.json`, `metadata.json`, and `schema_states.json`.
- managed-mode property, index, and parameter removals/updates are shown as `managed-delete`
  or `managed-update` operations and are allowed by default.
- destructive or manual-review operations outside managed member removals, including storage
  replacement, are blocked unless `allow_destructive=True` or CLI `--allow-destructive` is supplied.
- `verify_plan(plan)` checks whether the live schema converged to the plan target.
- `rollback_backup(path, allow_destructive=True)` restores classes from `schema_states.json` and
  deletes classes that did not exist before apply; rollback does not require or use a hand-written
  downgrade function.
- `check_drift([...])` uses the same schema normalizer as planning, so drift reports and plan
  output compare the same metadata surface.

Recommended production flow:

```bash
iris-persistence plan myapp.models:Product --to 001_add_product --out plan.json
iris-persistence review-plan plan.json
iris-persistence apply-plan plan.json --backup-dir .iris_persistence/backups
iris-persistence verify-plan plan.json
iris-persistence rollback-backup .iris_persistence/backups/<backup-id> --allow-destructive
```

For migration-managed classes, keep the default `mode="managed"` and `Meta.auto_sync = False`
in production paths. `auto_sync` is still useful for demos and local development, but it bypasses
reviewed migration plans and pre-apply backups.

## Current Coverage

The current codebase round-trips:

- field type/default/required/maxlen/readonly/collection/sql field name
- index unique/type/primary key metadata
- storage globals, row-id helpers, and SQL storage scalars
- storage data nodes
- storage property average size, selectivity, outlier stats, histogram, child stats, and stream location
- SQL map parent metadata
- SQL map data, row-id specs, subscripts, access vars, and invalid conditions

Anything outside these public dataclasses is still IRIS-only metadata and will not round-trip through `iris_persistence`
unless a corresponding Python type is added first.
