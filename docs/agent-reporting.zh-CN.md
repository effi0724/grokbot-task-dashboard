# 代理上报规则

`st` 是干活的人（或代理）对外的状态通道。看板只知道被记下来的内容。下面这些习惯让记录能互相比较，校准才有诚实的样本可以学。

机器人名字用示例里的 `Coder`、`Researcher`、`Ops`、`Coordinator`，或用 `ST_BOTS` 配你自己的。标题可以用任何语言。不要在标题、步骤或备注里写机密、令牌、账号 ID、邮箱或私人路径。

## 什么时候调用 `st`

在状态变化的当下记，不要攒到一天结束。

| 时机 | 命令 | 必须带上 |
| --- | --- | --- |
| 开始 | `st set` | 稳定的 `--task-id`、`--title`、`--task-type`，以及工期（`--estimate` 和/或 `--eta`）。`--state` 默认是 `running`。 |
| 推进 | `st set` | 步骤变了就更新 `--pct` 和 `--stage`。截止时间变了就传新的 `--eta`。 |
| 卡住 | `st set --state blocked` | `--note` 写明卡在哪里、怎样才算解开。同时刷新 `--eta`。 |
| 额度用完 | `st set --state quota` | `--resume` 写预计恢复时间，加一句 `--note`。如果是执行器本身没额度，再跑 `st claude --state quota --reset … --resume …`。 |
| 等待或排队 | `st set --state waiting` 或 `queued` | 给 ETA 或恢复时间。还没开始用 `queued`，开始后停下来用 `waiting`。 |
| 完成 | `st done` | 同一个 `--bot` 和 `--task-id`。任务会进历史，并记下实际工期。 |
| 登记错了 | `st rm` | 只用于根本不该存在的任务。它不进历史，也不影响校准。 |

`st done --state cancelled` 表示工作被主动停掉。取消的任务仍出现在最近完成列表里，但不进入倍率统计。

## 每次都给 ETA

- 开始时用 `--estimate 90m`（也可以是 `2h`、`1.5h`、`1d`）写下你相信的工期，用 `--eta +90m` 或一个绝对时间写下你承诺的截止点。
- 如果只给了 `--eta`，原始工期按「截止时间减开始时间」计算。之后再改 ETA，不会改掉这个原始数字。
- 只有真的估不出来时才用 `待估` / `unknown`，并在 `--note` 里说明原因。没有原始工期的任务仍会显示，但校准会跳过它们。
- 原先的 ETA 已经不可信时就更新。真正的变化会让 `eta_revisions` 加一。重复同一个时间不会加。
- `st set` 和 `st estimate` 都会打印校准建议。你可以把这个区间当成对外的截止时间。`--estimate` 仍应保持为没校准过的人工数字，这样以后才能看出人工数字是不是偏短。

只看建议、不写状态：

```bash
st estimate --bot Coder --task-type coding --estimate 2h
```

## 任务 id 要稳定

- 一开始就定好，之后不要换。短、小写、用连字符、不要斜杠。例如 `parse-durations`。
- 标题可以改。改 id 会把同一件事拆成两段，历史就断了。
- 一个 id 对应一件事。`st done` 之后不要复用。
- 推送失败时不要另开一个 id「重试」。`st` 会留下本地记录并在下次重试。想立刻重试就运行 `st push`。

## 任务类型

`--task-type` 用会反复出现的短标记：`coding`、`research`、`review`、`ops`、`writing`、`orchestration`，或你自己会复用的标记。校准按这个顺序找样本：这个机器人加这个类型、所有机器人的这个类型、这个机器人的全部类型、窗口内的全部样本。每个任务都换一个新类型，就永远攒不够样本。

默认统计窗口是 90 天（`ST_STATS_DAYS`），比看板上「最近完成」的 7 天（`ST_HISTORY_DAYS`）更长。一个可信的建议至少需要所选分组里有 3 个已完成样本（`ST_CALIBRATE_MIN`）。样本更少时，区间会变宽，倍率会往 1 收缩，并标明置信度低。

## 值得写的备注

- 步骤：当前在做什么，几个词。
- 卡住：卡点是什么，下次什么时候再看。
- 额度：谁的额度，何时恢复。
- 完成：如果标题看不出来交付了什么，补一句。

不要写流水账。进度靠百分比和 ETA。

## 执行器额度

`st claude` 记录 Claude Code 卡片：状态（`ok`、`running`、`quota`、`unknown`），5 小时和每周两根额度条（`--session-left`、`--week-left`，0–100），以及各自的重置时间（`--reset`、`--weekly-reset`）。尽量读真实数字，不要手填：`scripts/claude-usage.sh` 会打开 `/usage` 面板（不发模型请求、不耗额度），保存文字后运行 `st claude --from-usage FILE`。以下时机运行：

1. 把任务交给 Claude Code 之前；
2. 它跑完一段工作之后；
3. 一看到用量或限流提示就运行，不要手写 `st claude --state quota`；
4. 重置之后、续跑之前。

不要定时轮询。任一额度条接近 0 就标为 `quota`，恢复时间设为该次重置后 30 分钟；两根条都有余量的读数会退出 `quota`。只手动标 `--state quota` 而不给数字时，5 小时条会置 0，保证卡片和进度条一致。读数超过 3 小时，卡片会提示可能不准。

其他订阅执行者（例如 Gemini、Kimi）用 `st quota --runner 名称`，参数有 `--state ok|running|quota|login|unknown`、`--week-left`、`--used`、`--limit`、`--reset`、`--weekly-reset`、`--resume`、`--model`、`--plan`、`--tool`、`--note`。每个执行者一张卡片。

这些卡片不能代替每条任务自己的更新。任务的 `--via` 填执行者名称（`--via "Claude Code"`、`--via Gemini`）。执行者额度用完时，页面把它的进行中任务显示为 `quota`；重置时间一过，`quota` 任务显示为 `queued`。真正续跑时仍要 `st set ... --state running`。

## 例行任务

每个定期任务登记一次：`st set --bot 名称 --task-id 短id --title "..." --stage "每天 08:00" --state routine --eta 待估`。频率变了或删除时同步更新。只跑一次的定时任务跑完立刻 `st done`，不要一直留成例行任务。

## 长时间盯任务的进程（watcher）一律用 `stwatch` 启动

用 `cmd &` 或 `nohup` 起的 watcher 和 agent 的 shell 在同一个进程组。shell 被回收（命令超时、会话结束、重启）时整组会被 `SIGKILL`，不留任何报错，看板任务就停在旧进度。所以改用 `stwatch`：

```bash
stwatch start --name 英文短名 --bot 名称 --task-id 任务id [--cwd 目录] [--max-restarts 5] -- 命令 参数...
stwatch list                 # 状态、PID、重启次数、心跳
stwatch logs 英文短名        # 默认日志 $ST_ROOT/watchers/英文短名.log
stwatch stop 英文短名        # 停止；`stwatch rm` 还会删除登记
stwatch watchdog             # 巡检一次：守护进程没了就拉起，并确保常驻巡检在线
```

- 守护进程用 setsid 跑在独立会话里。命令退出码非 0 时退避重启（10 秒、20 秒、40 秒……最长 5 分钟；`STWATCH_BACKOFF_SEC` 设起始值），最多 `--max-restarts` 次。退出码 0 视为正常结束。任务被 `st done` 或 `st rm` 关掉后，1 分钟内自动停止（`--keep-after-done` 可关闭这一行为）。
- 心跳：每 10 分钟（`STWATCH_BEAT_SEC`）运行一次 `st beat`，只记录 `heartbeat` 和 watcher 状态，不改进度，也不改 `updated`。watcher 自己照常用 `st set` 推进度。
- 拉起：`stwatch daemon` 每 5 分钟巡检一次（`STWATCH_DAEMON_SEC`）；`stwatch watchdog` 发现常驻进程没了会拉起它。再用你手上的调度方式（cron、launchd、例行任务）每 15–30 分钟跑一次 `scripts/stwatch-watchdog.sh`，作为第二层。守护进程没了但命令还在跑时，巡检会接管它，不会再起一份。
- watcher 里调用 `st` 不要让异常打断循环：bash 写 `st set ... || true`，Python 用 try/except 包住 `subprocess.run([... "st" ...], timeout=60)`（`TimeoutExpired` 也要接住）。watcher 会带上 `ST_PUSH_RETRIES=3`，推送失败会退避重试。
- 真正干活的长任务（OCR、备份等）只有确认重跑安全时才这样托管。
- `stwatch` 以 Linux 为主：防 PID 复用和识别重启靠 `/proc`。macOS 上退化为用信号 0 判断进程是否存活。

## 可能卡住与失联

看板会给太久没动静的进行中任务挂标签。动静指 `st` 更新或 watcher 心跳。

- **可能卡住**：有 watcher 的任务 30 分钟没心跳；没有 watcher 的任务 60 分钟没更新；或者 ETA 过了 15 分钟还没有新进度。
- **失联**：watcher 报告已放弃（重启次数用完），或者 3 小时毫无动静。

标签可以点击，用来筛选看板。
