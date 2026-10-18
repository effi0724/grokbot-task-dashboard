# Deploy GrokBot Task Dashboard

This walks from an empty Cloudflare account to a private dashboard and a working `st` command. Replace every `YOUR_*` value. Do not commit the replacements.

The site is a static page plus two Pages Functions:

- `GET /api/state` reads the latest snapshot from D1. Visitors must present a Cloudflare Access JWT.
- `POST /api/push` accepts a full snapshot from `st`. It is the only path that bypasses Access, and it checks a bearer token against `TOKEN_SHA256`.

## 0. What you need

> `st` runs on macOS and Linux. It uses `fcntl` file locks, so native Windows is not supported; use WSL.

- A Cloudflare account with permission to create Workers/Pages, D1, and Zero Trust Access.
- Node.js 20+ (for Wrangler) and Python 3.11+ (for `st`).
- Wrangler: `npm install -g wrangler`, then `wrangler login`.

Nothing in this repository is bound to a particular account. `site/wrangler.toml` ships with the D1 block commented out on purpose.

## 1. Create the D1 database

```bash
npx wrangler d1 create YOUR_D1_DATABASE_NAME
npx wrangler d1 execute YOUR_D1_DATABASE_NAME --remote --file=site/schema.sql
```

The schema is a single table, `kv`, holding one row (`k = 'state'`) with the latest JSON snapshot. `push.js` also creates that table on the first successful push, so a missed schema step is recoverable, but run it anyway.

## 2. Create the Pages project

```bash
npx wrangler pages project create YOUR_PAGES_PROJECT --production-branch main
```

You can also create the project in the dashboard (Workers & Pages → Create → Pages → Direct Upload). The project name is yours; this repo does not assume one.

## 3. Bind D1 as `DB`

In the Pages project: **Settings → Bindings → Add → D1 database**.

- Variable name: `DB` (the functions read `env.DB`; another name will not work)
- Database: the one from step 1

Keep the binding in the dashboard. `site/wrangler.toml` deliberately has no `pages_build_output_dir`: with that key, Wrangler treats the file as the source of truth and a deploy replaces the D1 binding and variables you set in the dashboard (the site then answers 500 or 403). Its commented blocks are reference only. For local dev, pass the binding on the command line (`--d1 DB=...`, see step 8).

## 4. Cloudflare Access

The page, `/api/state`, and every other path must require Access. `/api/push` must not, because `st` sends its own bearer token and has no browser session.

1. Open **Zero Trust → Access → Applications → Add an application → Self-hosted**.
2. Name it however you like.
3. Add public hostnames:
   - `YOUR_PROJECT.pages.dev`
   - `*.YOUR_PROJECT.pages.dev` (preview deployments)
   - any custom domain you attach later
4. Session duration is up to you.
5. Add an **Allow** policy whose Include rule lists the email addresses that may open the dashboard.
6. Create a **second** self-hosted application for the same hostname and the path `/api/push` only. Give it a **Bypass** policy that includes Everyone. The more specific path application takes precedence, so only that path is public. Leave `/api/state` on the first application.
7. On the first application, copy the **Application Audience (AUD)** tag.
8. Your team domain is the host shown in Zero Trust, shaped like `YOUR_TEAM.cloudflareaccess.com`.

Put those into the Pages project as plain-text variables (**Settings → Variables and secrets**, production and preview):

| Name | Example shape | Notes |
| --- | --- | --- |
| `ACCESS_TEAM_DOMAIN` | `YOUR_TEAM.cloudflareaccess.com` | Hostname or `https://` origin. The placeholder `YOUR_TEAM` is rejected. |
| `ACCESS_AUD` | the AUD tag, or several separated by commas | The placeholder `YOUR_ACCESS_APPLICATION_AUD` is rejected. |
| `ACCESS_ALLOWED_EMAILS` | `you@example.com,partner@example.com` | Lowercased. Empty means the function refuses everyone. |

These values are read from the function `env` argument. They are not compiled into the JavaScript.

If you add a custom domain later, add that hostname to both Access applications.

## 5. Push token

Generate a token on the machine that will run `st`. Store the raw token only there.

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

```bash
export ST_ROOT="$HOME/.grokbot-task-dashboard"
mkdir -p "$ST_ROOT"
install -m 600 /dev/null "$ST_ROOT/.token"
# paste the token into $ST_ROOT/.token, one line, no quotes
```

Print the SHA-256 and nothing else:

```bash
python3 cli/st token-sha256
```

In the Pages project, create a **secret** (not a plain variable) named `TOKEN_SHA256` and paste the hash:

```bash
npx wrangler pages secret put TOKEN_SHA256 --project-name YOUR_PAGES_PROJECT
```

Cloudflare then holds the hash. The raw token never goes in `wrangler.toml`, the dashboard's plain variables, git, or the D1 row. For a local smoke test you can hash the obvious string `example-push-token` and paste that digest into `.dev.vars`. Use a fresh token for any deployment that is reachable from the internet.

Changing the secret usually needs a new deployment before the function sees it. Set the secret, then deploy (step 6).

To rotate: generate a new token, write it to `.token`, run `st token-sha256`, update the secret, redeploy. Old pushes start failing with 401, which is what you want.

## 6. Deploy

```bash
export CLOUDFLARE_API_TOKEN='paste a token with Pages and D1 edit access'
export CLOUDFLARE_ACCOUNT_ID='YOUR_ACCOUNT_ID'
export PROJECT_NAME='YOUR_PAGES_PROJECT'
./site/deploy.sh
```

`deploy.sh` publishes `site/public` with Wrangler. Functions live next to `public/` and are uploaded with it. The script refuses to run until the three variables above are set.

## 7. Point the CLI at the deployment

```bash
export ST_ROOT="$HOME/.grokbot-task-dashboard"
export ST_PUSH_URL="https://YOUR_PROJECT.pages.dev/api/push"
export ST_TZ="America/New_York"      # optional, this is the default
export ST_STATS_DAYS="90"            # optional, calibration window
export ST_HISTORY_DAYS="7"           # optional, "recently finished" window
export ST_STATS_MAX="500"            # optional, max finished tasks kept for calibration
export ST_CALIBRATE_MIN="3"          # optional, samples needed before suggesting a calibrated ETA
export ST_LANG="zh"                  # or en
chmod +x cli/st
export PATH="$PWD/cli:$PATH"
```

Smoke test:

```bash
st set --bot Coder --task-id example-smoke --task-type coding \
  --title "[示例] 连通性检查" --estimate 30m --eta +30m
st list
```

`st` prints the task and a calibration line, then `st: 已同步到看板` when the push is accepted. Open the Pages URL, pass the Access login, and confirm the card. Remove the smoke task with `st rm` if you do not want it in history, or `st done` if you want it to count as a sample.

A full command reference is in the README. Reporting habits for agents are in [agent-reporting.md](agent-reporting.md).

## 8. Look at example data without Cloudflare

```bash
cd site/public
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765/?example=1`. The banner says the numbers are synthetic. This path does not boot Functions or Access.

To boot Functions locally. The Access middleware still runs under `wrangler pages dev`, so a plain browser request gets `403 Forbidden` because there is no Access JWT. Use this to test `/api/push` with `curl` and the bearer token; to look at the page, use the example path above. Do not expose the port:

```bash
cd site
cp .dev.vars.example .dev.vars   # then replace the placeholders
npx wrangler pages dev public --d1 DB=YOUR_D1_DATABASE_NAME
```

`.dev.vars` is gitignored.

## Troubleshooting

| What you see | What it usually means |
| --- | --- |
| Push returns 401 | `TOKEN_SHA256` missing, or the hash is not the hash of the exact `.token` contents. |
| Browser shows 403 `access not configured` | `ACCESS_TEAM_DOMAIN` or `ACCESS_AUD` is empty or still a placeholder. |
| 403 `email not allowlisted` | The Access email is not in `ACCESS_ALLOWED_EMAILS`. |
| 403 `missing Access token` | The request did not pass through Access. Check the hostname is on the application, and that `/api/push` is the only bypass. |
| 500 `database not configured` | The D1 binding is missing or not named `DB`. |
| Page is empty after a successful push | The browser is on a preview deployment bound to a different D1 database. |
| `st` says the push URL is unset | Export `ST_PUSH_URL`. Local files are still updated. |
| Sync failed, next command retries | `st` writes `$ST_ROOT/.push_pending` and retries on the next command. `st push` retries now. |

## What not to commit

`.token`, `.env`, `.dev.vars`, `.wrangler/`, `node_modules/`, and the `bots/` directory inside `ST_ROOT`. The root `.gitignore` already names them. Account ids, real database ids, Access audience tags, and raw tokens stay in Cloudflare and in your shell, not in this repo.
