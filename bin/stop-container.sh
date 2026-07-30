#!/usr/bin/env bash
set -e

# 切换到项目根目录
cd "$(dirname "$0")/.."

# 加载环境变量获取端口
if [ -f conf/.env.prod ]; then
    export $(grep -v '^#' conf/.env.prod | xargs)
fi

PORT=${SERVER__PORT:-8083}
HOST=${SERVER__HOST:-0.0.0.0}

echo "Stopping service on ${HOST}:${PORT}..."
pkill -f "uvicorn service.main:app --host ${HOST} --port ${PORT}" || true

echo "✅ Service stopped"
