# musico

自托管音乐热榜：QQ 音乐热歌榜 + 网易云热歌榜，并支持通过独立下载源插件保存高规格音频到本地音乐库。下载源只使用其公开、授权的页面或直链，不绕过 DRM 或第三方访问限制。

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

## 下载源插件

下载源位于 `backend/app/download_sources/`，通过 `plugin.toml` 声明入口和允许的主机。启用状态和优先级写在 `configs/download_sources.yaml`，修改后重启 musico 生效；外部插件目录可通过 `DOWNLOAD_SOURCE_DIRS` 挂载。

核心负责歌曲匹配、最高质量选择、单任务队列、重试、断点续传、SHA-256 校验和文件入库。下载源只实现 `search` 和 `resolve`，不直接操作文件。

音乐文件默认写入 `data/music/`，容器部署时通过 `MUSIC_LIBRARY_DIR` 修改。PostgreSQL 中的 `musico_library` schema 保存曲目、文件引用和下载任务，不保存音频二进制。

## 加第三个平台

1. 复制 `backend/app/plugins/qqmusic/`
2. 改 `plugin.toml`（`id`、`config_schema.required`）
3. 实现 `charts.py` 的 `create_chart` / `fetch_board`，返回 `RawRankItem`
4. 在 `configs/boards.yaml` 加一行，`platform` 对应该 `id`
5. 加一份录制 JSON fixture 单测

不必改下载队列或 FastAPI 路由。

## 完成定义

- `docker compose up -d` 后 Alembic 自动建表
- 两榜入库后 `/api/v1/health` 为 `ready`
- `frontend` 的 `npm run build` 通过
- 应用镜像（Python + 静态资源）目标 < 200MB
