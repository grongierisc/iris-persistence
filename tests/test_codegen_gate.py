from __future__ import annotations

from benchmarks.codegen_gate import CodegenRun, evaluate_runs


def _run(runtime: str, implementation: str, mixed: float) -> CodegenRun:
    return CodegenRun(runtime, implementation, 1, 100, 0.01, 0.02, 0.03, mixed)


def test_gate_requires_twenty_percent_in_every_runtime_without_p95_regression():
    runs = [
        _run("embedded", "generated", 0.70),
        _run("embedded", "generated", 0.75),
        _run("embedded", "generic", 1.00),
        _run("embedded", "generic", 1.05),
        _run("native", "generated", 0.85),
        _run("native", "generated", 0.90),
        _run("native", "generic", 1.00),
        _run("native", "generic", 1.05),
    ]

    decisions = evaluate_runs(runs, ("embedded", "native"))

    assert decisions[0].passed is True
    assert decisions[1].passed is False
