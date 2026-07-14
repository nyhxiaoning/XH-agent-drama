#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo "  小云雀后端服务启动中..."
echo "  API文档: http://localhost:8000/docs"
echo "========================================"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
