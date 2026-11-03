# 用这个仓库让你自己的 Grok Bot 搭一套类似系统

把下面这段话连同本仓库地址发给你自己的 Grok Bot（Steward）。按需改括号里的内容。

---

> 请参照这个仓库搭一套多 bot 协作和进度看板：<本仓库 URL>。先通读 `README.zh-CN.md`、`docs/multi-bot-operations.zh-CN.md`、`docs/cloudflare.zh-CN.md`、`docs/agent-reporting.zh-CN.md`，然后按下面的顺序做，每一步做完告诉我结果，涉及花钱、对外发布、发消息、删除的步骤先问我：
>
> 1. **建运维 bot**：新建一个「运维」bot，职责照 `docs/multi-bot-operations.zh-CN.md` 第 2 节写进它的设定（维护看板和仓库、每 30 分钟刷新额度、巡检、45 分钟无动静或过 ETA 就优先唤醒、两次没回应告诉我、转发提醒、每日备份、接入新 bot、监控机器）。
> 2. **装命令行**：把 `cli/` 里的 `st`、`stwatch`、`stnudge`、`stcount` 放到共享电脑的固定目录，设好 `ST_ROOT`、`ST_LANG=zh`，跑一遍 `make test`。
> 3. **部署看板**：按 `docs/cloudflare.zh-CN.md` 第 1 节在我的 Cloudflare 账号（只用免费额度）上建 D1 和 Pages，用 Access 设成只有我能看；令牌只存哈希，原文放在权限 600 的文件里，不要打印给我看。
> 4. **建其他 bot**（我需要的角色：<例如 架构师、开发、科研助理、邮箱助理、审核官>），每个 bot 的设定里写明：用 `st` 汇报、长任务用 `stwatch`、方案和 PR 交审核官审、邮件只出草稿。
> 5. **建例行任务**：额度刷新（每 30 分钟）、提醒转发（每 30 分钟）、看板巡检、每日备份，每个都在看板登记一张 routine 卡片。
> 6. **可选：机器监控**：在我指定的机器上装 `server/grokbot-report.sh` 和 cron，每台机器一个只写令牌。需要从共享电脑 SSH 到不在同一网络的机器时，按第 3 节用 Cloudflare Tunnel + Access 服务令牌。
>
> 全程不要把我的个人信息、密钥、域名写进任何公开的地方；如果要建自己的仓库，先建私有仓库，脱敏检查后再问我要不要公开。

---

## 搭完后自检

- `st list` 能看到各 bot 的卡片，页面上能看到同样的内容。
- 未登录访问看板返回 403；`/api/push` 不带令牌返回 401。
- 停一个任务 45 分钟，运维 bot 会唤醒对应 bot。
- 机器监控：每 5 分钟有一个新点，关掉 cron 15 分钟后卡片变黄。
