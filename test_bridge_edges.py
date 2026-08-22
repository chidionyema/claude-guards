#!/usr/bin/env python3
"""Exhaustive edge case harness for the bridge HTTP surface and job queue.

Runs the real Handler and the real worker loop against a STUBBED browser, so
every case is deterministic, costs no model calls, and finishes in seconds.
The live behaviour of the browser itself is covered by test_bridge_live.py.

Founder, 2026-08-22: "this is a crucial tool for our agents, don't want it
breaking". This file is the list of ways it could.

Each case prints PASS or FAIL and, where the current behaviour is wrong, says
what it should be instead. A FAIL here is a bug to fix, not a test to relax.
"""
import http.client
import json
import os
import queue
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="edge-test-"))
PORT = 8794
os.environ.update({"BRIDGE_HOME": str(HOME), "BRIDGE_PORT": str(PORT),
                   "BRIDGE_TIMEOUT": "300"})
sys.path.insert(0, str(Path.home() / ".claude" / "scripts"))
import kimi_bridge as kb  # noqa: E402

RESULTS = []


def check(name, ok, note=""):
    RESULTS.append((name, ok, note))
    print(("PASS  " if ok else "FAIL  ") + name + (f"\n        {note}" if note else ""))


# ------------------------------------------------------------------ the stub

class StubBridge(kb.Bridge):
    """The real Bridge with the browser taken out.

    It subclasses rather than reimplements on purpose. The queue loop, the
    drop rule, the park clock and the error path are the code under test, so a
    stub that reimplemented run() would test the stub. Only the four methods
    that actually drive Chromium are replaced.
    """

    def __init__(self):
        super().__init__(headed=False)
        self.asked = []
        self.delay = 0.0
        self.raise_with = None
        self.state = "healthy"
        self.detail = "stub"
        self.page = object()

    # the browser, replaced
    def start(self):
        self.state, self.detail, self.page = "healthy", "stub", object()

    def stop(self):
        self.page = None

    def park(self):
        self.page = None

    def restart(self):
        self.start()

    def refresh_health(self):
        return self.state

    def _ensure(self):
        if self.page is None:
            self.start()

    def ask(self, prompt, timeout, deadline=None):
        self.asked.append((prompt, timeout, time.time()))
        if self.delay:
            time.sleep(self.delay)
        if self.raise_with:
            raise self.raise_with
        return f"echo:{prompt[:40]}"


STUB = StubBridge()
kb.BRIDGE = STUB
threading.Thread(target=STUB.run, daemon=True).start()  # the REAL run loop
SRV = kb.ThreadingHTTPServer(("127.0.0.1", PORT), kb.Handler)
threading.Thread(target=SRV.serve_forever, daemon=True).start()
time.sleep(0.4)


def raw(method, path, body=None, headers=None, timeout=20, content_length=None):
    """One request, returning (status, text). Bypasses json so malformed
    bodies and lying headers can be sent on purpose."""
    c = http.client.HTTPConnection("127.0.0.1", PORT, timeout=timeout)
    h = dict(headers or {})
    data = body.encode() if isinstance(body, str) else body
    if content_length is not None:
        h["Content-Length"] = str(content_length)
    try:
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        return r.status, r.read().decode("utf-8", "replace")
    except http.client.RemoteDisconnected:
        # An exception inside the handler kills the connection with no reply.
        # 599 is not an HTTP code; it is this harness saying "no answer at all",
        # which is strictly worse for a caller than any error status.
        return 599, "connection closed with no response"
    finally:
        c.close()


def post(payload, timeout=20):
    return raw("POST", "/query", json.dumps(payload),
               {"Content-Type": "application/json"}, timeout)


# ------------------------------------------------------- 1. protocol surface

s, b = raw("GET", "/health")
check("1  GET /health returns 200 json", s == 200 and "status" in b, b[:80])

s, b = raw("GET", "/nope")
check("2  GET an unknown path is refused", s in (404, 400, 405), f"{s} {b[:60]}")

s, b = raw("POST", "/nope", "{}", {"Content-Type": "application/json"})
check("3  POST an unknown path is refused", s in (404, 400, 405), f"{s} {b[:60]}")

s, b = raw("GET", "/query")
check("4  GET /query is refused, not treated as a query", s in (404, 400, 405),
      f"{s} {b[:60]}")

s, b = post({"prompt": "hello"})
check("5  a normal query answers 200", s == 200 and json.loads(b)["success"],
      b[:80])

s, b = raw("POST", "/query", "{not json", {"Content-Type": "application/json"})
check("6  malformed json is a 400, not a crash", s == 400, f"{s} {b[:60]}")

s, b = raw("POST", "/query", "", {"Content-Type": "application/json"})
check("7  an empty body is a 400", s == 400, f"{s} {b[:60]}")

s, b = post({})
check("8  a missing prompt is a 400", s == 400, f"{s} {b[:60]}")

s, b = post({"prompt": "   \n\t  "})
check("9  a whitespace-only prompt is a 400", s == 400, f"{s} {b[:60]}")

s, b = post({"prompt": None})
check("10 a null prompt is a 400", s == 400, f"{s} {b[:60]}")

s, b = post({"prompt": 12345})
check("11 a non-string prompt is refused, not coerced", s == 400,
      f"{s} {b[:60]}  should be 400; .strip() on an int raises 500")

s, b = post({"prompt": "ok", "timeout": "abc"})
check("12 a non-numeric timeout is a 400, not a 500",
      s == 400, f"{s} {b[:80]}  int('abc') must not escape the handler")

s, b = post({"prompt": "ok", "timeout": -5})
check("13 a negative timeout is refused or clamped", s in (200, 400),
      f"{s} {b[:60]}")

s, b = post({"prompt": "ok", "timeout": 10**9})
check("14 an absurd timeout is clamped, not honoured", s in (200, 400),
      f"{s} {b[:60]}")

s, b = post({"prompt": "ok", "timeout": 1.5})
check("15 a float timeout does not crash", s in (200, 400), f"{s} {b[:60]}")

# unicode, control characters, quoting
for name, p in (("16 unicode and emoji round trip", "héllo 世界 🐙"),
                ("17 newlines and quotes round trip", 'a\nb "c" \\d\t e'),
                ("18 a json-breaking payload round trips", '}{"success":false}')):
    s, b = post({"prompt": p})
    ok = s == 200 and json.loads(b)["success"]
    check(name, ok, f"{s} {b[:60]}")

big = "x" * 200_000
s, b = post({"prompt": big})
check("19 a 200KB prompt is handled or refused, never a crash",
      s in (200, 400, 413), f"{s} {b[:60]}")

s, b = raw("POST", "/query", '{"prompt":"ok"}',
           {"Content-Type": "text/plain"})
check("20 the wrong content-type still parses the body", s in (200, 400),
      f"{s} {b[:60]}")

# ------------------------------------------------- 2. lying content-length

t0 = time.time()
try:
    st, bd = raw("POST", "/query", '{"prompt":"ok"}',
                 {"Content-Type": "application/json"}, timeout=40,
                 content_length=999999)
    took = time.time() - t0
    note = f"{st} {bd[:50]} after {took:.1f}s"
except (socket.timeout, TimeoutError, http.client.HTTPException, OSError) as e:
    took = time.time() - t0
    note = f"{type(e).__name__} after {took:.1f}s"
check("21 a content-length larger than the body is given up on, not held for ever",
      took < kb.READ_TIMEOUT + 5, note)

# --------------------------------------------------------- 3. worker errors

STUB.raise_with = RuntimeError("browser exploded")
s, b = post({"prompt": "ok"})
STUB.raise_with = None
j = json.loads(b)
check("22 a worker exception becomes a clean 502, not a hang",
      s == 502 and j.get("success") is False and "exploded" in j.get("error", ""),
      f"{s} {b[:80]}")

s, b = post({"prompt": "ok"})
check("23 the bridge still answers after a worker exception",
      s == 200 and json.loads(b)["success"], f"{s} {b[:60]}")

check("24 the reply names which bridge answered",
      json.loads(b).get("backend") == kb.NAME,
      f"backend={json.loads(b).get('backend')} NAME={kb.NAME}")

# --------------------------------------------- 4. timeout and abandoned work

# The caller asks for MIN_TIMEOUT and the worker takes far longer. The reply
# must land near the caller's own deadline plus GRACE, not at deadline+40.
STUB.delay = 30.0
t0 = time.time()
s, b = post({"prompt": "slow", "timeout": kb.MIN_TIMEOUT}, timeout=90)
waited = time.time() - t0
STUB.delay = 0.0
check("25 a client timeout returns 504 near its own deadline, not deadline+40",
      s == 504 and waited < kb.MIN_TIMEOUT + kb.GRACE + 3,
      f"status {s} after {waited:.1f}s; the caller asked for "
      f"{kb.MIN_TIMEOUT}s and GRACE is {kb.GRACE}s")
time.sleep(31)   # let the blocked stub finish before the next case

# A job whose deadline passes while it is still QUEUED must never start. An
# answer nobody is waiting for is a paid model call thrown away, and while it
# runs it blocks every job behind it. A job already in flight cannot be
# cancelled safely, and this does not pretend to.
before = len(STUB.asked)
STUB.delay = 12.0
threading.Thread(target=lambda: post({"prompt": "blocker", "timeout": 60},
                                     timeout=90), daemon=True).start()
time.sleep(1.0)
victim = {}
threading.Thread(
    target=lambda: victim.update(zip(("s", "b"),
                                     post({"prompt": "victim",
                                           "timeout": kb.MIN_TIMEOUT},
                                          timeout=90))), daemon=True).start()
time.sleep(14)
STUB.delay = 0.0
ran = [p for p, _, _ in STUB.asked[before:]]
check("26 a job whose deadline passed while queued is dropped, not executed",
      "victim" not in ran,
      f"the worker ran {ran}; victim's deadline passed while it waited behind "
      f"blocker")
check("26b the dropped caller is told why",
      victim.get("s") in (502, 504) and
      ("dropped" in (victim.get("b") or "") or victim.get("s") == 504),
      f"{victim.get('s')} {(victim.get('b') or '')[:70]}")

# ------------------------------------------------------------ 5. concurrency

STUB.delay = 1.0
N = 8
out = [None] * N
def one(i):
    try:
        out[i] = post({"prompt": f"c{i}", "timeout": 120}, timeout=90)
    except Exception as e:
        out[i] = ("EXC", f"{type(e).__name__}: {e}")
t0 = time.time()
ths = [threading.Thread(target=one, args=(i,)) for i in range(N)]
[t.start() for t in ths]
[t.join(timeout=120) for t in ths]
span = time.time() - t0
STUB.delay = 0.0
oks = sum(1 for r in out if r and r[0] == 200)
check(f"27 {N} concurrent queries all get an answer",
      oks == N, f"{oks}/{N} ok in {span:.1f}s, results {[r[0] for r in out]}")
check("28 concurrent queries are serialised by the single worker",
      span >= N * 0.9,
      f"{span:.1f}s for {N} jobs at 1.0s each; one browser, one queue, so "
      f"they queue. This is by design but it is the head-of-line risk.")

check("29 the job queue is bounded so a flood cannot grow it without limit",
      getattr(STUB.jobs, "maxsize", 0) > 0 or
      getattr(kb, "QUEUE_MAX", 0) > 0,
      "queue.Queue() has maxsize 0, which means unbounded; a caller loop that "
      "never stops will queue forever and every entry waits behind the rest")

# ----------------------------------------------------------- 6. health shape

s, b = raw("GET", "/health")
h = json.loads(b)
check("30 health carries status, detail, last_healthy and target",
      {"status", "detail", "last_healthy", "target"} <= set(h), str(h)[:100])

s, b = raw("POST", "/health", "{}", {"Content-Type": "application/json"})
check("31 POST /health is refused", s in (404, 400, 405), f"{s} {b[:60]}")

# ---------------------------------------------------- 7. limits and refusals

s, b = post({"prompt": "x" * (kb.MAX_PROMPT + 1)})
check("32 a prompt over the cap is a clean 413", s == 413, f"{s} {b[:60]}")

s, b = raw("POST", "/query", "{}", {"Content-Type": "application/json"},
           content_length=kb.MAX_BODY + 1)
check("33 a body over the cap is refused without reading it", s == 413,
      f"{s} {b[:60]}")

s, b = post([1, 2, 3])
check("34 a json array body is a 400, not a 500", s == 400, f"{s} {b[:60]}")

s, b = raw("POST", "/query", '{"prompt":"ok"}',
           {"Content-Type": "application/json", "Content-Length": "abc"})
check("35 a non-numeric content-length is refused", s in (400, 599),
      f"{s} {b[:60]}")

# queue full: block the worker, then overfill
STUB.delay = 6.0
fillers = [threading.Thread(
    target=lambda: post({"prompt": "fill", "timeout": 30}, timeout=60),
    daemon=True) for _ in range(kb.QUEUE_MAX + 2)]
[t.start() for t in fillers]
time.sleep(1.0)
s, b = post({"prompt": "one too many", "timeout": 30}, timeout=60)
STUB.delay = 0.0
check("36 a flood is told the bridge is busy, not queued without limit",
      s == 503 and "busy" in b, f"{s} {b[:70]}")
for t in fillers:
    t.join(timeout=90)
time.sleep(1.0)

# a handler that raises must still answer
_real_put = STUB.jobs.put_nowait
STUB.jobs.put_nowait = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
s, b = post({"prompt": "ok"})
STUB.jobs.put_nowait = _real_put
check("37 an unhandled handler error is a 500 with a body, not a dropped socket",
      s == 500 and "internal error" in b, f"{s} {b[:70]}")

s, b = post({"prompt": "still here"})
check("38 the bridge still answers after a handler error",
      s == 200 and json.loads(b)["success"], f"{s} {b[:60]}")

# ------------------------------------------------------------------- verdict

SRV.shutdown()
STUB.jobs.put(None)
bad = [n for n, ok, _ in RESULTS if not ok]
print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} green")
if bad:
    print("\nFAILING:")
    for n in bad:
        print("  " + n)
sys.exit(1 if bad else 0)
