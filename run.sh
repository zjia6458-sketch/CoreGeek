#!/usr/bin/env bash
set -euo pipefail

PORT="${1:?usage: bash run.sh <port>}"
exec python main3.py "$PORT"
