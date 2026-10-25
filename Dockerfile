# ---------- 阶段1: 构建前端 ----------
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---------- 阶段2: Python 运行时 ----------
FROM python:3.13-slim AS runtime
WORKDIR /app

# 依赖先行(利用层缓存)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# 应用代码 + 已构建前端
COPY api/ ./api/
COPY web/ ./web/
COPY resource/ ./resource/
COPY main.py app.py config_template.ini ./
COPY --from=frontend /fe/dist ./frontend/dist

# 运行数据(账号/cookies/日志/设置)挂载持久化
RUN mkdir -p /app/data
VOLUME ["/app/data"]

ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

EXPOSE 5000

# 默认启动 Web 平台; CLI 用法: docker run <img> python main.py -c /app/data/config.ini
CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "5000"]
