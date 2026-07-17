# Model API reference

## Minimal managed model

```python
from iris_persistence import Field, Index, Model

class Person(Model, persistent=True):
    Name: str = Field(required=True, max_length=120)
    Age: int | None = None

    class Meta:
        classname = "App.Person"
        mode = "managed"
        indexes = [Index("NameIdx", properties="Name")]
```

Use `persistent=True` for stored objects and `serial=True` for embedded serial objects.

## Runtime

Embedded Python discovers IRIS automatically. Native Python supplies a supported connection:

```python
from iris_persistence import RuntimeConfig, configure_runtime

configure_runtime(RuntimeConfig(native_connection=connection))
```

Application code should use the same model API in both environments.

## Fields

Plain annotations are valid fields. `Field(...)` accepts `required`, `default`, `default_factory`, `nullable`, `primary_key`, `index`, `unique`, `index_name`, `index_type`, `max_length`, `initial_expression`, `readonly`, `collection`, `iris_type`, `sql_field_name`, `identity`, relationship metadata, transient/storable flags, and SQL projection metadata.

Do not set both `default` and `default_factory`.

Collections and related values:

```python
class Address(Model, serial=True):
    City: str = Field(required=True, max_length=80)

class Order(Model, persistent=True):
    ShipTo: Address | None = None
    Lines: list[Address] = Field(
        default_factory=list,
        iris_type="App.Address",
        collection="list",
    )
```

## Schema and CRUD

```python
diff = Person.diff_schema()
assert Person.sync_schema(dry_run=True) == diff
Person.sync_schema()  # mutation: require authorization

person = Person(Name="Ada", Age=36)
person.save()
loaded = Person.get(person.pk)
matches = Person.where(Name="Ada").order_by("Name").all()
deleted = loaded.delete() if loaded else False
```

`save()` does not rewrite schema unless `Meta.auto_sync=True`. `where()` performs equality filters and uses parameterized values. `order_by()` accepts declared model field names.

## Conversion

- `instance.to_dict()` and `Model.from_dict(values)` convert recursive plain values.
- `instance.to_dataclass(Type)` and `Model.from_dataclass(value)` bridge matching dataclass fields.
- `instance.to_iris()` materializes an IRIS handle without `%Save()`.
- `Model.from_iris(handle, known_pk=...)` wraps an existing handle.

## Storage

Use `StorageTuning` only to choose creation-time locations for compiler-owned default storage. Existing populated storage relocation requires an explicit expert maintenance workflow.
