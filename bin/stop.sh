#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

echo "Stopping application..."
pkill -f "service.main" || true

echo "Stopping infrastructure..."
docker compose down
