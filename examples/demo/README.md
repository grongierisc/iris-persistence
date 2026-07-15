# Demo Walkthrough

This folder contains a progressive set of `iris_persistence` demos, starting with a single-field `Model` and ending with a live IRIS scaffold round-trip.

## Run Order

1. `examples/demo/01_minimal_save.py`
2. `examples/demo/02_python_first_crud.py`
3. `examples/demo/03_related_objects.py`
4. `examples/demo/04_advanced_schema.py`
5. `examples/demo/05_scaffold_round_trip.py`
6. `examples/demo/06_persistent_lifecycle.py`

## What Each Demo Covers

- `01_minimal_save.py`: the smallest possible `Model`, plus `save()`, `get()`, and `all()`
- `02_python_first_crud.py`: field defaults, generated indexes, parameters, `%List`, and query chaining with `where(...).order_by(...)`
- `03_related_objects.py`: `%Persistent` and `%SerialObject` references, plus list and array collections of nested models
- `04_advanced_schema.py`: managed mode, advanced `StorageDefinition(...)`, `ClassMetadata(...)`, indexes, parameters, and richer scalar types
- `05_scaffold_round_trip.py`: create a live IRIS class from Python, scaffold an observe model back out, then read through the generated model
- `06_persistent_lifecycle.py`: create and evolve a managed class, then save, load, update, query, and delete a persistent object

## Runtime Selection

The demos default to `IRIS_DEMO_BACKEND=auto`:

- if `iris` is available, they try embedded IRIS first
- if IRIS is unavailable, they fall back to `iris_persistence.testing.InMemoryAdapter`

You can override that explicitly:

```bash
IRIS_DEMO_BACKEND=fake python examples/demo/01_minimal_save.py
IRIS_DEMO_BACKEND=embedded python examples/demo/02_python_first_crud.py
IRIS_DEMO_BACKEND=remote IRISUSERNAME=SuperUser IRISPASSWORD=SYS python examples/demo/05_scaffold_round_trip.py
```

Remote mode also accepts `IRIS_HOST`, `IRIS_PORT`, and `IRIS_NAMESPACE`.

## Notes

- Demos `01` through `04` and `06` run with either a live IRIS runtime or the fake adapter.
- Demo `05` needs live IRIS dictionary access for `scaffold_from_iris(...)`; it reports a skip instead of failing when the backend is fake.
