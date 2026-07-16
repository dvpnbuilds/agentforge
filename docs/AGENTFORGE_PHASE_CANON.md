# AgentForge Phase Canon

Last updated: 2026-07-16
Purpose: continuity anchor for AgentForge whenever chat context drifts, compression fails, or DEV/PLANNING/AUDIT need one trusted source.

---

## 1) Product canon

AgentForge is a **supervised adaptive workflow system for a persistent team of Hermes specialists**.

Primary product goal:
- the user describes the desired outcome through `Create Work`
- AgentForge organizes the request into a visible workflow, selects the right Hermes profiles, scopes what each worker must do, and coordinates their handoffs
- real Hermes profiles execute durable work instead of AgentForge simulating execution
- independent research, production, audit, and human-review stages reduce unsupported claims and make missing context visible
- human feedback corrects the current result and can propose approved lessons, trusted Vault memory, or a versioned workflow improvement
- once the human is satisfied, the successful process can become a reusable workflow

Main mental model:
- one user request becomes a **mission**
- a mission has a generated execution plan made of scoped specialist steps
- Hermes Kanban is the durable execution substrate
- AgentForge is the operator-facing planning, supervision, review, artifact, reusable-workflow, and memory layer
- only approved facts, lessons, artifacts, and workflow changes enter trusted organizational memory

Simple version:
- Claude Cowork and ChatGPT can help complete individual tasks
- AgentForge runs a repeatable work process, preserves what was learned, and improves the next run under human approval

Approved reset specification:
- `docs/AGENTFORGE_PRODUCT_RESET_A.md`
- DEV-ready phased roadmap: `docs/AGENTFORGE_PRODUCT_RESET_BUILD_PLAN.md`

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
System-generated improvement suggestions tied to task context, saved memory, and prior outputs.

### Phase 10 — Approval-governed adaptation
Safe learning with human approval for structural changes.

### Phase 11 — Output intelligence
Strengthen output generation so task deliverables are context-aware, usable, and close to the right final answer.

### Phase 12 — Functional completion loop
Make the full task loop reliable: task in -> strong output out -> smart suggestions visible -> operator can approve and improve the system from the same workspace.

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

### Implementation Phase 13 — Proposals V1
Status: confirmed complete
Date: 2026-06-11

Changed files:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`
- `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`
- `/root/agentforge/docs/AGENTFORGE_HANDOFF_CHECKLIST.md`

What shipped:
- Proposals tab added inside the shared task workspace so operators can capture structured improvement suggestions without leaving the task flow
- proposal records now preserve title, content, proposal type, status, source task linkage, optional run linkage, optional memory linkage, audit-state context, and a context summary snapshot
- task detail now surfaces linked proposals plus proposal count alongside existing run, audit, delegation, and memory data
- linked proposals can be reopened inside the same workspace and their status can be advanced through proposed, accepted, rejected, or applied
- proposal lifecycle changes now append readable task history events so the proposal trail stays visible from the same task record

Routes / data changes:
- new table: `proposals`
- new proposal fields: `id`, `title`, `content`, `proposal_type`, `status`, `source_task_id`, `source_run_id`, `source_memory_id`, `source_audit_state`, `source_context_summary`, `created_at`, `updated_at`
- new list/detail routes: `GET /api/proposals`, `GET /api/proposals/:id`
- new task-linked route: `GET /api/tasks/:id/proposals`
- new write route: `POST /api/proposals`
- new update route: `PUT /api/proposals/:id`
- additive task detail/list fields: `proposal_count`, `linked_proposals`
- task history events added: `proposal_created`, `proposal_updated`, `proposal_status_updated`

Verification:
- `python3 -m py_compile /root/agentforge/server.py`
- extracted inline JS + `node --check`
- real API smoke for task create/update, memory create, proposal create/update, task-linked proposal retrieval, and preserved child delegation linkage
- cleanup sweep removed stale temporary Phase 13 verification artifacts and confirmed marker absence in DB/API/UI results
- manual browser QA from Tasks and Kanban with shared workspace open, Proposals tab visible, proposal save/readback, and live status update actions
- live runtime confirmed on `http://127.0.0.1:50000` with startup proof from the active `server.py` process

Deferred:
- automatic proposal generation from models or runs
- proposal approval policies that mutate structure automatically
- proposal analytics, batching, or cross-task proposal queues

Next recommended phase:
- Implementation Phase 14 — Approval-Governed Adaptation V1
- proposals are now explicit and reviewable; the next highest-value layer is turning accepted proposals into safe, human-approved structural adaptation instead of passive suggestion storage

### Implementation Phase 14 — Approval-Governed Adaptation V1
Status: confirmed complete
Date: 2026-06-12

Changed files:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`
- `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`
- `/root/agentforge/docs/AGENTFORGE_HANDOFF_CHECKLIST.md`

What shipped:
- proposal records now carry explicit approval-governed adaptation state inside the same shared task workspace instead of stopping at passive proposal status
- operators can save approval reasoning, request approval, approve, reject, and apply proposals without leaving the task detail flow
- task detail now surfaces proposal governance counts so pending approvals and approved/applied proposals are visible at the task level
- proposal workflow actions append readable governance history events so approval decisions stay auditable from the same task record
- proposal detail now shows approval timestamps, applied timestamps, reviewer identity, adaptation type, and preserved task/run/memory/audit linkage context

Routes / data changes:
- extended proposal fields: `approval_state`, `approval_note`, `approval_updated_at`, `applied_at`, `reviewed_by`, `adaptation_type`
- extended list route: `GET /api/proposals` now supports `approval_state`
- extended write route: `POST /api/proposals` now accepts approval/adaptation metadata with guardrails
- extended update route: `PUT /api/proposals/:id` now accepts approval/adaptation metadata with lifecycle validation
- new proposal workflow routes: `POST /api/proposals/:id/request-approval`, `POST /api/proposals/:id/approve`, `POST /api/proposals/:id/reject`, `POST /api/proposals/:id/apply`
- additive task fields: `pending_approval_count`, `approved_proposal_count`, `pendingApprovalCount`, `approvedProposalCount`
- task history events added: `proposal_sent_for_approval`, `proposal_approved`, `proposal_rejected`, `proposal_applied`, `approval_note_saved`

Verification:
- `python3 -m py_compile /root/agentforge/server.py`
- extracted inline JS + `node --check`
- real API smoke for proposal acceptance, approval request, approval decision, apply path, task counters, and preserved task/memory/audit linkage
- browser QA from the live task workspace with proposal governance controls visible: linked proposals, approval pending badge, save approval note, approve/reject/apply actions
- cleanup sweep removed temporary Phase 14 verification artifacts and confirmed no lingering `P14_VERIFY_*` or `P14_BROWSER_QA*` records in DB cleanup checks
- live runtime confirmed on `http://127.0.0.1:50000` with startup proof from the active `server.py` process

Deferred:
- automatic structural mutation from approved proposals
- rollback execution engine for applied adaptations
- proposal queue analytics, batching, or multi-approver policy layers

Next recommended phase:
- Implementation Phase 15 — Applied Adaptation Execution V1
- approval-governed decisions are now explicit; the next highest-value layer is executing approved adaptations through a controlled, observable apply path instead of status-only governance

### Implementation Phase 15 — Applied Adaptation Execution V1
Status: confirmed complete
Date: 2026-06-12

Changed files:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`
- `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`
- `/root/agentforge/docs/AGENTFORGE_HANDOFF_CHECKLIST.md`

What shipped:
- approved proposals now create a real persisted adaptation execution record instead of stopping at governance state only
- proposal approval state remains separate from execution state, so AgentForge now records both what was allowed and what actually happened during apply
- the shared task workspace now surfaces adaptation execution count, latest execution state, editable execution summary/note/outcome fields, and operator lifecycle controls without leaving the proposal context
- operators can move an adaptation execution through a minimal explicit lifecycle and see matching history updates from the same task record
- task detail and proposal retrieval now expose linked adaptation execution context, making apply outcomes durable, inspectable, and auditable

Routes / data changes:
- new table: `adaptation_executions`
- new execution fields: `id`, `proposal_id`, `source_task_id`, `source_run_id`, `source_memory_id`, `proposal_title_snapshot`, `approval_state_snapshot`, `adaptation_type`, `execution_status`, `execution_summary`, `execution_note`, `operator_note`, `outcome_text`, `change_target`, `target_scope`, `created_by`, `applied_by`, `rollback_state`, `rollback_note`, `started_at`, `finished_at`, `created_at`, `updated_at`
- new execution routes: `GET /api/adaptations`, `GET /api/adaptations/:id`, `GET /api/tasks/:id/adaptations`, `GET /api/proposals/:id/adaptations`, `GET /api/proposals/:id/applications`, `POST /api/adaptations`, `POST /api/adaptations/update?id=...`
- extended proposal apply path: `POST /api/proposals/:id/apply` now creates or returns a persisted execution record instead of only touching governance metadata
- additive task/proposal payload fields: `adaptation_count`, `latest_adaptation`, `linked_adaptations`, `adaptationCount`, `latestAdaptation`, `linkedAdaptations`
- task history events added: `adaptation_apply_started`, `adaptation_apply_succeeded`, `adaptation_apply_failed`, `adaptation_rollback_marked`, `adaptation_execution_note_saved`

Verification:
- `python3 -m py_compile /root/agentforge/server.py`
- extracted inline JS + `node --check`
- real API smoke for task create, proposal create, proposal accept, request approval, approve, apply, execution record retrieval, execution status transitions (`pending_apply` -> `applying` -> `applied` -> `rolled_back`), task adaptation counts, and task history events
- browser QA from the live task workspace with the same task opened from list and board, proposal context visible, execution record created from the UI, execution summary/note/outcome persisted, and history entries rendered in the workspace timeline
- cleanup sweep removed temporary Phase 15 browser-QA and smoke-test tasks and confirmed no lingering `Phase 15` task titles or phase-specific adaptation rows in API/DB verification checks
- live runtime confirmed on `http://127.0.0.1:50000` with startup proof from the active `server.py` process

Deferred:
- automatic proposal generation or execution planning from models
- automatic rollback engine or structural self-modification
- richer execution analytics / batching / multi-step orchestration beyond operator-driven V1 transitions

Next recommended phase:
- Implementation Phase 16 — Proposal Automation V1
- applied execution is now real; the next highest-value gap is generating stronger proposal candidates automatically from task/run/memory/audit context instead of relying on fully manual proposal authoring

### Implementation Phase 16 — Proposal Automation V1
Status: confirmed complete
Date: 2026-06-12

Changed files:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`
- `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`

What shipped:
- proposal records can now be generated directly from live task context instead of requiring fully manual authoring every time
- generated proposals are persisted as normal proposal records inside the same shared task workspace, with manual/generated provenance preserved instead of hidden transient suggestions
- operators now get generation rationale, confidence metadata, context snapshots, and generation-source visibility before using the normal proposal governance flow
- duplicate generation attempts now reuse the latest matching generated draft instead of flooding the task with identical proposal spam
- the existing review -> approval -> apply chain remains intact, so proposal automation improves candidate creation without bypassing governance or adaptation safety controls

Routes / data changes:
- extended proposal fields: `origin`, `generation_source`, `confidence_label`, `confidence_score`, `generation_note`, `context_snapshot`, `generated_at`, `regenerated_from_proposal_id`, `is_generated`, `originLabel`
- extended list route: `GET /api/proposals` now supports `origin`
- extended write/update routes: `POST /api/proposals`, `PUT /api/proposals/:id` now preserve generated/manual provenance metadata
- new proposal generation route: `POST /api/tasks/:id/generate-proposal`
- task history events added: `proposal_generated`, `proposal_generation_regenerated`, `proposal_generation_context_saved`

Verification:
- `python3 -m py_compile /root/agentforge/server.py`
- extracted inline JS + `node --check`
- real API smoke for generated draft creation, generated/manual provenance, confidence/context metadata persistence, dedupe on repeated generation, task-linked proposal retrieval, `origin=generated` filtering, and generated proposal movement into the normal governance path
- browser QA from the live task workspace with the same task reopened from list/board, Proposals tab generation visible, generated-draft metadata rendered, generated proposal selected in place, and UI-driven send-for-approval plus approve flow verified with matching history entries
- cleanup sweep removed the temporary Phase 16 QA task, linked memory, linked proposal, and task events, then confirmed no lingering `Phase 16 QA Task` or generated Phase 16 proposal rows remained in API/DB verification checks
- live runtime confirmed on `http://127.0.0.1:50000` with the active `server.py` process serving the updated code path

Deferred:
- model-backed proposal synthesis beyond the current heuristic task-context generator
- batch candidate ranking / scoring across tasks
- autonomous approval or apply behavior

Next recommended phase:
- Implementation Phase 17 — Task Output Flow V1
- generated proposals now exist, but the next highest-value gap is making task deliverables durable, reusable, and visible inside the shared workspace instead of leaving output as shallow task-local text

### Implementation Phase 17 — Task Output Flow V1
Status: confirmed complete
Date: 2026-06-12

Changed files:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`
- `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`

What shipped:
- the shared task workspace Output tab now supports a real task-to-output generation flow instead of output fields behaving like shallow inline notes
- generated task outputs are now persisted as durable task-linked records with generator metadata, context summary snapshots, saved status, and linked run provenance
- output generation now creates and completes a real task-linked run so operators can inspect output generation as part of the same task lifecycle instead of losing that execution trace
- task detail/list payloads now surface saved output linkage consistently enough for the latest output and output count to round-trip through API and live UI state
- UI-driven output generation now survives reload/reopen through durable saved records instead of transient-only browser state

Routes / data changes:
- existing task output generation path now completes through a valid task-linked run lifecycle with `run_type='task_run'` and `run_purpose='task_output_generation'`
- task output records now link `source_run_id` to the actual generation run instead of a nullable/stale latest-run reference
- output persistence now uses normalized success-state values so task outputs and run completion metadata pass backend validation
- task run retrieval/listing now includes output-generation runs via `linked_task_id`, allowing `latest_run` and linked run summaries to reflect generated outputs correctly
- run purpose metadata now includes `task_output_generation` label/badge support for output-generation visibility in task-linked run surfaces
- task history confirms output lifecycle events through `output_generation_requested`, `output_generated`, `output_saved`, and `result_saved`

Verification:
- `python3 -m py_compile /root/agentforge/server.py`
- extracted inline JS + `node --check`
- real API smoke for task create, output generate/save, `output_count`, `latest_output`, `result_text`, linked `source_run_id`, completed run status, and output-history events
- browser QA from the live task workspace with task created from Tasks, Output tab opened, output generated from UI, saved output record rendered, and no browser console errors
- cleanup sweep removed the temporary browser-QA task and confirmed the live verification flow did not need to leave durable test clutter behind
- live runtime confirmed on `http://127.0.0.1:50000` with the active `server.py` process serving the updated code path

Deferred:
- richer output templates/types beyond the current V1 generator flow
- model-backed output generation/ranking instead of heuristic-only generation
- output analytics, comparison views, or bulk output workflows

Next recommended phase:
- Implementation Phase 18 — Vault Intelligence V1
- durable task outputs now exist as reusable artifacts; the next highest-value gap is stronger retrieval/synthesis across vault memory and saved task artifacts so future proposal/output quality can draw from more than local task context

### Implementation Phase 18 — Vault Intelligence V1
Status: reported complete / handoff ready
Date: 2026-06-26

Changed files:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`
- `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`

What shipped:
- ranked task-context retrieval now surfaces relevant vault memories and relevant saved outputs on the shared task record
- task detail/workspace payloads now carry `relevant_memories`, `relevant_outputs`, and `relevant_context_summary`
- output generation and proposal generation now both use ranked vault/output context instead of only shallow task-local context
- the shared task workspace now exposes a compact Relevant Context surface so operators can see reusable lessons and reference outputs from the same task flow

Routes / data changes:
- additive task detail fields: `relevant_memories`, `relevant_outputs`, `relevant_context_summary`
- additive retrieval helpers: ranked vault-memory lookup and ranked saved-output lookup by task context
- output generation path now defaults to `generation_source='heuristic_task_output_vault_intelligence_v1'`
- proposal generation path now defaults to `generation_source='heuristic_task_context_vault_intelligence_v1'`

Verification:
- `python3 -m py_compile /root/agentforge/server.py`
- extracted inline JS + `node --check`
- real API smoke on isolated live app `http://127.0.0.1:50001` confirmed task detail payload carries relevant context fields, ranked memory retrieval works, ranked saved-output retrieval works, output generation uses vault-intelligence metadata, and proposal generation uses vault-intelligence metadata
- browser QA on `http://127.0.0.1:50001` confirmed Tasks workspace shows Relevant Context, ranked memory/output content is visible, and the same shared task record remains usable across list/board flow
- at the time of this handoff, the primary app on `http://127.0.0.1:50000` still needed reload/restart before Phase 18 could be claimed live on the main port; this was later resolved in the Phase 19 closeout pass

Deferred:
- stronger ranking/model-backed retrieval beyond heuristic V1 matching
- explicit operator quality loop for marking whether the generated output was actually correct/useful
- main-port reload/restart was still pending at this Phase 18 handoff; resolved later in the Phase 19 closeout pass

Next recommended phase:
- Implementation Phase 19 — Functional Completion Loop V1
- Phase 18 improved context quality for outputs and suggestions; the next gap was letting the operator close the loop on whether the output was right, whether the suggestion helped, and whether the task was actually done from the same workspace

### Implementation Phase 19 — Functional Completion Loop V1
Status: confirmed complete on main port during stabilization / closeout pass
Date: 2026-07-06

Changed files:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`
- `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`
- `/root/agentforge/README.md`

What shipped:
- saved task outputs now carry explicit review state, review note, reviewer metadata, and optional linked proposal context
- the shared task workspace now separates `artifact saved` from `task complete` through a small operator-facing completion loop
- operators can mark the latest output as `needs_revision`, `usable`, or `approved` before completing the task
- task detail payloads now expose `completion_state`, `latest_output_review_status`, and `can_complete_from_workspace` so the UI and API agree on finishability
- the main-port runtime now exposes `GET /api/status` for lightweight truth checks
- this closeout pass also removed ambiguity around old side verification servers after confirming the real app should live on `127.0.0.1:50000`

Routes / data changes:
- new route: `GET /api/status`
- output review route active on main port: `POST /api/task-outputs/:id/review`
- task completion route active on main port: `POST /api/tasks/:id/complete-from-workspace`
- additive task fields: `completion_state`, `latest_output_review_status`, `can_complete_from_workspace`
- additive task output fields: `review_status`, `review_note`, `reviewed_by`, `reviewed_at`, `review_proposal_id`, `review_proposal_title`, `approved_at`, `revision_requested_at`

Verification:
- `python3 -m py_compile /root/agentforge/server.py`
- extracted inline JS + `node --check`
- real API smoke on main port `http://127.0.0.1:50000`: task create -> output generate -> output review (`usable`) -> complete-from-workspace -> task detail confirmed `completed`
- real HTTP proof on main port for `/` and `/api/status`
- port audit confirmed `50001` / `50002` were old verification servers and not the primary app; cleanup left the real app on `50000`

Deferred:
- stronger output quality/ranking beyond heuristic V1 generation
- tighter proposal-assisted revision flows beyond manual operator control
- deeper multi-step delegation/adaptation orchestration

Historical next recommendation, now superseded:
- Implementation Phase 20 — Output Intelligence V2
- superseded on 2026-07-16 after the product-usefulness audit showed that improving the heuristic output layer would deepen the wrong execution path before real Hermes work became the product center

### Product Reset A — Supervised Adaptive Workflow Re-anchor
Status: product direction approved on 2026-07-16; Reset B implementation now complete

Decision:
- preserve the existing task, review, memory, and history foundation
- replace the old task-management center with `Create Work -> generated workflow -> real Hermes execution -> human review/revision -> approved learning -> reusable workflow`
- use Hermes Kanban as the intended execution substrate rather than maintaining a second independent AgentForge execution state machine
- make the Knowledge Vault a trusted approved-memory layer, not a dump of raw generated output
- use the JobForge Application Pack as the recommended first real reference workflow

Continuity artifact:
- `docs/AGENTFORGE_PRODUCT_RESET_A.md`
- `docs/AGENTFORGE_PRODUCT_RESET_BUILD_PLAN.md`

### Product Reset B — Real Single-Profile Execution Proof
Status: **confirmed complete**
Date: 2026-07-16

Changed files:
- `/root/agentforge/hermes_kanban_adapter.py`
- `/root/agentforge/mission_service.py`
- `/root/agentforge/server.py`
- `/root/agentforge/index.html`
- `/root/agentforge/test_hermes_kanban_adapter.py`
- `/root/agentforge/test_mission_service.py`

What shipped:
- a safe argument-array adapter over supported `hermes kanban ... --json` commands on board `agentforge`
- durable AgentForge mission, step, artifact, and human-review persistence with Hermes task/run provenance
- a narrow research-only `Create Work` path with real Hermes state synchronization
- visible `Needs Input`, `Needs Review`, revision, completed, and failed attention states
- real artifact/source display and human approve/revision actions tied to the returned artifact

Routes / data changes:
- `GET|POST /api/missions`
- `GET /api/missions/:id`
- `POST /api/missions/:id/sync`
- `POST /api/missions/:id/review`
- `missions`, `mission_steps`, `mission_artifacts`, and `mission_reviews` tables in AgentForge-owned `board.db`

Verification:
- 10 adapter/service unit tests pass
- Python compile and extracted inline-JavaScript syntax checks pass
- idempotent API creation returned one mission and one Hermes task
- real gateway-dispatched research run `2` completed task `t_ebee2065` with official Python.org sources and tool evidence
- blocked-path QA produced `Needs Input` and zero artifacts; invalid profile produced HTTP `422`
- human approval persisted and repeated synchronization preserved `completed`
- main-port browser QA passed with zero JavaScript errors
- existing Tasks history remained visible and the pre-existing linked-output task deletion cleanup passed a create/output/delete regression
- temporary QA mission/task/run/output records were removed or archived; successful proof retained

Operational note:
- the first worker attempt exposed missing research-profile Codex auth; profile-local auth was restored from the already-authenticated master profile and the existing gateway dispatcher completed the retry
- the Hermes gateway was not restarted

## Reset C — Create Work + Planning Profile — complete (2026-07-16)

Delivered:
- calm goal-first `Create Work` intake with desired outcome, success criteria, context/links, priority, deadline, and staged attachments
- advanced implementation details demoted behind `Show Advanced`; no agent choice is required
- durable real Hermes task dispatch to profile `planning` through the existing safe Kanban adapter
- AgentForge-owned plan-version persistence with strict server validation for profiles, tools, dependencies, evidence, outputs, and human/audit gates
- visible specialist stage sequence, mission truth, retry/cancel handling, revision feedback, previous-plan history, and human plan approval
- approved plans stop at `queued`; downstream specialist dispatch is intentionally deferred to Reset D

Routes / data changes:
- `POST /api/missions/:id/plan-action`
- planning fields added to `missions`
- `execution_plans` table added to AgentForge-owned `board.db`
- `mission_steps` retains one mapped Hermes planning task per plan version

Verification:
- 18 adapter/service/planning unit tests pass
- Python compile and extracted inline-JavaScript syntax checks pass
- real planning mission `e68051e454d94999a1eae5c7b43fada5` produced plan v1 on task `t_7b4df93e`
- browser-driven revision feedback produced validated plan v2 on task `t_78efbb68`, preserving v1 and its feedback
- plan v2 added the requested explicit AUDIT gate and was approved by DV
- Kanban task count remained unchanged during approval, proving no Reset D execution tasks were dispatched
- production API, browser, console, ordinary 28-task history, attachment path, validation, blocked/malformed mapping, idempotency, cancel, retry, and Reset B regressions passed

Deferred:
- multi-profile execution of approved plans
- automatic AUDIT/revision task routing
- Vault learning and reusable workflow versions

Next planned reset:
- Reset D — Multi-Specialist Orchestration
- planned only; requires explicit DV authorization and must not start automatically

---

## 6) Where AgentForge is right now

Blunt status:
- **the existing persistence, task workspace, audit, memory, and review foundation is real**
- **real Hermes research execution and real planning-profile workflow generation are now proven end to end** through Resets B and C
- the broader product is still incomplete: multi-specialist orchestration, independent audit/revision, trusted learning, and reusable workflow versions remain future resets
- Product Reset A remains the product contract; Resets B and C are complete and Output Intelligence V2 remains superseded
- no later reset is authorized automatically

Functional-completion target:
- AgentForge should feel complete when a user creates work, receives a clear specialist workflow, lets real Hermes profiles execute it, reviews and corrects the delivered artifact, approves trusted learning for the Vault, and can reuse the improved versioned workflow later.

What feels strongest now:
- task creation
- Kanban on the shared task model
- runs/history visibility
- task workspace foundation
- durable task output generation and saved output readback
- relevant context surfacing inside the shared workspace
- output review + completion gating on the main port
- task-level audit workflow
- manual parent/child delegation inside the task workspace
- task-linked memory capture and retrieval
- task-linked proposal capture plus generated draft creation
- approval-governed proposal review and application controls
- durable applied adaptation execution with observable lifecycle state

What is still clearly missing from the canon product:
- full Agents overhaul
- deeper Delegation / subtask tree
- deeper Audit beyond V1
- deeper task workspace richness beyond V1
- deeper vault intelligence beyond heuristic V1 ranking/synthesis
- stronger output generation quality so the deliverable is closer to the right final answer
- higher-quality proposal synthesis beyond heuristic V1 generation
- richer proposal-to-output revision assistance beyond the current manual operator loop
- multi-step adaptation orchestration beyond operator-driven V1 execution

---

## 7) Recommended next build direction

### Confirmed next reset stage
**None automatically. Reset D — Multi-Specialist Orchestration is planned and awaits explicit DV authorization.**

Full Reset B–I scope, acceptance gates, verification, architecture rules, and standard DEV prompt:
- `docs/AGENTFORGE_PRODUCT_RESET_BUILD_PLAN.md`

Reset B proof now retained:
1. mission `82661edd618c484a96c7fe11bb3bf787` stores outcome, success criteria, and context
2. Hermes task `t_ebee2065` is durably mapped on board `agentforge`
3. real profile `research` completed run `2`
4. the returned Python.org research artifact includes sources and provenance
5. blocked-path QA became `Needs Input` with zero artifacts
6. the artifact entered `Needs Review`
7. human approval persisted and synchronization preserved `completed`

Reset C proof now retained:
1. planning mission `e68051e454d94999a1eae5c7b43fada5` stores goal-first intake and attachment provenance
2. real `planning` tasks `t_7b4df93e` and `t_78efbb68` produced validated plan versions 1 and 2
3. browser-submitted revision feedback is preserved against plan v1
4. plan v2 includes allowed specialist profiles, dependencies, evidence/tool requirements, and explicit HUMAN/AUDIT gates
5. DV approval moved the mission to `queued` without creating any downstream execution task

Architecture constraints:
- use Hermes Kanban through an explicit adapter and durable ID mapping
- do not write directly to two competing execution state machines
- do not label AgentForge lifecycle rows or heuristic templates as real worker execution
- preserve the pre-existing `server.py` working-tree change until its ownership is understood

Deferred to later explicitly authorized resets:
- multi-agent workflow generation
- automatic AUDIT and revision routing
- reusable workflow creation/versioning
- approved Vault-learning suggestions
- the JobForge end-to-end reference workflow
- main navigation simplification and advanced-module demotion

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

AgentForge is a supervised workflow and memory layer for a persistent team of Hermes specialists.

Current reality:
- Tasks + Kanban are real
- Runs/history are strong
- Task Workspace V1 is real
- Audit V1 is real
- Delegation V1 is real
- Memory Vault V1 is real
- Task Output Flow V1 is real
- Vault Intelligence V1 is real on the main port
- Proposals V1 is real
- Approval-Governed Adaptation V1 is real
- Applied Adaptation Execution V1 is real
- Proposal Automation V1 is real
- Functional Completion Loop V1 is now real on the main port
- Reset B real single-profile Hermes execution is proven on the main port

Approved product loop:
- `Create Work -> AgentForge designs workflow -> real Hermes specialists execute -> AUDIT/human review -> revision -> approval -> trusted Vault learning -> reusable versioned workflow`

Main missing product layers:
- reliable multi-profile handoffs and quality gates
- targeted revision routing from human feedback
- approved learning capture into the Knowledge Vault
- reusable workflow creation and versioning from successful missions

Current roadmap state:
- **Reset B — Real Single-Profile Execution Proof: complete**
- **Reset C — Create Work + Planning Profile: complete**
- full finish line: **5 remaining core build phases (D–H) plus Reset I hardening/completion**
