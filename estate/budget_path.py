"""crew#91 half 2 (2026-08-27): where the estate's budget file is.

The spend policy is tracked at ``estate/estate-budget.json`` in this repo
(crew#91 half 1). A machine may still carry the older per-Mac copy at
``~/.claude/estate-budget.json`` (or a symlink there); when it exists it wins
so nothing changes on a machine already set up. When it does not, the tracked
file is read directly, so a fresh machine needs no install step and no symlink
(LAW 27). Every reader calls this instead of naming the path itself (LAW 46).
"""
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKED = os.path.join(_REPO, "estate", "estate-budget.json")
LOCAL = os.path.join(os.path.expanduser("~"), ".claude", "estate-budget.json")


def budget_path(local=None, tracked=None):
    """Return the budget file to read: the machine-local path if present, else the tracked one."""
    local = LOCAL if local is None else local
    tracked = TRACKED if tracked is None else tracked
    return local if os.path.exists(local) else tracked
