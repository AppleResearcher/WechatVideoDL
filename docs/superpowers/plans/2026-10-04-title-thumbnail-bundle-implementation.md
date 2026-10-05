# WechatVideoDL 标题化历史、缩略图与打包下载 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让新版 WechatVideoDL 以真实视频标题和缩略图为主要识别信息，使用 `视频标题__000012` 统一命名分析文本、MP4、缩略图和 ZIP，并提供一键打包下载、可点击源链接与“微信打开”入口，同时保持旧历史、旧文件、反代和 API 兼容。

**Architecture:** 继续保留 `wxv_000012` 作为内部稳定 job ID；Browserless 已有 `title` / `coverUrl` 继续作为元数据来源。新增标题文件名策略、缩略图服务和 ZIP bundle 服务，把人类可读文件名与数据库主键分离；SQLite 通过幂等列迁移兼容旧库，UI 只把标题提升为主要视觉标识。

**Tech Stack:** Python 3.12, Flask 3, sqlite3 stdlib, requests, yt-dlp, ffmpeg/ffprobe, zipfile stdlib, Browserless Chromium, vanilla HTML/CSS/JS, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-04-title-thumbnail-bundle-design.md`

## Global Constraints

- 正式主仓库固定为 `https://github.com/topgptus/WechatVideoDL`；`samni728/WechatVideoDL` 仅作为旧版干净基线，不默认同步发布。
- 内部 job ID 继续使用 `wxv_\d{6}`；不得用标题替代数据库主键。
- 新任务用户可见文件名采用 `安全化视频标题__000012.ext`，同一任务的 `.md/.txt/.mp4/.jpg/.zip` 必须共享同一个 stem。
- 标题为空时回退为 `微信视频号__000012`；旧记录不批量回填标题、不强制改名旧 `wxv_*` 文件。
- SQLite 新增 `video_title`, `cover_url`, `thumbnail_filename`, `bundle_filename`，启动时自动迁移旧库。
- 缩略图优先使用 `coverUrl`；失败且 MP4 存在时用 ffmpeg 抽首帧；缩略图失败不能让主任务失败。
- Docker 镜像正式安装 `ffmpeg`，同时提供 `ffprobe`。
- “下载全部”使用单个 ZIP endpoint，避免浏览器拦截多个自动下载。
- 删除历史只删除数据库声明为该 job 所拥有的文件；禁止客户端提交任意文件路径，禁止按标题 glob 批量删除。
- 源链接始终保留普通 HTTPS 点击能力；“微信打开”只承诺“复制链接 + 尝试唤起 `weixin://`”，不承诺未公开 deep link 直达具体视频。
- 所有新增文件/接口路径必须继续支持直接 IP、HTTPS 域名、可信 `X-Forwarded-*` 和 `X-Forwarded-Prefix`。
- Cookie/session、`.env`、SQLite、下载文件、SSH key、VPS/WebUI 密码和 Browserless token 不得进入 Git。

## Review Focus

1. **标题是恶意/极端输入**：包含 `/`, `\\`, `..`, 控制字符、emoji、CJK、Windows 保留名、超长文本时，生成的文件必须仍在 `/data/downloads` 内且不同 job 不冲突。Task 1 必须固定此行为。
2. **封面 URL 指向内网或恶意重定向**：thumbnail 下载必须拒绝 loopback/private/link-local 等地址并限制字节数；cover 失败后主任务仍完成。Task 3 必须测试。
3. **retry 中途已经产生标题化 partial files**：下一次尝试前必须只清理该 job 明确拥有/本次尝试明确创建的文件，不得误删同标题邻居。Task 2 必须测试。
4. **旧 SQLite 和旧 `wxv_*` 文件**：升级启动不能丢历史，旧下载仍可用，title/thumbnail 为空时 API/UI 正常降级。Task 1/4/5 必须测试。
5. **反代子路径 + bundle/thumbnail**：`/wechat/...` 这类 path prefix 下所有新增链接仍可点击和下载，绝对 URL 不泄露内部 host。Task 4 必须测试。

---

## Execution Preflight

Before product-code changes begin, verify the clean release clone is based on the last shipped `de19fd6` lineage, then make the canonical remote explicit: keep the old `samni728/WechatVideoDL` URL only as a read-only `baseline` remote if useful, and set `origin` to `git@github.com:topgptus/WechatVideoDL.git`. Fetch with the isolated `~/.ssh/id_ed25519_topgptus` key and confirm target `main` contains the shipped base before creating the implementation worktree. Do not modify `~/.ssh/config` or global Git config.

### Task 1: 标题文件名策略与 SQLite 兼容迁移

**Files:**
- Create: `server_docker/artifact_names.py`
- Modify: `server_docker/history_store.py`
- Modify: `server_docker/job_files.py`
- Test: `server_docker/tests/test_artifact_names.py`
- Test: `server_docker/tests/test_history_store.py`
- Test: `server_docker/tests/test_job_files.py`

**Interfaces:**
- Produces: `artifact_stem(video_title: str | None, job_id: str, max_stem_bytes: int = 180) -> str`; UTF-8 截断必须保持完整码点并保证 stem 的编码长度不超过 180 bytes，为扩展名和跨平台文件系统限制留出余量。
- Produces: `artifact_filename(video_title: str | None, job_id: str, ext: str) -> str` for `txt|md|mp4|jpg|zip`.
- Produces: `safe_owned_path(download_dir: Path, filename: str | None, allowed_exts: set[str] | None = None) -> Path | None` that validates basename + containment + extension rather than the old `wxv_*` regex.
- `HistoryStore` gains persistent fields `video_title`, `cover_url`, `thumbnail_filename`, `bundle_filename` and idempotent old-schema migration.

- [ ] **Step 1: Write failing title-policy tests** for CJK/emoji preservation, `/\\:*?\"<>|` replacement, `..` and control-character removal, whitespace collapse, trailing-dot stripping, empty-title fallback, UTF-8 byte-safe long-title truncation (including long CJK/emoji titles), Windows reserved basename handling, and two equal titles with different job IDs yielding different stems.
- [ ] **Step 2: Run** `python -m unittest server_docker.tests.test_artifact_names -v`; expected FAIL because `artifact_names.py` does not exist.
- [ ] **Step 3: Implement `artifact_names.py`** with deterministic safe-title normalization and the exact `title__000012` suffix derived from validated `wxv_000012`.
- [ ] **Step 4: Run artifact-name tests**; expected PASS.
- [ ] **Step 5: Write failing migration tests** by creating a legacy `jobs` table without the four new columns, inserting an old completed row, reopening `HistoryStore`, and asserting the row survives while new columns exist as `NULL`.
- [ ] **Step 6: Extend `history_store.py`** with the four columns in fresh schema, `PRAGMA table_info` + `ALTER TABLE ... ADD COLUMN` migration, and allowed update fields.
- [ ] **Step 7: Run** `python -m unittest server_docker.tests.test_history_store -v`; expected PASS including legacy migration.
- [ ] **Step 8: Update job-file tests** so new title-aware jobs write `视频标题__000012.md|txt`, Markdown H1 is the video title, internal Task ID remains in the document, and legacy jobs without title still produce a safe fallback.
- [ ] **Step 9: Refactor `job_files.py`** to use `artifact_filename()` while preserving exact TXT/MD format semantics apart from the title header/additional title field.
- [ ] **Step 10: Expand `safe_owned_path()` tests** to accept valid Unicode titled files and reject traversal, nested paths, unsupported extensions, absolute paths, and filenames outside the DB-owned allowlist call sites.
- [ ] **Step 11: Run** `python -m unittest server_docker.tests.test_job_files -v`; expected PASS.
- [ ] **Step 12: Commit** `feat: add title-safe artifact naming and history migration`.

### Task 2: 在 parse/retry 生命周期中持久化标题并统一文本与视频文件名

**Files:**
- Modify: `server_docker/app.py`
- Modify: `server_docker/job_runner.py`
- Modify: `server_docker/job_files.py`
- Test: `server_docker/tests/test_job_runner.py`
- Test: `server_docker/tests/test_parse_api.py`

**Interfaces:**
- Consumes: `artifact_stem()`, `artifact_filename()`, migrated `HistoryStore`.
- `download_video(output_stem: str, direct_url: str, referer: str) -> Path` writes `<output_stem>.<actual-ext>` under `DOWNLOAD_DIR`.
- `run_parse_job(...)` persists `video_title`, `cover_url`, `preview_url`, `source_direct_url` immediately after analyzer success and returns the same history row shape as before plus new metadata.
- Retry cleanup receives exact provisional filenames/paths from the current attempt and DB-owned filenames from prior attempts; it never glob-deletes by title.

- [ ] **Step 1: Write failing runner tests** where analyzer returns `card.title`/`card.coverUrl`; assert those fields are persisted before file creation and text/video filenames share `视频标题__000101`.
- [ ] **Step 2: Add retry-isolation tests** where attempt 1 and attempt 2 return different titles and a neighboring job has the same title; assert only the current job’s provisional artifacts are cleaned.
- [ ] **Step 3: Run** `python -m unittest server_docker.tests.test_job_runner -v`; expected FAIL on missing title-aware lifecycle behavior.
- [ ] **Step 4: Refactor `run_parse_job()`** to read `result["card"]`, persist `video_title`/`cover_url`, compute one attempt stem, write title-aware analysis file, and pass that stem to downloader.
- [ ] **Step 5: Refactor `download_video()`** to accept the output stem instead of job ID while preserving yt-dlp timeout, referer, verification, and actual returned extension handling.
- [ ] **Step 6: Replace retry cleanup** with exact path cleanup based on tracked provisional/DB-owned filenames; continue clearing file metadata on final failure.
- [ ] **Step 7: Run job-runner tests**; expected PASS.
- [ ] **Step 8: Update parse API tests** so the response exposes `title`, retains `id`, keeps existing text/video fields, and validates title-aware filenames plus fallback title when Browserless returns empty title.
- [ ] **Step 9: Run** `python -m unittest server_docker.tests.test_parse_api -v`; expected PASS.
- [ ] **Step 10: Commit** `feat: persist video titles and use titled download names`.

### Task 3: 缩略图获取、首帧 fallback 与 ffmpeg 镜像依赖

**Files:**
- Create: `server_docker/thumbnail_service.py`
- Modify: `server_docker/job_runner.py`
- Modify: `server_docker/Dockerfile`
- Test: `server_docker/tests/test_thumbnail_service.py`
- Test: `server_docker/tests/test_job_runner.py`

**Interfaces:**
- Produces: `validate_public_http_url(url: str) -> str` rejecting non-http(s), credentials, localhost/private/link-local/multicast/reserved targets and unsafe redirect destinations.
- Produces: `create_thumbnail(download_dir: Path, target_filename: str, cover_url: str | None, video_path: Path | None, *, http_get=..., ffmpeg_bin="ffmpeg", max_bytes=8_000_000) -> Path | None`.
- Cover fetch uses bounded streaming and no unchecked redirect chain; downloaded cover bytes are transcoded to final JPEG with ffmpeg so the `.jpg` extension matches actual content.
- If cover path fails, the same function attempts one frame from MP4; any thumbnail failure returns `None` and never raises into the main completed-job path.

- [ ] **Step 1: Write failing URL-safety tests** for public HTTPS success and loopback, RFC1918, link-local, credentials, `file://`, malformed URL, and redirect-to-private rejection.
- [ ] **Step 2: Write failing thumbnail tests** for successful cover-to-JPEG transcode, response-size cap, invalid content/ffmpeg failure, and MP4-first-frame fallback.
- [ ] **Step 3: Run** `python -m unittest server_docker.tests.test_thumbnail_service -v`; expected FAIL because module does not exist.
- [ ] **Step 4: Implement `thumbnail_service.py`** with DNS/IP validation per hop, bounded response streaming to a temporary file, ffmpeg transcode/extract, temporary-file cleanup, and atomic replace of the final JPG.
- [ ] **Step 5: Run thumbnail-service tests**; expected PASS.
- [ ] **Step 6: Add runner tests** asserting thumbnail failure leaves the job `completed`, successful thumbnail persists `thumbnail_filename`, and the thumbnail stem matches text/video.
- [ ] **Step 7: Integrate thumbnail generation in `run_parse_job()`** after text/video output; call it even without MP4 when `cover_url` exists, and use MP4 fallback when available.
- [ ] **Step 8: Install `ffmpeg` in `server_docker/Dockerfile`** via a minimal apt layer and clean apt lists; keep the Python image and app command unchanged.
- [ ] **Step 9: Run** `python -m unittest server_docker.tests.test_job_runner server_docker.tests.test_thumbnail_service -v`; expected PASS.
- [ ] **Step 10: Build the Docker image locally** and verify `ffmpeg -version` and `ffprobe -version` both exit 0.
- [ ] **Step 11: Commit** `feat: add video thumbnails with cover and first-frame fallback`.

### Task 4: ZIP bundle、API 序列化、安全删除和反代路径

**Files:**
- Create: `server_docker/bundle_service.py`
- Modify: `server_docker/app.py`
- Modify: `server_docker/history_store.py`
- Test: `server_docker/tests/test_bundle_service.py`
- Test: `server_docker/tests/test_history_api.py`
- Test: `server_docker/tests/test_proxy_urls.py`

**Interfaces:**
- Produces: `ensure_bundle(download_dir: Path, job: dict[str, Any]) -> Path` using only DB-declared `text_filename`, `video_filename`, `thumbnail_filename`; archive member names are normalized to the current title stem even when legacy on-disk files are still named `wxv_*`; writes `<title-stem>.zip.tmp` then atomically replaces final ZIP and regenerates a cached ZIP whenever any component is newer or its expected member set changed.
- Produces endpoint: `GET /api/history/<job_id>/bundle` with existing session/Basic authentication.
- `serialize_job()` adds `title`, `source_url`, `thumbnail`, `bundle` while retaining all existing keys.
- Deletion checks exactly `text_filename`, `video_filename`, `thumbnail_filename`, `bundle_filename` through `safe_owned_path()` and tolerates already-missing files.

- [ ] **Step 1: Write failing bundle unit tests** asserting archive basename, title-normalized member names for both new and legacy on-disk files, optional MP4/JPG omission, no path nesting, cache reuse, cache invalidation when a component is newer/member set changes, and temp ZIP cleanup on failure.
- [ ] **Step 2: Implement `bundle_service.py`** with Python `zipfile`, DB-owned file validation, deterministic member names, temp output and `os.replace()`.
- [ ] **Step 3: Run** `python -m unittest server_docker.tests.test_bundle_service -v`; expected PASS.
- [ ] **Step 4: Write failing history API tests** for bundle auth, 404, completed job success, title-aware `Content-Disposition`, bundle filename persistence, old job without title, and missing component behavior.
- [ ] **Step 5: Add `GET /api/history/<job_id>/bundle`**; generate/reuse the bundle, persist `bundle_filename`, and return attachment response without changing job completion state on bundle failure.
- [ ] **Step 6: Extend serialization tests** for `title`, `source_url`, thumbnail links and bundle links while existing `yuanbao.preview_url`, `text`, `video` remain backward compatible.
- [ ] **Step 7: Extend deletion tests** to cover MD/TXT + MP4 + JPG + ZIP, missing optional files, a malicious DB filename, and a same-title neighboring job.
- [ ] **Step 8: Update delete implementation** to delete only DB-declared owned files and clear no unrelated file.
- [ ] **Step 9: Add proxy tests** for thumbnail and bundle URLs under direct host, trusted host/proto, `X-Forwarded-Prefix=/wechat`, and explicit `PUBLIC_BASE_URL`.
- [ ] **Step 10: Run** `python -m unittest server_docker.tests.test_history_api server_docker.tests.test_proxy_urls server_docker.tests.test_bundle_service -v`; expected PASS.
- [ ] **Step 11: Commit** `feat: add bundled downloads and titled history metadata`.

### Task 5: WebUI 标题卡片、缩略图、源链接、微信打开与下载全部

**Files:**
- Modify: `server_docker/static/app.js`
- Modify: `server_docker/static/app.css`
- Modify: `server_docker/templates/index.html`
- Modify: `server_docker/templates/history.html`
- Test: `server_docker/tests/test_frontend_contract.py`
- Test: `server_docker/tests/test_ui_routes.py`

**Interfaces:**
- Workspace result title: `job.title || job.id`; ID remains secondary metadata.
- History search matches lowercased `title + id + input_url/source_url + prompt`.
- `openSourceLink(url)` renders/uses a real HTTPS anchor with `target="_blank" rel="noopener noreferrer"`.
- `openInWeChat(url)` tries `navigator.clipboard.writeText(url)` then activates `weixin://`; clipboard failure falls back to a selectable/copyable prompt while normal HTTPS link remains available.
- Bundle action uses `job.bundle.download_path`; text/video keep their existing individual download buttons.

- [ ] **Step 1: Write failing frontend contract tests** for title rendering contract, thumbnail image, bundle button, clickable HTTPS source link attributes, WeChat action hook, title-inclusive search, and legacy title fallback.
- [ ] **Step 2: Run** `python -m unittest server_docker.tests.test_frontend_contract server_docker.tests.test_ui_routes -v`; expected FAIL.
- [ ] **Step 3: Refactor workspace result rendering** so title and optional thumbnail are primary, while `wxv_*`, attempts and format become secondary metadata; add `下载全部` before individual downloads.
- [ ] **Step 4: Refactor history cards** to a responsive thumbnail + content + actions layout; title is the primary heading, job ID/date/status are metadata, source URL is a real link, and prompt remains a compact summary.
- [ ] **Step 5: Implement source/WeChat actions** with safe anchor creation, clipboard attempt, `weixin://` activation, and non-destructive fallback messaging; do not hardcode a private video deep link.
- [ ] **Step 6: Extend history filtering** to match title in addition to the existing ID/link/Prompt fields.
- [ ] **Step 7: Update CSS** for 16:9 thumbnails, two-line title clamp, desktop three-part card and mobile stacking without breaking Light/Dark/System themes.
- [ ] **Step 8: Run frontend/UI tests**; expected PASS.
- [ ] **Step 9: Perform a local browser smoke check** in dark/light modes using seeded title/thumbnail/legacy history rows; verify no raw HTML injection and no layout overflow at desktop/mobile widths.
- [ ] **Step 10: Commit** `feat: show titled thumbnail history and WeChat actions`.

### Task 6: 全量回归、VPS 实机升级与真实视频验证

**Files:**
- Modify as required by discovered regression: `server_docker/tests/test_*.py`, `server_docker/tests/test_*.sh`, deployment files only when a verified defect requires it.
- Update screenshots after verified deploy: `docs/images/webui-dark.png`, `docs/images/webui-light.png`, `docs/images/webui-history.png`, `docs/images/webui-home.png`, `docs/images/webui-login.png` only if visually changed/relevant.

**Interfaces:**
- Existing deployment remains `./scripts/deploy.sh --dry-run` then `./scripts/deploy.sh`.
- Production VPS project remains `/root/wx-video-download` and must preserve `.env`, Cookie/session, history DB and unrelated Docker containers.

- [ ] **Step 1: Run the full Python suite** with `python -m unittest discover -s server_docker/tests -p 'test_*.py' -v`; expected zero failures/errors.
- [ ] **Step 2: Run all shell/deployment tests** with `for t in server_docker/tests/test_*.sh; do bash "$t"; done`; expected all PASS/exit 0.
- [ ] **Step 3: Run static/config checks**: Python compile, `bash -n`, Docker Compose config, README image-ref checker if already present, and `git diff --check`.
- [ ] **Step 4: Build the Docker image** and verify ffmpeg/ffprobe plus app import; no new runtime secret enters image layers.
- [ ] **Step 5: Deploy to the existing VPS** using dry-run first; back up current code only, preserve `/data`, `.env`, Cookie/session, and keep Browserless/unrelated containers intact.
- [ ] **Step 6: Run a real WeChat Channels parse** with MD + MP4 enabled and verify: real `video_title`, title-aware MD/MP4 names, thumbnail, completed history row, media info, source link, and 1/3 success when no retry is needed.
- [ ] **Step 7: Verify `下载全部`** returns a ZIP named with the same title stem containing the expected MD/MP4/JPG files; repeat request reuses valid cache.
- [ ] **Step 8: Verify thumbnail fallback** with a controlled bad cover URL while retaining a valid MP4; assert first-frame JPG appears and task remains completed.
- [ ] **Step 9: Verify reverse proxy behavior** for title files, thumbnail and bundle with trusted host/proto/prefix; confirm public URLs and relative paths are correct.
- [ ] **Step 10: Verify deletion** removes only the selected job’s MD/MP4/JPG/ZIP and DB row while a same-title neighbor remains untouched.
- [ ] **Step 11: Capture final screenshots** from the verified newest UI showing a titled result and titled thumbnail history; ensure no credentials, cookies, tokens or private session data appear.
- [ ] **Step 12: Commit** `test: verify titled media workflow on VPS` only if tracked verification artifacts/screenshots changed.

### Task 7: README、发布清理与 TopGPT 主仓库发布

**Files:**
- Modify: `README.md`
- Modify: `server_docker/README.md`
- Modify if required: `.gitignore`, `server_docker/.dockerignore`
- Use: `docs/images/*.png`

**Interfaces:**
- Documentation must describe `视频标题__000012` naming, thumbnail fallback, bundle ZIP, ffmpeg dependency, source/WeChat link behavior, DB migration and old-history compatibility exactly as shipped.
- Canonical release remote is `git@github.com:topgptus/WechatVideoDL.git`, using the already verified `~/.ssh/id_ed25519_topgptus` deploy key via isolated `GIT_SSH_COMMAND`; do not replace global SSH settings.

- [ ] **Step 1: Update root README** with final screenshots and user-facing workflow: titled workspace/history, thumbnails, `下载全部`, source link, WeChat activation behavior, filename examples and compatibility notes; all canonical clone/repository links must point to `https://github.com/topgptus/WechatVideoDL`.
- [ ] **Step 2: Update Docker README** with ffmpeg installation consequence, SQLite automatic migration fields, bundle endpoint, title-safe storage model, thumbnail failure semantics and data backup notes.
- [ ] **Step 3: Verify docs programmatically**: every referenced image/file exists, API examples match actual routes/fields, and no stale claim says `wxv_000012` is the new user-facing filename.
- [ ] **Step 4: Run final full verification again**: Python suite, shell suite, syntax/config, Docker image checks, VPS health, one authenticated history/bundle fetch, and `git diff --check`.
- [ ] **Step 5: Run secret/path scan** ensuring no Cookie/session, `.env`, DB/downloads, password/token, SSH private/public key material or host-specific secret was added.
- [ ] **Step 6: Review final branch history and status**; ensure the tree is clean and only intended release files are tracked.
- [ ] **Step 7: Commit release documentation** with `docs: document titled history thumbnails and bundle downloads`.
- [ ] **Step 8: Configure/verify the clean release repo’s canonical remote** for `topgptus/WechatVideoDL` without altering global SSH config; verify remote `main` before push.
- [ ] **Step 9: Push `main` to `topgptus/WechatVideoDL`** using `~/.ssh/id_ed25519_topgptus` with `IdentitiesOnly=yes`.
- [ ] **Step 10: Verify release SHA** with `git ls-remote` using the same isolated deploy key and confirm local HEAD equals `refs/heads/main` exactly.
- [ ] **Step 11: Do not push `samni728/WechatVideoDL`** unless the user explicitly requests a mirror after this release.
