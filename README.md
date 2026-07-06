# AgentForge

AgentForge is a local task-centered workforce OS for Hermes operations.

## Verified current surface

- **Tasks + Kanban** share one task model.
- **Task workspace** opens the same task from list or board with Overview, Thread, Output, Memory, Proposals, Audit, Delegation, and History.
- **Functional completion loop** is live on the main app: generate a saved output, review it (`needs revision` / `usable` / `approved`), then complete the task from the workspace.
- **Runs** are persisted and inspectable.
- **Agents, Playbooks, and Deployments** have live API-backed surfaces.
- **AI Ops / snapshot view** is fed by gateway, cron, session, VPS, and kanban snapshot data.
- **Vault library and knowledge graph** are present.

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
- Timestamped backups live under `backups/`
- Local databases, caches, backups, and environment files are intentionally not committed
