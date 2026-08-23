# Demo: one job declaration, two operating systems

Real output, captured 2026-08-23. Every block below is what the command printed.

## What a job looks like now

```
$ python3 -c "import json;j=json.load(open('jobs/jobs.json'));print(json.dumps(j['ai.estate.consultd'],indent=2))" | head -20
{
  "ProgramArguments": [
    "{PYTHON3_SYSTEM}",
    "{HOME}/.claude/scripts/consultd.py",
    "serve"
  ],
  "EnvironmentVariables": {
    "PATH": [
      "{HOME}/.local/bin",
      "/usr/local/bin",
      "/opt/homebrew/bin",
      "/usr/bin",
      "/bin",
      "/usr/sbin",
      "/sbin"
    ]
  }
}
```

No operating system appears in it. `{HOME}` is this account's home directory,
`{PYTHON3_SYSTEM}` is an interpreter, and the search path is a list of
directories rather than a string with a separator baked into it.

## Rendered for macOS

```
$ jobs/render.py --check
    com.founder.ingit
in step: 29 declared jobs match the installed plists
```

## Rendered for Windows

```
$ jobs/render_windows.py --check
29 declared jobs: 12 cross to Windows intact, 17 lose something, 0 cannot be rendered at all
28 of them keep their environment and logs through a cmd.exe wrapper, which is a translation and not a loss

the same few things, counted:
      9 jobs   Nice
      6 jobs   KeepAlive is a supervisor that restarts on ANY exit
      6 jobs   ThrottleInterval
      4 jobs   ProcessType
      2 jobs   PATH names N POSIX directory(...) with no Windows equivalent, dropped from the search path
      2 jobs   ExitTimeOut
      2 jobs   LimitLoadToSessionType
      2 jobs   SoftResourceLimits
      2 jobs   LowPriorityIO
      1 jobs   StartCalendarInterval Weekday rendered as a daily trigger
      1 jobs   SteamContentPaths
      1 jobs   WatchPaths

```

That list is the honest state of a Windows rebuild. Every line is a guarantee
the manifest makes that Task Scheduler does not keep. The command is what counts
them, so the number moves when the work lands rather than when someone says it
did.

## The task files it produces

```
$ jobs/render_windows.py --write --into /tmp/wintasks
wrote 29 task files into /tmp/wintasks
import each with:  schtasks /Create /TN "<label>" /XML <label>.xml

$ python3 -c "check every file parses, and list the commands"
XML files that parse: 29, malformed: 0
commands emitted: {'cmd.exe': 28, '%USERPROFILE%\\Library\\Application Support\\Steam\\SteamApps\\steamclean': 1}
any POSIX command left: none
```

## Proof the macOS side did not move

The manifest changed shape. The plists it generates did not, and that is checked
rather than hoped for: the same 29 files, rendered before and after the change,
have the same checksum.

```
$ ( cd /tmp/wf_before && shasum -a256 *.plist | shasum -a256 )
7ed313342c5f5daf5faf3d31380a6d04c9a327c9061e97fad5e53f5a50ebcd7b  -
$ ( cd /tmp/wf_after  && shasum -a256 *.plist | shasum -a256 )
7ed313342c5f5daf5faf3d31380a6d04c9a327c9061e97fad5e53f5a50ebcd7b  -
$ diff -r /tmp/wf_before /tmp/wf_after
(no output: no differences in 29 files)
```

The second angle is a clone. The rebuild drill pulls both repositories into an
empty home and renders the jobs there:

```
$ rebuild/drill.sh
  ok    no plist carries another machine's home (0)
  ok    every declared job rendered for this home (29)
  ok    the laws symlink resolves (# The laws)
  ok    the guards came with the clone (yes)
  ok    the commit gate came with the clone (yes)
  ok    no credential was restored (0)
  files rebuilt: 1885
  THE SCORE:     14 manual steps
DRILL PASSED
```
