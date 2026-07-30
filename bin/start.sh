#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

echo "Starting infrastructure..."
docker compose up -d mysql redis minio-app

echo "Waiting for MySQL..."
until docker exec llm-mysql mysql -uroot -proot -e "SELECT 1" >/dev/null 2>&1; do
  sleep 1
done

echo "Waiting for Redis..."
until docker exec llm-redis redis-cli ping | grep -q PONG; do
  sleep 1
done

echo "Waiting for MinIO..."
until curl -sf http://localhost:9000/minio/health/live >/dev/null 2>&1; do
  sleep 1
done

echo "Starting application..."
python -m service.main
