# iris_orm examples

Each file in this directory is a self-contained runnable example.
They all require a live IRIS connection (embedded or remote).

| File | What it shows |
|------|---------------|
| `01_plan_a.py` | Plan A — binding to an existing IRIS class, CRUD, queries |
| `02_plan_c.py` | Plan C — Python-first model definition, `.cls` generation |
| `03_relationships.py` | One-to-many and parent/child relationships |
| `04_schema_sync.py` | Git-style schema sync: status / push / pull / commit |
| `05_remote_connection.py` | Connecting to a remote IRIS server via SQLAlchemy engine |

## Running

```bash
# From the src/python/ directory with a live embedded IRIS connection:
python examples/01_plan_a.py
python examples/02_plan_c.py
...

# With a remote IRIS server (edit the connection string first):
python examples/05_remote_connection.py
```
