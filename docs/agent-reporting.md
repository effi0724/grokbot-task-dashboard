# Agent reporting rules

`st` is the status channel for whoever is doing the work: a person or an agent. The dashboard only knows what was recorded. These rules keep that record comparable, so the ETA calibration has something honest to learn from.

Use the example bots (`Coder`, `Researcher`, `Ops`, `Coordinator`) or names you configure with `ST_BOTS`. Task text can be any language. Do not put secrets, tokens, account ids, email addresses, or private filesystem paths in a title, stage, or note.

## When to call `st`

Call it at the transition, not at the end of the day.

| Moment | Command | What must be present |
| --- | --- | --- |
| Start | `st set` | Stable `--task-id`, `--title`, `--task-type`, and an estimate (`--estimate` and/or `--eta`). `--state` defaults to `running`. |
| Milestone | `st set` | `--pct` and `--stage` when the step changes. If the deadline moved, pass a new `--eta`. |
| Blocked | `st set --state blocked` | `--note` naming what is stuck and what would unblock it. Refresh `--eta`. |
| Quota | `st set --state quota` | `--resume` for when work can continue, plus a `--note`. If the runner itself is out of quota, also `st claude --state quota --reset … --resume …`. |
| Waiting or queued | `st set --state waiting` or `queued` | An ETA or a resume time. Use `queued` before it has started, `waiting` when it started and then paused. |
| Done | `st done` | The same `--bot` and `--task-id`. This moves the task into history and records the actual duration. |
| Mistake | `st rm` | Only when the task should never have been recorded. It does not enter history and does not affect calibration. |

`st done --state cancelled` is for work that stopped on purpose. Cancelled tasks stay on the recent-history list and are excluded from ratio stats.

## Always give an ETA

- On start, pass `--estimate 90m` (or `2h`, `1.5h`, `1d`) for the duration you believe, and `--eta +90m` or an absolute time for the deadline you are committing to.
- If you pass only `--eta`, the original duration is `deadline - start`. Later ETA edits do not change that original number.
- `待估` / `unknown` is allowed only when you cannot estimate. Say why in `--note`. Tasks without an original duration are shown, and they are skipped by the calibration math.
- When the previous ETA is no longer believable, update it. Each real change increments `eta_revisions`. Repeating the same timestamp does not.
- `st` prints a calibrated suggestion on `st set` and `st estimate`. You may adopt that range as the deadline you publish. Keep `--estimate` as the uncalibrated human number so later tasks can see whether the human number runs long.

Check a suggestion without writing:

```bash
st estimate --bot Coder --task-type coding --estimate 2h
```

## Stable task ids

- Pick the id at the start and keep it: short, lowercase, hyphenated, no slashes. Example: `parse-durations`.
- Changing the title is fine. Changing the id splits one piece of work into two and breaks the history.
- One id is one unit of work. Do not reuse an id after `st done`.
- Do not open a second id to "retry a failed push". `st` keeps the local write and retries. Use `st push` if you want to retry immediately.

## Task types

Pass a short slug in `--task-type`: `coding`, `research`, `review`, `ops`, `writing`, `orchestration`, or another slug you will reuse. Calibration looks for samples in this order: this bot and this type, this type across bots, this bot across types, then everything in the window. A type that changes every task never accumulates samples.

The default window is 90 days (`ST_STATS_DAYS`), longer than the 7-day list on the dashboard (`ST_HISTORY_DAYS`). A trusted suggestion needs 3 completed samples in the chosen bucket (`ST_CALIBRATE_MIN`). Fewer samples produce a widened, shrunk-toward-1 range and are labeled low confidence.

## Notes worth writing

- Stage: the current step, in a few words.
- Blocked: the blocker and the next check.
- Quota: whose quota, and the resume time.
- Done: one line on what shipped, if it is not obvious from the title.

Skip running commentary. The percent and the ETA carry the progress.

## Runner quota

`st claude` records the separate Claude Code card (state `ok`, `running`, `quota`, or `unknown`). It does not replace per-task updates. A task handed to that runner should set `--via "Claude Code"` so the dashboard can group it.
