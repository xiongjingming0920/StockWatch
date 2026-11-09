"""Minimal, local, content-free run journal for the case investigation workflow.

Only fixed vocabulary can be written as event metadata. Messages, tool arguments,
model output and exception text must never be passed to this journal.
"""
from __future__ import annotations

import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPES = frozenset({'run_started', 'run_finished', 'route_started', 'route_finished',
    'model_started', 'model_finished', 'tool_started', 'tool_finished',
    'fallback_started', 'fallback_finished', 'answer_started', 'answer_finished',
    'planning_started', 'planning_finished', 'collection_started', 'collection_finished',
    'response_started', 'response_finished', 'error', 'model_call', 'tool_call',
    'fallback', 'plan', 'collect', 'respond'})
EVENT_STATUSES = frozenset({'running', 'succeeded', 'degraded', 'failed', 'success', 'error', 'not_found'})
TOOL_NAMES = frozenset({'route_intent', 'get_case_detail', 'get_stockout_history', 'get_case_summary',
    'verify_and_compose', 'compose_answer', 'fallback_route', 'unknown_tool'})
ERROR_CODES = frozenset({'model_unavailable', 'model_timeout', 'model_error', 'invalid_model_response',
    'tool_error', 'invalid_tool', 'invalid_arguments', 'case_not_found', 'data_unavailable',
    'workflow_error', 'unexpected_error', 'fallback_failed', 'tool_limit_exceeded'})
TERMINAL_STATUSES = frozenset({'succeeded', 'degraded', 'failed'})


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


@contextmanager
def _connect():
    path = Path(os.environ.get('STOCKWATCH_RUN_DB') or Path(__file__).resolve().parent.parent / 'data' / 'agent-runs.sqlite3')
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, case_id TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS events (run_id TEXT NOT NULL REFERENCES runs(id), sequence INTEGER NOT NULL, event_type TEXT NOT NULL, status TEXT, tool_name TEXT, duration_ms INTEGER, error_code TEXT, created_at TEXT NOT NULL, PRIMARY KEY(run_id, sequence))')
    db.commit()
    try:
        with db:
            yield db
    finally:
        db.close()


def _event(db, run_id, event_type, status=None, tool_name=None, duration_ms=None, error_code=None):
    sequence = db.execute('SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE run_id=?', (run_id,)).fetchone()[0]
    db.execute('INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (run_id, sequence, event_type, status, tool_name, duration_ms, error_code, _now()))


def start_run(user_id: str, case_id: str) -> str:
    try:
        if str(uuid.UUID(user_id)) != user_id:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise ValueError('Invalid user identifier') from None
    if not isinstance(case_id, str) or not re.fullmatch(r'[a-f0-9]{20}', case_id):
        raise ValueError('Invalid case identifier')
    run_id = str(uuid.uuid4())
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO runs VALUES (?, ?, ?, ?, ?, NULL)', (run_id, user_id, case_id, 'running', _now()))
        _event(db, run_id, 'run_started', 'running')
    return run_id


def record_event(run_id, event_type, *, status=None, tool_name=None, duration_ms=None, error_code=None) -> None:
    if event_type not in EVENT_TYPES or event_type in {'run_started', 'run_finished'}:
        raise ValueError('Invalid event type')
    if status is not None and status not in EVENT_STATUSES:
        raise ValueError('Invalid event status')
    if tool_name is not None and tool_name not in TOOL_NAMES:
        raise ValueError('Invalid tool name')
    if error_code is not None and error_code not in ERROR_CODES:
        raise ValueError('Invalid error code')
    if duration_ms is not None and (type(duration_ms) is not int or not 0 <= duration_ms <= 86_400_000):
        raise ValueError('Invalid duration')
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise ValueError('Run not found')
        if row['status'] != 'running':
            raise ValueError('Run already finished')
        _event(db, run_id, event_type, status, tool_name, duration_ms, error_code)


def finish_run(run_id, status) -> None:
    if status not in TERMINAL_STATUSES:
        raise ValueError('Invalid terminal status')
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT status FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise ValueError('Run not found')
        if row['status'] != 'running':
            raise ValueError('Run already finished')
        db.execute('UPDATE runs SET status=?, finished_at=? WHERE id=?', (status, _now(), run_id))
        _event(db, run_id, 'run_finished', status)


def get_run(run_id: str, user_id: str):
    with _connect() as db:
        run = db.execute('SELECT id, case_id, status, started_at, finished_at FROM runs WHERE id=? AND user_id=?', (run_id, user_id)).fetchone()
        if run is None:
            return None
        events = db.execute('SELECT sequence, event_type, status, tool_name, duration_ms, error_code, created_at FROM events WHERE run_id=? ORDER BY sequence', (run_id,)).fetchall()
        return {'run': dict(run), 'events': [dict(event) for event in events]}
