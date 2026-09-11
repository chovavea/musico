# musico

自托管音乐热榜：QQ 音乐热歌榜 + 网易云热歌榜 + 哔哩哔哩音乐热歌榜，并支持通过独立下载源插件保存高规格音频到本地音乐库。下载源只使用其公开、授权的页面或直链，不绕过 DRM 或第三方访问限制。

改 `configs/boards.yaml`（含 `interval_sec`）后必须**重启容器**，调度间隔不会热更新。

## 启动

```bash
cp .env.example .env
docker compose up -d --build
```

应用设置全部写在 `.env`（compose 用 `env_file` 整份注入容器），新增开关不需要改 `docker-compose.yml`；只有描述容器本身的值（`DATABASE_URL`、`BOARDS_YAML`、`MUSIC_LIBRARY_DIR`、`DOWNLOAD_SOURCE_*`、`TZ`）由 compose 覆盖。改 `.env` 后需要 `docker compose up -d` 重建容器（不是 `restart`）。

应用镜像目标 < 200MB（Alpine 多阶段）。若 `docker compose` 拉官方镜像超时，可先从镜像站拉取再打官方 tag，例如：

```bash
docker pull docker.m.daocloud.io/library/python:3.12-alpine
docker tag docker.m.daocloud.io/library/python:3.12-alpine python:3.12-alpine
```

约 30 秒内完成建表；首次拉榜后 `GET /api/v1/health` 的 `data.status` 为 `ready`（各 enabled 榜至少一条成功快照）。打开 http://127.0.0.1:8080 。

## 搜索

首页顶部搜索框支持输入联想，回车后进入独立搜索结果页。搜索会并行查询已注册的
`SearchPort` 平台（当前包括 QQ 音乐和网易云音乐），将标题、主歌手和时长相符的同一首歌
合并展示；播放和下载默认选择已有曲库或历史可播率更优的平台候选。

接口：

```text
GET /api/v1/search?q=周杰伦&type=suggest&limit=5
GET /api/v1/search?q=周杰伦&type=full&limit=20
```

搜索结果只在响应层临时聚合，不会写入歌曲历史或创建下载任务；下载和曲库状态仍复用现有
`/api/v1/downloads` 与 `/api/v1/library` 流程。

本地开发：

```bash
cd server
pip install -e ".[dev]"
# 需要可用的 PostgreSQL，或先 docker compose up -d postgres
uvicorn app.main:create_app --factory --reload --port 8080

cd ../web
npm install
npm run dev
```

## 下载源插件

下载源位于 `server/app/download_sources/`，通过 `plugin.toml` 声明入口和允许的主机。启用状态、优先级和站点地址写在 `configs/download_sources.yaml`（`config.base_url`），修改后重启 musico 生效；外部插件目录可通过 `DOWNLOAD_SOURCE_DIRS` 挂载。若换镜像站，把 `config.base_url` 改成新域名即可，必要时再加同级 `hosts` 作为额外允许的下载主机。

内置下载源包括 `aries` 和 `taurus`。`taurus` 调用 `example.invalid` 的搜索与音频地址解析接口，默认只声明未验证采样率/位深的 FLAC 候选；该站点可能要求正常授权会话，按 `config.cookie_env` 指定的环境变量提供 Cookie（默认 `MUSICO_DL_TAURUS_COOKIE`）。不要把真实 Cookie 写入仓库，也不要在代码中实现或复现站点的反爬 Challenge；没有有效会话时，源会将搜索/解析失败交给下载源回退链路处理。

核心负责歌曲匹配、三种允许下载格式（FLAC / WAV / DSF）的质量排序与降级、单任务队列、重试、断点续传、SHA-256 校验和文件入库。多个下载源按照 `configs/download_sources.yaml` 中的 `priority` 从高到低串行检索；候选池再按实际下载质量从高到低排序，同质量时优先使用源 `priority` 高者。未指定 `requested_quality` 时，优先尝试最高质量，下载失败后按候选质量依次降级；指定了格式或采样维度时只匹配该要求，不跨格式降级。下载源只实现 `search` 和 `resolve`，不直接操作文件。

音乐文件默认写入 `data/music/`，容器部署时通过 `MUSIC_LIBRARY_DIR` 修改。PostgreSQL 中的 `musico_library` schema 保存曲目、文件引用和下载任务，不保存音频二进制。

哔哩哔哩音乐插件使用其公开的全站音乐榜、音乐详情和官方试听接口；榜单类型写在 `configs/boards.yaml` 的 `extra.list_type` 中（`1` 为热歌榜，`3` 为二创榜），插件会自动选择对应类型的最新一期。哔哩哔哩音乐站点当前没有与 QQ / 网易同形态的匿名关键词搜索接口，因此本次只接入榜单和本平台官方试听，不把普通视频搜索结果冒充为音频歌曲。

## 试听回退

按固定四档顺序尝试，每档都失败才进入下一档：**本地曲库** → **原平台官方试听** → **其他平台官方试听** → **下载源插件**（只出试听流，不建下载任务）。整条链路串行，同一时刻最多一条出站请求。QQ 官方播放器报错或 12 秒内未开始播放时进入这个档位，不再直接跳到下载源。

- 跨平台档**按顺序逐个平台请求，不并发**：平台之间按「该平台组合的历史可播率 → 平台 id」排序（不设静态平台优先级），先搜第一个平台、解析试听地址、打开音频流，只有这一步没出音才去问下一个平台；同一时刻最多只有一条出站请求。可播率是 Beta 后验 `(成功 + 1) / (总数 + 2)`，样本不足时先退化为按目标平台聚合、再退化为全局，冷启动各平台同为 0.5。**样本判定**：本次出音的那个平台记成功，被问过却没能出音的平台（搜到候选但打不开、候选全被匹配守卫拒掉、搜索返回空）逐个记失败，所以只会失败的平台会被逐步降权；搜索自身抛错或超时的平台不计样本，避免一次网络抖动误伤正常平台。
- 跨平台匹配校验：标题与时长必须一致（阈值 `PREVIEW_MATCH_MIN_SCORE`，默认 0.94，ISRC 命中直接放行），主歌手必须匹配，原曲不含版本词而候选含 Live / 伴奏 / Remix / 现场 / 翻唱等版本词时直接拒绝，避免听到 Live 或翻唱。
- 平台内部候选按「匹配分 → 搜索排名」排序，最多试 `PREVIEW_MAX_CANDIDATES` 个；第一个通过「首字节非空且不是 HTML」检查的即本次播放源，后面的平台就不会再被请求。搜索与解析不再套用旧的 3 秒单次超时（慢但正确的平台不该被判成不可播），出站调用的两个旋钮都按 1 分钟给：单次调用上限 `PREVIEW_CALL_TIMEOUT_SEC`（默认 60，作用于预览 HTTP 客户端、打开音频、T3 搜索/解析），整段跨平台预算 `PREVIEW_DEADLINE_SEC`（默认 60）。预算耗尽且没拿到任何音频时直接落到下载源档，且**不会**写不可播缓存（超时不能证明这首歌放不出来）。结果按 `platform:external_id` 缓存：可播 10 分钟、不可播 3 分钟；缓存的签名地址打不开时立即废弃该条并重新搜索。
- 缓存命中只是重放上一次已经记过账的决定：命中时不再往可播率里投票、也不再落 `preview_event` 行（同一次上游成功不能被同一次点击重复计数），只写一条 `cached=true` 的结构化日志。
- 每次点击都会在 `musico_library.preview_event` 落行（档位、来源平台、匹配分、耗时、状态、错误）：除了本次选中的源，跨平台档里每个被问过但没出音的目标平台也会各落一行 `tier=T2 / status=error`，用于排查「这次到底用了哪个源、为什么没播」；`musico_library.preview_source_stat` 是启动时按近 7 天事件刷新的聚合表（成功与失败都计入）。这些记录只用于排查，**前端不展示来源**。
- 下载源档**同样是逐个站点串行，不并发**：把全部**已启用**的下载源按优先级排序，先用优先级最高的源搜索（按歌名、歌手及可用的时长等信息匹配歌曲），命中的候选再按「浏览器支持且较轻量的格式 → 采样率 → 位深」逐个尝试，跳过 DSD 等不能直接试听的格式；只有这个源一个都放不出音，才去问下一个源。某个站点搜索、解析或打开音源失败不会阻断其他站点。
- 回退音频直接流式播放，支持暂停和拖动进度，**不会创建下载任务或自动加入曲库**。所有候选均不可用时显示无可用音源提示。
- 试听失败时保持当前曲目选中并显示提示，不会静默跳到下一首；需要继续时用播放器的“下一首”或重新点击其他曲目。
- 下载源站点限制匿名访问时（例如 aries 每日免费额度用尽后返回“今日访问已达限额”），该站点按无候选处理并记录 `download_source_access_limited` 日志，其余下载源仍会继续尝试。
- 新增并启用下载源插件后会自动参与试听回退；平台插件只要在 `plugin.toml` 声明 `search` 和 `preview` 能力就会自动成为跨平台试听来源，核心不写平台分支。

## 加第三个平台

1. 复制 `server/app/plugins/qqmusic/`
2. 改 `plugin.toml`（`id`、`config_schema.required`）
3. 实现 `charts.py` 的 `create_chart` / `fetch_board`，返回 `RawRankItem`
4. 在 `configs/boards.yaml` 加一行，`platform` 对应该 `id`
5. 加一份录制 JSON fixture 单测

想让新平台参与跨平台试听回退，再加一个 `search.py`（导出 `create_search`）并在 `plugin.toml` 的 `capabilities` 里声明 `"search"`；核心会自动把它列为试听来源。不必改下载队列或 FastAPI 路由。哔哩哔哩插件暂不声明 `search`，避免把普通视频或翻唱误当成官方音频候选。

## 安全与暴露边界

- **下载与试听不自动跟随重定向**：下载 worker、官方试听及下载站点试听代理在每次跳转后重新校验主机白名单（来自 `plugin.toml` / 内置后缀表），并拒绝解析到私有、环回或链路本地地址的目标，防止 302 到内网或云元数据地址（SSRF）。跨站跳转时不转发敏感请求头。
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
- `web` 的 `npm run build` 通过
- `web` 的 `npm test` 通过（播放器和试听回退回归测试）
- 应用镜像（Python + 静态资源）目标 < 200MB
