# Build Prompts (M1 → M5) — paste into Claude Code / Codex, one at a time

Run inside the cloned repo. After each milestone, the agent ticks it in `BUILD_STATE.md`,
commits, and pushes. Review the output before moving to the next.

> Golden rules to repeat to the agent: keep ALL behavior in `system_config.yaml`
> (no hardcoded params); every stage gated + audited; never auto-publish; Palestinian
> dialect needs native review and any Qur'an/Hadith needs scholar verification.

---

## M1 — Foundation (load the methodology)
> Read `BUILD_STATE.md`, `README.md`, and `docs/02_Phase1_Build_Spec.md`.
> Bring up the local stack: `cp system_config.example.yaml system_config.yaml`,
> `cp .env.example .env` (set DB_PASSWORD), then `docker compose up -d`.
> Confirm `db/init/schema.sql` loaded (14 tables) — Adminer at http://localhost:8080.
> Then build a loader that parses `methodology/canon/CANON-010..015` and the 42 records
> in `methodology/records/HCS_Records_All42_Seed_v1.md` and inserts them into the
> `pillar`, `hcs`, `lens`, `hook_type`, `format` tables (preserve `seq_in_pillar` order).
> Verify row counts (5 pillars, 42 HCS, 5 lenses, 5 hook types, 7 formats). Tick M1 in
> BUILD_STATE, commit, push, and stop for my review.

## M2 — Planner (auto 28-day round, no repeats)
> Implement the Planner per `docs/02_Phase1_Build_Spec.md` §3. Given a round request,
> read `system_config.yaml` (calendar template) and generate 56 slots: correct pillar
> distribution (22/17/9/4/4) and weekly format mix (4/1/2/2/3/1/1), assign HCS sequentially
> from `hcs_cursor` (carry across rounds; restart cycle when a pillar's list is exhausted),
> select a lens from each HCS's `recommended_lenses` excluding the previous cycle's lens
> (write `lens_history`), and set default hook type from the lens. Slots start `RESERVED`.
> Acceptance: re-running a second round continues the cursor and rotates lenses. Provide a
> CLI/endpoint `plan-round` and print the generated calendar. Tick M2, commit, push, stop.

## M3 — Writers (Topic + Script agents)
> Implement the Topic/Brief and Script agents per spec §4, wired to `system_config.yaml`
> model settings (frontier API for ar-PS writing; local embeddings for dedup). Topic agent:
> produce `topic_angle` + `hook_text` (obey CANON-013 hook rules) or flag
> NEEDS_STRATEGIC_CLARIFICATION; run the embedding dedup safety-net vs the `topic` ledger.
> Script agent: write `script_ar` enforcing CANON-012 Mandatory Delivery Check + CANON-013
> Hard Fail conditions; set `needs_scholar_review`/`needs_native_review` flags. Move slots to
> `DRAFT_ASSIGNED`. Tick M3, commit, push, stop.

## M4 — Gates + surfaces (review & approve)
> Build the approval layer per spec §5–6: a chat-first dashboard (Next.js, RTL) batch view
> with per-row + bulk Approve/Reject/Request-change and script preview, plus a Telegram bot
> for on-the-go approvals. Support partial batch approval, multi-approver/quorum from config,
> and write every transition to `audit_log`. Approved slots → `APPROVED_ASSIGNED`; changes
> loop back to the relevant agent. Tick M4, commit, push, stop.

## M5 — Polish + dry run
> Surface `needs_native_review` / `needs_scholar_review` in the review queue as required
> sign-offs. Run one full 28-day round end-to-end (plan → write → review → approved). Fix
> gaps against the acceptance criteria in spec §7. Tick M5, commit, push, and summarize.
