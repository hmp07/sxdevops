FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

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
