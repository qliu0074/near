# 公网 Docker 部署与验收

当前定位：单机部署、小规模试运行。代码检查通过不等于生产验收完成；真实 Docker、TLS、邮件、模型和备份恢复需要在部署机验证。此方案没有高可用或多主机容灾。

## 你需要准备

- 一台有公网 IP 的 Linux 服务器、Docker Engine 和 Compose 插件。建议先按 4 核 / 8 GB 内存预留，实际容量需压测确认。
- 一个域名，A 记录指向服务器；若设置 AAAA，也必须能连接该服务器。防火墙仅开放公网 TCP 80/443 及受限的 SSH 管理入口。
- 可用的 Qwen HTTPS 接口、聊天和 embedding 模型权限与额度；带 STARTTLS 的 SMTP 账号及已验证的发信域名。
- 异地备份存储、备份保留时间、服务告警接收方式及模型费用上限。

不要把密钥提交到仓库或贴进聊天。服务器端填写即可。

## 首次启动（Linux Bash）

在项目根目录运行。使用独立的生产 Compose 文件，不要叠加开发 compose.yaml。

```bash
cp .env.production.example .env.production
chmod 600 .env.production
# 独立运行三次，将结果分别填写到数据库密码、ES 密码、AUTH_SECRET。
openssl rand -hex 32
# 编辑 .env.production，填写所有空项及实际域名、邮件地址。
# DOMAIN 只填写主机名，不带 https://、路径或端口。
# POSTGRES_PASSWORD 使用十六进制，避免数据库 URL 转义问题。
sudo sysctl -w vm.max_map_count=262144
# 按服务器管理方式持久化这一内核配置，重启后检查。
docker compose --env-file .env.production -f compose.production.yaml config --quiet
docker compose --env-file .env.production -f compose.production.yaml up -d --build --wait --wait-timeout 240
docker compose --env-file .env.production -f compose.production.yaml ps -a
curl --fail https://你的域名/v1/ready
```

不要把 `config` 的完整输出发给其他人，它会展开密钥。使用 `config --quiet` 验证即可。生产环境不会读取可见登录验证码，也不会使用 mock 模型。

Caddy 是唯一公网入口，自动申请和续期证书，并将 /v1/* 直接代理到 API，流式响应立即转发。参见 [自动 HTTPS](https://caddyserver.com/docs/automatic-https) 和 [反向代理](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)。不要额外发布 PostgreSQL、Redis、Elasticsearch 或 API 端口。

API 只信任专用网段中 Caddy 的固定地址 172.30.91.2。若该网段与服务器现有网络冲突，需要同时修改 Compose 网段、Caddy 固定 IP 与 API 的 forwarded-allow-ips。当前方案面向直接连接公网的 Caddy；增加 CDN/其他代理时必须重新配置可信地址和限流。

ES 已启用密码认证；HTTP 仅限本机 Docker 私网，当前使用 elastic 管理账号初始化索引。若跨主机连接或需要细粒度权限，应改用 TLS 及限制到 near-memories-v1 的 API key；应用支持 ELASTICSEARCH_API_KEY，但需将其添加到生产 Compose 环境。Redis 仅限私网，不可暴露至公网。

## 上线验收

1. 从外部网络访问域名，确认 HTTPS 有效、HTTP 跳转 HTTPS、主页正常。
2. 使用真实邮箱收取验证码，确认页面不显示 development_code；检查 Cookie 的 Secure、HttpOnly 属性。
3. 创建角色、发送真实模型消息、确认流式输出；保存记忆后检查 worker 与 Elasticsearch 检索；验证多设备同步、退出及删除。
4. 对非付费认证请求测试限流，并确认来自两个不同公网 IP 的客户端不共用代理 IP 限流桶。真实付费操作避免重复压测。
5. 验证 API 文档在生产环境不可访问，数据库/Redis/ES 端口在外部不可达。
6. 重启服务后确认账号、消息和记忆保留；完成一次独立环境备份恢复。

`/v1/health` 是存活检查，`/v1/ready` 检查数据库及预算表初始化。它不调用收费模型，也不保证邮件、ES、Redis 或后台任务正常。持续监测这些依赖、磁盘空间、备份时效和 `memory_sync_needs_attention` / `memory_sync_paused` 日志。容器 unhealthy 不会自动触发 Docker 重启；需要外部告警与处置。

## 备份、恢复与升级

以下为 Linux Bash 示例。备份包含用户私密内容，限制权限并加密传到异地；不要提交到仓库。

```bash
mkdir -p backups
chmod 700 backups
docker compose --env-file .env.production -f compose.production.yaml exec -T postgres pg_dump -U near -d near -Fc > backups/near.dump
# 验证文件结构，不等同于实际恢复演练。
docker compose --env-file .env.production -f compose.production.yaml exec -T postgres pg_restore --list < backups/near.dump > /dev/null
```

每次备份使用独立日期文件名，保留多代，避免覆盖唯一可用备份。至少每日备份数据库，并定期备份 .env.production（加密）、Caddy 数据卷和 Elasticsearch 快照。Redis 的任务队列也需按一致性恢复方案处理。ES 不是随时可丢弃的缓存：已完成的数据库 outbox 不会自动重新索引；只恢复数据库会丢失检索结果。当前没有全量重建命令，必须保存 ES 快照或在演练时验证完整卷的一致性恢复。

数据库恢复先在独立测试项目执行，目标库应为空，禁止直接覆盖线上库：

```bash
# 指定独立环境的 env 文件与项目名；该环境需提前完成数据库启动。
docker compose --env-file .env.restore -p near-restore -f compose.production.yaml exec -T postgres pg_restore -U near -d near --no-owner --exit-on-error < backups/near.dump
```

恢复测试项目不要同时运行线上同域名的 Caddy，不要让后台任务连接真实模型自动消费历史任务。完整灾备恢复需要对齐数据库、搜索快照、队列和未结算的付费操作，确认后再启用 API 和 worker。

升级前备份并记下当前代码版本/镜像。停止 api、web、worker、scheduler、caddy 后，在新版本重新执行 `up -d --build --wait`，确保迁移和索引初始化成功。不要在仍有请求或任务运行时迁移。迁移不保证可逆，回滚涉及数据库时应使用演练过的备份恢复。不要执行 `down -v`，它会删除生产数据卷。生产卷存在时，单独修改 POSTGRES_PASSWORD / ELASTIC_PASSWORD 环境变量不会自动完成密码轮换。

## 当前尚未完成的生产门槛

- 当前工作机 Docker 引擎不可用，未执行容器镜像构建和容器端到端测试。已添加 Docker CI，结果需在 GitHub 或部署机实际运行确认。
- 尚未验证真实 SMTP、模型调用、证书签发、公网网络与重启持久化。
- 尚未完成目标并发量压测、异地恢复演练、外部告警和独立安全审查。镜像应经过漏洞扫描并在上线时固定经验证的 digest；当前版本标签不是安全审计结果。
- 当前仅支持单机；画像功能仍禁用，不能作为已实现能力对外承诺。

项目已使用的令牌预算为累计 admission cap，不是实际货币限额。请另在模型提供方配置费用告警和硬上限。
