"""AgentForge mission persistence over real Hermes Kanban execution truth.

Reset B retains the research proof path. Reset C adds a real planning-profile
proposal flow without dispatching downstream execution steps.
"""
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
    return value if isinstance(value, dict) else {}


def json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("runs", "tasks", "items"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def extract_urls(text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in re.findall(r"https?://[^\s<>\]\[\)\(\"']+", str(text or "")):
        clean = match.rstrip(".,;:!?")
        if clean and clean not in seen:
            seen.add(clean)
            urls.append(clean)
    return urls[:50]


class PlanValidationError(ValueError):
    """Planner result is readable but does not satisfy the Reset C contract."""


class MissionNotFoundError(LookupError):
    """Requested AgentForge mission does not exist."""


class MissionService:
    DEFAULT_PROFILE = "planning"
    RESEARCH_PROFILE = "research"
    PLANNING_PROFILE = "planning"
    BOARD = "agentforge"
    ALLOWED_PLAN_PROFILES = frozenset({"assistant", "research", "planning", "dev", "audit"})
    ALLOWED_PLAN_TOOLS = frozenset({"none", "web", "browser", "terminal", "file", "github"})
    ALLOWED_PRIORITIES = frozenset({"low", "medium", "high", "urgent"})

    def __init__(self, db_path: str | Path, *, adapter: Any | None = None) -> None:
        self.db_path = Path(db_path)
        self.adapter = adapter or HermesKanbanAdapter()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

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
                  profile TEXT NOT NULL DEFAULT 'planning',
                  state TEXT NOT NULL DEFAULT 'planning',
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
                CREATE TABLE IF NOT EXISTS execution_plans (
                  id TEXT PRIMARY KEY,
                  mission_id TEXT NOT NULL,
                  version INTEGER NOT NULL,
                  status TEXT NOT NULL DEFAULT 'proposed',
                  rationale TEXT NOT NULL,
                  final_deliverable TEXT NOT NULL,
                  plan_json TEXT NOT NULL,
                  raw_planner_output TEXT NOT NULL,
                  planner_task_id TEXT NOT NULL,
                  planner_run_id TEXT NOT NULL DEFAULT '',
                  planner_profile TEXT NOT NULL DEFAULT 'planning',
                  revision_feedback TEXT NOT NULL DEFAULT '',
                  reviewer TEXT NOT NULL DEFAULT '',
                  reviewed_at TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(mission_id, version),
                  FOREIGN KEY (mission_id) REFERENCES missions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS mission_attachments (
                  attachment_id TEXT PRIMARY KEY,
                  mission_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY (mission_id) REFERENCES missions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_missions_state ON missions(state, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_mission_artifacts_mission ON mission_artifacts(mission_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_mission_reviews_mission ON mission_reviews(mission_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_execution_plans_mission ON execution_plans(mission_id, version DESC);
                CREATE INDEX IF NOT EXISTS idx_mission_attachments_mission ON mission_attachments(mission_id);
                """
            )
            self._ensure_columns(
                conn,
                "missions",
                {
                    "priority": "TEXT NOT NULL DEFAULT 'medium'",
                    "deadline": "TEXT NOT NULL DEFAULT ''",
                    "attachments_json": "TEXT NOT NULL DEFAULT '[]'",
                    "planning_version": "INTEGER NOT NULL DEFAULT 0",
                    "plan_status": "TEXT NOT NULL DEFAULT ''",
                },
            )
            self._ensure_columns(
                conn,
                "execution_plans",
                {"capabilities_json": "TEXT NOT NULL DEFAULT '{}'"},
            )
            for row in conn.execute("SELECT id,attachments_json,created_at FROM missions WHERE attachments_json <> '[]'").fetchall():
                try:
                    attachments = json.loads(str(row["attachments_json"] or "[]"))
                except json.JSONDecodeError:
                    attachments = []
                for attachment in attachments if isinstance(attachments, list) else []:
                    attachment_id = str(json_object(attachment).get("id") or "").strip()
                    if attachment_id:
                        conn.execute(
                            "INSERT OR IGNORE INTO mission_attachments (attachment_id,mission_id,created_at) VALUES (?,?,?)",
                            (attachment_id, row["id"], row["created_at"]),
                        )
            conn.commit()

    @staticmethod
    def _idempotency_key(payload: dict) -> str:
        explicit = str(payload.get("idempotency_key") or payload.get("idempotencyKey") or "").strip()
        if explicit:
            if len(explicit) > 200:
                raise ValueError("idempotency key must be at most 200 characters")
            return explicit
        basis = "\n".join(
            str(payload.get(key) or "").strip()
            for key in ("desired_outcome", "success_criteria", "context", "priority", "deadline", "profile")
        )
        return "auto:" + hashlib.sha256(basis.encode("utf-8")).hexdigest()

    @staticmethod
    def _payload_list(payload: dict, snake: str, camel: str) -> list[str]:
        value = payload.get(snake)
        if value is None:
            value = payload.get(camel)
        if not isinstance(value, list):
            return []
        return [str(item or "").strip() for item in value if str(item or "").strip()]

    def _resolve_attachments(self, conn: sqlite3.Connection, payload: dict, mission_id: str) -> list[dict]:
        attachment_ids = self._payload_list(payload, "attachment_ids", "attachmentIds")
        if not attachment_ids:
            return []
        if len(attachment_ids) > 10 or len(set(attachment_ids)) != len(attachment_ids):
            raise ValueError("missions support at most 10 unique attachments")
        draft_token = str(payload.get("attachment_draft_token") or payload.get("attachmentDraftToken") or "").strip()
        if not draft_token:
            raise ValueError("attachment draft token is required")
        table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_attachments'").fetchone()
        if not table:
            raise ValueError("attachment storage is unavailable")
        marks = ",".join("?" for _ in attachment_ids)
        rows = conn.execute(f"SELECT * FROM task_attachments WHERE id IN ({marks})", attachment_ids).fetchall()
        found = {str(row["id"]): row for row in rows}
        missing = [item for item in attachment_ids if item not in found]
        if missing:
            raise ValueError(f"unknown attachment IDs: {', '.join(missing)}")
        upload_root = (self.db_path.parent / "task_uploads").resolve()
        attachments: list[dict] = []
        for attachment_id in attachment_ids:
            row = found[attachment_id]
            if str(row["task_id"] or "").strip():
                raise ValueError(f"attachment belongs to another task: {row['filename']}")
            if str(row["draft_token"] or "") != draft_token:
                raise ValueError(f"attachment draft token mismatch: {row['filename']}")
            storage_rel_path = Path(str(row["storage_rel_path"] or ""))
            absolute_path = (
                self.db_path.parent / storage_rel_path
                if storage_rel_path.parts and storage_rel_path.parts[0] == "task_uploads"
                else self.db_path.parent / "task_uploads" / storage_rel_path
            ).resolve()
            if not absolute_path.is_relative_to(upload_root) or not absolute_path.is_file():
                raise ValueError(f"attachment path is unavailable: {row['filename']}")
            attachments.append(
                {
                    "id": attachment_id,
                    "filename": str(row["filename"] or "attachment"),
                    "mime_type": str(row["mime_type"] or ""),
                    "size_bytes": int(row["size_bytes"] or 0),
                    "path": str(absolute_path),
                }
            )
        conn.execute(
            f"UPDATE task_attachments SET draft_token=?, updated_at=? WHERE id IN ({marks})",
            [f"mission:{mission_id}", utc_now(), *attachment_ids],
        )
        return attachments

    def _validated_mission_attachments(self, mission: dict) -> list[dict]:
        attachments = mission.get("attachments") or []
        if not attachments:
            return []
        with self.connect() as conn:
            for item in attachments:
                attachment_id = str(json_object(item).get("id") or "").strip()
                owner = conn.execute(
                    "SELECT 1 FROM mission_attachments WHERE attachment_id=? AND mission_id=?",
                    (attachment_id, mission["id"]),
                ).fetchone()
                row = conn.execute("SELECT storage_rel_path FROM task_attachments WHERE id=?", (attachment_id,)).fetchone()
                if not owner or not row:
                    raise ValueError(f"mission attachment is unavailable: {attachment_id or 'missing'}")
                upload_root = (self.db_path.parent / "task_uploads").resolve()
                rel = Path(str(row["storage_rel_path"] or ""))
                path = (self.db_path.parent / rel if rel.parts and rel.parts[0] == "task_uploads" else upload_root / rel).resolve()
                if not path.is_relative_to(upload_root) or not path.is_file():
                    raise ValueError(f"attachment path is unavailable: {json_object(item).get('filename') or attachment_id}")
        return attachments

    def create_mission(self, payload: dict | None) -> dict:
        payload = dict(payload or {})
        desired_outcome = str(payload.get("desired_outcome") or payload.get("desiredOutcome") or "").strip()
        success_criteria = str(payload.get("success_criteria") or payload.get("successCriteria") or "").strip()
        context = str(payload.get("context") or "").strip()
        profile = str(payload.get("profile") or self.DEFAULT_PROFILE).strip().lower()
        priority = str(payload.get("priority") or "medium").strip().lower()
        deadline = str(payload.get("deadline") or "").strip()
        if not desired_outcome:
            raise ValueError("desired outcome is required")
        if not success_criteria:
            raise ValueError("success criteria are required")
        if len(desired_outcome) > 2000 or len(success_criteria) > 4000 or len(context) > 8000:
            raise ValueError("mission input exceeds safety limits")
        if priority not in self.ALLOWED_PRIORITIES:
            raise ValueError("priority must be low, medium, high, or urgent")
        if len(deadline) > 100:
            raise ValueError("deadline is too long")
        if profile not in {self.DEFAULT_PROFILE, self.RESEARCH_PROFILE}:
            raise ValueError("Create Work supports planning; Reset B compatibility supports research")
        idempotency_key = self._idempotency_key(payload)
        with self.connect() as conn:
            existing = conn.execute("SELECT id FROM missions WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
            if existing:
                return self.get_mission(existing["id"])
            mission_id = uuid.uuid4().hex
            now = utc_now()
            attachments = self._resolve_attachments(conn, payload, mission_id)
            planning_version = 1 if profile == self.PLANNING_PROFILE else 0
            plan_status = "planning" if profile == self.PLANNING_PROFILE else ""
            conn.execute(
                """INSERT INTO missions
                (id,idempotency_key,desired_outcome,success_criteria,context,profile,state,hermes_board,priority,deadline,attachments_json,planning_version,plan_status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    mission_id,
                    idempotency_key,
                    desired_outcome,
                    success_criteria,
                    context,
                    profile,
                    "dispatching",
                    self.BOARD,
                    priority,
                    deadline,
                    json.dumps(attachments),
                    planning_version,
                    plan_status,
                    now,
                    now,
                ),
            )
            conn.executemany(
                "INSERT INTO mission_attachments (attachment_id,mission_id,created_at) VALUES (?,?,?)",
                [(str(item["id"]), mission_id, now) for item in attachments],
            )
            conn.commit()
        try:
            if profile == self.PLANNING_PROFILE:
                self._dispatch_planning_task(mission_id, version=1)
            else:
                self._dispatch_research_task(mission_id)
        except Exception as exc:
            with self.connect() as conn:
                conn.execute(
                    "UPDATE missions SET state='failed', plan_status=CASE WHEN profile='planning' THEN 'dispatch_failed' ELSE plan_status END, operator_message=?, updated_at=? WHERE id=?",
                    (str(exc)[:2000], utc_now(), mission_id),
                )
                conn.commit()
            raise
        return self.get_mission(mission_id)

    def _dispatch_research_task(self, mission_id: str) -> None:
        mission = self.get_mission(mission_id)
        step_id = uuid.uuid4().hex
        now = utc_now()
        step_key = "research-proof"
        hermes_key = f"agentforge:{mission_id}:{step_key}:1"
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO mission_steps (id,mission_id,step_key,profile,responsibility,expected_output,hermes_board,idempotency_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    step_id,
                    mission_id,
                    step_key,
                    self.RESEARCH_PROFILE,
                    "Research the requested outcome using real web/tool evidence.",
                    mission["success_criteria"],
                    self.BOARD,
                    hermes_key,
                    now,
                    now,
                ),
            )
            conn.commit()
        body = (
            "AgentForge Reset B real execution proof.\n\n"
            f"Desired outcome:\n{mission['desired_outcome']}\n\n"
            f"Success criteria:\n{mission['success_criteria']}\n\n"
            f"Relevant context:\n{mission['context'] or 'No extra context supplied.'}\n\n"
            "Execution requirements:\n"
            "- Use at least one real web or research tool action.\n"
            "- Return source URLs with the researched findings.\n"
            "- Do not invent missing information; block with a specific reason if access or context is missing.\n"
            "- Finish by calling kanban_complete with the complete user-facing research artifact in result and a concise structured summary."
        )
        task = self.adapter.create_task(
            title=f"Research proof: {mission['desired_outcome'][:180]}",
            body=body,
            assignee=self.RESEARCH_PROFILE,
            idempotency_key=hermes_key,
        )
        self._save_dispatched_task(mission_id, step_id, str(task.get("id") or ""), "queued", "")

    @staticmethod
    def _plan_schema_example() -> str:
        return json.dumps(
            {
                "rationale": "Why this specialist sequence is appropriate.",
                "final_deliverable": "The exact final deliverable.",
                "steps": [
                    {
                        "key": "research",
                        "title": "Research evidence",
                        "profile": "research",
                        "responsibility": "One narrowly scoped responsibility.",
                        "expected_output": "A concrete handoff artifact.",
                        "dependencies": [],
                        "evidence_requirements": ["Primary sources with URLs."],
                        "tool_requirements": ["web"],
                    }
                ],
                "gates": [
                    {"type": "human", "description": "Human accepts the plan before execution."}
                ],
            },
            indent=2,
        )

    def _dispatch_planning_task(self, mission_id: str, *, version: int, feedback: str = "") -> None:
        mission = self.get_mission(mission_id)
        now = utc_now()
        step_key = f"planning-v{version}"
        hermes_key = f"agentforge:{mission_id}:{step_key}:1"
        responsibility = "Design and validate the specialist workflow proposal. Do not execute the downstream work."
        attachments = self._validated_mission_attachments(mission)
        with self.connect() as conn:
            existing = conn.execute("SELECT id FROM mission_steps WHERE mission_id=? AND step_key=?", (mission_id, step_key)).fetchone()
            step_id = str(existing["id"]) if existing else uuid.uuid4().hex
            if not existing:
                conn.execute(
                    "INSERT INTO mission_steps (id,mission_id,step_key,profile,responsibility,expected_output,hermes_board,idempotency_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (step_id, mission_id, step_key, self.PLANNING_PROFILE, responsibility,
                     "One strict JSON workflow proposal that passes the AgentForge Reset C schema.",
                     self.BOARD, hermes_key, now, now),
                )
            conn.commit()
        attachment_lines = "\n".join(f"- {item['filename']}: {item['path']}" for item in attachments) or "- None"
        revision_section = f"\nRevision feedback from DV:\n{feedback}\n" if feedback else ""
        body = (
            f"AgentForge Reset C planning task, plan version {version}.\n\n"
            "You are PLANNING. Design the workflow only. Do not perform downstream research, writing, development, or audit work.\n"
            "Do not create or dispatch any additional Kanban tasks.\n\n"
            f"Desired outcome:\n{mission['desired_outcome']}\n\n"
            f"Success criteria / expected deliverable:\n{mission['success_criteria']}\n\n"
            f"Relevant context and links:\n{mission['context'] or 'No extra context supplied.'}\n\n"
            f"Priority: {mission['priority']}\nDeadline: {mission['deadline'] or 'Not specified'}\n\n"
            f"Readable attachments:\n{attachment_lines}\n"
            f"{revision_section}\n"
            "Return ONLY one JSON object. No markdown fence or commentary. Use exactly this shape:\n"
            f"{self._plan_schema_example()}\n\n"
            "Validation rules:\n"
            f"- profile must be one of: {', '.join(sorted(self.ALLOWED_PLAN_PROFILES))}.\n"
            f"- tool_requirements values must be one of: {', '.join(sorted(self.ALLOWED_PLAN_TOOLS))}.\n"
            "- every step key must be unique; dependencies must reference step keys and may not form cycles.\n"
            "- every responsibility and expected output must be specific.\n"
            "- include at least one human gate. Add an audit stage/gate when factual, technical, or external-facing quality requires it.\n"
            "- do not invent access or inputs; describe assumptions in rationale and keep missing input visible.\n"
            "Finish by calling kanban_complete with this JSON object as the complete result."
        )
        task = self.adapter.create_task(
            title=f"Plan v{version}: {mission['desired_outcome'][:180]}",
            body=body,
            assignee=self.PLANNING_PROFILE,
            idempotency_key=hermes_key,
        )
        self._save_dispatched_task(
            mission_id,
            step_id,
            str(task.get("id") or ""),
            "planning",
            f"PLANNING is preparing workflow proposal v{version} through Hermes Kanban.",
        )

    def _save_dispatched_task(self, mission_id: str, step_id: str, task_id: str, state: str, message: str) -> None:
        if not task_id:
            raise RuntimeError("Hermes task creation returned no task ID")
        with self.connect() as conn:
            now = utc_now()
            conn.execute(
                "UPDATE missions SET state=?, hermes_task_id=?, operator_message=?, updated_at=? WHERE id=?",
                (state, task_id, message, now, mission_id),
            )
            conn.execute("UPDATE mission_steps SET hermes_task_id=?, updated_at=? WHERE id=?", (task_id, now, step_id))
            conn.commit()

    @staticmethod
    def _task_from_show(payload: dict) -> dict:
        candidate = payload.get("task") if isinstance(payload, dict) else None
        return json_object(candidate) or json_object(payload)

    @staticmethod
    def _latest_run(runs_payload: Any) -> dict:
        runs = json_list(runs_payload)
        if not runs:
            return {}
        return json_object(
            runs[-1]
            if str(runs[-1].get("started_at") or runs[-1].get("created_at") or "")
            >= str(runs[0].get("started_at") or runs[0].get("created_at") or "")
            else runs[0]
        )

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
                event_payload = json_object(json_object(event).get("payload"))
                reason = str(event_payload.get("reason") or event_payload.get("error") or "").strip()
                if reason:
                    return reason
        return ""

    @staticmethod
    def _planner_json(raw: str) -> dict:
        text = str(raw or "").strip()
        fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
        if fence:
            text = fence.group(1).strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PlanValidationError(f"planner result is not valid JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise PlanValidationError("planner result must be one JSON object")
        return value

    def validate_plan(self, raw: str) -> dict:
        plan = self._planner_json(raw)
        installed_profiles = set(self.adapter.installed_profiles())
        available_profiles = self.ALLOWED_PLAN_PROFILES & installed_profiles
        available_tools = self.ALLOWED_PLAN_TOOLS & set(self.adapter.available_plan_tools())
        required = {"rationale", "final_deliverable", "steps", "gates"}
        unknown = set(plan) - required
        missing = required - set(plan)
        if missing:
            raise PlanValidationError(f"plan is missing fields: {', '.join(sorted(missing))}")
        if unknown:
            raise PlanValidationError(f"plan has unsupported fields: {', '.join(sorted(unknown))}")
        for key in ("rationale", "final_deliverable"):
            if not isinstance(plan[key], str) or not plan[key].strip() or len(plan[key]) > 4000:
                raise PlanValidationError(f"{key} must be a non-empty string up to 4000 characters")
            plan[key] = plan[key].strip()
        steps = plan["steps"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
            raise PlanValidationError("steps must contain between 1 and 12 stages")
        expected_step_fields = {
            "key",
            "title",
            "profile",
            "responsibility",
            "expected_output",
            "dependencies",
            "evidence_requirements",
            "tool_requirements",
        }
        keys: list[str] = []
        for index, raw_step in enumerate(steps, start=1):
            if not isinstance(raw_step, dict):
                raise PlanValidationError(f"step {index} must be an object")
            missing_step = expected_step_fields - set(raw_step)
            unknown_step = set(raw_step) - expected_step_fields
            if missing_step or unknown_step:
                detail = sorted(missing_step or unknown_step)
                raise PlanValidationError(f"step {index} has invalid fields: {', '.join(detail)}")
            key = str(raw_step["key"] or "").strip().lower()
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", key) or key in keys:
                raise PlanValidationError(f"step {index} key must be unique lowercase identifier")
            raw_step["key"] = key
            keys.append(key)
            profile = str(raw_step["profile"] or "").strip().lower()
            if profile not in available_profiles:
                raise PlanValidationError(f"step {key} uses unsupported profile: {profile or 'missing'}")
            raw_step["profile"] = profile
            for field, max_length in (("title", 300), ("responsibility", 2000), ("expected_output", 2000)):
                if not isinstance(raw_step[field], str) or not raw_step[field].strip() or len(raw_step[field]) > max_length:
                    raise PlanValidationError(f"step {key} {field} must be a non-empty string")
                raw_step[field] = raw_step[field].strip()
            list_limits = {"dependencies": (12, 64), "evidence_requirements": (12, 1000), "tool_requirements": (8, 64)}
            for field, (max_items, max_length) in list_limits.items():
                if not isinstance(raw_step[field], list) or any(not isinstance(item, str) for item in raw_step[field]):
                    raise PlanValidationError(f"step {key} {field} must be a string list")
                raw_step[field] = [item.strip() for item in raw_step[field] if item.strip()]
                if len(raw_step[field]) > max_items or any(len(item) > max_length for item in raw_step[field]):
                    raise PlanValidationError(f"step {key} {field} exceeds safety limits")
                if len(set(raw_step[field])) != len(raw_step[field]):
                    raise PlanValidationError(f"step {key} has duplicate {field}")
            tools = set(raw_step["tool_requirements"])
            unsupported_tools = tools - available_tools
            if unsupported_tools:
                raise PlanValidationError(f"step {key} uses unsupported tool: {', '.join(sorted(unsupported_tools))}")
        key_set = set(keys)
        graph: dict[str, list[str]] = {}
        for step in steps:
            dependencies = step["dependencies"]
            if len(set(dependencies)) != len(dependencies):
                raise PlanValidationError(f"step {step['key']} has duplicate dependencies")
            invalid = set(dependencies) - key_set
            if invalid or step["key"] in dependencies:
                raise PlanValidationError(f"step {step['key']} has invalid dependency: {', '.join(sorted(invalid or {step['key']}))}")
            graph[step["key"]] = dependencies
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise PlanValidationError("plan dependencies contain a cycle")
            if node in visited:
                return
            visiting.add(node)
            for parent in graph[node]:
                visit(parent)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)
        gates = plan["gates"]
        if not isinstance(gates, list) or not 1 <= len(gates) <= 12:
            raise PlanValidationError("gates must contain at least one human gate")
        for index, gate in enumerate(gates, start=1):
            if not isinstance(gate, dict) or set(gate) != {"type", "description"}:
                raise PlanValidationError(f"gate {index} must contain only type and description")
            gate_type = str(gate["type"] or "").strip().lower()
            if gate_type not in {"human", "audit"}:
                raise PlanValidationError(f"gate {index} uses unsupported type: {gate_type or 'missing'}")
            if not isinstance(gate["description"], str) or not gate["description"].strip() or len(gate["description"]) > 1000:
                raise PlanValidationError(f"gate {index} description is required")
            gate["type"] = gate_type
            gate["description"] = gate["description"].strip()
        if not any(gate["type"] == "human" for gate in gates):
            raise PlanValidationError("plan requires at least one human gate")
        if len(json.dumps(plan, ensure_ascii=False).encode("utf-8")) > 100_000:
            raise PlanValidationError("normalized plan exceeds 100000-byte safety limit")
        plan["_capability_snapshot"] = {
            "installed_profiles": sorted(installed_profiles),
            "allowed_profiles": sorted(available_profiles),
            "available_tools": sorted(available_tools),
            "validated_at": utc_now(),
        }
        return plan

    def sync_mission(self, mission_id: str) -> dict:
        mission = self.get_mission(mission_id)
        if mission["profile"] == self.PLANNING_PROFILE:
            return self._sync_planning_mission(mission)
        return self._sync_research_mission(mission)

    def _sync_planning_mission(self, mission: dict) -> dict:
        if mission["state"] == "canceled" or mission["plan_status"] == "approved":
            return mission
        task_id = str(mission.get("hermes_task_id") or "")
        if not task_id:
            return mission
        show_payload = self.adapter.show_task(task_id)
        runs_payload = self.adapter.task_runs(task_id)
        task = self._task_from_show(show_payload)
        latest_run = self._latest_run(runs_payload)
        status = str(task.get("status") or "").strip().lower()
        block_reason = self._block_reason(show_payload, task)
        plan_status = str(mission.get("plan_status") or "planning")
        if status == "blocked":
            state = "needs_input"
            operator_message = block_reason or "PLANNING is blocked and needs operator input."
            plan_status = "blocked"
        elif status in {"done", "review"}:
            run_id = str(latest_run.get("id") or latest_run.get("run_id") or "").strip()
            run_profile = str(latest_run.get("profile") or "").strip().lower()
            run_status = str(latest_run.get("status") or "").strip().lower()
            run_outcome = str(latest_run.get("outcome") or "").strip().lower()
            if not run_id or run_profile != self.PLANNING_PROFILE or run_status not in {"done", "success", "completed"} or run_outcome not in {"completed", "success"}:
                state = "failed"
                plan_status = "provenance_invalid"
                operator_message = "Planner result lacks a verified successful Hermes PLANNING run. Retry planning safely."
            else:
                raw = self._artifact_content(task, latest_run)
                try:
                    plan = self.validate_plan(raw)
                    self._upsert_plan(mission, plan, raw, task, latest_run)
                    state = "planning"
                    plan_status = "proposed"
                    operator_message = f"Workflow proposal v{mission['planning_version']} is validated and waiting for DV."
                except PlanValidationError as exc:
                    state = "failed"
                    plan_status = "invalid"
                    operator_message = f"Planner output failed validation: {exc}. Retry planning safely."
        elif status in {"running", "claimed"}:
            state = "planning"
            plan_status = "planning"
            operator_message = f"PLANNING is executing proposal v{mission['planning_version']} through Hermes Kanban."
        elif status in {"todo", "ready", "triage", "scheduled", ""}:
            state = "planning"
            plan_status = "planning"
            operator_message = f"Planning proposal v{mission['planning_version']} is queued on Hermes Kanban."
        else:
            state = "failed"
            plan_status = "failed"
            operator_message = f"Planning task entered unsupported Hermes state: {status}"
        with self.connect() as conn:
            now = utc_now()
            conn.execute(
                "UPDATE missions SET state=?, plan_status=?, operator_message=?, last_synced_at=?, updated_at=? WHERE id=?",
                (state, plan_status, operator_message, now, now, mission["id"]),
            )
            conn.commit()
        return self.get_mission(mission["id"])

    def _upsert_plan(self, mission: dict, plan: dict, raw: str, task: dict, run: dict) -> None:
        now = utc_now()
        capabilities = plan.pop("_capability_snapshot", {})
        version = int(mission.get("planning_version") or 1)
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id,status,revision_feedback,reviewer,reviewed_at,created_at FROM execution_plans WHERE mission_id=? AND version=?",
                (mission["id"], version),
            ).fetchone()
            plan_id = str(existing["id"]) if existing else uuid.uuid4().hex
            status = str(existing["status"]) if existing and str(existing["status"]) in {"approved", "revision_requested", "canceled"} else "proposed"
            values = (
                plan_id,
                mission["id"],
                version,
                status,
                plan["rationale"],
                plan["final_deliverable"],
                json.dumps(plan),
                raw,
                mission["hermes_task_id"],
                str(run.get("id") or run.get("run_id") or ""),
                str(run.get("profile") or task.get("assignee") or self.PLANNING_PROFILE),
                str(existing["revision_feedback"] or "") if existing else "",
                str(existing["reviewer"] or "") if existing else "",
                str(existing["reviewed_at"] or "") if existing else "",
                str(existing["created_at"] or now) if existing else now,
                now,
                json.dumps(capabilities),
            )
            conn.execute(
                """INSERT INTO execution_plans
                (id,mission_id,version,status,rationale,final_deliverable,plan_json,raw_planner_output,planner_task_id,planner_run_id,planner_profile,revision_feedback,reviewer,reviewed_at,created_at,updated_at,capabilities_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(mission_id,version) DO UPDATE SET
                  status=excluded.status,rationale=excluded.rationale,final_deliverable=excluded.final_deliverable,
                  plan_json=excluded.plan_json,raw_planner_output=excluded.raw_planner_output,
                  planner_task_id=excluded.planner_task_id,planner_run_id=excluded.planner_run_id,
                  planner_profile=excluded.planner_profile,capabilities_json=excluded.capabilities_json,updated_at=excluded.updated_at""",
                values,
            )
            conn.commit()

    def plan_action(self, mission_id: str, payload: dict | None) -> dict:
        payload = dict(payload or {})
        action = str(payload.get("action") or "").strip().lower().replace("-", "_")
        if action not in {"start", "request_revision", "cancel", "retry"}:
            raise ValueError("action must be start, request_revision, cancel, or retry")
        mission = self.get_mission(mission_id)
        if mission["profile"] != self.PLANNING_PROFILE:
            raise ValueError("plan actions require a Reset C planning mission")
        reviewer = str(payload.get("reviewer") or "operator").strip()[:120] or "operator"
        feedback = str(payload.get("feedback") or payload.get("note") or "").strip()
        current_plan = mission["plans"][0] if mission.get("plans") else None
        now = utc_now()
        if action == "start":
            if not current_plan or int(current_plan["version"]) != int(mission["planning_version"]):
                raise ValueError("a validated current plan is required before Start")
            if current_plan["status"] == "approved":
                return mission
            if mission["state"] != "planning" or mission["plan_status"] != "proposed" or current_plan["status"] != "proposed":
                raise ValueError("Start is available only for the current proposed plan")
            with self.connect() as conn:
                conn.execute(
                    "UPDATE execution_plans SET status='approved', reviewer=?, reviewed_at=?, updated_at=? WHERE id=?",
                    (reviewer, now, now, current_plan["id"]),
                )
                conn.execute(
                    "UPDATE missions SET state='queued', plan_status='approved', operator_message=?, updated_at=? WHERE id=?",
                    ("Plan approved. Downstream execution dispatch is intentionally deferred to Reset D.", now, mission_id),
                )
                conn.commit()
            self.adapter.comment(mission["hermes_task_id"], f"AgentForge plan v{mission['planning_version']} approved by {reviewer}.")
            return self.get_mission(mission_id)
        if action == "request_revision":
            if not current_plan or current_plan["status"] != "proposed":
                raise ValueError("a proposed current plan is required before requesting revision")
            if not feedback:
                raise ValueError("plan revision feedback is required")
            with self.connect() as conn:
                conn.execute(
                    "UPDATE execution_plans SET status='revision_requested', revision_feedback=?, reviewer=?, reviewed_at=?, updated_at=? WHERE id=?",
                    (feedback[:5000], reviewer, now, now, current_plan["id"]),
                )
                new_version = int(mission["planning_version"] or 1) + 1
                conn.execute(
                    "UPDATE missions SET state='dispatching', plan_status='revision_requested', planning_version=?, operator_message=?, updated_at=? WHERE id=?",
                    (new_version, "Dispatching a versioned planning revision.", now, mission_id),
                )
                conn.commit()
            try:
                self.adapter.comment(mission["hermes_task_id"], f"AgentForge requested plan revision: {feedback[:4500]}")
            except Exception:
                pass
            try:
                self._dispatch_planning_task(mission_id, version=new_version, feedback=feedback[:5000])
            except Exception as exc:
                with self.connect() as conn:
                    conn.execute(
                        "UPDATE missions SET state='failed', plan_status='dispatch_failed', operator_message=?, updated_at=? WHERE id=?",
                        (str(exc)[:2000], utc_now(), mission_id),
                    )
                    conn.commit()
                raise
            return self.get_mission(mission_id)
        if action == "retry":
            if mission["plan_status"] not in {"invalid", "failed", "dispatch_failed", "provenance_invalid"}:
                raise ValueError("retry is available only after planning failure")
            new_version = int(mission["planning_version"] or 1)
            if mission["plan_status"] != "dispatch_failed":
                new_version += 1
            with self.connect() as conn:
                conn.execute(
                    "UPDATE missions SET state='dispatching', plan_status='planning', planning_version=?, operator_message=?, updated_at=? WHERE id=?",
                    (new_version, "Retrying planning with a new durable version.", now, mission_id),
                )
                conn.commit()
            try:
                self._dispatch_planning_task(mission_id, version=new_version, feedback="Retry after the previous planner output failed server validation. Return only the required strict JSON object.")
            except Exception as exc:
                with self.connect() as conn:
                    conn.execute(
                        "UPDATE missions SET state='failed', plan_status='dispatch_failed', operator_message=?, updated_at=? WHERE id=?",
                        (str(exc)[:2000], utc_now(), mission_id),
                    )
                    conn.commit()
                raise
            return self.get_mission(mission_id)
        self.adapter.archive_task(mission["hermes_task_id"])
        with self.connect() as conn:
            if current_plan:
                conn.execute(
                    "UPDATE execution_plans SET status='canceled', reviewer=?, reviewed_at=?, updated_at=? WHERE id=?",
                    (reviewer, now, now, current_plan["id"]),
                )
            conn.execute(
                "UPDATE missions SET state='canceled', plan_status='canceled', operator_message='Mission canceled by human.', updated_at=? WHERE id=?",
                (now, mission_id),
            )
            conn.commit()
        return self.get_mission(mission_id)

    def _sync_research_mission(self, mission: dict) -> dict:
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
                refreshed = self.get_mission(mission["id"])
                existing_review_status = str((refreshed.get("artifacts") or [{}])[0].get("review_status") or "") if refreshed.get("artifacts") else ""
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
        elif status in {"running", "claimed"}:
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
            conn.execute(
                "UPDATE missions SET state=?, operator_message=?, last_synced_at=?, updated_at=? WHERE id=?",
                (state, operator_message, now, now, mission["id"]),
            )
            conn.commit()
        return self.get_mission(mission["id"])

    def _upsert_artifact(self, mission: dict, content: str, task: dict, run: dict, show_payload: dict, runs_payload: Any) -> None:
        with self.connect() as conn:
            step = conn.execute("SELECT * FROM mission_steps WHERE mission_id=? ORDER BY created_at LIMIT 1", (mission["id"],)).fetchone()
            if not step:
                raise RuntimeError("mission step mapping is missing")
            existing = conn.execute(
                "SELECT id FROM mission_artifacts WHERE mission_id=? AND hermes_task_id=?",
                (mission["id"], mission["hermes_task_id"]),
            ).fetchone()
            now = utc_now()
            artifact_id = existing["id"] if existing else uuid.uuid4().hex
            run_id = str(run.get("id") or run.get("run_id") or "")
            provenance = {
                "transport": "hermes kanban CLI --json",
                "board": self.BOARD,
                "task_id": mission["hermes_task_id"],
                "run_id": run_id,
                "worker_profile": str(run.get("profile") or run.get("assignee") or task.get("assignee") or mission["profile"]),
                "task_status": task.get("status"),
                "run_outcome": run.get("outcome") or run.get("status"),
                "tool_backed": True,
            }
            values = (
                artifact_id,
                mission["id"],
                step["id"],
                mission["hermes_task_id"],
                run_id,
                provenance["worker_profile"],
                f"Research artifact: {mission['desired_outcome'][:160]}",
                content,
                json.dumps(extract_urls(content)),
                json.dumps(provenance),
                "pending_review",
                now,
                now,
            )
            conn.execute(
                """INSERT INTO mission_artifacts
                (id,mission_id,mission_step_id,hermes_task_id,hermes_run_id,worker_profile,title,content,sources_json,provenance_json,review_status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(mission_id,hermes_task_id) DO UPDATE SET
                  hermes_run_id=excluded.hermes_run_id,worker_profile=excluded.worker_profile,title=excluded.title,
                  content=excluded.content,sources_json=excluded.sources_json,provenance_json=excluded.provenance_json,updated_at=excluded.updated_at""",
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
            conn.execute(
                "INSERT INTO mission_reviews (id,mission_id,artifact_id,action,note,reviewer,created_at) VALUES (?,?,?,?,?,?,?)",
                (uuid.uuid4().hex, mission_id, artifact["id"], action, note, reviewer, now),
            )
            conn.execute(
                "UPDATE missions SET state=?, operator_message=?, updated_at=? WHERE id=?",
                (
                    mission_state,
                    "Artifact approved by human." if action == "approve" else "Human requested revision on the real artifact.",
                    now,
                    mission_id,
                ),
            )
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
                raise MissionNotFoundError("mission not found")
            mission = dict(row)
            steps = [dict(item) for item in conn.execute("SELECT * FROM mission_steps WHERE mission_id=? ORDER BY created_at", (mission_id,)).fetchall()]
            artifacts = []
            for item in conn.execute("SELECT * FROM mission_artifacts WHERE mission_id=? ORDER BY updated_at DESC", (mission_id,)).fetchall():
                artifact = dict(item)
                artifact["sources"] = json.loads(artifact.pop("sources_json") or "[]")
                artifact["provenance"] = json.loads(artifact.pop("provenance_json") or "{}")
                artifacts.append(artifact)
            reviews = [dict(item) for item in conn.execute("SELECT * FROM mission_reviews WHERE mission_id=? ORDER BY created_at DESC", (mission_id,)).fetchall()]
            plans = []
            for item in conn.execute("SELECT * FROM execution_plans WHERE mission_id=? ORDER BY version DESC", (mission_id,)).fetchall():
                plan_row = dict(item)
                parsed = json.loads(plan_row.pop("plan_json") or "{}")
                plan_row["capabilities"] = json.loads(plan_row.pop("capabilities_json", "{}") or "{}")
                plan_row["steps"] = parsed.get("steps") or []
                plan_row["gates"] = parsed.get("gates") or []
                plans.append(plan_row)
        mission["attachments"] = json.loads(mission.pop("attachments_json", "[]") or "[]")
        mission["steps"] = steps
        mission["artifacts"] = artifacts
        mission["reviews"] = reviews
        mission["plans"] = plans
        mission["current_plan"] = plans[0] if plans and int(plans[0]["version"]) == int(mission.get("planning_version") or 0) else None
        return mission
