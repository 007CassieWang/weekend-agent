# ===== Stage 1: Build Frontend =====
FROM node:22-slim AS frontend-builder

WORKDIR /app/frontend

# 复制前端源码并构建（package-lock.json 已通过 .dockerignore 排除，
# npm 将在 Linux 上重新生成 lockfile，确保原生模块正确安装）
COPY frontend/ ./
RUN npm install && npm run build

# ===== Stage 2: Python Runtime =====
FROM python:3.12-slim

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码和数据文件
COPY *.py ./
COPY config/ ./config/
COPY data/ ./data/

# 从阶段 1 复制前端构建产物
COPY --from=frontend-builder /app/frontend/dist/ ./frontend/dist/

# Railway 通过 $PORT 环境变量动态分配端口
EXPOSE 8080

# 启动服务
CMD ["sh", "-c", "uvicorn api:app --host 0.0.0.0 --port ${PORT:-8080}"]
