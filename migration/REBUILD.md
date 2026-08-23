# Could we rebuild this estate on a new machine in one shot?

Measured 2026-08-23. Every number below came from a command, not from memory.

## The answer is no, and here is the size of the no

| what | measurement | why it stops a rebuild |
|---|---|---|
| this machine's name is compiled in | 188 occurrences across 35 files, 158 of them inside job definitions | a different username breaks every scheduled job |
| the scheduler is macOS only | 33 files know about `launchd` | Windows has no equivalent; nothing renders to one |
| `~/.claude` has no remote | 1029 tracked files, 128 uncommitted, last commit 35h ago | a disk failure loses it all; there is no second copy |
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

**1. STILL OPEN, and it is the founder's call. Give `~/.claude` a remote.** It is the largest single loss risk and
the smallest fix. 1029 files exist in exactly one place.

   This is a founder decision, not an agent one. That repository contains
   conversation transcripts and project memory. Pushing it anywhere is
   publishing it. It needs a private remote and an explicit yes.

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

A rebuild that has never been drilled is a hope, by LAW 19. The drill is a
throwaway user account on this same Mac: run the bootstrap, count the manual
steps, and the count is the score. Anything above the sign-ins is the backlog.


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

**The drill is still not run.** A throwaway user account on this Mac, the
bootstrap, and a count of the manual steps. Until that number exists this is a
better hope than yesterday's, and still a hope.
