#!/usr/bin/env bash
# 虾米平台 · 云端服务启动脚本（v2）
# 云端即平台：账号 + skill 市场（私有/公开）+ 个人主页 + 统一主脑 CeoLoop
set -euo pipefail

cd "$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="$PWD/cloud:${PYTHONPATH:-}"

echo "启动虾米平台云端服务 :19000 …"
exec python3 -m cloud.cloud_orchestrator.main
