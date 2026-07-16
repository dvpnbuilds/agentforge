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

For the Product Reset track, read before implementation:
- `/root/agentforge/docs/AGENTFORGE_PRODUCT_RESET_A.md`
- `/root/agentforge/docs/AGENTFORGE_PRODUCT_RESET_BUILD_PLAN.md`

Execute only the confirmed next Reset phase. Do not combine phases or advance automatically.

### 3) Verify for real
Minimum verification:
- `python3 -m py_compile /root/agentforge/server.py`
- extract inline JS from `index.html` and run `node --check`
- API smoke for the new behavior
- browser QA on `http://127.0.0.1:50000`
- verify updated code is actually serving live
- if the phase used smoke/temp artifacts, clean them up and confirm they no longer appear in DB/API/UI results before closeout
- if cleanup removes parent records that may leave linked child artifacts behind (for example proposals/adaptations), verify orphan cleanup too instead of assuming cascade behavior
- if the phase adds approval/governance workflow, verify the full state path and its history events, not just field writes

### 4) Update canon immediately
Update:
- `/root/agentforge/docs/AGENTFORGE_PHASE_CANON.md`
- `/root/agentforge/docs/AGENTFORGE_PRODUCT_RESET_BUILD_PLAN.md` when a Reset phase status changes

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
- branch
- changed files
- backups created
- what shipped
- routes / fields changed
- what was verified
- runtime status
- cleanup result
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

---

## Latest handoff — Reset B (2026-07-16)

- Phase: Reset B — Real Single-Profile Execution Proof
- Branch: `main`
- Baseline HEAD: `b8a0ffa Close out Phase 19 stabilization and add runtime health check`
- Backups:
  - `backups/index_vreset-b_2026-07-16T13-51.html`
  - `backups/server_vreset-b_2026-07-16T13-51.py`
- Runtime: `agentforge.service` active on `127.0.0.1:50000`
- Proof mission/task/run: `82661edd618c484a96c7fe11bb3bf787` / `t_ebee2065` / research run `2`
- Verification: 10 unit tests, Python/JS syntax, API idempotency, real worker, blocked path, invalid profile, human review persistence, browser/console, existing Tasks regression, and linked-output deletion cleanup all passed
- Cleanup: blocked fixture mission removed, blocked Hermes task archived, deletion fixture task/output/runs removed; successful proof retained for inspection
- Gateway: not restarted
- Deferred: every Reset C+ capability
- Next: Reset C is planned but requires explicit DV authorization; do not start automatically
