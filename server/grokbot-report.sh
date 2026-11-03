#!/usr/bin/env bash
# grokbot-report.sh — 每 5 分钟把本机资源快照（CPU/GPU/内存/磁盘/运行中的任务）上报到 Bot 进度看板。
# 令牌：~/.config/grokbot-report/token（600，只用于这个上报接口，只能写服务器指标）
# 日志：~/.local/state/grokbot-report.log（自动截断）。失败安静退出，不影响别的任务。
# 想在看板上给自己的长任务起个名字：在 ~/.local/state/grokbot-jobs/ 放一个文件，内容一行 "PID 任务名"，任务结束后删掉即可。
set -u
URL="${GROKBOT_REPORT_URL:-https://YOUR_DOMAIN/api/server-push}"
HOSTLABEL="${1:-${GROKBOT_REPORT_HOST:-}}"
[ -n "$HOSTLABEL" ] || HOSTLABEL="$(tr -d ' \r\n' <"$HOME/.config/grokbot-report/host" 2>/dev/null)"
[ -n "$HOSTLABEL" ] || HOSTLABEL=server-1   # 主机 ID：参数 > 环境变量 > ~/.config/grokbot-report/host > 默认（看板实际以令牌对应的主机为准）
TOKF="$HOME/.config/grokbot-report/token"
LOG="$HOME/.local/state/grokbot-report.log"
mkdir -p "$HOME/.local/state" 2>/dev/null
log(){ printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*" >>"$LOG" 2>/dev/null; }
if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG" 2>/dev/null || echo 0)" -gt 200000 ]; then tail -n 300 "$LOG" >"$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"; fi
exec 9>"$HOME/.local/state/grokbot-report.lock" 2>/dev/null && flock -n 9 || { log "skip: previous run still active"; exit 0; }
TMP="$(mktemp "${TMPDIR:-/tmp}/grokbot-report.XXXXXX")" || exit 0
trap 'rm -f "$TMP"' EXIT
chmod 600 "$TMP"
GROKBOT_HOST="$HOSTLABEL" nice -n 10 /usr/bin/python3 - >"$TMP" 2>>"$LOG" <<'PY'
import os, re, json, time, subprocess, glob, pwd
def rd(p):
    try:
        with open(p) as f: return f.read()
    except Exception: return ""
def run(cmd, t=10):
    try: return subprocess.run(cmd, capture_output=True, text=True, timeout=t).stdout
    except Exception: return ""
HZ = os.sysconf("SC_CLK_TCK")
RED = re.compile(r'((?:api[_-]?key|token|secret|passw(?:or)?d|auth(?:orization)?|bearer)[^\s=:]*[=:\s]+)(\S+)', re.I)
def clean(s, n=180): s = RED.sub(r'\1***', s.replace("\0", " ").strip()); return s[:n] + ("…" if len(s) > n else "")
def cpu_tot():
    v = [int(x) for x in rd("/proc/stat").split("\n")[0].split()[1:]]
    return sum(v), v[3] + (v[4] if len(v) > 4 else 0)
def proc_times():
    out = {}
    for d in os.listdir("/proc"):
        if not d.isdigit(): continue
        s = rd(f"/proc/{d}/stat")
        if not s: continue
        try:
            f = s[s.rindex(")") + 2:].split()
            out[int(d)] = (int(f[11]) + int(f[12]), int(f[19]))
        except Exception: pass
    return out
t0, i0 = cpu_tot(); p0 = proc_times(); w0 = time.time()
time.sleep(1.0)
t1, i1 = cpu_tot(); p1 = proc_times(); dt = time.time() - w0
cpu_pct = round(100.0 * (1 - (i1 - i0) / max(1, t1 - t0)), 1)
up = float((rd("/proc/uptime").split() or ["0"])[0]); boot = time.time() - up
mi = {l.split(":")[0]: int(l.split()[1]) * 1024 for l in rd("/proc/meminfo").splitlines() if l.split()[1:] and l.split()[1].isdigit()}
mem_total = mi.get("MemTotal", 0); mem_av = mi.get("MemAvailable", 0)
st = os.statvfs("/")
model = next((l.split(":", 1)[1].strip() for l in rd("/proc/cpuinfo").splitlines() if l.startswith("model name")), "")
def pinfo(pid):
    try:
        st_ = os.stat(f"/proc/{pid}")
        user = pwd.getpwuid(st_.st_uid).pw_name
    except Exception: user = ""
    comm = rd(f"/proc/{pid}/comm").strip()
    cmd = clean(rd(f"/proc/{pid}/cmdline")) or f"[{comm}]"
    rss = 0
    for l in rd(f"/proc/{pid}/status").splitlines():
        if l.startswith("VmRSS:"): rss = int(l.split()[1]) * 1024
    el = None
    if pid in p1: el = int(up - p1[pid][1] / HZ)
    cpu = round(100.0 * (p1[pid][0] - p0[pid][0]) / HZ / dt, 1) if pid in p1 and pid in p0 else None
    return {"pid": pid, "user": user, "name": comm, "cmd": cmd, "rss": rss, "elapsed": el, "cpu": cpu}
gpus = []
for l in run(["nvidia-smi", "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit", "--format=csv,noheader,nounits"]).strip().splitlines():
    f = [x.strip() for x in l.split(",")]
    if len(f) < 8: continue
    n = lambda x: (float(x) if re.match(r'^-?[\d.]+$', x) else None)
    gpus.append({"index": int(n(f[0]) or 0), "name": f[1], "util": n(f[2]), "mem_used": n(f[3]), "mem_total": n(f[4]), "temp": n(f[5]), "power": n(f[6]), "power_limit": n(f[7])})
gpu_procs = []
for l in run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"]).strip().splitlines():
    f = [x.strip() for x in l.split(",")]
    if len(f) < 3 or not f[0].isdigit(): continue
    pi = pinfo(int(f[0]))
    gpu_procs.append({"pid": int(f[0]), "name": pi["name"] or os.path.basename(f[1]), "cmd": pi["cmd"], "mem": float(f[2]) if re.match(r"^[\d.]+$", f[2]) else None, "elapsed": pi["elapsed"], "user": pi["user"]})
me = os.getpid(); anc = set()
p = me
while p > 1:
    anc.add(p)
    try: p = int(rd(f"/proc/{p}/stat").rsplit(")", 1)[1].split()[1])
    except Exception: break
JOB = re.compile(r'python|paddle|ocr|torch|whisper|ffmpeg|ollama|vllm|llama|comfy|jupyter|node |java|cargo|make|gcc|rsync|wget|aria2|hf |huggingface|pip |conda|uv |train|infer', re.I)
SKIP = re.compile(r'gnome|gvfs|dbus|pipewire|wireplumber|xdg-|ibus|evolution|gsd-|at-spi|systemd|tracker|goa-|Xwayland|mutter|snapd|update-notifier|localsearch|FlClash|networkd-dispatcher|unattended-upgrade|firmware', re.I)
myuid = os.getuid(); top = []
for pid in p1:
    if pid in anc or pid not in p0: continue
    cpu = 100.0 * (p1[pid][0] - p0[pid][0]) / HZ / dt
    try: uid = os.stat(f"/proc/{pid}").st_uid
    except Exception: continue
    cmdline = rd(f"/proc/{pid}/cmdline").replace("\0", " ")
    isjob = uid == myuid and cmdline and JOB.search(cmdline) and not SKIP.search(cmdline)
    if cpu >= 5 or isjob:
        pi = pinfo(pid)
        if not isjob and pi["rss"] < 1 and cpu < 5: continue
        pi["job"] = bool(isjob); top.append(pi)
top.sort(key=lambda x: (-(x["cpu"] or 0), -x["rss"]))
top = top[:12]
sessions = []
if run(["sh", "-c", "command -v tmux"]).strip():
    for l in run(["tmux", "ls"]).splitlines():
        if ":" in l: sessions.append({"kind": "tmux", "name": l.split(":")[0], "info": clean(l.split(":", 1)[1], 80)})
for l in run(["screen", "-ls"]).splitlines():
    m = re.match(r'\s+(\d+\.\S+)\s+(.*)', l)
    if m: sessions.append({"kind": "screen", "name": m.group(1), "info": clean(m.group(2), 80)})
jobs = []
for fp in sorted(glob.glob(os.path.expanduser("~/.local/state/grokbot-jobs/*")))[:20]:
    for l in rd(fp).splitlines()[:5]:
        m = re.match(r'\s*(\d+)\s+(.+)', l)
        if not m: continue
        pid = int(m.group(1)); alive = os.path.exists(f"/proc/{pid}")
        pi = pinfo(pid) if alive else {}
        jobs.append({"pid": pid, "label": clean(m.group(2), 80), "alive": alive, "cmd": pi.get("cmd", ""), "elapsed": pi.get("elapsed"), "cpu": pi.get("cpu")})
# GB10 / Jetson 等统一内存机器：nvidia-smi 显存是 N/A，CPU 和 GPU 共用系统内存
unified = bool(gpus) and all(g["mem_total"] is None for g in gpus) or bool(re.search(r'GB10|Grace|Thor|Orin', " ".join(g["name"] for g in gpus)))
print(json.dumps({"v": 1, "arch": os.uname().machine, "unified_memory": unified, "host": os.environ.get("GROKBOT_HOST", "server-1"), "hostname": os.uname().nodename, "ts": int(time.time() * 1000),
    "cpu_model": model, "uptime": int(up),
    "cpu": {"pct": cpu_pct, "threads": os.cpu_count(), "load": [float(x) for x in rd("/proc/loadavg").split()[:3]]},
    "mem": {"total": mem_total, "used": mem_total - mem_av, "available": mem_av, "swap_total": mi.get("SwapTotal", 0), "swap_used": mi.get("SwapTotal", 0) - mi.get("SwapFree", 0)},
    "disk": {"mount": "/", "total": st.f_blocks * st.f_frsize, "used": (st.f_blocks - st.f_bfree) * st.f_frsize, "avail": st.f_bavail * st.f_frsize},
    "gpus": gpus, "gpu_procs": gpu_procs, "top": top, "sessions": sessions, "jobs": jobs}, ensure_ascii=False))
PY
[ -s "$TMP" ] || { log "error: collector produced no output"; exit 0; }
if [ "${GROKBOT_REPORT_DRY:-0}" = 1 ]; then cat "$TMP"; exit 0; fi
[ -r "$TOKF" ] || { log "error: token file missing"; exit 0; }
TOK="$(tr -d ' \r\n' <"$TOKF")"
if ! command -v curl >/dev/null 2>&1; then  # 没有 curl 的机器用 python 发送；令牌走 stdin
code=$(printf '%s' "$TOK" | /usr/bin/python3 -c '
import sys,urllib.request,time
tok=sys.stdin.read().strip();data=open(sys.argv[1],"rb").read()
for i in range(3):
  try:
    r=urllib.request.urlopen(urllib.request.Request(sys.argv[2],data=data,headers={"Authorization":"Bearer "+tok,"content-type":"application/json","user-agent":"grokbot-report"}),timeout=25);print(r.status);break
  except urllib.error.HTTPError as e: print(e.code);break
  except Exception: time.sleep(5)
else: print(0)' "$TMP" "$URL" 2>>"$LOG")
else
code=$(printf 'header = "Authorization: Bearer %s"\n' "$TOK" | curl -sS -K - -o /dev/null -w '%{http_code}' --max-time 25 --retry 2 --retry-delay 5 \
  -H 'content-type: application/json' --data-binary "@$TMP" "$URL" 2>>"$LOG")
fi
if [ "$code" = 200 ]; then log "ok $(wc -c <"$TMP")B"; else log "error: HTTP $code"; fi
exit 0
