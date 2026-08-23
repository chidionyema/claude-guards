# Could we rebuild this estate on a new machine in one shot?

Measured 2026-08-23. Every number below came from a command, not from memory.

## The answer is no, and here is the size of the no

| what | measurement | why it stops a rebuild |
|---|---|---|
| this machine's name is compiled in | 188 occurrences across 35 files, 158 of them inside job definitions | a different username breaks every scheduled job |
| the scheduler is macOS only | ~~33 files know about `launchd`~~ FIXED 2026-08-23 | `jobs/render_windows.py` renders all 28 to Task Scheduler XML. 28 of 28 lose something on the way; the losses are counted below |
| `~/.claude` has no remote | ~~1029 tracked files in one place~~ FIXED 2026-08-23 | private remote `github.com/chidionyema/claude-estate`, with `scripts/` as the submodule `claude-guards`. 73 tracked files: the laws, settings, jobs and shell config. `projects/` was removed on 2026-08-23 and does not come back |
| load-bearing dotfiles untracked | `.prospector .config .ssh .aws .gnupg .zshrc .gitconfig .npmrc` | nothing records what they contained |
| credentials have no manifest | 11 environment variables named in code | nobody can list what a new machine must be given |
| external accounts | GitHub, Fly, Cloudflare R2, Telegram, Anthropic, Docker | each needs a sign-in a machine cannot do for itself |

## On Windows specifically

Not "harder". Undesigned. 158 of the 188 path references live inside macOS job
definitions that Windows cannot read at all. A Windows rebuild is not a porting
job, it is a rewrite of how work gets scheduled.

## What the target actually is

Not zero-touch. LAW 27 already settles that: a browser sign-in proving identity
is once per identity, ever, and no agent does it as him. So the honest target is

    one command, then about five sign-ins, then the machine owns itself

Anything beyond those five is a defect, not a step.

## How to crack it, smallest road first

**1. DONE 2026-08-23. `~/.claude` has a private remote.** `github.com/chidionyema/claude-estate`,
created private, with `scripts/` registered as the submodule `claude-guards`.

   The remote is private and a commit gate stands in front of it.
   `scripts/hooks/pre-commit` refuses any commit whose staged content matches a
   credential shape, reading the staged blob rather than the working tree, and
   reporting `file:line` only so a refusal cannot print the thing it stopped.

   **The repository no longer holds conversation transcripts or project memory,
   and must not again.** It carried 878 checkpoint notes, 704 memory files and 4
   state probes under `projects/` until 2026-08-23. Founder: "this shold not be
   ingithub". They were removed from the index and rewritten out of all 51
   commits with `git-filter-repo`, taking the repository from 1,659 tracked files
   to 73. Those files stay on disk and go to the offsite backup; they do not go
   to a code-hosting vendor. `.gitignore` no longer admits them and the commit
   gate refuses any staged path under `projects/`, because `.gitignore` alone is
   one `git add -f` away from being wrong.

   Scanned before removal: 193 credential-shaped matches across the 720 tracked
   markdown files in the prospector project. Every one is a variable NAME with no
   value after it, except a single `EXA_API_KEY=` whose value is 26 characters of
   lowercase letters and hyphens with no digit in it. An Exa key is a UUID and
   contains hex digits, so that one is a placeholder in a code snippet, not a
   key. Nothing needs rotating. (An earlier reading of "5 matched" counted files,
   not matches, and is corrected here.)

**2. DONE 2026-08-23. Widen `tracked.json` from four entries to the whole machine surface.**
The manifest built today already works and already has a guard that fails on
drift. Add the eight untracked dotfiles. Name every credential without storing
any value.

**3. DONE 2026-08-23. Declare jobs once and render them per platform.** This is the real crack.
Today a job IS a launchd plist with an absolute path typed into it. Instead
declare the job's intent once, and generate the plist from it. Two things fall
out at once: the 158 hardcoded paths disappear because the renderer fills in the
home directory, and a second renderer for systemd or Windows becomes a small
job rather than a rewrite.

That third step is what makes this repeatable as the estate grows. New job means
a new entry in a file that is already tracked and already guarded, not a plist
typed by hand into a directory nobody was watching.

## What proves it works

A rebuild that has never been drilled is a hope, by LAW 19. `rebuild/drill.sh`
clones both repositories into a throwaway home, restores from the manifest,
renders the jobs for that home, and asserts six things. It runs itself: the
launch agent `ai.estate.drills` fires Mondays at 04:30, runs every written drill
through `drills/run.py --all`, and writes one verdict line to
`ESTATE_BOARD.jsonl`, which every session is handed at startup. PASS and NOT-RUN
are different lines on the board, which is the whole point of scheduling it
rather than leaving a command for somebody to type.

The job was named `ai.estate.rebuild-drill` here until 2026-08-23 and no such job
has ever existed on this machine. The rebuild is one entry in a register of ten,
and the scheduler runs the register, not that one drill.

**Measured 2026-08-23 20:2x, and it is not yet proved by machine.** `launchctl
print gui/501/ai.estate.drills` reports `runs = 0`. The job is loaded and its
definition is correct; it has simply never fired, because its first Monday has
not come round. Every PASS on the register today was produced by an agent typing
the command, which is the exact thing the schedule exists to replace. Until a
Monday passes, the drills are proven by hand, not by the estate.

Two defects that this reading found, both fixed the same day:

- `drills/run.py:post()` swallowed every failure of its own board write. A drill
  suite that runs, passes and reaches no reader has proved nothing (LAW 28), and
  the swallow made that indistinguishable from a quiet estate. It now writes to
  stderr and raises a `guard-broken` row.
- `drills/check_bundle_restore.py` counted `{"event":"skipped"}` receipts as
  pushes that proved nothing, so the estate's own lock — working correctly —
  turned the drill red. Skips are now separated from attempts, and they are read
  for the one thing they do say: how long the lock was held. A wedge over an hour
  fails the drill while it is unresolved, and reports as cleared once a later push
  succeeds.


## What changed on 2026-08-23

Steps 2 and 3 are done. Step 1 is still the founder's call.

**Step 2.** `tracked.json` went from 4 paths to 9: `~/.zshrc`, `~/.gitconfig`,
`~/.npmrc`, the per-tool configuration under `~/.config`, and
`~/.prospector/bin`, on top of the launch agents, the laws and settings.

`tracked.py --pull` now scans every file before it copies it and refuses one
that looks like a credential. Two angles agree on what to keep out, and they
catch different things. The content scan catches the two age keys, the pi
`apiKey` and the telegram token in `estate.env`. The name excludes catch
`gh/hosts.yml` and the mono keypair, which are credential stores by design even
though they scan clean. Nothing in the repository trips the scan: 184 files
checked, 6 matches, all six the detector patterns inside `secret-scrub.py`,
`estate_audit.py`, `board.py`, `maestro.py` and `estate.yml` rather than values.

`rebuild/PREREQUISITES.md` is the other half of step 2. Fourteen paths that a
new machine needs and that must never be in git, each with what it holds and the
command that gets it. `~/.ssh`, `~/.aws` and `~/.gnupg` are named and their
contents are not.

**Step 3.** `jobs/jobs.json` declares all 28 non-vendor jobs with `{HOME}` where
this account's home directory was typed in. `jobs/render.py` generates the
plists back from it.

Three counts agree at 176: `{HOME}` placeholders in the manifest, home paths in
the live plists, and `/Users/newmachine` occurrences when the manifest is
rendered for another account. Rendering for that account leaves 0 files naming
this machine.

One thing the renderer loses, and it is why the live plists were restored from
git rather than left as rendered output: `plistlib` drops XML comments. Fourteen
of the 27 plists carry comments explaining why a job is shaped the way it is,
including the one on `com.founder.maestro` about why it is a one-shot rather
than a daemon. The manifest is a faithful record of what launchd runs, not of
what a person wrote. Treat it as the source for a NEW job and for a rebuild on a
new machine; leave an existing hand-written plist alone.

**The guard runs itself.** `ai.estate.tracked-guard` runs `tracked.py --sync`
every 30 minutes: pull, commit, push, and one line on `ESTATE_BOARD.jsonl`,
which every session is handed at startup. It is loaded, its first run exited 0,
and it committed and pushed its own plist. That is LAW 31 -- nobody types a
command to find out whether the estate's files are under version control -- and
LAW 28, because the board has readers and a log file does not.

**The drill has run, and it passes. The score is 14.**

    2026-08-23 14:46:02Z, run by launchd, exit 0

      ok    no plist carries another machine's home (0)
      ok    every declared job rendered for this home (29)
      ok    the laws symlink resolves (# The laws)
      ok    the guards came with the clone (yes)
      ok    the commit gate came with the clone (yes)
      ok    no credential was restored (0)
      files rebuilt: 1846
      THE SCORE: 14 manual steps

It failed on its first two runs, and both failures were real. The first: the
clone got an old `scripts/` because the parent repository still pointed at a
superseded submodule commit, which nothing on this machine can see -- only a
clone finds out. `tracked.py --check` now fails on a stale pointer, and that
check already runs every 30 minutes. The second: the manifest declared 29 jobs
and the clone rendered 28, because the new job was committed in the submodule
and not yet pushed. The same class, caught by the same assertion.

Four of the 14 steps are not steps, they are defects in the bootstrap: `~/.ssh`,
`~/.config/.mono/keypairs`, `~/.prospector/escrow/agent.pem` and
`~/.config/wave/state.json` can all be regenerated by a machine. The target is
the sign-ins only.

**Windows renders, and 26 of 29 jobs now cross intact.**
`jobs/render_windows.py` turns all 29 jobs into Task Scheduler XML and names,
per job, what Windows does not keep. The reading was 0 of 29 this morning.

Five things were being called losses that are in fact translations, and each one
is now carried rather than dropped.

- The program was `/usr/bin/python3`. It is now a placeholder such as
  `{PYTHON3_SYSTEM}`, and `jobs/platforms.json` is the only file holding a
  platform's own names. 13 losses gone.
- `PATH` was one colon-separated string. It is now a list of directories, joined
  with the platform's own separator, and the POSIX system directories Windows
  does not need are dropped rather than emitted. 23 losses down to 2, each
  naming the specific directory that has no equivalent.
- `Nice`, `ProcessType: Background` and `LowPriorityIO` are three launchd
  controls for one intent. Windows has one, `<Priority>`, and it now carries it.
  15 losses gone.
- `KeepAlive` restarts on any exit and `RestartOnFailure` only on a non-zero
  one, so the rest of the supervisor is the trigger: every task sets
  `MultipleInstancesPolicy` to `IgnoreNew`, and a trigger that re-fires on a gap
  starts a stopped job and is ignored while it is running. `ThrottleInterval`
  becomes that gap. 12 losses gone.
- `StartCalendarInterval` with a `Weekday` was rendered as a daily trigger.
  Task Scheduler has `ScheduleByWeek` and it now uses it. 1 loss gone.

One thing went the other way, and it matters more than the rest. Twelve jobs run
a virtualenv interpreter at `.venv/bin/python`. Windows venvs put it in
`Scripts\` with a `.exe`, and because the real program sits inside the cmd.exe
wrapper the interpreter check never saw it. Those twelve were reporting clean
and could not have run. The renderer now does that rewrite, which is what
`python -m venv` actually creates on Windows.

The macOS render did not move, and that is checked rather than hoped for: the 29
rendered plists have the same sha256 before and after
(`7ed313342c5f5daf5faf3d31380a6d04c9a327c9061e97fad5e53f5a50ebcd7b`), `diff -r`
reports no differences, and the rebuild drill still passes from a fresh clone.

What is left is three jobs and a genuine absence in every case: `ExitTimeOut`
(no configurable SIGTERM-to-SIGKILL gap), `LimitLoadToSessionType`,
`SoftResourceLimits`, `WatchPaths` (no file-watch trigger), and two `PATH`
entries naming macOS-only directories. None of those can be closed from this
machine.

**None of this is a proved Windows rebuild.** No rendered task has been imported
on Windows and run. The XML parses and its element order matches what Task
Scheduler itself exports, which is not the same as Windows accepting it.
`drills/run.py --list` carries a `windows-rebuild` entry that says exactly that,
so the gap is on the board rather than in somebody's head.
