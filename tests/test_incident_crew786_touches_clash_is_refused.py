"""crew#786: TOUCHES clash is refused.

A handoff that touches a path another session touched inside 2h must either
name that session on the OVERLAP line or leave the path to them.
"""

import datetime as dt
import importlib.util
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def _feed_guard():
    spec = importlib.util.spec_from_file_location("feed_guard", HERE / "feed-guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_incident_crew786_touches_clash_finds_the_clash():
    fg = _feed_guard()
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "feed.md"
        t0 = fg.now()
        t1 = t0 + dt.timedelta(minutes=10)

        # Write peer's handoff with TOUCHES containing a path
        peer_body = "🔴 a\n🟡 b\n🟢 c\n⚪ d\n🔧 TOUCHES: ~/dev/code/idp/bin/x\n🔀 OVERLAP: none\n📍 e"
        fg.append(f, "aaaa0000", "other-lane", peer_body, t1)

        # New entry from different session touching same path
        new_body = "🔴 a\n🟡 b\n🟢 c\n⚪ d\n🔧 TOUCHES: ~/dev/code/idp/bin/x\n🔀 OVERLAP: none\n📍 e"

        clashes = fg.touch_clashes(f, "bbbb0000", new_body, t1)
        assert len(clashes) == 1
        assert clashes[0][0] == "aaaa0000"
        assert "idp/bin/x" in clashes[0][1]


def test_incident_crew786_ignores_different_path():
    fg = _feed_guard()
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "feed.md"
        t0 = fg.now()
        t1 = t0 + dt.timedelta(minutes=10)

        # Write peer's handoff with TOUCHES containing a path
        peer_body = "🔴 a\n🟡 b\n🟢 c\n⚪ d\n🔧 TOUCHES: ~/dev/code/idp/bin/x\n🔀 OVERLAP: none\n📍 e"
        fg.append(f, "aaaa0000", "other-lane", peer_body, t1)

        # New entry touching a different path
        new_body = "🔴 a\n🟡 b\n🟢 c\n⚪ d\n🔧 TOUCHES: ~/dev/code/other/y\n🔀 OVERLAP: none\n📍 e"

        clashes = fg.touch_clashes(f, "bbbb0000", new_body, t1)
        assert clashes == []


def test_incident_crew786_ignores_same_session():
    fg = _feed_guard()
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "feed.md"
        t0 = fg.now()
        t1 = t0 + dt.timedelta(minutes=10)

        # Write peer's handoff with TOUCHES containing a path (same session)
        peer_body = "🔴 a\n🟡 b\n🟢 c\n⚪ d\n🔧 TOUCHES: ~/dev/code/idp/bin/x\n🔀 OVERLAP: none\n📍 e"
        fg.append(f, "aaaa0000", "other-lane", peer_body, t1)

        # Same session updates with same path - not a clash with itself
        new_body = "🔴 a\n🟡 b\n🟢 c\n⚪ d\n🔧 TOUCHES: ~/dev/code/idp/bin/x\n🔀 OVERLAP: none\n📍 e"

        clashes = fg.touch_clashes(f, "aaaa0000", new_body, t1)
        assert clashes == []


def test_incident_crew786_ignores_token_without_slash():
    fg = _feed_guard()
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "feed.md"
        t0 = fg.now()
        t1 = t0 + dt.timedelta(minutes=10)

        # Write peer's handoff with TOUCHES containing a non-path token (no slash)
        peer_body = "🔴 a\n🟡 b\n🟢 c\n⚪ d\n🔧 TOUCHES: none\n🔀 OVERLAP: none\n📍 e"
        fg.append(f, "aaaa0000", "other-lane", peer_body, t1)

        # New entry with TOUCHES line that has a token without slash
        new_body = (
            "🔴 a\n🟡 b\n🟢 c\n⚪ d\n🔧 TOUCHES: someword\n🔀 OVERLAP: none\n📍 e"
        )

        clashes = fg.touch_clashes(f, "bbbb0000", new_body, t1)
        assert clashes == []
