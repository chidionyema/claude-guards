"""crew#81 (rung 4): com.founder.ingit exits 1 whenever the estate has a hole, which is most of the
time while anyone is mid-work. Through hc-wrap.sh that exit failed the dead-man (liveness) check,
so 'instrument dead' and 'findings present' were one red light. hc-wrap.sh already splits the two
when a job declares HC_FINDINGS_EXIT; the job never opted in. The rule: a job whose wrapped
command reports findings by exit code must declare that code, so liveness stays green and the
findings land on <slug>-findings."""
import os
import plistlib
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PLIST = os.path.join(HERE, "launchagents", "com.founder.ingit.plist")


def test_ingit_declares_its_findings_exit_code():
    d = plistlib.load(open(PLIST, "rb"))
    assert d["ProgramArguments"][0].endswith("hc-wrap.sh")
    assert d["EnvironmentVariables"]["HC_FINDINGS_EXIT"].split() == ["1"]


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
