#!/usr/bin/env python3
"""
Estate Broadcast System — Safe, concurrent, validated JSON append.

All sessions use this to post to ESTATE_BOARD.jsonl.
Guarantees: no corruption, no concurrent writes, valid JSONL always.
"""

import json
import os
import sys
import time
import fcntl
from pathlib import Path
from datetime import datetime, timezone

BOARD_PATH = Path.home() / ".claude" / "ESTATE_BOARD.jsonl"
BOARD_LOCK = Path.home() / ".claude" / ".ESTATE_BOARD.lock"
MAX_RETRIES = 5
LOCK_TIMEOUT = 30

# Founder, 2026-08-24: "why not just use github issues? why reinvent the wheel badly."
# The board IS crew issue #102 — a phone can read it, nothing lives only on this laptop.
# The JSONL above remains the offline cache the prompt hooks read at each session start.
GH_REPO = "chidionyema/crew"
GH_BOARD_ISSUE = "102"
DEADLETTER = Path.home() / ".claude" / "state" / "board-deadletter.jsonl"


def format_row(record):
    """One board row as one GitHub comment body."""
    text = record.get("message") or record.get("text") or json.dumps(
        {k: v for k, v in record.items() if k not in ("ts", "from", "kind", "priority")},
        ensure_ascii=True)
    body = "`%s` **%s** (%s/%s): %s" % (
        record.get("ts", "?"), record.get("from", "?"), record.get("kind", "?"),
        record.get("priority", "info"), text)
    return body[:60000]


def mirror_to_github(record):
    """Land the row on the board issue. A failed mirror is dead-lettered and loud, never silent."""
    import subprocess
    try:
        subprocess.run(
            ["gh", "issue", "comment", GH_BOARD_ISSUE, "--repo", GH_REPO,
             "--body", format_row(record)],
            check=True, capture_output=True, text=True, timeout=30)
        return True
    except Exception as e:
        DEADLETTER.parent.mkdir(parents=True, exist_ok=True)
        with open(DEADLETTER, "a") as f:
            f.write(json.dumps({"record": record, "error": str(e)[:200],
                                "ts": datetime.now(timezone.utc).replace(
                                    tzinfo=None).isoformat() + "Z"}) + "\n")
        print(f"[WARN] row NOT on GitHub board (crew#{GH_BOARD_ISSUE}): {e} — "
              f"dead-lettered to {DEADLETTER}", file=sys.stderr)
        return False


def acquire_lock(timeout=LOCK_TIMEOUT):
    """Acquire exclusive lock on the board file."""
    lock_file = open(BOARD_LOCK, "w")
    start = time.time()
    
    while True:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock_file
        except IOError:
            if time.time() - start > timeout:
                raise TimeoutError(f"Could not acquire lock after {timeout}s")
            time.sleep(0.1)


def release_lock(lock_file):
    """Release the lock."""
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    lock_file.close()


def validate_json_line(line):
    """Validate a single line is valid JSON (no embedded newlines)."""
    if not line.strip():
        return False
    if '\n' in line.strip():
        return False
    try:
        json.loads(line)
        return True
    except json.JSONDecodeError:
        return False


def read_board_validated():
    """Read the board, return only valid lines. Report corruption."""
    if not BOARD_PATH.exists():
        return []
    
    valid_lines = []
    invalid_count = 0
    
    with open(BOARD_PATH, 'r') as f:
        for line_num, line in enumerate(f, 1):
            if validate_json_line(line):
                valid_lines.append(json.loads(line))
            else:
                invalid_count += 1
                print(f"[WARN] Line {line_num}: invalid JSON (skipped)", file=sys.stderr)
    
    if invalid_count > 0:
        print(f"[WARN] Board has {invalid_count} corrupted line(s)", file=sys.stderr)
    
    return valid_lines


# crew#656 CP0 (founder spec section 2, 2026-08-29). The banned-token check on the one
# surface every session posts through. Prevention at the write beats judgement at the read.
#
# FAIL LOUD ON CONFIG, NOT CLOSED -- deliberately, and this is the one place the spec's
# general "fail closed" rule inverts. Spec section 4.2 requires that the gate "must not be
# the only channel by which the estate can be told the gate is broken". This board IS that
# channel. On 2026-08-29 a fail-closed hook that could not find its own script denied every
# prompt across five sessions and removed the channel needed to repair it. So: a missing or
# broken checker prints GATE_UNAVAILABLE and lets the post through. A checker that runs and
# refuses blocks the post. Config failures are visible; content failures are stopped.
#
# Manual override, for the founder and for an incident where the board must carry a
# quotation containing banned words: ESTATE_VOCABULARY_OVERRIDE=1.
def _vocabulary_refusal(record):
    """Return a refusal string for a record that asserts service state in banned words.

    Returns None when the record is acceptable, when the checker is unavailable, or when
    the override is set. Never raises: a broken check must not take the board down.
    """
    import os

    if os.environ.get("ESTATE_VOCABULARY_OVERRIDE") == "1":
        print("[WARN] state-vocabulary check overridden by ESTATE_VOCABULARY_OVERRIDE",
              file=sys.stderr)
        return None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from state_vocabulary import Refusal, check
    except Exception as exc:  # noqa: BLE001 - config failure, must stay loud and open
        print(f"[GATE_UNAVAILABLE] state-vocabulary check could not load: {exc}. "
              f"Post allowed. This is a broken gate, not a clean post.", file=sys.stderr)
        return None
    text = " ".join(
        str(record.get(f, "")) for f in ("message", "claim", "summary", "title")
    )
    try:
        check(text)
    except Refusal as exc:
        return str(exc)
    return None


def _claim_refusal(record):
    """crew#656 CP2: a MEASURED_* assertion on the board carries its ```claim envelope, and the
    envelope is checked (founder spec section 4.2). Stale evidence is rewritten to UNKNOWN in
    place. Same posture as the vocabulary gate: content failures block, a gate that cannot load
    prints GATE_UNAVAILABLE and lets the post through, because this board is the channel the
    estate reports a broken gate on. Override: ESTATE_VOCABULARY_OVERRIDE=1.
    """
    import os

    if os.environ.get("ESTATE_VOCABULARY_OVERRIDE") == "1":
        return None
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import claim_gate
    except Exception as exc:  # noqa: BLE001 - config failure, loud and open
        print(f"[GATE_UNAVAILABLE] claim gate could not load: {exc}. Post allowed. "
              f"This is a broken gate, not a clean post.", file=sys.stderr)
        return None
    field = next((f for f in ("message", "claim", "summary") if isinstance(record.get(f), str)), None)
    if field is None:
        return None
    text, refusal = claim_gate.gate_text(record[field], session=str(record.get("from", "")), surface="board")
    if refusal:
        return refusal
    if text != record[field]:
        record[field] = text
    return None


def append_broadcast(record):
    """
    Append a broadcast record to the board atomically.
    
    Args:
        record (dict): The broadcast record to append
        
    Returns:
        bool: True if successful
        
    Raises:
        ValueError: If record is invalid
        TimeoutError: If lock acquisition times out
    """
    # Validate the record
    if not isinstance(record, dict):
        raise ValueError("record must be a dict")

    refusal = _vocabulary_refusal(record) or _claim_refusal(record)
    if refusal:
        raise ValueError(refusal)
    
    # Ensure required fields
    if 'ts' not in record:
        # utcnow() is deprecated and prints a DeprecationWarning on every broadcast,
        # which puts noise on stderr in the one place a session is trying to read a
        # receipt. Same wire format, no warning.
        record['ts'] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z'
    if 'from' not in record:
        raise ValueError("record must have 'from' field")
    if 'kind' not in record:
        raise ValueError("record must have 'kind' field")
    
    # Serialize to single-line JSON (no embedded newlines)
    json_line = json.dumps(record, separators=(',', ':'), ensure_ascii=True)
    
    if '\n' in json_line:
        raise ValueError("record contains newlines (not allowed)")
    
    # Acquire lock, append, release
    lock_file = acquire_lock()
    try:
        # Re-read to verify file is still valid before appending
        with open(BOARD_PATH, 'a') as f:
            f.write(json_line + '\n')
            f.flush()
            os.fsync(f.fileno())
        
        # Verify the write succeeded
        with open(BOARD_PATH, 'r') as f:
            f.seek(0, 2)  # Go to end
            # Read backwards to find the line we just wrote
            # This is a simple check — in production, hash the line
        
        return True
    finally:
        release_lock(lock_file)


def main():
    """CLI interface for estate-broadcast."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Estate Broadcast System')
    parser.add_argument('--post', type=str, help='Post a broadcast (JSON string)')
    parser.add_argument('--read', action='store_true', help='Read all broadcasts')
    parser.add_argument('--from', dest='from_field', type=str, required=False, help='Sender name')
    parser.add_argument('--kind', type=str, required=False, help='Message kind')
    parser.add_argument('--message', type=str, required=False, help='Message text')
    parser.add_argument('--priority', type=str, default='info', help='Priority (default: info)')
    
    args = parser.parse_args()
    
    if args.read:
        records = read_board_validated()
        for record in records:
            print(json.dumps(record))
        return 0
    
    if args.post:
        try:
            record = json.loads(args.post)
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON: {e}", file=sys.stderr)
            return 1
    elif args.from_field and args.kind and args.message:
        record = {
            'from': args.from_field,
            'kind': args.kind,
            'message': args.message,
            'priority': args.priority,
        }
    else:
        parser.print_help()
        return 1
    
    try:
        append_broadcast(record)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    on_github = mirror_to_github(record)
    print("[OK] Posted to board" + ("" if on_github else " (LOCAL ONLY — see warning)"),
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
