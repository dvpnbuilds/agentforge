"""Safe subprocess adapter for Hermes Kanban automation.

AgentForge uses this module instead of writing Hermes Kanban SQLite state directly.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any, Callable


class KanbanCommandError(RuntimeError):
    pass


class HermesKanbanAdapter:
    BOARD = "agentforge"
    MAX_BODY_BYTES = 20_000
    MAX_OUTPUT_BYTES = 2_000_000
    ALLOWED_PROFILES = frozenset({"assistant", "research", "planning", "dev", "audit"})

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        timeout: int = 20,
    ) -> None:
        self.runner = runner
        self.timeout = timeout

    def _run(self, operation: str, *args: str, expect_json: bool = True) -> Any:
        allowed = {"init", "boards", "create", "show", "list", "comment", "block", "unblock", "runs", "log", "archive"}
        if operation not in allowed:
            raise ValueError(f"unsupported Kanban operation: {operation}")
        command = ["hermes", "kanban", "--board", self.BOARD, operation, *[str(arg) for arg in args]]
        if expect_json:
            command.append("--json")
        try:
            result = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise KanbanCommandError(f"Hermes Kanban command timed out after {self.timeout}s") from exc
        stdout = str(result.stdout or "")
        stderr = str(result.stderr or "")
        if len(stdout.encode("utf-8", errors="replace")) > self.MAX_OUTPUT_BYTES:
            raise KanbanCommandError("Hermes Kanban response exceeded safe output limit")
        if result.returncode != 0:
            detail = (stderr or stdout or f"exit {result.returncode}").strip()
            raise KanbanCommandError(f"Hermes Kanban command failed: {detail[:2000]}")
        if not expect_json:
            return stdout
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise KanbanCommandError("Hermes Kanban returned malformed JSON") from exc

    @staticmethod
    def _require_id(task_id: str) -> str:
        task_id = str(task_id or "").strip()
        if not task_id or len(task_id) > 128:
            raise ValueError("valid task id is required")
        return task_id

    def init(self) -> str:
        return self._run("init", expect_json=False)

    def list_boards(self) -> Any:
        return self._run("boards", "list")

    def create_task(self, *, title: str, body: str, assignee: str, idempotency_key: str) -> dict:
        title = str(title or "").strip()
        body = str(body or "").strip()
        assignee = str(assignee or "").strip().lower()
        idempotency_key = str(idempotency_key or "").strip()
        if not title or len(title) > 300:
            raise ValueError("title is required and must be at most 300 characters")
        if len(body.encode("utf-8")) > self.MAX_BODY_BYTES:
            raise ValueError("body exceeds 20000-byte safety limit")
        if assignee not in self.ALLOWED_PROFILES:
            raise ValueError(f"unsupported profile: {assignee or 'missing'}")
        if not idempotency_key or len(idempotency_key) > 240:
            raise ValueError("valid idempotency key is required")
        payload = self._run(
            "create",
            title,
            "--body",
            body,
            "--assignee",
            assignee,
            "--workspace",
            "dir:/root/agentforge",
            "--idempotency-key",
            idempotency_key,
            "--created-by",
            "agentforge",
            "--max-runtime",
            "15m",
            "--max-retries",
            "1",
        )
        if not isinstance(payload, dict) or not str(payload.get("id") or "").strip():
            raise KanbanCommandError("Hermes Kanban create response did not include a task id")
        return payload

    def list_tasks(self) -> Any:
        return self._run("list", "--archived")

    def installed_profiles(self) -> set[str]:
        """Return persistent Hermes profiles visible through the supported CLI."""
        try:
            result = self.runner(
                ["hermes", "profile", "list"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise KanbanCommandError(f"Hermes profile list timed out after {self.timeout}s") from exc
        if result.returncode != 0:
            detail = str(result.stderr or result.stdout or f"exit {result.returncode}").strip()
            raise KanbanCommandError(f"Hermes profile list failed: {detail[:2000]}")
        profiles: set[str] = set()
        for line in str(result.stdout or "").splitlines():
            match = re.match(r"\s*[◆*]?\s*([a-z][a-z0-9_-]{0,63})\s+", line.lower())
            if match and match.group(1) not in {"profile"}:
                profiles.add(match.group(1))
        if not profiles:
            raise KanbanCommandError("Hermes profile list returned no parseable profiles")
        return profiles

    def available_plan_tools(self) -> set[str]:
        """Map enabled Hermes CLI toolsets to Reset C's plan vocabulary."""
        try:
            result = self.runner(
                ["hermes", "tools", "list", "--platform", "cli"],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise KanbanCommandError(f"Hermes tools list timed out after {self.timeout}s") from exc
        if result.returncode != 0:
            detail = str(result.stderr or result.stdout or f"exit {result.returncode}").strip()
            raise KanbanCommandError(f"Hermes tools list failed: {detail[:2000]}")
        enabled = {
            match.group(1)
            for line in str(result.stdout or "").splitlines()
            if (match := re.match(r"\s*✓\s+enabled\s+([a-z][a-z0-9_-]*)\b", line.lower()))
        }
        tools = {"none"} | ({"web", "browser", "terminal", "file"} & enabled)
        if "terminal" in enabled and (shutil.which("gh") or shutil.which("git")):
            tools.add("github")
        return tools

    def show_task(self, task_id: str) -> dict:
        payload = self._run("show", self._require_id(task_id))
        if not isinstance(payload, dict):
            raise KanbanCommandError("Hermes Kanban show response was not an object")
        return payload

    def task_runs(self, task_id: str) -> Any:
        return self._run("runs", self._require_id(task_id))

    def task_log(self, task_id: str, *, tail: int = 200_000) -> str:
        tail = max(1000, min(int(tail), self.MAX_OUTPUT_BYTES))
        return self._run("log", self._require_id(task_id), "--tail", str(tail), expect_json=False)

    def comment(self, task_id: str, text: str, *, author: str = "agentforge") -> str:
        text = str(text or "").strip()
        if not text or len(text) > 5000:
            raise ValueError("comment is required and must be at most 5000 characters")
        return self._run("comment", self._require_id(task_id), text, "--author", author, "--max-len", "5000", expect_json=False)

    def block_task(self, task_id: str, reason: str) -> str:
        reason = str(reason or "").strip()
        if not reason or len(reason) > 2000:
            raise ValueError("block reason is required and must be at most 2000 characters")
        return self._run("block", self._require_id(task_id), reason, "--kind", "needs_input", expect_json=False)

    def unblock_task(self, task_id: str, reason: str = "Input supplied in AgentForge") -> str:
        return self._run("unblock", self._require_id(task_id), "--reason", str(reason or "")[:2000], expect_json=False)

    def archive_task(self, task_id: str) -> str:
        return self._run("archive", self._require_id(task_id), expect_json=False)
