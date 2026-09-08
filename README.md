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

## 安全与暴露边界

- **下载与试听不自动跟随重定向**：下载 worker 和官方试听代理在每次跳转后重新校验主机白名单（来自 `plugin.toml` / 内置后缀表），并拒绝解析到私有、环回或链路本地地址的目标，防止 302 到内网或云元数据地址（SSRF）。
- **可选 API Token**：设置 `API_TOKEN` 后，所有 `POST` / `DELETE` / 其他写操作的 `/api/v1/*` 请求必须携带 `Authorization: Bearer <token>` 或 `X-API-Token: <token>`，否则返回 401。示例：
  ```bash
  curl -X POST http://127.0.0.1:8080/api/v1/downloads \
    -H "Authorization: Bearer $API_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"platform":"qqmusic","external_id":"xxx","title":"晴天","artist":"周杰伦"}'
  ```
  读接口（榜单、健康检查、曲库列表/试听）默认不鉴权；浏览器访问整套 UI 时建议在前面加一层反向代理认证，并仅在内网或本机暴露（默认 `docker compose` 将 `8080` 绑到所有网卡，可改为 `127.0.0.1:8080:8080`）。
- **下载 worker 是单实例设计**：`.part` 续传文件与任务租约强相关，当前数据库租约只保护写库、不保护同一任务跨进程写同一磁盘文件；请勿对 musico 服务水平扩容多个副本，也不要为同一 `MUSIC_LIBRARY_DIR` 挂载启动第二个 worker。
- 榜单抓取与下载使用独立的 HTTP 客户端与连接池，长连接大文件不会拖慢抓榜/健康检查；预览与下载各有独立的读超时。

## 完成定义

- `docker compose up -d` 后 Alembic 自动建表
- 两榜入库后 `/api/v1/health` 为 `ready`
- `frontend` 的 `npm run build` 通过
- 应用镜像（Python + 静态资源）目标 < 200MB
