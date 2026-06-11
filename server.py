#!/usr/bin/env python3
"""Read-only Hermes Mission Control backend.

Stdlib-only server for DV's local mission control dashboard.
Hermes data stores are opened read-only with SQLite URI mode=ro and
PRAGMA query_only=1. The only writable database is ./board.db.
"""

from __future__ import annotations

import cgi
import io
import json
import mimetypes
import os
import re
import sqlite3
import subprocess
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
PORT = 50000
PROJECT_DIR = Path(__file__).resolve().parent
HERMES_HOME = Path(os.environ.get("HERMES_HOME", "/root/.hermes"))
LIBRARY_ROOT = Path("/root/.hermes/content")
LIBRARY_AGENTS = ["master", "assistant", "research", "planning", "audit", "dev"]

AGENT_LOGS_DB = HERMES_HOME / "agent-logs.db"
STATE_DB = HERMES_HOME / "state.db"
BOARD_DB = PROJECT_DIR / "board.db"
TASK_ATTACHMENTS_DIR = PROJECT_DIR / "task_uploads"
TASK_ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024
TASK_ATTACHMENT_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".pdf", ".txt", ".md", ".csv", ".json", ".doc", ".docx", ".rtf", ".odt"}
TASK_ATTACHMENT_ALLOWED_MIME_PREFIXES = ("image/", "text/")
TASK_ATTACHMENT_ALLOWED_MIME_TYPES = {"application/pdf", "application/json", "application/msword", "application/rtf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.oasis.opendocument.text"}
TASK_STATUSES = ["backlog", "triage", "ready", "in_progress", "review", "revision_requested", "blocked", "completed"]
TASK_PRIORITIES = ["low", "medium", "high"]
TASK_STATUS_ALIASES = {"pending": "backlog", "done": "completed", "complete": "completed", "completed": "completed", "revision requested": "revision_requested", "revision-requested": "revision_requested", "in progress": "in_progress"}
AUDIT_STATES = ["pending_review", "approved", "rejected", "revision_requested"]
AUDIT_STATE_ALIASES = {"pending review": "pending_review", "pending-review": "pending_review", "approve": "approved", "approved": "approved", "reject": "rejected", "rejected": "rejected", "revision requested": "revision_requested", "revision-requested": "revision_requested", "request_revision": "revision_requested", "request revision": "revision_requested"}
DEPLOYMENT_TYPES = ["hermes_profile", "local_worker", "vps_worker", "webhook", "external"]
DEPLOYMENT_TRIGGER_MODES = ["manual", "task_driven", "schedule", "webhook"]
DEPLOYMENT_STATUSES = ["draft", "ready", "inactive"]
RUN_TYPES = ["task_run", "deployment", "sync", "agent_execution", "evaluation"]
RUN_STATUSES = ["queued", "running", "completed", "failed", "cancelled", "success"]
RUN_STATUS_ALIASES = {"complete": "completed", "completed": "completed", "succeeded": "completed", "success": "success", "canceled": "cancelled", "cancelled": "cancelled"}
RUN_ORIGINS = ["seed", "live"]
RUN_SOURCES = ["user", "system", "verification", "runtime", "deployment", "task", "unknown"]
RUN_SOURCE_ALIASES = {"demo": "system", "operator": "user"}
RUN_PURPOSES = ["execution", "test", "smoke_test", "cleanup", "verification", "retry", "diagnostic", "unknown"]
RUN_PURPOSE_ALIASES = {"task_lifecycle": "diagnostic", "deployment_lifecycle": "diagnostic", "agent_lifecycle": "diagnostic", "agent_execution": "execution", "evaluation": "execution", "demo_seed": "test", "task_execution": "execution"}
RUN_TRACE_EVENT_TYPES = ["queued", "planning", "tool_selection", "tool_execution", "result_assembly", "completed", "failed", "step"]
RUN_TRACE_STATUSES = ["pending", "running", "success", "failed", "skipped"]
RUN_OUTPUT_STATUSES = ["pending", "running", "success", "failed", "partial", "empty"]
RUN_SEED_TITLES = [
    "Validate Telegram and Discord gateway health",
    "Refresh Hermes profile deployment mapping",
    "Sync JobForge VPS migration metrics",
    "Research agent company brief generation",
    "Score deployment readiness for mapped agents",
]
RUN_TEST_PATTERNS = [
    r"\bphase\s*\d+\s+temp\b",
    r"\btemp\s+(agent|task|playbook)\b",
    r"\btemp-worker\b",
    r"duplicate-should-fail",
    r"\bverification\b",
    r"\bcleanup after verification\b",
]
GATEWAY_STATE_PATHS = [
    HERMES_HOME / "gateway_state.json",
    HERMES_HOME / "profiles" / "master" / "gateway_state.json",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str, fallback: str = "playbook") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or fallback


def parse_json_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass
    items = []
    for line in text.splitlines():
        clean = re.sub(r"^[\s\-•*\d\.)]+", "", line).strip()
        if clean:
            items.append(clean)
    return items


def dump_json_list(value) -> str:
    return json.dumps(parse_json_list(value), ensure_ascii=False)


def decode_json_list(value) -> list[str]:
    return parse_json_list(value)


def parse_json_object(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(k).strip(): v for k, v in value.items() if str(k).strip()}
    text = str(value).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {str(k).strip(): v for k, v in parsed.items() if str(k).strip()}
    except Exception:
        pass
    return {}


def dump_json_object(value) -> str:
    return json.dumps(parse_json_object(value), ensure_ascii=False)


def decode_json_object(value) -> dict:
    return parse_json_object(value)


def sanitize_task_filename(filename: str, fallback: str = "attachment") -> str:
    raw = Path(str(filename or fallback)).name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-._")
    return stem[:180] or fallback


def guess_task_attachment_mime_type(filename: str, provided: str = "") -> str:
    clean = str(provided or '').split(';', 1)[0].strip().lower()
    if clean:
        return clean
    guessed, _ = mimetypes.guess_type(str(filename or ''))
    return str(guessed or 'application/octet-stream').lower()


def task_attachment_allowed(filename: str, mime_type: str) -> bool:
    suffix = Path(str(filename or '')).suffix.lower()
    if suffix and suffix in TASK_ATTACHMENT_ALLOWED_EXTENSIONS:
        return True
    if any(str(mime_type or '').startswith(prefix) for prefix in TASK_ATTACHMENT_ALLOWED_MIME_PREFIXES):
        return True
    return str(mime_type or '') in TASK_ATTACHMENT_ALLOWED_MIME_TYPES


def task_attachments_root() -> Path:
    TASK_ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
    return TASK_ATTACHMENTS_DIR


def task_attachment_absolute_path(storage_rel_path: str) -> Path:
    if not storage_rel_path:
        raise ValueError('attachment storage path is missing')
    candidate = (task_attachments_root() / str(storage_rel_path).lstrip('/')).resolve(strict=False)
    root = task_attachments_root().resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError('attachment path escapes storage root') from exc
    return candidate


def delete_task_attachment_file(storage_rel_path: str):
    try:
        path = task_attachment_absolute_path(storage_rel_path)
    except Exception:
        return
    try:
        if path.exists() and path.is_file():
            path.unlink()
    except OSError:
        pass
    parent = path.parent
    root = task_attachments_root().resolve(strict=False)
    for _ in range(4):
        try:
            if parent == root or not parent.exists():
                break
            parent.rmdir()
            parent = parent.parent
        except OSError:
            break


def normalize_task_attachment_row(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item['id'] = str(item.get('id') or '')
    item['task_id'] = str(item.get('task_id') or '')
    item['draft_token'] = str(item.get('draft_token') or '')
    item['filename'] = str(item.get('filename') or '')
    item['mime_type'] = str(item.get('mime_type') or '').lower()
    item['size_bytes'] = int(item.get('size_bytes') or 0)
    item['size'] = item['size_bytes']
    item['storage_path'] = str(item.get('storage_rel_path') or '')
    item['storage_rel_path'] = item['storage_path']
    item['uploaded_at'] = str(item.get('uploaded_at') or item.get('created_at') or '')
    item['created_at'] = str(item.get('created_at') or item['uploaded_at'] or '')
    item['updated_at'] = str(item.get('updated_at') or item['uploaded_at'] or '')
    item['download_url'] = f"/api/task-attachments/{item['id']}/content" if item['id'] else ''
    item['preview_url'] = item['download_url']
    item['is_image'] = item['mime_type'].startswith('image/')
    item['is_pdf'] = item['mime_type'] == 'application/pdf'
    item['is_text'] = item['mime_type'].startswith('text/') or item['mime_type'] in {'application/json'}
    return item


def parse_task_attachment_ids(value) -> list[str]:
    ids = []
    seen = set()
    if isinstance(value, (list, tuple, set)):
        source = value
    else:
        source = parse_json_list(value)
    for item in source:
        if isinstance(item, dict):
            clean = str(item.get('id') or '').strip()
        else:
            clean = str(item).strip()
        if clean and clean not in seen:
            ids.append(clean)
            seen.add(clean)
    return ids


def task_attachment_rows_for_ids(conn: sqlite3.Connection, attachment_ids: list[str]) -> list[dict]:
    if not attachment_ids:
        return []
    placeholders = ','.join(['?'] * len(attachment_ids))
    rows = conn.execute(f"SELECT * FROM task_attachments WHERE id IN ({placeholders}) ORDER BY uploaded_at ASC, created_at ASC", attachment_ids).fetchall()
    found = {str(row['id']) for row in rows}
    missing = [attachment_id for attachment_id in attachment_ids if attachment_id not in found]
    if missing:
        raise ValueError(f"unknown attachment IDs: {', '.join(missing)}")
    by_id = {str(row['id']): dict(row) for row in rows}
    return [by_id[attachment_id] for attachment_id in attachment_ids]


def task_attachments_for_task(conn: sqlite3.Connection, task_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM task_attachments WHERE task_id = ? ORDER BY uploaded_at ASC, created_at ASC",
        (task_id,),
    ).fetchall()
    return [normalize_task_attachment_row(row) for row in rows]


def delete_task_attachment_rows(conn: sqlite3.Connection, rows):
    for row in rows or []:
        item = dict(row)
        if item.get('storage_rel_path'):
            delete_task_attachment_file(str(item.get('storage_rel_path') or ''))
        if item.get('id'):
            conn.execute('DELETE FROM task_attachments WHERE id = ?', (str(item.get('id')),))


def sync_task_attachments(conn: sqlite3.Connection, task_id: str, attachment_ids: list[str], draft_token: str = ''):
    keep_ids = [attachment_id for attachment_id in attachment_ids if attachment_id]
    keep_set = set(keep_ids)
    current_rows = conn.execute('SELECT * FROM task_attachments WHERE task_id = ? ORDER BY uploaded_at ASC, created_at ASC', (task_id,)).fetchall()
    delete_task_attachment_rows(conn, [row for row in current_rows if str(row['id']) not in keep_set])
    now = utc_now()
    for attachment_id in keep_ids:
        conn.execute(
            "UPDATE task_attachments SET task_id = ?, draft_token = '', updated_at = ? WHERE id = ?",
            (task_id, now, attachment_id),
        )
    if draft_token:
        staged_rows = conn.execute("SELECT * FROM task_attachments WHERE COALESCE(task_id, '') = '' AND draft_token = ?", (draft_token,)).fetchall()
        delete_task_attachment_rows(conn, [row for row in staged_rows if str(row['id']) not in keep_set])


def task_attachment_create(file_bytes: bytes, filename: str, mime_type: str = '', draft_token: str = '', task_id: str = '') -> dict:
    safe_name = sanitize_task_filename(filename)
    detected_mime = guess_task_attachment_mime_type(safe_name, mime_type)
    if not task_attachment_allowed(safe_name, detected_mime):
        raise ValueError('unsupported file type')
    size_bytes = len(file_bytes or b'')
    if size_bytes <= 0:
        raise ValueError('attachment file is empty')
    if size_bytes > TASK_ATTACHMENT_MAX_BYTES:
        raise ValueError(f'attachment exceeds {TASK_ATTACHMENT_MAX_BYTES // (1024 * 1024)}MB limit')
    attachment_id = uuid.uuid4().hex
    token = str(draft_token or '').strip()
    normalized_task_id = str(task_id or '').strip()
    bucket = normalized_task_id or token or 'direct'
    rel_path = f"{bucket}/{attachment_id}-{safe_name}"
    abs_path = task_attachment_absolute_path(rel_path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(file_bytes)
    now = utc_now()
    with connect_board() as conn:
        if normalized_task_id and not task_exists(conn, 'tasks', normalized_task_id):
            delete_task_attachment_file(rel_path)
            raise ValueError('task_id does not match an existing task')
        conn.execute(
            """
            INSERT INTO task_attachments (
              id, task_id, draft_token, filename, mime_type, size_bytes, storage_rel_path, uploaded_at, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (attachment_id, normalized_task_id, '' if normalized_task_id else token, safe_name, detected_mime, size_bytes, rel_path, now, now, now),
        )
        row = conn.execute('SELECT * FROM task_attachments WHERE id = ?', (attachment_id,)).fetchone()
        conn.commit()
    return normalize_task_attachment_row(row)


def task_attachment_get(attachment_id: str) -> dict:
    if not attachment_id:
        raise ValueError('attachment id is required')
    with connect_board() as conn:
        row = conn.execute('SELECT * FROM task_attachments WHERE id = ?', (attachment_id,)).fetchone()
        if row is None:
            raise KeyError('attachment not found')
        return normalize_task_attachment_row(row)


def task_attachment_delete(attachment_id: str):
    if not attachment_id:
        raise ValueError('attachment id is required')
    with connect_board() as conn:
        row = conn.execute('SELECT * FROM task_attachments WHERE id = ?', (attachment_id,)).fetchone()
        if row is None:
            raise KeyError('attachment not found')
        delete_task_attachment_rows(conn, [row])
        conn.commit()
        return {'deleted': 1, 'id': attachment_id}


def file_size_mb(path: Path) -> float:
    try:
        return round(path.stat().st_size / 1048576, 4)
    except OSError:
        return 0.0


def process_elapsed_seconds(pid) -> int | None:
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return None
    try:
        res = subprocess.run(
            ["ps", "-p", str(pid_int), "-o", "etimes="],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        if res.returncode != 0:
            return None
        raw = (res.stdout or "").strip()
        return int(raw) if raw else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def safe_call(name, fn):
    try:
        return {"ok": True, "data": fn(), "error": None}
    except Exception as exc:  # defensive: one subsystem must never kill snapshot
        return {"ok": False, "data": None, "error": f"{type(exc).__name__}: {exc}"}


def connect_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=1")
    return conn


def connect_board() -> sqlite3.Connection:
    conn = sqlite3.connect(str(BOARD_DB), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def rowdict(row):
    return dict(row) if row is not None else None


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def existing_table(conn: sqlite3.Connection, preferred: list[str]) -> str | None:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for name in preferred:
        if name in tables:
            return name
    # fallback: first non-sqlite table
    for name in sorted(tables):
        if not name.startswith("sqlite_"):
            return name
    return None


def gateway_data():
    path = next((p for p in GATEWAY_STATE_PATHS if p.exists()), None)
    if not path:
        return {
            "exists": False,
            "path": str(GATEWAY_STATE_PATHS[0]),
            "db_size_mb": 0.0,
            "state": "missing",
            "platforms": {},
            "active_agent_count": 0,
            "uptime_seconds": None,
            "updated_at": None,
        }

    data = json.loads(path.read_text(encoding="utf-8"))
    platforms = data.get("platforms") or {}
    active_agents = data.get("active_agents")
    if isinstance(active_agents, (list, tuple, dict)):
        active_count = len(active_agents)
    elif isinstance(active_agents, int):
        active_count = active_agents
    else:
        active_count = 0

    uptime = process_elapsed_seconds(data.get("pid"))
    start_time = data.get("start_time")
    if uptime is None and isinstance(start_time, (int, float)):
        # Hermes gateway_state uses process monotonic seconds on this host.
        now_mono = time.monotonic()
        now_epoch = time.time()
        if start_time < now_epoch - 10_000_000:  # likely monotonic, not epoch
            uptime = max(0, now_mono - float(start_time))
        else:
            uptime = max(0, now_epoch - float(start_time))

    return {
        "exists": True,
        "path": str(path),
        "db_size_mb": file_size_mb(path),
        "state": data.get("gateway_state") or data.get("state") or "unknown",
        "pid": data.get("pid"),
        "kind": data.get("kind"),
        "platforms": platforms,
        "platform_statuses": {k: (v.get("state") if isinstance(v, dict) else v) for k, v in platforms.items()},
        "active_agent_count": active_count,
        "uptime_seconds": uptime,
        "updated_at": data.get("updated_at"),
        "raw": data,
    }


def activity_data():
    if not AGENT_LOGS_DB.exists() or AGENT_LOGS_DB.stat().st_size == 0:
        return {
            "exists": AGENT_LOGS_DB.exists(),
            "path": str(AGENT_LOGS_DB),
            "db_size_mb": file_size_mb(AGENT_LOGS_DB),
            "entries": [],
            "per_agent": [],
            "totals": {"total": 0, "completed": 0, "failed": 0},
            "daily_7d": [],
            "note": "agent-logs.db is missing or has no schema yet",
        }

    with connect_ro(AGENT_LOGS_DB) as conn:
        table = existing_table(conn, ["agent_logs", "logs", "tasks", "runs", "entries"])
        if not table:
            return {"exists": True, "path": str(AGENT_LOGS_DB), "db_size_mb": file_size_mb(AGENT_LOGS_DB), "entries": [], "per_agent": [], "totals": {}}
        cols = table_columns(conn, table)

        def col(*names, default=None):
            for n in names:
                if n in cols:
                    return n
            return default

        id_col = col("id", "rowid", default="rowid")
        created_col = col("created_at", "timestamp", "started_at", "time", default=None)
        agent_col = col("agent", "agent_name", "profile", "assignee", "worker", default=None)
        status_col = col("status", "outcome", "state", default=None)
        task_col = col("task", "task_description", "task_title", "title", "prompt", "summary", "message", default=None)
        model_col = col("model", "model_used", "model_name", default=None)

        order_parts = []
        if created_col:
            order_parts.append(f'"{created_col}" DESC')
        if id_col == "rowid":
            order_parts.append("rowid DESC")
        else:
            order_parts.append(f'"{id_col}" DESC')
        order_sql = ", ".join(order_parts) or "rowid DESC"
        entries = [dict(r) for r in conn.execute(f'SELECT * FROM "{table}" ORDER BY {order_sql} LIMIT 50').fetchall()]

        total = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        completed = 0
        failed = 0
        if status_col:
            completed = conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE lower(COALESCE("{status_col}","")) IN ("completed","complete","done","success","succeeded")').fetchone()[0]
            failed = conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE lower(COALESCE("{status_col}","")) IN ("failed","failure","error","crashed","timed_out","timeout")').fetchone()[0]

        per_agent = []
        if agent_col:
            for r in conn.execute(f'SELECT COALESCE("{agent_col}", "unknown") AS agent, COUNT(*) AS total FROM "{table}" GROUP BY agent ORDER BY total DESC').fetchall():
                agent = r["agent"]
                where = f'COALESCE("{agent_col}", "unknown") = ?'
                last = conn.execute(f'SELECT * FROM "{table}" WHERE {where} ORDER BY {order_sql} LIMIT 1', (agent,)).fetchone()
                completed_a = failed_a = 0
                if status_col:
                    completed_a = conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {where} AND lower(COALESCE("{status_col}","")) IN ("completed","complete","done","success","succeeded")', (agent,)).fetchone()[0]
                    failed_a = conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {where} AND lower(COALESCE("{status_col}","")) IN ("failed","failure","error","crashed","timed_out","timeout")', (agent,)).fetchone()[0]
                last_d = dict(last) if last else {}
                per_agent.append({
                    "agent": agent,
                    "total": r["total"],
                    "completed": completed_a,
                    "failed": failed_a,
                    "last_task": last_d.get(task_col) if task_col else None,
                    "last_seen": last_d.get(created_col) if created_col else None,
                    "model": last_d.get(model_col) if model_col else None,
                })

        daily = []
        if created_col:
            if status_col and agent_col:
                sql = f'SELECT "{created_col}" AS created_at, "{status_col}" AS status, COALESCE("{agent_col}", "unknown") AS agent FROM "{table}" ORDER BY "{created_col}" DESC LIMIT 10000'
            elif status_col:
                sql = f'SELECT "{created_col}" AS created_at, "{status_col}" AS status, NULL AS agent FROM "{table}" ORDER BY "{created_col}" DESC LIMIT 10000'
            elif agent_col:
                sql = f'SELECT "{created_col}" AS created_at, NULL AS status, COALESCE("{agent_col}", "unknown") AS agent FROM "{table}" ORDER BY "{created_col}" DESC LIMIT 10000'
            else:
                sql = f'SELECT "{created_col}" AS created_at, NULL AS status, NULL AS agent FROM "{table}" ORDER BY "{created_col}" DESC LIMIT 10000'
            rows = conn.execute(sql).fetchall()
            buckets = {}
            cutoff = time.time() - 7 * 86400
            for r in rows:
                raw = r["created_at"]
                epoch = parse_time_to_epoch(raw)
                if epoch is None or epoch < cutoff:
                    continue
                day = datetime.fromtimestamp(epoch, timezone.utc).date().isoformat()
                b = buckets.setdefault(day, {"date": day, "total": 0, "completed": 0, "failed": 0, "agents": {}})
                b["total"] += 1
                agent_name = str(r["agent"] or "unknown").lower()
                b["agents"][agent_name] = b["agents"].get(agent_name, 0) + 1
                s = str(r["status"] or "").lower()
                if s in {"completed", "complete", "done", "success", "succeeded"}:
                    b["completed"] += 1
                if s in {"failed", "failure", "error", "crashed", "timed_out", "timeout"}:
                    b["failed"] += 1
            daily = [buckets[k] for k in sorted(buckets.keys())]

        return {
            "exists": True,
            "path": str(AGENT_LOGS_DB),
            "db_size_mb": file_size_mb(AGENT_LOGS_DB),
            "table": table,
            "entries": entries,
            "per_agent": per_agent,
            "totals": {"total": total, "completed": completed, "failed": failed},
            "daily_7d": daily,
        }


def parse_time_to_epoch(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def sessions_data():
    if not STATE_DB.exists():
        return {"exists": False, "path": str(STATE_DB), "db_size_mb": 0.0}
    with connect_ro(STATE_DB) as conn:
        sessions = conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]
        messages = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
        totals = conn.execute("""
            SELECT
              COALESCE(SUM(input_tokens),0) AS input_tokens,
              COALESCE(SUM(output_tokens),0) AS output_tokens,
              COALESCE(SUM(cache_read_tokens),0) AS cache_read_tokens,
              COALESCE(SUM(cache_write_tokens),0) AS cache_write_tokens,
              COALESCE(SUM(reasoning_tokens),0) AS reasoning_tokens,
              COALESCE(SUM(estimated_cost_usd),0) AS estimated_cost_usd,
              COALESCE(SUM(actual_cost_usd),0) AS actual_cost_usd
            FROM sessions
        """).fetchone()
        recent = [dict(r) for r in conn.execute("""
            SELECT id, source, user_id, model, started_at, ended_at, end_reason,
                   message_count, tool_call_count, input_tokens, output_tokens,
                   cache_read_tokens, cache_write_tokens, reasoning_tokens,
                   estimated_cost_usd, actual_cost_usd, cost_status, title,
                   handoff_state, handoff_platform, handoff_error
            FROM sessions
            ORDER BY started_at DESC
            LIMIT 25
        """).fetchall()]
        return {
            "exists": True,
            "path": str(STATE_DB),
            "db_size_mb": file_size_mb(STATE_DB),
            "session_count": sessions,
            "message_count": messages,
            "token_totals": dict(totals),
            "recent_sessions": recent,
        }


def read_proc_stat_cpu():
    parts = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    vals = [int(x) for x in parts]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    total = sum(vals)
    return idle, total


def vps_health():
    idle1, total1 = read_proc_stat_cpu()
    time.sleep(0.1)
    idle2, total2 = read_proc_stat_cpu()
    total_delta = total2 - total1
    idle_delta = idle2 - idle1
    cpu_percent = 0.0 if total_delta <= 0 else round((1 - idle_delta / total_delta) * 100, 2)

    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, rest = line.split(":", 1)
        mem[key] = int(rest.strip().split()[0]) * 1024
    mem_total = mem.get("MemTotal", 0)
    mem_available = mem.get("MemAvailable", 0)
    mem_used = max(0, mem_total - mem_available)

    st = os.statvfs("/")
    disk_total = st.f_blocks * st.f_frsize
    disk_free = st.f_bavail * st.f_frsize
    disk_used = disk_total - disk_free

    return {
        "cpu": {"percent": cpu_percent},
        "ram": {
            "total_bytes": mem_total,
            "available_bytes": mem_available,
            "used_bytes": mem_used,
            "percent": round((mem_used / mem_total) * 100, 2) if mem_total else 0,
        },
        "disk": {
            "path": "/",
            "total_bytes": disk_total,
            "free_bytes": disk_free,
            "used_bytes": disk_used,
            "percent": round((disk_used / disk_total) * 100, 2) if disk_total else 0,
        },
        "loadavg": os.getloadavg() if hasattr(os, "getloadavg") else None,
    }


def schedule_to_english(fields: list[str]) -> str:
    if len(fields) < 5:
        return "invalid schedule"
    minute, hour, dom, month, dow = fields[:5]
    if fields[:5] == ["*", "*", "*", "*", "*"]:
        return "every minute"
    if minute.startswith("*/") and hour == dom == month == dow == "*":
        return f"every {minute[2:]} minutes"
    if minute == "0" and hour.startswith("*/") and dom == month == dow == "*":
        return f"every {hour[2:]} hours"
    if dom == month == dow == "*":
        if hour == "*":
            return f"every hour at minute {minute}"
        return f"daily at {hour.zfill(2)}:{minute.zfill(2)}"
    if dow != "*" and dom == "*":
        return f"weekly on day-of-week {dow} at {hour.zfill(2)}:{minute.zfill(2)}"
    if dom != "*" and dow == "*":
        return f"monthly on day {dom} at {hour.zfill(2)}:{minute.zfill(2)}"
    return f"cron: {' '.join(fields[:5])}"


def parse_cron_line(line: str, source: str, system_file: bool):
    raw = line.rstrip("\n")
    stripped = raw.strip()
    if not stripped or stripped.startswith("#") or "=" in stripped.split()[0]:
        return None
    parts = stripped.split()
    if len(parts) < (7 if system_file else 6):
        return None
    schedule = parts[:5]
    username = None
    cmd_start = 5
    if system_file:
        username = parts[5]
        cmd_start = 6
    command = " ".join(parts[cmd_start:])
    if not command:
        return None
    label = "hermes" if "hermes" in command.lower() else "system"
    return {
        "source": source,
        "label": label,
        "schedule": " ".join(schedule),
        "schedule_english": schedule_to_english(schedule),
        "username": username,
        "command": command,
        "raw": raw,
    }


def user_crontab_files() -> list[tuple[Path, bool]]:
    files = []
    spool = Path("/var/spool/cron/crontabs")
    if spool.exists():
        for child in sorted(spool.iterdir()):
            if child.is_file():
                files.append((child, False))
    else:
        root_spool = Path("/var/spool/cron/crontabs/root")
        files.append((root_spool, False))
    return files


def hermes_job_command(job: dict) -> str:
    if job.get("script"):
        return str(job.get("script"))
    prompt = str(job.get("prompt") or "").strip().replace("\n", " ")
    return prompt[:180] + ("…" if len(prompt) > 180 else "") if prompt else "Hermes agent job"


def hermes_jobs_from_file(path: Path):
    jobs = []
    if not path.exists():
        return jobs
    data = json.loads(path.read_text(errors="replace"))
    for job in data.get("jobs", []):
        schedule = str(job.get("schedule_display") or job.get("schedule", {}).get("display") or job.get("schedule", {}).get("expr") or "")
        schedule_fields = schedule.split()
        jobs.append({
            "source": str(path),
            "label": "hermes",
            "owner": "hermes",
            "id": job.get("id"),
            "name": job.get("name") or job.get("id") or "Hermes automation",
            "description": job.get("name") or job.get("id") or "Hermes automation",
            "schedule": schedule,
            "schedule_english": schedule_to_english(schedule_fields) if len(schedule_fields) >= 5 else schedule,
            "username": None,
            "command": hermes_job_command(job),
            "raw": json.dumps({"id": job.get("id"), "name": job.get("name"), "state": job.get("state"), "enabled": job.get("enabled")}, separators=(",", ":")),
            "enabled": job.get("enabled"),
            "state": job.get("state"),
            "next_run_at": job.get("next_run_at"),
            "last_run_at": job.get("last_run_at"),
            "last_status": job.get("last_status"),
            "source_type": "hermes-cron-json",
        })
    return jobs


def systemd_timer_jobs():
    jobs = []
    result = subprocess.run(
        ["systemctl", "list-timers", "--all", "--no-pager", "--plain"],
        text=True,
        capture_output=True,
        timeout=8,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "systemctl failed").strip())
    for line in result.stdout.splitlines()[1:]:
        stripped = line.strip()
        if not stripped or stripped.endswith("timers listed."):
            continue
        parts = stripped.split()
        try:
            unit_idx = next(i for i, part in enumerate(parts) if part.endswith(".timer"))
        except StopIteration:
            continue
        unit = parts[unit_idx]
        activates = parts[unit_idx + 1] if unit_idx + 1 < len(parts) else ""
        jobs.append({
            "source": "systemd timers",
            "label": "hermes" if "hermes" in stripped.lower() else "system",
            "owner": "systemd",
            "name": unit,
            "description": unit.replace(".timer", "").replace("-", " "),
            "schedule": "systemd timer",
            "schedule_english": "systemd timer",
            "username": None,
            "command": activates,
            "raw": stripped,
            "source_type": "systemd-timer",
        })
    return jobs


def cron_jobs():
    jobs = []
    files = user_crontab_files() + [(Path("/etc/crontab"), True)]
    cron_d = Path("/etc/cron.d")
    if cron_d.exists():
        for child in sorted(cron_d.iterdir()):
            if child.is_file():
                files.append((child, True))
    hermes_files = []
    for candidate in [
        HERMES_HOME / "cron" / "jobs.json",
        Path("/root/.hermes/profiles/master/cron/jobs.json"),
        Path("/root/.hermes/cron/jobs.json"),
    ]:
        if candidate not in hermes_files:
            hermes_files.append(candidate)
    errors = []
    scanned = []
    counts = {}
    seen_hermes_ids = set()
    for path, system_file in files:
        scanned.append(str(path))
        before = len(jobs)
        try:
            if path.exists():
                for line in path.read_text(errors="replace").splitlines():
                    job = parse_cron_line(line, str(path), system_file)
                    if job:
                        jobs.append(job)
        except Exception as exc:
            errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
        counts[str(path)] = len(jobs) - before
    for path in hermes_files:
        scanned.append(str(path))
        before = len(jobs)
        try:
            for job in hermes_jobs_from_file(path):
                key = job.get("id")
                if key and key in seen_hermes_ids:
                    continue
                if key:
                    seen_hermes_ids.add(key)
                jobs.append(job)
        except Exception as exc:
            errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
        counts[str(path)] = len(jobs) - before
    scanned.append("systemd timers")
    before = len(jobs)
    try:
        jobs.extend(systemd_timer_jobs())
    except Exception as exc:
        errors.append({"path": "systemd timers", "error": f"{type(exc).__name__}: {exc}"})
    counts["systemd timers"] = len(jobs) - before
    return {"jobs": jobs, "count": len(jobs), "errors": errors, "scanned": scanned, "counts_by_source": counts}


def build_seed_runs(conn: sqlite3.Connection, now: str | None = None) -> list[dict]:
    now = str(now or utc_now())
    task_rows = conn.execute("SELECT id, title FROM tasks ORDER BY created_at ASC LIMIT 6").fetchall()
    agent_rows = conn.execute("SELECT id, name FROM agents ORDER BY created_at ASC LIMIT 6").fetchall()
    deployment_rows = conn.execute("SELECT id, target, deployment_type FROM deployments ORDER BY created_at ASC LIMIT 3").fetchall()
    task_ids = [str(row['id']) for row in task_rows]
    task_titles = [str(row['title']) for row in task_rows]
    agent_ids = [str(row['id']) for row in agent_rows]
    agent_names = [str(row['name']) for row in agent_rows]
    deployment_ids = [str(row['id']) for row in deployment_rows]
    deployment_targets = [str(row['target']) for row in deployment_rows]
    deployment_types = [str(row['deployment_type']) for row in deployment_rows]
    deployment_target = deployment_targets[0] if deployment_targets else 'master profile / local mapping'
    return [
        {
            'id': uuid.uuid4().hex,
            'type': 'task_run',
            'title': 'Validate Telegram and Discord gateway health',
            'agent_id': agent_ids[0] if agent_ids else '',
            'agent_name_snapshot': agent_names[0] if agent_names else '',
            'target': 'gateway-health / discord+telegram',
            'environment': 'vps',
            'status': 'running',
            'started_at': now,
            'finished_at': '',
            'summary': 'Live gateway health check is still in progress.',
            'log_preview': 'Polling gateway status...\nDiscord reachable\nTelegram reachable\nAwaiting next heartbeat.',
            'linked_task_id': task_ids[0] if task_ids else '',
            'linked_task_title_snapshot': task_titles[0] if task_titles else '',
            'deployment_id': deployment_ids[0] if deployment_ids else '',
            'deployment_target_snapshot': deployment_targets[0] if deployment_targets else deployment_target,
            'deployment_type_snapshot': deployment_types[0] if deployment_types else 'hermes_profile',
            'origin': 'seed',
            'run_source': 'demo',
            'run_purpose': 'demo_seed',
            'created_at': now,
            'updated_at': now,
        },
        {
            'id': uuid.uuid4().hex,
            'type': 'deployment',
            'title': 'Refresh Hermes profile deployment mapping',
            'agent_id': agent_ids[1] if len(agent_ids) > 1 else (agent_ids[0] if agent_ids else ''),
            'agent_name_snapshot': agent_names[1] if len(agent_names) > 1 else (agent_names[0] if agent_names else ''),
            'target': deployment_target,
            'environment': 'agentforge',
            'status': 'success',
            'started_at': now,
            'finished_at': now,
            'summary': 'Deployment metadata synced into AgentForge.',
            'log_preview': 'Fetched deployment record\nValidated target\nUpdated readiness state to ready.',
            'linked_task_id': task_ids[1] if len(task_ids) > 1 else '',
            'linked_task_title_snapshot': task_titles[1] if len(task_titles) > 1 else '',
            'deployment_id': deployment_ids[0] if deployment_ids else '',
            'deployment_target_snapshot': deployment_targets[0] if deployment_targets else deployment_target,
            'deployment_type_snapshot': deployment_types[0] if deployment_types else 'hermes_profile',
            'origin': 'seed',
            'run_source': 'demo',
            'run_purpose': 'demo_seed',
            'created_at': now,
            'updated_at': now,
        },
        {
            'id': uuid.uuid4().hex,
            'type': 'sync',
            'title': 'Sync JobForge VPS migration metrics',
            'agent_id': agent_ids[2] if len(agent_ids) > 2 else '',
            'agent_name_snapshot': agent_names[2] if len(agent_names) > 2 else '',
            'target': 'jobforge-migration / dashboard metrics',
            'environment': 'vps',
            'status': 'failed',
            'started_at': now,
            'finished_at': now,
            'summary': 'Metrics payload returned incomplete field set.',
            'log_preview': 'Requested metrics snapshot\nMissing scraper throughput field\nSync aborted for this cycle.',
            'linked_task_id': task_ids[2] if len(task_ids) > 2 else '',
            'linked_task_title_snapshot': task_titles[2] if len(task_titles) > 2 else '',
            'deployment_id': '',
            'deployment_target_snapshot': '',
            'deployment_type_snapshot': '',
            'origin': 'seed',
            'run_source': 'demo',
            'run_purpose': 'demo_seed',
            'created_at': now,
            'updated_at': now,
        },
        {
            'id': uuid.uuid4().hex,
            'type': 'agent_execution',
            'title': 'Research agent company brief generation',
            'agent_id': agent_ids[3] if len(agent_ids) > 3 else '',
            'agent_name_snapshot': agent_names[3] if len(agent_names) > 3 else '',
            'target': 'client-brief / interview prep',
            'environment': 'research',
            'status': 'queued',
            'started_at': now,
            'finished_at': '',
            'summary': 'Awaiting execution slot after upstream context sync.',
            'log_preview': 'Queued after directive handoff\nWaiting for vault context bundle.',
            'linked_task_id': task_ids[3] if len(task_ids) > 3 else '',
            'linked_task_title_snapshot': task_titles[3] if len(task_titles) > 3 else '',
            'deployment_id': '',
            'deployment_target_snapshot': '',
            'deployment_type_snapshot': '',
            'origin': 'seed',
            'run_source': 'demo',
            'run_purpose': 'demo_seed',
            'created_at': now,
            'updated_at': now,
        },
        {
            'id': uuid.uuid4().hex,
            'type': 'evaluation',
            'title': 'Score deployment readiness for mapped agents',
            'agent_id': agent_ids[4] if len(agent_ids) > 4 else '',
            'agent_name_snapshot': agent_names[4] if len(agent_names) > 4 else '',
            'target': 'agent registry / deployment readiness',
            'environment': 'agentforge',
            'status': 'success',
            'started_at': now,
            'finished_at': now,
            'summary': 'Mapped agents were scored and surfaced in the registry.',
            'log_preview': 'Loaded deployment list\nComputed mapped vs ready states\nPublished readiness badges.',
            'linked_task_id': task_ids[4] if len(task_ids) > 4 else '',
            'linked_task_title_snapshot': task_titles[4] if len(task_titles) > 4 else '',
            'deployment_id': deployment_ids[1] if len(deployment_ids) > 1 else '',
            'deployment_target_snapshot': deployment_targets[1] if len(deployment_targets) > 1 else '',
            'deployment_type_snapshot': deployment_types[1] if len(deployment_types) > 1 else '',
            'origin': 'seed',
            'run_source': 'demo',
            'run_purpose': 'demo_seed',
            'created_at': now,
            'updated_at': now,
        },
    ]


def insert_seed_runs(conn: sqlite3.Connection, items: list[dict] | None = None) -> int:
    rows = list(items if items is not None else build_seed_runs(conn))
    for item in rows:
        item.setdefault('agent_name_snapshot', '')
        item.setdefault('run_detail', '')
        item.setdefault('result_label', '')
        item.setdefault('error_message', '')
        item.setdefault('target_entity_type', '')
        item.setdefault('target_entity_id', '')
        item.setdefault('target_entity_name', '')
        item.setdefault('trigger_label', '')
        item.setdefault('changed_fields_json', '[]')
        item.setdefault('metadata_json', '{}')
        item.setdefault('linked_task_title_snapshot', '')
        item.setdefault('deployment_target_snapshot', '')
        item.setdefault('deployment_type_snapshot', '')
        item.setdefault('origin', 'seed')
        item.setdefault('run_source', 'demo')
        item.setdefault('run_purpose', 'demo_seed')
        conn.execute(
            """
            INSERT INTO runs (
              id, type, title, agent_id, agent_name_snapshot, target, environment, status, started_at, finished_at, summary,
              run_detail, result_label, error_message, log_preview, target_entity_type, target_entity_id, target_entity_name,
              trigger_label, changed_fields_json, metadata_json, linked_task_id, linked_task_title_snapshot, deployment_id,
              deployment_target_snapshot, deployment_type_snapshot, origin, run_source, run_purpose, created_at, updated_at
            ) VALUES (
              :id, :type, :title, :agent_id, :agent_name_snapshot, :target, :environment, :status, :started_at, :finished_at, :summary,
              :run_detail, :result_label, :error_message, :log_preview, :target_entity_type, :target_entity_id, :target_entity_name,
              :trigger_label, :changed_fields_json, :metadata_json, :linked_task_id, :linked_task_title_snapshot, :deployment_id,
              :deployment_target_snapshot, :deployment_type_snapshot, :origin, :run_source, :run_purpose, :created_at, :updated_at
            )
            """,
            item,
        )
    return len(rows)


def init_board():
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    with connect_board() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              description TEXT DEFAULT '',
              status TEXT DEFAULT 'backlog',
              priority TEXT DEFAULT 'medium',
              agent_id TEXT DEFAULT '',
              playbook_id TEXT DEFAULT '',
              blocked_reason TEXT DEFAULT '',
              notes TEXT DEFAULT '',
              result_text TEXT DEFAULT '',
              last_note TEXT DEFAULT '',
              audit_state TEXT DEFAULT '',
              audit_note TEXT DEFAULT '',
              audit_updated_at TEXT DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_dependencies (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id TEXT NOT NULL,
              depends_on_task_id TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_task_dependencies_unique
            ON task_dependencies(task_id, depends_on_task_id)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_attachments (
              id TEXT PRIMARY KEY,
              task_id TEXT DEFAULT '',
              draft_token TEXT DEFAULT '',
              filename TEXT NOT NULL,
              mime_type TEXT DEFAULT '',
              size_bytes INTEGER NOT NULL DEFAULT 0,
              storage_rel_path TEXT NOT NULL,
              uploaded_at TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_attachments_task_id ON task_attachments(task_id, uploaded_at, created_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_attachments_draft_token ON task_attachments(draft_token, uploaded_at, created_at)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              task_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              message TEXT NOT NULL,
              note TEXT DEFAULT '',
              metadata_json TEXT DEFAULT '{}',
              created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_events_task_id ON task_events(task_id, created_at, id)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS playbooks (
              id TEXT PRIMARY KEY,
              slug TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL,
              description TEXT DEFAULT '',
              category TEXT DEFAULT '',
              purpose TEXT DEFAULT '',
              sop TEXT DEFAULT '',
              rules TEXT DEFAULT '[]',
              input_schema TEXT DEFAULT '',
              output_schema TEXT DEFAULT '',
              linked_tools TEXT DEFAULT '[]',
              examples TEXT DEFAULT '[]',
              template_refs TEXT DEFAULT '[]',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agents (
              id TEXT PRIMARY KEY,
              slug TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL,
              description TEXT DEFAULT '',
              category TEXT DEFAULT '',
              role TEXT DEFAULT '',
              purpose TEXT DEFAULT '',
              instructions TEXT DEFAULT '',
              constraints TEXT DEFAULT '',
              status TEXT DEFAULT 'draft',
              linked_playbook_ids TEXT DEFAULT '[]',
              allowed_tools TEXT DEFAULT '[]',
              input_schema TEXT DEFAULT '',
              output_schema TEXT DEFAULT '',
              runtime_notes TEXT DEFAULT '',
              deployment_status TEXT DEFAULT 'not_deployed',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deployments (
              id TEXT PRIMARY KEY,
              agent_id TEXT NOT NULL UNIQUE,
              deployment_type TEXT NOT NULL,
              target TEXT NOT NULL,
              trigger_mode TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'draft',
              notes TEXT DEFAULT '',
              last_checked_at TEXT DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY,
              type TEXT NOT NULL,
              title TEXT NOT NULL,
              agent_id TEXT DEFAULT '',
              agent_name_snapshot TEXT DEFAULT '',
              target TEXT DEFAULT '',
              environment TEXT DEFAULT '',
              status TEXT NOT NULL DEFAULT 'queued',
              started_at TEXT NOT NULL,
              finished_at TEXT DEFAULT '',
              summary TEXT DEFAULT '',
              run_detail TEXT DEFAULT '',
              result_label TEXT DEFAULT '',
              result_summary TEXT DEFAULT '',
              result_payload_json TEXT DEFAULT '{}',
              artifact_count INTEGER NOT NULL DEFAULT 0,
              artifact_manifest_json TEXT DEFAULT '[]',
              output_status TEXT DEFAULT '',
              error_message TEXT DEFAULT '',
              log_preview TEXT DEFAULT '',
              target_entity_type TEXT DEFAULT '',
              target_entity_id TEXT DEFAULT '',
              target_entity_name TEXT DEFAULT '',
              trigger_label TEXT DEFAULT '',
              changed_fields_json TEXT DEFAULT '[]',
              metadata_json TEXT DEFAULT '{}',
              task_title_snapshot TEXT DEFAULT '',
              assignee_id TEXT DEFAULT '',
              assignee_name TEXT DEFAULT '',
              playbook_id TEXT DEFAULT '',
              playbook_name TEXT DEFAULT '',
              result_text TEXT DEFAULT '',
              linked_task_id TEXT DEFAULT '',
              linked_task_title_snapshot TEXT DEFAULT '',
              deployment_id TEXT DEFAULT '',
              deployment_target_snapshot TEXT DEFAULT '',
              deployment_type_snapshot TEXT DEFAULT '',
              origin TEXT NOT NULL DEFAULT 'live',
              run_source TEXT DEFAULT '',
              run_purpose TEXT DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS run_trace_events (
              id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              event_type TEXT NOT NULL,
              event_label TEXT NOT NULL,
              event_detail TEXT DEFAULT '',
              event_status TEXT NOT NULL DEFAULT 'pending',
              step_index INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              metadata_json TEXT DEFAULT '{}',
              FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_run_trace_events_run_id ON run_trace_events(run_id, step_index, created_at)")

        task_columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        task_column_defaults = {
            'description': "TEXT DEFAULT ''",
            'agent_id': "TEXT DEFAULT ''",
            'playbook_id': "TEXT DEFAULT ''",
            'blocked_reason': "TEXT DEFAULT ''",
            'notes': "TEXT DEFAULT ''",
            'result_text': "TEXT DEFAULT ''",
            'last_note': "TEXT DEFAULT ''",
            'audit_state': "TEXT DEFAULT ''",
            'audit_note': "TEXT DEFAULT ''",
            'audit_updated_at': "TEXT DEFAULT ''",
            'updated_at': "TEXT DEFAULT ''",
        }
        for column, ddl in task_column_defaults.items():
            if column not in task_columns:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} {ddl}")

        agent_columns = {row[1] for row in conn.execute("PRAGMA table_info(agents)").fetchall()}
        if 'instructions' not in agent_columns:
            conn.execute("ALTER TABLE agents ADD COLUMN instructions TEXT DEFAULT ''")
        if 'constraints' not in agent_columns:
            conn.execute("ALTER TABLE agents ADD COLUMN constraints TEXT DEFAULT ''")

        deployment_columns = {row[1] for row in conn.execute("PRAGMA table_info(deployments)").fetchall()}
        deployment_column_defaults = {
            'notes': "TEXT DEFAULT ''",
            'last_checked_at': "TEXT DEFAULT ''",
            'status': "TEXT DEFAULT 'draft'",
            'updated_at': "TEXT DEFAULT ''",
        }
        for column, ddl in deployment_column_defaults.items():
            if column not in deployment_columns:
                conn.execute(f"ALTER TABLE deployments ADD COLUMN {column} {ddl}")

        run_columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        run_column_defaults = {
            'agent_id': "TEXT DEFAULT ''",
            'agent_name_snapshot': "TEXT DEFAULT ''",
            'target': "TEXT DEFAULT ''",
            'environment': "TEXT DEFAULT ''",
            'status': "TEXT DEFAULT 'queued'",
            'finished_at': "TEXT DEFAULT ''",
            'summary': "TEXT DEFAULT ''",
            'run_detail': "TEXT DEFAULT ''",
            'result_label': "TEXT DEFAULT ''",
            'result_summary': "TEXT DEFAULT ''",
            'result_payload_json': "TEXT DEFAULT '{}'",
            'artifact_count': "INTEGER NOT NULL DEFAULT 0",
            'artifact_manifest_json': "TEXT DEFAULT '[]'",
            'output_status': "TEXT DEFAULT ''",
            'error_message': "TEXT DEFAULT ''",
            'log_preview': "TEXT DEFAULT ''",
            'target_entity_type': "TEXT DEFAULT ''",
            'target_entity_id': "TEXT DEFAULT ''",
            'target_entity_name': "TEXT DEFAULT ''",
            'trigger_label': "TEXT DEFAULT ''",
            'changed_fields_json': "TEXT DEFAULT '[]'",
            'metadata_json': "TEXT DEFAULT '{}'",
            'task_title_snapshot': "TEXT DEFAULT ''",
            'assignee_id': "TEXT DEFAULT ''",
            'assignee_name': "TEXT DEFAULT ''",
            'playbook_id': "TEXT DEFAULT ''",
            'playbook_name': "TEXT DEFAULT ''",
            'result_text': "TEXT DEFAULT ''",
            'linked_task_id': "TEXT DEFAULT ''",
            'linked_task_title_snapshot': "TEXT DEFAULT ''",
            'deployment_id': "TEXT DEFAULT ''",
            'deployment_target_snapshot': "TEXT DEFAULT ''",
            'deployment_type_snapshot': "TEXT DEFAULT ''",
            'origin': "TEXT NOT NULL DEFAULT 'live'",
            'run_source': "TEXT DEFAULT ''",
            'run_purpose': "TEXT DEFAULT ''",
            'updated_at': "TEXT DEFAULT ''",
        }
        for column, ddl in run_column_defaults.items():
            if column not in run_columns:
                conn.execute(f"ALTER TABLE runs ADD COLUMN {column} {ddl}")
        conn.execute("UPDATE runs SET origin = 'seed' WHERE COALESCE(NULLIF(origin,''), '') = ''")
        conn.execute(
            f"UPDATE runs SET origin = 'seed' WHERE title IN ({','.join('?' for _ in RUN_SEED_TITLES)}) AND COALESCE(origin, 'live') = 'live'",
            tuple(RUN_SEED_TITLES),
        )
        conn.execute("UPDATE runs SET task_title_snapshot = COALESCE(NULLIF(task_title_snapshot,''), linked_task_title_snapshot, '')")
        conn.execute("UPDATE runs SET assignee_id = COALESCE(NULLIF(assignee_id,''), agent_id, '')")
        conn.execute("UPDATE runs SET assignee_name = COALESCE(NULLIF(assignee_name,''), agent_name_snapshot, '')")
        conn.execute("UPDATE runs SET result_text = COALESCE(NULLIF(result_text,''), result_summary, '')")
        conn.execute("UPDATE runs SET status = 'completed' WHERE lower(COALESCE(status,'')) IN ('completed','complete')")
        conn.execute("UPDATE runs SET status = 'cancelled' WHERE lower(COALESCE(status,'')) IN ('cancelled','canceled')")
        backfill_run_semantics(conn)
        conn.execute("UPDATE agents SET deployment_status = COALESCE(NULLIF(deployment_status,''), 'not_deployed')")

        if 'status' in task_columns:

            conn.execute("UPDATE tasks SET status = 'backlog' WHERE LOWER(COALESCE(status,'')) = 'pending'")
            conn.execute("UPDATE tasks SET status = 'completed' WHERE LOWER(COALESCE(status,'')) IN ('completed','done','complete')")
            conn.execute("UPDATE tasks SET status = 'revision_requested' WHERE LOWER(COALESCE(status,'')) IN ('revision requested','revision-requested')")
            conn.execute("UPDATE tasks SET status = 'in_progress' WHERE LOWER(COALESCE(status,'')) = 'in progress'")
        conn.execute("UPDATE tasks SET updated_at = COALESCE(NULLIF(updated_at,''), created_at, ?) WHERE COALESCE(NULLIF(updated_at,''), '') = ''", (utc_now(),))

        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if count == 0:
            now = utc_now()
            seeds = [
                ("Review Mission Control dashboard data cards", "Confirm the top-level cards match Hermes ops priorities.", "ready", "high", "", "Baseline validation pass for the dashboard layer."),
                ("Add Nginx Proxy Manager host after local validation", "Keep app bound to 127.0.0.1; proxy from same VPS only.", "backlog", "medium", "", "Infrastructure follow-up once the board MVP is stable."),
                ("Audit read-only SQLite queries", "Verify all Hermes DB connections use mode=ro and query_only.", "ready", "high", "", "Protect AgentForge dashboards from accidental writes outside board.db."),
                ("Map JobForge migration metrics into dashboard", "Future widget for scraper/apply pipeline health.", "backlog", "medium", "", "Defer implementation until the orchestration layer is stable."),
                ("Validate Telegram and Discord gateway health", "Watch platform status and updated_at values.", "in_progress", "high", "", "Live ops visibility check."),
                ("Check cron visibility for morning JobForge run", "Make sure human-readable schedules are clear.", "blocked", "medium", "Waiting for main app refresh after route changes.", "Blocked until the updated AgentForge process is reloaded."),
                ("Document dashboard tunnel access", "Use SSH tunnel if exposing privately from laptop.", "done", "low", "", "Reference-only infrastructure note."),
            ]
            seeded_ids = []
            for title, description, status, priority, blocked_reason, notes in seeds:
                task_id = uuid.uuid4().hex
                seeded_ids.append(task_id)
                conn.execute(
                    """
                    INSERT INTO tasks (
                        id, title, description, status, priority, agent_id, playbook_id, blocked_reason, notes, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (task_id, title, description, status, priority, '', '', blocked_reason, notes, now, now),
                )
            if len(seeded_ids) >= 2:
                conn.execute(
                    "INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_task_id) VALUES (?, ?)",
                    (seeded_ids[4], seeded_ids[2]),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_task_id) VALUES (?, ?)",
                    (seeded_ids[5], seeded_ids[1]),
                )

        run_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        if run_count == 0:
            insert_seed_runs(conn)
        conn.commit()


def normalize_task_status(value) -> str:
    raw = str(value or 'backlog').strip().lower()
    status = TASK_STATUS_ALIASES.get(raw, raw or 'backlog')
    if status not in TASK_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(TASK_STATUSES)}")
    return status


def normalize_task_priority(value) -> str:
    priority = str(value or 'medium').strip().lower()
    if priority not in TASK_PRIORITIES:
        raise ValueError(f"priority must be one of: {', '.join(TASK_PRIORITIES)}")
    return priority


def normalize_audit_state(value) -> str:
    raw = str(value or '').strip().lower()
    if not raw:
        return ''
    state = AUDIT_STATE_ALIASES.get(raw, raw)
    return state if state in AUDIT_STATES else ''


def parse_task_dependency_ids(value) -> list[str]:
    ids = []
    seen = set()
    for item in parse_json_list(value):
        clean = str(item).strip()
        if clean and clean not in seen:
            ids.append(clean)
            seen.add(clean)
    return ids


def task_exists(conn: sqlite3.Connection, table: str, row_id: str) -> bool:
    if not row_id:
        return False
    row = conn.execute(f"SELECT id FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return row is not None


def task_dependency_ids(conn: sqlite3.Connection, task_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT depends_on_task_id FROM task_dependencies WHERE task_id = ? ORDER BY id ASC",
        (task_id,),
    ).fetchall()
    return [str(row['depends_on_task_id']) for row in rows if row['depends_on_task_id']]


def normalize_task_row(row, conn: sqlite3.Connection) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    item['id'] = str(item.get('id') or '')
    item['title'] = str(item.get('title') or '')
    item['description'] = str(item.get('description') or '')
    item['status'] = normalize_task_status(item.get('status') or 'backlog')
    item['priority'] = normalize_task_priority(item.get('priority') or 'medium')
    item['agent_id'] = str(item.get('agent_id') or '')
    item['playbook_id'] = str(item.get('playbook_id') or '')
    item['blocked_reason'] = str(item.get('blocked_reason') or '')
    item['notes'] = str(item.get('notes') or '')
    item['result_text'] = str(item.get('result_text') or '')
    item['last_note'] = str(item.get('last_note') or '')
    item['audit_state'] = normalize_audit_state(item.get('audit_state') or '')
    item['audit_note'] = str(item.get('audit_note') or '')
    item['audit_updated_at'] = str(item.get('audit_updated_at') or '')
    item['assigned_agent_name'] = str(item.get('assigned_agent_name') or '')
    item['linked_playbook_name'] = str(item.get('linked_playbook_name') or '')
    item['instruction'] = item['description']
    item['assigneeId'] = item['agent_id']
    item['assigneeName'] = item['assigned_agent_name']
    item['playbookId'] = item['playbook_id']
    item['playbookName'] = item['linked_playbook_name']
    item['result'] = item['result_text']
    item['lastNote'] = item['last_note']
    item['auditState'] = item['audit_state']
    item['auditNote'] = item['audit_note']
    item['auditUpdatedAt'] = item['audit_updated_at']
    item['createdAt'] = str(item.get('created_at') or '')
    item['updatedAt'] = str(item.get('updated_at') or '')
    item['created_at'] = str(item.get('created_at') or '')
    item['updated_at'] = str(item.get('updated_at') or '')
    dependency_ids = task_dependency_ids(conn, item['id'])
    item['dependency_ids'] = dependency_ids
    item['attachment_ids'] = []
    item['attachments'] = task_attachments_for_task(conn, item['id'])
    item['attachment_ids'] = [attachment['id'] for attachment in item['attachments'] if attachment.get('id')]
    item['dependencies'] = [
        {'id': dep_id, 'title': dep_title}
        for dep_id, dep_title in conn.execute(
            """
            SELECT td.depends_on_task_id, COALESCE(t.title, '')
            FROM task_dependencies td
            LEFT JOIN tasks t ON t.id = td.depends_on_task_id
            WHERE td.task_id = ?
            ORDER BY td.id ASC
            """,
            (item['id'],),
        ).fetchall()
    ]
    return item


def task_history_list(conn: sqlite3.Connection, task_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, task_id, event_type, message, note, metadata_json, created_at
        FROM task_events
        WHERE task_id = ?
        ORDER BY created_at ASC, id ASC
        """,
        (task_id,),
    ).fetchall()
    history = []
    for row in rows:
        item = dict(row)
        item['id'] = int(item.get('id') or 0)
        item['task_id'] = str(item.get('task_id') or '')
        item['event_type'] = str(item.get('event_type') or '')
        item['message'] = str(item.get('message') or '')
        item['note'] = str(item.get('note') or '')
        item['created_at'] = str(item.get('created_at') or '')
        item['metadata'] = parse_json_object(item.get('metadata_json'))
        item['createdAt'] = item['created_at']
        history.append(item)
    return history


def task_event_create(conn: sqlite3.Connection, task_id: str, event_type: str, message: str, note: str = '', metadata: dict | None = None, created_at: str | None = None):
    conn.execute(
        """
        INSERT INTO task_events (task_id, event_type, message, note, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(task_id or '').strip(),
            str(event_type or '').strip() or 'updated',
            str(message or '').strip() or 'Task updated.',
            str(note or '').strip(),
            json.dumps(metadata or {}, ensure_ascii=False),
            created_at or utc_now(),
        ),
    )


TASK_SELECT = """
SELECT
  t.*,
  COALESCE(a.name, '') AS assigned_agent_name,
  COALESCE(p.name, '') AS linked_playbook_name
FROM tasks t
LEFT JOIN agents a ON a.id = t.agent_id
LEFT JOIN playbooks p ON p.id = t.playbook_id
"""


def task_record_from_payload(payload: dict, conn: sqlite3.Connection, existing: dict | None = None) -> tuple[dict, list[str], list[str], str]:
    source = dict(existing or {})
    title = str(payload.get('title', source.get('title', '')) or '').strip()
    if not title:
        raise ValueError('title is required')
    instruction = str(payload.get('instruction', payload.get('description', source.get('description', ''))) or '').strip()
    if not instruction:
        raise ValueError('instruction is required')
    task_id = source.get('id') or uuid.uuid4().hex
    status = normalize_task_status(payload.get('status', source.get('status', 'backlog')) or 'backlog')
    priority = normalize_task_priority(payload.get('priority', source.get('priority', 'medium')) or 'medium')
    agent_id = str(payload.get('agent_id', payload.get('assigneeId', source.get('agent_id', ''))) or '').strip()
    playbook_id = str(payload.get('playbook_id', payload.get('playbookId', source.get('playbook_id', ''))) or '').strip()
    result_text = str(payload.get('result_text', payload.get('result', source.get('result_text', ''))) or '').strip()
    last_note = str(payload.get('last_note', payload.get('lastNote', source.get('last_note', ''))) or '').strip()
    audit_note = str(payload.get('audit_note', payload.get('auditNote', source.get('audit_note', ''))) or '').strip()
    explicit_audit_state = payload.get('audit_state', payload.get('auditState', None))
    audit_state = normalize_audit_state(explicit_audit_state if explicit_audit_state is not None else source.get('audit_state', ''))
    now = utc_now()
    audit_updated_at = str(source.get('audit_updated_at') or '')
    if status == 'review' and explicit_audit_state is None and not audit_state:
        audit_state = 'pending_review'
        audit_updated_at = now
    if explicit_audit_state is not None or audit_note != str(source.get('audit_note', '') or '').strip():
        audit_updated_at = now
    if status == 'ready' and not agent_id:
        raise ValueError('Run Now requires assignee')
    dependency_ids = parse_task_dependency_ids(payload.get('dependency_ids', payload.get('dependencies', [])))
    attachment_ids = parse_task_attachment_ids(payload.get('attachment_ids', payload.get('attachments', [])))
    attachment_draft_token = str(payload.get('attachment_draft_token', payload.get('draft_token', '')) or '').strip()
    if task_id in dependency_ids:
        raise ValueError('dependency IDs must not include the task itself')
    if agent_id and not task_exists(conn, 'agents', agent_id):
        raise ValueError('agent_id does not match an existing agent')
    if playbook_id and not task_exists(conn, 'playbooks', playbook_id):
        raise ValueError('playbook_id does not match an existing playbook')
    if dependency_ids:
        placeholders = ','.join(['?'] * len(dependency_ids))
        found = {
            row['id']
            for row in conn.execute(f"SELECT id FROM tasks WHERE id IN ({placeholders})", dependency_ids).fetchall()
        }
        missing = [dep_id for dep_id in dependency_ids if dep_id not in found]
        if missing:
            raise ValueError(f"unknown dependency task IDs: {', '.join(missing)}")
    attachment_rows = task_attachment_rows_for_ids(conn, attachment_ids)
    for row in attachment_rows:
        owner_task_id = str(row.get('task_id') or '').strip()
        owner_draft_token = str(row.get('draft_token') or '').strip()
        if owner_task_id and owner_task_id != task_id:
            raise ValueError(f"attachment belongs to another task: {row.get('filename') or row.get('id')}")
        if not owner_task_id:
            if not attachment_draft_token:
                raise ValueError('attachment_draft_token is required for staged attachments')
            if owner_draft_token != attachment_draft_token:
                raise ValueError(f"attachment draft token mismatch: {row.get('filename') or row.get('id')}")
    item = {
        'id': task_id,
        'title': title,
        'description': instruction,
        'status': status,
        'priority': priority,
        'agent_id': agent_id,
        'playbook_id': playbook_id,
        'blocked_reason': str(payload.get('blocked_reason', source.get('blocked_reason', '')) or '').strip(),
        'notes': str(payload.get('notes', source.get('notes', '')) or '').strip(),
        'result_text': result_text,
        'last_note': last_note,
        'audit_state': audit_state,
        'audit_note': audit_note,
        'audit_updated_at': audit_updated_at,
        'created_at': source.get('created_at') or now,
        'updated_at': now,
    }
    return item, dependency_ids, attachment_ids, attachment_draft_token


def task_list() -> list[dict]:
    with connect_board() as conn:
        rows = conn.execute(
            TASK_SELECT + " ORDER BY CASE t.status WHEN 'ready' THEN 0 WHEN 'triage' THEN 1 WHEN 'backlog' THEN 2 WHEN 'in_progress' THEN 3 WHEN 'review' THEN 4 WHEN 'revision_requested' THEN 5 WHEN 'blocked' THEN 6 WHEN 'completed' THEN 7 ELSE 8 END, CASE t.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, t.updated_at DESC, t.created_at DESC"
        ).fetchall()
        return [normalize_task_row(row, conn) for row in rows]


def task_get(task_id: str):
    if not task_id:
        raise ValueError('id is required')
    with connect_board() as conn:
        row = conn.execute(TASK_SELECT + " WHERE t.id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError('task not found')
        task = normalize_task_row(row, conn)
        runs = task_runs_list(conn, task_id)
        latest_run = runs[0] if runs else None
        task['runs'] = runs
        task['latest_run'] = latest_run
        return {'task': task, 'history': task_history_list(conn, task_id), 'runs': runs, 'latest_run': latest_run}


def task_history_get(task_id: str):
    if not task_id:
        raise ValueError('id is required')
    with connect_board() as conn:
        if conn.execute('SELECT id FROM tasks WHERE id = ?', (task_id,)).fetchone() is None:
            raise KeyError('task not found')
        return {'history': task_history_list(conn, task_id)}


def task_runs_get(task_id: str):
    if not task_id:
        raise ValueError('id is required')
    with connect_board() as conn:
        if conn.execute('SELECT id FROM tasks WHERE id = ?', (task_id,)).fetchone() is None:
            raise KeyError('task not found')
        runs = task_runs_list(conn, task_id)
        return {'runs': runs, 'latest_run': runs[0] if runs else None}


def sync_task_dependencies(conn: sqlite3.Connection, task_id: str, dependency_ids: list[str]):
    conn.execute('DELETE FROM task_dependencies WHERE task_id = ?', (task_id,))
    for dep_id in dependency_ids:
        conn.execute(
            'INSERT OR IGNORE INTO task_dependencies (task_id, depends_on_task_id) VALUES (?, ?)',
            (task_id, dep_id),
        )


def task_create(payload: dict):
    with connect_board() as conn:
        base_title = trim_run_text(f"Create task: {str((payload or {}).get('title') or 'Untitled task').strip() or 'Untitled task'}", 140)
        initial_ctx = run_context_for_task(conn, task=dict(payload or {}))
        run = create_run_record(
            conn,
            run_type="task_run",
            title=base_title,
            status="queued",
            summary="Task create request queued.",
            run_detail="Task payload accepted and queued for board write.",
            result_label="Queued",
            trigger_label="Manual board action",
            log_preview="Validating task payload.",
            run_source="user",
            run_purpose="task_lifecycle",
            **initial_ctx,
        )
        mark_run_running(conn, run["id"], summary="Creating task record.", run_detail="Validated task payload. Writing board row and dependency links.", result_label="Running", trigger_label="Manual board action", log_preview="Validated task payload. Writing to board.db.")
        try:
            task, dependency_ids, attachment_ids, attachment_draft_token = task_record_from_payload(payload, conn)
            conn.execute(
                """
                INSERT INTO tasks (
                    id, title, description, status, priority, agent_id, playbook_id, blocked_reason, notes, result_text, last_note, audit_state, audit_note, audit_updated_at, created_at, updated_at
                ) VALUES (
                    :id, :title, :description, :status, :priority, :agent_id, :playbook_id, :blocked_reason, :notes, :result_text, :last_note, :audit_state, :audit_note, :audit_updated_at, :created_at, :updated_at
                )
                """,
                task,
            )
            sync_task_dependencies(conn, task['id'], dependency_ids)
            sync_task_attachments(conn, task['id'], attachment_ids, attachment_draft_token)
            row = conn.execute(TASK_SELECT + " WHERE t.id = ?", (task['id'],)).fetchone()
            record = normalize_task_row(row, conn)
            task_event_create(conn, record['id'], 'created', f"Task created in {str(record['status']).replace('_', ' ').title()}.", note=record.get('last_note', ''), metadata={'status': record.get('status',''), 'agent_id': record.get('agent_id',''), 'playbook_id': record.get('playbook_id',''), 'result_text': record.get('result_text','')}, created_at=record.get('created_at') or utc_now())
            if record.get('audit_state') == 'pending_review':
                task_event_create(conn, record['id'], 'audit_requested', 'Task entered audit review.', note=record.get('audit_note', ''), metadata={'audit_state': record.get('audit_state', '')}, created_at=record.get('audit_updated_at') or record.get('updated_at') or utc_now())
            final_ctx = run_context_for_task(conn, task_id=record['id'], task=record)
            status_label = str(record['status']).replace('_', ' ').title()
            complete_run_record(
                conn,
                run["id"],
                "success",
                summary=f"Task \"{record['title']}\" created in {status_label}.",
                run_detail=f"Priority set to {record['priority']}. {len(record.get('dependency_ids') or [])} dependency link(s) and {len(record.get('attachment_ids') or [])} attachment(s) saved.",
                result_label="Created",
                log_preview=f"Created {record['title']} · priority {record['priority']} · dependencies {len(record.get('dependency_ids') or [])} · attachments {len(record.get('attachment_ids') or [])}.",
                trigger_label="Manual board action",
                changed_fields=["Title", "Status", "Priority", "Dependencies", "Attachments"],
                metadata={**run_context_metadata(task_id=record['id'], task_title=record['title'], agent_id=record.get('agent_id',''), deployment_id=final_ctx.get('deployment_id',''), deployment_target=final_ctx.get('deployment_target_snapshot',''), deployment_type=final_ctx.get('deployment_type_snapshot','')), "priority": record['priority'], "status": status_label, "dependency_count": len(record.get('dependency_ids') or []), "attachment_count": len(record.get('attachment_ids') or [])},
                title=trim_run_text(f"Create task: {record['title']}", 140),
                **final_ctx,
            )
            conn.commit()
            return record
        except Exception as exc:
            complete_run_record(
                conn,
                run["id"],
                "failed",
                summary="Task create failed.",
                run_detail="Task row was not created. Review the validation error for the blocked field or reference.",
                result_label="Failed",
                error_message=str(exc),
                log_preview=trim_run_text(str(exc) or "Task create failed.", 420),
                trigger_label="Manual board action",
                title=base_title,
                **initial_ctx,
            )
            conn.commit()
            raise


def task_update(task_id: str, payload: dict):
    if not task_id:
        raise ValueError('id is required')
    with connect_board() as conn:
        existing = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
        if existing is None:
            raise KeyError('task not found')
        existing_row = dict(existing)
        existing_record = normalize_task_row(existing, conn)
        explicit_thread_note = str((payload or {}).get('thread_note', (payload or {}).get('threadNote', (payload or {}).get('comment', ''))) or '').strip()
        explicit_audit_note = str((payload or {}).get('audit_note', (payload or {}).get('auditNote', '')) or '').strip()
        explicit_audit_state = (payload or {}).get('audit_state', (payload or {}).get('auditState', None))
        base_title = trim_run_text(f"Update task: {existing_row.get('title') or 'Untitled task'}", 140)
        initial_ctx = run_context_for_task(conn, task_id=task_id, task=existing_row)
        run = create_run_record(
            conn,
            run_type="task_run",
            title=base_title,
            status="queued",
            summary="Task update request queued.",
            run_detail="Current task snapshot loaded and queued for change application.",
            result_label="Queued",
            trigger_label="Manual board action",
            log_preview="Loading current task state.",
            run_source="user",
            run_purpose="task_lifecycle",
            **initial_ctx,
        )
        mark_run_running(conn, run["id"], summary="Applying task changes.", run_detail="Writing task fields and dependency links.", result_label="Running", trigger_label="Manual board action", log_preview="Current task loaded. Writing updated fields.")
        try:
            task, dependency_ids, attachment_ids, attachment_draft_token = task_record_from_payload(payload, conn, existing_row)
            conn.execute(
                """
                UPDATE tasks
                SET title = :title,
                    description = :description,
                    status = :status,
                    priority = :priority,
                    agent_id = :agent_id,
                    playbook_id = :playbook_id,
                    blocked_reason = :blocked_reason,
                    notes = :notes,
                    result_text = :result_text,
                    last_note = :last_note,
                    audit_state = :audit_state,
                    audit_note = :audit_note,
                    audit_updated_at = :audit_updated_at,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                task,
            )
            sync_task_dependencies(conn, task_id, dependency_ids)
            sync_task_attachments(conn, task_id, attachment_ids, attachment_draft_token)
            row = conn.execute(TASK_SELECT + " WHERE t.id = ?", (task_id,)).fetchone()
            record = normalize_task_row(row, conn)
            previous_status = str(existing_record.get('status') or '')
            current_status = str(record.get('status') or '')
            if previous_status != current_status:
                task_event_create(conn, record['id'], 'status_changed', f"Status changed from {previous_status.replace('_', ' ').title() or 'Unknown'} to {current_status.replace('_', ' ').title()}.", note=record.get('last_note', ''), metadata={'from_status': previous_status, 'to_status': current_status})
            if str(existing_record.get('agent_id') or '') != str(record.get('agent_id') or ''):
                before_name = existing_record.get('assigned_agent_name') or 'Unassigned'
                after_name = record.get('assigned_agent_name') or 'Unassigned'
                task_event_create(conn, record['id'], 'assignee_changed', f"Assignee changed from {before_name} to {after_name}.", metadata={'from_agent_id': existing_record.get('agent_id',''), 'to_agent_id': record.get('agent_id','')})
            if str(existing_record.get('playbook_id') or '') != str(record.get('playbook_id') or ''):
                before_name = existing_record.get('linked_playbook_name') or 'No playbook'
                after_name = record.get('linked_playbook_name') or 'No playbook'
                task_event_create(conn, record['id'], 'playbook_changed', f"Playbook changed from {before_name} to {after_name}.", metadata={'from_playbook_id': existing_record.get('playbook_id',''), 'to_playbook_id': record.get('playbook_id','')})
            if str(existing_record.get('description') or '') != str(record.get('description') or ''):
                task_event_create(conn, record['id'], 'instruction_updated', 'Instruction updated.', metadata={'previous_length': len(str(existing_record.get('description') or '')), 'current_length': len(str(record.get('description') or ''))})
            if str(existing_record.get('result_text') or '') != str(record.get('result_text') or ''):
                task_event_create(conn, record['id'], 'result_saved', 'Result/output updated.', note=record.get('result_text', ''), metadata={'has_result': bool(str(record.get('result_text') or '').strip())})
            if record.get('last_note') and str(existing_record.get('last_note') or '') != str(record.get('last_note') or '') and previous_status == current_status and not explicit_thread_note:
                task_event_create(conn, record['id'], 'note_saved', 'Operator note updated.', note=record.get('last_note', ''))
            if explicit_thread_note:
                task_event_create(conn, record['id'], 'thread_comment', 'Task thread note added.', note=explicit_thread_note, metadata={'kind': 'thread_comment'})
            previous_audit_state = normalize_audit_state(existing_record.get('audit_state') or '')
            current_audit_state = normalize_audit_state(record.get('audit_state') or '')
            previous_audit_note = str(existing_record.get('audit_note') or '')
            current_audit_note = str(record.get('audit_note') or '')
            if previous_audit_state != current_audit_state:
                audit_event_map = {
                    'pending_review': ('audit_requested', 'Task entered audit review.', current_audit_note, {'audit_state': current_audit_state}),
                    'approved': ('audit_approved', 'Task approved during audit.', current_audit_note, {'audit_state': current_audit_state}),
                    'rejected': ('audit_rejected', 'Task rejected during audit.', current_audit_note, {'audit_state': current_audit_state}),
                    'revision_requested': ('revision_requested', 'Revision requested during audit.', current_audit_note, {'audit_state': current_audit_state}),
                }
                if current_audit_state in audit_event_map:
                    event_type, message, note, metadata = audit_event_map[current_audit_state]
                    task_event_create(conn, record['id'], event_type, message, note=note, metadata=metadata)
            if explicit_audit_note and previous_audit_note != current_audit_note:
                task_event_create(conn, record['id'], 'audit_note_saved', 'Audit note saved.', note=current_audit_note, metadata={'audit_state': current_audit_state or previous_audit_state})
            elif explicit_audit_state is not None and previous_audit_note != current_audit_note and current_audit_note:
                task_event_create(conn, record['id'], 'audit_note_saved', 'Audit note saved.', note=current_audit_note, metadata={'audit_state': current_audit_state})
            final_ctx = run_context_for_task(conn, task_id=record['id'], task=record)
            status_label = str(record['status']).replace('_', ' ').title()
            changed_fields = run_changed_fields_for_keys(existing_row, record, [('title', 'Title'), ('status', 'Status'), ('priority', 'Priority'), ('agent_id', 'Assigned Agent'), ('playbook_id', 'Playbook'), ('blocked_reason', 'Blocked Reason'), ('notes', 'Notes'), ('description', 'Description')])
            if sorted(existing_row.get('dependency_ids') or []) != sorted(record.get('dependency_ids') or []):
                changed_fields.append('Dependencies')
            if sorted((existing_row.get('attachment_ids') or [])) != sorted(record.get('attachment_ids') or []):
                changed_fields.append('Attachments')
            summary = f"Task \"{record['title']}\" updated."
            previous_status_label = str(existing_row.get('status') or '').replace('_', ' ').title()
            if previous_status_label and previous_status_label != status_label:
                summary = f"Task \"{record['title']}\" moved from {previous_status_label} to {status_label}."
            complete_run_record(
                conn,
                run["id"],
                "success",
                summary=summary,
                run_detail=f"Changed {', '.join(changed_fields) if changed_fields else 'task metadata'}; task now has priority {record['priority']}, {len(record.get('dependency_ids') or [])} dependency link(s), and {len(record.get('attachment_ids') or [])} attachment(s).",
                result_label="Updated",
                log_preview=f"Saved {record['title']} · priority {record['priority']} · dependencies {len(record.get('dependency_ids') or [])} · attachments {len(record.get('attachment_ids') or [])}.",
                trigger_label="Manual board action",
                changed_fields=changed_fields,
                metadata={**run_context_metadata(task_id=record['id'], task_title=record['title'], agent_id=record.get('agent_id',''), deployment_id=final_ctx.get('deployment_id',''), deployment_target=final_ctx.get('deployment_target_snapshot',''), deployment_type=final_ctx.get('deployment_type_snapshot','')), 'status': status_label, 'priority': record['priority'], 'dependency_count': len(record.get('dependency_ids') or []), 'attachment_count': len(record.get('attachment_ids') or [])},
                title=trim_run_text(f"Update task: {record['title']}", 140),
                **final_ctx,
            )
            conn.commit()
            return record
        except Exception as exc:
            complete_run_record(
                conn,
                run["id"],
                "failed",
                summary="Task update failed.",
                run_detail="Task changes were not committed. Review the validation or reference error.",
                result_label="Failed",
                error_message=str(exc),
                log_preview=trim_run_text(str(exc) or "Task update failed.", 420),
                trigger_label="Manual board action",
                title=base_title,
                **initial_ctx,
            )
            conn.commit()
            raise


def task_delete(task_id: str):
    if not task_id:
        raise ValueError('id is required')
    with connect_board() as conn:
        existing = conn.execute('SELECT * FROM tasks WHERE id = ?', (task_id,)).fetchone()
        if existing is None:
            raise KeyError('task not found')
        existing_row = dict(existing)
        base_title = trim_run_text(f"Delete task: {existing_row.get('title') or 'Untitled task'}", 140)
        initial_ctx = run_context_for_task(conn, task_id=task_id, task=existing_row)
        run = create_run_record(
            conn,
            run_type="task_run",
            title=base_title,
            status="queued",
            summary="Task delete request queued.",
            run_detail="Task queued for removal from the board and dependency graph.",
            result_label="Queued",
            trigger_label="Manual board action",
            log_preview="Preparing task removal.",
            run_source="user",
            run_purpose="task_lifecycle",
            **initial_ctx,
        )
        mark_run_running(conn, run["id"], summary="Deleting task record.", run_detail="Removing task row, dependency links, and task attachments.", result_label="Running", trigger_label="Manual board action", log_preview="Removing task, dependency links, and attachments.")
        try:
            dependency_links = conn.execute('SELECT COUNT(*) FROM task_dependencies WHERE task_id = ? OR depends_on_task_id = ?', (task_id, task_id)).fetchone()[0]
            attachment_rows = conn.execute('SELECT * FROM task_attachments WHERE task_id = ? ORDER BY uploaded_at ASC, created_at ASC', (task_id,)).fetchall()
            attachment_count = len(attachment_rows)
            delete_task_attachment_rows(conn, attachment_rows)
            conn.execute('DELETE FROM task_dependencies WHERE task_id = ? OR depends_on_task_id = ?', (task_id, task_id))
            conn.execute('DELETE FROM task_events WHERE task_id = ?', (task_id,))
            cur = conn.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
            complete_run_record(
                conn,
                run["id"],
                "success",
                summary=f"Task \"{existing_row.get('title') or 'Untitled task'}\" removed from the board.",
                run_detail=f"Deleted the task row, detached {dependency_links} related dependency link(s), and removed {attachment_count} attachment(s).",
                result_label="Deleted",
                log_preview=f"Deleted {existing_row.get('title') or 'Untitled task'} · detached dependency links · removed {attachment_count} attachment(s).",
                trigger_label="Manual board action",
                changed_fields=['Deleted', 'Dependencies', 'Attachments'],
                metadata={**run_context_metadata(task_id=task_id, task_title=existing_row.get('title',''), agent_id=existing_row.get('agent_id',''), deployment_id=initial_ctx.get('deployment_id',''), deployment_target=initial_ctx.get('deployment_target_snapshot',''), deployment_type=initial_ctx.get('deployment_type_snapshot','')), 'dependency_links_removed': dependency_links, 'attachment_count_removed': attachment_count},
                title=base_title,
                **initial_ctx,
            )
            conn.commit()
            if cur.rowcount == 0:
                raise KeyError('task not found')
            return {'deleted': cur.rowcount, 'id': task_id}
        except Exception as exc:
            complete_run_record(
                conn,
                run["id"],
                "failed",
                summary="Task delete failed.",
                run_detail="Task row was not removed. Review the error before retrying deletion.",
                result_label="Failed",
                error_message=str(exc),
                log_preview=trim_run_text(str(exc) or "Task delete failed.", 420),
                trigger_label="Manual board action",
                title=base_title,
                **initial_ctx,
            )
            conn.commit()
            raise


def board_list():
    return task_list()



def board_create(payload: dict):
    board_payload = dict(payload or {})
    status = board_payload.get('status') or 'backlog'
    board_payload['status'] = TASK_STATUS_ALIASES.get(str(status).lower(), str(status).lower())
    return task_create(board_payload)


def board_update(task_id: str, payload: dict):
    board_payload = dict(payload or {})
    if 'status' in board_payload:
        board_payload['status'] = TASK_STATUS_ALIASES.get(str(board_payload.get('status')).lower(), str(board_payload.get('status')).lower())
    return task_update(task_id, board_payload)


def board_delete(task_id: str):
    return task_delete(task_id)

PLAYBOOK_LIST_FIELDS = ["rules", "linked_tools", "examples", "template_refs"]
PLAYBOOK_TEXT_FIELDS = ["name", "slug", "description", "category", "purpose", "sop", "input_schema", "output_schema"]


def normalize_playbook_row(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    for key in PLAYBOOK_LIST_FIELDS:
        item[key] = decode_json_list(item.get(key))
    for key in PLAYBOOK_TEXT_FIELDS:
        item[key] = str(item.get(key) or "")
    return item


def unique_playbook_slug(conn: sqlite3.Connection, preferred: str, exclude_id: str | None = None) -> str:
    base = slugify(preferred)
    slug = base
    counter = 2
    while True:
        row = conn.execute("SELECT id FROM playbooks WHERE slug = ?", (slug,)).fetchone()
        if row is None or (exclude_id and row["id"] == exclude_id):
            return slug
        slug = f"{base}-{counter}"
        counter += 1


def playbook_record_from_payload(payload: dict, conn: sqlite3.Connection, existing: dict | None = None) -> dict:
    source = dict(existing or {})
    name = str(payload.get("name", source.get("name", "")) or "").strip()
    if not name:
        raise ValueError("name is required")
    slug_source = payload.get("slug", source.get("slug") or name)
    slug = unique_playbook_slug(conn, str(slug_source or name), source.get("id"))
    now = utc_now()
    item = {
        "id": source.get("id") or uuid.uuid4().hex,
        "slug": slug,
        "name": name,
        "description": str(payload.get("description", source.get("description", "")) or "").strip(),
        "category": str(payload.get("category", source.get("category", "")) or "").strip(),
        "purpose": str(payload.get("purpose", source.get("purpose", "")) or "").strip(),
        "sop": str(payload.get("sop", source.get("sop", "")) or "").strip(),
        "rules": dump_json_list(payload.get("rules", source.get("rules", []))),
        "input_schema": str(payload.get("input_schema", source.get("input_schema", "")) or "").strip(),
        "output_schema": str(payload.get("output_schema", source.get("output_schema", "")) or "").strip(),
        "linked_tools": dump_json_list(payload.get("linked_tools", source.get("linked_tools", []))),
        "examples": dump_json_list(payload.get("examples", source.get("examples", []))),
        "template_refs": dump_json_list(payload.get("template_refs", source.get("template_refs", []))),
        "created_at": source.get("created_at") or now,
        "updated_at": now,
    }
    return item


def playbook_list() -> list[dict]:
    with connect_board() as conn:
        rows = conn.execute("SELECT * FROM playbooks ORDER BY updated_at DESC, created_at DESC, name ASC").fetchall()
    return [normalize_playbook_row(row) for row in rows]


def playbook_get(playbook_id: str = "", slug: str = "") -> dict:
    if not playbook_id and not slug:
        raise ValueError("id or slug is required")
    with connect_board() as conn:
        row = None
        if playbook_id:
            row = conn.execute("SELECT * FROM playbooks WHERE id = ?", (playbook_id,)).fetchone()
        if row is None and slug:
            row = conn.execute("SELECT * FROM playbooks WHERE slug = ?", (slug,)).fetchone()
    if row is None:
        raise KeyError("playbook not found")
    return normalize_playbook_row(row)


def playbook_create(payload: dict) -> dict:
    with connect_board() as conn:
        item = playbook_record_from_payload(payload, conn)
        conn.execute(
            """
            INSERT INTO playbooks (
              id, slug, name, description, category, purpose, sop, rules,
              input_schema, output_schema, linked_tools, examples, template_refs,
              created_at, updated_at
            ) VALUES (
              :id, :slug, :name, :description, :category, :purpose, :sop, :rules,
              :input_schema, :output_schema, :linked_tools, :examples, :template_refs,
              :created_at, :updated_at
            )
            """,
            item,
        )
        conn.commit()
    return playbook_get(playbook_id=item["id"])


def playbook_update(playbook_id: str, payload: dict) -> dict:
    if not playbook_id:
        raise ValueError("id is required")
    with connect_board() as conn:
        existing = conn.execute("SELECT * FROM playbooks WHERE id = ?", (playbook_id,)).fetchone()
        if existing is None:
            raise KeyError("playbook not found")
        item = playbook_record_from_payload(payload, conn, normalize_playbook_row(existing))
        conn.execute(
            """
            UPDATE playbooks
            SET slug = :slug,
                name = :name,
                description = :description,
                category = :category,
                purpose = :purpose,
                sop = :sop,
                rules = :rules,
                input_schema = :input_schema,
                output_schema = :output_schema,
                linked_tools = :linked_tools,
                examples = :examples,
                template_refs = :template_refs,
                updated_at = :updated_at
            WHERE id = :id
            """,
            item,
        )
        conn.commit()
    return playbook_get(playbook_id=playbook_id)


def playbook_delete(playbook_id: str) -> dict:
    if not playbook_id:
        raise ValueError("id is required")
    with connect_board() as conn:
        cur = conn.execute("DELETE FROM playbooks WHERE id = ?", (playbook_id,))
        conn.commit()
    if cur.rowcount == 0:
        raise KeyError("playbook not found")
    return {"deleted": cur.rowcount, "id": playbook_id}


AGENT_LIST_FIELDS = ["linked_playbook_ids", "allowed_tools"]
DEPLOYMENT_TEXT_FIELDS = [
    "id",
    "agent_id",
    "deployment_type",
    "target",
    "trigger_mode",
    "status",
    "notes",
    "last_checked_at",
    "created_at",
    "updated_at",
    "agent_name",
    "agent_status",
    "playbook_name",
]
AGENT_TEXT_FIELDS = [
    "name",
    "slug",
    "description",
    "category",
    "role",
    "purpose",
    "instructions",
    "constraints",
    "status",
    "input_schema",
    "output_schema",
    "runtime_notes",
    "deployment_status",
]


def normalize_agent_row(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    for key in AGENT_LIST_FIELDS:
        item[key] = decode_json_list(item.get(key))
    for key in AGENT_TEXT_FIELDS:
        item[key] = str(item.get(key) or "")
    deployment = item.get("deployment")
    item["deployment"] = normalize_deployment_row(deployment) if deployment else None
    item["deployment_type"] = str(item.get("deployment_type") or "")
    item["deployment_target"] = str(item.get("deployment_target") or "")
    item["deployment_trigger_mode"] = str(item.get("deployment_trigger_mode") or "")
    item["deployment_last_checked_at"] = str(item.get("deployment_last_checked_at") or "")
    return item


def unique_agent_slug(conn: sqlite3.Connection, preferred: str, exclude_id: str | None = None) -> str:
    base = slugify(preferred)
    slug = base
    counter = 2
    while True:
        row = conn.execute("SELECT id FROM agents WHERE slug = ?", (slug,)).fetchone()
        if row is None or (exclude_id and row["id"] == exclude_id):
            return slug
        slug = f"{base}-{counter}"
        counter += 1


def validate_linked_playbook_ids(conn: sqlite3.Connection, value) -> list[str]:
    ids = [str(x).strip() for x in parse_json_list(value) if str(x).strip()]
    if not ids:
        return []
    rows = conn.execute(
        f"SELECT id FROM playbooks WHERE id IN ({','.join(['?'] * len(ids))})",
        ids,
    ).fetchall()
    found = {str(row['id']) for row in rows}
    missing = [pid for pid in ids if pid not in found]
    if missing:
        raise ValueError(f"unknown playbook ids: {', '.join(missing)}")
    seen = set()
    clean = []
    for pid in ids:
        if pid not in seen:
            seen.add(pid)
            clean.append(pid)
    return clean


def agent_record_from_payload(payload: dict, conn: sqlite3.Connection, existing: dict | None = None) -> dict:
    source = dict(existing or {})
    name = str(payload.get("name", source.get("name", "")) or "").strip()
    if not name:
        raise ValueError("name is required")
    slug_source = payload.get("slug", source.get("slug") or name)
    slug = unique_agent_slug(conn, str(slug_source or name), source.get("id"))
    now = utc_now()
    status = str(payload.get("status", source.get("status", "draft")) or "draft").strip().lower() or "draft"
    if status not in {"draft", "active", "disabled"}:
        raise ValueError("status must be draft, active, or disabled")
    deployment_status = str(payload.get("deployment_status", source.get("deployment_status", "not_deployed")) or "not_deployed").strip().lower() or "not_deployed"
    linked_playbook_ids = validate_linked_playbook_ids(conn, payload.get("linked_playbook_ids", source.get("linked_playbook_ids", [])))
    role = str(payload.get("role", source.get("role", "")) or "").strip()
    purpose = str(payload.get("purpose", source.get("purpose", "")) or "").strip()
    if not role and not purpose:
        raise ValueError("role or purpose is required")
    item = {
        "id": source.get("id") or uuid.uuid4().hex,
        "slug": slug,
        "name": name,
        "description": str(payload.get("description", source.get("description", "")) or "").strip(),
        "category": str(payload.get("category", source.get("category", "")) or "").strip(),
        "role": role,
        "purpose": purpose,
        "instructions": str(payload.get("instructions", source.get("instructions", "")) or "").strip(),
        "constraints": str(payload.get("constraints", source.get("constraints", "")) or "").strip(),
        "status": status,
        "linked_playbook_ids": dump_json_list(linked_playbook_ids),
        "allowed_tools": dump_json_list(payload.get("allowed_tools", source.get("allowed_tools", []))),
        "input_schema": str(payload.get("input_schema", source.get("input_schema", "")) or "").strip(),
        "output_schema": str(payload.get("output_schema", source.get("output_schema", "")) or "").strip(),
        "runtime_notes": str(payload.get("runtime_notes", source.get("runtime_notes", "")) or "").strip(),
        "deployment_status": deployment_status,
        "created_at": source.get("created_at") or now,
        "updated_at": now,
    }
    return item


def agent_list() -> list[dict]:
    with connect_board() as conn:
        rows = conn.execute("SELECT * FROM agents ORDER BY updated_at DESC, created_at DESC, name ASC").fetchall()
        return [augment_agent_with_deployment(normalize_agent_row(row), conn) for row in rows]


def agent_get(agent_id: str = "", slug: str = "") -> dict:
    if not agent_id and not slug:
        raise ValueError("id or slug is required")
    with connect_board() as conn:
        row = None
        if agent_id:
            row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if row is None and slug:
            row = conn.execute("SELECT * FROM agents WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise KeyError("agent not found")
        return augment_agent_with_deployment(normalize_agent_row(row), conn)


def agent_create(payload: dict) -> dict:
    with connect_board() as conn:
        base_name = str((payload or {}).get("name") or "Untitled agent").strip() or "Untitled agent"
        base_title = trim_run_text(f"Create agent: {base_name}", 140)
        initial_ctx = run_context_for_agent(conn, agent=dict(payload or {}))
        run = create_run_record(
            conn,
            run_type="agent_execution",
            title=base_title,
            status="queued",
            summary="Agent configuration request queued.",
            run_detail="Agent payload accepted and queued for registry creation.",
            result_label="Queued",
            trigger_label="Manual registry action",
            log_preview="Validating agent payload.",
            run_source="user",
            run_purpose="agent_lifecycle",
            **initial_ctx,
        )
        mark_run_running(conn, run["id"], summary="Creating agent record.", run_detail="Writing agent registry row and resolving deployment context.", result_label="Running", trigger_label="Manual registry action", log_preview="Validated agent payload. Writing registry entry.")
        try:
            item = agent_record_from_payload(payload, conn)
            conn.execute(
                """
                INSERT INTO agents (
                  id, slug, name, description, category, role, purpose, instructions, constraints, status,
                  linked_playbook_ids, allowed_tools, input_schema, output_schema,
                  runtime_notes, deployment_status, created_at, updated_at
                ) VALUES (
                  :id, :slug, :name, :description, :category, :role, :purpose, :instructions, :constraints, :status,
                  :linked_playbook_ids, :allowed_tools, :input_schema, :output_schema,
                  :runtime_notes, :deployment_status, :created_at, :updated_at
                )
                """,
                item,
            )
            record = augment_agent_with_deployment(normalize_agent_row(conn.execute("SELECT * FROM agents WHERE id = ?", (item["id"],)).fetchone()), conn)
            final_ctx = run_context_for_agent(conn, agent_id=record["id"], agent=record)
            complete_run_record(
                conn,
                run["id"],
                "success",
                summary=f"Agent \"{record['name']}\" created with status {record['status']}.",
                run_detail=f"Role set to {record.get('role') or 'custom role'}. Linked {len(record.get('linked_playbook_ids') or [])} playbook(s) and {len(record.get('allowed_tools') or [])} tool permission(s).",
                result_label="Created",
                log_preview=f"Created {record['name']} · linked playbooks {len(record.get('linked_playbook_ids') or [])} · tools {len(record.get('allowed_tools') or [])}.",
                trigger_label="Manual registry action",
                changed_fields=['Name', 'Status', 'Role', 'Playbooks', 'Tools'],
                metadata={**run_context_metadata(agent_id=record['id'], agent_name=record['name'], deployment_id=final_ctx.get('deployment_id',''), deployment_target=final_ctx.get('deployment_target_snapshot',''), deployment_type=final_ctx.get('deployment_type_snapshot','')), 'status': record['status'], 'category': record.get('category',''), 'linked_playbooks': len(record.get('linked_playbook_ids') or []), 'allowed_tools': len(record.get('allowed_tools') or [])},
                title=trim_run_text(f"Create agent: {record['name']}", 140),
                **final_ctx,
            )
            conn.commit()
        except Exception as exc:
            complete_run_record(
                conn,
                run["id"],
                "failed",
                summary="Agent create failed.",
                run_detail="Agent registry row was not created. Review the validation error.",
                result_label="Failed",
                error_message=str(exc),
                log_preview=trim_run_text(str(exc) or "Agent create failed.", 420),
                trigger_label="Manual registry action",
                title=base_title,
                **initial_ctx,
            )
            conn.commit()
            raise
    return agent_get(agent_id=item["id"])


def agent_update(agent_id: str, payload: dict) -> dict:
    if not agent_id:
        raise ValueError("id is required")
    with connect_board() as conn:
        existing = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if existing is None:
            raise KeyError("agent not found")
        existing_row = normalize_agent_row(existing)
        base_title = trim_run_text(f"Update agent: {existing_row.get('name') or 'Untitled agent'}", 140)
        initial_ctx = run_context_for_agent(conn, agent_id=agent_id, agent=existing_row)
        run = create_run_record(
            conn,
            run_type="agent_execution",
            title=base_title,
            status="queued",
            summary="Agent update request queued.",
            run_detail="Current agent snapshot loaded and queued for registry changes.",
            result_label="Queued",
            trigger_label="Manual registry action",
            log_preview="Loading current agent configuration.",
            run_source="user",
            run_purpose="agent_lifecycle",
            **initial_ctx,
        )
        mark_run_running(conn, run["id"], summary="Applying agent changes.", run_detail="Writing updated agent registry fields.", result_label="Running", trigger_label="Manual registry action", log_preview="Current agent loaded. Writing registry changes.")
        try:
            item = agent_record_from_payload(payload, conn, existing_row)
            conn.execute(
                """
                UPDATE agents
                SET slug = :slug,
                    name = :name,
                    description = :description,
                    category = :category,
                    role = :role,
                    purpose = :purpose,
                    instructions = :instructions,
                    constraints = :constraints,
                    status = :status,
                    linked_playbook_ids = :linked_playbook_ids,
                    allowed_tools = :allowed_tools,
                    input_schema = :input_schema,
                    output_schema = :output_schema,
                    runtime_notes = :runtime_notes,
                    deployment_status = :deployment_status,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                item,
            )
            record = augment_agent_with_deployment(normalize_agent_row(conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()), conn)
            final_ctx = run_context_for_agent(conn, agent_id=record["id"], agent=record)
            changed_fields = run_changed_fields_for_keys(existing_row, record, [('name', 'Name'), ('status', 'Status'), ('role', 'Role'), ('purpose', 'Purpose'), ('category', 'Category'), ('instructions', 'Instructions'), ('constraints', 'Constraints'), ('runtime_notes', 'Runtime Notes')])
            if sorted(existing_row.get('linked_playbook_ids') or []) != sorted(record.get('linked_playbook_ids') or []): changed_fields.append('Playbooks')
            if sorted(existing_row.get('allowed_tools') or []) != sorted(record.get('allowed_tools') or []): changed_fields.append('Tools')
            complete_run_record(
                conn,
                run["id"],
                "success",
                summary=f"Agent \"{record['name']}\" updated with status {record['status']}.",
                run_detail=f"Changed {', '.join(changed_fields) if changed_fields else 'agent metadata'}; linked {len(record.get('linked_playbook_ids') or [])} playbook(s) and {len(record.get('allowed_tools') or [])} tool permission(s).",
                result_label="Updated",
                log_preview=f"Saved {record['name']} · linked playbooks {len(record.get('linked_playbook_ids') or [])} · tools {len(record.get('allowed_tools') or [])}.",
                trigger_label="Manual registry action",
                changed_fields=changed_fields,
                metadata={**run_context_metadata(agent_id=record['id'], agent_name=record['name'], deployment_id=final_ctx.get('deployment_id',''), deployment_target=final_ctx.get('deployment_target_snapshot',''), deployment_type=final_ctx.get('deployment_type_snapshot','')), 'status': record['status'], 'linked_playbooks': len(record.get('linked_playbook_ids') or []), 'allowed_tools': len(record.get('allowed_tools') or [])},
                title=trim_run_text(f"Update agent: {record['name']}", 140),
                **final_ctx,
            )
            conn.commit()
        except Exception as exc:
            complete_run_record(
                conn,
                run["id"],
                "failed",
                summary="Agent update failed.",
                run_detail="Agent changes were not committed. Review the validation error.",
                result_label="Failed",
                error_message=str(exc),
                log_preview=trim_run_text(str(exc) or "Agent update failed.", 420),
                trigger_label="Manual registry action",
                title=base_title,
                **initial_ctx,
            )
            conn.commit()
            raise
    return agent_get(agent_id=agent_id)


def agent_delete(agent_id: str) -> dict:
    if not agent_id:
        raise ValueError("id is required")
    with connect_board() as conn:
        existing = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if existing is None:
            raise KeyError("agent not found")
        existing_row = normalize_agent_row(existing)
        initial_ctx = run_context_for_agent(conn, agent_id=agent_id, agent=existing_row)
        base_title = trim_run_text(f"Delete agent: {existing_row.get('name') or 'Untitled agent'}", 140)
        run = create_run_record(
            conn,
            run_type="agent_execution",
            title=base_title,
            status="queued",
            summary="Agent delete request queued.",
            run_detail="Agent queued for registry removal.",
            result_label="Queued",
            trigger_label="Manual registry action",
            log_preview="Preparing agent removal.",
            run_source="user",
            run_purpose="agent_lifecycle",
            **initial_ctx,
        )
        mark_run_running(conn, run["id"], summary="Deleting agent record.", run_detail="Removing linked deployment rows and agent registry entry.", result_label="Running", trigger_label="Manual registry action", log_preview="Removing linked deployment and agent registry row.")
        try:
            deployment_count = conn.execute("SELECT COUNT(*) FROM deployments WHERE agent_id = ?", (agent_id,)).fetchone()[0]
            conn.execute("DELETE FROM deployments WHERE agent_id = ?", (agent_id,))
            cur = conn.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
            complete_run_record(
                conn,
                run["id"],
                "success",
                summary=f"Agent \"{existing_row.get('name') or 'Untitled agent'}\" removed from the registry.",
                run_detail=f"Deleted the agent and removed {deployment_count} linked deployment mapping(s).",
                result_label="Deleted",
                log_preview=f"Deleted {existing_row.get('name') or 'Untitled agent'} and cleared any mapped deployment.",
                trigger_label="Manual registry action",
                changed_fields=['Deleted', 'Deployments'],
                metadata={**run_context_metadata(agent_id=agent_id, agent_name=existing_row.get('name',''), deployment_id=initial_ctx.get('deployment_id',''), deployment_target=initial_ctx.get('deployment_target_snapshot',''), deployment_type=initial_ctx.get('deployment_type_snapshot','')), 'linked_deployments_removed': deployment_count},
                title=base_title,
                **initial_ctx,
            )
            conn.commit()
        except Exception as exc:
            complete_run_record(
                conn,
                run["id"],
                "failed",
                summary="Agent delete failed.",
                run_detail="Agent registry row was not removed. Review the error before retrying.",
                result_label="Failed",
                error_message=str(exc),
                log_preview=trim_run_text(str(exc) or "Agent delete failed.", 420),
                trigger_label="Manual registry action",
                title=base_title,
                **initial_ctx,
            )
            conn.commit()
            raise
    if cur.rowcount == 0:
        raise KeyError("agent not found")
    return {"deleted": cur.rowcount, "id": agent_id}


def normalize_deployment_type(value) -> str:
    clean = str(value or "hermes_profile").strip().lower()
    if clean not in DEPLOYMENT_TYPES:
        raise ValueError(f"deployment_type must be one of: {', '.join(DEPLOYMENT_TYPES)}")
    return clean


def normalize_trigger_mode(value) -> str:
    clean = str(value or "manual").strip().lower()
    if clean not in DEPLOYMENT_TRIGGER_MODES:
        raise ValueError(f"trigger_mode must be one of: {', '.join(DEPLOYMENT_TRIGGER_MODES)}")
    return clean


def normalize_deployment_status(value) -> str:
    clean = str(value or "draft").strip().lower()
    if clean not in DEPLOYMENT_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(DEPLOYMENT_STATUSES)}")
    return clean


def normalize_deployment_row(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    for key in DEPLOYMENT_TEXT_FIELDS:
        item[key] = str(item.get(key) or "")
    return item


DEPLOYMENT_SELECT = """
SELECT
  d.*,
  COALESCE(a.name, '') AS agent_name,
  COALESCE(a.status, '') AS agent_status,
  COALESCE(p.name, '') AS playbook_name
FROM deployments d
LEFT JOIN agents a ON a.id = d.agent_id
LEFT JOIN playbooks p ON p.id = json_extract(a.linked_playbook_ids, '$[0]')
"""


def deployment_for_agent(conn: sqlite3.Connection, agent_id: str) -> dict | None:
    if not agent_id:
        return None
    row = conn.execute(DEPLOYMENT_SELECT + " WHERE d.agent_id = ?", (agent_id,)).fetchone()
    return normalize_deployment_row(row)


def augment_agent_with_deployment(agent: dict | None, conn: sqlite3.Connection) -> dict | None:
    if agent is None:
        return None
    deployment = deployment_for_agent(conn, agent.get("id", ""))
    agent["deployment"] = deployment
    if deployment:
        agent["deployment_status"] = deployment.get("status") or agent.get("deployment_status") or "not_deployed"
        agent["deployment_type"] = deployment.get("deployment_type", "")
        agent["deployment_target"] = deployment.get("target", "")
        agent["deployment_trigger_mode"] = deployment.get("trigger_mode", "")
        agent["deployment_last_checked_at"] = deployment.get("last_checked_at", "")
    else:
        agent["deployment_status"] = "not_deployed"
        agent["deployment_type"] = ""
        agent["deployment_target"] = ""
        agent["deployment_trigger_mode"] = ""
        agent["deployment_last_checked_at"] = ""
    return agent


def deployment_record_from_payload(payload: dict, conn: sqlite3.Connection, existing: dict | None = None) -> dict:
    source = dict(existing or {})
    agent_id = str(payload.get("agent_id", source.get("agent_id", "")) or "").strip()
    if not agent_id:
        raise ValueError("agent_id is required")
    if not task_exists(conn, "agents", agent_id):
        raise ValueError("agent_id does not match an existing agent")
    if not source.get("id"):
        row = conn.execute("SELECT id FROM deployments WHERE agent_id = ?", (agent_id,)).fetchone()
        if row is not None:
            raise ValueError("this agent already has a deployment; use update instead")
    deployment_type = normalize_deployment_type(payload.get("deployment_type", source.get("deployment_type", "hermes_profile")))
    trigger_mode = normalize_trigger_mode(payload.get("trigger_mode", source.get("trigger_mode", "manual")))
    status = normalize_deployment_status(payload.get("status", source.get("status", "draft")))
    target = str(payload.get("target", source.get("target", "")) or "").strip()
    if not target:
        raise ValueError("target is required")
    now = utc_now()
    return {
        "id": source.get("id") or uuid.uuid4().hex,
        "agent_id": agent_id,
        "deployment_type": deployment_type,
        "target": target,
        "trigger_mode": trigger_mode,
        "status": status,
        "notes": str(payload.get("notes", source.get("notes", "")) or "").strip(),
        "last_checked_at": str(payload.get("last_checked_at", source.get("last_checked_at", "")) or "").strip(),
        "created_at": source.get("created_at") or now,
        "updated_at": now,
    }


def sync_agent_deployment_status(conn: sqlite3.Connection, agent_id: str, deployment_status: str):
    mapped = deployment_status if deployment_status in {"draft", "ready", "inactive"} else "not_deployed"
    conn.execute(
        "UPDATE agents SET deployment_status = ?, updated_at = COALESCE(updated_at, ?) WHERE id = ?",
        (mapped, utc_now(), agent_id),
    )


def deployment_list() -> list[dict]:
    with connect_board() as conn:
        rows = conn.execute(
            DEPLOYMENT_SELECT + " ORDER BY CASE d.status WHEN 'ready' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END, d.updated_at DESC, d.created_at DESC"
        ).fetchall()
        return [normalize_deployment_row(row) for row in rows]


def deployment_get(deployment_id: str):
    if not deployment_id:
        raise ValueError("id is required")
    with connect_board() as conn:
        row = conn.execute(DEPLOYMENT_SELECT + " WHERE d.id = ?", (deployment_id,)).fetchone()
        if row is None:
            raise KeyError("deployment not found")
        return {"deployment": normalize_deployment_row(row)}


def deployment_create(payload: dict):
    with connect_board() as conn:
        base_target = str((payload or {}).get("target") or "pending target").strip() or "pending target"
        base_title = trim_run_text(f"Create deployment: {base_target}", 140)
        initial_ctx = run_context_for_deployment(conn, deployment=dict(payload or {}))
        run = create_run_record(
            conn,
            run_type="deployment",
            title=base_title,
            status="queued",
            summary="Deployment create request queued.",
            run_detail="Deployment mapping queued for validation and save.",
            result_label="Queued",
            trigger_label="Manual deployment action",
            log_preview="Validating deployment payload.",
            run_source="user",
            run_purpose="deployment_lifecycle",
            **initial_ctx,
        )
        mark_run_running(conn, run["id"], summary="Creating deployment mapping.", run_detail="Writing deployment mapping and syncing agent deployment state.", result_label="Running", trigger_label="Manual deployment action", log_preview="Validated deployment payload. Writing mapping.")
        try:
            item = deployment_record_from_payload(payload, conn)
            conn.execute(
                """
                INSERT INTO deployments (
                  id, agent_id, deployment_type, target, trigger_mode, status, notes, last_checked_at, created_at, updated_at
                ) VALUES (
                  :id, :agent_id, :deployment_type, :target, :trigger_mode, :status, :notes, :last_checked_at, :created_at, :updated_at
                )
                """,
                item,
            )
            sync_agent_deployment_status(conn, item["agent_id"], item["status"])
            row = conn.execute(DEPLOYMENT_SELECT + " WHERE d.id = ?", (item["id"],)).fetchone()
            record = normalize_deployment_row(row)
            final_ctx = run_context_for_deployment(conn, deployment_id=record["id"], deployment=record)
            complete_run_record(
                conn,
                run["id"],
                "success",
                summary=f"Deployment for \"{record['agent_name'] or 'agent'}\" created with status {record['status']}.",
                run_detail=f"Mapped {record['target']} via {record['deployment_type']} using {record['trigger_mode']} trigger mode.",
                result_label="Created",
                log_preview=f"Mapped {record['agent_name'] or 'agent'} to {record['target']} via {record['deployment_type']}.",
                trigger_label="Manual deployment action",
                changed_fields=['Target', 'Type', 'Trigger Mode', 'Status'],
                metadata={**run_context_metadata(agent_id=record.get('agent_id',''), agent_name=record.get('agent_name',''), deployment_id=record['id'], deployment_target=record['target'], deployment_type=record['deployment_type']), 'status': record['status'], 'trigger_mode': record['trigger_mode']},
                title=trim_run_text(f"Create deployment: {record['target']}", 140),
                **final_ctx,
            )
            conn.commit()
            return record
        except Exception as exc:
            complete_run_record(
                conn,
                run["id"],
                "failed",
                summary="Deployment create failed.",
                run_detail="Deployment mapping was not created. Review the validation error.",
                result_label="Failed",
                error_message=str(exc),
                log_preview=trim_run_text(str(exc) or "Deployment create failed.", 420),
                trigger_label="Manual deployment action",
                title=base_title,
                **initial_ctx,
            )
            conn.commit()
            raise


def deployment_update(deployment_id: str, payload: dict):
    if not deployment_id:
        raise ValueError("id is required")
    with connect_board() as conn:
        existing = conn.execute("SELECT * FROM deployments WHERE id = ?", (deployment_id,)).fetchone()
        if existing is None:
            raise KeyError("deployment not found")
        existing_row = normalize_deployment_row(existing)
        base_title = trim_run_text(f"Update deployment: {existing_row.get('target') or 'pending target'}", 140)
        initial_ctx = run_context_for_deployment(conn, deployment_id=deployment_id, deployment=existing_row)
        run = create_run_record(
            conn,
            run_type="deployment",
            title=base_title,
            status="queued",
            summary="Deployment update request queued.",
            run_detail="Current deployment snapshot loaded and queued for changes.",
            result_label="Queued",
            trigger_label="Manual deployment action",
            log_preview="Loading current deployment mapping.",
            run_source="user",
            run_purpose="deployment_lifecycle",
            **initial_ctx,
        )
        mark_run_running(conn, run["id"], summary="Applying deployment changes.", run_detail="Writing updated deployment mapping and syncing related agent state.", result_label="Running", trigger_label="Manual deployment action", log_preview="Current deployment loaded. Writing updated mapping.")
        try:
            item = deployment_record_from_payload(payload, conn, existing_row)
            if item["agent_id"] != existing["agent_id"]:
                row = conn.execute("SELECT id FROM deployments WHERE agent_id = ? AND id != ?", (item["agent_id"], deployment_id)).fetchone()
                if row is not None:
                    raise ValueError("this agent already has a deployment; use the existing record instead")
            conn.execute(
                """
                UPDATE deployments
                SET agent_id = :agent_id,
                    deployment_type = :deployment_type,
                    target = :target,
                    trigger_mode = :trigger_mode,
                    status = :status,
                    notes = :notes,
                    last_checked_at = :last_checked_at,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                item,
            )
            if item["agent_id"] != existing["agent_id"]:
                sync_agent_deployment_status(conn, str(existing["agent_id"] or ""), "not_deployed")
            sync_agent_deployment_status(conn, item["agent_id"], item["status"])
            row = conn.execute(DEPLOYMENT_SELECT + " WHERE d.id = ?", (deployment_id,)).fetchone()
            record = normalize_deployment_row(row)
            final_ctx = run_context_for_deployment(conn, deployment_id=record["id"], deployment=record)
            changed_fields = run_changed_fields_for_keys(existing_row, record, [('agent_id', 'Agent'), ('deployment_type', 'Type'), ('target', 'Target'), ('trigger_mode', 'Trigger Mode'), ('status', 'Status'), ('notes', 'Notes'), ('last_checked_at', 'Last Checked')])
            complete_run_record(
                conn,
                run["id"],
                "success",
                summary=f"Deployment \"{record['target']}\" updated with status {record['status']}.",
                run_detail=f"Changed {', '.join(changed_fields) if changed_fields else 'deployment metadata'}; trigger mode is {record['trigger_mode']} and type is {record['deployment_type']}.",
                result_label="Updated",
                log_preview=f"Saved {record['target']} · trigger {record['trigger_mode']} · type {record['deployment_type']}.",
                trigger_label="Manual deployment action",
                changed_fields=changed_fields,
                metadata={**run_context_metadata(agent_id=record.get('agent_id',''), agent_name=record.get('agent_name',''), deployment_id=record['id'], deployment_target=record['target'], deployment_type=record['deployment_type']), 'status': record['status'], 'trigger_mode': record['trigger_mode']},
                title=trim_run_text(f"Update deployment: {record['target']}", 140),
                **final_ctx,
            )
            conn.commit()
            return record
        except Exception as exc:
            complete_run_record(
                conn,
                run["id"],
                "failed",
                summary="Deployment update failed.",
                run_detail="Deployment changes were not committed. Review the validation error.",
                result_label="Failed",
                error_message=str(exc),
                log_preview=trim_run_text(str(exc) or "Deployment update failed.", 420),
                trigger_label="Manual deployment action",
                title=base_title,
                **initial_ctx,
            )
            conn.commit()
            raise


def deployment_delete(deployment_id: str):
    if not deployment_id:
        raise ValueError("id is required")
    with connect_board() as conn:
        existing = conn.execute("SELECT * FROM deployments WHERE id = ?", (deployment_id,)).fetchone()
        if existing is None:
            raise KeyError("deployment not found")
        existing_row = normalize_deployment_row(existing)
        base_title = trim_run_text(f"Delete deployment: {existing_row.get('target') or 'pending target'}", 140)
        initial_ctx = run_context_for_deployment(conn, deployment_id=deployment_id, deployment=existing_row)
        run = create_run_record(
            conn,
            run_type="deployment",
            title=base_title,
            status="queued",
            summary="Deployment delete request queued.",
            run_detail="Deployment mapping queued for removal.",
            result_label="Queued",
            trigger_label="Manual deployment action",
            log_preview="Preparing deployment removal.",
            run_source="user",
            run_purpose="deployment_lifecycle",
            **initial_ctx,
        )
        mark_run_running(conn, run["id"], summary="Deleting deployment mapping.", run_detail="Removing deployment row and resetting the linked agent deployment state.", result_label="Running", trigger_label="Manual deployment action", log_preview="Removing deployment row and resetting agent deployment state.")
        try:
            cur = conn.execute("DELETE FROM deployments WHERE id = ?", (deployment_id,))
            sync_agent_deployment_status(conn, str(existing["agent_id"] or ""), "not_deployed")
            complete_run_record(
                conn,
                run["id"],
                "success",
                summary=f"Deployment mapping \"{existing_row.get('target') or 'pending target'}\" removed.",
                run_detail="Removed the deployment row and reset the linked agent deployment state to not deployed.",
                result_label="Deleted",
                log_preview=f"Deleted deployment target {existing_row.get('target') or 'pending target'}.",
                trigger_label="Manual deployment action",
                changed_fields=['Deleted', 'Agent Deployment State'],
                metadata={**run_context_metadata(agent_id=existing_row.get('agent_id',''), agent_name=existing_row.get('agent_name',''), deployment_id=deployment_id, deployment_target=existing_row.get('target',''), deployment_type=existing_row.get('deployment_type','')), 'status_after': 'not_deployed'},
                title=base_title,
                **initial_ctx,
            )
            conn.commit()
            return {"deleted": cur.rowcount, "id": deployment_id}
        except Exception as exc:
            complete_run_record(
                conn,
                run["id"],
                "failed",
                summary="Deployment delete failed.",
                run_detail="Deployment mapping was not removed. Review the error before retrying.",
                result_label="Failed",
                error_message=str(exc),
                log_preview=trim_run_text(str(exc) or "Deployment delete failed.", 420),
                trigger_label="Manual deployment action",
                title=base_title,
                **initial_ctx,
            )
            conn.commit()
            raise


def normalize_run_type(value) -> str:
    clean = str(value or "task_run").strip().lower()
    if clean not in RUN_TYPES:
        raise ValueError(f"type must be one of: {', '.join(RUN_TYPES)}")
    return clean


def normalize_run_status(value) -> str:
    raw = str(value or "queued").strip().lower()
    clean = RUN_STATUS_ALIASES.get(raw, raw)
    if clean not in RUN_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(RUN_STATUSES)}")
    return clean


def display_run_status(value) -> str:
    status = normalize_run_status(value)
    return 'completed' if status == 'success' else status


def normalize_run_origin(value) -> str:
    clean = str(value or "live").strip().lower()
    if clean not in RUN_ORIGINS:
        clean = "live"
    return clean


def normalize_run_source(value) -> str:
    clean = str(value or "").strip().lower()
    if not clean:
        return ""
    clean = RUN_SOURCE_ALIASES.get(clean, clean)
    return clean if clean in RUN_SOURCES else ""


def normalize_run_purpose(value) -> str:
    clean = str(value or "").strip().lower()
    if not clean:
        return ""
    clean = RUN_PURPOSE_ALIASES.get(clean, clean)
    return clean if clean in RUN_PURPOSES else ""


def run_semantics_from_row(row) -> tuple[str, str]:
    item = dict(row or {})
    source = normalize_run_source(item.get('run_source'))
    purpose = normalize_run_purpose(item.get('run_purpose'))
    if source and purpose:
        return source, purpose
    title = str(item.get('title') or '').strip()
    title_lower = title.lower()
    hay = ' '.join([
        title,
        str(item.get('target') or ''),
        str(item.get('summary') or ''),
        str(item.get('log_preview') or ''),
        str(item.get('agent_name_snapshot') or ''),
        str(item.get('linked_task_title_snapshot') or ''),
        str(item.get('deployment_target_snapshot') or ''),
    ]).lower()
    origin = normalize_run_origin(item.get('origin') or 'live')
    if origin == 'seed' or title in RUN_SEED_TITLES:
        return source or 'system', purpose or 'test'
    if any(re.search(pattern, hay) for pattern in RUN_TEST_PATTERNS):
        return source or 'verification', purpose or 'smoke_test'
    if title_lower.startswith(('create task:', 'update task:', 'delete task:')):
        return source or 'user', purpose or 'diagnostic'
    if title_lower.startswith(('create deployment:', 'update deployment:', 'delete deployment:')):
        return source or 'deployment', purpose or 'diagnostic'
    if title_lower.startswith(('create agent:', 'update agent:', 'delete agent:')):
        return source or 'user', purpose or 'diagnostic'
    if str(item.get('linked_task_id') or '').strip():
        return source or 'task', purpose or 'execution'
    if str(item.get('deployment_id') or '').strip():
        return source or 'deployment', purpose or 'execution'
    if normalize_run_type(item.get('type') or 'task_run') == 'evaluation':
        return source or 'runtime', purpose or 'execution'
    if normalize_run_type(item.get('type') or 'task_run') == 'agent_execution':
        return source or 'runtime', purpose or 'execution'
    return source or 'unknown', purpose or 'unknown'


RUN_SOURCE_PRESENTATION = {
    'user': {
        'source_label': 'User',
        'source_badge': 'User',
        'kind_label': 'User Activity',
        'kind_badge': 'User',
        'semantic_tone': 'user',
        'importance_level': 'normal',
    },
    'system': {
        'source_label': 'System',
        'source_badge': 'System',
        'kind_label': 'System Activity',
        'kind_badge': 'System',
        'semantic_tone': 'system',
        'importance_level': 'normal',
    },
    'verification': {
        'source_label': 'Verification',
        'source_badge': 'Verify',
        'kind_label': 'Verification Activity',
        'kind_badge': 'Verify',
        'semantic_tone': 'verification',
        'importance_level': 'low',
    },
    'runtime': {
        'source_label': 'Runtime',
        'source_badge': 'Runtime',
        'kind_label': 'Runtime Activity',
        'kind_badge': 'Runtime',
        'semantic_tone': 'runtime',
        'importance_level': 'medium',
    },
    'deployment': {
        'source_label': 'Deployment',
        'source_badge': 'Deploy',
        'kind_label': 'Deployment Activity',
        'kind_badge': 'Deploy',
        'semantic_tone': 'deployment',
        'importance_level': 'normal',
    },
    'task': {
        'source_label': 'Task',
        'source_badge': 'Task',
        'kind_label': 'Task Activity',
        'kind_badge': 'Task',
        'semantic_tone': 'task',
        'importance_level': 'medium',
    },
    'unknown': {
        'source_label': 'Unknown',
        'source_badge': 'Unknown',
        'kind_label': 'Operational Activity',
        'kind_badge': 'Ops',
        'semantic_tone': 'system',
        'importance_level': 'normal',
    },
}

RUN_PURPOSE_PRESENTATION = {
    'execution': {
        'purpose_label': 'Execution',
        'purpose_badge': 'Exec',
    },
    'test': {
        'purpose_label': 'Test',
        'purpose_badge': 'Test',
    },
    'smoke_test': {
        'purpose_label': 'Smoke Test',
        'purpose_badge': 'Smoke',
    },
    'cleanup': {
        'purpose_label': 'Cleanup',
        'purpose_badge': 'Cleanup',
    },
    'verification': {
        'purpose_label': 'Verification',
        'purpose_badge': 'Verify',
    },
    'retry': {
        'purpose_label': 'Retry',
        'purpose_badge': 'Retry',
    },
    'diagnostic': {
        'purpose_label': 'Diagnostic',
        'purpose_badge': 'Diag',
    },
    'unknown': {
        'purpose_label': 'Unknown',
        'purpose_badge': 'Unknown',
    },
}


def readable_run_semantic_label(value: str) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    return humanize_run_field_name(text)


def derive_run_importance_level(row: dict | None, source: str, purpose: str) -> str:
    item = dict(row or {})
    status = display_run_status(item.get('status') or '')
    if status == 'failed':
        return 'high'
    if source == 'system' and purpose == 'test':
        return 'low'
    if source == 'verification' or purpose in {'smoke_test', 'verification', 'test'}:
        return 'low'
    if source in {'runtime', 'task'} or purpose == 'execution':
        return 'medium'
    return 'normal'


def build_run_semantic_presentation(row: dict | None, *, raw_source: str = '', raw_purpose: str = '') -> dict:
    item = dict(row or {})
    source, purpose = run_semantics_from_row(item)
    raw_source_value = str(raw_source or item.get('run_source') or '').strip().lower()
    raw_purpose_value = str(raw_purpose or item.get('run_purpose') or '').strip().lower()
    source_meta = RUN_SOURCE_PRESENTATION.get(source, {})
    purpose_meta = RUN_PURPOSE_PRESENTATION.get(purpose, {})
    source_label = source_meta.get('source_label') or readable_run_semantic_label(source or raw_source_value) or 'Unknown Source'
    purpose_label = purpose_meta.get('purpose_label') or readable_run_semantic_label(purpose or raw_purpose_value) or 'General Activity'
    tone = source_meta.get('semantic_tone') or 'system'
    importance_level = derive_run_importance_level(item, source, purpose)
    status = display_run_status(item.get('status') or '')
    if status == 'failed':
        tone = 'failure'
    kind_label = source_meta.get('kind_label') or ('Execution Activity' if purpose == 'execution' else 'Operational Activity')
    kind_badge = source_meta.get('kind_badge') or ('Exec' if purpose == 'execution' else 'Ops')
    return {
        'source_label': source_label,
        'source_badge': source_meta.get('source_badge') or readable_run_semantic_label(source or raw_source_value) or 'Unknown',
        'purpose_label': purpose_label,
        'purpose_badge': purpose_meta.get('purpose_badge') or readable_run_semantic_label(purpose or raw_purpose_value) or 'General',
        'kind_label': kind_label,
        'kind_badge': kind_badge,
        'semantic_tone': tone,
        'importance_level': importance_level,
        'is_failure': status == 'failed',
    }


def is_demo_run_row(row) -> bool:
    source, purpose = run_semantics_from_row(row)
    if source == 'system' or purpose == 'test':
        return True
    return normalize_run_origin(dict(row or {}).get('origin') or 'live') == 'seed'


def is_verification_run_row(row) -> bool:
    item = dict(row or {})
    explicit_source = normalize_run_source(item.get('run_source'))
    explicit_purpose = normalize_run_purpose(item.get('run_purpose'))
    if explicit_source or explicit_purpose:
        return explicit_source == 'verification' or explicit_purpose in {'smoke_test', 'verification'}
    source, purpose = run_semantics_from_row(item)
    if source == 'verification' or purpose in {'smoke_test', 'verification'}:
        return True
    if normalize_run_origin(item.get('origin') or 'live') != 'live':
        return False
    hay = ' '.join([
        str(item.get('title') or ''),
        str(item.get('target') or ''),
        str(item.get('summary') or ''),
        str(item.get('log_preview') or ''),
        str(item.get('agent_name_snapshot') or ''),
        str(item.get('linked_task_title_snapshot') or ''),
        str(item.get('deployment_target_snapshot') or ''),
    ]).lower()
    return any(re.search(pattern, hay) for pattern in RUN_TEST_PATTERNS)


def backfill_run_semantics(conn: sqlite3.Connection):
    rows = conn.execute("SELECT * FROM runs").fetchall()
    for row in rows:
        current = dict(row)
        source = normalize_run_source(current.get('run_source'))
        purpose = normalize_run_purpose(current.get('run_purpose'))
        inferred_source, inferred_purpose = run_semantics_from_row(current)
        if source == inferred_source and purpose == inferred_purpose:
            continue
        conn.execute(
            "UPDATE runs SET run_source = ?, run_purpose = ? WHERE id = ?",
            (
                source or inferred_source,
                purpose or inferred_purpose,
                str(current.get('id') or ''),
            ),
        )


def trim_run_text(value, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def sanitize_changed_fields(value) -> list[str]:
    cleaned = []
    seen = set()
    for item in parse_json_list(value):
        label = trim_run_text(item, 48)
        key = label.lower()
        if not label or key in seen:
            continue
        seen.add(key)
        cleaned.append(label)
    return cleaned


def sanitize_run_metadata(value) -> dict:
    cleaned = {}
    for key, raw in decode_json_object(value).items():
        label = trim_run_text(key, 48)
        if not label:
            continue
        if raw is None:
            continue
        if isinstance(raw, (list, tuple, set)):
            values = [trim_run_text(item, 80) for item in raw if trim_run_text(item, 80)]
            if values:
                cleaned[label] = values
            continue
        if isinstance(raw, dict):
            nested = {trim_run_text(k, 48): trim_run_text(v, 80) for k, v in raw.items() if trim_run_text(k, 48) and trim_run_text(v, 80)}
            if nested:
                cleaned[label] = nested
            continue
        text = trim_run_text(raw, 160)
        if text:
            cleaned[label] = text
    return cleaned


def sanitize_run_payload_value(value, *, depth: int = 0):
    if depth > 2:
        return trim_run_text(value, 140)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return trim_run_text(value, 220)
    if isinstance(value, dict):
        cleaned = {}
        for key, raw in list(value.items())[:12]:
            label = trim_run_text(key, 40)
            if not label:
                continue
            clean = sanitize_run_payload_value(raw, depth=depth + 1)
            if clean is not None and clean != '' and clean != [] and clean != {}:
                cleaned[label] = clean
        return cleaned
    if isinstance(value, (list, tuple, set)):
        cleaned = []
        for item in list(value)[:8]:
            clean = sanitize_run_payload_value(item, depth=depth + 1)
            if clean is not None and clean != '' and clean != [] and clean != {}:
                cleaned.append(clean)
        return cleaned
    return trim_run_text(value, 220)


def sanitize_run_result_payload(value) -> dict:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                value = json.loads(stripped)
            except Exception:
                value = {'snippet': stripped}
    if not isinstance(value, dict):
        return {}
    cleaned = sanitize_run_payload_value(value)
    return cleaned if isinstance(cleaned, dict) else {}


def sanitize_run_artifact_manifest(value) -> list[dict]:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            try:
                value = json.loads(stripped)
            except Exception:
                value = [{'label': stripped}]
    if not isinstance(value, list):
        return []
    cleaned = []
    for raw in list(value)[:8]:
        item = raw if isinstance(raw, dict) else {'label': str(raw or '').strip()}
        label = trim_run_text(item.get('label') or item.get('name') or item.get('title') or '', 80)
        artifact_type = trim_run_text(item.get('type') or item.get('kind') or 'artifact', 32)
        path = trim_run_text(item.get('path') or item.get('url') or '', 180)
        preview = trim_run_text(item.get('preview') or item.get('snippet') or item.get('summary') or '', 220)
        status = trim_run_text(item.get('status') or '', 32)
        size = item.get('size')
        clean = {'label': label or 'Artifact', 'type': artifact_type or 'artifact'}
        if path:
            clean['path'] = path
        if preview:
            clean['preview'] = preview
        if status:
            clean['status'] = status
        if isinstance(size, (int, float)) and size >= 0:
            clean['size'] = int(size)
        metadata = sanitize_run_result_payload(item.get('metadata') or {})
        if metadata:
            clean['metadata'] = metadata
        cleaned.append(clean)
    return cleaned


def normalize_run_output_status(value) -> str:
    clean = str(value or '').strip().lower()
    if not clean:
        return ''
    if clean not in RUN_OUTPUT_STATUSES:
        raise ValueError(f"output status must be one of: {', '.join(RUN_OUTPUT_STATUSES)}")
    return clean


def normalize_trace_event_type(value) -> str:
    clean = str(value or 'step').strip().lower()
    return clean if clean in RUN_TRACE_EVENT_TYPES else 'step'


def normalize_trace_event_status(value) -> str:
    clean = str(value or 'pending').strip().lower()
    if clean not in RUN_TRACE_STATUSES:
        raise ValueError(f"trace status must be one of: {', '.join(RUN_TRACE_STATUSES)}")
    return clean


def next_trace_step_index(conn: sqlite3.Connection, run_id: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(step_index), 0) + 1 AS next_step FROM run_trace_events WHERE run_id = ?", (run_id,)).fetchone()
    return int((row['next_step'] if row is not None else 1) or 1)


def normalize_run_trace_row(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    return {
        'id': str(item.get('id') or ''),
        'run_id': str(item.get('run_id') or ''),
        'event_type': normalize_trace_event_type(item.get('event_type') or 'step'),
        'event_label': str(item.get('event_label') or ''),
        'event_detail': str(item.get('event_detail') or ''),
        'event_status': normalize_trace_event_status(item.get('event_status') or 'pending'),
        'step_index': max(1, int(item.get('step_index') or 1)),
        'created_at': str(item.get('created_at') or ''),
        'metadata': sanitize_run_metadata(item.get('metadata_json')),
    }


def list_run_trace_events(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM run_trace_events WHERE run_id = ? ORDER BY step_index ASC, created_at ASC, id ASC",
        (run_id,),
    ).fetchall()
    return [normalize_run_trace_row(row) for row in rows if row is not None]


def append_trace_event(conn: sqlite3.Connection, run_id: str, *, event_type: str = 'step', event_label: str = '', event_detail: str = '', event_status: str = 'pending', step_index: int | None = None, metadata=None) -> dict:
    if not run_id:
        raise ValueError('run id is required')
    exists = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
    if exists is None:
        raise KeyError('run not found')
    resolved_step = max(1, int(step_index)) if step_index is not None else next_trace_step_index(conn, run_id)
    item = {
        'id': uuid.uuid4().hex,
        'run_id': str(run_id),
        'event_type': normalize_trace_event_type(event_type),
        'event_label': trim_run_text(event_label or humanize_run_field_name(event_type or 'step') or 'Execution step', 80),
        'event_detail': trim_run_text(event_detail, 220),
        'event_status': normalize_trace_event_status(event_status),
        'step_index': resolved_step,
        'created_at': utc_now(),
        'metadata_json': json.dumps(sanitize_run_metadata(metadata), ensure_ascii=False),
    }
    conn.execute(
        """
        INSERT INTO run_trace_events (
          id, run_id, event_type, event_label, event_detail, event_status, step_index, created_at, metadata_json
        ) VALUES (
          :id, :run_id, :event_type, :event_label, :event_detail, :event_status, :step_index, :created_at, :metadata_json
        )
        """,
        item,
    )
    return normalize_run_trace_row(item)


def mark_execution_step_status(conn: sqlite3.Connection, event_id: str, *, status: str, detail: str | None = None, metadata=None) -> dict:
    if not event_id:
        raise ValueError('trace event id is required')
    row = conn.execute("SELECT * FROM run_trace_events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise KeyError('trace event not found')
    current = dict(row)
    payload = {
        'id': str(current.get('id') or event_id),
        'event_status': normalize_trace_event_status(status),
        'event_detail': trim_run_text(current.get('event_detail') if detail is None else detail, 220),
        'metadata_json': json.dumps(sanitize_run_metadata(metadata if metadata is not None else current.get('metadata_json') or {}), ensure_ascii=False),
    }
    conn.execute(
        "UPDATE run_trace_events SET event_status = :event_status, event_detail = :event_detail, metadata_json = :metadata_json WHERE id = :id",
        payload,
    )
    updated = conn.execute("SELECT * FROM run_trace_events WHERE id = ?", (event_id,)).fetchone()
    return normalize_run_trace_row(updated)


def create_execution_run(conn: sqlite3.Connection, *, run_type: str = 'agent_execution', title: str, summary: str = '', run_detail: str = '', result_label: str = 'Queued', trigger_label: str = 'Execution trace probe', log_preview: str = '', metadata=None, **kwargs) -> dict:
    run = create_run_record(
        conn,
        run_type=run_type,
        title=title,
        status='queued',
        summary=summary or 'Execution queued.',
        run_detail=run_detail or 'Execution request accepted and queued for trace capture.',
        result_label=result_label,
        trigger_label=trigger_label,
        log_preview=log_preview or 'Execution queued for runtime verification.',
        metadata=metadata,
        **kwargs,
    )
    append_trace_event(
        conn,
        run['id'],
        event_type='queued',
        event_label='Execution queued',
        event_detail='Run admitted to the execution queue.',
        event_status='success',
        metadata=metadata,
    )
    return run


def finalize_execution_run(conn: sqlite3.Connection, run_id: str, *, status: str, summary: str = '', run_detail: str = '', result_label: str = '', error_message: str = '', log_preview: str = '', final_event_label: str = '', final_event_detail: str = '', metadata=None, **changes) -> dict:
    final_status = normalize_run_status(status)
    append_trace_event(
        conn,
        run_id,
        event_type='completed' if final_status == 'success' else 'failed',
        event_label=final_event_label or ('Execution completed' if final_status == 'success' else 'Execution failed'),
        event_detail=final_event_detail or summary,
        event_status='success' if final_status == 'success' else 'failed',
        metadata=metadata,
    )
    return complete_run_record(
        conn,
        run_id,
        final_status,
        summary=summary,
        run_detail=run_detail,
        result_label=result_label,
        error_message=error_message,
        log_preview=log_preview,
        metadata=metadata,
        **changes,
    )


def make_run_error_message(value) -> str:
    return trim_run_text(value, 220)


def humanize_run_field_name(value: str) -> str:
    text = str(value or '').strip().replace('_', ' ').replace('-', ' ')
    return text.title() if text else ''


def run_target_entity_payload(*, entity_type: str = '', entity_id: str = '', entity_name: str = '') -> dict:
    return {
        'target_entity_type': trim_run_text(entity_type, 40),
        'target_entity_id': trim_run_text(entity_id, 80),
        'target_entity_name': trim_run_text(entity_name, 140),
    }


def run_context_metadata(*, task_id: str = '', task_title: str = '', agent_id: str = '', agent_name: str = '', deployment_id: str = '', deployment_target: str = '', deployment_type: str = '') -> dict:
    metadata = {}
    if task_id:
        metadata['linked_task_id'] = task_id
    if task_title:
        metadata['linked_task'] = task_title
    if agent_id:
        metadata['agent_id'] = agent_id
    if agent_name:
        metadata['agent'] = agent_name
    if deployment_id:
        metadata['deployment_id'] = deployment_id
    if deployment_target:
        metadata['deployment_target'] = deployment_target
    if deployment_type:
        metadata['deployment_type'] = deployment_type
    return metadata


def run_changed_fields_for_keys(before: dict | None, after: dict | None, mapping: list[tuple[str, str]]) -> list[str]:
    prev = dict(before or {})
    curr = dict(after or {})
    changed = []
    for key, label in mapping:
        if str(prev.get(key) or '') != str(curr.get(key) or ''):
            changed.append(label)
    return changed


RUN_SELECT = """
SELECT
  r.*,
  COALESCE(a.name, NULLIF(r.assignee_name, ''), NULLIF(r.agent_name_snapshot, ''), '') AS agent_name,
  COALESCE(t.title, NULLIF(r.task_title_snapshot, ''), NULLIF(r.linked_task_title_snapshot, ''), '') AS linked_task_title,
  COALESCE(p.name, NULLIF(r.playbook_name, ''), '') AS linked_playbook_name,
  COALESCE(d.target, NULLIF(r.deployment_target_snapshot, ''), '') AS deployment_target,
  COALESCE(d.deployment_type, NULLIF(r.deployment_type_snapshot, ''), '') AS deployment_type
FROM runs r
LEFT JOIN agents a ON a.id = COALESCE(NULLIF(r.assignee_id, ''), NULLIF(r.agent_id, ''))
LEFT JOIN tasks t ON t.id = r.linked_task_id
LEFT JOIN playbooks p ON p.id = r.playbook_id
LEFT JOIN deployments d ON d.id = r.deployment_id
"""


def normalize_run_row(row) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    raw_source = str(item.get('run_source') or '').strip().lower()
    raw_purpose = str(item.get('run_purpose') or '').strip().lower()
    item['id'] = str(item.get('id') or '')
    item['type'] = normalize_run_type(item.get('type') or 'task_run')
    item['title'] = str(item.get('title') or '')
    item['agent_id'] = str(item.get('agent_id') or '')
    item['agent_name'] = str(item.get('agent_name') or '')
    item['target'] = str(item.get('target') or '')
    item['environment'] = str(item.get('environment') or '')
    item['status'] = normalize_run_status(item.get('status') or 'queued')
    item['display_status'] = display_run_status(item['status'])
    item['started_at'] = str(item.get('started_at') or '')
    item['finished_at'] = str(item.get('finished_at') or '')
    item['summary'] = str(item.get('summary') or '')
    item['run_detail'] = str(item.get('run_detail') or '')
    item['result_label'] = str(item.get('result_label') or '')
    item['result_summary'] = str(item.get('result_summary') or '')
    item['result_payload'] = sanitize_run_result_payload(item.get('result_payload_json'))
    item['artifact_manifest'] = sanitize_run_artifact_manifest(item.get('artifact_manifest_json'))
    if item['artifact_manifest']:
        item['artifact_count'] = len(item['artifact_manifest'])
    else:
        item['artifact_count'] = max(0, int(item.get('artifact_count') or 0))
    item['output_status'] = normalize_run_output_status(item.get('output_status') or '')
    item['error_message'] = str(item.get('error_message') or '')
    item['log_preview'] = str(item.get('log_preview') or '')
    item['target_entity_type'] = str(item.get('target_entity_type') or '')
    item['target_entity_id'] = str(item.get('target_entity_id') or '')
    item['target_entity_name'] = str(item.get('target_entity_name') or '')
    item['trigger_label'] = str(item.get('trigger_label') or '')
    item['changed_fields'] = sanitize_changed_fields(item.get('changed_fields_json'))
    item['metadata'] = sanitize_run_metadata(item.get('metadata_json'))
    item['task_id'] = str(item.get('linked_task_id') or '')
    item['task_title_snapshot'] = str(item.get('task_title_snapshot') or item.get('linked_task_title') or item.get('linked_task_title_snapshot') or '')
    item['assignee_id'] = str(item.get('assignee_id') or item.get('agent_id') or '')
    item['assignee_name'] = str(item.get('agent_name') or item.get('assignee_name') or item.get('agent_name_snapshot') or '')
    item['playbook_id'] = str(item.get('playbook_id') or '')
    item['playbook_name'] = str(item.get('linked_playbook_name') or item.get('playbook_name') or '')
    item['result_text'] = str(item.get('result_text') or item.get('result_summary') or '')
    item['linked_task_id'] = str(item.get('linked_task_id') or '')
    item['linked_task_title'] = str(item.get('linked_task_title') or '')
    item['deployment_id'] = str(item.get('deployment_id') or '')
    item['deployment_target'] = str(item.get('deployment_target') or '')
    item['deployment_type'] = str(item.get('deployment_type') or '')
    item['origin'] = normalize_run_origin(item.get('origin') or 'live')
    run_source, run_purpose = run_semantics_from_row(item)
    item['run_source'] = run_source
    item['run_purpose'] = run_purpose
    item['semantic_display'] = build_run_semantic_presentation(item, raw_source=raw_source, raw_purpose=raw_purpose)
    if not item['result_summary'] and (item['result_payload'] or item['artifact_manifest'] or item['output_status']):
        item['result_summary'] = item['summary'] or item['result_label'] or 'Result available.'
    item['output'] = {
        'status': item['output_status'],
        'summary': item['result_summary'],
        'payload': item['result_payload'],
        'artifact_count': item['artifact_count'],
        'has_output': bool(item['result_summary'] or item['result_payload'] or item['artifact_manifest'] or item['output_status']),
        'has_artifacts': bool(item['artifact_count']),
    }
    item['result'] = {
        'summary': item['result_summary'],
        'text': item['result_text'],
        'payload': item['result_payload'],
        'status': item['output_status'],
    }
    item['artifacts'] = item['artifact_manifest']
    item['created_at'] = str(item.get('created_at') or '')
    item['updated_at'] = str(item.get('updated_at') or '')
    return item


def normalize_context_entity_type(value) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    lowered = raw.lower()
    if lowered == 'task':
        return 'Task'
    if lowered == 'deployment':
        return 'Deployment'
    if lowered == 'agent':
        return 'Agent'
    return raw


def resolve_run_entity_ref(item: dict | None) -> dict:
    row = dict(item or {})
    entity_type = normalize_context_entity_type(row.get('target_entity_type'))
    entity_id = str(row.get('target_entity_id') or '').strip()
    entity_name = str(row.get('target_entity_name') or '').strip()
    linked_task_id = str(row.get('linked_task_id') or '').strip()
    deployment_id = str(row.get('deployment_id') or '').strip()
    agent_id = str(row.get('agent_id') or '').strip()
    if entity_type:
        if entity_id:
            return {'entity_type': entity_type, 'entity_id': entity_id, 'entity_name': entity_name, 'guarded_empty': False}
        return {'entity_type': entity_type, 'entity_id': '', 'entity_name': entity_name, 'guarded_empty': True}
    if linked_task_id:
        return {
            'entity_type': 'Task',
            'entity_id': linked_task_id,
            'entity_name': entity_name or str(row.get('linked_task_title') or row.get('task_title_snapshot') or '').strip(),
            'guarded_empty': False,
        }
    if deployment_id:
        return {
            'entity_type': 'Deployment',
            'entity_id': deployment_id,
            'entity_name': entity_name or str(row.get('deployment_target') or '').strip(),
            'guarded_empty': False,
        }
    if agent_id:
        return {
            'entity_type': 'Agent',
            'entity_id': agent_id,
            'entity_name': entity_name or str(row.get('agent_name') or row.get('assignee_name') or '').strip(),
            'guarded_empty': False,
        }
    return {'entity_type': '', 'entity_id': '', 'entity_name': entity_name, 'guarded_empty': False}


def compact_run_context_item(item: dict | None) -> dict | None:
    row = normalize_run_row(item) if item else None
    if row is None:
        return None
    semantic = row.get('semantic_display') or {}
    return {
        'id': str(row.get('id') or ''),
        'title': str(row.get('task_title_snapshot') or row.get('title') or 'Untitled run'),
        'status': str(row.get('display_status') or row.get('status') or ''),
        'created_at': str(row.get('created_at') or ''),
        'started_at': str(row.get('started_at') or ''),
        'finished_at': str(row.get('finished_at') or ''),
        'updated_at': str(row.get('updated_at') or ''),
        'run_source': str(row.get('run_source') or ''),
        'run_purpose': str(row.get('run_purpose') or ''),
        'semantic_display': semantic,
        'task_id': str(row.get('task_id') or row.get('linked_task_id') or ''),
        'task_title_snapshot': str(row.get('task_title_snapshot') or ''),
        'assignee_name': str(row.get('assignee_name') or ''),
        'target_entity_type': str(row.get('target_entity_type') or ''),
        'target_entity_id': str(row.get('target_entity_id') or ''),
        'target_entity_name': str(row.get('target_entity_name') or ''),
        'summary': str(row.get('summary') or ''),
        'result_text': str(row.get('result_text') or ''),
        'log_preview': str(row.get('log_preview') or ''),
    }


def fetch_related_runs_for_entity(conn: sqlite3.Connection, entity_type: str, entity_id: str) -> list[dict]:
    entity_type = str(entity_type or '').strip()
    entity_id = str(entity_id or '').strip()
    if not entity_type or not entity_id:
        return []
    clauses = ["(r.target_entity_type = ? AND r.target_entity_id = ?)"]
    params: list[str] = [entity_type, entity_id]
    if entity_type == 'Task':
        clauses.append("(COALESCE(r.target_entity_type, '') = '' AND r.linked_task_id = ?)")
        params.append(entity_id)
    elif entity_type == 'Deployment':
        clauses.append("(COALESCE(r.target_entity_type, '') = '' AND r.deployment_id = ?)")
        params.append(entity_id)
    elif entity_type == 'Agent':
        clauses.append("(COALESCE(r.target_entity_type, '') = '' AND r.agent_id = ?)")
        params.append(entity_id)
    rows = conn.execute(
        RUN_SELECT
        + " WHERE " + " OR ".join(clauses)
        + " ORDER BY COALESCE(NULLIF(r.started_at, ''), NULLIF(r.finished_at, ''), NULLIF(r.updated_at, ''), r.created_at) ASC, r.created_at ASC, r.id ASC",
        params,
    ).fetchall()
    return [item for item in (normalize_run_row(row) for row in rows) if item]


def select_same_entity_recent_runs(related_runs: list[dict], anchor_index: int, *, max_recent: int = 3) -> tuple[list[dict], int]:
    if max_recent <= 0:
        return [], 0
    if anchor_index < 0 or anchor_index >= len(related_runs):
        siblings = [item for item in related_runs if item]
        return siblings[-max_recent:], max(0, len(siblings) - min(len(siblings), max_recent))
    excluded_indexes = {anchor_index}
    if anchor_index > 0:
        excluded_indexes.add(anchor_index - 1)
    if anchor_index + 1 < len(related_runs):
        excluded_indexes.add(anchor_index + 1)
    candidate_indexes = [idx for idx in range(len(related_runs)) if idx not in excluded_indexes]
    if not candidate_indexes:
        return [], 0
    ranked_indexes = sorted(candidate_indexes, key=lambda idx: (abs(idx - anchor_index), idx))
    selected_indexes = sorted(ranked_indexes[:max_recent])
    visible = [related_runs[idx] for idx in selected_indexes if related_runs[idx]]
    hidden_count = max(0, len(candidate_indexes) - len(visible))
    return visible, hidden_count


def build_run_context_payload(conn: sqlite3.Connection, run_id: str, *, max_recent: int = 3) -> dict:
    row = conn.execute(RUN_SELECT + " WHERE r.id = ?", (run_id,)).fetchone()
    if row is None:
        raise ResourceNotFoundError('run', run_id)
    run = normalize_run_row(row)
    entity_ref = resolve_run_entity_ref(run)
    entity_type = entity_ref.get('entity_type') or ''
    entity_id = entity_ref.get('entity_id') or ''
    guarded_empty = bool(entity_ref.get('guarded_empty'))
    if guarded_empty:
        related_runs = []
        anchor_index = -1
    else:
        related_runs = fetch_related_runs_for_entity(conn, entity_type, entity_id) if entity_type and entity_id else []
        anchor_index = next((idx for idx, item in enumerate(related_runs) if str(item.get('id') or '') == str(run.get('id') or '')), -1)
    before = related_runs[anchor_index - 1] if anchor_index > 0 else None
    after = related_runs[anchor_index + 1] if anchor_index >= 0 and anchor_index + 1 < len(related_runs) else None
    recent, hidden_count = select_same_entity_recent_runs(related_runs, anchor_index, max_recent=max_recent)
    recent_total = len(recent) + hidden_count
    compact_before = compact_run_context_item(before)
    compact_after = compact_run_context_item(after)
    compact_recent = [item for item in (compact_run_context_item(item) for item in recent) if item]
    return {
        'run_id': str(run.get('id') or run_id),
        'entity': {
            'entity_type': entity_type,
            'entity_id': entity_id,
            'entity_name': str(entity_ref.get('entity_name') or ''),
            'guarded_empty': guarded_empty,
        },
        'before': compact_before,
        'after': compact_after,
        'recent': compact_recent,
        'recent_total': recent_total,
        'recent_shown': len(compact_recent),
        'recent_hidden': hidden_count,
        'empty': not compact_before and not compact_after and not compact_recent,
        'run': run,
        'related': {
            'entity': {
                'entity_type': entity_type,
                'entity_id': entity_id,
                'entity_name': str(entity_ref.get('entity_name') or ''),
                'guarded_empty': guarded_empty,
            },
            'preceding': compact_before,
            'following': compact_after,
            'same_entity_recent': compact_recent,
            'same_entity_recent_total': recent_total,
            'same_entity_recent_shown': len(compact_recent),
            'hidden_count': hidden_count,
        },
    }


def run_context_for_agent(conn: sqlite3.Connection, agent_id: str = "", agent: dict | None = None) -> dict:
    row = dict(agent or {})
    if not row and agent_id:
        fetched = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
        if fetched is not None:
            row = normalize_agent_row(fetched)
    resolved_agent_id = str(row.get("id") or agent_id or "")
    deployment = deployment_for_agent(conn, resolved_agent_id) if resolved_agent_id else None
    return {
        "agent_id": resolved_agent_id,
        "agent_name_snapshot": str(row.get("name") or ""),
        "deployment_id": str((deployment or {}).get("id") or ""),
        "deployment_target_snapshot": str((deployment or {}).get("target") or ""),
        "deployment_type_snapshot": str((deployment or {}).get("deployment_type") or ""),
        "target": str((deployment or {}).get("target") or row.get("name") or ""),
        "environment": "agent_registry",
        **run_target_entity_payload(entity_type="Agent", entity_id=resolved_agent_id, entity_name=str(row.get("name") or "")),
    }


def run_context_for_task(conn: sqlite3.Connection, task_id: str = "", task: dict | None = None) -> dict:
    row = dict(task or {})
    if not row and task_id:
        fetched = conn.execute(TASK_SELECT + " WHERE t.id = ?", (task_id,)).fetchone()
        if fetched is not None:
            row = normalize_task_row(fetched, conn)
    agent_ctx = run_context_for_agent(conn, str(row.get("agent_id") or "")) if row.get("agent_id") else {
        "agent_id": "",
        "agent_name_snapshot": "",
        "deployment_id": "",
        "deployment_target_snapshot": "",
        "deployment_type_snapshot": "",
        "target": "",
        "environment": "kanban",
    }
    return {
        "agent_id": str(agent_ctx.get("agent_id") or ""),
        "agent_name_snapshot": str(agent_ctx.get("agent_name_snapshot") or ""),
        "assignee_id": str(row.get("agent_id") or agent_ctx.get("agent_id") or ""),
        "assignee_name": str(row.get("assigned_agent_name") or agent_ctx.get("agent_name_snapshot") or ""),
        "playbook_id": str(row.get("playbook_id") or ""),
        "playbook_name": str(row.get("linked_playbook_name") or ""),
        "task_title_snapshot": str(row.get("title") or ""),
        "result_text": str(row.get("result_text") or ""),
        "linked_task_id": str(row.get("id") or task_id or ""),
        "linked_task_title_snapshot": str(row.get("title") or ""),
        "deployment_id": str(agent_ctx.get("deployment_id") or ""),
        "deployment_target_snapshot": str(agent_ctx.get("deployment_target_snapshot") or ""),
        "deployment_type_snapshot": str(agent_ctx.get("deployment_type_snapshot") or ""),
        "target": str(agent_ctx.get("target") or row.get("title") or ""),
        "environment": "kanban",
        **run_target_entity_payload(entity_type="Task", entity_id=str(row.get("id") or task_id or ""), entity_name=str(row.get("title") or "")),
    }


def run_context_for_deployment(conn: sqlite3.Connection, deployment_id: str = "", deployment: dict | None = None) -> dict:
    row = dict(deployment or {})
    if not row and deployment_id:
        fetched = conn.execute("SELECT * FROM deployments WHERE id = ?", (deployment_id,)).fetchone()
        if fetched is not None:
            row = normalize_deployment_row(fetched)
    return {
        "agent_id": str(row.get("agent_id") or ""),
        "agent_name_snapshot": str(row.get("agent_name") or ""),
        "deployment_id": str(row.get("id") or deployment_id or ""),
        "deployment_target_snapshot": str(row.get("target") or ""),
        "deployment_type_snapshot": str(row.get("deployment_type") or ""),
        "target": str(row.get("target") or ""),
        "environment": "deployments",
        **run_target_entity_payload(entity_type="Deployment", entity_id=str(row.get("id") or deployment_id or ""), entity_name=str(row.get("target") or "")),
    }


def run_context_for_workspace() -> dict:
    return {
        "agent_id": "",
        "agent_name_snapshot": "",
        "deployment_id": "",
        "deployment_target_snapshot": "",
        "deployment_type_snapshot": "",
        "target": "Operator workspace",
        "environment": "runs_console",
        **run_target_entity_payload(entity_type="Workspace", entity_id="operator-workspace", entity_name="Operator Workspace"),
    }


class RunLaunchRequestError(Exception):
    def __init__(self, message: str, *, status_code: int = 422, code: str = 'invalid_launch', details: dict | None = None):
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = str(code or 'invalid_launch')
        self.details = dict(details or {})


class ResourceNotFoundError(Exception):
    def __init__(self, resource: str, resource_id: str = '', *, message: str = ''):
        self.resource = str(resource or 'resource')
        self.resource_id = str(resource_id or '')
        super().__init__(message or f'{self.resource} not found')


def api_error_payload(message: str, *, code: str, boundary: str, details: dict | None = None) -> dict:
    return {
        'ok': False,
        'error': str(message or 'request failed'),
        'code': str(code or 'bad_request'),
        'boundary': str(boundary or 'request_error'),
        'details': dict(details or {}),
    }


def exception_to_api_error(exc: Exception, *, fallback_boundary: str = 'request_error', fallback_code: str = 'bad_request') -> tuple[int, dict]:
    if isinstance(exc, ResourceNotFoundError):
        return 404, api_error_payload(
            str(exc),
            code='resource_not_found',
            boundary='not_found',
            details={'resource': exc.resource, 'resource_id': exc.resource_id},
        )
    if isinstance(exc, RunLaunchRequestError):
        boundary = 'not_found' if exc.status_code == 404 or exc.code == 'target_not_found' else 'launch_rejected'
        return exc.status_code, api_error_payload(str(exc), code=exc.code, boundary=boundary, details=exc.details)
    if isinstance(exc, json.JSONDecodeError):
        return 400, api_error_payload(
            'request body must be valid JSON',
            code='malformed_json',
            boundary='malformed_request',
            details={'line': exc.lineno, 'column': exc.colno},
        )
    if isinstance(exc, ValueError):
        return 422, api_error_payload(str(exc), code='validation_failed', boundary='validation_failed')
    return 400, api_error_payload(f'{type(exc).__name__}: {exc}', code=fallback_code, boundary=fallback_boundary)


def parse_launch_bool(value, field_name: str) -> bool:
    if value is None or value == '':
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {'true', '1', 'yes', 'on'}:
            return True
        if lowered in {'false', '0', 'no', 'off'}:
            return False
    raise RunLaunchRequestError(
        f'{field_name} must be a boolean',
        status_code=422,
        code='invalid_boolean',
        details={'field': field_name},
    )


def validate_operator_launch_payload(payload: dict | None) -> dict:
    data = dict(payload or {})
    action = str(data.get('action') or 'run_evaluation').strip().lower() or 'run_evaluation'
    if action != 'run_evaluation':
        raise RunLaunchRequestError(
            'action must be run_evaluation',
            status_code=422,
            code='unsupported_action',
            details={'field': 'action', 'allowed': ['run_evaluation']},
        )
    target_type = str(data.get('target_type') or 'workspace').strip().lower() or 'workspace'
    if target_type not in {'workspace', 'agent', 'task', 'deployment'}:
        raise RunLaunchRequestError(
            'target_type must be one of: workspace, agent, task, deployment',
            status_code=422,
            code='unsupported_target_type',
            details={'field': 'target_type', 'allowed': ['workspace', 'agent', 'task', 'deployment']},
        )
    target_id = str(data.get('target_id') or '').strip()
    if target_type == 'workspace' and target_id:
        raise RunLaunchRequestError(
            'target_id must be empty when target_type=workspace',
            status_code=422,
            code='unexpected_target_id',
            details={'field': 'target_id', 'target_type': 'workspace'},
        )
    if target_type != 'workspace' and not target_id:
        raise RunLaunchRequestError(
            f'target_id is required when target_type={target_type}',
            status_code=422,
            code='missing_target_id',
            details={'field': 'target_id', 'target_type': target_type},
        )
    run_mode = str(data.get('run_mode') or 'standard').strip().lower() or 'standard'
    if run_mode not in {'standard', 'failure_check'}:
        raise RunLaunchRequestError(
            'run_mode must be one of: standard, failure_check',
            status_code=422,
            code='unsupported_run_mode',
            details={'field': 'run_mode', 'allowed': ['standard', 'failure_check']},
        )
    execution_intent = trim_run_text(data.get('execution_intent') or '', 180)
    if not execution_intent:
        raise RunLaunchRequestError(
            'execution_intent is required',
            status_code=422,
            code='missing_execution_intent',
            details={'field': 'execution_intent'},
        )
    prompt_text = trim_run_text(data.get('prompt_text') or '', 420)
    test_mode = parse_launch_bool(data.get('test_mode'), 'test_mode')
    return {
        'action': action,
        'target_type': target_type,
        'target_id': target_id,
        'run_mode': run_mode,
        'execution_intent': execution_intent,
        'prompt_text': prompt_text,
        'test_mode': test_mode,
        'requested_failure_check': run_mode == 'failure_check' or test_mode,
    }


def resolve_run_launch_target(conn: sqlite3.Connection, target_type: str = '', target_id: str = '') -> tuple[dict, dict, dict]:
    normalized_type = str(target_type or '').strip().lower() or 'workspace'
    normalized_id = str(target_id or '').strip()
    if normalized_type == 'workspace':
        ctx = run_context_for_workspace()
        record = {
            'id': 'operator-workspace',
            'name': 'Operator Workspace',
            'surface': 'runs_console',
        }
        return ctx, {
            'target_type': 'workspace',
            'target_id': '',
            'target_label': 'Operator Workspace',
            'target_entity_type': 'Workspace',
        }, record
    if normalized_type == 'agent':
        row = conn.execute("SELECT * FROM agents WHERE id = ?", (normalized_id,)).fetchone()
        if row is None:
            raise RunLaunchRequestError(
                f'agent target not found: {normalized_id}',
                status_code=404,
                code='target_not_found',
                details={'target_type': 'agent', 'target_id': normalized_id},
            )
        agent = augment_agent_with_deployment(normalize_agent_row(row), conn) or {}
        ctx = run_context_for_agent(conn, agent_id=normalized_id, agent=agent)
        return ctx, {
            'target_type': 'agent',
            'target_id': normalized_id,
            'target_label': str(agent.get('name') or 'Unnamed agent'),
            'target_entity_type': 'Agent',
        }, agent
    if normalized_type == 'task':
        row = conn.execute(TASK_SELECT + " WHERE t.id = ?", (normalized_id,)).fetchone()
        if row is None:
            raise RunLaunchRequestError(
                f'task target not found: {normalized_id}',
                status_code=404,
                code='target_not_found',
                details={'target_type': 'task', 'target_id': normalized_id},
            )
        task = normalize_task_row(row, conn) or {}
        ctx = run_context_for_task(conn, task_id=normalized_id, task=task)
        return ctx, {
            'target_type': 'task',
            'target_id': normalized_id,
            'target_label': str(task.get('title') or 'Untitled task'),
            'target_entity_type': 'Task',
        }, task
    if normalized_type == 'deployment':
        row = conn.execute(DEPLOYMENT_SELECT + " WHERE d.id = ?", (normalized_id,)).fetchone()
        if row is None:
            raise RunLaunchRequestError(
                f'deployment target not found: {normalized_id}',
                status_code=404,
                code='target_not_found',
                details={'target_type': 'deployment', 'target_id': normalized_id},
            )
        deployment = normalize_deployment_row(row) or {}
        ctx = run_context_for_deployment(conn, deployment_id=normalized_id, deployment=deployment)
        return ctx, {
            'target_type': 'deployment',
            'target_id': normalized_id,
            'target_label': str(deployment.get('target') or 'Unnamed deployment'),
            'target_entity_type': 'Deployment',
        }, deployment
    raise RunLaunchRequestError(
        'target_type must be one of: workspace, agent, task, deployment',
        status_code=422,
        code='unsupported_target_type',
        details={'field': 'target_type'},
    )


def build_launch_target_profile(target_type: str, target_label: str, target_record: dict | None = None) -> dict:
    row = dict(target_record or {})
    base = {
        'family': 'operator evaluation',
        'target_type': target_type,
        'target_label': target_label,
        'queue_summary': 'Operator-triggered evaluation queued.',
        'queued_detail': 'Operator launched an evaluation run from the Runs workspace.',
        'running_summary': 'Operator evaluation running.',
        'running_detail': 'Building an execution plan and evaluating the selected target for operator review.',
        'result_label': 'Completed',
        'failure_result_label': 'Failed',
        'planning_label': 'Planning evaluation run',
        'selection_label': 'Selecting evaluation path',
        'selection_detail': 'Choosing compact evaluation + response synthesis path.',
        'execution_label': 'Executing evaluation',
        'assembly_label': 'Assembling operator output',
        'assembly_detail': 'Compacting evaluation findings into summary, payload, and draft artifacts.',
        'success_checks_passed': 3,
        'success_checks_failed': 0,
        'failure_checks_passed': 2,
        'failure_checks_failed': 1,
        'score': 0.94,
        'classification': 'ready',
        'focus': 'operator_readiness',
        'recommended_action': f'Review and approve the generated brief for {target_label}.',
        'output_snippet': f'Evaluation completed for {target_label}. Operator brief is ready for review.',
        'success_result_summary': 'Evaluation completed and operator brief generated.',
        'success_summary': 'Operator-triggered evaluation completed successfully.',
        'success_run_detail': 'Planning, execution, and output assembly completed from the Runs workspace launch control.',
        'success_log_preview': f'Operator evaluation for {target_label} completed successfully.',
        'success_final_event_label': 'Evaluation completed',
        'success_final_event_detail': 'Operator-triggered evaluation finished with review-ready output.',
        'failure_result_summary': 'Evaluation stopped in failure-check mode.',
        'failure_summary': 'Operator-triggered evaluation failed during execution.',
        'failure_run_detail': 'Planning completed, but failure-check mode intentionally exercised the failed execution branch.',
        'failure_log_preview': f'Operator evaluation for {target_label} stopped in failure-check mode.',
        'failure_error_message': 'Failure-check mode intentionally halted operator evaluation.',
        'failure_reason': 'Failure check requested by operator launch mode.',
        'failure_partial_output': f'Partial evaluation notes prepared for {target_label}, but final promotion was blocked.',
        'failure_final_event_label': 'Evaluation failed',
        'failure_final_event_detail': 'Failure-check mode exercised the failed execution path.',
        'success_report_label': 'Evaluation Summary',
        'success_response_label': 'Operator Brief Draft',
        'success_report_preview': f'Evaluation completed successfully for {target_label}.',
        'success_response_preview': f'Operator-facing brief prepared for {target_label}.',
        'failure_report_label': 'Evaluation Failure Summary',
        'failure_response_label': 'Partial Operator Draft',
        'failure_report_preview': f'Failure check triggered while evaluating {target_label}.',
        'failure_response_preview': 'Partial draft captured before the failure-check stop.',
    }
    if target_type == 'workspace':
        base.update({
            'focus': 'workspace_readiness',
            'planning_detail': f'Scoping workspace readiness review for {target_label}.',
            'execution_detail': f'Evaluating workspace readiness across runs, targets, and operator handoff context for {target_label}.',
            'success_result_summary': 'Workspace readiness evaluation completed and operator brief generated.',
            'success_run_detail': 'Workspace readiness, launch posture, and operator next action were assembled successfully.',
            'recommended_action': 'Review the workspace readiness brief and launch the next operator-approved run.',
            'output_snippet': 'Workspace readiness evaluated successfully. Operator brief is ready for review.',
            'success_report_label': 'Workspace Readiness Summary',
            'success_response_label': 'Workspace Operator Brief',
            'success_report_preview': 'Workspace readiness checks passed and the operator brief is ready.',
            'success_response_preview': 'Operator brief prepared for workspace launch oversight.',
            'failure_result_summary': 'Workspace readiness evaluation stopped in failure-check mode.',
            'failure_reason': 'Failure check requested while evaluating workspace readiness.',
            'failure_partial_output': 'Partial workspace readiness notes were prepared, but final promotion was blocked.',
            'failure_report_label': 'Workspace Failure Summary',
            'failure_response_label': 'Partial Workspace Brief',
        })
        return base
    if target_type == 'agent':
        agent_status = str(row.get('status') or 'draft').replace('_', ' ')
        deployment_status = str(row.get('deployment_status') or 'not_deployed').replace('_', ' ')
        base.update({
            'focus': 'agent_readiness',
            'planning_detail': f'Scoping agent readiness and execution posture for {target_label}.',
            'execution_detail': f'Evaluating agent capability, deployment posture, and operator-fit for {target_label}.',
            'classification': 'ready' if str(row.get('status') or '').lower() == 'active' else 'watch',
            'recommended_action': f'Review {target_label} role coverage and deployment posture before assigning live work.',
            'output_snippet': f'Agent readiness evaluated for {target_label}; role, status, and deployment posture were summarized.',
            'success_result_summary': 'Agent readiness evaluation completed and capability brief generated.',
            'success_run_detail': f'Agent role, status ({agent_status}), and deployment posture ({deployment_status}) were evaluated successfully.',
            'success_report_label': 'Agent Readiness Summary',
            'success_response_label': 'Agent Capability Brief',
            'success_report_preview': f'Agent readiness compiled for {target_label} with {agent_status} status.',
            'success_response_preview': f'Capability brief prepared for agent {target_label}.',
            'failure_result_summary': 'Agent readiness evaluation stopped in failure-check mode.',
            'failure_reason': f'Failure check requested while evaluating agent {target_label}.',
            'failure_partial_output': f'Partial agent readiness notes were prepared for {target_label}, but final promotion was blocked.',
            'failure_report_label': 'Agent Failure Summary',
            'failure_response_label': 'Partial Agent Brief',
        })
        return base
    if target_type == 'task':
        task_status = str(row.get('status') or 'backlog').replace('_', ' ')
        priority = str(row.get('priority') or 'medium')
        blocked_reason = str(row.get('blocked_reason') or '').strip()
        base.update({
            'focus': 'task_evaluation',
            'planning_detail': f'Scoping task execution review for {target_label}.',
            'execution_detail': f'Evaluating task readiness, execution context, and next operator move for {target_label}.',
            'classification': 'blocked' if blocked_reason else ('ready' if str(row.get('status') or '').lower() in {'ready', 'in_progress'} else 'watch'),
            'recommended_action': f'Review task state ({task_status}) and prioritize the next execution step for {target_label}.',
            'output_snippet': f'Task evaluation completed for {target_label}; state, priority, and next action were summarized.',
            'success_result_summary': 'Task evaluation completed and execution brief generated.',
            'success_run_detail': f'Task state ({task_status}), priority ({priority}), and execution readiness were evaluated successfully.',
            'success_report_label': 'Task Evaluation Summary',
            'success_response_label': 'Task Execution Brief',
            'success_report_preview': f'Task evaluation completed for {target_label} with {task_status} status.',
            'success_response_preview': f'Execution brief prepared for task {target_label}.',
            'failure_result_summary': 'Task evaluation stopped in failure-check mode.',
            'failure_reason': f'Failure check requested while evaluating task {target_label}.',
            'failure_partial_output': f'Partial task evaluation notes were prepared for {target_label}, but final promotion was blocked.',
            'failure_report_label': 'Task Failure Summary',
            'failure_response_label': 'Partial Task Brief',
        })
        return base
    if target_type == 'deployment':
        deployment_status = str(row.get('status') or 'draft').replace('_', ' ')
        deployment_type = str(row.get('deployment_type') or 'hermes_profile').replace('_', ' ')
        trigger_mode = str(row.get('trigger_mode') or 'manual').replace('_', ' ')
        base.update({
            'focus': 'deployment_readiness',
            'planning_detail': f'Scoping deployment readiness and health review for {target_label}.',
            'execution_detail': f'Evaluating deployment target, trigger mode, and readiness posture for {target_label}.',
            'classification': 'ready' if str(row.get('status') or '').lower() == 'ready' else 'watch',
            'recommended_action': f'Review deployment readiness for {target_label} before promoting new live execution.',
            'output_snippet': f'Deployment readiness evaluated for {target_label}; health posture and operator next action were summarized.',
            'success_result_summary': 'Deployment readiness evaluation completed and health brief generated.',
            'success_run_detail': f'Deployment type ({deployment_type}), status ({deployment_status}), and trigger mode ({trigger_mode}) were evaluated successfully.',
            'success_report_label': 'Deployment Readiness Summary',
            'success_response_label': 'Deployment Health Brief',
            'success_report_preview': f'Deployment readiness compiled for {target_label} with {deployment_status} status.',
            'success_response_preview': f'Health brief prepared for deployment {target_label}.',
            'failure_result_summary': 'Deployment readiness evaluation stopped in failure-check mode.',
            'failure_reason': f'Failure check requested while evaluating deployment {target_label}.',
            'failure_partial_output': f'Partial deployment readiness notes were prepared for {target_label}, but final promotion was blocked.',
            'failure_report_label': 'Deployment Failure Summary',
            'failure_response_label': 'Partial Deployment Brief',
        })
        return base
    return base


def build_launch_target_snapshot(target_type: str, target_record: dict | None = None) -> dict:
    row = dict(target_record or {})
    if target_type == 'workspace':
        return {
            'surface': 'runs_console',
            'entity_type': 'Workspace',
            'entity_id': 'operator-workspace',
            'entity_name': 'Operator Workspace',
        }
    if target_type == 'agent':
        return {
            'agent_id': str(row.get('id') or ''),
            'name': str(row.get('name') or ''),
            'role': str(row.get('role') or ''),
            'status': str(row.get('status') or ''),
            'deployment_status': str(row.get('deployment_status') or ''),
            'deployment_target': str(row.get('deployment_target') or ''),
        }
    if target_type == 'task':
        return {
            'task_id': str(row.get('id') or ''),
            'title': str(row.get('title') or ''),
            'status': str(row.get('status') or ''),
            'priority': str(row.get('priority') or ''),
            'blocked_reason': str(row.get('blocked_reason') or ''),
            'agent_id': str(row.get('agent_id') or ''),
            'agent_name': str(row.get('agent_name') or ''),
        }
    if target_type == 'deployment':
        return {
            'deployment_id': str(row.get('id') or ''),
            'target': str(row.get('target') or ''),
            'deployment_type': str(row.get('deployment_type') or ''),
            'status': str(row.get('status') or ''),
            'trigger_mode': str(row.get('trigger_mode') or ''),
            'agent_id': str(row.get('agent_id') or ''),
            'agent_name': str(row.get('agent_name') or ''),
        }
    return {}


def create_run_record(conn: sqlite3.Connection, *, run_type: str, title: str, status: str = "queued", started_at: str | None = None,
                      finished_at: str = "", summary: str = "", run_detail: str = "", result_label: str = "", result_summary: str = "", result_text: str = "", result_payload=None, artifact_manifest=None, artifact_count=None, output_status: str = "", error_message: str = "",
                      log_preview: str = "", target_entity_type: str = "", target_entity_id: str = "", target_entity_name: str = "",
                      trigger_label: str = "", changed_fields=None, metadata=None, agent_id: str = "", agent_name_snapshot: str = "", assignee_id: str = "", assignee_name: str = "", playbook_id: str = "", playbook_name: str = "", task_title_snapshot: str = "",
                      linked_task_id: str = "", linked_task_title_snapshot: str = "", deployment_id: str = "",
                      deployment_target_snapshot: str = "", deployment_type_snapshot: str = "", target: str = "",
                      environment: str = "", origin: str = "live", run_source: str = "", run_purpose: str = "") -> dict:
    now = utc_now()
    item = {
        "id": uuid.uuid4().hex,
        "type": normalize_run_type(run_type),
        "title": trim_run_text(title, 140) or "Untitled operation",
        "agent_id": str(agent_id or ""),
        "agent_name_snapshot": str(agent_name_snapshot or ""),
        "target": str(target or ""),
        "environment": str(environment or ""),
        "status": normalize_run_status(status),
        "started_at": str(started_at or now),
        "finished_at": str(finished_at or ""),
        "summary": trim_run_text(summary, 220),
        "run_detail": trim_run_text(run_detail, 420),
        "result_label": trim_run_text(result_label, 80),
        "result_summary": trim_run_text(result_summary, 220),
        "result_payload_json": json.dumps(sanitize_run_result_payload(result_payload), ensure_ascii=False),
        "artifact_count": max(0, int(artifact_count if artifact_count is not None else len(sanitize_run_artifact_manifest(artifact_manifest)))),
        "artifact_manifest_json": json.dumps(sanitize_run_artifact_manifest(artifact_manifest), ensure_ascii=False),
        "output_status": normalize_run_output_status(output_status),
        "error_message": make_run_error_message(error_message),
        "log_preview": trim_run_text(log_preview, 420),
        "target_entity_type": trim_run_text(target_entity_type, 40),
        "target_entity_id": trim_run_text(target_entity_id, 80),
        "target_entity_name": trim_run_text(target_entity_name, 140),
        "trigger_label": trim_run_text(trigger_label, 80),
        "changed_fields_json": json.dumps(sanitize_changed_fields(changed_fields), ensure_ascii=False),
        "metadata_json": json.dumps(sanitize_run_metadata(metadata), ensure_ascii=False),
        "task_title_snapshot": str(task_title_snapshot or linked_task_title_snapshot or ""),
        "assignee_id": str(assignee_id or agent_id or ""),
        "assignee_name": str(assignee_name or agent_name_snapshot or ""),
        "playbook_id": str(playbook_id or ""),
        "playbook_name": str(playbook_name or ""),
        "result_text": trim_run_text(result_text or result_summary, 4000),
        "linked_task_id": str(linked_task_id or ""),
        "linked_task_title_snapshot": str(linked_task_title_snapshot or task_title_snapshot or ""),
        "deployment_id": str(deployment_id or ""),
        "deployment_target_snapshot": str(deployment_target_snapshot or ""),
        "deployment_type_snapshot": str(deployment_type_snapshot or ""),
        "origin": normalize_run_origin(origin),
        "run_source": normalize_run_source(run_source),
        "run_purpose": normalize_run_purpose(run_purpose),
        "created_at": now,
        "updated_at": now,
    }
    conn.execute(
        """
        INSERT INTO runs (
          id, type, title, agent_id, agent_name_snapshot, target, environment, status, started_at, finished_at, summary,
          run_detail, result_label, result_summary, result_payload_json, artifact_count, artifact_manifest_json, output_status,
          error_message, log_preview, target_entity_type, target_entity_id, target_entity_name,
          trigger_label, changed_fields_json, metadata_json, task_title_snapshot, assignee_id, assignee_name, playbook_id, playbook_name, result_text, linked_task_id, linked_task_title_snapshot, deployment_id,
          deployment_target_snapshot, deployment_type_snapshot, origin, run_source, run_purpose, created_at, updated_at
        ) VALUES (
          :id, :type, :title, :agent_id, :agent_name_snapshot, :target, :environment, :status, :started_at, :finished_at, :summary,
          :run_detail, :result_label, :result_summary, :result_payload_json, :artifact_count, :artifact_manifest_json, :output_status,
          :error_message, :log_preview, :target_entity_type, :target_entity_id, :target_entity_name,
          :trigger_label, :changed_fields_json, :metadata_json, :task_title_snapshot, :assignee_id, :assignee_name, :playbook_id, :playbook_name, :result_text, :linked_task_id, :linked_task_title_snapshot, :deployment_id,
          :deployment_target_snapshot, :deployment_type_snapshot, :origin, :run_source, :run_purpose, :created_at, :updated_at
        )
        """,
        item,
    )
    row = conn.execute(RUN_SELECT + " WHERE r.id = ?", (item["id"],)).fetchone()
    return normalize_run_row(row)


def update_run_record(conn: sqlite3.Connection, run_id: str, **changes) -> dict:
    if not run_id:
        raise ValueError("run id is required")
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError("run not found")
    current = dict(row)
    payload = dict(current)
    payload["type"] = normalize_run_type(changes.get("type", current.get("type") or "task_run"))
    payload["title"] = trim_run_text(changes.get("title", current.get("title") or "Untitled operation"), 140)
    payload["agent_id"] = str(changes.get("agent_id", current.get("agent_id") or ""))
    payload["agent_name_snapshot"] = str(changes.get("agent_name_snapshot", current.get("agent_name_snapshot") or ""))
    payload["target"] = str(changes.get("target", current.get("target") or ""))
    payload["environment"] = str(changes.get("environment", current.get("environment") or ""))
    payload["status"] = normalize_run_status(changes.get("status", current.get("status") or "queued"))
    payload["started_at"] = str(changes.get("started_at", current.get("started_at") or utc_now()))
    payload["finished_at"] = str(changes.get("finished_at", current.get("finished_at") or ""))
    payload["summary"] = trim_run_text(changes.get("summary", current.get("summary") or ""), 220)
    payload["run_detail"] = trim_run_text(changes.get("run_detail", current.get("run_detail") or ""), 420)
    payload["result_label"] = trim_run_text(changes.get("result_label", current.get("result_label") or ""), 80)
    payload["result_summary"] = trim_run_text(changes.get("result_summary", current.get("result_summary") or ""), 220)
    payload["result_payload_json"] = json.dumps(sanitize_run_result_payload(changes.get("result_payload", current.get("result_payload_json") or {})), ensure_ascii=False)
    artifact_manifest = sanitize_run_artifact_manifest(changes.get("artifact_manifest", current.get("artifact_manifest_json") or []))
    payload["artifact_manifest_json"] = json.dumps(artifact_manifest, ensure_ascii=False)
    payload["artifact_count"] = max(0, int(changes.get("artifact_count", len(artifact_manifest))))
    payload["output_status"] = normalize_run_output_status(changes.get("output_status", current.get("output_status") or ""))
    payload["error_message"] = make_run_error_message(changes.get("error_message", current.get("error_message") or ""))
    payload["log_preview"] = trim_run_text(changes.get("log_preview", current.get("log_preview") or ""), 420)
    payload["target_entity_type"] = trim_run_text(changes.get("target_entity_type", current.get("target_entity_type") or ""), 40)
    payload["target_entity_id"] = trim_run_text(changes.get("target_entity_id", current.get("target_entity_id") or ""), 80)
    payload["target_entity_name"] = trim_run_text(changes.get("target_entity_name", current.get("target_entity_name") or ""), 140)
    payload["trigger_label"] = trim_run_text(changes.get("trigger_label", current.get("trigger_label") or ""), 80)
    payload["changed_fields_json"] = json.dumps(sanitize_changed_fields(changes.get("changed_fields", current.get("changed_fields_json") or [])), ensure_ascii=False)
    payload["metadata_json"] = json.dumps(sanitize_run_metadata(changes.get("metadata", current.get("metadata_json") or {})), ensure_ascii=False)
    payload["task_title_snapshot"] = str(changes.get("task_title_snapshot", current.get("task_title_snapshot") or current.get("linked_task_title_snapshot") or ""))
    payload["assignee_id"] = str(changes.get("assignee_id", current.get("assignee_id") or current.get("agent_id") or ""))
    payload["assignee_name"] = str(changes.get("assignee_name", current.get("assignee_name") or current.get("agent_name_snapshot") or ""))
    payload["playbook_id"] = str(changes.get("playbook_id", current.get("playbook_id") or ""))
    payload["playbook_name"] = str(changes.get("playbook_name", current.get("playbook_name") or ""))
    payload["result_text"] = trim_run_text(changes.get("result_text", current.get("result_text") or current.get("result_summary") or ""), 4000)
    payload["linked_task_id"] = str(changes.get("linked_task_id", current.get("linked_task_id") or ""))
    payload["linked_task_title_snapshot"] = str(changes.get("linked_task_title_snapshot", current.get("linked_task_title_snapshot") or current.get("task_title_snapshot") or ""))
    payload["deployment_id"] = str(changes.get("deployment_id", current.get("deployment_id") or ""))
    payload["deployment_target_snapshot"] = str(changes.get("deployment_target_snapshot", current.get("deployment_target_snapshot") or ""))
    payload["deployment_type_snapshot"] = str(changes.get("deployment_type_snapshot", current.get("deployment_type_snapshot") or ""))
    payload["origin"] = normalize_run_origin(changes.get("origin", current.get("origin") or "live"))
    payload["run_source"] = normalize_run_source(changes.get("run_source", current.get("run_source") or ""))
    payload["run_purpose"] = normalize_run_purpose(changes.get("run_purpose", current.get("run_purpose") or ""))
    payload["updated_at"] = utc_now()
    conn.execute(
        """
        UPDATE runs
        SET type = :type,
            title = :title,
            agent_id = :agent_id,
            agent_name_snapshot = :agent_name_snapshot,
            target = :target,
            environment = :environment,
            status = :status,
            started_at = :started_at,
            finished_at = :finished_at,
            summary = :summary,
            run_detail = :run_detail,
            result_label = :result_label,
            result_summary = :result_summary,
            result_payload_json = :result_payload_json,
            artifact_count = :artifact_count,
            artifact_manifest_json = :artifact_manifest_json,
            output_status = :output_status,
            error_message = :error_message,
            log_preview = :log_preview,
            target_entity_type = :target_entity_type,
            target_entity_id = :target_entity_id,
            target_entity_name = :target_entity_name,
            trigger_label = :trigger_label,
            changed_fields_json = :changed_fields_json,
            metadata_json = :metadata_json,
            task_title_snapshot = :task_title_snapshot,
            assignee_id = :assignee_id,
            assignee_name = :assignee_name,
            playbook_id = :playbook_id,
            playbook_name = :playbook_name,
            result_text = :result_text,
            linked_task_id = :linked_task_id,
            linked_task_title_snapshot = :linked_task_title_snapshot,
            deployment_id = :deployment_id,
            deployment_target_snapshot = :deployment_target_snapshot,
            deployment_type_snapshot = :deployment_type_snapshot,
            origin = :origin,
            run_source = :run_source,
            run_purpose = :run_purpose,
            updated_at = :updated_at
        WHERE id = :id
        """,
        payload,
    )
    row = conn.execute(RUN_SELECT + " WHERE r.id = ?", (run_id,)).fetchone()
    return normalize_run_row(row)


def mark_run_running(conn: sqlite3.Connection, run_id: str, summary: str = "", log_preview: str = "", **changes) -> dict:
    existing = conn.execute("SELECT started_at FROM runs WHERE id = ?", (run_id,)).fetchone()
    started_at = str(existing["started_at"] or utc_now()) if existing is not None else utc_now()
    return update_run_record(
        conn,
        run_id,
        status="running",
        started_at=started_at,
        finished_at="",
        summary=summary,
        log_preview=log_preview,
        **changes,
    )


def set_run_result_summary(conn: sqlite3.Connection, run_id: str, summary: str, *, output_status: str = '') -> dict:
    payload = {'result_summary': summary}
    if output_status:
        payload['output_status'] = output_status
    return update_run_record(conn, run_id, **payload)


def attach_run_result_payload(conn: sqlite3.Connection, run_id: str, payload, *, output_status: str = '') -> dict:
    changes = {'result_payload': payload}
    if output_status:
        changes['output_status'] = output_status
    return update_run_record(conn, run_id, **changes)


def attach_run_artifact_metadata(conn: sqlite3.Connection, run_id: str, artifacts, *, output_status: str = '', replace: bool = True) -> dict:
    row = conn.execute("SELECT artifact_manifest_json FROM runs WHERE id = ?", (run_id,)).fetchone()
    existing = []
    if row is not None and not replace:
        existing = sanitize_run_artifact_manifest(dict(row).get('artifact_manifest_json') or [])
    merged = existing + sanitize_run_artifact_manifest(artifacts)
    changes = {'artifact_manifest': merged, 'artifact_count': len(merged)}
    if output_status:
        changes['output_status'] = output_status
    return update_run_record(conn, run_id, **changes)


def finalize_run_output_state(conn: sqlite3.Connection, run_id: str, *, result_summary: str = '', result_payload=None, artifact_manifest=None, output_status: str = '', **changes) -> dict:
    payload = dict(changes)
    if result_summary:
        payload['result_summary'] = result_summary
    if result_payload is not None:
        payload['result_payload'] = result_payload
    if artifact_manifest is not None:
        clean_artifacts = sanitize_run_artifact_manifest(artifact_manifest)
        payload['artifact_manifest'] = clean_artifacts
        payload['artifact_count'] = len(clean_artifacts)
    if output_status:
        payload['output_status'] = output_status
    return update_run_record(conn, run_id, **payload)


def complete_run_record(conn: sqlite3.Connection, run_id: str, status: str, summary: str = "", log_preview: str = "", **changes) -> dict:
    payload = dict(changes)
    return update_run_record(
        conn,
        run_id,
        status=status,
        finished_at=utc_now(),
        summary=summary,
        log_preview=log_preview,
        **payload,
    )


def runs_cleanup(action: str, *, reseed: bool = False) -> dict:
    allowed = {'clear-seed', 'clear-test', 'reset'}
    if action not in allowed:
        raise ValueError(f"cleanup action must be one of: {', '.join(sorted(allowed))}")
    with connect_board() as conn:
        total_before = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        rows = conn.execute("SELECT * FROM runs").fetchall()
        deleted_ids = []
        deleted_seed = 0
        deleted_live = 0
        if action == 'clear-seed':
            deleted_ids = [str(row['id']) for row in rows if is_demo_run_row(row)]
        elif action == 'clear-test':
            deleted_ids = [str(row['id']) for row in rows if is_verification_run_row(row)]
        else:
            deleted_ids = [str(row['id']) for row in rows]
        if deleted_ids:
            placeholders = ','.join('?' for _ in deleted_ids)
            seed_rows = conn.execute(f"SELECT COUNT(*) FROM runs WHERE id IN ({placeholders}) AND lower(COALESCE(origin, 'seed')) = 'seed'", deleted_ids).fetchone()[0]
            conn.execute(f"DELETE FROM run_trace_events WHERE run_id IN ({placeholders})", deleted_ids)
            conn.execute(f"DELETE FROM runs WHERE id IN ({placeholders})", deleted_ids)
            deleted_seed = int(seed_rows or 0)
            deleted_live = len(deleted_ids) - deleted_seed
        reseeded = 0
        remaining = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        if reseed:
            reseeded = insert_seed_runs(conn)
            remaining = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        conn.commit()
        return {
            'ok': True,
            'action': action,
            'deleted': len(deleted_ids),
            'deleted_seed': deleted_seed,
            'deleted_live': deleted_live,
            'reseeded': reseeded,
            'before_count': total_before,
            'after_count': remaining,
        }


def run_list(*, task_id: str = '') -> list[dict]:
    with connect_board() as conn:
        clauses = []
        params = []
        if task_id:
            clauses.append("r.linked_task_id = ?")
            params.append(task_id)
        query = RUN_SELECT
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY CASE r.status WHEN 'running' THEN 0 WHEN 'failed' THEN 1 WHEN 'queued' THEN 2 WHEN 'cancelled' THEN 3 ELSE 4 END, r.started_at DESC, r.updated_at DESC"
        rows = conn.execute(query, params).fetchall()
        items = [normalize_run_row(row) for row in rows]
        non_demo = [item for item in items if not is_demo_run_row(item)]
        return non_demo if non_demo else items


def task_runs_list(conn: sqlite3.Connection, task_id: str) -> list[dict]:
    if not task_id:
        return []
    rows = conn.execute(
        RUN_SELECT + " WHERE r.linked_task_id = ? AND lower(COALESCE(r.run_source, '')) = 'task' AND lower(COALESCE(r.run_purpose, '')) IN ('execution', 'task_execution') ORDER BY COALESCE(NULLIF(r.started_at, ''), r.created_at) DESC, r.created_at DESC, r.id DESC",
        (task_id,),
    ).fetchall()
    return [normalize_run_row(row) for row in rows if row is not None]


def task_latest_run(conn: sqlite3.Connection, task_id: str) -> dict | None:
    runs = task_runs_list(conn, task_id)
    return runs[0] if runs else None


def run_get(run_id: str):
    if not run_id:
        raise ValueError("id is required")
    with connect_board() as conn:
        row = conn.execute(RUN_SELECT + " WHERE r.id = ?", (run_id,)).fetchone()
        if row is None:
            raise ResourceNotFoundError('run', run_id)
        return {"run": normalize_run_row(row)}


def run_rows_for_cleanup_scope(conn: sqlite3.Connection, scope: str) -> list[dict]:
    normalized = str(scope or '').strip().lower()
    if normalized not in {'cancelled', 'failed', 'completed', 'verification', 'all'}:
        raise ValueError('scope must be one of: cancelled, failed, completed, verification, all')
    rows = conn.execute('SELECT * FROM runs').fetchall()
    items = []
    for row in rows:
        item = dict(row)
        status = display_run_status(item.get('status') or '')
        if normalized == 'all':
            items.append(item)
        elif normalized == 'verification' and is_verification_run_row(item):
            items.append(item)
        elif normalized in {'cancelled', 'failed'} and status == normalized:
            items.append(item)
        elif normalized == 'completed' and status in {'completed', 'success'}:
            items.append(item)
    return items


def delete_runs_by_ids(conn: sqlite3.Connection, run_ids: list[str]) -> int:
    ids = [str(run_id or '').strip() for run_id in run_ids if str(run_id or '').strip()]
    if not ids:
        return 0
    placeholders = ','.join('?' for _ in ids)
    conn.execute(f'DELETE FROM run_trace_events WHERE run_id IN ({placeholders})', tuple(ids))
    conn.execute(f'DELETE FROM runs WHERE id IN ({placeholders})', tuple(ids))
    return len(ids)


def clear_runs(scope: str) -> dict:
    with connect_board() as conn:
        rows = run_rows_for_cleanup_scope(conn, scope)
        run_ids = [str(row.get('id') or '') for row in rows if str(row.get('id') or '')]
        deleted = delete_runs_by_ids(conn, run_ids)
        conn.commit()
        return {'ok': True, 'scope': str(scope or '').strip().lower(), 'deleted': deleted, 'deleted_ids': run_ids}


def delete_run_record(run_id: str) -> dict:
    if not run_id:
        raise ValueError('id is required')
    with connect_board() as conn:
        row = conn.execute('SELECT * FROM runs WHERE id = ?', (run_id,)).fetchone()
        if row is None:
            raise ResourceNotFoundError('run', run_id)
        deleted = delete_runs_by_ids(conn, [run_id])
        conn.commit()
        return {'ok': True, 'deleted': deleted, 'run_id': run_id}


def task_execution_run_payload(task: dict, *, summary: str = '', result_text: str = '', log_preview: str = '') -> dict:
    return {
        'run_type': 'task_run',
        'title': trim_run_text(f"Run task: {task.get('title') or 'Untitled task'}", 140),
        'status': 'queued',
        'summary': trim_run_text(summary or f"Execution queued for task \"{task.get('title') or 'Untitled task'}\".", 220),
        'run_detail': trim_run_text(f"Operator started a manual execution run from the task inspector.", 420),
        'result_label': 'Queued',
        'result_summary': trim_run_text(summary, 220),
        'result_text': result_text,
        'log_preview': trim_run_text(log_preview or 'Run queued from task inspector.', 420),
        'trigger_label': 'Task inspector execution',
        'run_source': 'task',
        'run_purpose': 'execution',
    }


def create_task_execution_run(task_id: str, payload: dict | None = None) -> dict:
    payload = dict(payload or {})
    with connect_board() as conn:
        row = conn.execute(TASK_SELECT + " WHERE t.id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError('task not found')
        task = normalize_task_row(row, conn)
        if task.get('status') != 'ready':
            raise ValueError('Only ready tasks can start a run')
        latest = task_latest_run(conn, task_id)
        if latest and latest.get('display_status') in {'queued', 'running'}:
            raise ValueError('Task already has an active run')
        summary = str(payload.get('summary') or '').strip()
        result_text = str(payload.get('resultText', payload.get('result_text', '')) or '').strip()
        log_preview = str(payload.get('logPreview', payload.get('log_preview', payload.get('note', ''))) or '').strip()
        base = task_execution_run_payload(task, summary=summary, result_text=result_text, log_preview=log_preview)
        ctx = run_context_for_task(conn, task_id=task_id, task=task)
        create_ctx = {key: value for key, value in ctx.items() if key != 'result_text'}
        run = create_run_record(conn, **base, **create_ctx)
        task_event_create(conn, task_id, 'run_created', f"Run created for task \"{task.get('title') or 'Untitled task'}\".", note=summary or log_preview, metadata={'run_id': run['id'], 'run_status': 'queued'})
        append_trace_event(conn, run['id'], event_type='queued', event_label='Run created', event_detail='Execution run created from the task inspector.', event_status='success', metadata={'task_id': task_id})
        mark_run_running(conn, run['id'], summary=trim_run_text(summary or f"Execution running for task \"{task.get('title') or 'Untitled task'}\".", 220), run_detail='Operator is driving the run manually from the task inspector.', result_label='Running', result_summary=trim_run_text(summary, 220), result_text=result_text, output_status='running', log_preview=trim_run_text(log_preview or 'Run started from task inspector.', 420), trigger_label='Task inspector execution', **create_ctx)
        append_trace_event(conn, run['id'], event_type='step', event_label='Run started', event_detail='Task execution is now in progress under operator control.', event_status='running', metadata={'task_id': task_id})
        previous_status = task.get('status') or ''
        now = utc_now()
        conn.execute("UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?", ('in_progress', now, task_id))
        task_event_create(conn, task_id, 'run_started', f"Run started for task \"{task.get('title') or 'Untitled task'}\".", note=summary or log_preview, metadata={'run_id': run['id'], 'run_status': 'running'})
        task_event_create(conn, task_id, 'status_changed', 'Status changed from Ready to In Progress.', note=summary or log_preview, metadata={'from_status': previous_status, 'to_status': 'in_progress', 'run_id': run['id']})
        conn.commit()
        return task_get(task_id)


def update_task_execution_run(run_id: str, payload: dict | None = None) -> dict:
    payload = dict(payload or {})
    requested_status = display_run_status(payload.get('status') or '')
    if requested_status not in {'completed', 'failed', 'cancelled'}:
        raise ValueError('Run update status must be one of: completed, failed, cancelled')
    summary = str(payload.get('summary') or '').strip()
    result_text = str(payload.get('resultText', payload.get('result_text', '')) or '').strip()
    log_preview = str(payload.get('logPreview', payload.get('log_preview', payload.get('note', ''))) or '').strip()
    fallback_task_status = 'triage' if requested_status == 'cancelled' else ('review' if requested_status == 'completed' else 'blocked')
    with connect_board() as conn:
        row = conn.execute(RUN_SELECT + " WHERE r.id = ?", (run_id,)).fetchone()
        if row is None:
            raise ResourceNotFoundError('run', run_id)
        run = normalize_run_row(row)
        task_id = str(run.get('linked_task_id') or run.get('task_id') or '')
        if not task_id:
            raise ValueError('Run is not linked to a task')
        task_row = conn.execute(TASK_SELECT + " WHERE t.id = ?", (task_id,)).fetchone()
        if task_row is None:
            raise KeyError('task not found')
        task = normalize_task_row(task_row, conn)
        if run.get('display_status') not in {'queued', 'running'}:
            raise ValueError('Only active runs can be updated from the execution controls')
        output_status = 'success' if requested_status == 'completed' else ('failed' if requested_status == 'failed' else 'empty')
        result_label = 'Completed' if requested_status == 'completed' else ('Failed' if requested_status == 'failed' else 'Cancelled')
        final_summary = summary or (f"Run completed for task \"{task.get('title') or 'Untitled task'}\"." if requested_status == 'completed' else f"Run {requested_status} for task \"{task.get('title') or 'Untitled task'}\".")
        final_note = log_preview or summary
        now = utc_now()
        update_run_record(conn, run_id, status=requested_status, summary=trim_run_text(final_summary, 220), result_summary=trim_run_text(summary or result_text or final_summary, 220), result_text=result_text, result_label=result_label, output_status=output_status, log_preview=trim_run_text(log_preview or final_summary, 420), error_message=(summary or log_preview) if requested_status == 'failed' else '', trigger_label='Task inspector execution', finished_at=now)
        trace_event_type = 'completed' if requested_status == 'completed' else ('failed' if requested_status == 'failed' else 'cancelled')
        trace_event_status = 'success' if requested_status == 'completed' else ('failed' if requested_status == 'failed' else 'skipped')
        append_trace_event(conn, run_id, event_type=trace_event_type, event_label=f'Run {result_label.lower()}', event_detail=trim_run_text(final_summary, 220), event_status=trace_event_status, metadata={'task_id': task_id, 'task_status': fallback_task_status})
        blocked_reason = task.get('blocked_reason') or ''
        if requested_status == 'failed':
            blocked_reason = final_note or blocked_reason or 'Run failed.'
        elif requested_status == 'cancelled':
            blocked_reason = ''
        conn.execute("UPDATE tasks SET status = ?, result_text = ?, last_note = ?, blocked_reason = ?, updated_at = ? WHERE id = ?", (fallback_task_status, result_text or task.get('result_text') or '', final_note or task.get('last_note') or '', blocked_reason, now, task_id))
        task_event_create(conn, task_id, f'run_{requested_status}', f"Run {requested_status} for task \"{task.get('title') or 'Untitled task'}\".", note=final_note or result_text, metadata={'run_id': run_id, 'run_status': requested_status, 'task_status': fallback_task_status})
        task_event_create(conn, task_id, 'status_changed', f"Status changed from {str(task.get('status') or '').replace('_', ' ').title() or 'Unknown'} to {fallback_task_status.replace('_', ' ').title()}.", note=final_note or result_text, metadata={'from_status': task.get('status') or '', 'to_status': fallback_task_status, 'run_id': run_id})
        if result_text and result_text != str(task.get('result_text') or ''):
            task_event_create(conn, task_id, 'result_saved', 'Result/output updated.', note=result_text, metadata={'has_result': True, 'run_id': run_id})
        conn.commit()
        return task_get(task_id)


def run_context_get(run_id: str):
    if not run_id:
        raise ValueError("id is required")
    with connect_board() as conn:
        return build_run_context_payload(conn, run_id)


def run_trace_get(run_id: str):
    if not run_id:
        raise ValueError("id is required")
    with connect_board() as conn:
        row = conn.execute(RUN_SELECT + " WHERE r.id = ?", (run_id,)).fetchone()
        if row is None:
            raise ResourceNotFoundError('run', run_id)
        return {
            'run': normalize_run_row(row),
            'trace': list_run_trace_events(conn, run_id),
            'trace_count': conn.execute("SELECT COUNT(*) FROM run_trace_events WHERE run_id = ?", (run_id,)).fetchone()[0],
        }


def create_trace_probe(payload: dict):
    mode = str((payload or {}).get('mode') or 'success').strip().lower()
    if mode not in {'success', 'failure'}:
        raise ValueError("mode must be one of: success, failure")
    requested_agent_id = str((payload or {}).get('agent_id') or '').strip()
    with connect_board() as conn:
        agent = None
        if requested_agent_id:
            row = conn.execute("SELECT * FROM agents WHERE id = ?", (requested_agent_id,)).fetchone()
            if row is None:
                raise KeyError('agent not found')
            agent = normalize_agent_row(row)
        else:
            row = conn.execute("SELECT * FROM agents ORDER BY updated_at DESC, created_at DESC LIMIT 1").fetchone()
            if row is not None:
                agent = normalize_agent_row(row)
        agent_ctx = run_context_for_agent(conn, agent_id=str((agent or {}).get('id') or ''), agent=agent or {}) if agent else {
            'agent_id': '',
            'agent_name_snapshot': 'Trace Sandbox',
            'deployment_id': '',
            'deployment_target_snapshot': '',
            'deployment_type_snapshot': '',
            'target': 'Runtime trace sandbox',
            'environment': 'runtime_probe',
            **run_target_entity_payload(entity_type='', entity_id='', entity_name=''),
        }
        probe_title = trim_run_text(f"Trace probe ({mode}): {(agent or {}).get('name') or 'Runtime sandbox'}", 140)
        base_metadata = {
            **run_context_metadata(
                agent_id=str((agent or {}).get('id') or ''),
                agent_name=str((agent or {}).get('name') or ''),
                deployment_id=str(agent_ctx.get('deployment_id') or ''),
                deployment_target=str(agent_ctx.get('deployment_target_snapshot') or ''),
                deployment_type=str(agent_ctx.get('deployment_type_snapshot') or ''),
            ),
            'probe_mode': mode,
            'phase': '19',
        }
        run = create_execution_run(
            conn,
            run_type='agent_execution',
            title=probe_title,
            summary='Execution probe queued.',
            run_detail='Phase 19 verification probe admitted for execution trace capture.',
            result_label='Queued',
            trigger_label='Execution trace probe',
            log_preview='Queued runtime probe for execution trace verification.',
            metadata=base_metadata,
            run_source='verification',
            run_purpose='smoke_test',
            origin='live',
            **agent_ctx,
        )
        mark_run_running(
            conn,
            run['id'],
            summary='Execution probe running.',
            run_detail='Recording ordered internal execution steps for operator inspection.',
            result_label='Running',
            result_summary='Execution probe admitted and awaiting evaluator output.',
            output_status='running',
            trigger_label='Execution trace probe',
            log_preview='Runtime probe started. Capturing planning and execution steps.',
            metadata=base_metadata,
            title=probe_title,
            **agent_ctx,
        )
        planning = append_trace_event(conn, run['id'], event_type='planning', event_label='Planning execution', event_detail='Building compact execution plan for the runtime probe.', event_status='running', metadata={'mode': mode, 'stage': 'planning'})
        mark_execution_step_status(conn, planning['id'], status='success', detail='Execution plan prepared for the trace probe.', metadata={'mode': mode, 'stage': 'planning'})
        tool_selection = append_trace_event(conn, run['id'], event_type='tool_selection', event_label='Selecting evaluator', event_detail='Choosing the verification evaluator for the probe.', event_status='running', metadata={'mode': mode, 'stage': 'tool_selection'})
        mark_execution_step_status(conn, tool_selection['id'], status='success', detail='Selected deterministic verification evaluator.', metadata={'mode': mode, 'stage': 'tool_selection'})
        tool_execution = append_trace_event(conn, run['id'], event_type='tool_execution', event_label='Executing evaluator', event_detail='Running the trace probe against the selected evaluator.', event_status='running', metadata={'mode': mode, 'stage': 'tool_execution'})
        if mode == 'failure':
            mark_execution_step_status(conn, tool_execution['id'], status='failed', detail='Evaluator returned a deterministic failure for the verification probe.', metadata={'mode': mode, 'stage': 'tool_execution'})
            append_trace_event(conn, run['id'], event_type='result_assembly', event_label='Result assembly skipped', event_detail='Skipped final result assembly because evaluator execution failed.', event_status='skipped', metadata={'mode': mode, 'stage': 'result_assembly'})
            failure_payload = {
                'decision': 'fail',
                'failed_step': 'executing_evaluator',
                'checks_passed': 2,
                'checks_failed': 1,
                'failure_reason': 'Evaluator timeout while scoring response draft.',
                'partial_output': 'Response draft created, but final evaluation verdict could not be finalized.',
            }
            failure_artifacts = [
                {
                    'type': 'report',
                    'label': 'Partial Evaluation Summary',
                    'path': '/tmp/agentforge-trace-probe-failure-summary.json',
                    'preview': '2 checks passed before evaluator timeout on the final verdict.',
                    'status': 'partial',
                },
                {
                    'type': 'response',
                    'label': 'Partial Response Draft',
                    'preview': 'Draft response available but not promoted to final operator answer.',
                    'status': 'failed',
                },
            ]
            finalize_run_output_state(
                conn,
                run['id'],
                result_summary='Execution failed during evaluator call.',
                result_payload=failure_payload,
                artifact_manifest=failure_artifacts,
                output_status='failed',
            )
            record = finalize_execution_run(
                conn,
                run['id'],
                status='failed',
                summary='Execution probe failed during evaluator execution.',
                run_detail='Planning and evaluator selection completed, but the execution step failed before final assembly.',
                result_label='Failed',
                result_summary='Execution failed during evaluator call.',
                result_payload=failure_payload,
                artifact_manifest=failure_artifacts,
                output_status='failed',
                error_message='Deterministic trace probe failure at evaluator execution step.',
                log_preview='Evaluator execution failed during Phase 19 trace probe.',
                final_event_label='Execution failed',
                final_event_detail='Trace probe stopped at evaluator execution.',
                metadata={**base_metadata, 'failure_step': 'Executing evaluator'},
                title=probe_title,
                **agent_ctx,
            )
        else:
            mark_execution_step_status(conn, tool_execution['id'], status='success', detail='Evaluator execution completed successfully.', metadata={'mode': mode, 'stage': 'tool_execution'})
            result_assembly = append_trace_event(conn, run['id'], event_type='result_assembly', event_label='Assembling result', event_detail='Compacting evaluator output into operator-facing result data.', event_status='running', metadata={'mode': mode, 'stage': 'result_assembly'})
            mark_execution_step_status(conn, result_assembly['id'], status='success', detail='Operator-facing result assembled for the probe.', metadata={'mode': mode, 'stage': 'result_assembly'})
            success_payload = {
                'decision': 'pass',
                'checks_passed': 3,
                'checks_failed': 0,
                'score': 0.96,
                'classification': 'ready',
                'output_snippet': 'Runtime evaluator stable and operator response draft generated.',
            }
            success_artifacts = [
                {
                    'type': 'report',
                    'label': 'Evaluation Summary',
                    'path': '/tmp/agentforge-trace-probe-success-summary.json',
                    'preview': 'Three checks passed. Runtime execution path verified.',
                    'status': 'success',
                },
                {
                    'type': 'response',
                    'label': 'Generated Response Draft',
                    'preview': 'Phase 19 probe completed. Runtime evaluator stable and ready for operator review.',
                    'status': 'success',
                },
            ]
            finalize_run_output_state(
                conn,
                run['id'],
                result_summary='Evaluation completed with 3 checks passed.',
                result_payload=success_payload,
                artifact_manifest=success_artifacts,
                output_status='success',
            )
            record = finalize_execution_run(
                conn,
                run['id'],
                status='success',
                summary='Execution probe completed successfully.',
                run_detail='Planning, evaluator execution, and result assembly all completed for the trace verification path.',
                result_label='Completed',
                result_summary='Evaluation completed with 3 checks passed.',
                result_payload=success_payload,
                artifact_manifest=success_artifacts,
                output_status='success',
                log_preview='Execution probe completed with a full ordered trace and operator-facing output.',
                final_event_label='Execution completed',
                final_event_detail='Trace probe finished with a successful result.',
                metadata={**base_metadata, 'result': 'success'},
                title=probe_title,
                **agent_ctx,
            )
        trace = list_run_trace_events(conn, run['id'])
        conn.commit()
        return {'ok': True, 'run': record, 'trace': trace, 'mode': mode}

def launch_operator_run(payload: dict):
    request = validate_operator_launch_payload(payload)
    action = request['action']
    target_type = request['target_type']
    target_id = request['target_id']
    run_mode = request['run_mode']
    execution_intent = request['execution_intent']
    prompt_text = request['prompt_text']
    test_mode = request['test_mode']
    requested_failure_check = request['requested_failure_check']
    with connect_board() as conn:
        target_ctx, target_meta, target_record = resolve_run_launch_target(conn, target_type=target_type, target_id=target_id)
        target_label = str(target_meta.get('target_label') or 'Operator Workspace')
        safe_target_id = str(target_meta.get('target_id') or '')
        target_profile = build_launch_target_profile(target_type, target_label, target_record)
        target_snapshot = build_launch_target_snapshot(target_type, target_record)
        metadata = {
            **run_context_metadata(
                task_id=str(target_ctx.get('linked_task_id') or ''),
                task_title=str(target_ctx.get('linked_task_title_snapshot') or ''),
                agent_id=str(target_ctx.get('agent_id') or ''),
                agent_name=str(target_ctx.get('agent_name_snapshot') or ''),
                deployment_id=str(target_ctx.get('deployment_id') or ''),
                deployment_target=str(target_ctx.get('deployment_target_snapshot') or ''),
                deployment_type=str(target_ctx.get('deployment_type_snapshot') or ''),
            ),
            'action': action,
            'intent': execution_intent,
            'target_type': target_type,
            'target_id': safe_target_id,
            'target_label': target_label,
            'run_mode': run_mode,
            'test_mode': test_mode,
            'phase': '21',
            'launch_family': target_profile.get('family') or 'operator evaluation',
            'target_context': target_snapshot,
        }
        if prompt_text:
            metadata['prompt_excerpt'] = trim_run_text(prompt_text, 160)
        title = trim_run_text(f"Run evaluation: {target_label}", 140)
        run = create_execution_run(
            conn,
            run_type='evaluation',
            title=title,
            summary=str(target_profile.get('queue_summary') or 'Operator-triggered evaluation queued.'),
            run_detail=str(target_profile.get('queued_detail') or 'Operator launched an evaluation run from the Runs workspace.'),
            result_label='Queued',
            trigger_label='Run evaluation',
            log_preview=f"Queued operator evaluation for {target_label}.",
            metadata=metadata,
            run_source=('task' if target_type == 'task' else ('deployment' if target_type == 'deployment' else 'runtime')),
            run_purpose=('smoke_test' if requested_failure_check else 'execution'),
            origin='live',
            **target_ctx,
        )
        mark_run_running(
            conn,
            run['id'],
            summary=str(target_profile.get('running_summary') or 'Operator evaluation running.'),
            run_detail=str(target_profile.get('running_detail') or 'Building an execution plan and evaluating the selected target for operator review.'),
            result_label='Running',
            result_summary='Evaluation started and waiting for execution output.',
            output_status='running',
            trigger_label='Run evaluation',
            log_preview=f"Operator evaluation started for {target_label}.",
            metadata=metadata,
            title=title,
            **target_ctx,
        )
        planning = append_trace_event(
            conn,
            run['id'],
            event_type='planning',
            event_label=str(target_profile.get('planning_label') or 'Planning evaluation run'),
            event_detail=str(target_profile.get('planning_detail') or f'Scoping evaluation intent for {target_label}.'),
            event_status='running',
            metadata={'intent': execution_intent, 'target_type': target_type, 'run_mode': run_mode},
        )
        mark_execution_step_status(
            conn,
            planning['id'],
            status='success',
            detail='Execution plan prepared for operator-triggered evaluation.',
            metadata={'target_label': target_label, 'intent': execution_intent},
        )
        tool_selection = append_trace_event(
            conn,
            run['id'],
            event_type='tool_selection',
            event_label=str(target_profile.get('selection_label') or 'Selecting evaluation path'),
            event_detail=str(target_profile.get('selection_detail') or 'Choosing compact evaluation + response synthesis path.'),
            event_status='running',
            metadata={'target_type': target_type, 'has_prompt': bool(prompt_text)},
        )
        mark_execution_step_status(
            conn,
            tool_selection['id'],
            status='success',
            detail='Selected evaluation path for operator launch.',
            metadata={'run_mode': run_mode, 'test_mode': test_mode},
        )
        tool_execution = append_trace_event(
            conn,
            run['id'],
            event_type='tool_execution',
            event_label=str(target_profile.get('execution_label') or 'Executing evaluation'),
            event_detail=str(target_profile.get('execution_detail') or f'Evaluating {target_label} and assembling operator-facing output.'),
            event_status='running',
            metadata={'target_label': target_label, 'intent': execution_intent, 'focus': target_profile.get('focus')},
        )
        prompt_excerpt = trim_run_text(prompt_text or execution_intent, 120)
        summary_path = Path(f"/tmp/agentforge-run-launch-{run['id']}-summary.json")
        response_path = Path(f"/tmp/agentforge-run-launch-{run['id']}-response.md")
        if requested_failure_check:
            mark_execution_step_status(
                conn,
                tool_execution['id'],
                status='failed',
                detail='Failure-check mode intentionally stopped the evaluation during execution.',
                metadata={'run_mode': run_mode, 'test_mode': test_mode},
            )
            append_trace_event(
                conn,
                run['id'],
                event_type='result_assembly',
                event_label='Result assembly skipped',
                event_detail='Operator-triggered failure check stopped before final result assembly.',
                event_status='skipped',
                metadata={'target_label': target_label, 'reason': 'failure_check', 'target_type': target_type},
            )
            failure_payload = {
                'decision': 'fail',
                'target_type': target_type,
                'target_label': target_label,
                'focus': target_profile.get('focus'),
                'intent': execution_intent,
                'failed_step': 'executing_evaluation',
                'failure_reason': str(target_profile.get('failure_reason') or 'Failure check requested by operator launch mode.'),
                'checks_passed': int(target_profile.get('failure_checks_passed') or 2),
                'checks_failed': int(target_profile.get('failure_checks_failed') or 1),
                'partial_output': str(target_profile.get('failure_partial_output') or f'Partial evaluation notes prepared for {target_label}, but final promotion was blocked.'),
                'prompt_excerpt': prompt_excerpt,
                'recommended_action': str(target_profile.get('recommended_action') or ''),
                'target_context': target_snapshot,
            }
            summary_path.write_text(json.dumps(failure_payload, indent=2, ensure_ascii=False), encoding='utf-8')
            response_path.write_text(
                f'''# Partial response draft

Target: {target_label}

Intent: {execution_intent}

Partial output only. Failure check stopped before final approval.
''',
                encoding='utf-8',
            )
            failure_artifacts = [
                {
                    'type': 'report',
                    'label': str(target_profile.get('failure_report_label') or 'Evaluation Failure Summary'),
                    'path': str(summary_path),
                    'preview': str(target_profile.get('failure_report_preview') or f'Failure check triggered while evaluating {target_label}.'),
                    'status': 'failed',
                },
                {
                    'type': 'response',
                    'label': str(target_profile.get('failure_response_label') or 'Partial Operator Draft'),
                    'path': str(response_path),
                    'preview': str(target_profile.get('failure_response_preview') or 'Partial draft captured before the failure-check stop.'),
                    'status': 'partial',
                },
            ]
            finalize_run_output_state(
                conn,
                run['id'],
                result_summary=str(target_profile.get('failure_result_summary') or 'Evaluation stopped in failure-check mode.'),
                result_payload=failure_payload,
                artifact_manifest=failure_artifacts,
                output_status='failed',
            )
            record = finalize_execution_run(
                conn,
                run['id'],
                status='failed',
                summary=str(target_profile.get('failure_summary') or 'Operator-triggered evaluation failed during execution.'),
                run_detail=str(target_profile.get('failure_run_detail') or 'Planning completed, but failure-check mode intentionally exercised the failed execution branch.'),
                result_label=str(target_profile.get('failure_result_label') or 'Failed'),
                result_summary=str(target_profile.get('failure_result_summary') or 'Evaluation stopped in failure-check mode.'),
                result_payload=failure_payload,
                artifact_manifest=failure_artifacts,
                output_status='failed',
                error_message=str(target_profile.get('failure_error_message') or 'Failure-check mode intentionally halted operator evaluation.'),
                log_preview=str(target_profile.get('failure_log_preview') or f'Operator evaluation for {target_label} stopped in failure-check mode.'),
                final_event_label=str(target_profile.get('failure_final_event_label') or 'Evaluation failed'),
                final_event_detail=str(target_profile.get('failure_final_event_detail') or 'Failure-check mode exercised the failed execution path.'),
                metadata={**metadata, 'result': 'failed', 'failure_reason': 'failure_check', 'target_profile': target_profile},
                title=title,
                **target_ctx,
            )
        else:
            mark_execution_step_status(
                conn,
                tool_execution['id'],
                status='success',
                detail='Evaluation logic completed and returned operator-facing findings.',
                metadata={'target_label': target_label, 'intent': execution_intent},
            )
            result_assembly = append_trace_event(
                conn,
                run['id'],
                event_type='result_assembly',
                event_label=str(target_profile.get('assembly_label') or 'Assembling operator output'),
                event_detail=str(target_profile.get('assembly_detail') or 'Compacting evaluation findings into summary, payload, and draft artifacts.'),
                event_status='running',
                metadata={'target_label': target_label, 'target_type': target_type, 'focus': target_profile.get('focus')},
            )
            mark_execution_step_status(
                conn,
                result_assembly['id'],
                status='success',
                detail='Operator-facing evaluation output assembled successfully.',
                metadata={'target_label': target_label},
            )
            success_payload = {
                'decision': 'pass',
                'target_type': target_type,
                'target_label': target_label,
                'focus': target_profile.get('focus'),
                'intent': execution_intent,
                'checks_passed': int(target_profile.get('success_checks_passed') or 3),
                'checks_failed': int(target_profile.get('success_checks_failed') or 0),
                'score': float(target_profile.get('score') or 0.94),
                'classification': str(target_profile.get('classification') or 'ready'),
                'recommended_action': str(target_profile.get('recommended_action') or f'Review and approve the generated brief for {target_label}.'),
                'output_snippet': str(target_profile.get('output_snippet') or f'Evaluation completed for {target_label}. Operator brief is ready for review.'),
                'prompt_excerpt': prompt_excerpt,
                'target_context': target_snapshot,
            }
            summary_path.write_text(json.dumps(success_payload, indent=2, ensure_ascii=False), encoding='utf-8')
            response_path.write_text(
                f'''# Operator evaluation brief

Target: {target_label}

Intent: {execution_intent}

Summary: {success_payload['output_snippet']}

Recommended action: {success_payload['recommended_action']}
''',
                encoding='utf-8',
            )
            success_artifacts = [
                {
                    'type': 'report',
                    'label': str(target_profile.get('success_report_label') or 'Evaluation Summary'),
                    'path': str(summary_path),
                    'preview': str(target_profile.get('success_report_preview') or f'Evaluation completed successfully for {target_label}.'),
                    'status': 'success',
                },
                {
                    'type': 'response',
                    'label': str(target_profile.get('success_response_label') or 'Operator Brief Draft'),
                    'path': str(response_path),
                    'preview': str(target_profile.get('success_response_preview') or f'Operator-facing brief prepared for {target_label}.'),
                    'status': 'success',
                },
            ]
            finalize_run_output_state(
                conn,
                run['id'],
                result_summary=str(target_profile.get('success_result_summary') or 'Evaluation completed and operator brief generated.'),
                result_payload=success_payload,
                artifact_manifest=success_artifacts,
                output_status='success',
            )
            record = finalize_execution_run(
                conn,
                run['id'],
                status='success',
                summary=str(target_profile.get('success_summary') or 'Operator-triggered evaluation completed successfully.'),
                run_detail=str(target_profile.get('success_run_detail') or 'Planning, execution, and output assembly completed from the Runs workspace launch control.'),
                result_label=str(target_profile.get('result_label') or 'Completed'),
                result_summary=str(target_profile.get('success_result_summary') or 'Evaluation completed and operator brief generated.'),
                result_payload=success_payload,
                artifact_manifest=success_artifacts,
                output_status='success',
                log_preview=str(target_profile.get('success_log_preview') or f'Operator evaluation for {target_label} completed successfully.'),
                final_event_label=str(target_profile.get('success_final_event_label') or 'Evaluation completed'),
                final_event_detail=str(target_profile.get('success_final_event_detail') or 'Operator-triggered evaluation finished with review-ready output.'),
                metadata={**metadata, 'result': 'success', 'target_profile': target_profile},
                title=title,
                **target_ctx,
            )
        trace = list_run_trace_events(conn, run['id'])
        conn.commit()
        return {
            'ok': True,
            'run': record,
            'trace': trace,
            'launch': {
                'action': action,
                'target_type': target_type,
                'target_id': safe_target_id,
                'target_label': target_label,
                'run_mode': run_mode,
                'test_mode': test_mode,
            },
        }


def snapshot():
    return {
        "generated_at": utc_now(),
        "service": {"name": "Hermes Mission Control", "host": HOST, "port": PORT},
        "gateway": safe_call("gateway", gateway_data),
        "activity": safe_call("activity", activity_data),
        "sessions": safe_call("sessions", sessions_data),
        "vps": safe_call("vps", vps_health),
        "cron": safe_call("cron", cron_jobs),
        "board": safe_call("board", lambda: {"tasks": board_list()}),
        "runs": safe_call("runs", lambda: {"items": run_list()}),
    }


def library_agent_for(path: Path) -> str:
    rel_parts = [p.lower() for p in path.relative_to(LIBRARY_ROOT).parts]
    for part in rel_parts[:-1]:
        clean = part.replace(" ", "_").replace("-", "_")
        for agent in LIBRARY_AGENTS:
            if clean == agent:
                return agent
    stem = path.stem.lower().replace(" ", "_")
    for agent in LIBRARY_AGENTS:
        if stem == agent or stem.startswith(agent + "_") or stem.startswith(agent + "-"):
            return agent
    return "master"


def markdown_title(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("# "):
                    title = stripped[2:].strip()
                    return title or path.name
    except OSError:
        pass
    return path.name


def library_rel(path: Path) -> str:
    return str(path.relative_to(LIBRARY_ROOT)).replace(os.sep, "/")


def validate_library_path(raw_path: str) -> Path:
    if not raw_path or not isinstance(raw_path, str):
        raise ValueError("missing path")
    if "\x00" in raw_path or ".." in Path(raw_path).parts:
        raise ValueError("invalid path")
    candidate = (LIBRARY_ROOT / raw_path.lstrip("/")).resolve(strict=False)
    root = LIBRARY_ROOT.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes library root") from exc
    if candidate.suffix.lower() != ".md":
        raise ValueError("only markdown files are supported")
    if candidate.exists():
        real_candidate = candidate.resolve(strict=True)
        try:
            real_candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("symlink escapes library root") from exc
        if not real_candidate.is_file():
            raise ValueError("not a file")
        return real_candidate
    parent = candidate.parent.resolve(strict=False)
    try:
        parent.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes library root") from exc
    return candidate


def library_list() -> list[dict]:
    if not LIBRARY_ROOT.exists():
        return []
    root = LIBRARY_ROOT.resolve(strict=False)
    docs = []
    for path in LIBRARY_ROOT.rglob("*.md"):
        try:
            real = path.resolve(strict=True)
            real.relative_to(root)
            if not real.is_file():
                continue
            stat = real.stat()
            docs.append({
                "agent": library_agent_for(real),
                "path": library_rel(real),
                "filename": real.name,
                "title": markdown_title(real),
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "size": stat.st_size,
            })
        except Exception:
            continue
    docs.sort(key=lambda d: d.get("modified_at") or "", reverse=True)
    return docs


def library_get(raw_path: str) -> dict:
    path = validate_library_path(raw_path)
    if not path.exists():
        raise FileNotFoundError("document not found")
    return {"path": library_rel(path), "content": path.read_text(encoding="utf-8", errors="replace")}


def library_save(payload: dict) -> dict:
    raw_path = str(payload.get("path") or "")
    content = payload.get("content")
    if not isinstance(content, str):
        raise ValueError("content must be a string")
    path = validate_library_path(raw_path)
    if not path.exists():
        raise FileNotFoundError("document not found")
    path.write_text(content, encoding="utf-8")
    os.utime(path, None)
    return {"ok": True, "document": next((d for d in library_list() if d["path"] == library_rel(path)), None)}


GRAPH_TYPE_COLORS = {
    "project": "#22D3EE",
    "note": "#8B5CF6",
    "runbook": "#F59E0B",
    "agent": "#3B82F6",
    "system": "#22C55E",
    "automation": "#EC4899",
    "memory": "#F97316",
}


PROJECT_GRAPH_NODES = [
    {
        "id": "project:jobforge",
        "label": "JobForge",
        "summary": "Primary AI job-matching and ranking system for DV's remote AI developer hunt.",
        "keywords": ["jobforge", "onlinejobs", "oj.ph", "job hunt"],
        "path": "/opt/jobforge/JobForge",
    },
    {
        "id": "project:clientforge",
        "label": "ClientForge",
        "summary": "Flagship AI SaaS portfolio project for service-company copilot workflows.",
        "keywords": ["clientforge", "service companies", "copilot"],
        "path": "portfolio / active build",
    },
    {
        "id": "project:promptforge",
        "label": "PromptForge",
        "summary": "Live multi-agent prompt engineering SaaS with model routing and niche pipelines.",
        "keywords": ["promptforge", "prompt engineering", "god-mode-sigma"],
        "path": "promptforge.dvpnbuilds.com",
    },
    {
        "id": "project:med-reviewer",
        "label": "Chimmy's Med Reviewer",
        "summary": "Personal med-school study platform built for Chim with RAG, PDFs, and spaced repetition.",
        "keywords": ["med reviewer", "chim", "medical", "spaced repetition"],
        "path": "app.dvpnbuilds.com",
    },
    {
        "id": "project:voltedge",
        "label": "Voltedge",
        "summary": "Construction-company AI operations stack for DV's father's business.",
        "keywords": ["voltedge", "construction", "father", "rag system"],
        "path": "voltedge.dvpnbuilds.com",
    },
]


MEMORY_GRAPH_NODES = [
    {
        "id": "memory:concise-replies",
        "label": "Concise Replies",
        "summary": "DV prefers terse, direct, technical responses with low fluff.",
        "keywords": ["concise", "terse", "direct", "technical"],
    },
    {
        "id": "memory:contract-first",
        "label": "Contract-First Path",
        "summary": "DV prefers contract and freelance AI work over traditional employment when practical.",
        "keywords": ["contract", "freelance", "remote"],
    },
    {
        "id": "memory:jobforge-primary",
        "label": "JobForge Primary",
        "summary": "JobForge is the main operating system for DV's job hunt and application flow.",
        "keywords": ["jobforge", "job hunt", "applications"],
    },
    {
        "id": "memory:clientforge-flagship",
        "label": "ClientForge Flagship",
        "summary": "ClientForge is the flagship SaaS portfolio build intended to signal real AI product capability.",
        "keywords": ["clientforge", "flagship", "portfolio"],
    },
]


SYSTEM_GRAPH_NODES = [
    {
        "id": "system:agentforge",
        "label": "AgentForge Mission Control",
        "summary": "Mission-control dashboard for visualizing agents, tasks, automation, vault knowledge, and graph context.",
        "keywords": ["agentforge", "mission control", "dashboard"],
        "path": "/root/agentforge",
    },
    {
        "id": "system:hermes",
        "label": "Hermes Gateway",
        "summary": "Always-on Hermes runtime orchestrating DV's specialist profiles and messaging channels.",
        "keywords": ["hermes", "gateway", "profiles"],
        "path": str(HERMES_HOME),
    },
    {
        "id": "system:vault",
        "label": "Knowledge Vault",
        "summary": "Canonical markdown knowledge under /root/.hermes/content used as long-form operational memory.",
        "keywords": ["vault", "knowledge", "markdown", "content"],
        "path": str(LIBRARY_ROOT),
    },
    {
        "id": "system:vps",
        "label": "Hostinger VPS",
        "summary": "Ubuntu host running Hermes, AgentForge, n8n, Docker, and DV's migrating client workloads.",
        "keywords": ["vps", "hostinger", "ubuntu"],
        "path": "Hostinger KVM 2",
    },
    {
        "id": "system:n8n",
        "label": "n8n Automation Core",
        "summary": "Self-hosted workflow engine for recurring automation and client-service delivery.",
        "keywords": ["n8n", "automation", "workflow"],
        "path": "/opt/n8n/docker-compose.yml",
    },
    {
        "id": "system:state-db",
        "label": "Hermes State DB",
        "summary": "Session, message, token, and runtime state database used for live dashboard telemetry.",
        "keywords": ["state.db", "sessions", "telemetry"],
        "path": str(STATE_DB),
    },
]


def graph_note_type(rel_path: str, title: str, summary: str) -> str:
    hay = f"{rel_path} {title} {summary}".lower()
    if any(k in hay for k in ["protocol", "spec", "build plan", "architecture"]):
        return "runbook"
    return "note"


def graph_summary(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    for part in parts:
        cleaned = " ".join(line.strip() for line in part.splitlines() if line.strip())
        if not cleaned or cleaned.startswith("#") or cleaned == "---":
            continue
        if cleaned.startswith(">"):
            cleaned = cleaned.lstrip("> ")
        if cleaned.lower().startswith("metadata:"):
            continue
        return cleaned[:220]
    return ""


def graph_automation_description(job: dict) -> str:
    command = str(job.get("command") or "")
    source = str(job.get("source") or "")
    name = str(job.get("name") or job.get("id") or "").strip()
    hay = f"{name} {command} {source}".lower()
    if "cleanup-logs" in hay:
        return "Agent activity log cleanup"
    if "docker image prune" in hay:
        return "Docker image cleanup"
    if "run-parts --report /etc/cron.hourly" in hay:
        return "Hourly platform routines"
    if "run-parts --report /etc/cron.daily" in hay:
        return "Daily platform maintenance"
    if "run-parts --report /etc/cron.weekly" in hay:
        return "Weekly platform maintenance"
    if "run-parts --report /etc/cron.monthly" in hay:
        return "Monthly platform maintenance"
    if "e2scrub" in hay:
        return "Filesystem integrity scrub"
    if "sysstat" in hay or "debian-sa1" in hay:
        return "System telemetry capture"
    if "monarx" in hay or "apt-get install" in hay:
        return "Security agent update"
    if name:
        return name.replace("-", " ").replace("_", " ").strip().title()
    return "Scheduled automation"


def graph_automation_category(job: dict) -> str:
    hay = f"{graph_automation_description(job)} {job.get('command','')} {job.get('source','')}".lower()
    if any(k in hay for k in ["backup", "dump", "archive"]):
        return "backup"
    if any(k in hay for k in ["cleanup", "prune", "tmp", "cache"]):
        return "cleanup"
    if any(k in hay for k in ["security", "monarx"]):
        return "security"
    if any(k in hay for k in ["telemetry", "monitor", "sysstat", "sa1"]):
        return "monitoring"
    if any(k in hay for k in ["hermes", "agentforge"]):
        return "ai"
    return "system"


def graph_data() -> dict:
    nodes = []
    edges = []
    node_ids = set()
    edge_ids = set()

    def add_node(node_id: str, label: str, node_type: str, source: str, summary: str = "", **extra):
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        payload = {
            "id": node_id,
            "label": label,
            "type": node_type,
            "source": source,
            "summary": summary,
            "color": GRAPH_TYPE_COLORS.get(node_type, "#64748B"),
        }
        payload.update(extra)
        nodes.append(payload)

    def add_edge(source_id: str, target_id: str, rel_type: str, reason: str = ""):
        if source_id == target_id:
            return
        key = tuple(sorted((source_id, target_id)) + [rel_type])
        if key in edge_ids or source_id not in node_ids or target_id not in node_ids:
            return
        edge_ids.add(key)
        edges.append({
            "id": f"{source_id}::{target_id}::{rel_type}",
            "source": source_id,
            "target": target_id,
            "type": rel_type,
            "reason": reason,
        })

    for agent_key in ["master", "assistant", "research", "planning", "audit", "dev"]:
        add_node(
            f"agent:{agent_key}",
            agent_key.upper(),
            "agent",
            "ops",
            {
                "master": "Coordinates all specialist agents and delegates execution across the workforce.",
                "assistant": "Produces user-facing responses and polished communication.",
                "research": "Collects and verifies external information.",
                "planning": "Builds plans, decomposition, and sequencing.",
                "audit": "Validates outputs and catches quality issues.",
                "dev": "Implements technical changes and code execution.",
            }.get(agent_key, "Specialist Hermes agent."),
            profile=agent_key,
        )

    for item in PROJECT_GRAPH_NODES:
        add_node(item["id"], item["label"], "project", "ops", item["summary"], path=item.get("path"), keywords=item["keywords"])

    for item in MEMORY_GRAPH_NODES:
        add_node(item["id"], item["label"], "memory", "memory", item["summary"], keywords=item["keywords"])

    for item in SYSTEM_GRAPH_NODES:
        add_node(item["id"], item["label"], "system", "ops", item["summary"], path=item.get("path"), keywords=item["keywords"])

    if LIBRARY_ROOT.exists():
        root = LIBRARY_ROOT.resolve(strict=False)
        for file_path in sorted(LIBRARY_ROOT.rglob("*.md")):
            try:
                real = file_path.resolve(strict=True)
                real.relative_to(root)
                if not real.is_file():
                    continue
                rel = library_rel(real)
                title = markdown_title(real)
                summary = graph_summary(real)
                stat = real.stat()
                add_node(
                    f"vault:{rel}",
                    title,
                    graph_note_type(rel, title, summary),
                    "vault",
                    summary or "Canonical knowledge artifact in the AgentForge vault.",
                    path=rel,
                    agent=library_agent_for(real),
                    modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    size=stat.st_size,
                )
                add_edge(f"vault:{rel}", "system:vault", "documents", "Vault artifact stored in canonical knowledge root.")
                add_edge(f"vault:{rel}", f"agent:{library_agent_for(real)}", "documents", "Artifact belongs to this specialist lane.")
            except Exception:
                continue

    cron = cron_jobs()
    selected = []
    seen = set()
    for job in cron.get("jobs", []):
        desc = graph_automation_description(job)
        cat = graph_automation_category(job)
        key = (desc, cat, job.get("schedule"), job.get("source"))
        if key in seen:
            continue
        owner = "hermes" if str(job.get("label") or job.get("owner") or "").lower().startswith("hermes") else "system"
        if owner == "hermes" and len([x for x in selected if x.get('_owner') == 'hermes']) < 4:
            job = dict(job)
            job["_owner"] = owner
            job["_desc"] = desc
            job["_cat"] = cat
            selected.append(job)
            seen.add(key)
        elif owner == "system" and len([x for x in selected if x.get('_owner') == 'system']) < 4:
            job = dict(job)
            job["_owner"] = owner
            job["_desc"] = desc
            job["_cat"] = cat
            selected.append(job)
            seen.add(key)
        if len(selected) >= 8:
            break

    for idx, job in enumerate(selected, start=1):
        label = job.get("_desc") or graph_automation_description(job)
        node_id = f"automation:{idx}:{label.lower().replace(' ', '-')}"
        add_node(
            node_id,
            label,
            "automation",
            "ops",
            f"{job.get('_owner','system').title()} routine · {job.get('schedule_english') or job.get('schedule') or 'scheduled'}",
            path=job.get("source"),
            schedule=job.get("schedule"),
            owner=job.get("_owner"),
            category=job.get("_cat"),
            command=job.get("command"),
        )
        add_edge(node_id, "system:vps", "supports", "Automation runs on VPS operations surface.")
        add_edge(node_id, "system:agentforge", "supports", "Automation is surfaced inside AgentForge operations.")
        if job.get("_owner") == "hermes":
            add_edge(node_id, "system:hermes", "depends_on", "Hermes-owned automation.")

    base_edges = [
        ("system:agentforge", "system:hermes", "depends_on", "AgentForge visualizes Hermes runtime state."),
        ("system:agentforge", "system:vault", "uses", "Graph and Library read canonical vault markdown."),
        ("system:agentforge", "system:state-db", "uses", "Dashboard reads session and telemetry state."),
        ("system:hermes", "system:vps", "depends_on", "Hermes runs on the Hostinger VPS."),
        ("system:n8n", "system:vps", "depends_on", "n8n is self-hosted on the VPS."),
        ("project:jobforge", "system:vps", "depends_on", "JobForge is migrating to the VPS."),
        ("project:jobforge", "system:agentforge", "related_to", "Mission control sits alongside JobForge operations."),
        ("project:clientforge", "system:agentforge", "related_to", "AgentForge informs ClientForge architecture and QA."),
        ("project:promptforge", "system:hermes", "related_to", "Both rely on multi-agent orchestration patterns."),
        ("project:voltedge", "system:n8n", "uses", "Voltedge client workflows depend on automation."),
        ("project:med-reviewer", "system:vault", "related_to", "Knowledge-centric product aligned with memory workflows."),
        ("memory:jobforge-primary", "project:jobforge", "supports", "Memory preference anchors the graph around JobForge."),
        ("memory:clientforge-flagship", "project:clientforge", "supports", "Flagship positioning memory informs this project."),
        ("memory:contract-first", "project:jobforge", "supports", "JobForge feeds the contract-first path."),
        ("memory:concise-replies", "agent:assistant", "supports", "Communication style maps to assistant outputs."),
    ]
    for edge in base_edges:
        add_edge(*edge)

    for agent_key in ["master", "assistant", "research", "planning", "audit", "dev"]:
        add_edge(f"agent:{agent_key}", "system:hermes", "uses", "Agent profile operates through Hermes.")
        add_edge(f"agent:{agent_key}", "system:agentforge", "related_to", "Agent status is surfaced in Mission Control.")
    add_edge("agent:master", "system:vault", "uses", "Master coordinates against canonical knowledge.")
    add_edge("agent:research", "system:vault", "uses", "Research consumes vault knowledge for context.")
    add_edge("agent:dev", "project:clientforge", "supports", "DEV implements portfolio systems.")
    add_edge("agent:planning", "project:clientforge", "supports", "PLANNING sequences flagship build phases.")
    add_edge("agent:audit", "system:agentforge", "supports", "AUDIT validates dashboard truthfulness and polish.")

    keyword_targets = {}
    for item in PROJECT_GRAPH_NODES:
        for kw in item["keywords"]:
            keyword_targets[kw.lower()] = item["id"]
    for item in SYSTEM_GRAPH_NODES:
        for kw in item["keywords"]:
            keyword_targets[kw.lower()] = item["id"]
    for item in MEMORY_GRAPH_NODES:
        for kw in item["keywords"]:
            keyword_targets.setdefault(kw.lower(), item["id"])

    vault_nodes = [n for n in nodes if n.get("source") == "vault"]
    for node in vault_nodes:
        hay = f"{node.get('label','')} {node.get('path','')} {node.get('summary','')}".lower()
        for kw, target in keyword_targets.items():
            if kw in hay:
                add_edge(node["id"], target, "references", f"Matched keyword: {kw}")

    counts_by_type = {}
    counts_by_source = {}
    for node in nodes:
        counts_by_type[node["type"]] = counts_by_type.get(node["type"], 0) + 1
        counts_by_source[node["source"]] = counts_by_source.get(node["source"], 0) + 1

    return {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "generated_at": utc_now(),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "counts_by_type": counts_by_type,
            "counts_by_source": counts_by_source,
            "sources": ["memory", "vault", "ops"],
            "types": ["project", "note", "runbook", "agent", "system", "automation", "memory"],
            "root": str(LIBRARY_ROOT),
            "read_only": True,
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "HermesMissionControl/1.0"

    def log_message(self, fmt, *args):
        print(f"[{datetime.now().isoformat(timespec='seconds')}] {self.address_string()} {fmt % args}")

    def send_json(self, obj, status=200):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_payload(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        ctype = self.headers.get("Content-Type", "")
        if "application/json" in ctype:
            return json.loads(raw or "{}")
        parsed = parse_qs(raw)
        return {k: v[-1] if v else "" for k, v in parsed.items()}

    def read_multipart_form(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return cgi.FieldStorage(
            fp=io.BytesIO(raw),
            headers=self.headers,
            environ={
                "REQUEST_METHOD": self.command,
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(length),
            },
            keep_blank_values=True,
        )

    def send_binary(self, body: bytes, *, content_type: str = 'application/octet-stream', filename: str = ''):
        payload = body or b''
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        if filename:
            safe_name = filename.replace('\"', '')
            self.send_header("Content-Disposition", f'inline; filename="{safe_name}"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_api_error(self, exc: Exception, *, fallback_boundary: str = 'request_error', fallback_code: str = 'bad_request'):
        status, payload = exception_to_api_error(exc, fallback_boundary=fallback_boundary, fallback_code=fallback_code)
        self.send_json(payload, status)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            index = PROJECT_DIR / "index.html"
            if not index.exists():
                self.send_error(404, "index.html not found")
                return
            body = index.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/snapshot":
            self.send_json(snapshot())
            return
        task_history_match = re.fullmatch(r"/api/tasks/([^/]+)/history", parsed.path)
        task_runs_match = re.fullmatch(r"/api/tasks/([^/]+)/runs", parsed.path)
        task_match = re.fullmatch(r"/api/tasks/([^/]+)", parsed.path)
        task_attachment_match = re.fullmatch(r"/api/task-attachments/([^/]+)", parsed.path)
        task_attachment_content_match = re.fullmatch(r"/api/task-attachments/([^/]+)/content", parsed.path)
        deployment_match = re.fullmatch(r"/api/deployments/([^/]+)", parsed.path)
        run_trace_match = re.fullmatch(r"/api/runs/([^/]+)/trace", parsed.path)
        run_context_match = re.fullmatch(r"/api/runs/([^/]+)/context", parsed.path)
        run_match = re.fullmatch(r"/api/runs/([^/]+)", parsed.path)
        if parsed.path == "/api/board":
            self.send_json({"tasks": board_list()})
            return
        if parsed.path == "/api/tasks":
            self.send_json({"tasks": task_list()})
            return
        if task_history_match:
            try:
                self.send_json(task_history_get(task_history_match.group(1)))
            except Exception as exc:
                self.send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 400)
            return
        if task_runs_match:
            try:
                self.send_json(task_runs_get(task_runs_match.group(1)))
            except Exception as exc:
                self.send_api_error(exc, fallback_boundary='task_runs_failed', fallback_code='task_runs_failed')
            return
        if task_match:
            try:
                self.send_json(task_get(task_match.group(1)))
            except Exception as exc:
                self.send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 400)
            return
        if task_attachment_content_match:
            try:
                attachment = task_attachment_get(task_attachment_content_match.group(1))
                path = task_attachment_absolute_path(attachment.get('storage_path') or attachment.get('storage_rel_path') or '')
                if not path.exists() or not path.is_file():
                    raise FileNotFoundError('attachment content not found')
                self.send_binary(path.read_bytes(), content_type=attachment.get('mime_type') or 'application/octet-stream', filename=attachment.get('filename') or 'attachment')
            except Exception as exc:
                self.send_api_error(exc, fallback_boundary='attachment_content_failed', fallback_code='attachment_content_failed')
            return
        if task_attachment_match:
            try:
                self.send_json({'attachment': task_attachment_get(task_attachment_match.group(1))})
            except Exception as exc:
                self.send_api_error(exc, fallback_boundary='attachment_detail_failed', fallback_code='attachment_detail_failed')
            return
        if parsed.path == "/api/playbooks":
            self.send_json({"playbooks": playbook_list()})
            return
        if parsed.path == "/api/playbooks/get":
            qs = parse_qs(parsed.query)
            try:
                self.send_json(playbook_get((qs.get("id") or [""])[0], (qs.get("slug") or [""])[0]))
            except Exception as exc:
                self.send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 400)
            return
        if parsed.path == "/api/agents":
            self.send_json({"agents": agent_list()})
            return
        if parsed.path == "/api/agents/get":
            qs = parse_qs(parsed.query)
            try:
                self.send_json(agent_get((qs.get("id") or [""])[0], (qs.get("slug") or [""])[0]))
            except Exception as exc:
                self.send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 400)
            return
        if parsed.path == "/api/deployments":
            self.send_json({"deployments": deployment_list()})
            return
        if deployment_match:
            try:
                self.send_json(deployment_get(deployment_match.group(1)))
            except Exception as exc:
                self.send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 400)
            return
        if parsed.path == "/api/runs":
            self.send_json({"runs": run_list()})
            return
        if run_trace_match:
            try:
                self.send_json(run_trace_get(run_trace_match.group(1)))
            except Exception as exc:
                self.send_api_error(exc, fallback_boundary='run_trace_failed', fallback_code='run_trace_failed')
            return
        if run_context_match:
            try:
                self.send_json(run_context_get(run_context_match.group(1)))
            except Exception as exc:
                self.send_api_error(exc, fallback_boundary='run_context_failed', fallback_code='run_context_failed')
            return
        if run_match:
            try:
                self.send_json(run_get(run_match.group(1)))
            except Exception as exc:
                self.send_api_error(exc, fallback_boundary='run_detail_failed', fallback_code='run_detail_failed')
            return
        if parsed.path == "/api/library":
            self.send_json(library_list())
            return
        if parsed.path == "/api/library/get":
            qs = parse_qs(parsed.query)
            try:
                self.send_json(library_get((qs.get("path") or [""])[0]))
            except Exception as exc:
                self.send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 400)
            return
        if parsed.path == "/api/graph":
            self.send_json(graph_data())
            return
        if parsed.path == "/events":
            accept = self.headers.get("Accept", "")
            # SSE is the primary transport. If the frontend falls back to polling,
            # it requests JSON from the same /events endpoint with Accept: application/json.
            if "text/event-stream" not in accept and "application/json" in accept:
                self.send_json(snapshot())
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    payload = json.dumps(snapshot(), default=str)
                    self.wfile.write(f"event: snapshot\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(5)
            except (BrokenPipeError, ConnectionResetError):
                return
        self.send_error(404, "not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/task-attachments/upload":
                form = self.read_multipart_form()
                file_item = form['file'] if 'file' in form else None
                if file_item is None or not getattr(file_item, 'filename', ''):
                    raise ValueError('file is required')
                file_bytes = file_item.file.read() if getattr(file_item, 'file', None) else b''
                draft_token = form.getfirst('draft_token', '') if hasattr(form, 'getfirst') else ''
                task_id = form.getfirst('task_id', '') if hasattr(form, 'getfirst') else ''
                attachment = task_attachment_create(file_bytes, getattr(file_item, 'filename', ''), getattr(file_item, 'type', ''), draft_token=draft_token, task_id=task_id)
                self.send_json({'attachment': attachment}, 201)
                return
            payload = self.read_payload()
            if parsed.path == "/api/board":
                self.send_json({"task": board_create(payload)}, 201)
                return
            if parsed.path == "/api/tasks":
                self.send_json({"task": task_create(payload)}, 201)
                return
            if parsed.path == "/api/tasks/update":
                task_id = (qs.get("id") or [""])[0] or str((payload or {}).get('id') or '')
                self.send_json({"task": task_update(task_id, payload)})
                return
            if parsed.path == "/api/playbooks":
                self.send_json({"playbook": playbook_create(payload)}, 201)
                return
            if parsed.path == "/api/playbooks/update":
                playbook_id = (qs.get("id") or [""])[0]
                self.send_json({"playbook": playbook_update(playbook_id, payload)})
                return
            if parsed.path == "/api/playbooks/delete":
                playbook_id = (qs.get("id") or [""])[0]
                self.send_json(playbook_delete(playbook_id))
                return
            if parsed.path == "/api/agents":
                self.send_json({"agent": agent_create(payload)}, 201)
                return
            if parsed.path == "/api/agents/update":
                agent_id = (qs.get("id") or [""])[0]
                self.send_json({"agent": agent_update(agent_id, payload)})
                return
            if parsed.path == "/api/agents/delete":
                agent_id = (qs.get("id") or [""])[0]
                self.send_json(agent_delete(agent_id))
                return
            if parsed.path == "/api/deployments":
                self.send_json({"deployment": deployment_create(payload)}, 201)
                return
            if parsed.path == "/api/admin/runs/clear-seed":
                self.send_json(runs_cleanup('clear-seed', reseed=bool((payload or {}).get('reseed'))))
                return
            if parsed.path == "/api/admin/runs/clear-test":
                self.send_json(runs_cleanup('clear-test', reseed=bool((payload or {}).get('reseed'))))
                return
            if parsed.path == "/api/admin/runs/reset":
                self.send_json(runs_cleanup('reset', reseed=bool((payload or {}).get('reseed'))))
                return
            if parsed.path == "/api/admin/runs/trace-probe":
                self.send_json(create_trace_probe(payload), 201)
                return
            if parsed.path == "/api/runs/launch":
                try:
                    self.send_json(launch_operator_run(payload), 201)
                except RunLaunchRequestError as exc:
                    self.send_api_error(exc, fallback_boundary='launch_rejected', fallback_code='invalid_launch')
                return
            if parsed.path == "/api/runs":
                self.send_json(create_task_execution_run(str((payload or {}).get('taskId') or (payload or {}).get('task_id') or '').strip(), payload), 201)
                return
            if parsed.path == "/api/runs/update":
                run_id = (qs.get("id") or [""])[0] or str((payload or {}).get('id') or '')
                self.send_json(update_task_execution_run(run_id, payload))
                return
            if parsed.path == "/api/runs/clear":
                scope = str((payload or {}).get('scope') or (qs.get('scope') or [''])[0] or '').strip().lower()
                self.send_json(clear_runs(scope))
                return
            if parsed.path == "/api/runs/delete":
                run_id = (qs.get("id") or [""])[0] or str((payload or {}).get('id') or '')
                self.send_json(delete_run_record(run_id))
                return
            if parsed.path == "/api/board/update":
                task_id = (qs.get("id") or [""])[0]
                self.send_json({"task": board_update(task_id, payload)})
                return
            if parsed.path == "/api/board/delete":
                task_id = (qs.get("id") or [""])[0]
                self.send_json(board_delete(task_id))
                return
            if parsed.path == "/api/library/save":
                self.send_json(library_save(payload))
                return
            self.send_error(404, "not found")
        except Exception as exc:
            self.send_api_error(exc)

    def do_PUT(self):
        parsed = urlparse(self.path)
        task_match = re.fullmatch(r"/api/tasks/([^/]+)", parsed.path)
        task_attachment_match = re.fullmatch(r"/api/task-attachments/([^/]+)", parsed.path)
        deployment_match = re.fullmatch(r"/api/deployments/([^/]+)", parsed.path)
        run_match = re.fullmatch(r"/api/runs/([^/]+)", parsed.path)
        if not task_match and not task_attachment_match and not deployment_match and not run_match:
            self.send_error(404, "not found")
            return
        try:
            payload = self.read_payload()
            if task_match:
                self.send_json({"task": task_update(task_match.group(1), payload)})
                return
            if run_match:
                self.send_json(update_task_execution_run(run_match.group(1), payload))
                return
            self.send_json({"deployment": deployment_update(deployment_match.group(1), payload)})
        except Exception as exc:
            self.send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 400)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        task_match = re.fullmatch(r"/api/tasks/([^/]+)", parsed.path)
        deployment_match = re.fullmatch(r"/api/deployments/([^/]+)", parsed.path)
        if not task_match and not deployment_match:
            self.send_error(404, "not found")
            return
        try:
            if task_match:
                self.send_json(task_delete(task_match.group(1)))
                return
            if task_attachment_match:
                self.send_json(task_attachment_delete(task_attachment_match.group(1)))
                return
            self.send_json(deployment_delete(deployment_match.group(1)))
        except Exception as exc:
            self.send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 400)


def main():
    init_board()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Hermes Mission Control serving on http://{HOST}:{PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
