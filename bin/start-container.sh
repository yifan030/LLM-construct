#!/usr/bin/env bash
set -e

# 切换到项目根目录（使用 BASH_SOURCE 兼容 source 方式执行）
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# 加载环境变量
if [ -f conf/.env ]; then
    echo "Loading conf/.env..."
    export $(grep -v '^#' conf/.env | xargs)
else
    echo "Warning: conf/.env not found, using default settings"
fi

PORT=${SERVER__PORT:-8083}
HOST=${SERVER__HOST:-0.0.0.0}

echo "Service will start on ${HOST}:${PORT}"

# 检查端口是否被占用，如果被占用则杀掉旧进程
echo "Checking port ${PORT}..."
if python3 -c "import socket; s=socket.socket(); s.bind(('', ${PORT})); s.close()" 2>/dev/null; then
    echo "Port ${PORT} is available"
else
    echo "Port ${PORT} is already in use, stopping existing service..."
    pkill -f "uvicorn service.main:app --host ${HOST} --port ${PORT}" || true
    sleep 2
fi

# 安装/更新依赖
echo "Installing dependencies..."
pip install -r requirements.txt

# 启动服务
echo "Starting service..."
nohup uvicorn service.main:app --host "${HOST}" --port "${PORT}" > /tmp/app.log 2>&1 &

PID=$!
echo "Service started, PID: ${PID}"

# 等待服务就绪
sleep 3
if curl -sf "http://127.0.0.1:${PORT}/health" > /dev/null 2>&1; then
    echo "✅ Service is healthy: http://127.0.0.1:${PORT}/health"
else
    echo "⚠️  Service may not be ready yet, check logs:"
    echo "   tail -f /tmp/app.log"
fi

echo ""
echo "Useful commands:"
echo "  View logs:    tail -f /tmp/app.log"
echo "  Health check: curl http://127.0.0.1:${PORT}/health"
echo "  Stop service: bin/stop-container.sh"
