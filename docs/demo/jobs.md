# Demo: one job declaration, two operating systems

Real output, captured 2026-08-23. Every block below is what the command printed.

## What a job looks like now

```
$ python3 -c "import json;j=json.load(open('jobs/jobs.json'));print(json.dumps(j['ai.estate.consultd'],indent=2))"
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
in step: 29 declared jobs match the installed plists
```

## Rendered for Windows

```
$ jobs/render_windows.py --check
29 declared jobs: 26 cross to Windows intact, 3 lose something, 0 cannot be rendered at all
28 of them keep their environment and logs through a cmd.exe wrapper, which is a translation and not a loss

the same few things, counted:
      2 jobs   PATH names N POSIX directory(...) with no Windows equivalent, dropped from the search path
      2 jobs   ExitTimeOut
      2 jobs   LimitLoadToSessionType
      2 jobs   SoftResourceLimits
      1 jobs   SteamContentPaths
      1 jobs   WatchPaths

```

Three jobs still lose something and each line names what. Every one of those is
a launchd feature Task Scheduler does not have, so none of them can be closed
from this machine. The command is what counts them, so the number moves when the
work lands rather than when someone says it did.

## What a supervised job becomes

launchd's `KeepAlive` restarts a job on any exit. Task Scheduler's
`RestartOnFailure` only restarts on a non-zero one, so the rest of the
supervisor is the trigger: every task sets `MultipleInstancesPolicy` to
`IgnoreNew`, and a trigger that re-fires on a gap starts the job when it has
stopped and is ignored while it is still running.

```
$ iconv -f UTF-16 -t UTF-8 /tmp/wintasks/ai.architect.gateway.xml
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Repetition>
        <Interval>PT60S</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>/c "set "HERMES_HOME=%USERPROFILE%\dev\code\hermes-v2"&amp;&amp; set "PATH=%USERPROFILE%\dev\code\hermes-v2\hermes-agent\venv\bin;%USERPROFILE%\.kimi-code\bin;%USERPROFILE%\.local\bin;%USERPROFILE%\anaconda3\bin;%USERPROFILE%\anaconda3\condabin;~\.dotnet\tools;%USERPROFILE%\.cargo\bin;%USERPROFILE%\.rvm\bin;%USERPROFILE%\.claude\plugins\cache\claude-plugins-official\mattpocock-skills\1.2.3\bin"&amp;&amp; set "VIRTUAL_ENV=%USERPROFILE%\dev\code\hermes-v2\.venv"&amp;&amp; %USERPROFILE%\dev\code\hermes-v2\.venv\Scripts\python.exe -m hermes_cli.stderr_timestamp --error-log %USERPROFILE%\dev\code\hermes-v2\logs\gateway.error.log -- %USERPROFILE%\dev\code\hermes-v2\.venv\Scripts\python.exe -m hermes_cli.main gateway run --replace --external-supervisor &gt;&gt;"%USERPROFILE%\dev\code\hermes-v2\logs\gateway.log" 2&gt;&gt;"%USERPROFILE%\dev\code\hermes-v2\logs\gateway.error.log""</Arguments>
```

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

## What this demo does not show

A rendered task running on Windows. Nothing here has been imported with
`schtasks /Create /XML` on a real Windows host. The XML parses and its element
order matches what Task Scheduler itself exports, and that is not the same as
Windows accepting it. `drills/run.py --list` carries a `windows-rebuild` entry
saying exactly that, so the gap is on the board rather than in somebody's head.
