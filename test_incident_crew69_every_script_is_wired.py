"""crew#69: 31 of 59 scripts were reachable by nothing and read as live machinery.
Rung 4, incident test. Every non-test script here is in one honest state: wired into a
settings.json hook, scheduled by a LaunchAgent, on PATH (~/.local/bin), imported or invoked by
another script, or named in RETIRED below with the reason. A new script in none of those
states fails here. No silent miss: an unknown script is a failure, never a skip."""
import glob
import json
import os
import pathlib
import stat

HOME = pathlib.Path.home()
SCRIPTS = pathlib.Path(__file__).resolve().parent

# Scripts that are deliberately not wired, each with the reason and the crew item that may
# reverse it. Adding a line here is a decision, not a tidy-up.
RETIRED = {
    "consult-verify.sh": "one-off wrapper for hermes-v2/bin/verify-consult; retire with crew#69",
    "setup-kimi-bridge.sh": "one-off venv setup for the Kimi bridge; retire with crew#69",
}


def _states():
    hooks = json.dumps(json.load(open(HOME / ".claude" / "settings.json")))
    plists = "".join(open(f).read() for f in glob.glob(str(HOME / "Library/LaunchAgents/*.plist")))
    local_bin = HOME / ".local" / "bin"
    on_path = {p.name for p in local_bin.iterdir()} if local_bin.exists() else set()
    sources = {str(p.relative_to(SCRIPTS)): p.read_text(errors="ignore") for p in SCRIPTS.rglob("*")
               if p.is_file() and p.suffix != ".pyc" and ".wt-" not in str(p.relative_to(SCRIPTS)) and p.stat().st_size < 400_000}
    hook_dir = HOME / ".estate" / "guards"
    if hook_dir.exists():
        for p in hook_dir.rglob("*"):
            if p.is_file() and p.stat().st_size < 200_000:
                sources[f"estate:{p.name}"] = p.read_text(errors="ignore")
    out = {}
    for p in sorted(SCRIPTS.iterdir()):
        n = p.name
        if p.suffix not in (".py", ".sh") or not p.is_file() or n.startswith("test_"):
            continue
        if n in hooks:
            out[n] = "hook"
        elif n in plists:
            out[n] = "launchd"
        elif n in on_path:
            out[n] = "path"
        elif any(k != n and (n in t or n[:-3] in t) for k, t in sources.items()):
            out[n] = "called"
        elif n in RETIRED:
            out[n] = "retired"
        else:
            out[n] = "NONE"
    return out


def test_incident_crew69_no_script_is_reachable_by_nothing():
    states = _states()
    orphans = sorted(n for n, s in states.items() if s == "NONE")
    assert orphans == [], f"scripts in no state (wire, put on PATH, or add to RETIRED with a reason): {orphans}"


def test_incident_crew69_retired_list_names_only_real_files():
    stale = sorted(n for n in RETIRED if not (SCRIPTS / n).exists())
    assert stale == [], f"RETIRED names files that no longer exist, delete the lines: {stale}"


def test_incident_crew69_agents_md_names_resolve_on_path():
    import re
    import shutil
    names = sorted(set(re.findall(r"[a-z-]+\.py", (HOME / "AGENTS.md").read_text())))
    missing = [n for n in names if shutil.which(n) is None]
    assert missing == [], f"AGENTS.md tells sessions to run these by name and PATH cannot find them: {missing}"


def test_incident_crew69_scripts_on_path_are_executable():
    local_bin = HOME / ".local" / "bin"
    ours = [p for p in local_bin.iterdir() if p.is_symlink() and SCRIPTS.name in str(os.readlink(p))]
    bad = sorted(p.name for p in ours if not p.resolve().exists() or not p.resolve().stat().st_mode & stat.S_IXUSR)
    assert bad == [], f"symlinked into ~/.local/bin but dangling or not executable: {bad}"


# crew#69, second instance (2026-08-27): the PATH row was added to ~/.zshrc, which `zsh -c` never
# reads, so every agent Bash-tool call still got "command not found: founder-blocker.py". The
# laws name these two by bare filename (LAW 22, LAW 47); the shell agents run is `zsh -c`.
NAMED_IN_LAWS = ("founder-blocker.py", "pr-evidence.py")


def _resolves_in_zsh_c(name):
    import shutil
    import subprocess

    zsh = shutil.which("zsh")
    assert zsh, "zsh is the shell every agent Bash-tool call runs; it is missing here"
    return subprocess.run([zsh, "-c", f"command -v {name}"], capture_output=True, text=True).returncode == 0


def test_incident_crew69_law_named_scripts_resolve_in_a_zsh_c_shell():
    missing = [n for n in NAMED_IN_LAWS if not _resolves_in_zsh_c(n)]
    assert not missing, f"named by the laws as if on PATH, not found by `zsh -c command -v`: {missing}; the export belongs in ~/.zshenv, not ~/.zshrc"


def test_incident_crew69_the_probe_itself_can_fail():
    assert not _resolves_in_zsh_c("crew69-no-such-script.py")
