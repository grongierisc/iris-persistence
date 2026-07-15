# Architecture

The project has one core dependency direction:

```text
models / query / schema / migrations / scaffold / advanced storage
                              |
                              v
                     Runtime protocol
                              |
                              v
               internal IRIS wrapper backend
```

Domain algorithms request semantic operations from `Runtime`: object persistence, field and
collection access, managed DBAPI connections, transactions, status validation, and compilation.
They do not import `iris`, inspect wrapper state, or branch on Embedded versus Native.

`configure_runtime()` gives the immutable `RuntimeConfig` to the wrapper, lets the wrapper perform
automatic backend selection, constructs `IRISRuntime`, and atomically installs that single runtime
in the registry. Custom applications and tests may install any structurally compatible runtime.

The public product center is models, CRUD/query, runtime configuration, and managed schema.
Migrations, reverse scaffolding, and advanced storage are secondary orchestration layers. They are
shipped together but imported explicitly from their own namespaces.

Architecture tests reject wrapper imports, backend literals, and wrapper object internals outside
the runtime boundary and dedicated backend tests.
