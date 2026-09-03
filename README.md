# musico

自托管音乐热榜：QQ 音乐热歌榜 + 网易云热歌榜。只聚合公开元数据和官方预览，不解灰、不下载、不做跨平台同一首歌匹配。

改 `configs/boards.yaml`（含 `interval_sec`）后必须**重启容器**，调度间隔不会热更新。

## 启动

```bash
cp .env.example .env
docker compose up -d --build
```

应用镜像目标 < 200MB（Alpine 多阶段）。若 `docker compose` 拉官方镜像超时，可先从镜像站拉取再打官方 tag，例如：

```bash
docker pull docker.m.daocloud.io/library/python:3.12-alpine
docker tag docker.m.daocloud.io/library/python:3.12-alpine python:3.12-alpine
```

约 30 秒内完成建表；首次拉榜后 `GET /api/v1/health` 的 `data.status` 为 `ready`（各 enabled 榜至少一条成功快照）。打开 http://127.0.0.1:8080 。

本地开发：

```bash
cd backend
pip install -e ".[dev]"
# 需要可用的 PostgreSQL，或先 docker compose up -d postgres
uvicorn app.main:create_app --factory --reload --port 8080

cd ../frontend
npm install
npm run dev
```

## 加第三个平台

1. 复制 `backend/app/plugins/qqmusic/`
2. 改 `plugin.toml`（`id`、`config_schema.required`）
3. 实现 `charts.py` 的 `create_chart` / `fetch_board`，返回 `RawRankItem`
4. 在 `configs/boards.yaml` 加一行，`platform` 对应该 `id`
5. 加一份录制 JSON fixture 单测

不必改 FastAPI 路由或调度器。

## 完成定义

- `docker compose up -d` 后 Alembic 自动建表
- 两榜入库后 `/api/v1/health` 为 `ready`
- `frontend` 的 `npm run build` 通过
- 应用镜像（Python + 静态资源）目标 < 200MB
