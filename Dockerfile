FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
# 镜像源抖动会导致 npm ci 失败：提高 fetch 重试次数（npm 默认仅 2 次）
RUN npm ci --fetch-retries=5 --fetch-timeout=300000

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
# 阿里云镜像偶发 Read timed out 会直接中断构建：加长单次超时与重试次数，
# 并对整步再做最多 3 次重试，避免网络抖动导致整次 build 失败
RUN for attempt in 1 2 3; do \
        pip install --no-cache-dir --timeout 120 --retries 10 -r /app/backend/requirements.txt && exit 0 || echo "pip install attempt ${attempt} failed, retrying..."; \
        sleep 5; \
    done; exit 1

COPY backend/ /app/backend/
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist
COPY docker/entrypoint.sh /entrypoint.sh

# Windows 检出可能带 CRLF 行尾，破坏 shebang，统一转为 LF
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

WORKDIR /app/backend

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
# --http-timeout：挂起的请求 60s 后由 daphne 主动 503 并写访问日志，
# 避免故障静默无痕（历史问题：请求被阻塞时访问日志无记录、客户端只见超时）
CMD ["python", "-m", "daphne", "-b", "0.0.0.0", "-p", "8000", "--http-timeout", "60", "sxdevops.asgi:application"]
