# AgentForge Product Reset — DEV Build Plan

Date: 2026-07-16
Status: Reset B implemented and verified on 2026-07-16; Reset C remains planned and requires explicit DV authorization
Continuity sources:

1. `docs/AGENTFORGE_PHASE_CANON.md`
2. `docs/AGENTFORGE_PRODUCT_RESET_A.md`
3. this build plan

## 1. Build rule

DEV must execute **one reset phase at a time**. Do not combine phases, silently advance, or build later-phase UI early.

At the start of every phase:

1. Read all three continuity documents above.
2. Run `git status --short`, `git branch --show-current`, `git log -1 --oneline`, and `git diff --stat`.
3. Separate pre-existing changes from the current phase.
4. Before editing `index.html` or `server.py`, create the required timestamped backup in `/root/agentforge/backups/`.
5. Inspect the live API/data shape before changing it.
6. Preserve unrelated local work.

At the end of every phase:

1. Run backend and frontend syntax checks when those files changed.
2. Run the phase-specific API/integration smoke test.
3. Browser-QA every changed user flow.
4. Check the browser console.
5. Remove temporary QA tasks/artifacts and prove cleanup.
6. Update the canon, this build plan's phase status, README, and handoff checklist.
7. Review `git diff --check`, `git diff --stat`, and targeted diffs.
8. Report the branch, changed files, real verification results, runtime state, deferred items, and confirmed next phase.
9. Do not claim a phase shipped unless the requested commit/push actions actually completed.

## 2. Non-negotiable architecture rules

- **Real execution only:** an AgentForge run is not real merely because a lifecycle row or synthetic trace exists. A named Hermes profile must actually execute the work with real tools.
- **One execution source of truth:** Hermes Kanban owns executable step status, assignment, dependencies, claiming, retries, comments, run attempts, and completion.
- **No direct Kanban SQL writes:** the AgentForge integration must use an adapter over supported Hermes automation surfaces. Reset B should begin with `hermes kanban ... --json`, explicit `--board agentforge`, argument arrays without shell interpolation, strict timeouts, and JSON validation.
- **AgentForge owns the mission layer:** desired outcome, generated plan, review state, artifacts, human decisions, learning candidates, workflow versions, and operator UX.
- **Durable ID mapping:** every AgentForge mission step stores its Hermes Kanban task ID and board slug. Creation uses an idempotency key so retries cannot duplicate work.
- **No status masquerading:** cached Hermes state may be used for display performance only when marked with `last_synced_at`; it cannot become an independent writable execution state.
- **Human governance:** rejected output, unverified facts, raw drafts, and model-proposed structural changes never become trusted memory or reusable workflows automatically.
- **No gateway restart:** do not restart the Hermes gateway from DEV tooling. If a restart is required, report it for DV to perform manually.
- **Keep AgentForge stable:** the existing app on `127.0.0.1:50000` remains the primary runtime. Use an isolated verification port when the main process is stale, and report main-port versus isolated-port truth separately.
- **No early redesign:** prove the execution spine before broad visual cleanup or removing existing modules.

## 3. Known pre-build repository state

Baseline observed on 2026-07-16:

- branch: `main`
- HEAD: `b8a0ffa Close out Phase 19 stabilization and add runtime health check`
- Reset A docs/README changes are currently uncommitted
- `server.py` has a pre-existing uncommitted cleanup fix in `task_delete()`:
  - counts linked `task_outputs`
  - deletes linked `task_outputs`
  - records output cleanup in the deletion run metadata and summary

DEV must preserve this hunk. Do not reset or overwrite it. Before Reset B implementation, either isolate it in a dedicated baseline commit with DV's approval or explicitly carry it as pre-existing work and keep the Reset B diff separable.

## 4. Target mission model

The migration should evolve toward these product objects without requiring one large schema rewrite:

- **Mission** — desired outcome, success criteria, context, priority/deadline, human-facing state.
- **Execution Plan** — versioned proposed workflow, rationale, final deliverable, approval state.
- **Mission Step** — scoped profile responsibility, expected output, dependencies, Hermes task ID.
- **Artifact** — worker output, source/profile, provenance, version, review status.
- **Human Review** — approval, revision request, missing context, rejection, override reason.
- **Learning Candidate** — proposed fact, preference, lesson, or mistake-to-avoid awaiting approval.
- **Workflow Recipe** — approved versioned plan, matching conditions, inputs, stages, gates, and outcomes.

Existing `board.db` records remain historical/product metadata during migration. Do not destroy existing task/run history.

## 5. Reset roadmap

| Reset | Name | Deliverable | Status |
|---|---|---|---|
| A | Product Re-anchor | Approved product contract and architecture boundary | **Complete** |
| B | Real Single-Profile Execution Proof | One mission executes through a real Hermes profile | **Complete — verified 2026-07-16** |
| C | Create Work + Planning Profile | Goal-first intake and visible validated workflow proposal | **Planned — awaiting explicit authorization** |
| D | Multi-Specialist Orchestration | Durable dependencies, handoffs, parallel/ordered specialist work | Planned |
| E | Audit + Human Revision Loop | Independent audit, targeted revision, approval gate, Needs Input | Planned |
| F | Trusted Vault Learning | Human-approved memory candidates with provenance and retrieval | Planned |
| G | Reusable Workflow Versions | Successful missions become approved versioned workflow recipes | Planned |
| H | JobForge Application Pack | Real daily-use JobForge workflow and outcome feedback | Planned |
| I | Product Simplification + Hardening | Attention-first IA, migration cleanup, full E2E proof | Planned |

There are **6 remaining core build phases (C–H) plus 1 hardening/completion phase (I).**

---

# Reset B — Real Single-Profile Execution Proof

Status: **Complete — implementation and real-worker proof verified 2026-07-16**

## Objective

Prove that AgentForge can create one mission, route one scoped step to a real named Hermes profile through Hermes Kanban, receive the real result, and place the artifact into human review.

## Scope

- Add a small Hermes Kanban adapter as a separate backend module rather than scattering subprocess calls through `server.py`.
- Use the named Kanban board `agentforge`.
- Use `hermes kanban ... --json` as the initial automation transport.
- Allowlist supported adapter operations: initialize/list boards, create, show, list, comment, block/unblock, and read runs/logs as required.
- Use subprocess argument arrays, no `shell=True`, explicit timeout, safe body-size limits, and strict JSON/error handling.
- Add minimal mission/step mapping persistence in AgentForge.
- Add idempotency keys in the shape `agentforge:<mission_id>:<step_key>:<attempt_or_version>`.
- Add one narrow `Create Work` proof path that routes a research-shaped mission to the real `research` profile.
- Poll/read the Hermes task through the adapter and map real states into a mission summary.
- Persist the completion summary/result as an AgentForge artifact with Hermes task/run provenance.
- Show `Needs Input` when the Hermes task is blocked.
- Show `Needs Review` when a real artifact returns.
- Reuse the existing human approve/revision control only where it can be tied honestly to this real artifact.

## Out of scope

- Model-generated multi-step plans
- Multiple profiles on one mission
- Automatic AUDIT
- Vault learning
- Reusable workflows
- JobForge integration
- Broad navigation redesign

## Required proof mission

Use a safe research task that requires at least one real web/tool action and returns sources. It must be executed by the `research` Hermes profile, not by AgentForge's heuristic output composer.

## Acceptance criteria

- A real Hermes Kanban task exists on board `agentforge` and is linked to the AgentForge mission.
- Retrying mission creation does not duplicate the Kanban task.
- The gateway dispatcher launches the `research` profile.
- Hermes run history proves a real worker attempt.
- The returned artifact contains real researched content and provenance.
- Blocking the worker produces `Needs Input`; no invented answer is generated.
- Completion produces `Needs Review`.
- Human approve/revision action persists against the real artifact.
- No synthetic output is shown as the execution result.
- Existing Tasks/Kanban history still loads.

## Verification

- Unit tests for adapter command construction, JSON parsing, timeout, non-zero exit, malformed JSON, and idempotent create handling.
- API smoke: mission create -> Hermes task mapping -> real task show/runs -> artifact -> review state.
- Failure smoke: invalid profile or blocked task produces a readable operator error/Needs Input state.
- Browser QA of the proof path plus console check.
- Main-port truth reported separately from any isolated test port.

## Exit gate

Exit evidence retained for DV/AUDIT inspection:

- AgentForge mission `82661edd618c484a96c7fe11bb3bf787`
- Hermes board/task `agentforge` / `t_ebee2065`
- completed Hermes run `2`, profile `research`, with terminal/web retrieval evidence
- real artifact sourced from `https://www.python.org/downloads/` and `https://www.python.org/downloads/release/python-3146/`
- persisted human approval with final mission state `completed`
- idempotency retry returned the same mission and Hermes task
- blocked-path QA mapped to `Needs Input`, included the real block reason, and created zero artifacts
- invalid `dev` profile request returned HTTP `422`
- main-port browser QA showed the artifact, provenance, sources, and approved state with zero JavaScript errors
- existing task-output deletion cleanup was regression-tested: one linked output existed before task deletion and zero remained after API deletion

Operational note: the first worker attempt exposed missing profile-local Codex credentials for `research`. The existing master Codex credential was installed into the research profile; the gateway dispatcher retried the same task and run `2` completed. The Hermes gateway was not restarted.

Temporary blocked-path and deletion-cleanup QA records were removed; the blocked Hermes fixture task was archived. The successful proof mission remains intentionally retained.

**Do not start Reset C without explicit DV authorization.**

---

# Reset C — Create Work + Planning Profile

Status: Planned

## Objective

Replace manual technical task setup with a calm goal-first intake and a real PLANNING-profile workflow proposal that the user can inspect before execution.

## Scope

- Build the default `Create Work` form with only:
  - desired outcome
  - success criteria / expected deliverable
  - context, links, attachments
  - optional priority and deadline
- Keep agent, playbook, queue, run, and low-level controls under Advanced.
- Dispatch a durable planning task to the `planning` Hermes profile.
- Require the planner to return a validated structured plan containing:
  - plan rationale
  - allowed profile per step
  - scoped responsibility
  - expected output
  - dependencies
  - evidence/tool requirements
  - final deliverable
  - audit/human gates
- Validate the plan server-side against installed allowlisted profiles and a strict schema.
- Display the plan as a simple stage sequence.
- Allow `Start`, `Request Plan Revision`, or `Cancel`.
- Do not dispatch execution steps until the plan is accepted.

## Out of scope

- Multi-profile execution of the accepted plan
- Automatic workflow reuse
- Vault learning
- JobForge trigger

## Acceptance criteria

- A user can create work without choosing an agent.
- PLANNING is real Hermes execution, not an in-process template.
- Malformed plans fail visibly and can be retried safely.
- Unsupported profile/tool assignments are rejected by server validation.
- The user can understand who will do what before pressing Start.
- Plan revisions preserve previous versions and feedback.

## Verification

- Valid plan, malformed plan, unsupported profile, missing success criteria, and attachment paths.
- Browser QA of create -> planning -> proposed plan -> revision/start.
- No execution step appears on Hermes Kanban before plan approval except the planning task itself.

---

# Reset D — Multi-Specialist Orchestration

Status: Planned

## Objective

Turn an approved plan into real durable specialist work with visible dependencies and handoffs.

## Scope

- Create one Hermes Kanban task per approved mission step.
- Assign only existing persistent profiles: `assistant`, `research`, `planning`, `dev`, `audit`, or an explicitly configured future profile.
- Link dependencies through supported Kanban commands.
- Support ordered and parallel steps.
- Pass only relevant mission context, approved Vault context, parent results, success criteria, and expected output to each step.
- Derive mission progress from Hermes step truth.
- Summarize progress without dumping raw telemetry by default.
- Surface failed spawn/retry/circuit-breaker states clearly.
- Preserve every step's task ID, run attempts, comments, and output provenance.

## Out of scope

- Automatic AUDIT verdict enforcement
- Human revision routing
- Vault writes
- Workflow templating

## Acceptance criteria

- One approved plan creates the exact expected graph once.
- Parallel steps can run independently.
- Dependent steps do not start before parents complete.
- Downstream workers receive parent summaries/provenance.
- One failed/blocked step does not falsely mark the mission successful.
- Closing AgentForge does not stop execution.
- Reloading AgentForge reconstructs the mission from persisted mappings and Hermes state.

## Verification

- Real two- or three-profile mission.
- Dependency-order proof from task events/run timestamps.
- Duplicate-start/idempotency test.
- Worker failure, retry, and blocked-state test.
- Browser QA of summarized stage progress and step detail.

---

# Reset E — Audit + Human Revision Loop

Status: Planned

## Objective

Make quality control and correction the central completion path.

## Scope

- Add an AUDIT step automatically when the plan requires factual, technical, external-facing, or otherwise reviewable output.
- Require a structured audit verdict: `pass`, `revision_required`, or `blocked`, with evidence, unsupported claims, omissions, and required corrections.
- Final human review actions:
  - Approve
  - Request Revision
  - Add Missing Context
  - Reject
  - Approve with explicit override reason when necessary
- Route revision to the responsible producer profile, not automatically to every worker.
- Create a new versioned revision step/artifact while preserving rejected versions.
- Attach human feedback, audit findings, source artifact, and success criteria to revision context.
- Map missing access/information into `Needs Input`.
- Prevent mission completion until required audit and human gates pass or an explicit override is recorded.

## Out of scope

- Durable Vault learning
- Reusable workflow generation
- JobForge integration

## Acceptance criteria

- AUDIT can reject unsupported or incomplete work.
- Rejected work returns to the correct worker with exact correction context.
- Old and revised artifacts remain inspectable.
- Human approval is the final authority.
- A blocked mission asks for missing information rather than guessing.
- Approval, override, rejection, and revision decisions are auditable.

## Verification

- One intentional unsupported-claim test that AUDIT rejects.
- One human revision round trip ending in approval.
- One Needs Input -> add context -> resume flow.
- Browser QA of artifact-first review, concise audit verdict, sources, warnings, and actions.

---

# Reset F — Trusted Vault Learning

Status: Planned

## Objective

Convert approved work and human corrections into trusted, reusable memory without polluting the Vault with raw model output.

## Scope

- After human approval, generate separate learning candidates for:
  - verified fact/decision
  - reusable context
  - preference
  - mistake to avoid
  - successful quality check
  - approved artifact reference
- Let the human edit, approve, or reject each candidate.
- Write only approved candidates through the existing secured Vault path under the appropriate agent/organizational namespace.
- Store provenance: mission, artifact version, sources, reviewer, approval date, and workflow version when available.
- Mark rejected/raw/unverified content as non-trusted and do not index it as trusted memory.
- Retrieve relevant approved Vault entries for future planning and show which memory influenced the plan.

## Out of scope

- Automatic workflow mutation
- Reusable workflow templates
- JobForge integration

## Acceptance criteria

- No Vault entry is created before explicit approval.
- A rejected candidate cannot appear in trusted retrieval.
- Approved memory can be recalled in a later related mission.
- The user can see why a memory matched and where it came from.
- Editing a candidate before approval changes only the proposed entry, not the original artifact.

## Verification

- Approve/edit/reject candidate flows.
- Traversal/symlink security tests for Vault writes.
- Retrieval test from a new mission.
- Cleanup of temporary Vault notes after QA.

---

# Reset G — Reusable Workflow Versions

Status: Planned

## Objective

Turn a successful corrected mission into an approved workflow recipe that can be suggested and improved across future runs.

## Scope

- Propose workflow creation only after final human satisfaction.
- Capture:
  - matching conditions/use case
  - required inputs
  - stage graph and assignments
  - stage instructions and expected outputs
  - tool/evidence requirements
  - audit and human gates
  - known failure/revision rules
- Require human approval before activation.
- Version every structural change; preserve prior versions and outcomes.
- Suggest matching workflows during Create Work without forcing them.
- Let the user inspect/override the suggested workflow.
- Record outcome quality, revisions, blocks, and approval result per run.
- Convert feedback into a workflow-improvement proposal, never a silent mutation.

## Out of scope

- JobForge-specific trigger
- Autonomous structural adaptation

## Acceptance criteria

- An approved mission can become workflow version 1.
- A similar new mission suggests version 1.
- A corrected second run can propose version 2.
- Version 1 remains inspectable and reusable until version 2 is approved.
- No feedback silently rewrites an active workflow.

## Verification

- First run -> approve workflow -> matching second run -> revision -> proposed v2 -> approve/reject v2.
- API and browser verification of version history and outcome metrics.

---

# Reset H — JobForge Application Pack

Status: Planned

## Objective

Prove daily usefulness through DV's real job-hunting workflow.

## Scope

- Add a safe JobForge-to-AgentForge intake contract using an API/webhook or an agreed local integration after inspecting `/opt/jobforge/JobForge`.
- Import a high-scoring listing with canonical source URL, normalized job data, score, and matching evidence.
- Run the real workflow:
  1. RESEARCH — company, product, role, and sources
  2. PLANNING — map requirements to DV's verified portfolio and identify gaps
  3. ASSISTANT — draft application package and outreach
  4. AUDIT — truth, relevance, unsupported claims, generic wording, and omissions
  5. DV — approve or request revision
- Save only approved application lessons/memory.
- Return application/outcome linkage to JobForge without auto-submitting an application.

## Out of scope

- Automatic job application submission
- Credentialed external writes without human approval
- Broad integration marketplace

## Acceptance criteria

- One real JobForge listing enters AgentForge without duplicate missions.
- The final pack uses only verified portfolio claims.
- Sources and reasoning are inspectable.
- Human revision updates the final package.
- Approval and later reply/outcome can link back to the same mission/workflow run.
- The workflow is useful enough for DV to run on a real application.

## Verification

- One safe test listing and one real listing with DV's approval.
- Duplicate webhook/idempotency test.
- End-to-end browser and API proof.
- Confirm no application was externally submitted by AgentForge.

---

# Reset I — Product Simplification + Hardening

Status: Planned

## Objective

Make the proven workflow calm, daily-usable, and portfolio-ready without hiding technical depth.

## Scope

- Make these the primary attention surfaces:
  1. Create Work
  2. Running
  3. Needs Input
  4. Needs Review
  5. Completed
- Move Agents, Playbooks, Runs, Deployments, raw telemetry, adaptations, and low-level controls under Advanced/System.
- Keep task detail artifact-first; show summarized stage progress by default and raw execution only on demand.
- Preserve historical AgentForge records.
- Clearly label or demote diagnostic, lifecycle-only, heuristic, seeded, and synthetic history.
- Back up before removing stale QA/demo data, and use semantic cleanup rather than broad deletion.
- Add recovery for duplicate dispatch, stale mapping, malformed planner output, worker timeout, blocked work, dispatcher failure, and unavailable profile.
- Complete security review for command arguments, attachments, Vault paths, API validation, and unsafe external actions.
- Add one deterministic end-to-end smoke script for the approved product loop.
- Update recruiter-facing README and Loom/demo script with honest architecture claims.

## Acceptance criteria

- The main screen answers: what is running, what needs DV, and what was delivered.
- A first-time viewer can complete Create Work without understanding agents or Kanban.
- The JobForge reference workflow passes end to end.
- Existing advanced surfaces remain reachable but do not dominate daily use.
- All core failure paths have visible recovery.
- No primary UI metric or status overstates real execution.
- Canon, README, live app copy, and runtime truth agree.

## Verification

- Full regression suite and syntax checks.
- Real end-to-end smoke: Create Work -> plan -> specialists -> audit -> revision -> approval -> Vault learning -> workflow reuse.
- Main-port browser QA at desktop and narrow viewport.
- Browser console and API error audit.
- Database cleanup verification and backup path recorded.
- Final git diff/commit/push/handoff verification.

---

## 6. Mission state presentation

AgentForge should present simple attention states while deriving execution truth from Hermes:

- **Planning** — planning task is running or plan awaits approval.
- **Queued** — plan approved; executable steps are todo/ready.
- **Running** — at least one executable step is running and no human blocker dominates.
- **Needs Input** — a step is blocked for human information, permission, or access.
- **Needs Review** — executable work/audit is ready for human judgment.
- **Revision** — a targeted correction step is active.
- **Completed** — required gates passed and human approved.
- **Failed** — unrecovered execution failure/circuit breaker; requires operator action.

AgentForge may store its human review state. It must not independently rewrite Hermes execution status to make the UI look complete.

## 7. Standard DEV invocation

Use this prompt when handing a phase to DEV:

> Read `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`, `/root/agentforge/docs/AGENTFORGE_PRODUCT_RESET_A.md`, and `/root/agentforge/docs/AGENTFORGE_PRODUCT_RESET_BUILD_PLAN.md` first. Re-anchor from live git/runtime state. Execute **only the confirmed next reset phase** and do not advance automatically. Preserve unrelated local changes, especially the pre-existing `server.py` task-output deletion cleanup. Create required timestamped backups before editing `index.html` or `server.py`. Build the real behavior, run the phase-specific verification and browser QA, remove temporary artifacts, update canon/README/build-plan status, then report exact evidence, changed files, runtime state, deferred items, and the confirmed next phase. Do not restart the Hermes gateway; report if DV must restart it manually.

For the immediate build, replace `confirmed next reset phase` with:

> **Reset B — Real Single-Profile Execution Proof**

## 8. Anti-drift rule

If a future implementation discovers that a planned transport, schema, or Hermes command differs from the live installed version, DEV must:

1. verify current Hermes docs and local CLI help,
2. adapt the narrow phase safely,
3. document the deviation and reason,
4. update this plan only after real verification,
5. not expand scope into the next phase.
