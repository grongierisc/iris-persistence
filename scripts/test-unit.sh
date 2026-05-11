#!/usr/bin/env bash
set -euo pipefail

if [ "${PYTHON_BIN:-}" ]; then
  PYTHON="$PYTHON_BIN"
elif [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
else
  PYTHON="python3"
fi

if [ "$#" -eq 0 ]; then
  PYTEST_ARGS=(-m "not integration")
else
  PYTEST_ARGS=("$@")
fi

exec "$PYTHON" -m pytest "${PYTEST_ARGS[@]}"
