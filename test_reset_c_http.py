import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import server
from hermes_kanban_adapter import KanbanCommandError
from mission_service import MissionService


class HttpFakeAdapter:
    ALLOWED_PROFILES = frozenset({"assistant", "research", "planning", "dev", "audit"})

    def __init__(self):
        self.fail = False

    def create_task(self, **kwargs):
        if self.fail:
            raise KanbanCommandError("simulated Hermes outage")
        return {"id": "t_http_plan", "status": "todo", "assignee": kwargs["assignee"]}

    def installed_profiles(self):
        return set(self.ALLOWED_PROFILES)

    def available_plan_tools(self):
        return {"none", "web", "browser", "terminal", "file", "github"}


class ResetCHttpTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.originals = (server.BOARD_DB, server.TASK_ATTACHMENTS_DIR, server.MISSION_SERVICE)
        server.BOARD_DB = self.root / "board.db"
        server.TASK_ATTACHMENTS_DIR = self.root / "task_uploads"
        server.MISSION_SERVICE = MissionService(server.BOARD_DB, adapter=HttpFakeAdapter())
        server.init_board()
        server.MISSION_SERVICE.init_schema()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        server.BOARD_DB, server.TASK_ATTACHMENTS_DIR, server.MISSION_SERVICE = self.originals
        self.tempdir.cleanup()

    def upload(self, token="reset-c-http"):
        boundary = "----AgentForgeResetCTest"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="draft_token"\r\n\r\n'
            f"{token}\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="context.md"\r\n'
            "Content-Type: text/markdown\r\n\r\n"
            "Reset C context\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        request = urllib.request.Request(
            self.base + "/api/task-attachments/upload",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 201)
            return json.load(response)["attachment"]

    def test_staged_attachment_upload_delete_round_trip(self):
        attachment = self.upload()
        stored = server.TASK_ATTACHMENTS_DIR / attachment["storage_path"]
        self.assertTrue(stored.is_file())
        request = urllib.request.Request(
            self.base + f"/api/task-attachments/{attachment['id']}", method="DELETE"
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response)["deleted"], 1)
        self.assertFalse(stored.exists())
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 400)

    def test_mission_owned_attachment_cannot_be_deleted_or_assigned_to_task(self):
        attachment = self.upload("mission-draft")
        mission = server.MISSION_SERVICE.create_mission({
            "desired_outcome": "Create a secure launch workflow.",
            "success_criteria": "Return a validated specialist plan.",
            "attachment_ids": [attachment["id"]],
            "attachment_draft_token": "mission-draft",
            "idempotency_key": "http-owned-attachment",
        })
        request = urllib.request.Request(
            self.base + f"/api/task-attachments/{attachment['id']}", method="DELETE"
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 400)
        with server.connect_board() as conn:
            owner = conn.execute(
                "SELECT mission_id FROM mission_attachments WHERE attachment_id=?",
                (attachment["id"],),
            ).fetchone()
        self.assertEqual(owner["mission_id"], mission["id"])

    def test_mission_not_found_and_hermes_transport_have_truthful_status_codes(self):
        with self.assertRaises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(self.base + "/api/missions/missing", timeout=5)
        self.assertEqual(missing.exception.code, 404)

        setattr(server.MISSION_SERVICE.adapter, "fail", True)
        payload = json.dumps({
            "desired_outcome": "Plan during an outage.",
            "success_criteria": "Return a recoverable transport failure.",
            "idempotency_key": "http-hermes-outage",
        }).encode()
        request = urllib.request.Request(
            self.base + "/api/missions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as unavailable:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(unavailable.exception.code, 503)


if __name__ == "__main__":
    unittest.main()
