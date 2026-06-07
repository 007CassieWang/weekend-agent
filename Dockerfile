# ===== Stage 1: Build Frontend =====
FROM node:22-slim AS frontend-builder

WORKDIR /app/frontend

# 复制所有前端文件，在同一层完成安装+构建
# --force 标志强制 npm 重新解析并安装所有可选依赖（包括 @rollup/rollup-linux-x64-gnu）
# 解决 npm 可选依赖跳过导致 Vite build 报 MODULE_NOT_FOUND 的问题
COPY frontend/ ./
RUN npm install --force && npm run build

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
