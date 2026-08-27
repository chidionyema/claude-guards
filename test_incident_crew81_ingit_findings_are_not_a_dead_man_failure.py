"""crew#81 (rung 4): com.founder.ingit exits 1 whenever the estate has a hole, which is most of the
time while anyone is mid-work. Through hc-wrap.sh that exit failed the dead-man (liveness) check,
so 'instrument dead' and 'findings present' were one red light. hc-wrap.sh already splits the two
when a job declares HC_FINDINGS_EXIT; the job never opted in. The rule: a job whose wrapped
command reports findings by exit code must declare that code, so liveness stays green and the
findings land on <slug>-findings."""
import os
import plistlib
import re
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PLIST = os.path.join(HERE, "launchagents", "com.founder.ingit.plist")


def findings_exit_jobs():
    """The jobs hc-wrap.sh's own header names as 'prints a finding and exits 1'. crew#425
    follow-on, 2026-08-27: ingit was opted in by cg#126 while lawenforcement and sciencecollect,
    named two lines apart in the same comment, still sat at exit 1 on the liveness board. The
    class is every job the wrapper documents as findings-exit, not the one file being edited."""
    text = open(os.path.join(HERE, "hc-wrap.sh")).read()
    named = set(re.findall(r"(com\.founder\.\w+) prints .*? and exits 1", text, re.S))
    return sorted(named | {"com.founder.ingit"})


def declares_findings_exit(plist_path):
    d = plistlib.load(open(plist_path, "rb"))
    return (d["ProgramArguments"][0].endswith("hc-wrap.sh")
            and d.get("EnvironmentVariables", {}).get("HC_FINDINGS_EXIT", "").split() == ["1"])


def test_every_documented_findings_exit_job_declares_it():
    jobs = findings_exit_jobs()
    assert {"com.founder.ingit", "com.founder.lawenforcement", "com.founder.sciencecollect"} <= set(jobs)
    missing = [j for j in jobs if not declares_findings_exit(os.path.join(HERE, "launchagents", j + ".plist"))]
    assert missing == []


def test_rule_refuses_a_plist_without_the_declaration(tmp_path):
    """The other way: the same plist with the line removed is refused."""
    d = plistlib.load(open(PLIST, "rb"))
    del d["EnvironmentVariables"]["HC_FINDINGS_EXIT"]
    bad = tmp_path / "x.plist"
    plistlib.dump(d, open(bad, "wb"))
    assert declares_findings_exit(PLIST) and not declares_findings_exit(bad)


def test_hc_wrap_keeps_liveness_green_on_a_declared_finding(tmp_path):
    """Both ways in one run: a declared finding pings liveness /0 and findings /fail;
    an undeclared code (2) pings liveness with the crash code."""
    log = tmp_path / "pings"
    fake_curl = tmp_path / "curl"
    fake_curl.write_text('#!/bin/sh\nfor a in "$@"; do :; done\necho "$a" >> "%s"\n' % log)
    fake_curl.chmod(0o755)
    home = tmp_path / "home"
    (home / ".estate" / "healthchecks").mkdir(parents=True)
    (home / ".estate" / "healthchecks" / "ping_key").write_text("k")
    env = dict(os.environ, HOME=str(home), PATH=f"{tmp_path}:{os.environ['PATH']}",
               HC_BASE="http://hc.test/ping", HC_FINDINGS_EXIT="1")
    wrap = os.path.join(HERE, "hc-wrap.sh")
    rc = subprocess.run([wrap, "ingit", "sh", "-c", "exit 1"], env=env).returncode
    assert rc == 1
    assert log.read_text().splitlines()[-2:] == [
        "http://hc.test/ping/k/ingit/0", "http://hc.test/ping/k/ingit-findings/fail?create=1"]
    rc = subprocess.run([wrap, "ingit", "sh", "-c", "exit 2"], env=env).returncode
    assert rc == 2
    assert log.read_text().splitlines()[-1] == "http://hc.test/ping/k/ingit/2"
