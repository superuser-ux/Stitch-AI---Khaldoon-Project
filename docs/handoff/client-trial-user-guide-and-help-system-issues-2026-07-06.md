# Client Trial User Guide + Deferred Help-System Issues

Author: CC · Date: 2026-07-06
Prompt: "Client Trial User Guide + Deferred Help-System Issues — CC only (OR)"
Result: **Client guide, feedback template, PDF, and 8 screenshots produced from the locked client surface; 3 deferred help-system issues created. Ready for owner review — NOT sent to the client.**

---

## 1. Preflight (all green)

| Surface | State |
|---------|-------|
| Client dashboard `:3002` | 200 · locked (admin `/workflows`,`/methodology` → 307) · banner + "Generation: Live" · points to trial API `:8012` (`DB_NAME=tanaghom_trial`) |
| Trial rounds visible | 3 (R1 topic-approved, R2 3 fresh topics, R3 stray "Test_Run") |
| Operator `:3001` / dev `:3000` | not used for capture |

No secrets, ports, admin routes, provider names, or env values appear in any screenshot or in the client guide.

## 2. Artifact paths (uncommitted)

```
artifacts/client-trial-guide/
├── Tanaghom_Client_Trial_User_Guide_2026-07-06.md      (client guide, 11 sections)
├── Tanaghom_Client_Trial_User_Guide_2026-07-06.pdf     (6 pages, ~2.1 MB — pandoc+wkhtmltopdf)
├── Tanaghom_Client_Trial_Feedback_Template_2026-07-06.md
└── screenshots/
    ├── 01-landing.png          (dashboard on the clean R2 round + banner)
    ├── 02-live-banner.png      (banner + "Generation: Live" closeup)
    ├── 03-round-selector.png   (round picker)
    ├── 04-review-entry.png     (status summary + review-entry)
    ├── 05-review-cards.png     (review surface with cards)
    ├── 06-topic-card.png       (topic card anatomy — real live hook + Approve/Request/Drop)
    ├── 07-request-change.png   (request-change note dialog, typed, not submitted)
    └── 08-admin-blocked.png    (admin route bounced back to dashboard)
```

**Not committed** (per directive). Artifacts live under `artifacts/` (not git-ignored, but I used explicit `git add` paths only and staged nothing).

## 3. Screenshots — what was captured vs deferred

**Captured (8)** — all from the locked client surface, with **no new live-generation calls** and **no mutation of the fresh client round** (opening a review gate is non-destructive; the request-change dialog was opened but not submitted).

**Deferred (need a live/transient state):**
- **Script-stage card** — requires generating a script (a live-model call). Guide has a placeholder note; capture in a session once a script exists, or approve a one-off live-gen pass.
- **Regenerate progress** and the **"just approved" confirmation lane** — transient states that appear only during/after a live action. Described in text in the guide.

These were deferred deliberately: the directive says to stop and ask before generating additional live content for screenshots.

## 4. Feedback path

- Provided as a **markdown template** (`…Feedback_Template…md`) with 10 sections (impression, usability score, topic/script quality, confusing moments, bugs, screenshots, missing functionality, operational-fit, top-3 improvements).
- **No Google Doc / Form created or shared** (needs owner authorization). Recommend the owner pastes the template into a shared Google Doc for the first trial, or uses it as-is over email.

## 5. Deferred GitHub issues (created)

| # | Title | Labels |
|---|-------|--------|
| **#44** | Integrated in-app guided tour for client and operator onboarding | enhancement · area:client-onboarding · priority:p2 |
| **#45** | Contextual product help copilot for Tanaghom | enhancement · area:help-copilot · priority:p2 |
| **#46** | Living user guide and product-help source of truth | documentation · area:product-docs · priority:p2 |

Scoped non-overlapping: #44 = in-product guided tour, #45 = ask-questions copilot, #46 = the docs source-of-truth both draw from. Each links the relevant dependencies (#13 role model, #20 layout, and each other). Three new labels (`area:client-onboarding`, `area:help-copilot`, `area:product-docs`) were created.

## 6. Limitations / notes for owner

1. **Stray round in the client view** — `R3 "3 d Test_Run (2 p/d)"` (RESERVED, no topics) shows up in the client's round selector and is not a client-friendly name. Purge was out of scope here; **recommend removing R3 (and confirming only R1/R2 remain) before sending access** — I can do a guarded trial-DB-only purge on your word.
2. **Access URL is a placeholder** in the client guide (`[Client Trial URL — to be provided separately]`). The current working URL is the public funnel **`https://mac-2-608.taile18f28.ts.net/`** (operator-only info — kept out of the client doc). Fill it in (or your final URL) before sending.
3. **Support contact** placeholder in the guide — fill before sending.
4. **Script screenshot** — add after a script is generated (see §3).

## 7. Is the guide ready?

**Ready for owner review.** It accurately describes the locked client experience and the new button copy ("Review Topics" / "Generate Scripts"). It is **not** client-ready-to-send until the placeholders (§6.2–6.3) are filled and the stray R3 round (§6.1) is cleaned.

## 8. Exact owner action needed before sending to client

1. **Fill the URL + support contact** placeholders in the guide (`.md` and re-export `.pdf`, or tell me the values and I'll do it).
2. **Approve removing the stray R3 round** so the client selector is clean.
3. *(Optional)* approve a one-off live script generation so I can add the script-card screenshot.
4. **Choose the feedback channel** (shared Google Doc recommended) — I did not create one.
5. Then send the client: the **PDF guide + feedback doc link + the URL/access note** (access note drafted in the Phase-4 report).

## 9. Attestation

- Screenshots captured **only** from the locked client dashboard `:3002`; no operator/admin/dev surface shown; no secrets/ports/provider/env in any artifact.
- **No new live-generation calls** made; no fresh client round mutated; no trial purge; no client access sent; no credentials created.
- Deferred features (tour/copilot/docs system) were **not implemented** — only captured as issues #44/#45/#46.
- Artifacts **not committed**; no `git add .`; no `.env*` touched; no Pi. This report is uncommitted. `origin/main` unchanged (`e3ba1e4`).

---

# Addendum (2026-07-06) — operator guide, cleanup, and roadmap

## 10. Operator & admin guide (produced)

`artifacts/operator-admin-guide/` — internal (operator/admin), captured from the **unlocked** dev surface `:3000` (rich admin data):
- `Tanaghom_Operator_Admin_Guide_2026-07-06.md` + `.pdf` (5 pages, ~1.5 MB) — 12 sections (surfaces, generation-mode safeguard, dashboard tour, planner, persona switching, review flow, lenses, methodology admin, workflow admin, operational notes, cautions).
- `screenshots/` (8): operator dashboard, new-run planner, persona switcher, overview lens, workflow lens, methodology admin, workflow admin, generation-mode stub banner.
- Marked **internal — not for clients** (includes admin routes, surfaces, ports, trial-stack notes).

## 11. Cleanup performed (owner-authorized)

- **Stray round R3 ("3 d Test_Run") purged** from the trial DB only — snapshot first (`trial_pre_r3purge_2026-07-06.dump`, 147 KB), FK-safe transaction with a label guard (aborts if R3 isn't the Test_Run), deleting 6 gate_targets + 6 slots + 1 round. **Trial now shows only R1 + R2** (both "Client Trial —" named). **Dev untouched (209 rounds).**
- **Client guide finalized** — URL filled (`https://mac-2-608.taile18f28.ts.net/`) and support contact (`stitch@taatheerinvest.com`); PDF re-exported. *(Owner: change the support contact if a different one is preferred.)*

## 12. Client roadmap (produced) + INTERNAL source map

`artifacts/client-trial-guide/Tanaghom_Planned_Improvements_and_Product_Roadmap_2026-07-06.md` + `.pdf` (3 pages) — client-facing, translated from the open backlog; **no issue numbers, labels, ports, DB names, provider/dev terms**.

**INTERNAL source map (operator-only — NOT in the client roadmap):**

| Client roadmap theme | Source issues | Type |
|----------------------|---------------|------|
| Clearer navigation / stage labels / terminology | #20, #39 | fix + feature |
| Better topic/script presentation; inline edits | #14 | feature |
| Search / filter / sort review items | #16 | feature |
| Remembered working views / preferences | #16 (+ #15 shipped) | feature |
| Editable workflow/stage names; internal-vs-label separation | #39, #6 | decision + feature |
| Flexible workflow configuration; admin controls | #6, #18 | feature |
| Run management (edit/archive/restore/delete) | #18 | feature |
| Role-based access; safe reviewer/operator/admin views | #13, #10 | feature + hardening |
| Approval rules, snapshots, audit; server-resolved actor | #9, #10 | backend/semantics |
| Stronger generation controls / guardrails / reliability | #5, #9, #10 | ops/process |
| Draft→review→approved→production-ready states; production checks | #9, #5 | semantics/ops |
| Content & calendar pipeline; content-type management | #7 | backend/data |
| Expanded operating channels (messaging/notifications) | #8 | integration |
| AI co-working assistance | #11, #19, #21 | large / governance |
| In-app guided tour | #44 | onboarding |
| Contextual help / copilot | #45 | help |
| Living user guide / docs source of truth | #46 | docs |

Issues intentionally **not surfaced** in the client roadmap as standalone items (folded into broader themes or internal-only): #19 (multi-agent architecture doc) and #21 (agent binding governance) → folded into "AI co-working assistance"; #5/#8 ops/integration → softened into "reliability" and "expanded operating channels."

## 13. Deliverables summary (all uncommitted, not sent)

| Document | Path | Audience |
|----------|------|----------|
| Client trial user guide (md+pdf) | `artifacts/client-trial-guide/…User_Guide…` | client |
| Client feedback template (md) | `…Feedback_Template…` | client |
| Client roadmap (md+pdf) | `…Planned_Improvements_and_Product_Roadmap…` | client |
| Operator & admin guide (md+pdf) | `artifacts/operator-admin-guide/…Operator_Admin_Guide…` | internal |

## 14. Addendum attestation

- Roadmap contains **no issue numbers, labels, ports, DB/container names, local URLs, or provider/dev terms**; the source map lives only here (operator-only).
- R3 purge was **trial-DB-only** (snapshot + label-guarded transaction); **dev DB untouched (209)**; no e2e fixtures touched; no other issue mutated; no labels changed (beyond the 3 help-system labels created earlier); no client access sent.
- No roadmap features implemented. Artifacts not committed. `.env*` untouched. `origin/main` unchanged (`e3ba1e4`).
