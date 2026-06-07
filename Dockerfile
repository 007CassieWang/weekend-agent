# ===== Stage 1: Build Frontend =====
FROM node:22-slim AS frontend-builder

WORKDIR /app/frontend

# 复制所有前端文件，删除 macOS 生成的 lockfile 后在同一层安装+构建
# 强制 npm 在 Linux 上重新解析依赖，确保 @rollup/rollup-linux-x64-gnu 被正确安装
COPY frontend/ ./
RUN rm -f package-lock.json node_modules && npm install && npm run build

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
