#!/usr/bin/env python3
"""Institutional memory. One SQLite file; every episode, shape and skill lands here."""

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

# ───────────────────────────────────────────────────────────────────────────────
# EXPERIENCE GRAPH (SQLite)
# ───────────────────────────────────────────────────────────────────────────────

class ExperienceGraph:
    def __init__(self, db_path: str):
        self.db_path = os.path.expanduser(db_path)
        # ":memory:" and a bare filename both have an empty dirname, and
        # makedirs("") raises FileNotFoundError. An in-memory graph is how the
        # law checks run in CI, so it has to be constructible.
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    def kv_get(self, key: str, default=None):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def kv_set(self, key: str, value: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def _init_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    lane TEXT,
                    trigger TEXT,
                    action TEXT,
                    outcome TEXT,
                    evidence TEXT,
                    duration_ms INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    shape_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_episodes_time ON episodes(timestamp);
                CREATE INDEX IF NOT EXISTS idx_episodes_lane ON episodes(lane);
                CREATE INDEX IF NOT EXISTS idx_episodes_shape ON episodes(shape_id);

                CREATE TABLE IF NOT EXISTS shapes (
                    id TEXT PRIMARY KEY,
                    pattern_name TEXT NOT NULL,
                    morphology TEXT,
                    contexts_observed TEXT,
                    invariant_violated TEXT,
                    prevention_skill TEXT,
                    first_seen TEXT,
                    last_seen TEXT,
                    occurrence_count INTEGER DEFAULT 0,
                    prevention_success_rate REAL DEFAULT 0.0,
                    confidence REAL DEFAULT 0.0
                );
                CREATE INDEX IF NOT EXISTS idx_shapes_name ON shapes(pattern_name);

                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    lane TEXT,
                    trigger_pattern TEXT,
                    procedure TEXT,
                    success_rate REAL DEFAULT 0.0,
                    total_uses INTEGER DEFAULT 0,
                    created_from_shape TEXT,
                    last_used TEXT,
                    avg_duration_ms INTEGER DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_skills_lane ON skills(lane);

                CREATE TABLE IF NOT EXISTS invariants (
                    id TEXT PRIMARY KEY,
                    law_name TEXT NOT NULL,
                    violations_prevented INTEGER DEFAULT 0,
                    violations_allowed INTEGER DEFAULT 0,
                    last_enforced TEXT
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    role TEXT,
                    content TEXT,
                    context_summary TEXT,
                    session_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id);

                CREATE TABLE IF NOT EXISTS daily_spend (
                    date TEXT PRIMARY KEY,
                    amount_usd REAL DEFAULT 0.0
                );
            """)

    def log_episode(self, episode: Episode) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO episodes
                (id, timestamp, lane, trigger, action, outcome, evidence,
                 duration_ms, cost_usd, shape_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                episode.id, episode.timestamp, episode.lane, episode.trigger,
                episode.action, episode.outcome, json.dumps(episode.evidence),
                episode.duration_ms, episode.cost_usd, episode.shape_id
            ))

    def get_shapes(self, pattern_name: Optional[str] = None) -> List[Shape]:
        with sqlite3.connect(self.db_path) as conn:
            if pattern_name:
                rows = conn.execute(
                    "SELECT * FROM shapes WHERE pattern_name = ?", (pattern_name,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM shapes").fetchall()
            return [self._row_to_shape(r) for r in rows]

    def get_shape_by_context(self, context: str) -> List[Shape]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM shapes WHERE contexts_observed LIKE ?", (f"%{context}%",)
            ).fetchall()
            return [self._row_to_shape(r) for r in rows]

    def upsert_shape(self, shape: Shape) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO shapes
                (id, pattern_name, morphology, contexts_observed, invariant_violated,
                 prevention_skill, first_seen, last_seen, occurrence_count,
                 prevention_success_rate, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    occurrence_count = excluded.occurrence_count,
                    last_seen = excluded.last_seen,
                    prevention_success_rate = excluded.prevention_success_rate,
                    confidence = excluded.confidence,
                    contexts_observed = excluded.contexts_observed
            """, (
                shape.id, shape.pattern_name, json.dumps(shape.morphology),
                json.dumps(shape.contexts_observed), shape.invariant_violated,
                shape.prevention_skill, shape.first_seen, shape.last_seen,
                shape.occurrence_count, shape.prevention_success_rate, shape.confidence
            ))

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
            if not row:
                return None
            return self._row_to_skill(row)

    def get_skills_for_lane(self, lane: str) -> List[Skill]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM skills WHERE lane = ?", (lane,)).fetchall()
            return [self._row_to_skill(r) for r in rows]

    def upsert_skill(self, skill: Skill) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO skills
                (id, name, lane, trigger_pattern, procedure, success_rate,
                 total_uses, created_from_shape, last_used, avg_duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    success_rate = excluded.success_rate,
                    total_uses = excluded.total_uses,
                    last_used = excluded.last_used,
                    avg_duration_ms = excluded.avg_duration_ms
            """, (
                skill.id, skill.name, skill.lane, skill.trigger_pattern,
                skill.procedure, skill.success_rate, skill.total_uses,
                skill.created_from_shape, skill.last_used, skill.avg_duration_ms
            ))

    def get_daily_spend(self, date: str) -> float:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT amount_usd FROM daily_spend WHERE date = ?", (date,)
            ).fetchone()
            return row[0] if row else 0.0

    def add_spend(self, amount_usd: float) -> None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO daily_spend (date, amount_usd)
                VALUES (?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    amount_usd = amount_usd + excluded.amount_usd
            """, (today, amount_usd))

    def get_stats(self) -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            total_episodes = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            total_shapes = conn.execute("SELECT COUNT(*) FROM shapes").fetchone()[0]
            total_skills = conn.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
            success_rate = conn.execute(
                "SELECT AVG(CASE WHEN outcome='success' THEN 1.0 ELSE 0.0 END) FROM episodes"
            ).fetchone()[0] or 0.0
            today_spend = self.get_daily_spend(datetime.utcnow().strftime("%Y-%m-%d"))
            return {
                "total_episodes": total_episodes,
                "total_shapes": total_shapes,
                "total_skills": total_skills,
                "success_rate": round(success_rate, 3),
                "today_spend_usd": round(today_spend, 2),
            }

    @staticmethod
    def _row_to_shape(row) -> Shape:
        return Shape(
            id=row[0], pattern_name=row[1],
            morphology=json.loads(row[2]) if row[2] else {},
            contexts_observed=json.loads(row[3]) if row[3] else [],
            invariant_violated=row[4], prevention_skill=row[5],
            first_seen=row[6], last_seen=row[7],
            occurrence_count=row[8], prevention_success_rate=row[9],
            confidence=row[10]
        )

    @staticmethod
    def _row_to_skill(row) -> Skill:
        return Skill(
            id=row[0], name=row[1], lane=row[2],
            trigger_pattern=row[3], procedure=row[4],
            success_rate=row[5], total_uses=row[6],
            created_from_shape=row[7], last_used=row[8],
            avg_duration_ms=row[9]
        )


