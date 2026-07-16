import json
import tempfile
import unittest
from pathlib import Path

from mission_service import MissionService


VALID_PLAN = {
    "rationale": "Research first, then produce a concise brief with human approval.",
    "final_deliverable": "A sourced decision brief.",
    "steps": [
        {
            "key": "research",
            "title": "Research evidence",
            "profile": "research",
            "responsibility": "Collect current facts from primary sources.",
            "expected_output": "A sourced fact brief.",
            "dependencies": [],
            "evidence_requirements": ["Use primary sources and include URLs."],
            "tool_requirements": ["web"],
        },
        {
            "key": "draft",
            "title": "Draft deliverable",
            "profile": "assistant",
            "responsibility": "Turn verified evidence into the requested brief.",
            "expected_output": "A concise decision brief.",
            "dependencies": ["research"],
            "evidence_requirements": ["Use only facts from the research step."],
            "tool_requirements": ["none"],
        },
    ],
    "gates": [
        {"type": "human", "description": "DV approves the plan before execution."}
    ],
}


class FakeAdapter:
    ALLOWED_PROFILES = frozenset({"assistant", "research", "planning", "dev", "audit"})

    def __init__(self):
        self.created = []
        self.archived = []
        self.comments = []
        self.tasks = {}
        self.runs = {}
        self.comment_error = False
        self.create_error_on_calls = set()

    def create_task(self, **kwargs):
        call_number = len(self.created) + 1
        if call_number in self.create_error_on_calls:
            self.create_error_on_calls.remove(call_number)
            raise RuntimeError("simulated dispatch failure")
        task_id = f"t_plan_{len(self.created) + 1}"
        self.created.append(kwargs)
        self.tasks[task_id] = {
            "id": task_id,
            "status": "todo",
            "assignee": kwargs["assignee"],
            "result": "",
        }
        return dict(self.tasks[task_id])

    def show_task(self, task_id):
        return {"task": dict(self.tasks[task_id]), "comments": []}

    def task_runs(self, task_id):
        return list(self.runs.get(task_id, []))

    def comment(self, task_id, text, author="agentforge"):
        if self.comment_error:
            raise RuntimeError("simulated comment failure")
        self.comments.append((task_id, text, author))
        return "ok"

    def archive_task(self, task_id):
        self.archived.append(task_id)
        return "ok"

    def installed_profiles(self):
        return set(self.ALLOWED_PROFILES)

    def available_plan_tools(self):
        return {"none", "web", "browser", "terminal", "file", "github"}


class PlanningMissionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "board.db"
        self.adapter = FakeAdapter()
        self.service = MissionService(self.db_path, adapter=self.adapter)
        self.service.init_schema()

    def tearDown(self):
        self.tempdir.cleanup()

    def create(self, **overrides):
        payload = {
            "desired_outcome": "Prepare a launch decision brief.",
            "success_criteria": "Return a sourced brief with risks and a recommendation.",
            "context": "Use current primary sources.",
            "priority": "high",
            "deadline": "2026-08-01",
            "idempotency_key": "reset-c-planning-1",
        }
        payload.update(overrides)
        return self.service.create_mission(payload)

    def complete_plan(self, mission, plan=None, *, fenced=True):
        task_id = mission["hermes_task_id"]
        raw = json.dumps(plan or VALID_PLAN)
        self.adapter.tasks[task_id].update({
            "status": "done",
            "result": f"```json\n{raw}\n```" if fenced else raw,
        })
        self.adapter.runs[task_id] = [{
            "id": f"run_{task_id}",
            "profile": "planning",
            "status": "done",
            "outcome": "completed",
        }]
        return self.service.sync_mission(mission["id"])

    def test_goal_first_create_dispatches_only_real_planning_task_and_is_idempotent(self):
        first = self.create()
        second = self.create()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["profile"], "planning")
        self.assertEqual(first["state"], "planning")
        self.assertEqual(first["planning_version"], 1)
        self.assertEqual(len(self.adapter.created), 1)
        self.assertEqual(self.adapter.created[0]["assignee"], "planning")
        self.assertIn('"final_deliverable"', self.adapter.created[0]["body"])
        self.assertEqual([step["profile"] for step in first["steps"]], ["planning"])

    def test_valid_planner_output_is_validated_and_presented_without_execution_dispatch(self):
        mission = self.create()
        synced = self.complete_plan(mission)
        self.assertEqual(synced["state"], "planning")
        self.assertEqual(synced["plan_status"], "proposed")
        self.assertEqual(len(synced["plans"]), 1)
        self.assertIn("planning", synced["plans"][0]["capabilities"]["allowed_profiles"])
        self.assertIn("web", synced["plans"][0]["capabilities"]["available_tools"])
        self.assertEqual(synced["plans"][0]["steps"][1]["dependencies"], ["research"])
        self.assertEqual(len(self.adapter.created), 1)
        started = self.service.plan_action(mission["id"], {"action": "start", "reviewer": "DV"})
        self.assertEqual(started["state"], "queued")
        self.assertEqual(started["plan_status"], "approved")
        self.assertEqual(len(self.adapter.created), 1, "Reset C must not dispatch execution steps")
        repeated = self.service.plan_action(mission["id"], {"action": "start", "reviewer": "DV"})
        self.assertEqual(repeated["state"], "queued")
        self.assertEqual(repeated["plan_status"], "approved")
        self.assertEqual(len(self.adapter.created), 1, "Repeated Start must stay idempotent")

    def test_completed_task_requires_real_successful_planning_run_provenance(self):
        mission = self.create(idempotency_key="missing-run")
        task_id = mission["hermes_task_id"]
        self.adapter.tasks[task_id].update({"status": "done", "result": json.dumps(VALID_PLAN)})
        failed = self.service.sync_mission(mission["id"])
        self.assertEqual(failed["plan_status"], "provenance_invalid")
        self.assertEqual(failed["plans"], [])

        mission = self.create(idempotency_key="wrong-profile-run")
        task_id = mission["hermes_task_id"]
        self.adapter.tasks[task_id].update({"status": "done", "result": json.dumps(VALID_PLAN)})
        self.adapter.runs[task_id] = [{"id": "run_wrong", "profile": "research", "status": "done", "outcome": "completed"}]
        failed = self.service.sync_mission(mission["id"])
        self.assertEqual(failed["plan_status"], "provenance_invalid")
        self.assertEqual(failed["plans"], [])

    def test_malformed_plan_fails_visibly_and_retry_creates_one_new_planning_attempt(self):
        mission = self.create()
        task_id = mission["hermes_task_id"]
        self.adapter.tasks[task_id].update({"status": "done", "result": "not json"})
        self.adapter.runs[task_id] = [{"id": "run_malformed", "profile": "planning", "status": "done", "outcome": "completed"}]
        failed = self.service.sync_mission(mission["id"])
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["plan_status"], "invalid")
        self.assertIn("validation", failed["operator_message"].lower())
        retried = self.service.plan_action(mission["id"], {"action": "retry"})
        self.assertEqual(retried["state"], "planning")
        self.assertEqual(retried["planning_version"], 2)
        self.assertEqual(len(self.adapter.created), 2)

    def test_unsupported_profile_and_tool_are_rejected_by_server_validation(self):
        for mutation, expected in [
            (("profile", "sales"), "profile"),
            (("tool_requirements", ["root_shell"]), "tool"),
        ]:
            with self.subTest(mutation=mutation):
                mission = self.create(idempotency_key=f"invalid-{mutation[0]}")
                plan = json.loads(json.dumps(VALID_PLAN))
                if mutation[0] == "profile":
                    plan["steps"][0]["profile"] = mutation[1]
                else:
                    plan["steps"][0][mutation[0]] = mutation[1]
                synced = self.complete_plan(mission, plan)
                self.assertEqual(synced["state"], "failed")
                self.assertIn(expected, synced["operator_message"].lower())

    def test_revision_preserves_previous_plan_and_feedback(self):
        mission = self.create()
        proposed = self.complete_plan(mission)
        revised = self.service.plan_action(proposed["id"], {
            "action": "request_revision",
            "feedback": "Make AUDIT an explicit final stage.",
            "reviewer": "DV",
        })
        self.assertEqual(revised["planning_version"], 2)
        self.assertEqual(revised["state"], "planning")
        self.assertEqual(len(revised["plans"]), 1)
        self.assertEqual(revised["plans"][0]["status"], "revision_requested")
        self.assertEqual(revised["plans"][0]["revision_feedback"], "Make AUDIT an explicit final stage.")
        self.assertIn("Make AUDIT", self.adapter.created[1]["body"])
        second = json.loads(json.dumps(VALID_PLAN))
        second["steps"].append({
            "key": "audit",
            "title": "Audit brief",
            "profile": "audit",
            "responsibility": "Check evidence and unsupported claims.",
            "expected_output": "A pass or revision-required verdict.",
            "dependencies": ["draft"],
            "evidence_requirements": ["Trace every factual claim."],
            "tool_requirements": ["none"],
        })
        synced = self.complete_plan(revised, second)
        self.assertEqual(len(synced["plans"]), 2)
        self.assertEqual(synced["plans"][0]["version"], 2)
        self.assertEqual(synced["plans"][1]["version"], 1)

    def test_revision_comment_failure_is_best_effort_and_dispatches_revision(self):
        mission = self.complete_plan(self.create(idempotency_key="comment-failure"))
        self.adapter.comment_error = True
        revised = self.service.plan_action(mission["id"], {"action": "request_revision", "feedback": "Tighten evidence.", "reviewer": "DV"})
        self.assertEqual(revised["planning_version"], 2)
        self.assertEqual(len(self.adapter.created), 2)

    def test_revision_dispatch_failure_retries_same_version(self):
        mission = self.complete_plan(self.create(idempotency_key="dispatch-failure"))
        self.adapter.create_error_on_calls.add(2)
        with self.assertRaisesRegex(RuntimeError, "dispatch failure"):
            self.service.plan_action(mission["id"], {"action": "request_revision", "feedback": "Revise.", "reviewer": "DV"})
        failed = self.service.get_mission(mission["id"])
        self.assertEqual(failed["planning_version"], 2)
        self.assertEqual(failed["plan_status"], "dispatch_failed")
        retried = self.service.plan_action(mission["id"], {"action": "retry"})
        self.assertEqual(retried["planning_version"], 2)
        self.assertEqual(len(self.adapter.created), 2)

    def test_attachment_path_is_validated_persisted_and_sent_to_planner(self):
        upload_dir = self.root / "task_uploads" / "reset-c"
        upload_dir.mkdir(parents=True)
        upload = upload_dir / "brief.md"
        upload.write_text("Launch context", encoding="utf-8")
        with self.service.connect() as conn:
            conn.execute("""
                CREATE TABLE task_attachments (
                  id TEXT PRIMARY KEY, task_id TEXT DEFAULT '', draft_token TEXT DEFAULT '',
                  filename TEXT NOT NULL, mime_type TEXT DEFAULT '', size_bytes INTEGER NOT NULL,
                  storage_rel_path TEXT NOT NULL, uploaded_at TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO task_attachments VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("att_1", "", "draft_1", "brief.md", "text/markdown", 14, "task_uploads/reset-c/brief.md", "now", "now", "now"),
            )
        mission = self.create(
            idempotency_key="reset-c-attachment",
            attachment_ids=["att_1"],
            attachment_draft_token="draft_1",
        )
        self.assertEqual(mission["attachments"][0]["filename"], "brief.md")
        self.assertIn(str(upload.resolve()), self.adapter.created[0]["body"])
        with self.service.connect() as conn:
            owner = conn.execute("SELECT mission_id FROM mission_attachments WHERE attachment_id='att_1'").fetchone()
        self.assertEqual(owner["mission_id"], mission["id"])
        task_id = mission["hermes_task_id"]
        self.adapter.tasks[task_id].update({"status": "done", "result": "not json"})
        self.adapter.runs[task_id] = [{"id": "run_attachment", "profile": "planning", "status": "done", "outcome": "completed"}]
        self.assertEqual(self.service.sync_mission(mission["id"])["plan_status"], "invalid")
        upload.unlink()
        with self.assertRaisesRegex(ValueError, "attachment path"):
            self.service.plan_action(mission["id"], {"action": "retry"})

    def test_missing_success_criteria_is_rejected_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, "success criteria"):
            self.create(success_criteria="")
        self.assertEqual(self.adapter.created, [])

    def test_cancel_archives_current_planning_task_without_execution(self):
        mission = self.create()
        canceled = self.service.plan_action(mission["id"], {"action": "cancel", "reviewer": "DV"})
        self.assertEqual(canceled["state"], "canceled")
        self.assertEqual(self.adapter.archived, [mission["hermes_task_id"]])
        self.assertEqual(len(self.adapter.created), 1)
        with self.assertRaisesRegex(ValueError, "validated current plan"):
            self.service.plan_action(mission["id"], {"action": "start", "reviewer": "DV"})

    def test_canceled_proposed_plan_cannot_be_resurrected(self):
        mission = self.complete_plan(self.create(idempotency_key="cancel-proposed"))
        canceled = self.service.plan_action(mission["id"], {"action": "cancel", "reviewer": "DV"})
        self.assertEqual(canceled["plans"][0]["status"], "canceled")
        with self.assertRaisesRegex(ValueError, "current proposed plan"):
            self.service.plan_action(mission["id"], {"action": "start", "reviewer": "DV"})


if __name__ == "__main__":
    unittest.main()
