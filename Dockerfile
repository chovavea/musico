FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-alpine AS wheels
WORKDIR /src
ENV PYTHONDONTWRITEBYTECODE=1
# pip 默认 15 秒读超时，在国内网络下拉这些轮子（uvloop/httptools/watchfiles 等
# C/Rust 扩展）很容易中途 Read timed out 而整层构建失败；放宽到 60 秒。
ENV PIP_DEFAULT_TIMEOUT=60
# 这份清单要与 server/pyproject.toml 的 [project].dependencies 对齐：
# - uvicorn 必须带 [standard]：uvloop/httptools 是 uvicorn 的加速实现，缺了会退回
#   纯 Python 事件循环（容器里吞吐明显下降）；
# - 刻意不装 asyncpg 与 python-multipart：前者在 settings.py / database.py 里会被
#   改写成 psycopg 驱动，运行期用不到；后者是 pyproject 里的历史遗留，代码里没有
#   表单/文件上传接口用到它。
RUN pip install --no-cache-dir --prefix=/install \
      "fastapi>=0.115.0" \
      "uvicorn[standard]>=0.32.0" \
      "sqlalchemy[asyncio]>=2.0.36" \
      "psycopg[binary]>=3.2.0" \
      "alembic>=1.14.0" \
      "pydantic-settings>=2.6.0" \
      "httpx>=0.27.0" \
      "structlog>=24.4.0" \
      "apscheduler>=3.10.4" \
      "pyyaml>=6.0.2" \
      "mutagen>=1.47.0"

FROM python:3.12-alpine
WORKDIR /app/server
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=wheels /install /usr/local
COPY server/app ./app
COPY server/alembic ./alembic
COPY server/alembic.ini ./alembic.ini
COPY --from=web /web/dist /app/web/dist
COPY configs /app/configs
COPY server/app/download_sources /app/download_sources
ENV BOARDS_YAML=/app/configs/boards.yaml
ENV DOWNLOAD_SOURCE_CONFIG=/app/configs/download_sources.yaml DOWNLOAD_SOURCE_DIRS=/app/download_sources
ENV MUSIC_LIBRARY_DIR=/app/data/music
# 非 root 运行：容器逃逸需要第二个漏洞，且写入 bind mount（音乐库）的文件
# 属于 uid 1000，而不是宿主上的 root。数据目录先建好再交给 appuser，
# 这样不带卷直接 docker run 也不会在 mkdir 时失败；Compose 的 bind mount
# 则由一次性的 music-init 容器修复挂载目录权限，应用进程仍保持非 root。
RUN adduser -D -u 1000 appuser \
    && mkdir -p /app/data/music \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 8080
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
