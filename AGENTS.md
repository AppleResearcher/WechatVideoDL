# GT WechatVideoDL 开发与部署约定

本仓库是 AppleResearcher/WechatVideoDL 的独立 Fork。origin 指向个人 Fork，upstream 指向 topgptus/WechatVideoDL。优先保持原作者业务流程和目录，局部修改、测试后合并到 main。

## 开发边界
- 默认工作目录：`server_docker/`；开发前查看当前 Git 状态和现有容器状态。
- Mac mini 的 WebUI 宿主机端口只能监听 `127.0.0.1:18770`；NPM 通过外部 Docker 网络 `npm_default` 的服务别名 `wechatvideodl:8080` 访问。
- 不能随意停止、重建或清理其他项目容器；不能运行 `docker system prune` 或 `docker compose down -v`。
- `.env`、`server_docker/data/`、Cookie、Session、下载文件、数据库、密钥均为敏感数据，不得纳入 Git、Issue、日志或公开报告。
- 同步上游时先 `git fetch upstream`、对比差异、审查 Compose 和权限配置；合并后检查本机监听地址及 NPM 网络配置。
- 未经明确授权，不创建/修改公网 NPM、Cloudflare DNS、不主动导出用户的腾讯元宝/微信登录态。
- 部署只使用 `server_docker/scripts/deploy.sh` 和 Compose 项目 `wx-video-download`，先 dry-run。
- 代码修改要执行相关测试；发布前以实际运行、网络与容器状态验收，不以文档承诺替代验证。

项目说明：`docs/GT-DEPLOYMENT.md`。
