#!/usr/bin/env python3
"""Refuse a reply that claims done without the Definition of Done evidence.

WHY. Founder, 2026-08-25, after a "DONE:" reply that meant "merged, CI green": "what does done
mean" and then "we are upgrading standards now as in tired of repeating myself, i need things
working like clockwork". He handed over AGENTS_md_DoD_v2_1 (Definition of Done, Hard v2.1).
Its Golden Rule: merged code, green CI and passing tests are inventory, not done. Done is the
founder having used the thing end to end and confirmed it.

WHAT IT ENFORCES, mechanically, on the text above the fold of the last assistant message:

  DONE:       needs a `Founder receipt:` line (the founder confirmed it, and where that is
              recorded) AND an `Evidence:` line.
  INVENTORY:  the new word for built-merged-green-awaiting-founder. Needs the five handoff
              items from Gate 4, each as a labelled line: `Built:`, `Use:`, `Expect:`,
              `Not done:`, `Evidence:`.
  Evidence:   must carry something checkable: a URL, a commit hash, a file path, or a
              command in backticks. A bare sentence is not evidence.

WORKING:, WAITING: and BLOCKED: replies are untouched. So is anything below the first `---`.

WHAT IT CANNOT SEE (residual, stated per LAW 45 step 5). It checks the shape of the claim,
not its truth. A false `Founder receipt:` line passes this guard; the founder is the oracle
for that, and the interventions log is where it will be verified once the receipt tooling
exists (crew board, DoD gates issue). It never blocks the same text twice and at most three
times per session, so it cannot wedge a session.

DoD v3 (founder, 2026-09-15): "done means commercially ready and viable", not "proven against
a local daemon on someone's laptop." 2026-09-15's own ticket
(docs/tickets/2026-09-15-typed-multidomain-mutation-ledger.md) said "Built, smoke-tested, and
doored" on the strength of a BDD suite run against a real daemon -- while the backend that door
depended on had no Dockerfile, no Deployment, no Service, and nothing running under that name in
the live cluster. This guard narrows exactly that gap: a `Built:` line (INVENTORY) or the summary
line (DONE) that claims the thing is live -- "on cluster", "live", "deployed", "door"/"doored",
"running", "reachable" -- is refused unless `Evidence:` shows an actual live-environment check
(a `kubectl`/`idp-kube get ...` reference, a `Running` status, a curl/HTTP status check, or an
independent verifier's name such as `qa-agent`) rather than only a test command or a PR/commit
link. Scoped to one line each (Built:/the summary line) on purpose, per LAW 38: a guard that
blocks a correct reply because "live" showed up in an unrelated sentence is itself an outage.

  python3 dod-guard.py --selftest    # one case that must fail, one that must pass
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

STATE = Path.home() / ".claude" / "state" / "dod-guard.json"
MAX_BLOCKS_PER_SESSION = 3

HANDOFF = ("Built:", "Use:", "Expect:", "Not done:", "Evidence:")
CHECKABLE = re.compile(r"https?://\S+|\b[0-9a-f]{7,40}\b|`[^`]+`|(?:~|/)[\w./-]+")


def above_the_fold(text: str) -> str:
    return text.split("\n---", 1)[0]


def first_word(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    m = re.match(r"\s*\**\s*(DONE|INVENTORY|WORKING|WAITING|BLOCKED|STAGED):", line)
    return m.group(1) if m else ""


def has_line(text: str, label: str) -> bool:
    pat = re.compile(
        r"^\s*(?:[-*\d.]+\s*)?\**\s*" + re.escape(label), re.IGNORECASE | re.MULTILINE
    )
    return bool(pat.search(text))


def evidence_is_checkable(text: str) -> bool:
    for line in text.splitlines():
        if re.match(r"^\s*(?:[-*\d.]+\s*)?\**\s*Evidence:", line, re.IGNORECASE):
            rest = line.split(":", 1)[1]
            if CHECKABLE.search(rest):
                return True
    return False


def line_value(text: str, label: str) -> str | None:
    """The text after `label:` on its own line, or None if the line isn't present."""
    pat = re.compile(r"^\s*(?:[-*\d.]+\s*)?\**\s*" + re.escape(label), re.IGNORECASE)
    for line in text.splitlines():
        if pat.match(line):
            return line.split(":", 1)[1] if ":" in line else ""
    return None


# DoD v3 -- a claim that the thing is LIVE, not just built. Deliberately narrow phrases, because
# this is checked against exactly one line (Built:, or DONE's own summary line), not the whole
# reply: "live" showing up in an unrelated sentence elsewhere in the reply must never trip this.
_LIVE_CLAIM = re.compile(
    r"\bon cluster\b|\blive\b|\bdeployed\b|\bdoor(?:ed)?\b|\brunning\b|\breachable\b",
    re.IGNORECASE,
)
# What actually looks like someone having checked the live environment, as opposed to a test
# command or a PR/commit link: a kubectl/idp-kube get, an observed Running status, an HTTP/curl
# status check, or the estate's own independent verifier role.
_LIVE_EVIDENCE = re.compile(
    r"\b(?:kubectl|idp-kube)\s+\S*\s*get\b"
    r"|\bRunning\b"
    r"|\bcurl\b[^\n]*\b(?:200|201|204|301|302|healthz|http)\b"
    r"|\bHTTP/?\d?\s*\d{3}\b"
    r"|\bqa-agent\b",
    re.IGNORECASE,
)


def unverified_live_claim(fold: str, kind: str) -> str | None:
    """The claim line, if `kind` asserts a live capability with no live-probe Evidence:."""
    if kind == "INVENTORY":
        claim_line = line_value(fold, "Built:")
    elif kind == "DONE":
        lines = fold.strip().splitlines()
        claim_line = lines[0] if lines else None
    else:
        return None
    if not claim_line or not _LIVE_CLAIM.search(claim_line):
        return None
    evidence = line_value(fold, "Evidence:") or ""
    if _LIVE_EVIDENCE.search(evidence):
        return None
    return claim_line.strip()


# LAW 31 -- "The founder does not run scripts". Enforced here because a rule the guard was blind
# to is a rule that gets broken: on 2026-09-10 three replies in one session handed him a shell
# command, an installer to run, and a policy to authorise, and nothing refused any of them.
#
# The scope is wider than "a script", because that is how the rule was missed each time. It
# catches the four shapes a session actually reaches for:
#
#   1. A fenced block that is plainly a command to type (`bash`, `sh`, `zsh`, `shell`, `console`),
#      or a fenced block whose body starts with a bare command word.
#   2. A sentence telling him to run something, in the imperative or as a suggestion.
#   3. A named estate tool offered as his action (`bin/idp-*`), which is the same thing wearing
#      the platform's own name.
#   4. An ask that he authorise, approve or paste -- the same handoff, phrased as a permission.
#
# What is NOT an offence, and this matters more than the rule: a command quoted as EVIDENCE of
# what was run, a command inside a `Not done:` or `Evidence:` line, or a command shown as proof
# in a table. The guard grades what the reply ASKS HIM TO DO, not every backtick it contains --
# a guard that refuses correct work is an outage (R38).
_FENCE_IS_A_COMMAND = re.compile(
    r"^```(?:bash|sh|zsh|shell|console|terminal)\s*$", re.M
)
_FENCE_ANY = re.compile(r"^```.*$", re.M)
# A fenced block's body, tagged or bare.
_FENCED_BODIES = re.compile(r"^```[^\n]*\n(.*?)^```", re.M | re.S)
# The first word of a line that is a command rather than prose: an estate tool, a known binary,
# or a path-ish token followed by an argument.
# The first word of a line that is a command rather than prose. Three shapes, because the third
# is the one that got past the first version of this rule: a bare tool name with no path and no
# argument (`concierge-install`) is still an instruction to type it.
_LOOKS_LIKE_A_COMMAND = re.compile(
    r"^(?:\$\s*)?(?:sudo\s+)?(?:"
    r"bin/[\w.-]+"  # an estate tool by path
    r"|\./\S+|/\S+"  # a path
    r"|(?:python3?|pip3?|npm|npx|yarn|pnpm|brew|git|docker|kubectl|helm|flux|make|curl|wget|ssh|"
    r"bash|sh|zsh|launchctl|systemsetup|gh|uv|uvicorn|pipx|conda|cargo|go|ruby|perl)\b"
    r"|[a-z][a-z0-9]*-(?:install|up|down|deliver|run|build|deploy|bootstrap|start|stop|migrate)\b"
    r"|[a-z][a-z0-9]*(?:-[a-z0-9]+){2,}\b"  # a hyphenated tool name, 2+ hyphens
    r")",
)

# "run X", "you run", "please run", "just run" directed at him.
_ASK_TO_RUN = re.compile(
    r"\b(?:please\s+|just\s+|now\s+|you\s+|you'll\s+|you need to\s+|you should\s+|"
    r"run this|then run|execute this|type this|paste this|copy this)\b[^.]{0,80}?"
    r"\b(?:run|execute|type|paste|invoke|install)\b",
    re.I,
)
# A named estate tool offered as his action, not as evidence.
_NAMES_A_TOOL = re.compile(r"\b(?:run|use|execute|invoke)\s+`?bin/idp-[a-z0-9-]+", re.I)
# Asking him to authorise or approve a change rather than doing it.
_ASKS_PERMISSION = re.compile(
    r"\b(?:authorise|authorize|approve|paste it|paste the|confirm and I|say go and I|"
    r"your call to apply|tell me to apply)\b",
    re.I,
)


def hands_the_founder_work(fold: str) -> list[str]:
    """The lines where the reply asks HIM to do something a product should do itself.

    Returns one string per offence, each quoting the line, so the session can see exactly which
    sentence broke the rule rather than a general accusation.
    """
    found: list[str] = []
    for raw in fold.splitlines():
        line = raw.strip()
        if not line:
            continue
        # A command offered as evidence is not work handed over. The DoD already requires an
        # `Evidence:` line, and refusing the command inside it would refuse correct work.
        if re.match(
            r"^(?:Evidence|Not done|Founder receipt|Built|Use|Expect)\s*:", line, re.I
        ):
            continue
        if line.startswith("|") or line.startswith(">"):
            continue  # a table row or a quotation, not an instruction
        for pattern, why in (
            (_NAMES_A_TOOL, "names an estate tool as his action"),
            (_ASK_TO_RUN, "asks him to run something"),
            (
                _ASKS_PERMISSION,
                "asks him to authorise something the estate can do itself",
            ),
        ):
            if pattern.search(line):
                found.append(f"LAW 31: {why}: {line[:160]}")
                break
    # The fence case, and it has to inspect the BODY rather than the tag: a tagged ```bash is the
    # obvious shape, but the one used on 2026-09-10 was a BARE fence, which no tag-based rule can
    # see. A block whose first non-blank line is a command word is an instruction to type it.
    for body in _FENCED_BODIES.findall(fold):
        stripped = body.strip()
        if not stripped:
            continue
        first = stripped.splitlines()[0].strip()
        if _LOOKS_LIKE_A_COMMAND.match(first):
            found.append(
                "LAW 31: the reply hands him a shell block to run: "
                f"`{first[:110]}`. A consumer product is installed and used; it is not started by "
                "a person typing commands."
            )
            break
    return found


def offences(text: str) -> list[str]:
    fold = above_the_fold(text)
    kind = first_word(fold)
    out: list[str] = []
    if kind == "DONE":
        if not has_line(fold, "Founder receipt:"):
            out.append(
                "DONE: needs a `Founder receipt:` line. If the founder has not used it and "
                "confirmed it, the word is INVENTORY:, not DONE:."
            )
        if not has_line(fold, "Evidence:"):
            out.append("DONE: needs an `Evidence:` line.")
    elif kind == "INVENTORY":
        missing = [h for h in HANDOFF if not has_line(fold, h)]
        if missing:
            out.append(
                "INVENTORY: needs all five handoff lines; missing "
                + ", ".join(f"`{m}`" for m in missing)
            )
    elif kind == "STAGED":
        # crew#281: a staged handoff carries its own default and timer, in the founder's words.
        if not re.search(r"Reply 'go' to execute immediately, 'hold' to review", fold):
            out.append(
                "STAGED: needs the sentence `Reply 'go' to execute immediately, 'hold' to review.`"
            )
        if not re.search(r"Auto-activating in \d+ minutes", fold):
            out.append("STAGED: needs `Auto-activating in <N> minutes.` with a number.")
    if (
        kind in ("DONE", "INVENTORY")
        and has_line(fold, "Evidence:")
        and not evidence_is_checkable(fold)
    ):
        out.append(
            "`Evidence:` must contain a URL, a commit hash, a file path or a `command`."
        )
    claim = unverified_live_claim(fold, kind)
    if claim is not None:
        out.append(
            'DoD v3: this claims the thing is live ("'
            + claim[:160]
            + '") but `Evidence:` '
            "shows only a test command or a merge/PR link, not a live-environment check. Add a "
            "`kubectl`/`idp-kube get ...` reference, an observed Running status, an HTTP/curl "
            "status check, or `qa-agent`'s sign-off -- or say `Not done:` instead."
        )
    # LAW 31, and it applies to EVERY reply kind, not only the two above: handing him work is a
    # defect whatever word the reply opens with.
    out.extend(hands_the_founder_work(fold))
    return out


def last_assistant_text(transcript: Path) -> str:
    text = ""
    with transcript.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") != "assistant":
                continue
            content = (row.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            joined = "\n".join(p for p in parts if p).strip()
            if joined:
                text = joined
    return text


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    os.replace(tmp, STATE)


def report(found: list[str]) -> str:
    lines = ["BLOCKED by dod-guard (Definition of Done v2.1, founder 2026-08-25):"]
    lines += [f"  - {f}" for f in found]
    lines.append(
        "  Shape: line 1 DONE:/INVENTORY:/WORKING:/WAITING:/BLOCKED:/STAGED:. INVENTORY carries Built:, Use:, "
        "Expect:, Not done:, Evidence:. DONE additionally carries Founder receipt:."
    )
    return "\n".join(lines)


def selftest() -> int:
    bad = "DONE: idp#104 is merged to main as c553b34 and the KINI job has nothing open.\n\nMain CI came back green."
    bad2 = "INVENTORY: the worker restarts on merged code.\nBuilt: restart step.\nEvidence: it works."
    good = (
        "INVENTORY: the ollama-vision alias is on main; you have not tried it yet.\n"
        "Built: llm/config.yaml now declares `ollama-vision` -> gemma3:4b.\n"
        "Use: `sb ask --vision <image>` from the menu bar.\n"
        "Expect: a caption within 10 seconds.\n"
        "Not done: no founder run yet; pyright has 382 errors.\n"
        "Evidence: https://github.com/chidionyema/idp/pull/104 merged as c553b34.\n"
    )
    good2 = (
        "DONE: you ran the vision route and confirmed it.\n"
        "Founder receipt: crew#219 comment 5414486390, 'works'.\n"
        "Evidence: https://github.com/chidionyema/idp/pull/104\n"
    )
    working = "WORKING: waiting on CI.\n"
    staged = (
        "STAGED: platform/access apply (idp#150) is ready. Reply 'go' to execute immediately, 'hold' to "
        "review. Auto-activating in 60 minutes.\n"
    )
    staged_bad = "STAGED: platform/access apply is ready, say go.\n"
    # DoD v3: a live/deployment claim backed only by a test command is not evidence it's live.
    live_bad = (
        "INVENTORY: fleetview backend is packaged.\n"
        "Built: FleetView backend, on cluster and doored.\n"
        "Use: open the FleetView page in Backstage.\n"
        "Expect: a live agent roster.\n"
        "Not done: nothing.\n"
        "Evidence: `pytest tests/test_fleetview.py` all green.\n"
    )
    live_good = (
        "INVENTORY: fleetview backend is packaged.\n"
        "Built: FleetView backend, on cluster and doored.\n"
        "Use: open the FleetView page in Backstage.\n"
        "Expect: a live agent roster.\n"
        "Not done: nothing.\n"
        "Evidence: `idp-kube get deploy fleetview-backend -n backstage` shows 1/1 Running; "
        "`curl https://fleetview.internal/healthz` -> 200.\n"
    )
    ok = True
    for name, text, expect_block in (
        ("bad", bad, True),
        ("bad2", bad2, True),
        ("good", good, False),
        ("good2", good2, False),
        ("working", working, False),
        ("staged", staged, False),
        ("staged_bad", staged_bad, True),
        ("live_bad", live_bad, True),
        ("live_good", live_good, False),
    ):
        got = bool(offences(text))
        print(
            f"{name}: {'BLOCK' if got else 'PASS'} {'ok' if got == expect_block else 'WRONG'}"
        )
        ok &= got == expect_block
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        payload = {}
    path = payload.get("transcript_path") or ""
    if not path or not os.path.exists(path):
        return 0
    try:
        text = last_assistant_text(Path(path))
    except OSError:
        return 0
    if not text:
        return 0
    found = offences(text)
    if not found:
        return 0
    session = str(payload.get("session_id") or "unknown")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    state = load_state()
    mine = state.get(session) or {"count": 0, "seen": []}
    if digest in mine["seen"] or mine["count"] >= MAX_BLOCKS_PER_SESSION:
        return 0
    mine["count"] += 1
    mine["seen"] = (mine["seen"] + [digest])[-20:]
    state[session] = mine
    save_state(state)
    print(report(found), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
