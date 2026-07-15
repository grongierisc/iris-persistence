# Advanced Schema Mapping

## Ownership model

Version 0.3.0 has two modes:

| Mode | Authority | Behavior |
| --- | --- | --- |
| `managed` | Python for declared members | Reconciles properties, indexes, parameters, and class metadata without rebuilding the class |
| `observe` | IRIS | Performs no schema write or compile |

IRIS owns compiler-generated `Storage Default`, SQL projection artifacts, and runtime methods.
Python does not reconstruct or diff those artifacts.

## Class metadata

| Python | Writable dictionary target |
| --- | --- |
| Model field | `%Dictionary.PropertyDefinition` |
| `Meta.indexes` | `%Dictionary.IndexDefinition` |
| `Meta.parameters` | `%Dictionary.ParameterDefinition` |
| `Meta.metadata` | `%Dictionary.ClassDefinition` scalar fields |

Managed sync removes omitted Python-owned properties, indexes, and parameters. Inherited and
system members are preserved.

## Creation-time tuning

Prefer `Meta.parameters`, especially `DEFAULTGLOBAL` and `USEEXTENTSET`. When explicit physical
locations are necessary, `StorageTuning` supports only:

- `data_location`
- `extent_location`
- `id_location`
- `index_location`
- `stream_location`
- `counter_location`
- `version_location`
- `index_locations`, keyed by index name

For a new class, these values pre-seed `%Dictionary.StorageDefinition` named `Default`. The class
is then compiled once, allowing IRIS to generate the remaining storage nodes.

## Complete custom storage

The full dataclasses live in `iris_persistence.advanced_storage`:

- `StorageDefinition`
- `StorageData`
- `StorageIndex`
- `StorageProperty`
- `StorageSQLMap` and its nested definitions

Declare them with `Meta.custom_storage`. `StorageDefinition.name` defaults to `CustomStorage`.
The schema writer creates the complete nested dictionary definition before first compilation and
sets `StorageStrategy` only for a name other than `Default`.

This API is for layouts that cannot be expressed by compiler defaults or class parameters. It is
not a relocation mechanism.

## Immutability and migration

Once a class exists, ordinary sync compares only the declared tuning or custom fields against the
writable storage definition. Compiler-added fields are ignored. Equal declarations are no-ops;
any declared mismatch produces `blocked_storage_change` and raises `StorageMigrationRequired`
before mutation.

No application or rollback flag can bypass a blocked storage operation. Physical relocation
needs a future workflow that can copy data, switch globals, validate, and roll back safely.

## Scaffolding

Storage is ignored by default. `storage="custom"` reads the active storage directly from
`%Dictionary.ClassDefinition.Storages` and emits an advanced-storage snapshot. It requires
`mode="managed"` because storage declarations are invalid in observe mode.

The scaffold does not query compiled storage tables, merge selectivity projections, or infer a
storage definition from SQL metadata.
