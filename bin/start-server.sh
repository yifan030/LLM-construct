#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

echo "Starting application on server (using existing middleware)..."
python -m service.main
