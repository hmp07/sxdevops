#!/bin/sh
set -eu

wait_for_tcp() {
  host="$1"
  port="$2"
  label="$3"

  python - "$host" "$port" "$label" <<'PY'
import socket
import sys
import time

host, port, label = sys.argv[1], int(sys.argv[2]), sys.argv[3]
deadline = time.time() + 120
while time.time() < deadline:
    try:
        with socket.create_connection((host, port), timeout=3):
            print(f"{label} is ready")
            sys.exit(0)
    except OSError:
        time.sleep(2)

raise SystemExit(f"Timed out waiting for {label} at {host}:{port}")
PY
}

if [ "${SXDEVOPS_WAIT_FOR_DB:-1}" = "1" ]; then
  wait_for_tcp "${MYSQL_HOST:-mysql}" "${MYSQL_PORT:-3306}" "MySQL"
fi

# 演示模式：首次启动种子一次，重启保留演示数据与聊天历史。
# SXDEVOPS_RESEED=1 强制重新种子；SXDEVOPS_SEED_MARKER 可自定义标记路径。
SEED_MARKER="${SXDEVOPS_SEED_MARKER:-/data/.seeded}"
RUN_SEED=1
if [ "${SXDEVOPS_SKIP_SEED_IF_MARKED:-1}" = "1" ] && [ -f "$SEED_MARKER" ] && [ "${SXDEVOPS_RESEED:-0}" != "1" ]; then
  RUN_SEED=0
  echo "Seed marker found ($SEED_MARKER), skipping seed. Set SXDEVOPS_RESEED=1 to force."
fi

if [ "${SXDEVOPS_MIGRATE:-1}" = "1" ]; then
  python manage.py migrate --noinput
fi

# 演示种子默认关闭（安全加固）；需要演示数据时显式 SXDEVOPS_SEED_DATA=1
if [ "${SXDEVOPS_SEED_DATA:-0}" = "1" ] && [ "$RUN_SEED" = "1" ]; then
  python manage.py seed_data
elif [ "${SXDEVOPS_SEED_DATA:-0}" != "1" ]; then
  # 生产模式（不加载演示种子）：仅确保管理员账号按 .env 口令初始化。
  # 幂等且廉价，每次启动执行，用于把默认演示口令加固为环境变量口令。
  python manage.py ensure_admin
fi

if [ "${SXDEVOPS_SEED_TEMPLATES:-1}" = "1" ] && [ "$RUN_SEED" = "1" ]; then
  python manage.py seed_templates
fi

if [ "$RUN_SEED" = "1" ]; then
  mkdir -p "$(dirname "$SEED_MARKER")" 2>/dev/null || true
  touch "$SEED_MARKER" 2>/dev/null || true
fi

# 演示环境真实 LLM：配置 DEEPSEEK_API_KEY 时自动接入 DeepSeek 并默认切换真实模型。
# SXDEVOPS_LLM_DEMO_MOCK=1 可显式强制回离线模拟模型（0 表示真实模型）。
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  python manage.py provision_llm_provider
  if [ -z "${SXDEVOPS_LLM_DEMO_MOCK:-}" ]; then
    export SXDEVOPS_LLM_DEMO_MOCK=0
  fi
fi

exec "$@"
