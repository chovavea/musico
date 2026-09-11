FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-alpine AS wheels
WORKDIR /src
ENV PYTHONDONTWRITEBYTECODE=1
RUN pip install --no-cache-dir --prefix=/install \
      "fastapi>=0.115.0" \
      "uvicorn>=0.32.0" \
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
EXPOSE 8080
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
