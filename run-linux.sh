#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Сначала запусти: bash setup-linux.sh"
  exit 1
fi
exec .venv/bin/python linux_main.py "$@"
