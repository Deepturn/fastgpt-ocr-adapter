#!/usr/bin/env bash
set -euo pipefail

marker="/models/.pipeline-ready"
config="${MINERU_TOOLS_CONFIG_JSON:-/models/mineru.json}"

if [[ ! -f "$marker" || ! -f "$config" ]]; then
  echo "Downloading MinerU 3.4.4 pipeline models from ModelScope..."
  MINERU_MODEL_SOURCE=modelscope mineru-models-download -s modelscope -m pipeline
  test -f "$config"
  touch "$marker"
fi

exec "$@"
