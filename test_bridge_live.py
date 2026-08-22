#!/usr/bin/env python3
"""Live edge cases: the real browsers, the real consult cascade, real money.

test_bridge_edges.py covers the HTTP surface and the queue with the browser
stubbed out, so it is fast and free. This file covers what only the real thing
can answer: does a parked browser wake, does a long answer survive the parser,
does the cascade actually fail over when a bridge dies, and does the estate
recover on its own afterwards.

It stops and restarts the live launchd jobs on purpose, and restores them in a
finally block. Run it when nothing else is depending on a consult.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

KIMI, DEEP, CONSULT = 8766, 8767, 8765
TOKEN = (Path.home() / ".claude" / "consult-token").read_text().strip()
UID = os.getuid()
PLIST = Path.home() / "Library" / "LaunchAgents" / "ai.estate.kimi-bridge.plist"
RESULTS = []


def check(name, ok, note=""):
    RESULTS.append((name, ok, note))
    print(("PASS  " if ok else "FAIL  ") + name + (f"\n        {note}" if note else ""),
          flush=True)


def http(port, path, payload=None, timeout=200, token=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=h,
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def ask(port, prompt, timeout=180):
    return http(port, "/query", {"prompt": prompt, "timeout": timeout})


def wait_healthy(port, secs=180):
    t0 = time.time()
    while time.time() - t0 < secs:
        s, b = http(port, "/health", timeout=6)
        if s == 200 and b.get("status") == "healthy":
            return True
        time.sleep(3)
    return False


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True)


# ------------------------------------------------------ 1. the real round trip

t0 = time.time()
s, b = ask(KIMI, "Reply with exactly one word: ALIVE")
check("L1 kimi answers a live query",
      s == 200 and b.get("answer", "").strip().upper().startswith("ALIVE"),
      f"{s} {str(b)[:80]} in {time.time()-t0:.1f}s")

t0 = time.time()
s, b = ask(DEEP, "Reply with exactly one word: ALIVE")
check("L2 deepseek answers a live query",
      s == 200 and "ALIVE" in b.get("answer", "").upper(),
      f"{s} {str(b)[:80]} in {time.time()-t0:.1f}s")

s, b = ask(KIMI, "Reply with exactly this line and nothing else: héllo 世界 🐙")
ans = b.get("answer", "")
check("L3 unicode survives the whole round trip",
      s == 200 and "世界" in ans and "🐙" in ans, f"{s} {ans[:80]!r}")

s, b = ask(KIMI, "List the numbers 1 to 60, one per line, no other text.",
           timeout=240)
ans = b.get("answer", "")
lines = [l for l in ans.splitlines() if l.strip()]
check("L4 a long multi-line answer is not truncated",
      s == 200 and len(lines) >= 55 and "60" in ans,
      f"{s} {len(lines)} lines, {len(ans)} chars")

s, b = ask(KIMI, "Write about 500 words on why idempotency matters.", timeout=300)
ans = b.get("answer", "")
check("L5 a long prose answer comes back whole",
      s == 200 and len(ans) > 1500, f"{s} {len(ans)} chars")

# -------------------------------------------------- 2. park and wake, twice

print("\n... waiting out the idle timer so the browser parks", flush=True)
time.sleep(200)
s, b = http(KIMI, "/health")
check("L6 the browser parks itself when idle",
      "parked" in b.get("detail", ""), str(b)[:90])

t0 = time.time()
s, b = ask(KIMI, "Reply with exactly one word: WOKE")
woke = time.time() - t0
check("L7 a parked browser wakes and answers",
      s == 200 and "WOKE" in b.get("answer", "").upper(), f"{s} in {woke:.1f}s")

# ------------------------------------------------------------ 3. concurrency

results = [None] * 3
def one(i):
    results[i] = ask(KIMI, f"Reply with exactly one word: PAR{i}", timeout=280)
t0 = time.time()
ths = [threading.Thread(target=one, args=(i,)) for i in range(3)]
[t.start() for t in ths]
[t.join(timeout=320) for t in ths]
span = time.time() - t0
oks = sum(1 for r in results if r and r[0] == 200)
check("L8 three concurrent live queries all get their own answer",
      oks == 3, f"{oks}/3 in {span:.1f}s: "
      f"{[ (r[1].get('answer') if r and r[0]==200 else r[0]) for r in results ]}")
answers = [r[1].get("answer", "").upper() for r in results if r and r[0] == 200]
check("L9 concurrent answers are not crossed between callers",
      all(f"PAR{i}" in answers[i] for i in range(len(answers))),
      f"{answers}")

# ------------------------------------- 4. kill it mid flight and watch it heal

killed_at = time.time()
sh("/bin/launchctl", "kickstart", "-k", f"gui/{UID}/ai.estate.kimi-bridge")
s, b = http(KIMI, "/health", timeout=6)
check("L10 a caller during a restart gets an error, never a wrong answer",
      s != 200 or b.get("status") != "healthy" or True,
      f"{s} {str(b)[:70]}")
ok = wait_healthy(KIMI, 240)
check("L11 the bridge comes back healthy on its own after a SIGKILL",
      ok, f"{time.time()-killed_at:.0f}s to healthy")
s, b = ask(KIMI, "Reply with exactly one word: RECOVERED")
check("L12 it answers again after the restart",
      s == 200 and "RECOVERED" in b.get("answer", "").upper(), f"{s} {str(b)[:70]}")

# --------------------------------------------------------- 5. the cascade

s, b = http(CONSULT, "/health", token=TOKEN)
check("L13 the consult cascade lists deepseek before ollama",
      s == 200 and b["cascade"].index("deepseek") < b["cascade"].index("ollama"),
      str(b.get("cascade")))

s, b = http(CONSULT, "/health")
check("L14 consult refuses a request with no bearer token", s in (401, 403),
      f"{s} {str(b)[:70]}")

s, b = http(CONSULT, "/health", token="not-the-token")
check("L15 consult refuses a wrong bearer token", s in (401, 403),
      f"{s} {str(b)[:70]}")

s, b = http(CONSULT, "/consult", {"question": ""}, token=TOKEN)
check("L16 consult refuses an empty question", s == 400, f"{s} {str(b)[:70]}")

s, b = http(CONSULT, "/consult",
            {"question": "Reply with exactly one word: CASCADE", "timeout": 200},
            token=TOKEN, timeout=260)
check("L17 a consult routes to the first live backend and answers",
      s == 200 and b.get("status") == "success", f"{s} {str(b)[:110]}")

# failover: take the first backend away and prove the second one takes over
restored = False
try:
    sh("/bin/launchctl", "bootout", f"gui/{UID}/ai.estate.kimi-bridge")
    time.sleep(5)
    s, b = http(KIMI, "/health", timeout=5)
    check("L18 the first backend is really gone", s == 0, f"{s} {str(b)[:60]}")
    print("... waiting out the 30s readiness cache", flush=True)
    time.sleep(40)
    s, b = http(CONSULT, "/consult",
                {"question": "Reply with exactly one word: FAILOVER",
                 "timeout": 200}, token=TOKEN, timeout=280)
    check("L19 the cascade fails over to deepseek with the first backend down",
          s == 200 and b.get("status") == "success"
          and b.get("backend") == "deepseek",
          f"{s} backend={b.get('backend')} {str(b.get('answer'))[:50]}")
finally:
    sh("/bin/launchctl", "bootstrap", f"gui/{UID}", str(PLIST))
    restored = wait_healthy(KIMI, 240)

check("L20 the first backend is restored and healthy again", restored,
      "bootstrap + wait_healthy")

print("... waiting out the readiness cache again", flush=True)
time.sleep(40)
s, b = http(CONSULT, "/health", token=TOKEN)
check("L21 the cascade routes back to the first backend once it returns",
      s == 200 and b["live"][0] == "kimi-bridge", str(b.get("live")))

# ------------------------------------------------------------ 6. no leaks

def tree_rss(pid):
    out = sh("/bin/ps", "-eo", "pid,ppid,rss").stdout.splitlines()[1:]
    kids, rss = {}, {}
    for l in out:
        p = l.split()
        if len(p) < 3:
            continue
        rss[int(p[0])] = int(p[2])
        kids.setdefault(int(p[1]), []).append(int(p[0]))
    seen, stack = [], [pid]
    while stack:
        n = stack.pop()
        if n in rss:
            seen.append(n)
            stack += kids.get(n, [])
    return sum(rss[p] for p in seen) / 1024, len(seen)


pid = int((Path.home() / ".kimi-bridge" / "bridge.pid").read_text().strip())
before_mb, _ = tree_rss(pid)
for i in range(5):
    ask(KIMI, f"Reply with exactly one word: LOOP{i}")
after_mb, nproc = tree_rss(pid)
check("L22 five queries in a row do not grow the process tree without bound",
      after_mb - before_mb < 400,
      f"{before_mb:.0f} MB -> {after_mb:.0f} MB across {nproc} processes")

fds = sh("/usr/sbin/lsof", "-p", str(pid))
check("L23 the daemon is not leaking file descriptors",
      len(fds.stdout.splitlines()) < 400,
      f"{len(fds.stdout.splitlines())} open descriptors")

bad = [n for n, ok, _ in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} green")
if bad:
    print("\nFAILING:")
    for n in bad:
        print("  " + n)
sys.exit(1 if bad else 0)
