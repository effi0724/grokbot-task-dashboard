# Cloudflare 用法（全部免费额度）

用到的产品：Pages + Functions（托管看板）、D1（任务快照和服务器指标）、Zero Trust / Access（登录保护、服务令牌）、Tunnel（让共享电脑 SSH 到不在同一 VPN 的机器）。

占位符：`YOUR_DOMAIN`（如 `bot.example.com`）、`YOUR_PROJECT`（Pages 项目名）、`YOUR_DB`（D1 名）、`server-1`/`server-2`（主机 ID）。

## 1. 看板：Pages + Functions + D1

```bash
npm i -g wrangler && wrangler login
wrangler d1 create YOUR_DB                     # 把输出的 database_id 填进 site/wrangler.toml
wrangler d1 execute YOUR_DB --remote --file site/schema.sql
wrangler pages project create YOUR_PROJECT
# st 推送令牌：只存哈希
st token-sha256 | wrangler pages secret put PUSH_TOKEN_SHA256 --project-name YOUR_PROJECT
cd site && ./deploy.sh
```

完整步骤见 [deploy.zh-CN.md](deploy.zh-CN.md)。

## 2. 服务器指标：推送模型

看板**不主动拉取**服务器，而是每台机器自己推：

1. 机器上装 `server/grokbot-report.sh` 到 `~/.local/bin/`，crontab：
   ```
   */5 * * * * $HOME/.local/bin/grokbot-report.sh >/dev/null 2>&1
   ```
2. 脚本采集 CPU、GPU、内存、磁盘、运行中的任务，HTTPS POST 到 `https://YOUR_DOMAIN/api/server-push`。
3. 每台机器一个**只写令牌**，放在 `~/.config/grokbot-report/token`（权限 600），只能写指标、不能读任何数据，与 `st` 的推送令牌分开。
4. Cloudflare 只存令牌的 **SHA-256**：
   ```bash
   # 在本机生成令牌，不要打印到共享日志
   umask 077; openssl rand -hex 32 > ~/.config/grokbot-report/token
   tr -d '\r\n' < ~/.config/grokbot-report/token | sha256sum | cut -d' ' -f1   # 去掉换行再算哈希
   wrangler pages secret put SERVER_TOKEN_SHA256 --project-name YOUR_PROJECT          # 第一台机器
   wrangler pages secret put SERVER_TOKENS_JSON  --project-name YOUR_PROJECT          # 其余：{"<sha256>":"server-2", ...}
   ```
   主机 ID 以令牌对应的名字为准，上报里的 host 字段只作参考。
5. `site/functions/api/server-push.js` 校验令牌（常量时间比较），把快照写进 D1 表 `server_metrics`，**保留 7 天**；最新快照和 24 小时曲线同时写进 `kv` 表的 `srv:<host>` 行，读取时只读一行，省 D1 读量。
6. `_middleware.js` 对 `/api/push` 和 `/api/server-push` 跳过 Access，由各自的令牌校验；其他路径都要 Access JWT。
7. 试跑不上报：`GROKBOT_REPORT_DRY=1 ~/.local/bin/grokbot-report.sh`。

共享电脑（agent 所在的 box）也可以同样上报，用 `stwatch` 托管一个每 5 分钟跑一次的 watcher 即可。

## 3. Zero Trust：Access + Tunnel + 服务令牌

**场景**：共享电脑（box）不在你的私有 VPN 里，又需要 SSH 到某台服务器。做法是在服务器上跑 `cloudflared` 隧道，再用 Access 限定只有指定的服务令牌和你本人能连。

服务器上：
```bash
cloudflared tunnel login
cloudflared tunnel create server-1
cloudflared tunnel route dns server-1 ssh-server-1.YOUR_ZONE
# ~/.cloudflared/config.yml:
#   tunnel: <TUNNEL_ID>
#   credentials-file: /etc/cloudflared/<TUNNEL_ID>.json
#   ingress:
#     - hostname: ssh-server-1.YOUR_ZONE
#       service: ssh://localhost:22
#     - service: http_status:404
sudo cloudflared service install    # 以系统服务运行，凭据文件 600
```

Zero Trust 控制台：
1. Access → Applications → 新建 Self-hosted 应用，域名 `ssh-server-1.YOUR_ZONE`。
2. Access → Service Auth → 新建服务令牌（如 `box-agent`），设有效期，记下 Client ID / Secret（只存到 box 的私有配置，权限 600）。
3. 策略：`Service Auth` 包含该服务令牌；另加一条 `Allow`，只放你自己的邮箱。
4. 看板本身（`YOUR_DOMAIN`、`*.pages.dev`、预览地址）也挂同一条「仅本人」策略；`/api/push`、`/api/server-push` 单独建 Bypass 应用。

box 上 `~/.ssh/config`：
```
Host server-1
  HostName ssh-server-1.YOUR_ZONE
  User YOUR_USER
  IdentityFile ~/.ssh/server-1
  ProxyCommand cloudflared access ssh --hostname %h --service-token-id ${CF_ACCESS_CLIENT_ID} --service-token-secret ${CF_ACCESS_CLIENT_SECRET}
```
`CF_ACCESS_CLIENT_ID` / `CF_ACCESS_CLIENT_SECRET` 从权限 600 的文件里读进环境变量，不要写进仓库或日志。服务令牌到期前由运维 bot 提醒续期。

## 4. 安全要点

- Cloudflare 上只存哈希，不存令牌原文。
- 换令牌：生成新随机串 → 写机器上的 token 文件 → 更新对应 secret → 重新部署。
- 一台机器只放它自己的上报令牌，不放其他任何凭据。
- 免费额度：Pages、Functions、D1、Zero Trust（50 人以内）都够个人使用；超过就降低上报频率，不要升级付费。
