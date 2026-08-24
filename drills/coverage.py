#!/usr/bin/env python3
"""Join every asset this estate owns to the drill that proves it comes back.

WHY THIS EXISTS. On 2026-08-24 the founder asked whether the Kimi bridge and
Aiden were under drill. The honest answer took four commands and came out
different for each of them, and the reason was not that somebody had been lazy.
It was that nothing on this machine could answer the question at all. Three
instruments each held a third of it:

    .estate/scripts/inventory.py    knows every asset -- 194 rows, 6 kinds
    drills/audit.py                 knows the rule -- covered_by or dismissed,
                                    no third state, unclassified is red
    drills/register.json            knows which recovery paths have been proved

Nobody applied the rule to the list. 194 assets, 13 drills, zero joins. So the
estate could say "this drill passed" and could say "this job exists" and could
never say "losing this job has been rehearsed". That is this file.

THE THING THAT WAS ACTUALLY WRONG. Asking "is it drilled" as one question is
what produced the confusion, because it hides three different questions that
have three different answers:

    restart   it stops, and it comes back on this machine
    rebuild   this machine dies, and it comes back on a new one
    replace   the vendor behind it is gone, and the estate still works

Aiden has restart and neither of the others. The Kimi bridge has restart and
replace but not rebuild. Graded as one question both look covered, because
recovery-posture passes and it grades every job on this Mac. Graded as three,
the holes are obvious and each names the drill that would close it.

Which slots apply is a property of the kind. A ledger does not restart. A repo
does not restart. A drill is not an asset to be drilled. SLOTS below is the
whole of that judgement and it is deliberately short.

THE RULE, WHICH IS AUDIT.PY'S AND IS NOT NEW. Every slot on every asset is
exactly one of:

    covered_by: <drill id>    a drill on the register rehearses this
    dismissed:  <reason>      a person decided losing it cannot stop us

There is no third state. Unclassified is red. That rule is already gating pull
requests on four repositories for hosts and credentials, it has been shown not
to rot, and the only thing changed here is what it is pointed at.

WHAT IT DOES NOT DO. It does not decide whether a dismissal is honest, and it
does not check that a drill named in covered_by actually exercises that asset.
A drill that passes while touching nothing still reads as coverage here. What
it closes is the gap where an asset arrives and nobody ever decides what
happens when it goes, which is the gap Aiden was sitting in.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
COVERAGE = os.path.join(HERE, "coverage.json")
REGISTER = os.path.join(HERE, "register.json")
INVENTORY = os.environ.get(
    "ESTATE_INVENTORY", os.path.join(HOME, ".estate", "state", "inventory.json"))

# How old the asset list may be before its answers stop counting. The inventory
# job runs daily, so two days means it has missed a run and the estate has had a
# day to grow an asset this file cannot see. A coverage report built on a stale
# list is the worst output here: it reads green about assets that no longer
# exist and silent about ones that arrived.
INVENTORY_MAX_AGE_H = 48

# Two different failures share this report and must not share a gate.
#
# A broken answer key -- a rule that matches nothing, a drill name that is not on
# the register, a kind nobody has taught this file, an asset list too old to
# believe -- is a defect in the instrument. It is fixed in minutes and it makes
# every other number here a lie, so it is red.
#
# A hole -- an asset nobody has classified -- is a fact about the estate, and
# there were 111 of them when this was written. Gating on that would paint the
# board red every day for weeks, and a gate that is red forever is one people
# stop reading, which is the exact failure docs/onboarding/drills.md already
# names. So the hole count is reported and delivered, and it is the number that
# has to fall; it does not stop anything.
HOLE = "unclassified-assets"

# Below this many assets of a kind, "no rule matched" says nothing. See
# dead_rules for why the check has to keep quiet rather than guess.
MIN_POPULATION = 3

# The off switch, and it is a file rather than a flag because the two places that
# report this -- the nightly drill run and the founder board -- are different
# processes nobody wants to edit one at a time. Touch it and both go quiet;
# delete it and both come back. The tool still answers when somebody asks it
# directly, because turning off a report is not the same as turning off an
# instrument.
OFF_FLAG = os.path.join(HOME, ".claude", "state", "coverage-off")


def is_off():
    return os.path.exists(OFF_FLAG)


# Which of the three questions each kind of asset has to answer. Absence is the
# judgement, not an omission: a ledger cannot restart, and drilling a drill is
# not a thing.
SLOTS = {
    "scheduled_job": ("restart", "rebuild", "replace"),
    "guard":         ("rebuild", "replace"),
    "repo":          ("rebuild", "replace"),
    "ledger":        ("rebuild",),
    "data":          ("rebuild",),
    "drill":         (),
}


def load_json(path, what):
    if not os.path.exists(path):
        raise SystemExit(f"no {what} at {path}")
    with open(path) as fh:
        return json.load(fh)


def inventory_age_hours(inv, path):
    """Hours since the asset list was generated, from its own stamp.

    Read the stamp the generator wrote rather than the file's mtime. A file
    copied, restored or touched has a fresh mtime and a stale answer, and this
    estate has already been fooled once by exactly that.
    """
    at = inv.get("at")
    if not at:
        return None
    try:
        t = time.strptime(at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None
    return (time.time() - (time.mktime(t) - time.timezone)) / 3600.0


def enrich(rows):
    """Add the facts the asset list does not carry and coverage cannot do without.

    One so far, and it earns its place. A launchd job comes back on a new
    machine only if something can write its plist there, and on this estate that
    is `jobs/render.py` reading `jobs/jobs.json`. The plists themselves are
    deliberately never restored -- tracked.json says so in as many words,
    because a plist has this home directory baked into it and restoring 46 of
    them onto a new Mac installs 46 jobs pointing at a machine that is gone.

    So `rendered` is the difference between a job that survives this laptop and
    one that does not, and nothing else on the estate was computing it.
    Measured 2026-08-24: 31 of 43 live jobs are in jobs.json and 12 are not,
    ai.aiden.watch among them.
    """
    jobs_file = os.path.join(os.path.dirname(HERE), "jobs", "jobs.json")
    try:
        with open(jobs_file) as fh:
            rendered = set(json.load(fh))
    except (OSError, ValueError):
        rendered = None
    for row in rows:
        if row.get("kind") == "scheduled_job" and rendered is not None:
            row["rendered"] = row["id"] in rendered
    return rows


def matches(rule_when, row):
    """True when every field the rule names equals the row's value.

    A rule that names a field the row does not carry never matches. That is
    deliberate: a rule keyed on `offsite` must not silently cover a kind of
    asset that has no such property.

    A rule value may also be {"prefix": "..."}, which is there for one real
    case: `remote` holds a whole URL and what decides whether GitHub going away
    takes the repo with it is the host at the front of it.
    """
    for field, want in rule_when.items():
        if field not in row:
            return False
        got = row[field]
        if isinstance(want, dict) and "prefix" in want:
            if not isinstance(got, str) or not got.startswith(want["prefix"]):
                return False
        elif got != want:
            return False
    return True


def classify(row, cov, fired=None):
    """What is decided about each of this asset's slots, and by what.

    Per-asset entries win over rules, because a rule is a generalisation and an
    entry is somebody looking at the one thing. Rules are tried in file order
    and the first match wins, so the file reads top to bottom as most specific
    first.
    """
    kind = row.get("kind", "?")
    out = {}
    for slot in SLOTS.get(kind, ()):
        decided, by = None, None
        entry = cov.get("assets", {}).get(row["id"], {})
        if slot in entry:
            decided, by = entry[slot], "asset"
        else:
            for rule in cov.get("rules", []):
                if rule.get("kind") != kind or slot not in rule:
                    continue
                if matches(rule.get("when", {}), row):
                    decided, by = rule[slot], rule.get("name", "rule")
                    if fired is not None:
                        fired.add(rule.get("name", "rule"))
                    break
        out[slot] = (decided, by)
    return out


def dead_rules(cov, fired, kinds_present):
    """Decisions no rule reaches, which on this estate means a typo.

    Written after one. The rule covering repositories against GitHub going away
    was keyed on a remote starting `github.com/`, and every remote the inventory
    records starts `https://github.com/`. It matched zero of 20 repositories and
    the report was happy: the rows simply came out unclassified, mixed in with
    the ones that are meant to be. A rule that fires on nothing is invisible
    exactly when it is wrong.

    The unit is the kind and slot, not the single rule, and the first version of
    this got that wrong. Rules deliberately come in alternatives that split a
    population -- a job with a vendor rides the vendor drill, a job without one
    is dismissed -- and on any given estate only one of a pair can match a given
    row. Grading each rule alone reported both halves of a working pair as dead
    the moment an estate held only one sort of job, which is a guard refusing
    correct work. Grading the pair together says the true thing: nothing at all
    decides `repo`/`replace`, so whatever was meant to is broken.

    A kind the estate does not own today is skipped rather than reported. There
    is nothing there for a rule to match and nothing to be wrong about.

    So is a kind the estate owns fewer than MIN_POPULATION of, and that is the
    third correction rather than caution. On a two-row estate "no rule matched"
    is not evidence: the two rows can honestly miss every rule, and the same
    output means a typo on 20 rows and means nothing on 1. The threshold is the
    point below which this check has to keep quiet instead of guessing, because
    a finding that is right on the real estate and wrong on a small one is a
    guard that refuses correct work somewhere.
    """
    counts = {k: len(v) for k, v in kinds_present.items()}
    groups = {}
    for r in cov.get("rules", []):
        kind = r.get("kind")
        if counts.get(kind, 0) < MIN_POPULATION:
            continue
        for slot in SLOTS.get(kind, ()):
            if slot in r:
                groups.setdefault((kind, slot), []).append(r.get("name", "rule"))
    return [(kind, slot, names) for (kind, slot), names in sorted(groups.items())
            if not any(n in fired for n in names)]


def check(verbose=False):
    """Every asset against every slot. Returns (report lines, problems)."""
    cov = load_json(COVERAGE, "coverage rule file")
    reg = load_json(REGISTER, "drill register")
    drills = {d["id"]: d for d in reg["drills"]}

    lines, problems = [], []

    if not os.path.exists(INVENTORY):
        problems.append(("inventory", f"no asset list at {INVENTORY}. Coverage is "
                                      "unknown, which is not the same as zero."))
        return lines, problems
    inv = load_json(INVENTORY, "asset list")
    age = inventory_age_hours(inv, INVENTORY)
    if age is None:
        problems.append(("inventory", "the asset list carries no generation stamp, "
                                      "so its age cannot be established"))
    elif age > INVENTORY_MAX_AGE_H:
        problems.append(("inventory", f"the asset list was generated {age:.0f}h ago, "
                                      f"past the {INVENTORY_MAX_AGE_H}h bar. Anything "
                                      "added since is invisible to this check."))

    rows = enrich(inv.get("rows", []))
    by_kind = {}
    for row in rows:
        by_kind.setdefault(row.get("kind", "?"), []).append(row)

    lines.append(f"{len(rows)} assets in {len(by_kind)} kinds, "
                 f"asset list generated {inv.get('at', 'at an unknown time')}")
    lines.append("")
    lines.append(f"  {'kind':<15}{'assets':>7}  {'slots':<24}{'covered':>8}"
                 f"{'dismissed':>11}{'UNCLASSIFIED':>14}")

    unclassified = []
    on_paper = {}
    fired = set()
    total_slots = 0
    for kind in sorted(by_kind):
        rs = by_kind[kind]
        slots = SLOTS.get(kind)
        if slots is None:
            problems.append((kind, f"{len(rs)} asset(s) of a kind this file has never "
                                   f"been taught about. Add it to SLOTS, even if the "
                                   f"answer is that no slot applies."))
            continue
        if not slots:
            lines.append(f"  {kind:<15}{len(rs):>7}  {'-- not an asset to drill':<24}"
                         f"{'':>8}{'':>11}{'':>14}")
            continue
        c = d = u = 0
        for row in rs:
            for slot, (decided, by) in classify(row, cov, fired).items():
                if decided is None:
                    u += 1
                    unclassified.append((kind, row["id"], slot))
                elif "covered_by" in decided:
                    c += 1
                    name = decided["covered_by"]
                    if name not in drills:
                        problems.append((row["id"], f"{slot} names '{name}', which is "
                                                    "not a drill on the register"))
                    elif not drills[name].get("cmd"):
                        on_paper.setdefault(name, []).append(f"{row['id']}/{slot}")
                elif "dismissed" in decided:
                    d += 1
                else:
                    problems.append((row["id"], f"{slot} is classified with neither "
                                                "covered_by nor dismissed"))
        total_slots += c + d + u
        flag = f"{u:>14}" if u else f"{'0':>14}"
        lines.append(f"  {kind:<15}{len(rs):>7}  {'/'.join(slots):<24}"
                     f"{c:>8}{d:>11}{flag}")

    lines.append("")
    dead = dead_rules(cov, fired, by_kind)
    if dead:
        lines.append("decisions that no rule reaches, so every asset under them "
                     "falls through unclassified. Usually a wrong field or value:")
        for kind, slot, names in dead:
            lines.append(f"  {kind}/{slot}   {len(names)} rule(s) written, "
                         f"none matched an asset: {', '.join(names)}")
        lines.append("")
        problems.append(("rules", f"{len(dead)} kind/slot decision(s) matched nothing"))

    if on_paper:
        lines.append("covered on paper only, because these drills are NOT WRITTEN:")
        for name, who in sorted(on_paper.items()):
            lines.append(f"  {name:<24} {len(who)} asset slot(s) rest on it")
        lines.append("")

    if unclassified:
        lines.append(f"{len(unclassified)} asset slot(s) nobody has classified. Each is "
                     "an asset whose loss has never been thought about:")
        shown = unclassified if verbose else unclassified[:20]
        for kind, ident, slot in shown:
            lines.append(f"  {kind:<15} {ident:<44} {slot}")
        if len(shown) < len(unclassified):
            lines.append(f"  ... and {len(unclassified) - len(shown)} more "
                         f"(--verbose lists every one)")
        problems.append((HOLE, f"{len(unclassified)} asset slot(s) unclassified"))
    else:
        lines.append("Every asset is either pointed at a drill or dismissed with a "
                     "reason. Nothing on this estate is unaccounted for.")

    lines.append("")
    lines.append(f"SUMMARY: {len(unclassified)} unclassified of {total_slots} "
                 f"asset slot(s) across {len(rows)} assets")
    return lines, problems


def one(asset_id):
    """Everything decided about one asset, for the question that started this.

    `coverage.py --asset ai.aiden.watch` is the command that answers "is Aiden
    under drill" in one line each for the three ways it could be, instead of
    four commands and a judgement call.
    """
    cov = load_json(COVERAGE, "coverage rule file")
    inv = load_json(INVENTORY, "asset list")
    rows = [r for r in enrich(inv.get("rows", [])) if asset_id in r["id"]]
    if not rows:
        print(f"no asset matching '{asset_id}' in {INVENTORY}")
        return 1
    for row in rows:
        print(f"{row['id']}   [{row.get('kind')}]  coupling={row.get('coupling')}")
        if not SLOTS.get(row.get("kind"), ()):
            print("  nothing to drill: this kind is not an asset that has to come back")
            continue
        for slot, (decided, by) in classify(row, cov).items():
            if decided is None:
                print(f"  {slot:<9} UNCLASSIFIED   nobody has said what happens "
                      f"when this is lost")
            elif "covered_by" in decided:
                print(f"  {slot:<9} drill: {decided['covered_by']:<24} [{by}]")
            else:
                print(f"  {slot:<9} dismissed: {decided['dismissed']}   [{by}]")
        print()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--asset", help="report the three slots for one asset and stop")
    ap.add_argument("--verbose", action="store_true",
                    help="list every unclassified slot rather than the first 20")
    ap.add_argument("--gate", action="store_true",
                    help="exit 1 only when the answer key itself is broken, not "
                         "when the estate has holes in it")
    # estate-selftest.py runs every script under ~/.claude/scripts that takes
    # `--selftest`, once an hour, and it skips anything named test_*. So the 13
    # cases in test_coverage.py sat next to this file and nothing ever ran them
    # on a schedule. This hands the estate the spelling it looks for rather than
    # moving the cases, because a control nobody runs is not a control.
    ap.add_argument("--selftest", action="store_true",
                    help="run test_coverage.py, the paired control for this tool")
    a = ap.parse_args()

    if a.selftest:
        return subprocess.call([sys.executable,
                                os.path.join(HERE, "test_coverage.py")])

    if a.asset:
        return one(a.asset)

    # --gate is the machine-facing mode: the nightly run is its only caller, so
    # it is also where the off switch has to bite. A person running this by hand
    # still gets an answer, which is the difference between silencing a report
    # and breaking a tool.
    if a.gate and is_off():
        print(f"coverage reporting is off ({OFF_FLAG} exists); delete that file "
              f"to turn it back on")
        return 0

    lines, problems = check(a.verbose)
    print("\n".join(lines))
    if a.gate:
        problems = [p for p in problems if p[0] != HOLE]
    if problems:
        print()
        for who, why in problems:
            print(f"  {who}: {why}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
