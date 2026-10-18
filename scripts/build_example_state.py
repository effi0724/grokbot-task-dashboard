#!/usr/bin/env python3
"""Write the labeled example snapshot used by the docs screenshots and ?example=1.

Every bot, title, and number in the output is synthetic.
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

import stlib  # noqa: E402

NY = ZoneInfo("America/New_York")
COMMENT = "EXAMPLE DATA ONLY. Synthetic bots, tasks, and durations for documentation. Not a live board."


def iso(dt):
    return dt.replace(microsecond=0).isoformat()


def done(task_id, title, task_type, estimate, ratio, revisions, finished, note=""):
    actual = int(round(estimate * ratio))
    started = finished - timedelta(minutes=actual)
    return {
        "id": task_id,
        "title": title,
        "task_type": task_type,
        "stage": "",
        "pct": 100,
        "eta": iso(started + timedelta(minutes=estimate)),
        "eta_first": iso(started + timedelta(minutes=estimate)),
        "estimate_minutes": estimate,
        "estimate_source": "flag",
        "state": "done",
        "note": note,
        "via": "",
        "started": iso(started),
        "updated": iso(finished),
        "finished": iso(finished),
        "eta_revisions": revisions,
        "actual_minutes": actual,
    }


def active(task_id, title, task_type, state, pct, estimate, eta, started, updated, **extra):
    task = {
        "id": task_id,
        "title": title,
        "task_type": task_type,
        "stage": extra.get("stage", ""),
        "pct": pct,
        "eta": iso(eta) if eta else "",
        "eta_first": iso(extra.get("eta_first") or eta) if (extra.get("eta_first") or eta) else "",
        "estimate_minutes": estimate,
        "estimate_source": "flag",
        "state": state,
        "note": extra.get("note", ""),
        "via": extra.get("via", ""),
        "started": iso(started),
        "updated": iso(updated),
        "eta_revisions": extra.get("eta_revisions", 0),
        "resume": iso(extra["resume"]) if extra.get("resume") else "",
    }
    return task


def main():
    # Fixed clock so regenerated example data is reproducible.
    fixed = os.environ.get("EXAMPLE_NOW", "2026-01-15T14:00:00")
    now = datetime.fromisoformat(fixed).replace(tzinfo=NY, microsecond=0)
    bots = {
        "Coordinator": {
            "desc": "Routes work across agents",
            "desc_zh": "在多个代理之间分派工作",
            "history_spec": [
                ("orch-1", "[示例] 整理周计划", "orchestration", 60, 1.2, 1, 3),
                ("orch-2", "[示例] 回收昨日状态", "orchestration", 40, 1.8, 2, 16),
            ],
        },
        "Researcher": {
            "desc": "Reads and summarizes sources",
            "desc_zh": "阅读资料并整理摘要",
            "history_spec": [
                ("read-1", "[示例] 摘要接口说明", "research", 90, 1.0, 0, 1),
                ("read-2", "[示例] 对照两篇公开文档", "research", 120, 1.1, 0, 4),
                ("read-3", "[示例] 列出开放问题", "research", 60, 1.3, 1, 9),
                ("read-4", "[示例] 复核引用", "research", 45, 0.9, 0, 15),
                ("read-5", "[示例] 归纳术语表", "research", 80, 1.2, 1, 28),
                ("read-6", "[示例] 写阅读笔记", "research", 100, 1.4, 1, 40),
            ],
        },
        "Coder": {
            "desc": "Implements changes and opens PRs",
            "desc_zh": "实现改动并提交合并请求",
            "history_spec": [
                ("code-1", "[示例] 补上工期解析", "coding", 120, 1.4, 1, 1),
                ("code-2", "[示例] 为校准补测试", "coding", 90, 1.6, 2, 3),
                ("code-3", "[示例] 拆分推送校验", "coding", 60, 1.2, 0, 6),
                ("code-4", "[示例] 修正历史窗口", "coding", 180, 1.5, 1, 12),
                ("code-5", "[示例] 补命令行帮助", "coding", 45, 1.8, 3, 18),
                ("code-6", "[示例] 整理示例数据", "coding", 120, 1.1, 0, 25),
                ("code-7", "[示例] 写状态迁移", "coding", 90, 1.3, 1, 36),
                ("code-8", "[示例] 检查边界输入", "coding", 150, 2.0, 2, 48),
            ],
        },
        "Ops": {
            "desc": "Deploy and monitoring",
            "desc_zh": "部署与运行状态",
            "history_spec": [
                ("ops-1", "[示例] 核对部署清单", "deploy", 60, 0.7, 0, 2),
                ("ops-2", "[示例] 演练回滚步骤", "deploy", 90, 0.8, 0, 8),
                ("ops-3", "[示例] 看监控空跑", "deploy", 30, 1.1, 1, 14),
                ("ops-4", "[示例] 更新占位配置", "deploy", 40, 0.6, 0, 22),
                ("ops-5", "[示例] 检查备份任务", "deploy", 50, 0.9, 0, 33),
            ],
        },
        "Writer": {
            "desc": "Drafts notes and digests",
            "desc_zh": "撰写说明和摘要",
            "history_spec": [
                ("write-1", "[示例] 写发布说明", "writing", 70, 1.0, 0, 5),
                ("write-2", "[示例] 改一版简介", "writing", 40, 0.95, 0, 11),
                ("write-3", "[示例] 对齐中英标题", "writing", 50, 1.05, 1, 21),
                ("write-4", "[示例] 压缩更新日志", "writing", 30, 1.0, 0, 44),
            ],
        },
    }

    temp = tempfile.TemporaryDirectory()
    os.environ["ST_ROOT"] = temp.name
    os.environ["ST_STATS_DAYS"] = "90"
    os.environ["ST_HISTORY_DAYS"] = "7"
    os.environ["ST_TZ"] = "America/New_York"
    os.environ.pop("ST_BOTS", None)
    bots_dir = Path(temp.name) / "bots"
    bots_dir.mkdir(parents=True, exist_ok=True)

    for name, spec in bots.items():
        history = []
        for task_id, title, task_type, estimate, ratio, revisions, days_ago in spec["history_spec"]:
            finished = now - timedelta(days=days_ago, hours=2)
            history.append(done(task_id, title, task_type, estimate, ratio, revisions, finished, note="EXAMPLE"))
        payload = {
            "_example": True,
            "_comment": COMMENT,
            "bot": name,
            "desc": spec["desc"],
            "desc_zh": spec["desc_zh"],
            "tasks": {},
            "history": history,
            "updated": iso(now),
        }
        (bots_dir / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    coder = json.loads((bots_dir / "Coder.json").read_text(encoding="utf-8"))
    coder["tasks"] = {
        "parse-durations": active(
            "parse-durations", "[示例] 实现工期解析", "coding", "running", 62, 120,
            now + timedelta(hours=2), now - timedelta(minutes=70), now - timedelta(minutes=4),
            stage="补相对时间与绝对时间", eta_revisions=1,
            eta_first=now - timedelta(minutes=70) + timedelta(hours=3),
            note="EXAMPLE · 原始预估 2 小时，ETA 改过 1 次。",
        ),
        "flaky-check": active(
            "flaky-check", "[示例] 看一条不稳定的检查", "coding", "blocked", 30, 60,
            now - timedelta(minutes=20), now - timedelta(hours=3), now - timedelta(minutes=12),
            stage="等待一个可重复的失败样本", eta_revisions=2, via="Claude Code",
            note="EXAMPLE · 卡在复现步骤，ETA 已过。",
        ),
    }
    (bots_dir / "Coder.json").write_text(json.dumps(coder, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    coordinator = json.loads((bots_dir / "Coordinator.json").read_text(encoding="utf-8"))
    coordinator["tasks"] = {
        "route-morning": active(
            "route-morning", "[示例] 分发晨间摘要", "orchestration", "running", 40, 90,
            now + timedelta(minutes=50), now - timedelta(minutes=40), now - timedelta(minutes=6),
            stage="等待 Researcher 回传要点", eta_revisions=1,
            note="EXAMPLE · 还在等上游摘要。",
        ),
    }
    (bots_dir / "Coordinator.json").write_text(json.dumps(coordinator, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    researcher = json.loads((bots_dir / "Researcher.json").read_text(encoding="utf-8"))
    researcher["tasks"] = {
        "source-pass": active(
            "source-pass", "[示例] 通读发布说明", "research", "waiting", 25, 150,
            now + timedelta(hours=3), now - timedelta(hours=1), now - timedelta(minutes=8),
            stage="排队等一个空闲窗口", eta_revisions=0,
            note="EXAMPLE · 人还在上一份材料上。",
        ),
    }
    (bots_dir / "Researcher.json").write_text(json.dumps(researcher, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    ops = json.loads((bots_dir / "Ops.json").read_text(encoding="utf-8"))
    ops["tasks"] = {
        "quota-window": active(
            "quota-window", "[示例] 等额度恢复后部署", "deploy", "quota", 15, 45,
            now + timedelta(hours=5), now - timedelta(minutes=25), now - timedelta(minutes=3),
            stage="额度窗口已满", eta_revisions=0, resume=now + timedelta(hours=4, minutes=30),
            note="EXAMPLE · 恢复时间只是占位。",
        ),
    }
    ops["history"].append({
        "id": "ops-cancelled",
        "title": "[示例] 取消的演练",
        "task_type": "deploy",
        "state": "cancelled",
        "pct": 10,
        "estimate_minutes": 30,
        "actual_minutes": 12,
        "eta_revisions": 0,
        "started": iso(now - timedelta(days=1, hours=3)),
        "finished": iso(now - timedelta(days=1, hours=2)),
        "updated": iso(now - timedelta(days=1, hours=2)),
        "note": "EXAMPLE · 取消的任务不计入倍率。",
        "stage": "",
        "via": "",
        "eta": "",
        "eta_first": "",
    })
    (bots_dir / "Ops.json").write_text(json.dumps(ops, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    runner = {
        "_example": True,
        "_comment": COMMENT,
        "bot": "Claude Code",
        "tasks": {},
        "history": [],
        "updated": iso(now),
        "claude": {
            "state": "quota",
            "reset": iso(now + timedelta(hours=4)),
            "resume": iso(now + timedelta(hours=4, minutes=30)),
            "model": "example-model",
            "plan": "example",
            "note": "[示例] 额度窗口已用完，恢复后再继续排队任务。",
            "updated": iso(now - timedelta(minutes=9)),
        },
    }
    (bots_dir / "Claude Code.json").write_text(json.dumps(runner, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    stlib.set_clock(lambda: now)
    snapshot = stlib.snapshot()
    stlib.set_clock(None)
    snapshot["_example"] = True
    snapshot["_comment"] = COMMENT
    text = json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n"
    targets = [
        ROOT / "site" / "public" / "example-state.json",
        ROOT / "examples" / "example-snapshot.json",
    ]
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    sample = ROOT / "examples" / "sample-state"
    sample.mkdir(parents=True, exist_ok=True)
    for child in sample.glob("*.json"):
        child.unlink()
    for path in sorted(bots_dir.glob("*.json")):
        (sample / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    temp.cleanup()
    print(f"example snapshot: {snapshot['accuracy']['sample_count']} calibration samples")
    print(f"bots: {', '.join(bot['bot'] for bot in snapshot['bots'])}")


if __name__ == "__main__":
    main()
