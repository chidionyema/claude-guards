#!/usr/bin/env python3
"""Failure pattern extraction. A shape is what a failure looks like, stripped of its instance."""

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
# SHAPE EXTRACTOR
# ───────────────────────────────────────────────────────────────────────────────

class ShapeExtractor:
    KNOWN_PATTERNS = {
        "resource-exhaustion-monotonic": {
            "triggers": ["disk full", "memory full", "connection pool exhausted", "GPU OOM"],
            "mechanism": "monotonic growth of ephemeral artifact without cleanup",
            "contexts": ["disk", "memory", "network", "gpu"],
            "invariant": "LAW_RIPPLE",
        },
        "retry-storm-no-backoff": {
            "triggers": ["infinite loop", "retry exceeded", "timeout cascade", "connection refused loop"],
            "mechanism": "failure triggers immediate retry with no state change, identical failure recurs",
            "contexts": ["api", "db", "git", "file-lock"],
            "invariant": "LAW_DEGREE",
        },
        "manual-intervention-left-in-production": {
            "triggers": ["debug flag set", "temp file old", "cron commented", "firewall rule open"],
            "mechanism": "temporary change made for debugging, never reverted, silently decays",
            "contexts": ["config", "cron", "firewall", "env", "feature-flag"],
            "invariant": "LAW_RIPPLE",
        },
        "scope-creep-sidequest": {
            "triggers": ["task expanded", "unrelated files touched", "goal drift", "original issue abandoned"],
            "mechanism": "agent expands task scope beyond original goal, loses focus, original deliverable delayed",
            "contexts": ["coding", "research", "writing", "analysis"],
            "invariant": "LAW_CONTEXT",
        },
        "credential-leak-surface": {
            "triggers": ["key in log", "token in history", "password in diff", "secret in env"],
            "mechanism": "sensitive material written to durable surface without redaction",
            "contexts": ["shell-history", "git-log", "log-file", "env-var", "config-file"],
            "invariant": "LAW_TRADEOFF",
        },
    }

    def __init__(self, graph: ExperienceGraph):
        self.graph = graph

    def extract(self, episode: Episode) -> Optional[Shape]:
        for pattern_id, pattern in self.KNOWN_PATTERNS.items():
            if self._matches_pattern(episode, pattern):
                return self._create_or_update_shape(pattern_id, pattern, episode)
        logger.info(f"Novel incident logged: {episode.id}")
        return None

    def _matches_pattern(self, episode: Episode, pattern: Dict) -> bool:
        trigger_lower = episode.trigger.lower()
        action_lower = episode.action.lower()
        return any(t in trigger_lower or t in action_lower for t in pattern["triggers"])

    def _create_or_update_shape(self, pattern_id: str, pattern: Dict, episode: Episode) -> Shape:
        existing = self.graph.get_shapes(pattern_name=pattern_id)

        if existing:
            shape = existing[0]
            shape.occurrence_count += 1
            shape.last_seen = episode.timestamp
            if episode.lane not in shape.contexts_observed:
                shape.contexts_observed.append(episode.lane)
            if episode.outcome == "prevented":
                successes = shape.prevention_success_rate * (shape.occurrence_count - 1)
                shape.prevention_success_rate = (successes + 1) / shape.occurrence_count
        else:
            shape = Shape(
                id=pattern_id,
                pattern_name=pattern_id,
                morphology={
                    "trigger_keywords": pattern["triggers"],
                    "mechanism": pattern["mechanism"],
                },
                contexts_observed=[episode.lane],
                invariant_violated=pattern["invariant"],
                prevention_skill=f"skills/{pattern_id}.py",
                first_seen=episode.timestamp,
                last_seen=episode.timestamp,
                occurrence_count=1,
                prevention_success_rate=0.0,
                confidence=0.7
            )

        self.graph.upsert_shape(shape)
        return shape

    def find_prevention(self, trigger: str, lane: str) -> Optional[Skill]:
        shapes = self.graph.get_shape_by_context(lane)
        for shape in shapes:
            if shape.prevention_success_rate > 0.5 and shape.confidence > 0.5:
                triggers = shape.morphology.get("trigger_keywords", [])
                if any(t in trigger.lower() for t in triggers):
                    skill = self.graph.get_skill(shape.prevention_skill)
                    if skill:
                        return skill
        return None


