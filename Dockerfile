FROM node:22-alpine AS frontend
WORKDIR /web
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
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
WORKDIR /app/backend
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=wheels /install /usr/local
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./alembic.ini
COPY --from=frontend /web/dist /app/frontend/dist
COPY configs /app/configs
COPY backend/app/download_sources /app/download_sources
ENV BOARDS_YAML=/app/configs/boards.yaml
ENV DOWNLOAD_SOURCE_CONFIG=/app/configs/download_sources.yaml DOWNLOAD_SOURCE_DIRS=/app/download_sources
ENV MUSIC_LIBRARY_DIR=/app/data/music
EXPOSE 8080
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080"]
