#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export PYTEST_MARK="${PYTEST_MARK:-not integration}"

exec "$SCRIPT_DIR/test-docker.sh" "$@"
