# AgentForge Handoff Checklist

Purpose: tiny post-phase checklist so DEV/AUDIT do not forget continuity-critical steps.

---

## After every completed phase

### 1) Backup before edits
If editing these files, create timestamped backups first:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`

Backup pattern:
- `/root/agentforge/backups/index_v{version}_{YYYY-MM-DDThh-mm}.html`
- `/root/agentforge/backups/server_v{version}_{YYYY-MM-DDThh-mm}.py`

### 2) Implement the phase
Expected main live files:
- `/root/agentforge/index.html`
- `/root/agentforge/server.py`

### 3) Verify for real
Minimum verification:
- `python3 -m py_compile /root/agentforge/server.py`
- extract inline JS from `index.html` and run `node --check`
- API smoke for the new behavior
- browser QA on `http://127.0.0.1:50000`
- verify updated code is actually serving live

### 4) Update canon immediately
Update:
- `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`

Must update these sections:
- `Current implementation sequence`
- `Where AgentForge is right now`
- `Recommended next build direction`
- `Short canonical summary`

Add the new phase entry using the canon template.

### 5) Commit and push
Required git flow:
- review changed files
- commit with a phase-specific message
- push to `main`

### 6) Handoff summary must include
- phase number and name
- commit SHA
- commit message
- push result
- changed files
- backups created
- what shipped
- routes / fields changed
- what was verified
- runtime status
- intentionally deferred items
- next recommended phase

---

## Rule
A phase is not really done until:
1. implementation works
2. verification passed
3. canon file is updated
4. git commit/push is done
5. handoff summary is written
