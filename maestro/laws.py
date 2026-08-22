#!/usr/bin/env python3
"""The 7 constitutional invariants, enforced as runtime blocks, not documentation."""

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
# ───────────────────────────────────────────────────────────────────────────────
# THE 7 LAWS — CONSTITUTIONAL INVARIANTS
# ───────────────────────────────────────────────────────────────────────────────

class LawViolation(Exception):
    def __init__(self, law_name: str, reason: str, evidence: Dict = None):
        self.law_name = law_name
        self.reason = reason
        self.evidence = evidence or {}
        super().__init__(f"LAW_VIOLATION: {law_name} — {reason}")

class LawMiddleware:
    @classmethod
    def validate(cls, plan: Dict, context: Dict, graph: ExperienceGraph) -> List[str]:
        applied = []

        applied.append("LAW_CONTEXT")
        if not cls._law_context(plan, context):
            raise LawViolation("LAW_CONTEXT",
                f"Plan domain '{plan.get('domain', 'unknown')}' not in allowed contexts")

        applied.append("LAW_DEGREE")
        if not cls._law_degree(plan):
            raise LawViolation("LAW_DEGREE",
                "Plan contains binary assessment without scalar metric")

        applied.append("LAW_BASELINE")
        if not cls._law_baseline(plan):
            raise LawViolation("LAW_BASELINE",
                "Plan claims improvement without baseline comparison")

        applied.append("LAW_TRADEOFF")
        if not cls._law_tradeoff(plan):
            raise LawViolation("LAW_TRADEOFF",
                "Plan does not surface invisible costs")

        applied.append("LAW_RIPPLE")
        if not cls._law_ripple(plan, depth=2):
            raise LawViolation("LAW_RIPPLE",
                f"Plan traces insufficient ripple effects")

        applied.append("LAW_MECHANISM")
        if not cls._law_mechanism(plan):
            raise LawViolation("LAW_MECHANISM",
                "Plan mechanism is hand-waving")

        applied.append("LAW_SOURCE")
        if not cls._law_source(plan):
            raise LawViolation("LAW_SOURCE",
                "Plan uses unattributed data")

        return applied

    @staticmethod
    def _law_context(plan: Dict, context: Dict) -> bool:
        allowed = context.get("allowed_domains", ["estate", "research", "meta"])
        domain = plan.get("domain", "unknown")
        return domain in allowed or domain == "meta"

    @staticmethod
    def _law_degree(plan: Dict) -> bool:
        assessments = plan.get("assessments", {})
        if not assessments:
            return True
        for key, val in assessments.items():
            if isinstance(val, bool):
                return False
            if isinstance(val, dict):
                if "value" not in val or "threshold" not in val:
                    return False
        return True

    @staticmethod
    def _law_baseline(plan: Dict) -> bool:
        baseline = plan.get("baseline")
        if baseline is None and plan.get("outcome_claim") in ["improved", "better", "faster"]:
            return False
        return True

    @staticmethod
    def _law_tradeoff(plan: Dict) -> bool:
        tradeoffs = plan.get("tradeoffs", [])
        if not plan.get("actions"):
            return True
        return len(tradeoffs) > 0

    @staticmethod
    def _law_ripple(plan: Dict, depth: int = 2) -> bool:
        effects = plan.get("ripple_effects", [])
        max_depth = 0
        for effect in effects:
            d = 1
            current = effect
            while isinstance(current, dict) and "then" in current:
                d += 1
                current = current["then"]
            max_depth = max(max_depth, d)
        return max_depth >= depth or len(effects) == 0

    @staticmethod
    def _law_mechanism(plan: Dict) -> bool:
        mechanism = plan.get("mechanism", "")
        if not mechanism:
            return True
        steps = [s for s in mechanism.split("\n") if s.strip()]
        return len(steps) >= 2 and all(len(s.strip()) > 10 for s in steps)

    @staticmethod
    def _law_source(plan: Dict) -> bool:
        evidence_nodes = plan.get("evidence", {})
        if not evidence_nodes:
            return True
        for key, val in evidence_nodes.items():
            if isinstance(val, dict) and "source" not in val:
                return False
        return True


