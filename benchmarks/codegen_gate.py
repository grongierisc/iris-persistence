"""Validate and summarize the recorded generated-code benchmark decision."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

MINIMUM_MEDIAN_IMPROVEMENT = 0.20
MAXIMUM_P95_REGRESSION = 0.05
DEFAULT_REPORT = Path(__file__).parent / "results" / "codegen-gate.json"
RUNTIMES = ("embedded", "native")
IMPLEMENTATIONS = ("generated", "generic")


@dataclass(frozen=True)
class CodegenRun:
    runtime: str
    implementation: str
    iteration: int
    rows: int
    init_seconds: float
    save_seconds: float
    load_seconds: float
    mixed_seconds: float


@dataclass(frozen=True)
class RuntimeDecision:
    runtime: str
    generated_median_seconds: float
    generic_median_seconds: float
    median_improvement: float
    generated_p95_seconds: float
    generic_p95_seconds: float
    p95_regression: float
    passed: bool


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("cannot calculate a percentile without samples")
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def evaluate_runs(runs: Sequence[CodegenRun], runtimes: Sequence[str]) -> list[RuntimeDecision]:
    decisions: list[RuntimeDecision] = []
    for runtime in runtimes:
        samples = {
            implementation: [
                run.mixed_seconds
                for run in runs
                if run.runtime == runtime and run.implementation == implementation
            ]
            for implementation in IMPLEMENTATIONS
        }
        missing = [name for name, values in samples.items() if not values]
        if missing:
            raise ValueError(f"missing {runtime} samples for: {', '.join(missing)}")

        generated_median = statistics.median(samples["generated"])
        generic_median = statistics.median(samples["generic"])
        generated_p95 = _percentile(samples["generated"], 0.95)
        generic_p95 = _percentile(samples["generic"], 0.95)
        median_improvement = (generic_median - generated_median) / generic_median
        p95_regression = (generated_p95 - generic_p95) / generic_p95
        decisions.append(
            RuntimeDecision(
                runtime=runtime,
                generated_median_seconds=generated_median,
                generic_median_seconds=generic_median,
                median_improvement=median_improvement,
                generated_p95_seconds=generated_p95,
                generic_p95_seconds=generic_p95,
                p95_regression=p95_regression,
                passed=(
                    median_improvement >= MINIMUM_MEDIAN_IMPROVEMENT
                    and p95_regression <= MAXIMUM_P95_REGRESSION
                ),
            )
        )
    return decisions


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-evaluate a recorded code-generation gate.")
    parser.add_argument("--input", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    report = json.loads(args.input.read_text())
    runs = [CodegenRun(**run) for run in report["runs"]]
    decisions = evaluate_runs(runs, RUNTIMES)
    print(json.dumps([decision.__dict__ for decision in decisions], indent=2, sort_keys=True))
    if any(decision.passed for decision in decisions):
        raise SystemExit("report no longer matches the recorded remove-codegen decision")


if __name__ == "__main__":
    main()
