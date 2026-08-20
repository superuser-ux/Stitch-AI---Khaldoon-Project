# Backlog Triage After #24 Closure (2026-07-05)

Author: CC (read-only triage; no GitHub/DB/code mutation)
`origin/main`: `c682620` · Prompt: "Read-Only Backlog Triage After #24 Closure — CC only (OR)"
Open issues: **19** (#5–#23).

---

## Recommendation (one line)

**Do #12 next** — "retain previous stage summary" stale-state bug. It is the only open *correctness* item in the frontend-doable set, it is demo-facing, and it is the **completion dependency of the #24 item-5 forward-transition affordance just shipped** (clicking `Next: {stage} →` can currently land on the previous stage's stale `complete` summary). Autonomously executable with the systematic-debugging guardrail.

---

## Open issue table

| # | Title (short) | Area | Prio | Category | Impl risk | Autonomous? | Owner decision first? |
|---|---------------|------|------|----------|-----------|-------------|-----------------------|
| **12** | Retain previous stage summary on stage nav | review-ui | (none) | **Correctness/UX bug** | **Low** (frontend; report says API state is correct) | **Yes** + systematic-debugging | No — correct behavior is unambiguous |
| 23 | Runtime generation-mode visibility (live/stub/demo) | ops | p1 | Demo-safety / process | Low (surface existing `/health` writer flag) | Yes | No (banner placement is a minor choice) |
| 17 | Refine/suppress low-signal 'Why now' | review-ui | (none) | Demo polish | Low (frontend display) | Yes | Light — keep-improve vs suppress (has a safe default: suppress placeholder) |
| 15 | Persist working view across entry/stage | review-ui | (none) | UX friction | Low–med (localStorage already exists) | Yes | Light — "last-used vs Overview" default |
| 22 | Scripts card hero = topic hook not script line | review-ui | (none) | Display correctness | Med (script opening lives in `script.structure.hook`; may need a tiny read in the gate-target query) | Partial | Some — which script field is the hero |
| 20 | Consolidate review header → sticky control bar | review-ui | p1 | **Layout/IA redesign** | **Med–high** (shared layout; multi-direction) | **No — design/IA preflight first** | **Yes** — IA direction; now also carries the two deferred #24 layout notes |
| 14 | Inline edit on review items | review-ui | (none) | Feature (edit path) | **High** — needs an in-place-edit **backend write + audit** path | No | **Yes** — audit/versioning model |
| 16 | Filter/search/sort review cards | review-ui | (none) | Feature | Med–high (larger surface) | Partial | Some — control scope |
| 13 | Demo persona login surface | review-ui/admin | (none) | Demo feature | Med | Partial | **Yes** — session/persona model |
| 5 | Ops health & demo-safe preflight | ops | p1 | Process | Low–med (`tools/dashboard-health-check.sh` exists) | Yes (scriptable) | No |
| 6 | Workflow governance & admin-surface hardening | workflow-admin | p1 | Admin/backend | High | No | Yes |
| 7 | Calendar / numbering / content-type alignment | planner | p1 | Backend/data | High | No | Yes |
| 8 | Telegram control-channel hardening | telegram | p1 | Integration | High | No | Yes |
| 9 | Approval semantics completion (ANY/ALL, snapshots) | workflow-admin | p1 | Backend/semantics | High | No | Yes |
| 10 | Approval identity hardening (server-resolved actor) | workflow-admin | p1 | Backend/security | High | No | Yes |
| 11 | Agent-first cowork surface | review-ui/admin | (none) | Large redesign | High | No | Yes |
| 18 | Run management surface (edit/archive/delete) | planner | (none) | Feature + backend | High | No | Yes |
| 19 | Make multi-agent/model architecture explicit | agents | p1 | Documentation | Low | Yes (docs) | Light |
| 21 | Agent binding governance (IAM/Agent Rep) | workflow-admin/agents | p1 | Backend/governance | High | No | Yes |

Category legend: product-facing = review-ui feature/polish; demo-facing = affects a client walkthrough; process/ops; backend/semantics; layout/IA.

## Ranked shortlist (frontend-doable, demo-value, autonomous)

1. **#12 — stale stage summary** — correctness bug, demo-facing, protects the just-shipped #24 item-5 affordance. **← next.**
2. **#23 — generation-mode visibility** — demo *safety* (stub output must not be silently misread); surfaces an existing `/health` writer flag. High value if any client demo is near.
3. **#17 — 'Why now' low-signal suppression** — quick demo polish; placeholder text currently reads as unfinished.
4. **#15 — persist working view** — friction reduction across stage changes; localStorage plumbing already exists.
5. **#22 — Scripts hero line** — display correctness, but likely needs a tiny gate-target read (script opening field) → verify frontend-only before starting.

Everything p1/backend (#6–#10, #21, #7, #8, #18) and the large redesigns (#11, #20, #14, #16, #13) need owner/product decisions and are not autonomous.

## Recommended next issue — #12

### Why
- **Only correctness bug** among the frontend-doable set (others are polish/features). Live-review confusion + "next stage looks unavailable" is a demo-visible defect.
- **Dependency completion:** #24 item 5 shipped a `Next: {stage} →` affordance; #24 explicitly cross-referenced #12 so that forward navigation "does not land on a stale summary." Fixing #12 closes that loop and hardens what was just merged.
- **Frontend-only & bounded:** the issue notes the API reports the correct next-stage state — so the defect is client-side (stale `stageState` / snapshot not refreshing on cross-stage nav). `setStageKey` already `setStageState(null)` + `reassertStageSnapshot(...)`; the bug is likely a stale snapshot restore or a missed refetch — a contained root-cause hunt.

### Autonomy level
**Autonomous with guardrails.** Correct behavior is unambiguous (the next stage must show its real `generate`/`start_review` action, never the previous stage's summary), so no owner decision is needed to start.

### Stop gates
- **Systematic-debugging first** — root-cause the stale-state path (is it `reassertStageSnapshot` restoring a cached `roundStates` snapshot? a missed load() after cross-stage nav?) before any fix. No guessing.
- **Do not weaken the #3 stabilization guard** — the #3 fix made "re-selecting the *current* stage" a no-op to avoid blanking `changes`/`dropped`. #12 is *cross-stage* nav; the fix must not re-introduce the same-stage blanking that #3 closed. If the only fix risks that guard → **stop and report.**
- **Frontend-only** — if the root cause turns out to be a backend/API stale response (contradicting the issue's premise) → **stop and report** (scope changes).
- Standard: `tsc` clean; targeted specs (`co-creation`, `content-handoff-flow`, `integrity-and-dispositions` cover stage nav) + full Chromium pack; **isolate any flake** before classifying; one branch / one PR / `Refs #12`.

### Owner decision needed first?
**No.** Proceed autonomously on #12. (If you would rather prioritize *demo safety*, #23 is the alternative — but it's process/ops, not the correctness+dependency win #12 is.)

## Suggested next directive

> "Fix #12 (stale previous-stage summary) — CC only (OR) — Root-cause(1st), Fix(2nd), Validate(3rd), PR(4th). Frontend-only; systematic-debugging first; do not weaken the #3 same-stage guard; one PR `Refs #12`; stop if the fix requires backend or risks the #3 guarantees."

## Attestation
- Read-only: `gh issue` reads only. No GitHub mutation, no DB, no code, no PR, no cleanup, no handoff persistence, no Pi.
- #20 classified as **design/IA preflight**, not direct implementation, per constraint.
- Housekeeping (DB clutter, 6 local handoff docs) left deferred. This report is uncommitted.
