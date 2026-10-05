# WechatVideoDL 标题化历史、缩略图与打包下载设计

日期：2026-10-04
状态：用户已确认，进入实施计划（正式主仓库：topgptus/WechatVideoDL）

## 1. 背景

当前 WechatVideoDL 已经具备稳定的视频号解析、腾讯元宝内容理解、MP4 下载、TXT/Markdown 输出、自动重试、历史记录和反向代理支持。现有 Browserless 解析结果实际上已经返回视频卡片的 `title` 与 `coverUrl`，但后端没有把这些元数据完整写入历史库，也没有用于文件命名和历史卡片展示。

当前用户体验仍以 `wxv_000012` 这类内部任务 ID 为主要识别信息。对于长期保存、知识库整理和再次查找视频来说，用户更需要“视频标题 + 缩略图”作为主要视觉识别；同时，希望文本分析与视频文件使用相同的人类可读标题，并能一次性下载完整附件包。

## 2. 用户目标

本次版本更新需要实现：

1. 工作台结果与历史记录以抓取到的真实视频标题为主，不再把 `wxv_000012` 作为主要名称展示。
2. Markdown/TXT、MP4、缩略图和 ZIP 的用户可见文件名统一使用“安全化标题 + 内部序号”。
3. 历史记录显示视频封面缩略图；优先使用微信视频号卡片的封面 URL，获取不到时从已下载 MP4 抽取首帧。
4. 提供“一键下载全部”，将分析文本、视频和可用缩略图放入一个 ZIP 包。
5. 原微信视频号分享链接在历史记录和结果区可直接点击。
6. 在 macOS/桌面浏览器场景提供“微信打开”入口：复制链接并尝试激活本机微信；无法稳定深链到具体视频时明确降级，不伪装成可保证直达。
7. 升级必须兼容既有 `history.db`、既有 `wxv_*` 文件和当前 API/反向代理行为。

## 3. 核心设计原则

### 3.1 保留内部稳定 ID

内部数据库主键、任务生命周期、重试关联和安全删除边界继续使用：

```text
wxv_000012
```

用户界面和下载文件不再以该 ID 为主，而是使用标题化名称。

这样可以避免标题重名、标题变化、特殊字符、Unicode、超长标题和旧数据库迁移对核心任务模型造成破坏。

### 3.2 用户可见文件命名

采用用户确认的 A 方案：

```text
视频标题__000012.mp4
视频标题__000012.md
视频标题__000012.txt
视频标题__000012.jpg
视频标题__000012.zip
```

规则：

- `000012` 来源于内部 `wxv_000012`。
- 标题先经过文件名安全化处理。
- 非法路径字符替换为安全字符，移除控制字符和危险路径片段。
- 连续空白压缩，去掉首尾空格与点号。
- 对标题做最大长度限制，为扩展名和序号保留空间。
- 标题为空时降级为 `微信视频号__000012`。
- 同一任务的 MD/TXT、MP4、JPG 和 ZIP 必须使用完全一致的 stem。
- 内部仍保留原始 `video_title`，文件名安全化结果单独生成，不覆盖原始标题。

## 4. 元数据采集与持久化

### 4.1 已有数据来源

`browserless_function.js` 当前已经返回：

```text
title
coverUrl
previewUrl
directUrl
yuanbaoContent
```

本次不改变标题和封面主要抓取来源，只把已有结果真正接入数据库与 UI。

### 4.2 SQLite 新字段

`jobs` 表新增：

```text
video_title TEXT
cover_url TEXT
thumbnail_filename TEXT
bundle_filename TEXT
```

数据库初始化采用幂等迁移：启动时检查列是否存在，缺失时执行 `ALTER TABLE ... ADD COLUMN ...`。不得要求用户删除或重建现有 `history.db`。

旧记录这些字段为空时：

- 标题显示回退到任务 ID；
- 不显示缩略图或显示统一占位图；
- 原有 MD/TXT/MP4 下载继续可用；
- 不自动猜测或批量改名旧文件。

## 5. 文件生成流程

### 5.1 新任务数据流

1. 创建内部 `job_id`，例如 `wxv_000012`。
2. Browserless 返回视频标题、封面 URL、preview URL、direct URL 和元宝内容。
3. 后端立即把 `video_title`、`cover_url`、`preview_url`、`source_direct_url` 写入历史记录。
4. 根据 `video_title + job_id` 生成安全的公共文件 stem。
5. 写入 Markdown/TXT，文件名使用标题 stem。
6. 如请求 MP4，则 yt-dlp 下载到标题 stem 对应的 MP4 文件。
7. 生成/保存缩略图：封面优先，首帧 fallback。
8. 任务完成后 API 返回 title、thumbnail、text、video 和 bundle 能力信息。

### 5.2 文本文件内容

Markdown/TXT 内仍保留内部任务 ID，便于技术追踪，同时增加视频标题字段。

Markdown 顶部示例：

```md
# 视频标题

- Task ID: `wxv_000012`
- Source: https://weixin.qq.com/sph/...
- Created: ...
- Preset: ...
```

这样用户下载后首先看到视频标题，而不是通用的 `WechatVideoDL Analysis`。

## 6. 缩略图设计

### 6.1 优先级

缩略图生成顺序：

1. 优先下载 Browserless 返回的 `coverUrl`。
2. 若 cover URL 缺失、过期或下载失败，且 MP4 已存在，则使用 ffmpeg 从视频开头抽取一帧。
3. 两者都失败时，任务本身仍应成功；UI 使用本地占位图，不将缩略图失败升级为主任务失败。

### 6.2 封面下载安全

封面请求需要：

- 有连接和读取超时；
- 限制最大响应字节数；
- 只接受图片 Content-Type 或可验证的图像数据；
- 不跟随到本地/私网地址，避免 SSRF；
- 文件只能写入项目下载目录；
- 最终文件统一保存为 `.jpg` 或明确支持的图片扩展名。

### 6.3 ffmpeg

Docker 应用镜像加入 `ffmpeg`，同时获得 `ffprobe`。

收益：

- 稳定抽取首帧作为缩略图；
- `media_info()` 不再经常返回 `null`；
- 为未来视频处理能力保留基础工具。

代价是镜像体积增加，但本项目本身以视频下载为核心，该依赖合理。

## 7. ZIP 一键下载

### 7.1 原因

不采用前端连续触发两个浏览器下载，因为 Safari/Chrome 可能拦截“多个自动下载”，体验不稳定。

### 7.2 行为

历史记录和任务结果增加：

```text
下载全部
```

服务端提供按任务打包的 ZIP 下载。ZIP 名称：

```text
视频标题__000012.zip
```

ZIP 内容根据实际存在文件包含：

```text
视频标题__000012.md   或 .txt
视频标题__000012.mp4  （如果请求并成功下载）
视频标题__000012.jpg  （如果缩略图存在）
```

### 7.3 ZIP 生命周期

推荐采用“按需即时生成 + 可缓存”的方式：

- 首次请求 bundle 时创建 ZIP；
- 写入完成后原子替换目标文件，避免用户下载半成品；
- 后续重复下载可复用该 ZIP；
- 任一组成文件变化时应废弃旧 ZIP；
- 删除历史时同步删除 ZIP。

## 8. 安全文件所有权模型

当前 `safe_owned_path()` 只接受：

```text
wxv_000012.md
wxv_000012.mp4
```

标题化后不能简单放宽为“任意文件名”。需要改成基于数据库记录验证所有权：

- API 删除只读取该 job 在数据库中登记的 `text_filename`、`video_filename`、`thumbnail_filename`、`bundle_filename`；
- 每个候选文件仍必须经过 `Path(name).name == name`、下载根目录 containment、扩展名白名单等校验；
- 不允许客户端提交任意服务器路径；
- job ID 校验仍保持 `wxv_\d{6}`。

这样既能支持标题化文件名，又保持原来的路径穿越防护。

## 9. API 结构

`serialize_job()` 增加：

```json
{
  "id": "wxv_000012",
  "title": "视频标题",
  "source_url": "https://weixin.qq.com/sph/...",
  "thumbnail": {
    "filename": "视频标题__000012.jpg",
    "download_path": "/files/...",
    "download_url": "https://..."
  },
  "bundle": {
    "download_path": "/api/history/wxv_000012/bundle",
    "download_url": "https://..."
  }
}
```

现有字段继续保留，避免破坏已使用的 API 客户端。

新增 endpoint：

```text
GET /api/history/<job_id>/bundle
```

由该 endpoint 校验任务所有权和文件存在性后生成/返回 ZIP。

## 10. WebUI 设计

### 10.1 工作台结果

任务完成后的主要标题显示真实视频标题。

内部 ID 变成次要信息，例如：

```text
视频标题
wxv_000012 · 1/3 次尝试 · MD
```

操作区：

```text
下载全部   下载 MD   下载 MP4
```

有缩略图时显示封面。

### 10.2 历史记录

历史卡片结构：

```text
[16:9 缩略图]  视频标题
                2026-10-04 21:20 · wxv_000012 · 完成
                打开原链接 · 微信打开
                Prompt 摘要

                下载全部  下载 MD  MP4  详情  删除
```

历史搜索同时匹配：

- 标题；
- job ID；
- 原链接；
- Prompt。

### 10.3 缩略图布局

桌面：历史卡片采用缩略图 + 正文 + 操作区三段布局。

移动端：缩略图置顶或左上，自适应宽度，标题最多两行，不能把操作按钮挤出屏幕。

## 11. 微信链接与桌面微信

### 11.1 普通链接

原始 `https://weixin.qq.com/sph/...` 必须渲染为真实 `<a>`，允许用户直接在浏览器打开。

所有链接安全设置：

```text
target="_blank"
rel="noopener noreferrer"
```

### 11.2 “微信打开”按钮

在已确认 macOS 微信注册：

```text
weixin://
wechat://
xweixin://
```

的前提下，WebUI 的“微信打开”执行：

1. 使用 Clipboard API 复制原始视频号分享链接；
2. 尝试导航到 `weixin://` 激活桌面微信；
3. UI 提示：“链接已复制，微信已尝试打开，请在微信中粘贴访问。”

若 Clipboard API 因非 HTTPS/权限策略失败：

- 回退到浏览器选择/复制提示；
- 仍可尝试激活微信；
- 普通“打开原链接”始终保留。

### 11.3 不承诺未公开 deep link

当前没有可靠、公开、跨版本稳定的 URI 可以保证把任意 `weixin.qq.com/sph/...` 直接注入微信桌面客户端并跳转到该具体视频。

因此本版本不伪造或硬编码未经验证的私有 scheme。若后续通过真实微信版本验证出稳定 deep link，可作为独立增强加入。

## 12. 重试与失败处理

- 标题缺失：不重试整个任务，使用回退标题。
- 封面下载失败：不重试主任务；MP4 存在时尝试首帧。
- 首帧生成失败：不让主任务失败。
- ZIP 生成失败：只影响 bundle 下载 endpoint，不修改原任务 completed 状态。
- 文本写入、MP4 下载仍沿用现有自动重试策略。
- 每次 retry 前必须清理当前任务可能生成的标题化 partial artifacts。

## 13. 删除行为

删除历史记录时删除该任务数据库明确拥有的：

```text
MD/TXT
MP4
JPG thumbnail
ZIP bundle
```

缺失文件视为可容忍，不导致删除失败。

不得根据标题 glob 批量删除，以免误删同名任务或其他文件。

## 14. 兼容性

### 14.1 旧数据库

启动自动新增字段，不重建库。

### 14.2 旧文件

旧的：

```text
wxv_000007.md
wxv_000007.mp4
```

保持原样；历史下载继续使用数据库中的原文件名。

### 14.3 API

现有 `text`、`video`、`yuanbao.preview_url` 等字段继续保留；只增加新字段，不做破坏性删除或改名。

### 14.4 反向代理

所有新增 thumbnail/bundle 路径必须继续通过现有 prefix-aware 路径策略，支持：

- 直接 IP；
- HTTPS 域名；
- Nginx/Caddy/Cloudflare；
- `X-Forwarded-Prefix` 子路径部署。

## 15. 测试范围

必须新增/更新自动化测试：

1. 标题安全化：特殊字符、Unicode、空标题、超长标题。
2. 同标题不同 job ID 不冲突。
3. MD/TXT、MP4、JPG、ZIP 使用统一标题 stem。
4. Browserless title/coverUrl 写入历史数据库。
5. 旧 SQLite schema 自动迁移并保留原数据。
6. cover 下载成功时生成缩略图。
7. cover 失败时 MP4 首帧 fallback。
8. thumbnail 失败不导致 completed 任务失败。
9. ZIP 内容与文件名正确。
10. bundle endpoint 鉴权、404、文件缺失和反向代理路径。
11. 删除记录只删除数据库声明的拥有文件。
12. 防路径穿越和危险标题文件名。
13. 历史 API 返回 title/thumbnail/bundle。
14. 历史前端展示标题、缩略图、源链接、微信打开、bundle 按钮。
15. 历史搜索匹配标题。
16. 旧记录无 title/thumbnail 时正常降级。
17. 原有 retry、TXT/MD、proxy、deployment tests 全部继续通过。

## 16. 文档与发布

实现完成后：

- 更新根 README 的新版功能说明和截图；
- 更新 `server_docker/README.md`；
- 重新生成工作台与历史记录截图；
- 文档说明 ffmpeg 现在是镜像内正式依赖；
- 文档说明 ZIP 内容与标题化文件命名；
- 文档说明“微信打开”是复制链接 + 唤起客户端的兼容实现，不承诺直接深链具体视频。

验证全部通过后，正式发布到主仓库：

```text
https://github.com/topgptus/WechatVideoDL
```

`samni728/WechatVideoDL` 不再作为默认发布目标；仅在用户后续明确要求时再同步为镜像/备份。

## 17. 非目标

本版本不包含：

- 多用户账户体系；
- 视频标题手工编辑；
- 批量历史重命名；
- 自动回填旧历史标题/封面；
- 微信私有协议逆向；
- 把 title 替换为数据库主键；
- 在线编辑 ZIP 内容。
