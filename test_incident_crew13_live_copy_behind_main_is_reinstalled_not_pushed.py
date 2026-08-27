"""claude-guards aae334c, 2026-08-27 04:42Z: tracked.py --sync read ~/.claude/settings.json and
~/AGENTS-FULL.md, which nobody had reinstalled after #118, #122 and the LAW 50 merge, as
"changed outside git" and pushed the stale copies over main. LAW 50 left the law text, every
hook lost its hook-run.py wrapper, and main went red for an hour. The rule: a live copy that
is byte-identical to a version committed before HEAD is behind git, not ahead of it. The
job reinstalls the committed copy and pushes nothing. A live copy that is genuinely new is
still mirrored (the permit case, same run).
"""

from test_incident_tracked_committed_into_a_checkout_it_does_not_own import estate, git, load, run_sync  # noqa: F401  (estate is a fixture)


def test_incident_crew13_live_copy_behind_main_is_reinstalled_not_pushed(estate):
    tmp_path, origin, shared, live = estate
    # main moves past the seed: "old" -> "newer"; the machine still holds "old".
    git(shared, "checkout", "main")
    (shared / "mirrors" / "thing.conf").write_text("newer, reviewed and merged\n")
    git(shared, "commit", "-am", "reviewed change")
    git(shared, "push", "origin", "main")
    git(shared, "checkout", "fix/somebody-elses-work")
    (live / "thing.conf").write_text("old\n")

    mod = load()
    run_sync(mod, tmp_path, shared)

    head = git(shared, "show", "origin/main:mirrors/thing.conf")
    assert head == "newer, reviewed and merged", "the stale live copy was pushed over main"
    assert (live / "thing.conf").read_text() == "newer, reviewed and merged\n", "live copy not reinstalled"
    assert "stale-behind" in (tmp_path / "board.jsonl").read_text()


def test_a_genuinely_new_live_copy_is_still_mirrored(estate):
    tmp_path, origin, shared, live = estate  # live holds "new, and this must reach origin"
    mod = load()
    run_sync(mod, tmp_path, shared)
    assert git(shared, "show", "origin/main:mirrors/thing.conf") == "new, and this must reach origin"
