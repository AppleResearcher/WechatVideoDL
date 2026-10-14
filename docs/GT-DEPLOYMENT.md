# GT Edition · Mac mini 部署和开发说明

## 项目位置与 Git
- Mac mini 源码：`~/Docker/WechatVideoDL`
- `origin`: `https://github.com/AppleResearcher/WechatVideoDL.git`
- `upstream`: `https://github.com/topgptus/WechatVideoDL.git`
- Compose 项目：`wx-video-download`
- 数据：`server_docker/data/`（不纳入 Git）
- 密钥配置：`server_docker/.env`，权限 `0600`（不纳入 Git）

## 网络设计
- Mac mini 本机：`http://127.0.0.1:18770`
- Docker App 内部：`8080`
- App 同时位于私有默认 Docker 网络与 NPM 的 `npm_default` 外部网络。
- NPM Proxy Host（**待用户选择域名后配置**）：Scheme=`http`；Forward Hostname=`wechatvideodl`；Forward Port=`8080`。
- 仅绑定宿主机 `127.0.0.1` 不妨碍 NPM 从 Docker 内部互联；不得误用 NPM 容器内的 `127.0.0.1:18770`。
- NPM 可继续通过原有 HTTPS :8443 和 Cloudflare；本次部署没有创建反代、DNS 或公共访问规则。

## 运维
在 `server_docker/` 下执行：
```bash
./scripts/deploy.sh --dry-run
./scripts/deploy.sh
docker compose -p wx-video-download -f docker-compose.yml -f docker-compose.browserless.yml ps
curl -I http://127.0.0.1:18770/login
```
本地查看账户密码（请勿发到聊天或 Git）：
```bash
grep '^WEBUI_PASSWORD=' .env
```
元宝 Cookie 和 Session 首次需用户本人授权并导入。未导入时，WebUI 登录页可访问，但解析和 `/health` 可能报告不可用，这是预期状态。

## 二次开发
新特性使用 `feature/<description>` 分支。通过本地测试和 PR 合并到个人 Fork 的 `main`，用 `vX.Y.Z-gt.N` 打 Tag。上游更新先对比改动再合并，不覆盖 GT 的 localhost 监听和 npm_default 网络设置。
