# Advanced Schema Mapping

This document maps `iris_orm`'s Python model metadata to the IRIS class dictionary,
SQL projection, and physical storage metadata.

`iris_orm` works across three layers:

- Python model definition: `IRISModel`, `Field(...)`, `Index(...)`, `StorageDefinition(...)`
- IRIS class metadata: `%Dictionary.*Definition` and `%Dictionary.Compiled*`
- SQL/storage projection: projected SQL table/column/index shape plus global storage layout

## Mental Model

`iris_orm` does not generate standalone SQL DDL directly.
It writes IRIS class metadata, and IRIS projects that metadata into SQL schema.

In practice:

- `Model.sync_schema()` writes `%Dictionary.ClassDefinition`, `%Dictionary.PropertyDefinition`,
  `%Dictionary.IndexDefinition`, and storage metadata
- IRIS compiles the class
- the compiled class becomes the source of truth for the SQL projection
- `scaffold_from_iris()` reads `%Dictionary.Compiled*` metadata back into Python
- `scaffold_from_iris(..., scaffold_selectivity=True)` also enriches storage-property selectivity
  from `%Dictionary.StoragePropertyDefinition` when compiled storage-property rows are sparse

## Meta Mapping

| Python `Meta` attribute | IRIS metadata target | SQL / runtime effect |
| --- | --- | --- |
| `classname` | `%Dictionary.ClassDefinition.Name` | Defines the IRIS class name; SQL table naming is derived by IRIS from the class unless separately customized in IRIS |
| `mode` | no direct dictionary field | Controls ownership behavior in `iris_orm`: `extend`, `replace`, `observe` |
| `superclasses` | `%Dictionary.ClassDefinition.Super` | Controls whether the class is `%Persistent`, `%SerialObject`, `Ens.Request`, etc., which changes table projection and object behavior |
| `parameters` | `%Dictionary.ParameterDefinition` | IRIS class parameters; some may affect SQL/storage behavior depending on IRIS semantics |
| `indexes` | `%Dictionary.IndexDefinition` | Projects SQL indexes and related access paths |
| `storage` | `%Dictionary.StorageDefinition` and children | Controls physical storage layout and custom SQL map projection |

## Mode Semantics

| Mode | IRIS write behavior | Use case |
| --- | --- | --- |
| `extend` | Adds/updates Python-declared members, keeps unrelated IRIS metadata | Brownfield classes |
| `replace` | Rebuilds the class from Python metadata | Python-owned schema |
| `observe` | Never writes schema | Bind to existing IRIS classes |

## Field Mapping

Field metadata is written to `%Dictionary.PropertyDefinition` and then projected by IRIS.

| Python field / `Field(...)` | IRIS property metadata | SQL projection notes |
| --- | --- | --- |
| annotation type | `Type` | IRIS projects SQL type from the IRIS property type |
| `iris_type` | `Type` | Forces the IRIS property type directly |
| `required=True` | `Required=1` | IRIS projects required/non-nullable semantics for the property |
| `default=...` | `InitialExpression` | Object/property default; this is not the same as issuing raw SQL `DEFAULT` DDL yourself |
| `maxlen=...` | property parameter `MAXLEN` | Affects string length projection and validation |
| `readonly=True` | `ReadOnly=1` | Marks the IRIS property as read-only |
| `collection="list"` / `"array"` | `Collection` | Changes collection semantics and SQL/storage projection behavior |
| `sql_field_name="..."` | `SqlFieldName` | Overrides the projected SQL column name |

Notes:

- `Field.default` is written as an IRIS initial expression.
- `Field.sql_type` remains a backward-compatible alias for `Field.iris_type`.
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
| `dict` | `%Library.DynamicObject` |
| `list` | `%Library.DynamicArray` |
| `datetime.date` | `%Library.Date` |
| `datetime.time` | `%Library.Time` |
| `datetime.datetime` | `%Library.TimeStamp` |
| `IRISModel` subclass | target class `Meta.classname` |

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

| Python `StorageDefinition(...)` | IRIS metadata target | Meaning |
| --- | --- | --- |
| `type` | `Type` | Storage class type such as `%Storage.Persistent` or `%Storage.Serial` |
| `data_location` | `DataLocation` | Main data global |
| `default_data` | `DefaultData` | Default storage node name |
| `id_location` | `IdLocation` | Row ID location |
| `index_location` | `IndexLocation` | Index global location |
| `stream_location` | `StreamLocation` | Stream global location |
| `data` | `Data` child collection | Storage node definitions |
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

## StorageProperty Mapping

`StorageProperty(...)` maps to `%Dictionary.StoragePropertyDefinition`.

| Python `StorageProperty(...)` | IRIS metadata target | Meaning |
| --- | --- | --- |
| `name` | `Name` | Property name |
| `average_field_size` | `AverageFieldSize` | IRIS storage sizing metadata |
| `selectivity` | `Selectivity` | IRIS selectivity metadata used by SQL/runtime heuristics |

### Selectivity Scaffolding

`scaffold_from_iris()` normally reads storage property rows from `%Dictionary.CompiledStorageProperty`.
Some classes expose incomplete data there. For example, `Demo.Demo` may only return a partial subset of
storage-property rows from the compiled view while `%Dictionary.StoragePropertyDefinition` still contains
per-property `Selectivity` and `AverageFieldSize`.

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
- `AverageFieldSize` and `Selectivity` from the definition view fill gaps or replace empty compiled values

This option only affects scaffold metadata extraction. It is most useful when you want generated
`StorageProperty(...)` entries to retain tuning statistics for existing IRIS classes.

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

Important caveats when reading `iris_orm` metadata as SQL schema:

- `classname` is not a raw SQL table name override by itself.
  IRIS derives SQL projection from the class definition and superclass behavior.
- `Field.default` writes `InitialExpression`; it should be treated as IRIS object/property default metadata,
  not as a promise of a raw SQL `DEFAULT` clause identical to hand-written DDL.
- `%SerialObject` classes are embedded/serial structures, not standalone persistent SQL tables.
- `%Persistent` and `Ens.Request` classes project persistent storage and SQL tables.
- `sql_field_name` is the explicit Python-side way to control the IRIS projected SQL column name.

## Current Coverage

The current codebase round-trips:

- field type/default/required/maxlen/readonly/collection/sql field name
- index unique/type/primary key metadata
- storage globals and storage data nodes
- storage property average size and selectivity
- SQL map parent metadata
- SQL map data, row-id specs, subscripts, access vars, and invalid conditions

Anything outside these public dataclasses is still IRIS-only metadata and will not round-trip through `iris_orm`
unless a corresponding Python type is added first.
