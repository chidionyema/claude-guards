#!/usr/bin/env python3
"""One command that runs every guard's own selftest and says PASS or FAIL out loud.

    estate-selftest.py            run everything, print the board
    estate-selftest.py --json     machine output
    estate-selftest.py --quiet    only print if something failed (for launchd)

Exit code is 0 only when nothing failed. Anything red exits 1 so a scheduler,
a CI job or a hook can act on it without reading the text.
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, json, os, pathlib, re, subprocess, sys, time

HOME = pathlib.Path.home()
ROOT = HOME / ".claude/scripts"
STATE = HOME / ".claude/state/estate-selftest.json"
PY3 = sys.executable or "python3"
TIMEOUT = 45.0

G, R, Y, D, B, X = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    G = R = Y = D = B = X = ""


def discover() -> list[pathlib.Path]:
    seen, out = set(), []
    for p in sorted(ROOT.glob("*.py")) + sorted(ROOT.glob("*/*.py")):
        if p.name.startswith("test_") or p.resolve() in seen:
            continue
        seen.add(p.resolve())
        out.append(p)
    return out


def wired_hooks() -> set[str]:
    try:
        d = json.loads((HOME / ".claude/settings.json").read_text())
    except Exception:
        return set()
    return {h.get("command", "").split("/")[-1]
            for arr in d.get("hooks", {}).values() for g in arr for h in g.get("hooks", [])}


def run_one(p: pathlib.Path) -> dict:
    rel = p.relative_to(ROOT).as_posix()
    try:
        src = p.read_text(errors="replace")
    except Exception as exc:
        return {"name": rel, "status": "UNREADABLE", "detail": repr(exc), "secs": 0.0}
    if "--selftest" not in src:
        return {"name": rel, "status": "NO SELFTEST", "detail": "", "secs": 0.0}
    t0 = time.monotonic()
    try:
        r = subprocess.run([PY3, str(p), "--selftest"], capture_output=True,
                           text=True, timeout=TIMEOUT, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        return {"name": rel, "status": "TIMEOUT", "detail": f"no exit in {TIMEOUT:.0f}s",
                "secs": time.monotonic() - t0}
    secs = time.monotonic() - t0
    blob = (r.stderr or "") + (r.stdout or "")
    if "unrecognized arguments: --selftest" in blob:
        return {"name": rel, "status": "NO SELFTEST", "detail": "mentions the flag, does not accept it", "secs": secs}
    if "ModuleNotFoundError" in blob:
        mod = re.search(r"No module named '([^']+)'", blob)
        return {"name": rel, "status": "MISSING DEP", "detail": f"needs {mod.group(1)}" if mod else blob.strip()[-100:], "secs": secs}
    if r.returncode == 0:
        tail = [ln for ln in r.stdout.strip().splitlines() if ln.strip()]
        return {"name": rel, "status": "PASS", "detail": tail[-1][:80] if tail else "", "secs": secs}
    err = (r.stderr or r.stdout).strip().splitlines()
    return {"name": rel, "status": "FAIL", "detail": (err[-1][:120] if err else f"rc={r.returncode}"),
            "secs": secs}


def _alert(bad: list[dict], payload: dict) -> None:
    """Say it out loud. An alert that fails to arrive is worse than no alert (LAW 28)."""
    sys.path.insert(0, str(ROOT / "estate"))
    lines = [f"GUARD SELFTEST RED: {len(bad)} failing of {payload['pass'] + len(bad)}"]
    lines += [f"  {r['status']} {r['name']} — {r['detail']}" for r in bad[:8]]
    lines.append(f"  run: estate-selftest")
    try:
        import estate_alert
        ok = estate_alert.send_operator_alert("\n".join(lines),
                                              debounce_key="guard-selftest", debounce_s=3600.0)
        print(f"  alert delivered={ok}")
    except Exception as exc:                                       # noqa: BLE001
        print(f"  {R}alert FAILED to send: {exc!r}{X}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="print only on failure")
    ap.add_argument("--alert", action="store_true", help="send a Telegram alert when something fails")
    ap.add_argument("--selftest", action="store_true", help="prove this script itself works")
    a = ap.parse_args()

    if a.selftest:
        ok = discover()
        assert ok, "discover() found no scripts"
        assert all(p.suffix == ".py" for p in ok)
        probe = run_one(ROOT / "jargon-guard.py")
        assert probe["status"] in ("PASS", "FAIL", "NO SELFTEST"), probe
        print(f"selftest OK: {len(ok)} scripts discoverable, runner returns {probe['status']}")
        return 0

    files = discover()
    wired = wired_hooks()
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(run_one, files))
    rows.sort(key=lambda r: ({"FAIL": 0, "TIMEOUT": 0, "UNREADABLE": 0,
                              "MISSING DEP": 1, "NO SELFTEST": 2, "PASS": 3}[r["status"]], r["name"]))
    for r in rows:
        r["wired"] = r["name"].split("/")[-1] in wired

    bad = [r for r in rows if r["status"] in ("FAIL", "TIMEOUT", "UNREADABLE")]
    dep = [r for r in rows if r["status"] == "MISSING DEP"]
    gap = [r for r in rows if r["status"] == "NO SELFTEST"]
    good = [r for r in rows if r["status"] == "PASS"]
    payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "elapsed_s": round(time.time() - t0, 1),
               "pass": len(good), "fail": len(bad), "no_selftest": len(gap), "missing_dep": len(dep),
               "wired": sum(r["wired"] for r in rows), "rows": rows}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(payload, indent=1) + "\n")

    if a.json:
        print(json.dumps(payload, indent=1))
        return 1 if bad else 0
    if a.quiet and not bad:
        return 0
    alerted = False
    if a.quiet and bad and a.alert:
        _alert(bad, payload); alerted = True

    banner = f"{R}{B}  {len(bad)} GUARD(S) FAILING  {X}" if bad else f"{G}{B}  ALL GUARDS PASS  {X}"
    print(f"\n{'=' * 64}\n{banner}   {len(good)} pass · {len(bad)} fail · "
          f"{len(gap)} untested · {payload['wired']} switched on\n{'=' * 64}")
    for r in bad + dep:
        col = R if r in bad else Y
        print(f"  {col}{r['status']:<11}{X} {r['name']:<30} {D}{r['detail']}{X}")
    if bad or dep:
        print()
    for r in good:
        print(f"  {G}pass{X}        {r['name']:<30} {D}{r['secs']:4.1f}s "
              f"{'[ON]' if r['wired'] else '':4} {r['detail']}{X}")
    if gap:
        print(f"\n  {Y}no selftest{X} ({len(gap)}): {D}{', '.join(r['name'] for r in gap)}{X}")
    print(f"\n  state: {STATE}   took {payload['elapsed_s']}s\n")
    if a.alert and bad and not alerted:
        _alert(bad, payload)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
