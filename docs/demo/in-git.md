# in-git, running

One command asks whether every load-bearing file on this machine is kept somewhere,
and answers in six classes. This is a real run, pasted with the command above it.

```
$ ~/.claude/scripts/estate/in-git.py
  runners   kept=35  holes=0
  declared  kept=10  holes=0
  repos     kept=2   holes=4
     HOLE  ~/.claude: 3 tracked file(s) edited and not committed
     HOLE  ~/.claude/scripts: 4 tracked file(s) edited and not committed
     HOLE  ~/dev/code/crew: checked out on 'docs/kimi-diagnosis', not 'main'; work committed here does not reach main
     HOLE  ~/dev/code/crew: 1 commit(s) never pushed
  mirrors   kept=0   holes=1
     HOLE  1 difference(s). LAW 24: run `tracked.py --pull`, then commit.
  secrets   kept=1   holes=0
  offsite   kept=19  holes=0
load-bearing holes: 5
exit=1
```

Read it top to bottom. `kept` is how many things that class checked and found kept.
`holes` is how many it could not account for. Every `HOLE` line names the file or the
repository and says what is wrong with it, so the next step never needs a second command.

The run above found five. Two are other sessions editing the laws and the settings file
while the sweep was running, which is the drift this class exists to catch: the live file
had moved ahead of the committed copy by about a minute. One is a checkout parked on a
branch that is not main, which is how one session's work gets committed where another
session cannot see it. That failure stranded five files earlier the same day, which is why
the check is there.

Exit status is 0 when every class is clean and 1 when anything is not, so the scheduler and
the founder's board both read the same answer.

## What arrives without anyone running it

The founder is never the one who types that command. `com.founder.ingit` runs it hourly and
messages Telegram when the set of holes changes, plus one green a day so silence never means
nobody checked. The board at http://127.0.0.1:8787 carries the same line, live.
