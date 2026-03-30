#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}/python${PYTHONPATH:+:${PYTHONPATH}}"

exec "${PYTHON_BIN:-python3}" -m make_ansible_portable.cli install-collections "$@"
