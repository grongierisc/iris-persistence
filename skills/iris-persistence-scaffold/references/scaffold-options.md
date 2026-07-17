# Scaffold options

## Basic call

```python
from iris_persistence.scaffold import scaffold_from_iris

result = scaffold_from_iris(
    "App.*",
    "./generated",
    mode="observe",
    storage="ignore",
    return_result=True,
)

for path in result.files:
    print(path)
for warning in result.warnings:
    print(warning)
```

The pattern uses `*` wildcards and is translated to the IRIS dictionary query wildcard.

## Options

- `mode`: generated model ownership mode. Default and safest value is `observe`.
- `extract_meta`: include supported class metadata when true.
- `include_related`: recursively collect referenced classes when true.
- `storage`: control advanced storage extraction. Keep `ignore` unless exact storage metadata is required.
- `return_result`: return files plus warnings instead of only a file list.
- `best_effort`: continue past supported extraction failures while collecting warnings. Keep false for strict generation.

## Runtime

Embedded Python needs no explicit connection when IRIS is discoverable. Native Python must configure the runtime before scaffolding:

```python
from iris_persistence import RuntimeConfig, configure_runtime

configure_runtime(RuntimeConfig(native_connection=connection))
```

## Review checklist

- Confirm `Meta.classname` matches the live class exactly.
- Confirm `Meta.mode` remains `observe`.
- Check Python types, nullability, defaults, collection kinds, relationships, SQL names, indexes, and parameters.
- Inspect generated-name collision handling when multiple packages contain the same short classname.
- Import every generated module.
- Read representative rows with `GeneratedModel.get(id)`.
- Keep generated output in version control so regeneration produces a reviewable diff.

Offline generation from exported `.cls` files is not implemented.
