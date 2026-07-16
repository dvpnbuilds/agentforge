# AgentForge

AgentForge is the supervised workflow and memory layer for a persistent team of Hermes specialists.

The user creates work by describing an outcome. AgentForge plans the specialist workflow, routes durable execution through Hermes, returns the artifact for human review, and turns approved feedback into trusted Vault knowledge and reusable versioned workflows.

Current product reset contract: [`docs/AGENTFORGE_PRODUCT_RESET_A.md`](docs/AGENTFORGE_PRODUCT_RESET_A.md)

DEV-ready phase plan: [`docs/AGENTFORGE_PRODUCT_RESET_BUILD_PLAN.md`](docs/AGENTFORGE_PRODUCT_RESET_BUILD_PLAN.md)

## Verified current surface

- **Tasks + Kanban** share one task model.
- **Task workspace** opens the same task from list or board with Overview, Thread, Output, Memory, Proposals, Audit, Delegation, and History.
- **Functional completion loop** is live on the main app: generate a saved output, review it (`needs revision` / `usable` / `approved`), then complete the task from the workspace.
- **Runs** are persisted and inspectable.
- **Agents, Playbooks, and Deployments** have live API-backed surfaces.
- **AI Ops / snapshot view** is fed by gateway, cron, session, VPS, and kanban snapshot data.
- **Vault library and knowledge graph** are present.

These surfaces remain the existing foundation. Resets B and C add a narrow real-execution spine plus real planning without pretending the full multi-profile product is complete.

## Reset B — verified real execution proof

The Tasks screen now includes a `Create Work` proof path for research-shaped missions:

- mission intent, success criteria, and context persist in AgentForge
- `hermes_kanban_adapter.py` creates and reads a durable task on Hermes board `agentforge`
- the task is assigned to the real `research` profile
- Hermes Kanban remains execution truth; AgentForge stores mapping, artifact, review, and attention state
- a completed Hermes result becomes a provenance-bearing AgentForge artifact
- blocked work maps to `Needs Input` without a fabricated artifact
- approve/revision decisions persist against that artifact

Verified proof retained for DV/AUDIT inspection:

- AgentForge mission: `82661edd618c484a96c7fe11bb3bf787`
- Hermes task: `t_ebee2065`
- Hermes board/profile/run: `agentforge` / `research` / `2`
- real sources: `python.org/downloads/` and the Python `3.14.6` release page
- human state: approved / completed

API surfaces:

- `GET|POST /api/missions`
- `GET /api/missions/:id`
- `POST /api/missions/:id/sync`
- `POST /api/missions/:id/review`
- `POST /api/missions/:id/plan-action`

## Reset C — verified real planning workflow

The Tasks screen now defaults to a calm goal-first Create Work path:

- desired outcome and success criteria are required; context, links, attachments, priority, and deadline are supported
- a real Hermes `planning` task proposes a strict server-validated specialist workflow
- plans show profile ownership, scoped responsibilities, outputs, dependencies, evidence/tool requirements, final deliverable, and HUMAN/AUDIT gates
- malformed or unsupported plans fail visibly and can be retried
- revision feedback creates a new planning task while preserving previous plan versions
- `Start` approves the plan only; no specialist execution task is created until Reset D

Verified proof retained for DV/AUDIT inspection:

- AgentForge mission: `e68051e454d94999a1eae5c7b43fada5`
- planning tasks: `t_7b4df93e` (v1) and `t_78efbb68` (v2)
- final state: plan v2 approved / mission queued
- v1 revision feedback and explicit v2 AUDIT gate are retained

Reset D is planned but is **not authorized or started automatically**. Output Intelligence V2 remains superseded by the Product Reset roadmap.

## Runtime

- Local URL: `http://127.0.0.1:50000`
- Health/status: `http://127.0.0.1:50000/api/status`
- Backend entrypoint: `server.py`
- Frontend shell: `index.html`

## Local dev

```bash
cd /root/agentforge
python3 server.py
```

The app binds to `127.0.0.1:50000` by default.

## Repo notes

- Main continuity doc: `docs/AGENTFORGE_PHASE_CANON.md`
- Product Reset A contract: `docs/AGENTFORGE_PRODUCT_RESET_A.md`
- Reset B–I DEV build plan: `docs/AGENTFORGE_PRODUCT_RESET_BUILD_PLAN.md`
- Timestamped backups live under `backups/`
- Local databases, caches, backups, and environment files are intentionally not committed
