#!/usr/bin/env python3
"""The body and lane every automatically opened issue carries.

crew#527 CP4 (founder 2026-08-27: "we have many features half done"): 123 of 187 open issues had no
checklist and 42 no lane, so the finish-first rank (estate_board.py) could not tell a half-done
feature from an untouched one. ticket-gate.py calls issue_body() for every issue it opens; the
three boxes and the lane label are the minimum the rank and the closer (crew#526) read.
Not a guard: a template and a lane map, kept out of ticket-gate.py so that file only shrinks
(policy/hand_rolled_policy.rego)."""
from __future__ import annotations

import re

DOD_BOXES = (
    "## Definition of done\n"
    "- [ ] Built: the change is merged and CI is green (inventory, not progress)\n"
    "- [ ] Proved: one command shows it running, its output pasted here\n"
    "- [ ] Founder used it and confirmed (receipt: the comment or message where he said so)\n"
)
LANE_BY_DIR = {"idp": "platform", "crew": "process", "hermes-v2": "agents", "prospector-main": "money",
               "mumchimp-medusa": "money", "estate": "platform", "claude-guards": "process"}


def lane_for(cwd: str) -> str:
    """The lane label for a working directory; unsorted when the directory names no product."""
    parts = [x for x in cwd.replace("\\", "/").split("/") if x]
    for name in reversed(parts):
        if name in LANE_BY_DIR:
            return "lane:" + LANE_BY_DIR[name]
    return "lane:unsorted"


def has_dod(body: str) -> bool:
    """Three or more checkboxes: the minimum estate_board.py ranks on."""
    return len(re.findall(r"^\s*- \[[ xX]\]", body or "", re.M)) >= 3


def issue_body(words: str, cwd: str, sid: str, budget_usd, budget_min) -> str:
    body = (
        "Opened automatically when a session started changing files without a ticket.\n\n"
        "**The founder's own words, first thing he typed in this session:**\n\n> %s\n\n"
        "- working directory: `%s`\n- session: `%s`\n\n"
        "This issue exists so the work is followed up rather than lost between tabs. "
        "Close it when a command proves the outcome, not when an agent says so.\n\n"
        "## Budget\n"
        "- cost: $%s\n"
        "- time: %sm\n\n"
        "A default, not an estimate. Revise it now if this job is bigger or smaller, because the "
        "comparison printed when this issue closes is only worth reading if the number was set "
        "before the work rather than after it.\n\n" % (
            words or "(nothing captured)", cwd, sid, budget_usd, budget_min)
        + DOD_BOXES
    )
    if not has_dod(body):
        raise ValueError("issue body lost its three boxes")
    return body
