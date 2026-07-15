# Runtime Boundary Migration

This release centralizes all IRIS wrapper behavior behind a structural `Runtime` protocol. Model,
query, schema, migration, and scaffold APIs keep their existing behavior, but runtime configuration
and custom runtime integrations contain intentional breaking changes.

## Breaking changes

### Runtime configuration requires `RuntimeConfig`

Passing a connection directly to `configure_runtime()` is no longer supported. The deprecated root
`configure()` function and `configure_default_runtime()` were removed.

```python
# Before
import iris_persistence

iris_persistence.configure_runtime(native_connection)
```

```python
# After
from iris_persistence import RuntimeConfig, configure_runtime

configure_runtime(RuntimeConfig(native_connection=native_connection))
```

Embedded and automatically selected runtimes normally need no arguments:

```python
from iris_persistence import configure_runtime

configure_runtime()
```

The wrapper remains authoritative for `mode="auto"`. Application algorithms should not inspect
the selected mode or `iris.runtime` state.

### Adapter classes were replaced by a protocol

`RuntimeAdapter`, `IRISRuntimeAdapter`, and `IRISValueAdapterMixin` were removed. Applications can
provide a structurally compatible implementation without inheriting from a package class:

```python
from iris_persistence import install_runtime

install_runtime(MyRuntime())
```

Custom runtimes must implement the complete `Runtime` contract, including `connection()`,
`transaction()`, status validation, object operations, collection conversion, reference clearing,
and class compilation. Native-shaped test doubles that expose `_oref`, `_db`, or wrapper mode state
should be replaced with semantic runtime fixtures.

### Connections and transactions are context managed

`get_dbapi_connection()` and direct `begin_transaction()`, `commit_transaction()`, and
`rollback_transaction()` calls are not part of the `Runtime` protocol. Use the managed operations:

```python
from iris_persistence import get_runtime

runtime = get_runtime()

with runtime.connection() as connection:
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT Name FROM App.Person")
    finally:
        cursor.close()

with runtime.transaction():
    person.save()
```

The runtime decides connection ownership. Closing the managed proxy closes runtime-owned
connections but does not close a caller-owned Native connection. Code that checks the concrete
connection or cursor type must instead rely on the DBAPI interface.

### Runtime failures are typed

Runtime operations now raise one of:

- `RuntimeConfigurationError`
- `RuntimeOperationError`
- `RuntimeStatusError`
- `RuntimeClassNotFoundError`
- `UnsupportedRuntimeOperation`

Boolean failure conventions are no longer supported for semantic operations. For example,
`clear_reference()` succeeds with `None` or raises a typed exception. Runtime errors include the
operation and normalized backend context, and retain the original error as `__cause__`.

Transaction commit failures trigger rollback and raise `RuntimeOperationError`. If rollback also
fails, that failure is available as `exception.__cause__.rollback_error`.

## Behavior changes and regression risks

- Wrapper probing and fallback order now run once inside the runtime backend. Applications relying
  on private wrapper fallback side effects may observe different exception timing.
- Vendor DBAPI errors are normalized to `RuntimeOperationError`. Catching a vendor-specific DBAPI
  exception around persistence internals will no longer work reliably.
- Missing IRIS classes raise `RuntimeClassNotFoundError` with schema and namespace guidance instead
  of leaking the wrapper's class lookup error.
- Failing IRIS status values raise `RuntimeStatusError`; previously ignored or boolean-tested status
  values may now stop an operation.
- Silent broad exception fallbacks were removed. Invalid dictionary operations, exhausted reference
  clearing fallbacks, and unsupported runtime capabilities now fail explicitly.
- `RuntimeConfig` is immutable. Reconfiguration requires constructing a new config and calling
  `configure_runtime()` again.
- Installing or configuring a runtime clears model runtime-derived caches. Code relying on a cached
  SQL table name across runtime changes will now resolve it again.
- `InMemoryRuntime` is the supported test runtime. `InMemoryAdapter` remains an alias for migration,
  but new tests should use `InMemoryRuntime`.

No known model-level CRUD, schema, migration, scaffold, nullable-reference, collection, or storage
regressions remain in the tested Embedded environment. Native deployments should run their existing
integration matrix because connection ownership and wrapper fallback timing are the most likely
compatibility-sensitive areas.

## Root compatibility wrappers

The root `materialize()` and `from_iris()` functions still emit `DeprecationWarning`. Prefer
`Model.to_iris()` and `Model.from_iris()`; they are removed with the other deprecated root aliases
in `0.4.0`. See the [product-surface migration](product_surface_migration.md).
