#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$project_root/.venv/bin/python" ]]; then
  printf '%s\n' '未找到 .venv；请先按 README.md 安装依赖。' >&2
  exit 1
fi
export QT_API=pyside6
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$project_root/.venv/bin/python" -m gimbal_lab "$@"

