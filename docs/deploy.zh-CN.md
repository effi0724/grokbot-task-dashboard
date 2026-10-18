# 部署 GrokBot 任务监控看板

下面从零开始，把看板部署到你自己的 Cloudflare 账号，并让 `st` 能把状态推上去。所有 `YOUR_*` 都要换成你自己的值，不要把换过的文件提交进仓库。

站点是一个静态页面加两个 Pages Functions：

- `GET /api/state` 从 D1 读出最新快照。浏览器访问必须带 Cloudflare Access 的 JWT。
- `POST /api/push` 接收 `st` 推上来的完整快照。这是唯一绕过 Access 的路径，函数会用 `TOKEN_SHA256` 核对 Bearer 令牌。

## 0. 准备

> `st` 支持 macOS 和 Linux。它用 `fcntl` 文件锁，不支持原生 Windows，Windows 上请用 WSL。

- 一个能创建 Pages、D1 和 Zero Trust Access 的 Cloudflare 账号。
- Node.js 20+（跑 Wrangler）和 Python 3.11+（跑 `st`）。
- 安装并登录 Wrangler：`npm install -g wrangler`，然后 `wrangler login`。

仓库不绑定任何具体账号。`site/wrangler.toml` 里的 D1 配置默认是注释掉的。

## 1. 创建 D1 数据库

```bash
npx wrangler d1 create YOUR_D1_DATABASE_NAME
npx wrangler d1 execute YOUR_D1_DATABASE_NAME --remote --file=site/schema.sql
```

表只有一张 `kv`：一行 `k = 'state'`，值是最新的 JSON 快照。`push.js` 在第一次推送成功时也会建这张表，所以漏跑 schema 还能补救，但还是先执行一遍。

## 2. 创建 Pages 项目

```bash
npx wrangler pages project create YOUR_PAGES_PROJECT --production-branch main
```

也可以在控制台创建：Workers 和 Pages → 创建 → Pages → 直接上传。项目名由你决定，仓库里没有预设。

## 3. 把 D1 绑定成 `DB`

打开 Pages 项目：**设置 → 绑定 → 添加 → D1 数据库**。

- 变量名必须是 `DB`。函数只认 `env.DB`。
- 数据库选第 1 步创建的那个。

绑定留在控制台里就好。`site/wrangler.toml` 故意不写 `pages_build_output_dir`：一旦写了，Wrangler 会把这个文件当成配置来源，部署时会覆盖控制台里配好的 D1 绑定和变量，站点随之返回 500 或 403。文件里注释掉的段落只作参考。本地开发用命令行传绑定（`--d1 DB=...`，见第 8 步）。

## 4. Cloudflare Access

页面、`/api/state` 以及其他所有路径都要经过 Access。`/api/push` 不要经过 Access，因为 `st` 没有浏览器登录态，它自己带 Bearer 令牌。

1. 打开 **Zero Trust → Access → 应用程序 → 添加应用程序 → 自托管**。
2. 名字随意。
3. 添加公共主机名：
   - `YOUR_PROJECT.pages.dev`
   - `*.YOUR_PROJECT.pages.dev`（预览部署）
   - 以后绑上的自定义域名
4. 会话时长按你的需要设置。
5. 添加一条 **允许（Allow）** 策略，Include 规则里写上可以打开看板的邮箱。
6. 再为**同一个主机名、仅路径 `/api/push`** 建第二个自托管应用程序。策略用 **绕过（Bypass）**，Include 选所有人。路径更具体的应用程序会优先生效，所以只有这一条路径是公开的。`/api/state` 仍留在第一个应用程序上。
7. 在第一个应用程序里复制 **应用程序受众（AUD）**。
8. 团队域名是 Zero Trust 里看到的主机名，形状像 `YOUR_TEAM.cloudflareaccess.com`。

在 Pages 项目里把它们设成明文变量（**设置 → 变量和机密**，生产和预览都要设）：

| 名称 | 形状 | 说明 |
| --- | --- | --- |
| `ACCESS_TEAM_DOMAIN` | `YOUR_TEAM.cloudflareaccess.com` | 可以是主机名，也可以是 `https://` 开头的源。占位符 `YOUR_TEAM` 会被拒绝。 |
| `ACCESS_AUD` | AUD，多个用英文逗号分开 | 占位符 `YOUR_ACCESS_APPLICATION_AUD` 会被拒绝。 |
| `ACCESS_ALLOWED_EMAILS` | `you@example.com,partner@example.com` | 会转成小写。留空则函数拒绝所有人。 |

这些值通过函数的 `env` 参数读入，不会写进 JavaScript 源码。

以后如果加了自定义域名，两个 Access 应用程序都要加上这个主机名。

## 5. 推送令牌

在真正运行 `st` 的那台机器上生成令牌。明文只放在这台机器上。

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

```bash
export ST_ROOT="$HOME/.grokbot-task-dashboard"
mkdir -p "$ST_ROOT"
install -m 600 /dev/null "$ST_ROOT/.token"
# 把令牌贴进 $ST_ROOT/.token，一行，不要加引号
```

只打印 SHA-256：

```bash
python3 cli/st token-sha256
```

在 Pages 项目里创建一个**机密**（不要做成明文变量），名字是 `TOKEN_SHA256`，把哈希贴进去：

```bash
npx wrangler pages secret put TOKEN_SHA256 --project-name YOUR_PAGES_PROJECT
```

Cloudflare 上只留哈希。明文不要出现在 `wrangler.toml`、控制台的明文变量、git 或 D1 里。本地冒烟可以把明文字符串 `example-push-token` 做一次哈希，把摘要写进 `.dev.vars`。任何能从公网访问的部署都要换新令牌。

改机密之后通常要重新部署，函数才会读到新值。先写机密，再做第 6 步。

轮换：生成新令牌，写入 `.token`，运行 `st token-sha256`，更新机密并重新部署。旧令牌会开始收到 401。

## 6. 部署

```bash
export CLOUDFLARE_API_TOKEN='有 Pages 和 D1 编辑权限的令牌'
export CLOUDFLARE_ACCOUNT_ID='YOUR_ACCOUNT_ID'
export PROJECT_NAME='YOUR_PAGES_PROJECT'
./site/deploy.sh
```

`deploy.sh` 用 Wrangler 发布 `site/public`。`functions/` 和 `public/` 放在一起，会一起上传。三个环境变量缺一个，脚本会直接退出。

## 7. 让 CLI 指向这个部署

```bash
export ST_ROOT="$HOME/.grokbot-task-dashboard"
export ST_PUSH_URL="https://YOUR_PROJECT.pages.dev/api/push"
export ST_TZ="America/New_York"      # 可选，默认就是这个时区
export ST_STATS_DAYS="90"            # 可选，校准用的历史窗口
export ST_HISTORY_DAYS="7"           # 可选，看板上「最近完成」的窗口
export ST_STATS_MAX="500"            # 可选，参与校准的已完成任务上限
export ST_CALIBRATE_MIN="3"          # 可选，样本数达到多少才给出校准后的 ETA
export ST_LANG="zh"                  # 或 en
chmod +x cli/st
export PATH="$PWD/cli:$PATH"
```

冒烟：

```bash
st set --bot Coder --task-id example-smoke --task-type coding \
  --title "[示例] 连通性检查" --estimate 30m --eta +30m
st list
```

`st` 会打印任务和一行校准建议。推送成功时会看到 `st: 已同步到看板`。打开 Pages 地址，通过 Access 登录，确认卡片出现。这条冒烟任务如果不想留在历史里，用 `st rm`；如果想让它变成校准样本，用 `st done`。

命令说明在 README。给代理用的上报习惯在 [agent-reporting.zh-CN.md](agent-reporting.zh-CN.md)。

## 8. 不连 Cloudflare 时看示例数据

```bash
cd site/public
python3 -m http.server 8765
```

打开 `http://127.0.0.1:8765/?example=1`。横幅会标明这些数字是编出来的。这条路径不会启动 Functions，也不会经过 Access。

在本地把 Functions 跑起来。`wrangler pages dev` 下 Access 中间件照样生效，浏览器直接打开会因为没有 Access JWT 而得到 `403 Forbidden`。这种方式适合用 `curl` 带 Bearer 令牌测试 `/api/push`；想看页面请用上面的示例路径。不要把端口暴露到公网：

```bash
cd site
cp .dev.vars.example .dev.vars   # 然后换成你的值
npx wrangler pages dev public --d1 DB=YOUR_D1_DATABASE_NAME
```

`.dev.vars` 已被 git 忽略。

## 排错

| 现象 | 通常原因 |
| --- | --- |
| 推送返回 401 | 没有 `TOKEN_SHA256`，或者哈希和 `.token` 的内容对不上。 |
| 浏览器 403，`access not configured` | `ACCESS_TEAM_DOMAIN` 或 `ACCESS_AUD` 是空的，或仍是占位符。 |
| 403 `email not allowlisted` | Access 里的邮箱不在 `ACCESS_ALLOWED_EMAILS` 中。 |
| 403 `missing Access token` | 请求没有经过 Access。检查主机名是否加进了应用程序，以及是不是只有 `/api/push` 被绕过。 |
| 500 `database not configured` | 没有 D1 绑定，或变量名不是 `DB`。 |
| 推送成功但页面是空的 | 浏览器开的是另一个预览部署，它绑了另一套 D1。 |
| `st` 说没有设置推送地址 | 导出 `ST_PUSH_URL`。本地文件仍然会更新。 |
| 同步失败，下次会重试 | `st` 会写 `$ST_ROOT/.push_pending`，下一次命令会重试。马上重试用 `st push`。 |

## 不要提交的东西

`.token`、`.env`、`.dev.vars`、`.wrangler/`、`node_modules/`，以及 `ST_ROOT` 里的 `bots/`。根目录的 `.gitignore` 已经写了这些。账号 ID、真实的数据库 ID、Access 受众标签和令牌明文只留在 Cloudflare 和你的 shell 里。
