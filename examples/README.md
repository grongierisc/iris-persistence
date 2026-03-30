# iris_orm examples

Each file in this directory is a self-contained runnable example.
They all require a live embedded IRIS connection.

| File | What it shows |
|------|---------------|
| `01_existing_class.py` | Binding to an existing IRIS class, CRUD, queries |
| `02_typed_model.py` | Declared model definition, `.cls` generation |
| `03_relationships.py` | One-to-many and parent/child relationships |
| `04_schema_sync.py` | Git-style schema sync: status / push / pull / commit |
| `07_brownfield_scaffold.py` | Brownfield import: scaffold Python + sidecar state from IRIS or `.cls` |
| `08_python_first_sync.py` | Python-first sync with lockfile-based storage preservation |

## Running

```bash
# From the src/python/ directory with a live embedded IRIS connection:
python examples/01_existing_class.py
python examples/02_typed_model.py
...
python examples/07_brownfield_scaffold.py
python examples/08_python_first_sync.py
```
