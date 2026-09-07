"""2026-09-07: blocker-guard refused a reply for NAMING the mark it was correcting.

The rule tested `"FOUNDER ACTION:" in reply`, a bare substring, so it refused the sentence
"Correction taken: I wrote `FOUNDER ACTION:` for something that is not a device-in-hand step" --
a reply whose whole content was that the mark had been used wrongly. The only way past it was to
stop naming the thing being corrected. LAW 38.

The rules now live in policy/blocker.rego (cases in blocker_test.rego). What is pinned here is the
one transform the guard still owns: a mark written as code is a mention, a mark written as prose is
a directive. Each case below is a real reply this guard graded, or the exact line
founder-blocker.py prints.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "blocker_guard", Path(__file__).resolve().parents[1] / "blocker-guard.py"
)
bg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bg)

ACTION, STAGED = "FOUNDER ACTION:", "STAGED:"


def marks(reply: str) -> tuple[bool, bool]:
    said = bg.prose(reply)
    return ACTION in said, STAGED in said


@pytest.mark.parametrize(
    ("name", "reply", "expected"),
    [
        (
            "a bare directive",
            "FOUNDER ACTION: plug the YubiKey in and touch it",
            (True, False),
        ),
        (
            "the self-correction that was wrongly refused",
            "Correction taken: I wrote `FOUNDER ACTION:` for something that is not a "
            "device-in-hand step. It's a reversible merge, so it's staged instead.",
            (False, False),
        ),
        (
            "the line founder-blocker.py prints",
            "STAGED: the gate deletion is ready. Reply 'go' to execute immediately, 'hold' to "
            "review. Auto-activating in 60 minutes.",
            (False, True),
        ),
        (
            "a directive mid-line after a sentence",
            "Google publishes no create-client API. **FOUNDER ACTION:** mint the client.",
            (True, False),
        ),
        (
            "a directive under a list bullet",
            "- cyrus waits on the Linear token nobody can mint but you.\n"
            "  FOUNDER ACTION: paste the Linear API token",
            (True, False),
        ),
        (
            "a fenced block is quoted material",
            "Here is what the guard prints:\n```\nFOUNDER ACTION: <the device step>\n```\n",
            (False, False),
        ),
        ("a tilde fence too", "~~~\nSTAGED: x is ready\n~~~", (False, False)),
        (
            "naming both marks in code",
            "A billing page is a console step, so this is `STAGED:`, not `FOUNDER ACTION:`.",
            (False, False),
        ),
        (
            "a promise to send one later is not sending one",
            "The seed step comes after #606 lands, and I'll send a `FOUNDER ACTION:` line then.",
            (False, False),
        ),
        ("no mark at all", "Merged 8b7a25e0; the tool is on main.", (False, False)),
    ],
)
def test_a_mark_written_as_code_is_a_mention(
    name: str, reply: str, expected: tuple[bool, bool]
):
    assert marks(reply) == expected, name


def test_the_transform_leaves_the_rest_of_the_reply_alone():
    """Blanking a span must not eat the sentence around it -- the rules read what is left."""
    said = bg.prose("The merge is `armed` and the checks are green.")
    assert "The merge is" in said and "and the checks are green." in said
