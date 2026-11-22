#!/usr/bin/env bash
# 一键启动脚本：云子域 · 二级域名分发系统
set -e
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
PORT=${PORT:-8000}
HOST=${HOST:-0.0.0.0}

if ! $PY -c "import fastapi, uvicorn, jwt, requests" >/dev/null 2>&1; then
  echo "[1/3] 安装依赖 ..."
  $PY -m pip install -r requirements.txt
else
  echo "[1/3] 依赖已就绪"
fi

mkdir -p data
echo "[2/3] 数据库：${SDH_DB:-data/app.db}（首次启动自动建表并写入演示数据）"
echo "[3/3] 启动服务：http://${HOST}:${PORT}  文档：http://${HOST}:${PORT}/docs"
exec $PY -m uvicorn app.main:app --host "$HOST" --port "$PORT" --workers 1
