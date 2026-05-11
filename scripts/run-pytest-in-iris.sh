#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${IRIS_APP_DIR:-/irisdev/app}"
VENV_DIR="${PYTEST_VENV_DIR:-/tmp/iris-persistence-pytest-venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
IRIS_INSTALL_DIR="${IRISINSTALLDIR:-${ISC_PACKAGE_INSTALLDIR:-/usr/irissys}}"

export IRISINSTALLDIR="${IRISINSTALLDIR:-$IRIS_INSTALL_DIR}"
export LD_LIBRARY_PATH="${IRIS_INSTALL_DIR}/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="${APP_DIR}${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
export PYTEST_ADDOPTS="${PYTEST_ADDOPTS:+$PYTEST_ADDOPTS }-p no:cacheprovider"

cd "$APP_DIR"

# The repository is mounted read-only in the test container; keep all runtime
# setup in /tmp and do not let IRIS rewrite the mounted merge file.
unset ISC_CPF_MERGE_FILE

"$PYTHON_BIN" -m venv --clear "$VENV_DIR"
# shellcheck disable=SC1091
. "$VENV_DIR/bin/activate"

python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install -r requirements.txt

export IRIS_HOST="${IRIS_HOST:-localhost}"
export IRIS_PORT="${IRIS_PORT:-1972}"
export IRIS_NAMESPACE="${IRIS_NAMESPACE:-${IRISNAMESPACE:-IRISAPP}}"
export IRISNAMESPACE="${IRISNAMESPACE:-$IRIS_NAMESPACE}"
export IRISUSERNAME="${IRISUSERNAME:-SuperUser}"
export IRISPASSWORD="${IRISPASSWORD:-SYS}"

exec python3 -m pytest "$@"
