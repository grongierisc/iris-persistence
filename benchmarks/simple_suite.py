from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

import iris

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iris_orm import Field, Model, configure
from iris_orm.query import _resolve_sql_table_name
from iris_orm.runtime import get_runtime

BENCHMARK_ROOT = Path(__file__).parent
OBJECTSCRIPT_CLS_ROOT = BENCHMARK_ROOT / "objectscript" / "cls"
OBJECTSCRIPT_SOURCES = (
    OBJECTSCRIPT_CLS_ROOT / "simple_benchmark_record.cls",
    OBJECTSCRIPT_CLS_ROOT / "simple_benchmark_harness.cls",
)
OBJECTSCRIPT_CLASSNAMES = (
    "Bench.SimpleBenchmarkRecord",
    "Bench.SimpleBenchmarkHarness",
)
_BENCHMARK_CLASSES_READY = False


class SimpleBenchmarkRecord(Model):
    Name: str = Field(required=True, max_length=120)
    Category: str = Field(required=True, max_length=40)
    Quantity: int = Field(required=True)
    Price: float = Field(required=True)
    Active: bool = Field(required=True)

    class Meta:
        classname = "Bench.SimpleBenchmarkRecord"
        mode = "observe"
        validate_on_init = False


@dataclass(frozen=True)
class BenchmarkRun:
    mode: str
    iteration: int
    rows: int
    write_seconds: float
    read_seconds: float
    fetch_all_seconds: float


def _remote_connection():
    host = os.environ.get("IRIS_HOST", "localhost")
    port = int(os.environ.get("IRIS_PORT", "1972"))
    namespace = os.environ.get("IRIS_NAMESPACE", "IRISAPP")
    username = os.environ.get("IRISUSERNAME")
    password = os.environ.get("IRISPASSWORD")
    missing = [
        name
        for name, value in (
            ("IRISUSERNAME", username),
            ("IRISPASSWORD", password),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Remote benchmark requires env vars: " + ", ".join(missing)
        )
    return iris.connect(
        hostname=host,
        port=port,
        namespace=namespace,
        username=username,
        password=password,
    )


def _verify_benchmark_classes() -> None:
    dictionary = iris.cls("%Dictionary.ClassDefinition")
    missing = [
        classname
        for classname in OBJECTSCRIPT_CLASSNAMES
        if not dictionary._ExistsId(classname)
    ]
    if missing:
        raise RuntimeError(
            "Missing benchmark classes after load: " + ", ".join(missing)
        )
    setattr(SimpleBenchmarkRecord, "_sql_table_name", None)


def _load_benchmark_classes_on_current_runtime() -> None:
    system_obj = iris.cls("%SYSTEM.OBJ")
    for source in OBJECTSCRIPT_SOURCES:
        status = system_obj.Load(str(source), "cuk")
        if not status:
            raise RuntimeError(f"Failed to load benchmark source: {source}")
    _verify_benchmark_classes()


def _provision_benchmark_classes() -> None:
    global _BENCHMARK_CLASSES_READY
    if _BENCHMARK_CLASSES_READY:
        return

    remote_error: Optional[Exception] = None
    try:
        connection = _remote_connection()
    except Exception as exc:
        remote_error = exc
    else:
        try:
            configure(native_connection=connection)
            _load_benchmark_classes_on_current_runtime()
            _BENCHMARK_CLASSES_READY = True
            return
        except Exception as exc:
            remote_error = exc
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()
            configure()

    _load_benchmark_classes_on_current_runtime()
    _BENCHMARK_CLASSES_READY = True
    if remote_error is not None:
        print(f"Remote class provisioning failed, using current runtime instead: {remote_error}")

def _ensure_benchmark_classes_loaded() -> None:
    if not _BENCHMARK_CLASSES_READY:
        _provision_benchmark_classes()
    _verify_benchmark_classes()


def _reset_extent() -> None:
    runtime = get_runtime()
    class_ref = iris.cls(SimpleBenchmarkRecord._classname)
    status = class_ref._DeleteExtent()
    if not runtime.is_ok(status):
        raise RuntimeError(f"Failed to reset benchmark extent: {runtime.format_status(status)}")


def _consume_loaded_record(record: object) -> None:
    _ = record.Name
    _ = record.Category
    _ = record.Quantity
    _ = record.Price
    _ = record.Active


def _measure_fetch_all(load_record: Callable[[str], object], mode: str, rows: int) -> float:
    runtime = get_runtime()
    table_name = _resolve_sql_table_name(SimpleBenchmarkRecord)
    start = time.perf_counter()
    payload = runtime.call_classmethod(
        "Bench.SimpleBenchmarkHarness",
        "SelectIds",
        table_name,
    )
    if not payload:
        raise RuntimeError(f"{mode} benchmark fetch-all returned an empty payload")

    row_count = 0
    for row_id in json.loads(str(payload)):
        obj = load_record(str(row_id))
        if obj is None:
            raise RuntimeError(f"{mode} benchmark fetch-all failed for id={row_id}")
        _consume_loaded_record(obj)
        row_count += 1
    fetch_all_seconds = time.perf_counter() - start

    if row_count != rows:
        raise RuntimeError(
            f"{mode} benchmark expected {rows} rows from fetch-all, got {row_count}"
        )
    return fetch_all_seconds


def _make_record(index: int) -> SimpleBenchmarkRecord:
    return SimpleBenchmarkRecord(
        Name=f"name-{index}",
        Category=f"group-{index % 10}",
        Quantity=index,
        Price=index / 10.0,
        Active=index % 2 == 0,
    )


def _run_python_benchmark(mode: str, rows: int, iteration: int) -> BenchmarkRun:
    _ensure_benchmark_classes_loaded()
    _reset_extent()

    ids: list[str] = []
    start = time.perf_counter()
    for index in range(rows):
        record = _make_record(index)
        record.save()
        if record.pk is None:
            raise RuntimeError(f"{mode} benchmark save returned no primary key")
        ids.append(record.pk)
    write_seconds = time.perf_counter() - start

    start = time.perf_counter()
    for record_id in ids:
        loaded = SimpleBenchmarkRecord.get(record_id)
        if loaded is None:
            raise RuntimeError(f"{mode} benchmark read failed for id={record_id}")
        _consume_loaded_record(loaded)
    read_seconds = time.perf_counter() - start

    fetch_all_seconds = _measure_fetch_all(SimpleBenchmarkRecord.get, mode, rows)

    return BenchmarkRun(
        mode=mode,
        iteration=iteration,
        rows=rows,
        write_seconds=write_seconds,
        read_seconds=read_seconds,
        fetch_all_seconds=fetch_all_seconds,
    )

def _run_raw_benchmark(mode: str, rows: int, iteration: int) -> BenchmarkRun:
    _ensure_benchmark_classes_loaded()
    _reset_extent()

    runtime = get_runtime()
    class_ref = iris.cls(SimpleBenchmarkRecord._classname)

    ids: list[str] = []

    start = time.perf_counter()
    for index in range(rows):
        obj = class_ref._New()
        obj.Name = f"name-{index}"
        obj.Category = f"group-{index % 10}"
        obj.Quantity = index
        obj.Price = index / 10.0
        obj.Active = 1 if index % 2 == 0 else 0
        status = obj._Save()
        if not runtime.is_ok(status):
            raise RuntimeError(f"{mode} raw benchmark save failed: {runtime.format_status(status)}")
        ids.append(str(obj._Id()))
    write_seconds = time.perf_counter() - start

    start = time.perf_counter()
    for record_id in ids:
        loaded = class_ref._OpenId(record_id)
        if loaded is None:
            raise RuntimeError(f"{mode} raw benchmark read failed for id={record_id}")
        _ = loaded.Name
        _ = loaded.Category
        _ = loaded.Quantity
        _ = loaded.Price
        _ = loaded.Active
    read_seconds = time.perf_counter() - start

    fetch_all_seconds = _measure_fetch_all(
        lambda record_id: iris.cls(SimpleBenchmarkRecord._classname)._OpenId(record_id),
        mode,
        rows,
    )

    return BenchmarkRun(
        mode=mode,
        iteration=iteration,
        rows=rows,
        write_seconds=write_seconds,
        read_seconds=read_seconds,
        fetch_all_seconds=fetch_all_seconds,
    )


def _run_objectscript_benchmark(rows: int, iteration: int) -> BenchmarkRun:
    _ensure_benchmark_classes_loaded()
    table_name = _resolve_sql_table_name(SimpleBenchmarkRecord)
    runtime = get_runtime()
    payload = runtime.call_classmethod(
        "Bench.SimpleBenchmarkHarness",
        "Run",
        table_name,
        rows,
    )
    if not payload:
        raise RuntimeError("ObjectScript benchmark returned an empty payload")
    data = json.loads(str(payload))
    if data.get("rows") != rows:
        raise RuntimeError(
            f"ObjectScript benchmark expected {rows} rows, got {data.get('rows')}"
        )
    if data.get("fetched_rows") != rows:
        raise RuntimeError(
            "ObjectScript benchmark fetched "
            f"{data.get('fetched_rows')} rows instead of {rows}"
        )
    return BenchmarkRun(
        mode="objectscript",
        iteration=iteration,
        rows=rows,
        write_seconds=float(data["write_seconds"]),
        read_seconds=float(data["read_seconds"]),
        fetch_all_seconds=float(data["fetch_all_seconds"]),
    )


def _run_with_embedded(fn: Callable[[], BenchmarkRun]) -> BenchmarkRun:
    configure()
    return fn()


def _run_with_remote(fn: Callable[[], BenchmarkRun]) -> BenchmarkRun:
    connection = _remote_connection()
    try:
        configure(native_connection=connection)
        return fn()
    finally:
        close = getattr(connection, "close", None)
        if callable(close):
            close()
        configure()


def _print_summary(runs: list[BenchmarkRun]) -> None:
    print(
        f"{'mode':<14} {'runs':>4} {'rows':>6} {'write(s)':>11} "
        f"{'read(s)':>11} {'fetch_all(s)':>14} {'write r/s':>11} "
        f"{'read r/s':>10} {'fetch r/s':>10}"
    )
    for mode in (
        "embedded_raw",
        "embedded_orm",
        "remote_raw",
        "remote_orm",
        "objectscript",
    ):
        mode_runs = [run for run in runs if run.mode == mode]
        if not mode_runs:
            continue
        write_avg = statistics.mean(run.write_seconds for run in mode_runs)
        read_avg = statistics.mean(run.read_seconds for run in mode_runs)
        fetch_avg = statistics.mean(run.fetch_all_seconds for run in mode_runs)
        rows = mode_runs[0].rows
        print(
            f"{mode:<14} {len(mode_runs):>4} {rows:>6} "
            f"{write_avg:>11.4f} {read_avg:>11.4f} {fetch_avg:>14.4f} "
            f"{rows / write_avg:>11.1f} {rows / read_avg:>10.1f} {rows / fetch_avg:>10.1f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the same IRIS class via embedded iris_orm, remote iris_orm, "
            "and pure ObjectScript."
        )
    )
    parser.add_argument("--rows", type=int, default=500, help="Rows per benchmark phase.")
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Number of iterations per mode.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw benchmark runs as JSON after the summary table.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Randomization seed used to shuffle benchmark mode order per iteration.",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    runs: list[BenchmarkRun] = []
    for iteration in range(1, args.repeats + 1):
        iteration_runs: list[Callable[[], BenchmarkRun]] = [
            lambda iteration=iteration: _run_with_embedded(
                lambda: _run_raw_benchmark(
                    mode="embedded_raw",
                    rows=args.rows,
                    iteration=iteration,
                )
            ),
            lambda iteration=iteration: _run_with_embedded(
                lambda: _run_python_benchmark(
                    mode="embedded_orm",
                    rows=args.rows,
                    iteration=iteration,
                )
            ),
            lambda iteration=iteration: _run_with_remote(
                lambda: _run_raw_benchmark(
                    mode="remote_raw",
                    rows=args.rows,
                    iteration=iteration,
                )
            ),
            lambda iteration=iteration: _run_with_remote(
                lambda: _run_python_benchmark(
                    mode="remote_orm",
                    rows=args.rows,
                    iteration=iteration,
                )
            ),
            lambda iteration=iteration: _run_with_embedded(
                lambda: _run_objectscript_benchmark(
                    rows=args.rows,
                    iteration=iteration,
                )
            ),
        ]
        rng.shuffle(iteration_runs)
        for run_benchmark in iteration_runs:
            runs.append(run_benchmark())

    _print_summary(runs)
    if args.json:
        print()
        print(json.dumps([asdict(run) for run in runs], indent=2))


if __name__ == "__main__":
    main()
