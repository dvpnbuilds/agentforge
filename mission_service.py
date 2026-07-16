"""Reset B mission persistence and real Hermes Kanban synchronization."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_kanban_adapter import HermesKanbanAdapter


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    return {}


def json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("runs", "tasks", "items"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def extract_urls(text: str) -> list[str]:
    seen = set()
    urls = []
    for match in re.findall(r"https?://[^\s<>\]\[\)\(\"']+", str(text or "")):
        clean = match.rstrip(".,;:!?")
        if clean and clean not in seen:
            seen.add(clean)
            urls.append(clean)
    return urls[:50]


class MissionService:
    PROFILE = "research"
    BOARD = "agentforge"

    def __init__(self, db_path: str | Path, *, adapter: HermesKanbanAdapter | None = None) -> None:
        self.db_path = Path(db_path)
        self.adapter = adapter or HermesKanbanAdapter()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS missions (
                  id TEXT PRIMARY KEY,
                  idempotency_key TEXT NOT NULL UNIQUE,
                  desired_outcome TEXT NOT NULL,
                  success_criteria TEXT NOT NULL,
                  context TEXT NOT NULL DEFAULT '',
                  profile TEXT NOT NULL DEFAULT 'research',
                  state TEXT NOT NULL DEFAULT 'queued',
                  hermes_board TEXT NOT NULL DEFAULT 'agentforge',
                  hermes_task_id TEXT NOT NULL DEFAULT '',
                  operator_message TEXT NOT NULL DEFAULT '',
                  last_synced_at TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mission_steps (
                  id TEXT PRIMARY KEY,
                  mission_id TEXT NOT NULL,
                  step_key TEXT NOT NULL,
                  profile TEXT NOT NULL,
                  responsibility TEXT NOT NULL,
                  expected_output TEXT NOT NULL,
                  hermes_board TEXT NOT NULL,
                  hermes_task_id TEXT NOT NULL DEFAULT '',
                  idempotency_key TEXT NOT NULL UNIQUE,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(mission_id, step_key),
                  FOREIGN KEY (mission_id) REFERENCES missions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS mission_artifacts (
                  id TEXT PRIMARY KEY,
                  mission_id TEXT NOT NULL,
                  mission_step_id TEXT NOT NULL,
                  hermes_task_id TEXT NOT NULL,
                  hermes_run_id TEXT NOT NULL DEFAULT '',
                  worker_profile TEXT NOT NULL,
                  title TEXT NOT NULL,
                  content TEXT NOT NULL,
                  sources_json TEXT NOT NULL DEFAULT '[]',
                  provenance_json TEXT NOT NULL DEFAULT '{}',
                  review_status TEXT NOT NULL DEFAULT 'pending_review',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(mission_id, hermes_task_id),
                  FOREIGN KEY (mission_id) REFERENCES missions(id) ON DELETE CASCADE,
                  FOREIGN KEY (mission_step_id) REFERENCES mission_steps(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS mission_reviews (
                  id TEXT PRIMARY KEY,
                  mission_id TEXT NOT NULL,
                  artifact_id TEXT NOT NULL,
                  action TEXT NOT NULL,
                  note TEXT NOT NULL DEFAULT '',
                  reviewer TEXT NOT NULL DEFAULT 'operator',
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (mission_id) REFERENCES missions(id) ON DELETE CASCADE,
                  FOREIGN KEY (artifact_id) REFERENCES mission_artifacts(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_missions_state ON missions(state, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_mission_artifacts_mission ON mission_artifacts(mission_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_mission_reviews_mission ON mission_reviews(mission_id, created_at DESC);
                """
            )

    @staticmethod
    def _idempotency_key(payload: dict) -> str:
        explicit = str(payload.get("idempotency_key") or payload.get("idempotencyKey") or "").strip()
        if explicit:
            if len(explicit) > 200:
                raise ValueError("idempotency key must be at most 200 characters")
            return explicit
        basis = "\n".join(
            str(payload.get(key) or "").strip()
            for key in ("desired_outcome", "success_criteria", "context")
        )
        return "auto:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def create_mission(self, payload: dict | None) -> dict:
        payload = dict(payload or {})
        desired_outcome = str(payload.get("desired_outcome") or payload.get("desiredOutcome") or "").strip()
        success_criteria = str(payload.get("success_criteria") or payload.get("successCriteria") or "").strip()
        context = str(payload.get("context") or "").strip()
        profile = str(payload.get("profile") or self.PROFILE).strip().lower()
        if not desired_outcome:
            raise ValueError("desired outcome is required")
        if not success_criteria:
            raise ValueError("success criteria are required")
        if len(desired_outcome) > 2000 or len(success_criteria) > 4000 or len(context) > 12000:
            raise ValueError("mission input exceeds Reset B safety limits")
        if profile != self.PROFILE:
            raise ValueError("Reset B supports only the research profile")
        idempotency_key = self._idempotency_key(payload)
        with self.connect() as conn:
            existing = conn.execute("SELECT id FROM missions WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                return self.get_mission(existing["id"])
            mission_id = uuid.uuid4().hex
            step_id = uuid.uuid4().hex
            now = utc_now()
            step_key = "research-proof"
            hermes_key = f"agentforge:{mission_id}:{step_key}:1"
            conn.execute(
                "INSERT INTO missions (id,idempotency_key,desired_outcome,success_criteria,context,profile,state,hermes_board,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (mission_id, idempotency_key, desired_outcome, success_criteria, context, profile, "dispatching", self.BOARD, now, now),
            )
            conn.execute(
                "INSERT INTO mission_steps (id,mission_id,step_key,profile,responsibility,expected_output,hermes_board,idempotency_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (step_id, mission_id, step_key, profile, "Research the requested outcome using real web/tool evidence.", success_criteria, self.BOARD, hermes_key, now, now),
            )
            conn.commit()
        body = (
            "AgentForge Reset B real execution proof.\n\n"
            f"Desired outcome:\n{desired_outcome}\n\n"
            f"Success criteria:\n{success_criteria}\n\n"
            f"Relevant context:\n{context or 'No extra context supplied.'}\n\n"
            "Execution requirements:\n"
            "- Use at least one real web or research tool action.\n"
            "- Return source URLs with the researched findings.\n"
            "- Do not invent missing information; block with a specific reason if access or context is missing.\n"
            "- Finish by calling kanban_complete with the complete user-facing research artifact in result and a concise structured summary."
        )
        try:
            task = self.adapter.create_task(
                title=f"Research proof: {desired_outcome[:180]}",
                body=body,
                assignee=profile,
                idempotency_key=hermes_key,
            )
            task_id = str(task.get("id") or "").strip()
            with self.connect() as conn:
                now = utc_now()
                conn.execute("UPDATE missions SET state='queued', hermes_task_id=?, operator_message='', updated_at=? WHERE id=?", (task_id, now, mission_id))
                conn.execute("UPDATE mission_steps SET hermes_task_id=?, updated_at=? WHERE id=?", (task_id, now, step_id))
                conn.commit()
        except Exception as exc:
            with self.connect() as conn:
                conn.execute("UPDATE missions SET state='failed', operator_message=?, updated_at=? WHERE id=?", (str(exc)[:2000], utc_now(), mission_id))
                conn.commit()
            raise
        return self.get_mission(mission_id)

    @staticmethod
    def _task_from_show(payload: dict) -> dict:
        candidate = payload.get("task") if isinstance(payload, dict) else None
        return json_object(candidate) or json_object(payload)

    @staticmethod
    def _latest_run(runs_payload: Any) -> dict:
        runs = json_list(runs_payload)
        if not runs:
            return {}
        return json_object(runs[-1] if str(runs[-1].get("started_at") or runs[-1].get("created_at") or "") >= str(runs[0].get("started_at") or runs[0].get("created_at") or "") else runs[0])

    @staticmethod
    def _artifact_content(task: dict, run: dict) -> str:
        for key in ("result", "result_text", "result_summary", "completion_summary", "output"):
            value = task.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("result", "summary", "result_summary"):
            value = run.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _block_reason(show_payload: dict, task: dict) -> str:
        direct = str(task.get("blocked_reason") or task.get("block_reason") or task.get("reason") or "").strip()
        if direct:
            return direct
        comments = show_payload.get("comments") if isinstance(show_payload, dict) else []
        if isinstance(comments, list):
            for comment in reversed(comments):
                body = str(json_object(comment).get("body") or "").strip()
                if body:
                    return body.removeprefix("BLOCK: ").strip()
        events = show_payload.get("events") if isinstance(show_payload, dict) else []
        if isinstance(events, list):
            for event in reversed(events):
                payload = json_object(json_object(event).get("payload"))
                reason = str(payload.get("reason") or payload.get("error") or "").strip()
                if reason:
                    return reason
        return ""

    def sync_mission(self, mission_id: str) -> dict:
        mission = self.get_mission(mission_id)
        task_id = str(mission.get("hermes_task_id") or "")
        if not task_id:
            return mission
        show_payload = self.adapter.show_task(task_id)
        runs_payload = self.adapter.task_runs(task_id)
        task = self._task_from_show(show_payload)
        latest_run = self._latest_run(runs_payload)
        status = str(task.get("status") or "").strip().lower()
        block_reason = self._block_reason(show_payload, task)
        if status == "blocked":
            state = "needs_input"
            operator_message = block_reason or "Research worker is blocked and needs operator input."
        elif status in {"done", "review"}:
            content = self._artifact_content(task, latest_run)
            if content:
                self._upsert_artifact(mission, content, task, latest_run, show_payload, runs_payload)
                existing_review_status = str((mission.get("artifacts") or [{}])[0].get("review_status") or "") if mission.get("artifacts") else ""
                if existing_review_status == "approved":
                    state = "completed"
                    operator_message = "Artifact approved by human."
                elif existing_review_status == "revision_requested":
                    state = "revision"
                    operator_message = "Human requested revision on the real artifact."
                else:
                    state = "needs_review"
                    operator_message = "Real Hermes research artifact is ready for human review."
            else:
                state = "failed"
                operator_message = "Hermes task completed without a real result artifact."
        elif status == "running":
            state = "running"
            operator_message = "Research profile is executing through Hermes Kanban."
        elif status in {"todo", "ready", "triage", "scheduled", ""}:
            state = "queued"
            operator_message = "Mission is queued on Hermes Kanban."
        else:
            state = "failed"
            operator_message = f"Hermes task entered unsupported state: {status}"
        with self.connect() as conn:
            now = utc_now()
            conn.execute("UPDATE missions SET state=?, operator_message=?, last_synced_at=?, updated_at=? WHERE id=?", (state, operator_message, now, now, mission_id))
            conn.commit()
        return self.get_mission(mission_id)

    def _upsert_artifact(self, mission: dict, content: str, task: dict, run: dict, show_payload: dict, runs_payload: Any) -> None:
        with self.connect() as conn:
            step = conn.execute("SELECT * FROM mission_steps WHERE mission_id=? ORDER BY created_at LIMIT 1", (mission["id"],)).fetchone()
            if not step:
                raise RuntimeError("mission step mapping is missing")
            existing = conn.execute("SELECT id FROM mission_artifacts WHERE mission_id=? AND hermes_task_id=?", (mission["id"], mission["hermes_task_id"])).fetchone()
            now = utc_now()
            artifact_id = existing["id"] if existing else uuid.uuid4().hex
            run_id = str(run.get("id") or run.get("run_id") or "")
            provenance = {
                "transport": "hermes kanban CLI --json",
                "board": self.BOARD,
                "task_id": mission["hermes_task_id"],
                "run_id": run_id,
                "worker_profile": str(run.get("profile") or run.get("assignee") or task.get("assignee") or self.PROFILE),
                "task_status": task.get("status"),
                "run_outcome": run.get("outcome") or run.get("status"),
                "tool_backed": True,
            }
            values = (
                artifact_id, mission["id"], step["id"], mission["hermes_task_id"], run_id,
                provenance["worker_profile"], f"Research artifact: {mission['desired_outcome'][:160]}", content,
                json.dumps(extract_urls(content)), json.dumps(provenance), "pending_review", now, now,
            )
            conn.execute(
                """INSERT INTO mission_artifacts (id,mission_id,mission_step_id,hermes_task_id,hermes_run_id,worker_profile,title,content,sources_json,provenance_json,review_status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(mission_id,hermes_task_id) DO UPDATE SET hermes_run_id=excluded.hermes_run_id,worker_profile=excluded.worker_profile,title=excluded.title,content=excluded.content,sources_json=excluded.sources_json,provenance_json=excluded.provenance_json,updated_at=excluded.updated_at""",
                values,
            )
            conn.commit()

    def review_mission(self, mission_id: str, payload: dict | None) -> dict:
        payload = dict(payload or {})
        action = str(payload.get("action") or "").strip().lower().replace("-", "_")
        if action not in {"approve", "request_revision"}:
            raise ValueError("action must be approve or request_revision")
        note = str(payload.get("note") or "").strip()
        reviewer = str(payload.get("reviewer") or "operator").strip()[:120] or "operator"
        with self.connect() as conn:
            artifact = conn.execute("SELECT * FROM mission_artifacts WHERE mission_id=? ORDER BY updated_at DESC LIMIT 1", (mission_id,)).fetchone()
            if not artifact:
                raise ValueError("real mission artifact is required before review")
            now = utc_now()
            review_status = "approved" if action == "approve" else "revision_requested"
            mission_state = "completed" if action == "approve" else "revision"
            conn.execute("UPDATE mission_artifacts SET review_status=?, updated_at=? WHERE id=?", (review_status, now, artifact["id"]))
            conn.execute("INSERT INTO mission_reviews (id,mission_id,artifact_id,action,note,reviewer,created_at) VALUES (?,?,?,?,?,?,?)", (uuid.uuid4().hex, mission_id, artifact["id"], action, note, reviewer, now))
            conn.execute("UPDATE missions SET state=?, operator_message=?, updated_at=? WHERE id=?", (mission_state, "Artifact approved by human." if action == "approve" else "Human requested revision on the real artifact.", now, mission_id))
            conn.commit()
        self.adapter.comment(str(artifact["hermes_task_id"]), f"AgentForge human review: {action.replace('_', ' ')}. {note}".strip())
        return self.get_mission(mission_id)

    def list_missions(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id FROM missions ORDER BY updated_at DESC, created_at DESC").fetchall()
        return [self.get_mission(row["id"]) for row in rows]

    def get_mission(self, mission_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM missions WHERE id=?", (str(mission_id or ""),)).fetchone()
            if not row:
                raise KeyError("mission not found")
            mission = dict(row)
            steps = [dict(item) for item in conn.execute("SELECT * FROM mission_steps WHERE mission_id=? ORDER BY created_at", (mission_id,)).fetchall()]
            artifacts = []
            for item in conn.execute("SELECT * FROM mission_artifacts WHERE mission_id=? ORDER BY updated_at DESC", (mission_id,)).fetchall():
                artifact = dict(item)
                artifact["sources"] = json.loads(artifact.pop("sources_json") or "[]")
                artifact["provenance"] = json.loads(artifact.pop("provenance_json") or "{}")
                artifacts.append(artifact)
            reviews = [dict(item) for item in conn.execute("SELECT * FROM mission_reviews WHERE mission_id=? ORDER BY created_at DESC", (mission_id,)).fetchall()]
        mission["steps"] = steps
        mission["artifacts"] = artifacts
        mission["reviews"] = reviews
        return mission
