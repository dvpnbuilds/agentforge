# AgentForge Phase Canon

Last updated: 2026-06-11
Purpose: continuity anchor for AgentForge whenever chat context drifts, compression fails, or DEV/PLANNING/AUDIT need one trusted source.

---

## 1) Product canon

AgentForge is a **task-centered workforce OS**.

Main mental model:
- Tasks is the entry point
- Kanban is the operational view of the same task system
- a task is not just a card and not just a chat
- a task is a **managed work object with a live thread**
- runs, audit, memory, and proposals support that same task

Simple version:
- normal users get a friendly task workflow
- developers/operators can open deeper controls when needed

---

## 2) Canon roadmap

### Phase 1 — Tasks
Make Tasks the main entry point.

### Phase 2 — Kanban
Make work visible through one shared task board.

### Phase 3 — Task Detail
Make each task a real workspace with:
- Overview
- Thread
- Output
- Audit
- History
- Proposals

### Phase 4 — Playbooks
Reusable SOP-native execution layer.

### Phase 5 — Agents overhaul
Role-based workforce management.

### Phase 6 — Delegation
Parent/child tasks, manual delegation, auto-routing.

### Phase 7 — Audit
AI audit + human review + revision loop.

### Phase 8 — Memory Vault
Save reusable outputs, lessons, and approved work.

### Phase 9 — Proposals
System-generated improvement suggestions.

### Phase 10 — Approval-governed adaptation
Safe learning with human approval for structural changes.

---

## 3) Board/status canon

Statuses currently in use:
- backlog
- triage
- ready
- in_progress
- review
- revision_requested
- blocked
- completed

Required queue mapping:
- Run Now -> ready
- Add to Triage -> triage
- Add to Backlog -> backlog

Rule:
- Run Now requires assignee

---

## 4) Trusted implementation baseline

Main live code:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`

Local app URL:
- `http://127.0.0.1:50000`

Current known implementation strengths:
- task-first entry flow is real
- Tasks list + Kanban use one shared task model
- shared statuses are real
- playbook attachment exists in task flow
- runs/history system is real
- task↔run lifecycle mapping is real
- runs cleanup/admin controls exist
- runs inspector exists
- timeline context for runs exists

Runs timeline context route:
- `GET /api/runs/:id/context`

---

## 5) Current implementation sequence (actual shipped/handoff track)

Important:
This section tracks the **actual implementation phases/handoffs**.
It is separate from the canon roadmap above.
Do not merge the two numbering systems unless explicitly renumbered later.

### Implementation Phase 1 — Task-first entry flow
Confirmed complete.
Highlights:
- Tasks became the main task-entry surface
- title/instruction/assignee/playbook/queue destination added
- list + Kanban use same task data
- queue mapping preserved exactly

### Implementation Phase 2 — Task workflow / task detail groundwork
Confirmed complete.
Highlights:
- lifecycle/detail groundwork added around tasks
- task history/result/note flow was introduced in earlier handoff sequence

### Implementation Phase 3 — Task↔Run execution linkage
Confirmed complete.
Highlights:
- run records became first-class
- task-linked execution/run lifecycle mapping added

### Implementation Phase 4 — Runs surface
Confirmed complete.
Highlights:
- Runs tab / run history UI became real

### Implementation Phase 5 — Runs admin hygiene
Confirmed complete.
Highlights:
- cleanup/admin controls added for run history

### Implementation Phase 6-8 — Later runs/history depth work
Confirmed through handoff sequence.
Highlights:
- semantic/run presentation depth
- filtering/preset/timeline-related evolution
- latest clearly confirmed shipped milestone before this file: **Implementation Phase 8 = Runs timeline context**

Implementation Phase 8 key result:
- `GET /api/runs/:id/context`
- `before`
- `after`
- `recent`
- entity-first related-run lookup
- safe empty-context guardrails
- clickable related-run navigation
- preserved filter/saved-view state

### Implementation Phase 9 — Task Workspace V1
Status: **reported complete / handoff ready** on 2026-06-11.
Use this wording until independently re-verified in a future audit.

Reported highlights:
- one shared task workspace opened from Tasks or Kanban
- Overview
- Thread
- Output
- History
- same underlying task record everywhere
- additive task persistence through:
  - `GET /api/tasks/:id`
  - `GET /api/tasks/:id/history`
  - `POST /api/tasks/update?id=...`
- additive task fields used:
  - `last_note`
  - `result_text`
- additive thread note write compatibility:
  - `thread_note`
  - `threadNote`
- history event types reported:
  - `created`
  - `status_changed`
  - `thread_comment`
  - `result_saved`

Phase 9 handoff changed files:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`

Phase 9 backups:
- `/root/agentforge/backups/index_vnext_2026-06-11T11-03-51.html`
- `/root/agentforge/backups/server_vnext_2026-06-11T11-03-51.py`

Phase 9 reported verification:
- `python3 -m py_compile /root/agentforge/server.py` ✅
- extracted inline JS + `node --check` ✅
- task create/use/update/history/run-linked retrieval ✅
- UI open from Tasks and Kanban ✅
- save thread comment ✅
- save output/result ✅
- list + board stayed in sync ✅

### Implementation Phase 10 — Audit V1
Status: confirmed complete
Date: 2026-06-11

Changed files:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`
- `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`

What shipped:
- Audit tab added inside the shared task workspace
- task-level audit state, note, and timestamp became first-class task fields
- operator can save an audit note, approve, reject, or request revision from the same task workspace
- audit actions persist on the same task record and append readable task history events
- review-stage tasks auto-enter `pending_review` when no audit state has been set yet

Routes / data changes:
- additive task fields: `audit_state`, `audit_note`, `audit_updated_at`
- existing task write paths extended: `PUT /api/tasks/:id` and `POST /api/tasks/update?id=...`
- task list/detail payloads now surface audit fields through existing task APIs
- audit history events added: `audit_requested`, `audit_approved`, `audit_rejected`, `audit_note_saved`, `revision_requested`

Verification:
- `python3 -m py_compile /root/agentforge/server.py`
- extracted inline JS + `node --check`
- real API smoke for audit state, audit note, history round-trip, and preserved thread/output flows
- manual browser QA from Tasks and Kanban with audit actions

Deferred:
- AI-generated audit logic
- standalone audit analytics or dashboards
- permissions, attachments, proposal coupling, or autonomous review workers

Next recommended phase:
- Implementation Phase 11 — Delegation V1
- tasks now support execution and audit; next highest-leverage loop is parent/child task routing and manual delegation

### Implementation Phase 11 — Delegation V1
Status: confirmed complete
Date: 2026-06-11

Changed files:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`
- `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`

What shipped:
- Delegation tab added inside the shared task workspace
- tasks now support additive parent/child linkage through the same task record model
- operator can create a linked child task from the parent workspace with title, instruction, assignee, playbook, queue/status, and delegation note
- parent tasks show linked child task count and child status rows
- child tasks show parent task reference in the same workspace
- delegated child rows are clickable and reopen the child inside the same shared workspace

Routes / data changes:
- additive task fields: `parent_task_id`, `delegation_note`
- existing task create/update/detail payloads now surface: `parent_task`, `child_tasks`, `child_count`
- additive child lookup route: `GET /api/tasks/:id/children`
- existing task write paths extended: `POST /api/tasks`, `PUT /api/tasks/:id`, and `POST /api/tasks/update?id=...`
- delegation history events added: `delegated_from_parent`, `delegation_child_created`, `delegation_unlinked`, `delegation_child_unlinked`, `delegation_note_saved`

Verification:
- `python3 -m py_compile /root/agentforge/server.py`
- extracted inline JS + `node --check`
- real API smoke for parent create, child create, `parent_task_id` round-trip, `GET /api/tasks/:id/children`, parent/child detail linkage, status update, and history events
- manual browser QA from Tasks and Kanban with live delegated child creation, parent child-count refresh, child open from linked-child row, and shared workspace sync
- live runtime confirmed on `http://127.0.0.1:50000`

Deferred:
- nested delegation tree UI beyond one-level linked child visibility
- automated delegation logic, queue workers, or child run orchestration
- dependency graphs, child roll-up analytics, or permissions

Next recommended phase:
- Implementation Phase 12 — Memory Vault V1
- delegation is now real enough; the next highest-leverage layer is durable knowledge capture tied to tasks, runs, and operator review

### Implementation Phase 12 — Memory Vault V1
Status: confirmed complete
Date: 2026-06-11

Changed files:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`
- `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`
- `/root/agentforge/docs/AGENTFORGE_HANDOFF_CHECKLIST.md`

What shipped:
- Memory tab added inside the shared task workspace so operators can save durable vault records without leaving the task flow
- vault records now preserve title, content, source task linkage, optional source run linkage, memory type, created-by label, and timestamps
- task detail now surfaces linked memory records plus memory count alongside existing run/audit/delegation data
- linked memories can be reopened and read inside the same workspace, including linked-run context when present
- a simple vault list/search API now exists for practical retrieval outside the task detail payload

Routes / data changes:
- new table: `vault_records`
- additive task detail/list fields: `memory_count`, `linked_memories`
- new routes: `POST /api/vault`, `GET /api/vault`, `GET /api/vault/:id`, `GET /api/tasks/:id/memories`
- new vault fields: `id`, `title`, `content`, `source_task_id`, `source_run_id`, `memory_type`, `created_by`, `created_at`, `updated_at`
- task history event added: `memory_saved`

Verification:
- `python3 -m py_compile /root/agentforge/server.py`
- extracted inline JS + `node --check`
- real API smoke for task create, run start/complete, thread/output/audit updates, child delegation, vault create/list/detail/search, and task-linked memory count round-trip
- manual browser QA from Tasks and Kanban with shared workspace open, Memory tab visible, linked record readback, and live save-to-vault from the workspace
- live runtime confirmed on `http://127.0.0.1:50000` with updated `server.py` process bound to port `50000`

Deferred:
- embeddings/vector retrieval or autonomous summarization
- proposal coupling, approval-governed learning, permissions, or attachments on vault records
- standalone vault analytics/dashboard expansion beyond practical V1 retrieval

Next recommended phase:
- Implementation Phase 13 — Proposals V1
- now that tasks can retain durable outputs and lessons, the next highest-value layer is turning that preserved context into explicit operator-visible improvement proposals

---

## 6) Where AgentForge is right now

Blunt status:
- **foundation is real**
- **task workspace is real and now includes execution, audit, delegation, and memory capture in one shared flow**
- but the full canon product is still not complete

What feels strongest now:
- task creation
- Kanban
- runs/history visibility
- run inspector depth
- task workspace foundation
- task-level audit workflow
- manual parent/child delegation inside the task workspace
- task-linked memory capture and retrieval

What is still clearly missing from the canon product:
- full Agents overhaul
- deeper Delegation / subtask tree
- deeper Audit beyond V1
- Proposals system
- Approval-governed adaptation layer
- deeper task workspace richness beyond V1
- richer vault intelligence beyond operator-curated V1 capture

---

## 7) Recommended next build direction

Current recommended next implementation phase:

### Preferred next implementation phase
**Implementation Phase 13 — Proposals V1**

Reason:
- tasks now have creation, execution linkage, workspace, audit, delegation, and durable memory capture
- the highest-value remaining gap is turning preserved task/run/memory context into explicit operator-visible improvement proposals
- Proposals V1 fits naturally after Memory Vault because it can reuse linked outputs, lessons, and audit history instead of inventing context from scratch

Proposals V1 should likely add:
- additive proposal records tied to tasks, runs, and optionally vault memories
- clear operator-visible suggestion cards with approve/reject states
- proposal generation focused on workflow improvements, next actions, or system refinements without mutating structure automatically

Alternative after that:
- deeper Delegation V2 or approval-governed adaptation groundwork

---

## 8) Update protocol after every completed phase

After each phase, update this file immediately.

Always update these sections:
1. `Current implementation sequence`
2. `Where AgentForge is right now`
3. `Recommended next build direction`

Use this exact mini-template:

### Implementation Phase X — <name>
Status: confirmed complete | reported complete / handoff ready | needs audit
Date: YYYY-MM-DD

Changed files:
- path
- path

What shipped:
- bullet
- bullet
- bullet

Routes / data changes:
- route or field
- route or field

Verification:
- syntax check
- API smoke
- browser QA

Deferred:
- bullet
- bullet

Next recommended phase:
- name
- why

---

## 9) Rules for future continuity

When continuity drifts:
- trust this file before reply snippets
- trust attached handoff text before truncated Discord reply previews
- keep **canon roadmap numbering** separate from **implementation phase numbering**
- do not jump to a new phase number just because higher-number internal reference files exist
- if unsure, label uncertainty explicitly instead of guessing

---

## 10) Short canonical summary

AgentForge is a task-centered workforce OS.

Current reality:
- Tasks + Kanban are real
- Runs/history are strong
- Task Workspace V1 is real
- Audit V1 is real
- Delegation V1 is now real
- Memory Vault V1 is now real

Main missing product layers:
- Proposals
- approval-governed adaptation
- deeper delegation/orchestration depth
- richer memory intelligence beyond curated V1 capture

Current best next step after Phase 12:
- **Implementation Phase 13 — Proposals V1**
