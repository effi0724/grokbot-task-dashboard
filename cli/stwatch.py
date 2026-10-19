"""stwatch: supervise long-running watcher processes for `st`.

A watcher started from an agent's shell (`cmd &`, `nohup`) shares that
shell's process group and dies silently when the shell is reaped. `stwatch`
detaches the work with setsid, restarts it with backoff when it exits
non-zero, sends `st beat` heartbeats, and stops it once the task is finished
on the dashboard. `stwatch watchdog` (or the resident `stwatch daemon`)
revives supervisors that were killed.

State lives in $ST_ROOT/watchers/NAME.json. Linux gets PID-reuse protection
from /proc; elsewhere liveness falls back to signal 0.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import stlib  # noqa: E402

t = stlib.t
ST = str(HERE / "st")
SELF = str(HERE / "stwatch")


def env_int(name, default):
    return stlib.int_env(name, default)


def local_every():
    return env_int("STWATCH_LOCAL_SEC", 60)


def beat_every():
    return env_int("STWATCH_BEAT_SEC", 600)


def daemon_every():
    return env_int("STWATCH_DAEMON_SEC", 300)


def backoff_base():
    raw = os.environ.get("STWATCH_BACKOFF_SEC", "").strip()
    try:
        return max(0.0, float(raw)) if raw else 10.0
    except ValueError:
        return 10.0


def backoff(n):
    return min(300.0, backoff_base() * 2 ** (n - 1))


def wdir():
    return os.path.join(stlib.root_dir(), "watchers")


def now():
    return stlib.iso(stlib.now())


def boot_id():
    try:
        with open("/proc/sys/kernel/random/boot_id", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def pstart(pid):
    """Process start time (field 22 of /proc/PID/stat), to detect PID reuse."""
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
            stat = handle.read()
        return stat[stat.rindex(")") + 2:].split()[19]
    except Exception:
        return None


def alive(pid, start=None):
    if not pid:
        return False
    proc = f"/proc/{pid}/stat"
    if os.path.exists("/proc/self/stat"):
        try:
            with open(proc, encoding="utf-8") as handle:
                stat = handle.read()
            if stat[stat.rindex(")") + 2:].split()[0] == "Z":
                return False
        except Exception:
            return False
        return start is None or pstart(pid) == start
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def safe_name(name):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,59}", name or ""):
        raise SystemExit(t(f"stwatch: 名称只能用字母、数字、. _ -：{name!r}",
                           f"stwatch: name may only use letters, digits, . _ -: {name!r}"))
    return name


def rpath(name):
    return os.path.join(wdir(), name + ".json")


def lockpath(name):
    return os.path.join(wdir(), "." + name + ".runlock")


def runner_locked(name):
    """A supervisor is online iff it holds the exclusive lock on .NAME.runlock."""
    try:
        handle = open(lockpath(name), "a")
    except OSError:
        return False
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        handle.close()


def load(name):
    with open(rpath(name), encoding="utf-8") as handle:
        return json.load(handle)


def save(record):
    path = rpath(record["name"])
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def update(name, **fields):
    os.makedirs(wdir(), exist_ok=True)
    with open(os.path.join(wdir(), ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = load(name)
        record.update(fields)
        save(record)
        return record


def names():
    os.makedirs(wdir(), exist_ok=True)
    return sorted(f[:-5] for f in os.listdir(wdir()) if f.endswith(".json") and not f.startswith("."))


def wlog(message):
    path = os.path.join(wdir(), "watchdog.log")
    try:
        os.makedirs(wdir(), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 512 * 1024:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{now()} {message}\n")
    except OSError:
        pass


def task_active(record):
    """Is the task still open on the dashboard? Unreadable state counts as open."""
    try:
        with open(stlib.bot_path(record["bot"]), encoding="utf-8") as handle:
            data = json.load(handle)
        return record["task_id"] in (data.get("tasks") or {})
    except Exception:
        return True


def beat(record, alive_flag=True, note=None, attempts=3):
    """Send `st beat`. Failures are logged and retried; they never stop the watcher."""
    if not record.get("task_id"):
        return
    cmd = [sys.executable, ST, "beat", "--bot", record["bot"], "--task-id", record["task_id"],
           "--watcher", record["name"], "--alive", "1" if alive_flag else "0",
           "--restarts", str(record.get("restarts", 0)), "--quiet"]
    if note:
        cmd += ["--wnote", note]
    env = dict(os.environ, ST_PUSH_RETRIES=os.environ.get("ST_PUSH_RETRIES", "3"))
    for attempt in range(attempts):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env, stdin=subprocess.DEVNULL)
            if proc.returncode in (0, 3):
                return
            wlog(f"[{record['name']}] beat rc={proc.returncode} {proc.stderr.strip()[-200:]}")
        except Exception as exc:
            wlog(f"[{record['name']}] beat error {exc!r}")
        if attempt + 1 < attempts:
            time.sleep(5 * 3 ** attempt)


def spawn_runner(name, adopt=None):
    """Start the supervisor in its own session so the caller's shell cannot take it down."""
    record = load(name)
    log = record.get("log") or os.path.join(wdir(), name + ".log")
    with open(log, "a") as handle:
        args = [sys.executable, SELF, "_run", name] + (["--adopt", str(adopt)] if adopt else [])
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT,
                         cwd=record.get("cwd") or "/", start_new_session=True, close_fds=True)
    for _ in range(50):
        if runner_locked(name):
            return True
        time.sleep(0.1)
    return False


def kill(pid):
    if not pid:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    for _ in range(50):
        if not alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def cmd_start(args):
    name = safe_name(args.name)
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else list(args.cmd or [])
    if not cmd:
        raise SystemExit(t("stwatch: 在 -- 后面给出要运行的命令", "stwatch: give the command after --"))
    os.makedirs(wdir(), exist_ok=True)
    if os.path.exists(rpath(name)):
        old = load(name)
        if runner_locked(name) or (old.get("boot_id") == boot_id() and alive(old.get("pid"), old.get("pid_start"))):
            raise SystemExit(t(f"stwatch: {name} 已在运行；先 stwatch stop {name}",
                               f"stwatch: {name} is already running; stwatch stop {name} first"))
    stamp = now()
    record = {
        "name": name, "bot": args.bot, "task_id": args.task_id, "cmd": cmd,
        "cwd": os.path.abspath(args.cwd or os.getcwd()),
        "log": os.path.abspath(args.log) if args.log else os.path.join(wdir(), name + ".log"),
        "max_restarts": max(0, args.max_restarts), "restarts": 0, "status": "starting",
        "created": stamp, "started": stamp, "pid": None, "pid_start": None,
        "runner_pid": None, "runner_start": None, "boot_id": boot_id(),
        "heartbeat": None, "last_exit": None, "stop_when_task_done": not args.keep_after_done,
    }
    save(record)
    spawn_runner(name)
    for _ in range(50):
        time.sleep(0.1)
        record = load(name)
        if record.get("pid"):
            break
    print(t(f"stwatch: 已启动 {name}（守护 {record.get('runner_pid')}，任务进程 {record.get('pid')}），日志 {record['log']}",
            f"stwatch: started {name} (supervisor {record.get('runner_pid')}, process {record.get('pid')}), log {record['log']}"))


def log_line(message):
    print(f"{now()} stwatch: {message}", flush=True)


def run(name, adopt=None):
    """Supervisor loop: run, restart non-zero exits with backoff, heartbeat, stop when the task closes."""
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    runlock = open(lockpath(name), "a")
    try:
        fcntl.flock(runlock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log_line(t(f"{name} 已有守护进程，本进程退出", f"{name} already has a supervisor; exiting"))
        return
    stop = {"flag": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))
    update(name, runner_pid=os.getpid(), runner_start=pstart(os.getpid()), boot_id=boot_id(), status="running")
    last_local = 0.0
    while True:
        record = load(name)
        child = None
        if adopt and alive(adopt, record.get("pid_start")):
            pid = adopt
            log_line(t(f"接管仍在运行的任务进程 {pid}", f"adopting running process {pid}"))
        else:
            env = dict(os.environ, STWATCH_NAME=name, STWATCH_TASK=record.get("task_id") or "",
                       STWATCH_BOT=record.get("bot") or "", ST_PUSH_RETRIES=os.environ.get("ST_PUSH_RETRIES", "3"))
            log_line(t(f"启动（第 {record.get('restarts', 0) + 1} 次）：{' '.join(record['cmd'])}",
                       f"start #{record.get('restarts', 0) + 1}: {' '.join(record['cmd'])}"))
            try:
                child = subprocess.Popen(record["cmd"], cwd=record.get("cwd") or None, stdin=subprocess.DEVNULL, env=env)
            except Exception as exc:
                update(name, status="dead", last_exit=f"spawn failed {exc!r}")
                beat(load(name), False, t("启动失败", "failed to start"))
                return
            pid = child.pid
            record = update(name, pid=pid, pid_start=pstart(pid), last_start=now(), status="running")
        adopt = None
        while True:
            if child is not None:
                rc = child.poll()
                if rc is not None:
                    break
            elif not alive(pid, record.get("pid_start")):
                rc = "adopted-exit"
                break
            tick = time.time()
            if tick - last_local >= local_every():
                record = update(name, heartbeat=now())
                if record.get("stop_when_task_done") and not task_active(record):
                    log_line(t("看板上任务已结束，停止", "task closed on the dashboard; stopping"))
                    kill(pid)
                    update(name, status="done", pid=None)
                    return
                if tick - record.get("_last_push", 0) >= beat_every():
                    beat(record)
                    record = update(name, _last_push=tick)
                last_local = tick
            if stop["flag"]:
                kill(pid)
                update(name, status="stopped", pid=None)
                log_line(t("已停止", "stopped"))
                return
            time.sleep(1)
        record = load(name)
        log_line(t(f"任务进程退出 rc={rc}", f"process exited rc={rc}"))
        if rc == 0 or (rc == "adopted-exit" and not record.get("stop_when_task_done")):
            update(name, status="exited", last_exit=str(rc), pid=None)
            return
        if record.get("stop_when_task_done") and not task_active(record):
            update(name, status="done", last_exit=str(rc), pid=None)
            return
        if record.get("restarts", 0) >= record.get("max_restarts", 5):
            update(name, status="dead", last_exit=str(rc), pid=None)
            wlog(f"[{name}] gave up after {record.get('restarts')} restarts (rc={rc})")
            beat(load(name), False, t(f"自动重启 {record.get('restarts')} 次仍失败，需要人工处理",
                                      f"still failing after {record.get('restarts')} restarts; needs a human"))
            return
        n = record.get("restarts", 0) + 1
        update(name, restarts=n, last_exit=str(rc))
        wlog(f"[{name}] exited rc={rc}; restart #{n} in {backoff(n):g}s")
        time.sleep(backoff(n))
        beat(load(name))


def watchdog(quiet=False):
    """Revive supervisors that disappeared (reaped shell, reboot, kill -9) while the task is still open."""
    out = []
    os.makedirs(wdir(), exist_ok=True)
    with open(os.path.join(wdir(), ".watchdog.lock"), "a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        for name in names():
            try:
                record = load(name)
            except Exception as exc:
                out.append(f"{name}: bad record {exc!r}")
                continue
            status = record.get("status")
            if status in ("stopped", "exited", "done"):
                out.append(f"{name}: {status}")
                continue
            if runner_locked(name):
                out.append(t(f"{name}: 正常（pid {record.get('pid')}，重启 {record.get('restarts', 0)} 次）",
                             f"{name}: ok (pid {record.get('pid')}, {record.get('restarts', 0)} restarts)"))
                continue
            if status == "dead":
                out.append(t(f"{name}: 已放弃，需要人工处理", f"{name}: gave up; needs a human"))
                continue
            if record.get("stop_when_task_done") and not task_active(record):
                update(name, status="done")
                out.append(t(f"{name}: 看板任务已结束，不再拉起", f"{name}: task closed; not reviving"))
                continue
            same_boot = record.get("boot_id") == boot_id()
            if same_boot and alive(record.get("pid"), record.get("pid_start")):
                spawn_runner(name, adopt=record["pid"])
                message = t(f"{name}: 守护进程没了，任务进程 {record['pid']} 还在 → 重新接管",
                            f"{name}: supervisor gone, process {record['pid']} alive → adopted")
            elif record.get("restarts", 0) >= record.get("max_restarts", 5):
                update(name, status="dead")
                beat(load(name), False, t("守护进程和任务进程都没了，重启次数已用完",
                                          "supervisor and process gone; restarts used up"))
                message = t(f"{name}: 重启次数已用完 → 标记失联", f"{name}: restarts used up → marked lost")
            else:
                update(name, restarts=record.get("restarts", 0) + 1, pid=None)
                spawn_runner(name)
                why = t("重启过" if not same_boot else "被杀", "reboot" if not same_boot else "killed")
                message = t(f"{name}: 守护进程和任务进程都没了（{why}）→ 第 {record.get('restarts', 0) + 1} 次重启",
                            f"{name}: supervisor and process gone ({why}) → restart #{record.get('restarts', 0) + 1}")
            wlog(message)
            out.append(message)
    if not quiet:
        print("\n".join(out) if out else t("stwatch: 没有登记的 watcher", "stwatch: no watchers registered"))
    return out


def daemon_ok():
    try:
        with open(os.path.join(wdir(), ".daemon"), encoding="utf-8") as handle:
            pid, start = handle.read().split()
        return alive(int(pid), None if start == "None" else start)
    except Exception:
        return False


def ensure_daemon():
    if daemon_ok():
        return False
    os.makedirs(wdir(), exist_ok=True)
    with open(os.path.join(wdir(), "daemon.log"), "a") as handle:
        subprocess.Popen([sys.executable, SELF, "daemon"], stdin=subprocess.DEVNULL, stdout=handle,
                         stderr=subprocess.STDOUT, start_new_session=True, close_fds=True, cwd="/")
    time.sleep(0.5)
    return True


def cmd_daemon(_args):
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    os.makedirs(wdir(), exist_ok=True)
    lock = open(os.path.join(wdir(), ".daemon.lock"), "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(t("stwatch daemon: 已有实例", "stwatch daemon: already running"))
        return
    with open(os.path.join(wdir(), ".daemon"), "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {pstart(os.getpid())}")
    wlog(f"daemon started pid {os.getpid()}, every {daemon_every()}s")
    while True:
        try:
            watchdog(quiet=True)
        except Exception as exc:
            wlog(f"daemon watchdog error {exc!r}")
        time.sleep(daemon_every())


def cmd_list(_args):
    found = names()
    if not found:
        print(t("stwatch: 没有登记的 watcher", "stwatch: no watchers registered"))
        return
    for name in found:
        record = load(name)
        online = t("守护在线", "supervised") if runner_locked(name) else t("守护不在", "unsupervised")
        beat_at = (record.get("heartbeat") or "—")[5:16].replace("T", " ")
        print(f"{name:<22} {record.get('status', ''):<8} {online:<12} pid {str(record.get('pid')):<8} "
              f"{record.get('restarts', 0)}/{record.get('max_restarts')}  [{record.get('bot')}/{record.get('task_id')}]  "
              f"♥ {beat_at}  {' '.join(record['cmd'])[:80]}")
    print(t(f"巡检守护：{'在线' if daemon_ok() else '不在'}", f"watchdog daemon: {'online' if daemon_ok() else 'offline'}"))


def cmd_stop(args, remove=False):
    name = safe_name(args.name)
    record = load(name)
    update(name, status="stopped")
    if runner_locked(name) and alive(record.get("runner_pid"), record.get("runner_start")):
        try:
            os.kill(record["runner_pid"], signal.SIGTERM)
        except OSError:
            pass
        for _ in range(80):
            if not runner_locked(name):
                break
            time.sleep(0.1)
    if alive(record.get("pid"), record.get("pid_start")):
        kill(record["pid"])
    update(name, status="stopped", pid=None)
    if remove:
        os.remove(rpath(name))
    print(t(f"stwatch: 已停止{'并删除' if remove else ''} {name}", f"stwatch: stopped{' and removed' if remove else ''} {name}"))


def build_parser():
    parser = argparse.ArgumentParser(prog="stwatch", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd_name", required=True)
    start = sub.add_parser("start", help="start a supervised watcher / 启动并托管")
    start.add_argument("--name", required=True)
    start.add_argument("--bot", required=True)
    start.add_argument("--task-id", required=True)
    start.add_argument("--cwd")
    start.add_argument("--log")
    start.add_argument("--max-restarts", type=int, default=5)
    start.add_argument("--keep-after-done", action="store_true", help="keep running after the task closes / 任务结束后不自动停")
    start.add_argument("cmd", nargs=argparse.REMAINDER)
    for name in ("status", "stop", "rm", "logs"):
        sub.add_parser(name).add_argument("name")
    sub.add_parser("list")
    sub.add_parser("watchdog", help="revive dead supervisors and ensure the daemon / 巡检并拉起")
    sub.add_parser("daemon", help="resident watchdog loop / 常驻巡检")
    run_cmd = sub.add_parser("_run")
    run_cmd.add_argument("name")
    run_cmd.add_argument("--adopt", type=int)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd_name == "start":
        cmd_start(args)
    elif args.cmd_name == "_run":
        run(args.name, args.adopt)
    elif args.cmd_name == "list":
        cmd_list(args)
    elif args.cmd_name == "status":
        print(json.dumps(load(safe_name(args.name)), ensure_ascii=False, indent=1))
    elif args.cmd_name == "stop":
        cmd_stop(args)
    elif args.cmd_name == "rm":
        cmd_stop(args, remove=True)
    elif args.cmd_name == "logs":
        os.execvp("tail", ["tail", "-n", "40", load(safe_name(args.name))["log"]])
    elif args.cmd_name == "watchdog":
        watchdog()
        started = ensure_daemon()
        print(t("巡检守护：" + ("刚拉起" if started else "在线"), "watchdog daemon: " + ("started" if started else "online")))
    elif args.cmd_name == "daemon":
        cmd_daemon(args)
    return 0
