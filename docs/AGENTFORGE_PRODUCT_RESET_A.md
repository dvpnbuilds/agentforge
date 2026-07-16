# AgentForge Product Reset A — Supervised Adaptive Workflows

Date approved: 2026-07-16
Status: product direction approved; implementation not yet started

## 1. Product promise

AgentForge is the supervised workflow and memory layer for a persistent team of Hermes specialists.

A user creates work by describing the desired outcome. AgentForge decides how the work should be organized, chooses the appropriate specialist profiles, gives each worker a scoped responsibility, coordinates their handoffs, returns a reviewed deliverable, and learns from human feedback.

Short positioning:

> Chat tools help with one task. AgentForge runs a repeatable work process, preserves what was learned, and improves the next run.

AgentForge must not compete on generic chat, file handling, browsing, or one-agent task execution. Those capabilities are already available in Claude Cowork and ChatGPT. AgentForge differentiates through durable orchestration, specialist separation, human governance, reusable workflows, and approved organizational memory.

## 2. Primary user flow

### A. Create Work

The default form asks only for:

- desired outcome
- success criteria or expected deliverable
- relevant context, links, and attachments
- optional priority or deadline

Agent selection, playbook selection, queue selection, run fields, and low-level execution settings stay hidden under Advanced.

### B. AgentForge designs the workflow

AgentForge converts the request into a visible execution plan containing:

- stages and dependencies
- selected Hermes profile for each stage
- the exact responsibility of each profile
- expected output from each stage
- final deliverable
- quality and approval gates

Example:

1. RESEARCH gathers facts and sources.
2. PLANNING organizes the solution and defines constraints.
3. ASSISTANT or DEV produces the deliverable.
4. AUDIT checks evidence, correctness, omissions, and unsupported claims.
5. The responsible profile revises any failed quality checks.
6. Human review approves the final result or requests another revision.

The user can inspect and adjust the proposed plan before starting, but does not need to manually assign every worker.

### C. Real Hermes execution

The approved plan creates real durable Hermes work rather than simulated AgentForge runs.

- Named Hermes profiles execute scoped steps.
- Dependencies control order; independent steps may run in parallel.
- Every worker receives only the task context needed for its responsibility.
- Tool activity, blockers, decisions, artifacts, and handoffs are persisted.
- Closing AgentForge does not cancel the work.
- Missing access or missing information moves the mission to `Needs Input` instead of encouraging the model to guess.

Hermes Kanban is the intended execution substrate. AgentForge is the operator-facing workflow, review, artifact, and memory layer.

## 3. Hallucination-reduction model

AgentForge reduces hallucination risk through workflow design rather than claiming that multiple agents automatically guarantee truth.

Required controls:

- separate research, production, and audit responsibilities
- require sources or tool evidence for factual claims when applicable
- pass structured context and expected outputs between stages
- prevent a production worker from silently inventing missing inputs
- make blockers and uncertainty visible to the human
- let AUDIT reject unsupported claims or incomplete deliverables
- route rejected work back to the responsible stage with explicit correction instructions
- preserve source provenance and review history with the final artifact

The final human remains the approval authority.

## 4. Human review and learning loop

The review surface prioritizes the final artifact and shows:

- deliverable
- important sources and provenance
- AUDIT verdict
- unresolved warnings or assumptions
- concise execution summary

Human actions:

- Approve
- Request Revision
- Add Missing Context
- Reject

Revision feedback is attached to the same mission and routed to the correct worker. It does not create a disconnected new chat.

Feedback is classified into three levels:

1. **Task correction** — applies only to the current mission.
2. **Reusable preference or lesson** — proposed for Knowledge Vault capture.
3. **Workflow improvement** — proposed as a new version of the reusable workflow.

AgentForge must not silently rewrite agent instructions, workflows, or organizational memory. Durable changes require human approval.

## 5. Knowledge Vault advantage

Once the human approves the result, AgentForge proposes useful knowledge to save:

- approved final artifact
- verified facts and decisions
- reusable context
- human preferences
- mistakes to avoid
- successful quality checks
- links to the originating mission, sources, and workflow version

Only approved knowledge enters the trusted Vault. Raw drafts, rejected claims, and unverified model output must not become trusted memory by default.

Future work retrieves relevant approved Vault entries and shows what memory influenced the plan or output. This creates continuity across tasks instead of forcing the user to explain the same context again.

## 6. Reusable workflow lifecycle

A completed mission does not automatically become a reusable workflow. After the human is satisfied, AgentForge can propose converting it into a versioned workflow recipe containing:

- use case and matching conditions
- required inputs
- stage/dependency graph
- profile assignment per stage
- stage instructions and expected outputs
- required tools and knowledge sources
- audit and human approval gates
- known failure cases and revision rules
- workflow version and prior outcomes

Lifecycle:

`First run -> human corrections -> approved result -> proposed workflow -> human approval -> reusable workflow -> future measured runs -> versioned improvements`

Future matching work should suggest the approved workflow automatically while still allowing the user to inspect or override it.

## 7. Main product surfaces

The daily experience should center on five attention-oriented surfaces:

1. **Create Work** — goal-first intake.
2. **Running** — current missions and summarized stage progress.
3. **Needs Input** — blockers, missing information, and decisions waiting for the human.
4. **Needs Review** — completed deliverables awaiting approval or revision.
5. **Completed** — approved missions, artifacts, learned knowledge, and reusable workflows.

Agents, Playbooks, Runs, Deployments, raw telemetry, and adaptation controls remain available under an Advanced/System area. They are supporting depth, not the primary workflow.

## 8. Source-of-truth boundary

Target architecture:

- Hermes Kanban: executable work items, dependencies, assignment, claiming, worker state, comments, attachments, retries, and execution history.
- AgentForge: mission-level intent, generated workflow plan, human approvals, artifact presentation, review state, reusable workflow versions, Vault capture proposals, and operator experience.

AgentForge must use an explicit adapter and durable ID mapping. It must not maintain a second independent execution state machine that can disagree with Hermes.

The current AgentForge `board.db` model remains historical/product metadata during migration. Existing history should be preserved, but heuristic/template-generated runs must not be presented as real Hermes execution.

## 9. Reset A completion criteria

Reset A is complete when:

- this product contract is accepted as the new continuity anchor
- the old Phase 20 Output Intelligence V2 recommendation is marked superseded
- the product vocabulary and source-of-truth boundaries are defined
- the first real reference workflow is selected
- Reset B has a narrow proof target: `Create Work -> generated plan -> one real Hermes profile executes -> artifact returns -> human review`

## 10. First reference workflow

Recommended first workflow: **JobForge Application Pack**.

A high-scoring JobForge listing becomes a mission. RESEARCH investigates the company and role, PLANNING maps the opportunity to DV's verified portfolio, ASSISTANT drafts the application package, AUDIT checks truth and relevance, and DV approves or requests revision. Approved lessons and outcome data are saved for future applications.

This gives AgentForge a real daily use case while proving the general supervised-workflow architecture.
