"""Incident test. 2026-08-27 23:30 -> 2026-08-28 08:15, crew#516: The Architect went silent on
Telegram for 8h45m because two pollers held one bot token. The gateway had moved to the cluster and
a launchd poller was still running on the laptop; one token admits one poller, so the laptop held
the bot and every message went to a process that could not answer it.

Parking the plist did not hold -- a peer session rewrote it within minutes, because hermes-v2's own
verifier failed when the plist was absent and its onboarding doc printed the bootstrap command. That
half is fixed in hermes-v2. This half does not depend on anyone reading a document: rule
second_telegram_poller in policy/command.rego refuses the command itself. Founder, 2026-08-28: "we
leaving traps again, why not solve once and for all ... next session will fuck it up again".
Proved both ways."""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rule_guard", HERE / "rule-guard.py")
rg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rg)


def _verdict(cmd: str):
    return rg.decide(cmd)


def test_incident_starting_a_gateway_on_this_mac_is_refused_and_names_the_cluster():
    for cmd in (
        "launchctl bootstrap gui/501 ~/Library/LaunchAgents/ai.architect.gateway.plist",
        "launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/ai.hermes.gateway.plist",
        "launchctl load -w ~/Library/LaunchAgents/ai.architect.gateway.plist",
        "launchctl start ai.architect.gateway",
        "cd ~/dev/code/hermes-v2 && .venv/bin/python -m hermes_cli.main gateway run --replace",
    ):
        v = _verdict(cmd)
        assert v is not None, cmd
        assert "hermes-agent-gateway" in v[1], cmd


def test_incident_stopping_one_and_looking_at_the_real_one_are_never_refused():
    """LAW 38: a guard that refuses correct work is an outage. Booting the Mac poller out is the
    fix, not the mistake, and reading the cluster's own gateway must never need a marker."""
    for cmd in (
        "launchctl bootout gui/501/ai.architect.gateway",
        "launchctl list | grep gateway",
        "launchctl print gui/501/ai.architect.gateway",
        "bin/idp-kube -n hermes-agent logs deploy/hermes-agent-gateway",
        "bin/idp-kube -n hermes-agent rollout restart deploy/hermes-agent-gateway",
        "launchctl bootstrap gui/501 ~/Library/LaunchAgents/ai.estate.scheduler.plist",
        "launchctl bootstrap gui/501 ~/Library/LaunchAgents/ai.architect.gateway.plist  # second-poller-intended",
    ):
        assert _verdict(cmd) is None, cmd
