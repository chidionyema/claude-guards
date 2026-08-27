#!/usr/bin/env python3
"""estate_downshift.py — the money rail the sentinel could not be.

WHY THIS EXISTS
---------------
`estate_cost_sentinel.py` measures the whole estate and can only stop the daemon. Measured
2026-08-22: it watched $429.04 and its halt reaches $0.13 of it — 0.03% — and that halt is
disarmed. Its author was right to refuse the obvious fix. From estate_cost_sentinel.py:143:
"killing you mid-sentence would be worse than the spend", and "a rail keyed to a number it
cannot influence is not a rail".

So this rail does not kill anything. It makes the NEXT session cheaper.

    ~/.claude/settings.json is read once at process start.

That is normally an annoyance (a model change needs a relaunch). Here it is the whole design:
rewriting the model key cannot interrupt a running session, and every session started after
the threshold begins on the cheaper tier. The brake is real and it is never violent.

WHAT IT REACHES
---------------
Measured 2026-08-22, the day this was written:

    by_model    opus-5 $428.91 (99.97%)   haiku-4-5 $0.13
    by_driver   cache_read $221.89 (51.7%)  cache_write $122.79 (28.6%)
                output $84.32 (19.7%)       raw_input $0.04 (0.0%)
    context     443.8M cache-read tokens / 3,913 requests = 113,412 tokens per request

Model choice multiplies all four driver rows at once, which is why it is the lever. opus-5 is
$5/$25 per MTok; sonnet-5 is $3/$15. Every token of that 113K average context costs 40% less
on the next tier down, before anyone writes a shorter prompt.

Context length is the bigger prize and this rail does not touch it. Cutting the average
context in half would save more than downshifting does. That is a discipline problem, not a
mechanism problem, and a script cannot fix it. This one buys time while that gets fixed.

POLICY IS CONFIG, NEVER CODE
----------------------------
Thresholds live in ~/.claude/estate-budget.json beside the sentinel's own, same as
estate_cost_sentinel.py:22 argues. Ships DISARMED: downshift_usd 0 changes nothing, ever.

    "downshift_usd":   0,            0 disables. e.g. 250 = downshift past $250/day
    "downshift_model": "sonnet",     what new sessions start on once tripped
    "restore_model":   null          filled in automatically; --restore puts it back

SAFETY
------
settings.json configures every session on this machine, so a corrupt write is worse than any
overspend. Every write is: serialise -> re-parse the serialised text -> write a temp file in
the same directory -> os.replace. A timestamped backup is taken before the first change. If
anything raises, the original file was never touched.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import estate_spend  # noqa: E402

SETTINGS = os.path.expanduser("~/.claude/settings.json")
from budget_path import budget_path  # crew#91
CONFIG = budget_path()
BACKUPS = os.path.expanduser("~/.claude/settings-backups")

DEFAULTS = {"downshift_usd": 0.0, "downshift_model": "sonnet", "restore_model": None}


def load_cfg() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG) as fh:
            cfg.update({k: v for k, v in json.load(fh).items() if not k.startswith("_")})
    except (OSError, json.JSONDecodeError):
        pass
    return cfg


def save_cfg(updates: dict) -> None:
    """Merge keys into the budget file, preserving comments and the sentinel's own keys."""
    try:
        with open(CONFIG) as fh:
            cur = json.load(fh)
    except (OSError, json.JSONDecodeError):
        cur = {}
    cur.update(updates)
    atomic_write_json(CONFIG, cur)


def atomic_write_json(path: str, obj: dict) -> None:
    """Serialise, re-parse to prove it is valid, then swap in one syscall."""
    text = json.dumps(obj, indent=2) + "\n"
    json.loads(text)  # a corrupt settings.json breaks every session; refuse to write one
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w") as fh:
        fh.write(text)
    os.replace(tmp, path)


def read_settings() -> dict:
    with open(SETTINGS) as fh:
        return json.load(fh)


def backup_settings() -> str:
    os.makedirs(BACKUPS, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    dest = os.path.join(BACKUPS, f"settings.{stamp}.json")
    shutil.copy2(SETTINGS, dest)
    return dest


def set_model(new: str, dry_run: bool) -> tuple[str, str]:
    s = read_settings()
    old = s.get("model", "(unset)")
    if old == new:
        return old, "unchanged"
    if dry_run:
        return old, f"DRY RUN — would set model {old!r} -> {new!r}"
    backup_settings()
    s["model"] = new
    atomic_write_json(SETTINGS, s)
    return old, f"model {old!r} -> {new!r}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="report and show what WOULD change")
    ap.add_argument("--status", action="store_true", help="print state and exit 0, change nothing")
    ap.add_argument("--restore", action="store_true", help="put the recorded model back, arm again")
    ap.add_argument("--day", default=dt.date.today().isoformat())
    args = ap.parse_args()

    cfg = load_cfg()
    thresh = float(cfg.get("downshift_usd") or 0.0)
    target = cfg.get("downshift_model") or "sonnet"
    saved = cfg.get("restore_model")
    live = read_settings().get("model", "(unset)")

    if args.status:
        print(f"settings.json model : {live}")
        print(f"threshold           : "
              + (f"${thresh:,.2f}/day" if thresh else "0 — DISARMED, this rail changes nothing"))
        print(f"downshift target    : {target}")
        print(f"tripped             : {'yes, saved ' + repr(saved) if saved else 'no'}")
        res = estate_spend.scan(args.day)
        print(f"spend {args.day}    : ${res['total']:,.2f} ({res['requests']:,} requests)")
        return 0

    if args.restore:
        if not saved:
            print("not tripped — nothing to restore")
            return 0
        _, what = set_model(saved, args.dry_run)
        print(f"restore: {what}")
        if not args.dry_run:
            save_cfg({"restore_model": None})
        return 0

    if not thresh:
        print("downshift_usd is 0 — DISARMED. Nothing to do.")
        print(f"To arm:  edit {CONFIG}, set downshift_usd to a number.")
        return 0

    res = estate_spend.scan(args.day)
    total = res["total"]
    print(f"spend {args.day}: ${total:,.2f} of ${thresh:,.2f} downshift threshold")

    if total < thresh:
        print(f"under threshold — model stays {live!r}")
        return 0
    if saved:
        print(f"already downshifted to {live!r} (saved {saved!r}) — nothing to do")
        return 0

    old, what = set_model(target, args.dry_run)
    print(f"OVER THRESHOLD: {what}")
    print("running sessions are untouched; the next one launched starts on the cheaper tier")
    if not args.dry_run and old != target:
        save_cfg({"restore_model": old})
    return 0


if __name__ == "__main__":
    sys.exit(main())
