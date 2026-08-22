#!/usr/bin/env python3
"""MAESTRO DEPUTY v1.0 -- the state machine. Sense, decide under the laws, act, verify, learn."""

import os
import sys
import json
import time
import sqlite3
import hashlib
import logging
import subprocess
import threading
from enum import Enum, auto
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any, Callable, Tuple
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from models import Config, logger, State, Priority, Episode, Shape, Skill, Intent

from graph import ExperienceGraph
from laws import LawViolation, LawMiddleware
from shapes import ShapeExtractor
import board

# ───────────────────────────────────────────────────────────────────────────────
# TELEGRAM BRIDGE
# ───────────────────────────────────────────────────────────────────────────────

class TelegramBridge:
    def __init__(self, token: str, chat_id: str, graph: ExperienceGraph):
        self.token = token
        self.chat_id = chat_id
        self.graph = graph
        self.enabled = bool(token and chat_id)

    def send(self, message: str, priority: Priority = Priority.P2) -> bool:
        if not self.enabled:
            logger.info(f"[TELEGRAM would send]: {message}")
            return True
        if priority == Priority.P3:
            return True

        try:
            import urllib.request
            import urllib.parse
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    def send_digest(self, stats: Dict, incidents: List[Dict], needs_human: List[Dict]) -> bool:
        lines = [
            "🏠 *Estate Digest*",
            f"\n📊 Stats: {stats['total_episodes']} episodes, "
            f"{stats['total_shapes']} shapes, {stats['total_skills']} skills",
            f"💰 Today: ${stats['today_spend_usd']:.2f} / ${Config.MAX_DAILY_SPEND_USD:.0f}",
        ]

        if needs_human:
            lines.append(f"\n⚠️ *Need you: {len(needs_human)}*")
            for item in needs_human:
                lines.append(f"  • {item['description']}")

        if incidents:
            lines.append(f"\n✅ *Auto-resolved: {len(incidents)}*")
            for inc in incidents:
                lines.append(f"  • {inc['description']}")

        if not needs_human and not incidents:
            lines.append("\n✅ All clear. Nothing needs you.")

        return self.send("\n".join(lines), Priority.P2)

    def poll_commands(self) -> List[Dict]:
        if not self.enabled:
            return []
        try:
            import urllib.request
            url = f"https://api.telegram.org/bot{self.token}/getUpdates?offset=-10"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
                commands = []
                for update in data.get("result", []):
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    if text.startswith("/"):
                        commands.append({
                            "command": text.split()[0],
                            "args": text.split()[1:],
                            "from": msg.get("from", {}).get("id"),
                            "timestamp": msg.get("date")
                        })
                return commands
        except Exception as e:
            logger.error(f"Telegram poll failed: {e}")
            return []


# ───────────────────────────────────────────────────────────────────────────────
# ESTATE SENSORS
# ───────────────────────────────────────────────────────────────────────────────

class EstateSensors:
    def __init__(self):
        self.audit_path = os.path.expanduser(Config.ESTATE_AUDIT_PATH)

    # estate_audit.py writes {"generated_at", "counts", "rows"} where a row is
    # {domain,title,value,severity,proof,detail} and severity is one of
    # critical|warn|unknown|ok. Maestro speaks findings with ids, lanes and P-levels.
    # This method is the whole interface between the two minds. Nothing else crosses.
    SEVERITY_MAP = {"critical": "P1", "warn": "P2", "unknown": "P3"}
    STALE_HOURS = float(os.getenv("MAESTRO_AUDIT_STALE_H", "3"))

    def read_audit(self) -> List[Dict]:
        if not os.path.exists(self.audit_path):
            logger.warning(f"Audit file not found: {self.audit_path}")
            return []
        try:
            with open(self.audit_path) as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read audit: {e}")
            return []

        findings = []

        # An audit nobody refreshed is not evidence. Say so rather than trusting it.
        age_h = (time.time() - float(data.get("generated_at", 0))) / 3600.0
        if age_h > self.STALE_HOURS:
            findings.append({
                "id": "audit_stale",
                "lane": "estate",
                "severity": "P1",
                "check": "audit_freshness",
                "description": f"The estate audit is {age_h:.1f}h old; the sensors are not reporting",
                "context": {"path": self.audit_path, "age_hours": round(age_h, 1),
                            "expected_within_hours": self.STALE_HOURS},
            })

        for row in data.get("rows", []):
            sev = self.SEVERITY_MAP.get(str(row.get("severity", "")).lower())
            if not sev:                       # "ok" and anything unrecognised are not work
                continue
            domain = row.get("domain", "estate")
            title = row.get("title", "untitled check")
            findings.append({
                "id": hashlib.sha256(f"{domain}|{title}".encode()).hexdigest()[:12],
                "lane": "estate",
                "severity": sev,
                "check": f"{domain}/{title}",
                "description": title,
                "context": {
                    "domain": domain,
                    "value": row.get("value"),
                    "proof": row.get("proof"),
                    "detail": row.get("detail"),
                },
            })
        logger.info(f"audit: {len(findings)} findings from {len(data.get('rows', []))} rows")
        return findings

    def check_bridges(self) -> List[Dict]:
        findings = []
        bridges = [("kimi-bridge", 8765), ("deepseek-bridge", 8767), ("ollama", 11434)]
        for name, port in bridges:
            try:
                import socket
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex(("127.0.0.1", port))
                sock.close()
                if result != 0:
                    findings.append({
                        "id": f"bridge-down-{name}",
                        "severity": "P1",
                        "lane": "estate",
                        "description": f"{name} not responding on port {port}",
                        "auto_fix": True,
                        "skill": "restart_bridge",
                        "context": {"bridge_name": name, "port": port}
                    })
            except Exception as e:
                logger.error(f"Bridge check failed for {name}: {e}")
        return findings

    def check_disk(self) -> List[Dict]:
        findings = []
        try:
            # Percent-used is not a usable signal on APFS. statvfs f_bfree and
            # f_bavail both exclude purgeable space, so this machine reads 95.9%
            # while `df -h /` reads 40% -- a P0 crisis every 60 seconds on a disk
            # with 19 GiB free. Free bytes is the same number under both
            # accountings, so alert on that and report percent for context only.
            stat = os.statvfs("/")
            free_gb = stat.f_bavail * stat.f_frsize / (1024 ** 3)
            percent = (stat.f_blocks - stat.f_bfree) / stat.f_blocks * 100
            if free_gb < Config.DISK_FREE_GB_CRITICAL:
                findings.append({
                    "id": "disk-critical",
                    "severity": "P0",
                    "lane": "estate",
                    "description": f"Disk has {free_gb:.1f} GiB free ({percent:.1f}% used)",
                    "auto_fix": True,
                    "skill": "disk_cleanup",
                    "context": {"free_gb": free_gb, "percent": percent,
                                "threshold_gb": Config.DISK_FREE_GB_CRITICAL}
                })
            elif free_gb < Config.DISK_FREE_GB_WARNING:
                findings.append({
                    "id": "disk-warning",
                    "severity": "P1",
                    "lane": "estate",
                    "description": f"Disk has {free_gb:.1f} GiB free ({percent:.1f}% used)",
                    "auto_fix": True,
                    "skill": "disk_cleanup",
                    "context": {"free_gb": free_gb, "percent": percent,
                                "threshold_gb": Config.DISK_FREE_GB_WARNING}
                })
        except Exception as e:
            logger.error(f"Disk check failed: {e}")
        return findings

    def check_credentials(self) -> List[Dict]:
        findings = []
        history_paths = [
            os.path.expanduser("~/.bash_history"),
            os.path.expanduser("~/.zsh_history"),
            os.path.expanduser("~/.claude/history.jsonl"),
        ]
        patterns = [
            (r"sk-ant-api[0-9a-zA-Z-_]{100,}", "Anthropic API key"),
            (r"sk_live_[a-zA-Z0-9]{40,}", "Stripe live key"),
            (r"hf_[a-zA-Z0-9]{30,}", "HuggingFace token"),
            (r"ghp_[a-zA-Z0-9]{36,}", "GitHub token"),
        ]

        for hist_path in history_paths:
            if not os.path.exists(hist_path):
                continue
            try:
                with open(hist_path, "rb") as f:
                    content = f.read().decode("utf-8", errors="ignore")
                    for pattern, name in patterns:
                        import re
                        if re.search(pattern, content):
                            findings.append({
                                "id": f"credential-leak-{name.lower().replace(' ', '-')}",
                                "severity": "P0",
                                "lane": "estate",
                                "description": f"{name} found in {hist_path}",
                                "auto_fix": False,
                                "skill": "credential_rotation",
                                "context": {"file": hist_path, "key_type": name}
                            })
            except Exception as e:
                logger.error(f"Credential scan failed for {hist_path}: {e}")
        return findings

    def sense(self) -> List[Dict]:
        findings = []
        findings.extend(self.read_audit())
        findings.extend(self.check_bridges())
        findings.extend(self.check_disk())
        findings.extend(self.check_credentials())
        return findings


# ───────────────────────────────────────────────────────────────────────────────
# SKILL EXECUTOR
# ───────────────────────────────────────────────────────────────────────────────

class SkillExecutor:
    ALLOWED_PATHS = [
        os.path.expanduser("~/.estate"),
        os.path.expanduser("~/.maestro"),
        os.path.expanduser("~/prospector"),
        os.path.expanduser(Config.SKILLS_DIR),
        "/tmp",
    ]

    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+/",
        r"rm\s+-rf\s+~",
        r":\s*\{\s*:\s*\}\s*;\s*while",
        r"mkfs\.",
        r"dd\s+if=.*of=/dev/",
    ]

    def __init__(self, graph: ExperienceGraph):
        self.graph = graph

    def execute(self, skill: Skill, context: Dict) -> Tuple[bool, Dict]:
        start = time.time()
        evidence = {"skill_id": skill.id, "context": context}

        if not self._path_safe(skill.procedure):
            return False, {**evidence, "error": "Path violation", "blocked": True}

        if self._dangerous_detected(skill.procedure):
            return False, {**evidence, "error": "Dangerous pattern detected", "blocked": True}

        try:
            if skill.procedure.startswith("shell:"):
                cmd = skill.procedure.replace("shell:", "").strip()
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=300, cwd=context.get("cwd", "/tmp")
                )
                success = result.returncode == 0
                evidence["stdout"] = result.stdout[:2000]
                evidence["stderr"] = result.stderr[:2000]
                evidence["returncode"] = result.returncode
            elif skill.procedure.startswith("skill:"):
                # A vetted procedure file inside SKILLS_DIR. Named, reviewable, in git.
                name = skill.procedure.split(":", 1)[1].strip()
                path = os.path.join(os.path.expanduser(Config.SKILLS_DIR), f"{name}.py")
                if not os.path.isfile(path):
                    raise FileNotFoundError(f"skill file missing: {path}")
                result = subprocess.run(
                    [sys.executable, path, "--json"], capture_output=True, text=True,
                    timeout=300, cwd=context.get("cwd", "/tmp"),
                    env={**os.environ, "MAESTRO_CONTEXT": json.dumps(context)},
                )
                success = result.returncode == 0
                evidence["skill_file"] = path
                evidence["stdout"] = result.stdout[:2000]
                evidence["stderr"] = result.stderr[:2000]
                evidence["returncode"] = result.returncode
            elif skill.procedure.startswith("python:"):
                code = skill.procedure.replace("python:", "").strip()
                namespace = {"__builtins__": {}}
                exec(code, namespace)
                success = namespace.get("__result__", False)
                evidence["result"] = success
            else:
                success = False
                evidence["error"] = f"Unknown procedure type: {skill.procedure[:50]}"

            duration_ms = int((time.time() - start) * 1000)
            evidence["duration_ms"] = duration_ms

            skill.total_uses += 1
            skill.last_used = datetime.utcnow().isoformat()
            skill.avg_duration_ms = int(
                (skill.avg_duration_ms * (skill.total_uses - 1) + duration_ms) / skill.total_uses
            )
            if success:
                skill.success_rate = (skill.success_rate * (skill.total_uses - 1) + 1.0) / skill.total_uses
            else:
                skill.success_rate = (skill.success_rate * (skill.total_uses - 1)) / skill.total_uses

            self.graph.upsert_skill(skill)
            return success, evidence

        except Exception as e:
            evidence["error"] = str(e)
            evidence["duration_ms"] = int((time.time() - start) * 1000)
            return False, evidence

    def _path_safe(self, procedure: str) -> bool:
        suspicious = ["/etc/", "/usr/", "/bin/", "/sbin/", "/var/", "/home/"]
        for s in suspicious:
            if s in procedure and not any(a in procedure for a in self.ALLOWED_PATHS):
                return False
        return True

    def _dangerous_detected(self, procedure: str) -> bool:
        import re
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, procedure):
                return True
        return False


# ───────────────────────────────────────────────────────────────────────────────
# THE MAESTRO
# ───────────────────────────────────────────────────────────────────────────────

class Maestro:
    def __init__(self):
        self.board_enabled = os.getenv("MAESTRO_BOARD", "1") != "0"
        self.unacked_p0s = []
        # A first run against a 47-row audit would otherwise open 22 issues at once.
        # The cap is per tick, never silent: what it held back is counted and reported.
        self.board_max_new = int(os.getenv("MAESTRO_BOARD_MAX_NEW", "5"))
        self._board_new_this_tick = 0
        self._board_suppressed = 0
        self.db = ExperienceGraph(Config.DB_PATH)
        self.extractor = ShapeExtractor(self.db)
        self.bridge = TelegramBridge(Config.TELEGRAM_TOKEN, Config.TELEGRAM_CHAT_ID, self.db)
        self.sensors = EstateSensors()
        self.executor = SkillExecutor(self.db)
        self.state = State.IDLE
        self.current_intent: Optional[Intent] = None
        self.crisis_mode = False
        # Was: utcnow() - 25h. That made every fresh process go IDLE -> META_REVIEW
        # and stop there, so `--once` could never reach SENSE and the dry test only
        # ever exercised one branch. The timestamp is durable now: a restart resumes
        # the real schedule, and a first-ever run senses before it reviews itself.
        _last = self.db.kv_get("last_meta_review")
        self.last_meta_review = (
            datetime.fromisoformat(_last) if _last else datetime.utcnow()
        )
        self.daily_findings: List[Dict] = []
        self.daily_resolved: List[Dict] = []
        self.daily_needs_human: List[Dict] = []
        self._seed_invariants()

    def _seed_invariants(self):
        laws = ["LAW_CONTEXT", "LAW_DEGREE", "LAW_BASELINE",
                "LAW_TRADEOFF", "LAW_RIPPLE", "LAW_MECHANISM", "LAW_SOURCE"]
        with sqlite3.connect(self.db.db_path) as conn:
            for law in laws:
                conn.execute("""
                    INSERT OR IGNORE INTO invariants (id, law_name, last_enforced)
                    VALUES (?, ?, ?)
                """, (law, law, datetime.utcnow().isoformat()))

    def _board(self, fn, *args, **kwargs):
        """The board is a bus, not a dependency. A GitHub outage must not stop the deputy."""
        if not self.board_enabled:
            return None
        try:
            return fn(*args, **kwargs)
        except Exception as exc:                                      # noqa: BLE001
            logger.warning(f"board unreachable, continuing headless: {exc}")
            return None

    def _new_intent(self, trigger: str) -> Intent:
        self.current_intent = Intent(
            id=f"INTENT-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{hashlib.sha256(trigger.encode()).hexdigest()[:8]}",
            timestamp=datetime.utcnow().isoformat(),
            trigger=trigger,
            state_transitions=["IDLE"]
        )
        return self.current_intent

    def _transition(self, new_state: State):
        self.state = new_state
        if self.current_intent:
            self.current_intent.state_transitions.append(new_state.name)
        logger.info(f"State: {new_state.name}")

    def _save_intent(self):
        if not self.current_intent:
            return
        intent_dir = os.path.expanduser(Config.INTENT_LOG_DIR)
        os.makedirs(intent_dir, exist_ok=True)
        path = os.path.join(intent_dir, f"{self.current_intent.id}.json")
        with open(path, "w") as f:
            json.dump(asdict(self.current_intent), f, indent=2, default=str)

    def tick(self):
        try:
            if self.state == State.IDLE:
                self._do_idle()
            elif self.state == State.SENSE:
                self._do_sense()
            elif self.state == State.ORIENT:
                self._do_orient()
            elif self.state == State.DECIDE:
                self._do_decide()
            elif self.state == State.ACT:
                self._do_act()
            elif self.state == State.VERIFY:
                self._do_verify()
            elif self.state == State.REPORT:
                self._do_report()
            elif self.state == State.CRISIS:
                self._do_crisis()
            elif self.state == State.META_REVIEW:
                self._do_meta_review()
        except Exception as e:
            logger.exception("Tick failed")
            self._transition(State.IDLE)
            self._save_intent()

    def _do_idle(self):
        self._new_intent("periodic_tick")
        if self.crisis_mode:
            self._transition(State.CRISIS)
            return
        if datetime.utcnow() - self.last_meta_review > timedelta(hours=Config.META_REVIEW_INTERVAL_HOURS):
            self._transition(State.META_REVIEW)
            return
        self._transition(State.SENSE)

    def _do_sense(self):
        self._board_new_this_tick = 0
        self._board_suppressed = 0
        findings = self.sensors.sense()
        self.daily_findings.extend(findings)
        p0s = [f for f in findings if f.get("severity") == "P0"]
        # A P0 the founder already holds on the board is not a fresh crisis.
        # Without this, three standing P0s freeze the deputy forever and the
        # remaining findings are never sensed at all.
        self.unacked_p0s = [f for f in p0s
                            if not self._board(board.acknowledged, f)]
        if p0s and not self.unacked_p0s:
            logger.info(f"{len(p0s)} P0(s) already on the board in needs-chidi; "
                        f"continuing to the rest of the estate")
        if self.unacked_p0s:
            self.crisis_mode = True
            self._transition(State.CRISIS)
            return
        if findings:
            self._transition(State.ORIENT)
        else:
            self._transition(State.REPORT)

    def _do_orient(self):
        intent = self.current_intent
        intent.orient_analysis["findings"] = len(self.daily_findings)
        intent.orient_analysis["shapes_matched"] = 0
        intent.orient_analysis["novel"] = 0

        for finding in self.daily_findings:
            prevention = self.extractor.find_prevention(
                finding["description"], finding.get("lane", "estate")
            )
            if prevention:
                finding["prevention_skill"] = prevention.id
                finding["prevention_available"] = True
                intent.orient_analysis["shapes_matched"] += 1
            else:
                episode = Episode(
                    id=f"EP-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{hashlib.sha256(finding['id'].encode()).hexdigest()[:6]}",
                    timestamp=datetime.utcnow().isoformat(),
                    lane=finding.get("lane", "estate"),
                    trigger=finding["description"],
                    action="detected",
                    outcome="unknown"
                )
                shape = self.extractor.extract(episode)
                if shape:
                    finding["shape_extracted"] = shape.id
                    intent.orient_analysis["shapes_matched"] += 1
                else:
                    intent.orient_analysis["novel"] += 1

            if self._board_new_this_tick >= self.board_max_new:
                self._board_suppressed += 1
                continue
            num = self._board(board.open_finding, finding, board.BACKLOG)
            if num:
                self._board_new_this_tick += 1
                finding["issue"] = num
                shape = finding.get("shape_extracted") or finding.get("prevention_skill")
                self._board(board.move, num, board.TRIAGE,
                            f"Triaged. Shape: `{shape}`." if shape else "Triaged. Novel -- no shape matched yet.")

        self._transition(State.DECIDE)

    def _do_decide(self):
        intent = self.current_intent
        intent.decision["auto_fix"] = []
        intent.decision["queue"] = []
        intent.decision["escalate"] = []

        for finding in self.daily_findings:
            lane = finding.get("lane", "estate")
            lane_config = Config.LANES.get(lane, Config.LANES["estate"])

            plan = {
                "domain": lane,
                "assessments": {
                    "severity": {"value": finding.get("severity", "P2"), "threshold": "P1", "rate": "static"}
                },
                "baseline": "previous_state_normal",
                "tradeoffs": [{"cost": "time", "probability": 0.3, "impact": "delay"}],
                "ripple_effects": [{"effect": "service_restart", "then": {"effect": "brief_downtime"}}],
                "mechanism": finding.get("skill", "unknown") + " execution with verification",
                "sources": [{"source": "estate_audit", "retrieval_date": datetime.utcnow().isoformat(), "confidence": 0.9}]
            }

            try:
                laws = LawMiddleware.validate(plan, {"allowed_domains": list(Config.LANES.keys())}, self.db)
                intent.laws_applied.extend(laws)
            except LawViolation as e:
                intent.laws_violated.append({"law": e.law_name, "reason": e.reason})
                finding["route"] = "escalate"
                finding["reason"] = f"Law violation: {e.law_name}"
                intent.decision["escalate"].append(finding)
                continue

            if finding.get("severity") == "P0":
                finding["route"] = "escalate"
                intent.decision["escalate"].append(finding)
            elif finding.get("auto_fix") and lane_config["auto_fix"]:
                finding["route"] = "auto_fix"
                intent.decision["auto_fix"].append(finding)
            else:
                finding["route"] = "queue"
                intent.decision["queue"].append(finding)

        for finding in self.daily_findings:
            num = finding.get("issue")
            if not num:
                continue
            route = finding.get("route")
            if route == "auto_fix":
                self._board(board.move, num, board.AUTO_FIX,
                            f"Reversible, skill `{finding.get('skill', 'generic_fallback')}` available. Executing.")
            else:
                self._board(board.move, num, board.NEEDS_CHIDI,
                            f"Held for your tap. Reason: {finding.get('reason', route or 'not auto-fixable')}.")

        self._transition(State.ACT)

    def _do_act(self):
        intent = self.current_intent
        intent.execution["results"] = []

        for finding in intent.decision.get("auto_fix", []):
            skill_id = finding.get("skill", "generic_fallback")
            skill = self.db.get_skill(skill_id)

            if not skill:
                skill = Skill(
                    id=skill_id,
                    name=f"Auto-generated fix for {finding['id']}",
                    lane=finding.get("lane", "estate"),
                    trigger_pattern=finding["description"],
                    procedure=f"shell: echo 'Fix for {finding['id']}'",
                    created_from_shape=finding.get("shape_extracted")
                )
                self.db.upsert_skill(skill)

            success, evidence = self.executor.execute(skill, finding.get("context", {}))
            intent.execution["results"].append({
                "finding_id": finding["id"],
                "skill_id": skill.id,
                "success": success,
                "evidence": evidence
            })

            num = finding.get("issue")
            if num:
                self._board(board.post_intent, num, {
                    "id": intent.id, "state": self.state.name,
                    "laws_applied": intent.laws_applied,
                    "hypothesis": f"skill `{skill.id}` resolves: {finding['description']}",
                    "evidence": evidence,
                })

            if success:
                self.daily_resolved.append(finding)
                if num:
                    self._board(board.move, num, board.VERIFY, "Executed. Re-sensing to confirm it held.")
            else:
                finding["route"] = "escalate"
                finding["auto_fix_failed"] = True
                self.daily_needs_human.append(finding)
                if num:
                    self._board(board.move, num, board.NEEDS_CHIDI,
                                "Auto-fix ran and did not hold. Output is in the INTENT comment above.")

        for finding in intent.decision.get("queue", []):
            self.daily_needs_human.append(finding)

        for finding in intent.decision.get("escalate", []):
            self.daily_needs_human.append(finding)

        self._transition(State.VERIFY)

    def _do_verify(self):
        intent = self.current_intent
        intent.verification["checks"] = []
        recheck = self.sensors.sense()
        remaining_ids = {f["id"] for f in recheck}

        for result in intent.execution.get("results", []):
            if result["success"]:
                if result["finding_id"] not in remaining_ids:
                    intent.verification["checks"].append({
                        "finding_id": result["finding_id"],
                        "status": "verified_fixed"
                    })
                else:
                    intent.verification["checks"].append({
                        "finding_id": result["finding_id"],
                        "status": "fix_failed_still_present"
                    })
                    self.daily_needs_human.append(next(
                        f for f in self.daily_resolved if f["id"] == result["finding_id"]
                    ))

        self._transition(State.REPORT)

    def _do_report(self):
        stats = self.db.get_stats()
        if self._board_suppressed:
            logger.warning(
                f"board cap: {self._board_new_this_tick} issues opened this tick, "
                f"{self._board_suppressed} findings held back (MAESTRO_BOARD_MAX_NEW="
                f"{self.board_max_new}); they are still in the audit and will board on later ticks")

        if self.daily_needs_human:
            self.bridge.send_digest(stats, self.daily_resolved, self.daily_needs_human)
        elif self.daily_resolved:
            self.bridge.send(f"✅ Auto-resolved {len(self.daily_resolved)} issues. All clear.", Priority.P3)
        else:
            logger.info("All clear — no digest sent (P3)")

        for finding in self.daily_resolved:
            if finding.get("issue"):
                self._board(board.move, finding["issue"], board.DONE,
                            "Verified by re-sense. Logged to the experience graph.")
            self.db.log_episode(Episode(
                id=f"EP-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{finding['id']}",
                timestamp=datetime.utcnow().isoformat(),
                lane=finding.get("lane", "estate"),
                trigger=finding["description"],
                action="auto_fix",
                outcome="success",
                evidence=finding.get("context", {}),
                shape_id=finding.get("shape_extracted")
            ))

        for finding in self.daily_needs_human:
            self.db.log_episode(Episode(
                id=f"EP-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{finding['id']}",
                timestamp=datetime.utcnow().isoformat(),
                lane=finding.get("lane", "estate"),
                trigger=finding["description"],
                action="escalated",
                outcome="needs_human",
                evidence=finding.get("context", {}),
                shape_id=finding.get("shape_extracted")
            ))

        self.daily_findings = []
        self.daily_resolved = []
        self.daily_needs_human = []
        self._save_intent()
        self._transition(State.IDLE)

    def _do_crisis(self):
        p0_findings = getattr(self, "unacked_p0s", None) or [
            f for f in self.daily_findings if f.get("severity") == "P0"]
        self.bridge.send(
            f"🚨 *CRISIS MODE*\n\n"
            f"{len(p0_findings)} P0 finding(s):\n" +
            "\n".join(f"• {f['description']}" for f in p0_findings) +
            "\n\nAll non-essential lanes frozen. Manual intervention required.",
            Priority.P0
        )

        # A crisis that only reaches Telegram is a crisis with no state and no
        # audit trail. The board is where it stays visible until someone acts.
        for finding in p0_findings:
            num = self._board(board.open_finding, finding, board.NEEDS_CHIDI)
            if num:
                finding["issue"] = num
                self._board(board.move, num, board.NEEDS_CHIDI,
                            "P0. All non-essential lanes frozen. This needs your tap.")

        for finding in p0_findings:
            self.db.log_episode(Episode(
                id=f"CRISIS-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{finding['id']}",
                timestamp=datetime.utcnow().isoformat(),
                lane=finding.get("lane", "estate"),
                trigger=finding["description"],
                action="crisis_escalation",
                outcome="needs_human",
                evidence=finding.get("context", {})
            ))

        self.crisis_mode = False
        self.daily_findings = []
        self._save_intent()
        self._transition(State.IDLE)

    def _do_meta_review(self):
        stats = self.db.get_stats()
        with sqlite3.connect(self.db.db_path) as conn:
            yesterday = (datetime.utcnow() - timedelta(hours=24)).isoformat()
            rows = conn.execute(
                "SELECT * FROM episodes WHERE timestamp > ?", (yesterday,)
            ).fetchall()

        failure_shapes = {}
        for row in rows:
            if row[5] == "failure":
                shape_id = row[9]
                if shape_id:
                    failure_shapes[shape_id] = failure_shapes.get(shape_id, 0) + 1

        proposals = []
        for shape_id, count in failure_shapes.items():
            if count >= 2:
                proposals.append(f"Shape {shape_id} failed {count} times — review prevention skill")

        if proposals:
            self.bridge.send(
                f"📊 *Meta-Review*\n\n"
                f"24h episodes: {len(rows)}\n"
                f"Failure patterns: {len(failure_shapes)}\n\n"
                f"Proposals:\n" + "\n".join(f"• {p}" for p in proposals) +
                "\n\n[Review on GitHub]",
                Priority.P2
            )

        self.last_meta_review = datetime.utcnow()
        self.db.kv_set("last_meta_review", self.last_meta_review.isoformat())
        self._transition(State.IDLE)

    def run(self):
        logger.info("Maestro Deputy v1.0 starting...")
        logger.info(f"Database: {self.db.db_path}")
        logger.info(f"Tick interval: {Config.TICK_INTERVAL}s")

        try:
            while True:
                self.tick()
                time.sleep(Config.TICK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("Shutting down gracefully...")
            self._save_intent()


# ───────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ───────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Maestro Deputy")
    parser.add_argument("--once", action="store_true", help="Run one tick and exit")
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    parser.add_argument("--init", action="store_true", help="Initialize database and exit")
    args = parser.parse_args()

    if args.init:
        db = ExperienceGraph(Config.DB_PATH)
        print(f"Initialized: {db.db_path}")
        sys.exit(0)

    if args.status:
        db = ExperienceGraph(Config.DB_PATH)
        stats = db.get_stats()
        print(json.dumps(stats, indent=2))
        sys.exit(0)

    maestro = Maestro()

    if args.once:
        # One tick is one state transition, so a single call stopped at SENSE and
        # proved nothing. A dry run drives the machine until it comes back to IDLE.
        for _ in range(20):
            maestro.tick()
            if maestro.state == State.IDLE:
                break
        else:
            logger.warning("Dry run did not return to IDLE within 20 transitions")
            sys.exit(1)
    else:
        maestro.run()

