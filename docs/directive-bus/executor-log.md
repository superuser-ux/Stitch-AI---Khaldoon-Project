# Executor log — directive-bus briefings (newest first)

Append-only briefings from the Claude Code executor lane, one entry per completed directive
execution/closeout. For any agent lane (Codex, GPT): read the top entries to sync on what the
executor changed. Briefing only — entries never request action.

## 2026-08-05 · #427 + #429 CLOSED (directive:done) — Stage 4 final-review backend read projection MERGED

- **PR #428 merged:** operator-approved reviewed head `bf89e3c2c58b13fa3fca0446fa13eafa548b3f92` squash-merged as `4e8ff12480f5d5ab6d55ecd1c95c52c070850df2` at `2026-08-05T06:12:09Z` onto `main` (base `528c0f4`). One PR carried the feature (#427) and its one correction cycle (#429); held at the human merge gate throughout; never self-merged. **Source-only slice — NO deployment (the developer VPS is unchanged).** Approval bindings (no-trailing-newline body SHAs): #427 `0bf5fb56…`, #429 `fc22be98…`.
- **Directive chain (one deliverable):** #427 built the additive read projection; #429 corrected the decision/audit-attribution defect it shipped. Each was a separate GPT-reviewed / operator-approved / Codex-reconciled critical directive on the SAME PR #428 branch (no replacement PR); every step ran read-only preflight → reconciliation → bounded edits → isolated-harness/static validation → hold at a fresh exact-head GPT gate.
- **What it delivers (additive, read-only; no schema/migration/write; V1 shapes untouched):** `gates/final_review_projection.py` — `read(cur, gate_id, slot_id)` resolves one admitted final-review `(gate_id, slot_id)` and joins persisted evidence server-side from frozen tables only, composing existing truths: identity (`gate`/`gate_target`), immutable package (`final_review_target_package.read`, #423), gate-wide frozen assignment (`engine._load_gate_snapshot`, #282/#422), head-correct persisted decision/coverage (`engine._authoritative_target_projection` over `gate_token_coverage`, #321), and gate-scoped audit history. Additive `GET /gates/{gate_id}/slots/{slot_id}/final-review-projection` (`gates/api.py`) — new route, **zero** change to the #423 `/target-package` V1 route/shape. `docs/final-review-read-projection.md` — evidence authority, canonical attribution rule, typed limits.
- **#429 correction (the shipped defect + fix):** #427 nested gate-wide `audit_log` rows inside the slot-scoped `decision_evidence` group with `status="recorded"`, promoting gate history to slot-attributable decision evidence and letting an incomplete audit hide behind a recorded status. Fixed to a **separate `audit_evidence` group**: gate-scoped history only, `slot_attributable:false`, never `recorded`/`available` (status `gate_scoped_history`|`unavailable`, always carrying `audit_gate_scoped_not_slot_attributable`); new reason code added. Each evidence group now carries an **independent, fail-closed** status — no combined decision/audit status, so an unavailable audit group is neither hidden behind nor able to downgrade recorded decision/coverage; ambiguous decision attribution fails closed.
- **Invariants proven:** canonical attribution only (a fact is attributed to `(gate, slot, snapshot)` solely through an enforced persisted key — gate association / actor / revision / event kind / outcome / timestamp proximity are NOT slot linkage); no target-level assignment snapshot (gate-wide per #422); frozen eligibility disclosed as history, never present authorization (no authorization evaluated); fail-closed typed `recorded`/`unknown_history`/`unavailable` + machine-readable reason codes; **invariance** — later changes to current Topic/Script head, workflow-version state (retire-then-activate), and slot mutable status/label cannot alter a recorded projection.
- **Schema-impossible ambiguity boundaries (documented, not simulated):** (a) slot-attributable audit is impossible — `audit_log` has no FK/column relating a row to a slot/snapshot (nearest fail-closed case tested: gate-scoped-only exposure; slot-entity row excluded); (b) whole-batch/NULL-slot decision is impossible — `gate_decision` PK `(gate_id, approver_id, slot_id)` forces `slot_id` NOT NULL (harness proves the write is rejected with `NotNullViolation`; code keeps a defensive fail-closed check).
- **Evidence at the merged head (permitted isolated boundary only — NO shared-DB/Docker/Compose/browser/VPS/runtime; `gates.api_selftest` NOT run):** runtime-free unit matrix `gates/final_review_projection_test.py` **31/31**; isolated ephemeral-Postgres harness `gates/final_review_target_package_harness.py` **84/84, 0 FAIL** (7 new #429 cases + all pre-existing #423/#425/#426/#427 green = no regression; owned cluster on a private socket, `PG*` scrubbed); additive AST API-contract `gates/final_review_projection_apicontract_test.py` **6/6** (V1 `/target-package` unchanged, new route additive, no collision); `py_compile` clean; gitleaks clean.
- **Roadmap ledger #294:** delivered — additive backend read projection linking immutable target-package + gate-wide assignment + attributable decision/coverage evidence, with independent gate-scoped audit. Conserved — #422 gate-wide assignment authority and #423 immutable target-package contract. Still outstanding for Stage 4: frontend/V2 presentation, sign-off/action semantics, rejection/reconsideration, production-direction approval contract, runtime + deployment validation, client acceptance, Stage 4 closeout. Stage 5 remains unopened.
- **Residual follow-ups (non-authorizing, operator-owned):** (a) no deployment — the slice lives on `main` only; the developer VPS lane (`695b35d` from #417) is unchanged; (b) runtime/E2E and any shared-DB integration run of the new endpoint are separate, un-authorized steps (validated only via the isolated harness + static checks); (c) no V2/UI surface for this endpoint yet (backend-only slice).

## 2026-08-04 · #423 + #425 + #426 CLOSED (directive:done) — immutable final-review target-package snapshots at attachment MERGED

- **PR #424 merged:** operator-approved reviewed head `95c33aabaf72196d4fc79f5266dd05dbd6b2590a` squash-merged as `8e9a07e5b9e67ecfe8c7760be33a6cf50a9c3abe` at `2026-08-04T19:37:08Z` onto `main` (base `635b2cc`). One PR carried the feature (#423) and both correction cycles (#425, #426); held at the human merge gate throughout; never self-merged. **Source-only slice — NO deployment (the developer VPS is unchanged).**
- **Directive chain (one deliverable):** #423 built the feature; #425 corrected five mandatory GPT source-review findings; #426 corrected the three remaining findings. Each cycle was a separate GPT-reviewed / operator-approved / Codex-reconciled critical directive on the SAME PR #424 branch (no replacement PRs); every step ran read-only preflight → reconciliation → bounded edits → isolated-harness validation → hold at a fresh exact-head GPT gate. Approval bindings (no-trailing-newline body SHAs): #423 `0be7bd92`, #425 `fda6e1a9`, #426 `ac01b80d`.
- **What it delivers (additive, no-backfill; `db/init/schema.sql` untouched):** migration `036_final_review_target_package.sql` — an immutable `final_review_target_package` table (PK `(gate_id, slot_id)`, FKs to `gate_target` and `gate_snapshot(gate_id, snapshot_id)`, `BEFORE UPDATE OR DELETE` immutability trigger, and a `BEFORE INSERT` trigger rejecting non-`final_review` gate evidence). `gates/engine.py` — `TargetPackageNotReady(GateNotReady)` (attachment readiness, NOT authorization), `_derive_final_review_target_package` / `_validate_final_review_batch` / `_insert_final_review_target_package`, and whole-batch validate-before-insert wiring in `open_gate` + `reconcile_gate_targets`, **final_review-only** (a legacy gate with no gate-wide snapshot fails closed rather than admit an unpinnable target). `gates/final_review_target_package.py` + additive `GET /gates/{gate_id}/slots/{slot_id}/target-package`, plus a V2 read-only projection (`workbench/app/gates/[gateId]/slots/[slotId]/target-package/page.tsx` + panel + allowlist/type) — the SOLE typed `recorded`/`unknown_history`/`unavailable` disclosure (stage-aware, from persisted `gate.stage`; never reconstructs from live state).
- **Invariants proven:** consumed vs active workflow provenance distinct; gate-wide frozen `gate_snapshot` REFERENCED (no target-level assignment snapshot, no membership re-resolution); whole-batch atomicity (open/reuse/reconcile validate all before inserting any; a refusal rolls back with zero target/snapshot/audit residue; `decide`/`resolve`/reads stop before their writes on a blocked attachment — readiness, never authorization); attachment audit only from a successful snapshot `INSERT … RETURNING` (replay-safe); legacy targets stay `unknown_history` (no backfill/re-attest/rewrite); DB-boundary update/delete/non-final-stage rejection.
- **Evidence at the merged head (permitted isolated boundary only — NO shared-DB/Docker/Compose/browser/VPS/runtime):** `gates/final_review_target_package_harness.py` — an owned ephemeral-Postgres cluster (`initdb`/`pg_ctl` on a private socket, inherited `PG*` scrubbed) applying the committed schema + migrations 001–036 — ALL PASS, covering: real `open_gate()` initial success / underivable-candidate rollback with zero residue across gate+snapshot+target+package+both audits / replay-reuse dedup; late reconcile success + whole-batch rollback + no-snapshot legacy refusal (idempotent, canonically-equivalent candidate set); DB update/delete + non-final-stage insert rejection + PK uniqueness; post-attachment mutation cannot alter recorded evidence; stage-aware `recorded`/`unknown_history`/`unavailable` reads; and `start_pg()` failure-injection cleanup at pre-initdb/startup/post-start with original-exception preservation. `py_compile` OK; V2 `tsc --noEmit` 0 / `next build` 0 at the feature head.
- **Residual follow-ups (non-authorizing, operator-owned):** (a) no deployment — the slice lives on `main` only; the developer VPS lane (`695b35d` from #417) is unchanged; (b) runtime/E2E rendering of the V2 projection and any shared-DB integration run are separate, un-authorized steps (the whole slice was validated only via the isolated harness + static checks).

## 2026-08-04 · #419 CLOSED (directive:done) — read-only Stage 4 approval-package preflight (read endpoint + V2 projection) MERGED

- **PR #420 merged:** operator-approved exact head `53877d4a45837ffc09644949cefa99a374dacc1d` squash-merged as `9e8cbb4ded160020a956a7ea589d5c4d74c21bdc` at `2026-08-04T12:51:56Z` onto `main` (base `d78480b`). Amended issue #419 body SHA `0d591ab41241bdc7aca6cd76b70a20a64191c8f540998c5faad153215540cbee`; GPT exact-head review reconciled to approve (no remaining implementation finding). Held at the human merge gate throughout; never self-merged. **Source-only slice — NO deployment (the developer VPS was not touched).**
- **Gate flow (critical directive):** CC read-only adversarial preflight → Codex reconciliation (GO) → additive implementation → GPT exact-head review found P1s → **three bounded corrective cycles**, each resetting review at a fresh head: (1) amendment — production-direction absence becomes non-blocking `not_yet_recorded`; (2) P1 — structurally validate the persisted directive package + selected-script/slot reference; (3) P1 follow-up — the persisted `directive.revision` column must also equal the selected script revision. Two operator body-SHA approvals bound the amendment (`bf82ab5b` → `0d591ab4`).
- **What it delivers (additive, read-only, server-authoritative; no schema/migration/write):** `gates/stage4_preflight.py` — a pure-SELECT aggregation of EXISTING canonical records into typed `{available, reason_code, detail, evidence, denials}` for one canonical `slot_id`. Additive `GET /slots/{slot_id}/stage4_preflight` (`gates/api.py`) — a new route with no shared-shape change → **zero V1 impact**. V2: `workbench/lib/api-contract.ts` allowlist + `read-model.ts` `Stage4Preflight` type + `components/stage4-preflight-panel.tsx` + `app/stage4/[slotId]/page.tsx` read projection inside the existing shell (renders the verdict verbatim, no action, never implies a denied path; **no governed rail gate required**).
- **Invariants proven:** consumed workflow identity (`script_provenance.workflow_version_id` / `round_policy_snapshot.workflow_version`) and active identity (`workflow_version.status='active'`) are DISTINCT and never rebound; final-review requirement read from the CONSUMED version's `workflow_stage` (never the active singleton); missing/underivable pins → `unknown_history` fail-closed; consumed≠active → `consumed_active_workflow_divergence` (never eligible-by-implication); production direction OBSERVED via a pure `directive` read (never `script_to_production`/emit/record) — absence = `not_yet_recorded` non-blocking, malformed/mismatch (canonical `PACKAGE_FIELDS` + script/slot ref + `directive.revision` column vs selected script) fail-closed; agent/AgentRep/provider/secret = truthful `not_applicable`/`not_recorded`, conferring no authority.
- **Evidence at the merged head (static/unit — implementation flow was no-runtime):** backend `py_compile` OK + `gates/stage4_preflight_test.py` **24/24** runtime-free unit checks (coherent + every discriminator: mismatched topic/script, absent provenance→`unknown_history`, missing consumed/active workflow, divergence, final-review absent/disabled/AI-generated, and production-direction not_yet_recorded/malformed/mismatch incl. row-revision). V2 `tsc --noEmit` **0**; `next build` **0** (`/stage4/[slotId]` route present). E2E `stage4-preflight-419.spec.ts` is skip-guarded.
- **Residual follow-ups (non-authorizing, operator-owned):** (a) runtime execution of the focused E2E discriminators against a seeded Stage-4 fixture (coherent / mismatched / unknown-history / invalid-direction) is a separate runtime validation step, not performed here; (b) no deployment — the slice lives on `main` only; the developer VPS lane (`695b35d` from #417) is unchanged.

## 2026-08-04 · #417 CLOSED (directive:done) — `695b35d` deployed to the isolated developer VPS via opaque env-file + immutable legacy directory

- **Deployment (not a merge):** exact release `695b35d327192c711c455ca1f8c18a73d8ba889b` (Process Studio + #414 read-only startup) deployed to the `tanaghom-v2-dev` developer-VPS lane, replacing the running `43a67d`. Operator approval bound to raw-body SHA `b800f552…` + release commit + this CC session; GPT `APPROVE-DIRECTIVE-DRAFT`; CC adversarial preflight GO reconciled by Codex (`5176672429`). Executed via existing session only.
- **Supersedes #416's blocked boundary** (do NOT resume #416 independently). #416 had halted at two stop-before-mutation conditions: (1) the new package's `.env`/`DB_PASSWORD` could not be provisioned without reading/copying a secret; (2) `/srv/tanaghom-v2-dev` is a plain directory with no candidate selector and no separate immutable `43a67d` sibling. #417's convention resolved both.
- **Convention used (bounded):** staged the runtime-only `695b35` package in a NEW sibling `/srv/tanaghom-v2-dev.candidate-695b35d…`; used `/srv/tanaghom-v2-dev/.env` **solely as an opaque `--env-file` pathname** (never read/printed/hashed/copied); supplied only an **ephemeral non-secret `V2DEV_GIT_SHA`** process override; recreated **only** `gateapi`+`workbench` with `docker compose --project-name tanaghom-v2-dev -f <sibling> up -d --no-deps --force-recreate` (logical service-source switch, not a filesystem selector). Legacy `/srv/tanaghom-v2-dev` (dir/MANIFEST/anchor/`.env`) left immutable.
- **Off-host build/provenance:** clean detached checkout at `695b35d`; `build.sh`/`stage.sh` produced two `linux/amd64` images + runtime-only 18-file package; external anchor `116de602…`; gateapi archive `4f9bc02c…`/oci `6e75aed1…`, workbench archive `0f79239b…`/oci `bb801e3e…`. Transfer sha256 identical local↔VPS (`4b769942…`, 634,427,904 B). Removed 21 macOS AppleDouble artifacts to restore the exact 18-file closure. `load-images.sh` verified external anchor + grammar + archive-hash + post-load image-ID/oci/revision, no tag collision, exactly gateapi+workbench. Redaction-safe `config --services/--images/--volumes/--networks` only (never full `config`) resolved db+gateapi+workbench, `695b35` images, existing `tanaghom-v2-dev_{db_data,init_marker,internal}` + external `tanaghom-iam-dev`.
- **Read-only proof (VPS):** both apps healthy on `695b35`; **db/volumes/networks/init-marker/neighbors untouched** (db cid `33892b0b…`/StartedAt unchanged, net id `bdc8913b…` unchanged, 25-container parity); loopback-only `127.0.0.1:18110`/`:13101`, db no host port; runtime `build=695b35d`. **Three exact #414 §6b fingerprints BYTE-IDENTICAL** — pre-deployment == post-recreation == post in-place gateapi restart: `99934436bcdc942ac424296ab9a5b85e|audit_count=224|audit_max=224` (DB identity `7669179147016478758`; 224 historical audit rows preserved). Restart in-place (StartedAt advanced), post-boundary read-only startup records=2, `actual_seed_executions=0`.
- **Rendered browser acceptance** (existing loopback tunnel, read-only, no sign-in/writes): identity bar `build 695b35d…`; `/studio` document title "Process Studio — Tanaghom Workbench (V2)"; full Workbench-shell chrome on `/` and `/studio`. (First attempt deferred — Claude browser extension was disconnected; on reconnect the directive briefly sat at `directive:pending` with that exact boundary, then completed.)
- **Prohibitions honored:** no secret value read/printed/hashed/copied/persisted; no DB/schema/migration/volume/network/OpenBao/ZITADEL/IAM/Ollama/shared/ingress mutation; no automatic rollback (`43a67d` retained immutable); no #412/#413 execution, UAT, staging, production, public ingress, IAM activation, or source cleanup.
- **Residual follow-ups (non-authorizing, operator-owned):** (a) any rollback to `43a67d` needs a separate exact operator decision; (b) `43a67d` app images + all prior `.previous-*/.candidate-*` packages remain retained on the VPS (rollback evidence); (c) the transferred build tar remains under `/home/administrator/` (my transfer artifact; left in place — not source cleanup); (d) #416 is superseded by this completed deployment and normalized/closed.

## 2026-08-04 · #414 CLOSED (directive:done) — read-only v2-dev Gate API startup + explicit synthetic fixture initializer MERGED

- **PR #415 merged:** reviewed/authorized exact head `d6b87a1ac807591b07e5da95c47b0acc9065e8f2` squash-merged as `695b35d327192c711c455ca1f8c18a73d8ba889b` at `2026-08-04T07:46:50Z` onto `main` (base `9f96677`). Explicit operator conditional-merge authorization for that exact SHA after a fresh GPT source review (`APPROVE-VALIDATION-DRAFT`) and an isolated §6b runtime gate; held at the human merge gate, never self-merged. Scope confined to `deploy/v2-dev/`.
- **Origin:** the #413 finding — the v2-dev gateapi entrypoint ran `init_db.py` → `load_methodology` + `e2e_seed` + `open_gate` on **every** start, appending an `audit_log` row and breaking the literal persisted-data snapshot equality that #412/#413 depend on.
- **What it delivers (`deploy/v2-dev/`):** (1) **ordinary startup is DB-read-only** — `init_db.py` drops the catalogue loader / `e2e_seed` / `open_gate`; a known-owned restart/recreate verifies schema+ownership only and writes **zero rows incl. zero `audit_log`** (a genuinely fresh DB still gets committed schema+migrations+ownership marker, structural one-time). (2) new **explicit `init_fixtures.py`** synthetic-fixture initializer — refuses unless `TANAGHOM_LANE_ID=v2-dev-389` + `TANAGHOM_DATA_CLASS=synthetic` + `--confirm`; idempotent create-missing (catalogue / RE2E round+slots+topics / open gate); **marker-evidenced** (generation + **source revision** + cluster identity; no secrets); **fail-closed** — unrecognized ownership or incomplete/unexpected pre-existing data is never re-attested; validates the complete canon catalogue + exact RE2E round/slots + the **exact committed RE2E topic set** (identity from `e2e_seed.SLOTS`; refuses missing/extra/substituted/duplicated) + open RE2E-targeted gate before (re)writing the marker; `_fixture_state()` probes every fixture surface so orphan rows fail closed instead of entering the fresh-slate path. (3) §6b read-only-startup regression added to `packaging_test.sh`; runtime-free `init_fixtures_test.py`. Files: `init_db.py`, `init_fixtures.py`, `init_fixtures_test.py`, `gateapi-entrypoint.sh`, `docker-compose.yml`, `packaging_test.sh`, `README.md`.
- **Review gate (patches reset review each time):** GPT source review found five bounded corrections at head `23463bd` → applied at `6fbafbf` (corrections 1–4 accepted: full-table fingerprint, mandatory verified in-place restart, post-restart log boundary, revision-bound marker) → correction 5 refined at `d6b87a1` (exact RE2E topic-set comparison + all-surface markerless detection + refusal tests) → fresh GPT `APPROVE-VALIDATION-DRAFT`.
- **§6b gate actually run (operator-approved, isolated):** one privileged **Docker-in-Docker** runner — **no host Docker socket**, no VPS; reviewed source delivered via a self-contained `git bundle` (clean clone, empty porcelain). Host is arm64; `build.sh` forces `--platform linux/amd64`, cross-built/run under nested emulation. `packaging_test.sh` run **through §6b only** (git-ignored `head -525` + `exit 0`, so the clean-tree gate genuinely still passed). §1→§6b **ALL PASS**: fresh startup seeds `0|0|0`; explicit initializer first-run `1|1|3`; **ordinary restart DB-read-only — exact `audit_log`-inclusive fingerprint (table counts + audit_log count + max id) byte-identical** across a mandatory in-place fresh restart (StartedAt `07:42:37→07:42:55Z`); no-op rerun identical; refusal writes nothing; no sentinel in logs.
- **Environment note (no test logic changed):** `docker:29-dind` defaults to the containerd image store, whose BuildKit attaches attestation/manifest-list digests → a never-pushed local build reports a RepoDigest, tripping §1's pre-existing "must not push" check. Switched the runner daemon to the standard **overlay2 image store** (the store the dev/VPS environment uses); local builds then had empty RepoDigests. No packaging-test assertion was modified.
- **Cleanup/preservation:** runner container + inner candidate stack/images/networks + anonymous `/var/lib/docker` volume + transfer bundle **fully removed**; isolation verified (no `d6b87a1` image reached the host daemon); pre-existing host image **`v2dev-gw-test:414` preserved** (`e69513aef74d`, unchanged).
- **Residual follow-ups (non-authorizing, operator-owned):** (a) **#412/#413** remain open and were out of scope — #414 delivers the read-only-startup + literal-fingerprint precondition they consume; (b) remote branch `feat/issue-414-readonly-gateapi-startup` not deleted (remote deletion permission-gated); (c) issue carried `agent:codex` but was executed via the operator's direct `agent:cc` session dispatch — flagged for lane reconciliation.

## 2026-07-29 · #389 CLOSED (directive:done) — isolated `tanaghom-v2-dev` STITCH-VPS development-lane PACKAGING MERGED

- **PR #390 merged:** reviewed/authorized exact head `63a49a7b3c6f7379092c257d302ac473a8250e69` squash-merged as `f6ccbb3bbfb38512f6254261a7eb492237fab9f2` at `2026-07-28T21:09:51Z` onto `main` (merge tree carries `deploy/v2-dev/`). Explicit operator merge authorization for that exact SHA after a full multi-round review gate; held at the human merge gate, never self-merged. Baseline `a2a1b831832c07050b2abad234ebeb24fe790d9d`.
- **Scope — PACKAGING ONLY.** Committed, exact-SHA-traceable packaging + static validation + candidate-only runbook for a **non-production** V2 dev/testing lane for the rebuilt STITCH-VPS. **Authorizes no STITCH-VPS access/mutation, deployment, secret creation, or runtime action** — deployment requires a SEPARATE later critical directive (fresh host inventory → GPT → operator → CC preflight → Codex reconciliation → release). No product/domain/schema/migration/authority/IAM/configuration-generation change, no new runtime dependency.
- **Gate actually run:** CC adversarial elaboration → named Codex reconciliation (6 binding decisions) → implement → exact-head review found a merge-blocking candidate-path/build-context contradiction → **four review rounds** of bounded hardening, each resetting GPT+Codex review at a fresh head, each with the raw `git diff --binary` SHA-256 supplied as the review artifact.
- **What it delivers (`deploy/v2-dev/`, sibling of the local `tanaghom-acc` lane — never adopts/mutates it or any shared service):** three isolated services — `pgvector/pgvector:pg16` **digest-pinned** (`sha256:1d533553…`, resolved via `docker pull`, no host port), governed gate API, V2 workbench — built from the EXISTING committed `deploy/stitch-vps/Dockerfile.api` + `workbench/Dockerfile` verbatim (byte-identical provenance). Frozen: namespace `tanaghom-v2-dev`; loopback ports `127.0.0.1:18110` API / `127.0.0.1:13101` workbench; per-service + aggregate CPU/mem ceilings (`2.0 CPU / 1.66 GiB`) + runbook admission minima/stops; candidate path `/srv/tanaghom-v2-dev` (`administrator:administrator`, `0750`/`0640`/`0750`/`0600`, canonical-path + symlink-escape checks); shared-service denylist (`tanaghum-backup`/`postiz`/`powerfix`, `/srv/tanaghum-primary`) + pre-mutation manifest schema; candidate-only rollback/interruption contract. Files: `docker-compose.yml` (runtime-only), `build.sh`, `stage.sh`, `load-images.sh`, `gateapi-entrypoint.sh`, `init_db.py`, `packaging_test.sh`, `README.md`, `.env.example`, `.gitignore`.
- **Self-contained candidate path (review round 1):** the runtime compose has NO `build:` and references app images by exact-SHA tag with `pull_policy: never` — resolving the contradiction where `../..` build contexts needed a repo checkout the candidate-path contract forbids. Images are built off-host from a clean checkout, exported as **immutable OCI archives** (`docker save`), transferred, and `docker load`ed via `load-images.sh`. Gate API has no runtime-SHA HTTP surface, so its identity is a **fatal packaging-boundary entrypoint guard** (expected reviewed SHA == baked `/work/BUILD_SHA`) — no product endpoint added.
- **Provenance hardening (rounds 2–4):** **external manifest trust anchor** — `stage.sh` emits the `MANIFEST.txt` sha256 OUTSIDE the candidate dir; `load-images.sh` requires an independently-supplied expected digest and verifies it BEFORE any Docker mutation (a self-consistent archive+manifest rewrite that travels inside the dir is still rejected). **Whole-manifest grammar** (exact `manifest_version 2`/reviewed SHA/frozen db digest/2 image/6 file records; no blank/comment/unknown/duplicate/trailing). **Exact filesystem structure** (only root + `./images` + declared files; undeclared dirs/entry types rejected). Strict typed records; canonical non-symlink archive paths under `./images`; detached manifest (never self-hashed); ambiguous-tag-replacement refusal. **Dedicated `INT`→130 / `TERM`→143 signal handlers** perform idempotent candidate-only rollback and terminate (execution cannot resume into further mutation); `EXIT`/`ERR` cleanup idempotent; refs tracked as introduced before load.
- **Evidence at the frozen head `63a49a7` (serial / single-worker / ZERO retries):** `packaging_test.sh` ALL PASS — full static/provenance/build matrix + **25 adversarial negatives** including empty/partial/duplicate/malformed/substituted manifests, path traversal, symlink escape, stale/undeclared files, hash tamper, missing/changed db digest, changed version, unknown record, trailing junk, undeclared directory, external-anchor consistent-rewrite rejection, post-load + second-load rollback, ambiguous-tag refusal, and **real SIGINT→130 / SIGTERM→143** tests (process-group Ctrl-C emulation: first image rolled back, no second load, pre-existing state unchanged) — each proving non-zero exit + unchanged Docker state + unrelated-image isolation. Stack brought up **purely from transferred archives** (`/api/runtime`==head, `/gw` writer_mode stub + canonical rounds, loopback-only, DB internal); container image-ID == reviewed build == loaded; init idempotency `tables|rounds|slots|methodology=68|1|3|1`. Workbench affected gate: `tsc --noEmit` 0; production `next build` 0. Zero-residue teardown verified (no v2-dev objects/tags/staging), pgvector intact, unrelated stacks untouched. `gates.api_selftest` never overlapped Playwright on the shared DB (this lane exercises the workbench, not the dashboard E2E suite).
- **Residual follow-ups (non-authorizing, operator-owned):** (a) **deployment is a separate later critical directive** referencing merged `f6ccbb3` — fresh read-only host inventory, GPT pre-approval, operator approval, CC adversarial preflight, named Codex reconciliation, and a distinct deployment release; neither this merge nor #389's closure grants deployment authority. (b) at deploy time the frozen loopback ports / candidate path / numeric ceilings / shared-service parity are revalidated against freshly-measured host headroom; any collision/drift/degradation is STOP. (c) protected lanes, the dirty canonical checkout, shared services, and runtime were untouched throughout.

## 2026-07-28 · #385 CLOSED (directive:done) — schedule drag / view-naming / topic-order discoverability (presentation-only) MERGED

- **PR #386 merged:** reviewed/authorized exact head `96f00fa9a82a9ee09da99172030b3944760525a8` squash-merged as `18920d9853b92db23d9cb8c0c81f8a997e7ea464` at `2026-07-28T08:13:55Z` onto `main`. Explicit operator merge authorization for that exact SHA after Codex Browser re-audit; held at the human merge gate, never self-merged. Baseline `8ae5a680507e05bc9fbe280625c640d48d8cb9c8`.
- **Origin:** consumes the #384 operator non-acceptance (confirmed discoverability gaps 1–7) from the restored V2 shell. **Presentation + accessibility only — no backend/domain/schema/migration/authority/IAM/workflow/lifecycle/disposition/topic-generation/policy-generation/configuration-generation change, no new dependency** (existing HTML5 drag + React state only). Every governed contract unchanged: write path, `schedule_token`, 409 conflict/refresh, URL canonicalization (`v_{scope}` keys, stable `list` key), stage/lens resolution, and the fail-closed Agent boundary.
- **What it delivers (7 scopes):** (1) discoverable reorder — visible per-row `⠿` handle + guidance ("dragging previews an order; **Apply order** commits"), distinct `data-dragging`/`data-drop-target`/`data-order-state`, keyboard `↑/↓` retained; ONE ordering model (canonical ids + token + server acceptance + reread) unchanged. (2) calendar gesture legend (empty-range create vs move-existing vs frozen) + per-event `⠿`/`🔒` `data-movable` affordance, `title` now supplemental. (3) view-naming disambiguation — calendar-internal `list` relabelled **Agenda** (key + URL unchanged), top lens gains **Workspace view** caption, calendar toolbar **Calendar display** caption. (4) Topics persistent copy separating editorial presentation order from governed schedule timing + why Calendar is unavailable there. (5) disabled lenses/stages get a visible, keyboard-focusable, touch-tappable `DisabledHelp` disclosure surfacing each truthful reason; `toBeDisabled()`+`title` contract preserved. (6) Schedule List regrouped `identity`/`timing`/`classification`/`edit`/`ordering`, no 375px overflow, RTL via logical properties. (7) absent optional data renders `—`, never literal `undefined` (regression scan asserts). Files: `run-schedule-workspace.tsx`, `runs-calendar.tsx`, `schedule-views.ts`, `schedule-view-toolbar.tsx`, `workbench-shell.tsx`, `topics-workspace.tsx`, `topic-presentation-reorder.tsx`; new spec `e2e/ux-discoverability-385.spec.ts`.
- **Evidence at the frozen head `96f00fa` (#370 fail-closed isolated lane, `FIXTURE=zero-run` + governed `#376` gen + run-mix policy, stub writer, digest-pinned images, `EXPECT_SHA`-bound, served source byte-verified == accepted head; serial/one-worker/ZERO-retries):** `tsc --noEmit` 0; production `next build` 0. Focused `ux-discoverability-385` **10/10** (naming disambiguation, real HTML5-drag preview, Apply-commit + keyboard reorder, 375px LTR/RTL grouping+containment, lens help disclosure, stage help disclosure, calendar legend + movable affordance, Topics semantics, no-`undefined` scan). Regression on affected specs, same lane: shell-containment 6/6, workbench-shell 10/10, lens-menu 4/4, schedule-first-shell 5/5, schedule-style 4/4, runs-calendar 9/9, run-schedule + topics-coverage 24/24. The preserved `#384` operator lane was NOT touched; a directive-owned disposable lane was used throughout and torn down at closeout. `gates.api_selftest` never overlapped Playwright on the shared DB.
- **Disclosed, not masked — two non-green results, NEITHER caused by #385:** (a) `schedule-views.spec.ts` 5/6 — the failing test's no-mutation `snapshot()` helper runs `docker exec … tanaghom-db` against the shared dev DB container (currently Exited) and errors before any UI assertion; harness/environment. (b) `calendar-geometry.spec.ts` 10 pass/8 fail — **pre-existing main defect**: spec last updated in `#341` (778c2df) BEFORE `#380` Daylight (0f3659b) made light omit `data-theme` (light = base `:root`); all 8 failures are "light" rows failing the `data-theme="light"` precondition (line 183) before geometry. Dark/geometry rows pass — proving the legend/event-marker changes do NOT disturb calendar geometry. Out of scope for #385 (no appearance/theme edits, no unrelated remediation).
- **Residual follow-up (non-authorizing, operator-owned):** a small directive to realign `calendar-geometry.spec.ts` with `#380` Daylight (drop the stale `data-theme="light"` precondition) would clear result (b); it is a pre-existing spec-staleness issue independent of #385.

## 2026-07-25 · #382 CLOSED (directive:done) — V2 containment shell + governed navigation + preserved Agent panel MERGED

- **PR #383 merged:** reviewed/authorized exact head `05b7efe99944a23d34040bedcde8934eeb0a4f6e` squash-merged as `1a5c443e8aff1e1f6cf113ec1ff0145c984f2fde` at `2026-07-25T01:27:57Z` onto `main`. The approved head, the merge commit, and `origin/main` all share tree `7cba79136b784814a9f989025bcc4bcaf24dc634` — byte-equivalent; `git diff 05b7efe <main>` empty. Match-head squash merge, explicit operator authorization; held at the human merge gate, never self-merged.
- **Origin:** the shell-structure prerequisite before renewed calendar/run human UAT (after #380 Daylight). **Presentation + client-routing only — no backend/domain/schema/migration/configuration-generation change.** Ran the full critical-directive gate: GPT review → operator approval → CC read-only adversarial preflight (GO) → **Codex reconciliation `5071383590` rulings 1–8** → implementation.
- **What it delivers:** ONE containment shell (`components/workbench-shell.tsx`) is the SOLE global-navigation owner (ruling 3) — a responsive side rail (`full→icons→hidden`, ⌘/Ctrl-B, mobile overlay+scrim), a top lens menu, and a first-class Agent panel region — mounted once in `app/layout.tsx` under one `<ShellNavProvider>` wrapping `/` and `/runs/{id}`, preserving the single `<main>`. The in-workspace rail/lens chrome was removed in the same change (no duplicate authority). New: `lib/shell-lens.ts` (the ONE typed 3-class lens matrix), `components/shell-nav.tsx` (the ONE shared pure resolver bound to the live URL — render/click/keyboard/reload/popstate + `replace`-canonicalization + accessible notice), `components/agent-panel.tsx` (structurally-complete conversation panel + injectable adapter), `app/agent-adapter-probe/` (dev-gated injected-adapter probe). `components/stage-lens-matrix.ts` folded into `shell-lens.ts`. Stages stay derived from `/workflow-stages/active-enabled`; only lenses use the local 3-class matrix.
- **Rulings, implemented literally:** **1** root/no-run rail is context-only (Schedule current, Calendar root lens, no navigation, no fabricated run). **2** one 3-class lens matrix + one shared resolver; stages governed-derived. **3** sole rail owner, single `<main>`, no duplicate/transient rail. **4** behavioral floor preserved (URL-sync, per-run scope, `aria-current`, reload, governed derivation, provenance, fail-closed unavailable) — existing rows adapted for the moved DOM home WITHOUT weakening assertions (locator-only: `run-lens-toolbar→lens-menu`, `run-lens-{k}→lens-{k}`; lens vocab → 3-class, strengthened with `data-class`). **5** Agent hard stop — default adapter zero-I/O, composer disabled/non-queuing, `rounds/{id}/agent` out of BOTH `/gw` allowlists (still 403); transport-error ONLY via the dev-gated injected test adapter (`/agent-adapter-probe`, 404 outside `TANAGHOM_DEV_MODE`). **6** one versioned presentation-only key `wb-shell-chrome-v1` (no run/stage/lens/identity/authority/server data), namespaced off V1; malformed fails safe; mobile overlay never overwrites desktop rail mode; rail/agent mutually exclusive (keyboard-driven, occlusion-independent). **7** #380 deterministic light-first + Daylight token authority preserved. **8** scope ceiling — no backend/schema/generation change, no new content surfaces, no direction-persistence expansion, Agent authority untouched.
- **Evidence at the frozen head `05b7efe` (#370 fail-closed isolated lanes, serial/one-worker/ZERO-retries, native exits) — each SATISFIED, zero skips, `inventory_changed={}`:** `f382z` (zero-run+gov376) shell-containment+visual-system+daylight-a11y **20/20** — proves zero durable state before/after shell browse + agent open (Acceptance 4/11); `f382g` (zero-run+gov376) v376-run-planning **12/12** — VIEW-01/STG-01/02/CAL/MIX; `f382r2` (zero-run) v372+v373 **21/21** — regression incl. moved lens locators. Served-workbench real-browser zero-retry on the `f382z` topology (gov376, seeded runs — those files mix root+run-route tests): lens-menu 4/4, agent-panel 8/8, schedule-first-shell 5/5, scripts-stage 8/8. `tsc` 0; production `next build` 0. Eight induced-failure red controls (§H) each fail the suite on regression. Eight matched desktop(1280)+375px screenshots (root zero-run/full rail, collapsed rail, top lens menu, agent panel, RTL, mobile rail overlay, mobile agent drawer), every one the deterministic LIGHT canvas under forced OS-DARK (bgL≈0.98), with a head/state/viewport/direction/SHA-256 manifest — kept OUT of the committed tree (harness reproducible).
- **Disclosed, not masked:** two mobile stacking bugs the lane caught and I fixed (header/overlay z-order + close-control reachability) → rail⇄agent mutual exclusion made keyboard-driven and occlusion-independent; the agent no-I/O red control narrowed to forbid agent-endpoint + `/gw` mutation requests only (the page's own calendar GET reads of seeded runs are not the panel — the panel is pure client state), the transport attempt still caught; `#372/#373` hit two documented test-harness transients (`socket hang up` in the self-provision path, `route.continue` route-flip race) — byte-identical specs, cleared by clean re-runs to 21/21. The retained off-limits `tan-human372-0723` UAT lane was untouched (verified in the before/after inventory).
- **Release ceiling:** passing authorizes only a SEPARATE, genuinely clean **zero-run human walkthrough** of the restored shell — NOT started during closeout. NOT production/media, NOT deployment, NOT external-integration or Agent-authority readiness (exposing the V1 agent through V2 remains a separate authority/integration directive).
- **Residual follow-ups:** (a) the clean zero-run human walkthrough is the deliberate next gate, launched separately from committed `main@1a5c443`; (b) the deterministic screenshots/manifest were kept out of the committed tree (the frozen head is presentation + specs only) — regenerable on demand from the harness; (c) the retained `tan-human372-0723` UAT containers remain off-limits to the executor and were untouched.

## 2026-07-24 · #380 CLOSED (directive:done) — Tanaghom Daylight presentation-only visual system MERGED

- **PR #381 merged:** reviewed exact head `372af64a9c269ac1e0740fb1323522d358849d60` squash-merged as `0f3659bea624fff118cee98f75fa47e2de207a88` at `2026-07-24T13:32:53Z` onto `main`. `git diff 372af64 <main>` is **empty** and the two trees are the SAME object (`4091b46b1cb65ecaea1ea403edef606743e4acff`) — byte-equivalent to the reviewed/authorized head. Explicit operator merge authorization for that exact SHA; held at the human merge gate, never self-merged.
- **Origin:** the visual precursor for the renewed calendar-first human UAT after #376. **Presentation-only by directive** — no product/domain/API/schema/routing/data change. Architecture, interaction semantics, FullCalendar geometry, and governed truth are all unchanged.
- **What it delivers:** a deterministic **light-first** Daylight semantic-token layer in `workbench/app/globals.css` (OKLCH surfaces/text/borders/accent/status-soft via `color-mix`, calendar-state bridge tokens, shadow/radii/type-scale/spacing scales). The `@media (prefers-color-scheme: dark)` OS-follow block was **removed** — base `:root` renders deterministic Light and only `:root[data-theme="dark"]` is non-light. Appearance is now explicit **Light | Dark** only (`presentation-prefs.ts`: `"system"` removed, `DEFAULT_APPEARANCE="light"`; pre-paint init in `layout.tsx` sets/removes the attribute deterministically; a stale stored `"system"` resolves to Light).
- **WCAG AA, proven deterministically:** new self-contained `scripts/daylight-contrast.mjs` parses the globals.css tokens, resolves `color-mix`, converts OKLCH→sRGB and asserts 20 token pairs ≥ threshold (4.5 text / 3.0 UI) in **both** Light and Dark — 20/20. To clear AA the accent was **deepened** (`oklch(57% 0.16 50)`, from L66) and border-strong darkened; this was a required accessibility correction, disclosed as such, not a silent restyle.
- **Behavioral evidence at the reviewed head:** visual-system spec 11/11 (OS-dark must NOT darken the default; Dark is explicit-only; stale `"system"`→light; storage-denied→light), daylight-a11y 3/3 (visible `:focus-visible` ring on every control, keyboard traversal to New run + all composer actions, Light holds under both OS prefs and RTL), matrix 12/12, #372/#373 regression 21/21, contrast 20/20, `tsc` 0, production `next build` 0. Serial / one-worker / zero-retries, native exits.
- **Codex review of 85d34ac found a bounded evidence-harness defect (not a product defect), corrected at the frozen head:** the prior `scripts/daylight-screens.mjs` skipped the `blocked` state and `.catch(()=>{})`-swallowed required waits, so it could pass while recording the wrong thing. Rewritten **fail-closed by construction**: five required deterministic states (`zero-run`, `blocked`, `recommendation`, `populated`, `rtl`) captured for real across TWO genuine lane MODES (`no-policy` → zero-run/blocked/rtl; `with-policy` → recommendation/populated) on the unmodified base lane, every state hard-**asserted** (wrong page / mis-enabled control / unwritten file → nonzero exit), emitting a `<label>-manifest.json` binding each shot to label, exact source head, fixture, viewport, direction, emulated OS scheme, rendered theme attr, body-bg lightness, and SHA-256. Matched before/after regenerated under forced OS-**dark**: BEFORE (main@93a63d9) 5/5 all `body_is_dark:true` (System follows OS-dark); AFTER (branch) 5/5 all `body_is_dark:false` (deterministic Light) — the determinism delta is machine-checkable. The prior harness defect was disclosed in the PR. The frozen head differs from the reviewed 85d34ac by exactly one file (the harness); exploratory lane edits were reverted.
- **Two genuine issues fixed during the slice, disclosed honestly:** daylight-a11y RTL focus modality (toggle direction via keyboard so `:focus-visible` matches — a preceding pointer click would suppress it and make the assert vacuous), and `schedule-first-shell.spec.ts` stale `create-run` → `new-run` testid (orphaned by #376's composer rename). A presentation-lane run of unrelated specs against the down/stale pre-seeded #345/#348 dev DB was fixture-starvation (missing `GOVERNED_GEN_376`), not Daylight regressions — diagnosed and disclosed, not chased.
- **Release ceiling:** the harness is HARNESS-ONLY (no product surface). Passing authorizes only the next step — a **separate, genuinely clean zero-run human walkthrough** of the Daylight surface, launched independently from committed `main`. NOT started during this closeout; not production/media/readiness.
- **Residual follow-ups:** (a) the clean zero-run **human UAT walkthrough** is the deliberate next step, to be started separately from committed `main`; (b) captured PNGs/manifests were kept OUT of the committed tree (frozen head is the one-file harness fix) — regenerable on demand from the harness; (c) the retained `tan-human372-0723` UAT containers remain off-limits to the executor and were untouched.

## 2026-07-24 · #376 CLOSED (directive:done) — calendar-first run planning + governed mix recommendation UX MERGED

- **PR #379 merged:** reviewed exact head `8ac41a0254d1d38b9ab79fc4f640f64ed47d584e` squash-merged as `8610677a0b98988be44869e96b1fc969393cd168` at `2026-07-23T20:08:40Z` onto `main@eacc9b83`. `git diff 8ac41a0 8610677a` is **empty** and the two trees are the SAME object (`4cbc5f7d…`) — byte-equivalent; merge parent is exactly the reviewed base. 27 files, +2008/−382. Match-head merge (pinned to the exact SHA). **Codex re-review 4767596486 CLEAR + independent GPT review 4767617395 CLEAR**, both at that exact head; explicit operator merge authorization.
- **Origin:** the first human-UAT correction slice after #372, consuming #377's authority. #376 was kept blocked/untouched through its own preflight and reconciliation; this was its first implementation. Under GPT amendment `5055078429` and Codex reconciliation rulings **A–E** (`5060583293`).
- **What it delivers:** ONE ephemeral run composer (`run-composer.tsx`) reached by all three entry paths — date click, inclusive range drag-select, `New run` — replacing the detached create-run form (deleted). The inclusive range IS the duration (no independent `days`). Calendar/Grid/List are three projections of ONE authoritative slot collection (each emits `data-slot-order`; divergence is detectable). A canonical active-stage projection drives the rail. Migration-free, V1 untouched, no new authorization model — the `/gw` boundary widened by exact-match only for the #377 reads + the preview/proposal writes.
- **Rulings, implemented literally:** **A** — new side-effect-free `GET /workflow-stages/active-enabled` (canonical active-stage projection); the rail consumes it, so a disabled stage is absent *because the generation disabled it*, not a client filter. `/workflow-stages/active` unchanged for existing consumers. **B** — one governed `stage_label` `Approved for production` via draft → update → activate (no alias, no derived string, no seed rewrite, no schema field, no active-generation mutation). **C** — no browser commit floor; GAP-02 mechanism, GAP-07 human-UAT consequence only. **D** — MIX-03 (no current policy → typed blocked) and MIX-01 (policy minted → recommended path) on deliberately distinct governed setup, serial order enforced. **E** — the retained human lane is created only after automated acceptance (NOT stood up during merge closeout).
- **Codex review 4766819179 [P1], valid and load-bearing:** the composer fired `POST /run-mix-proposals` on *Get recommended mix*, inserting a `run_mix_proposal` row + `run_mix_proposal_created` audit event **before** the explicit Plan run — a durable side effect GPT amendment 4 forbids, and the green matrix accepted a pre-submit fence. Corrected without weakening #377 authority/snapshots: (1) new **side-effect-free** `POST /run-mix-recommendation-preview` = `run_mix.recommend()` verbatim (pure SELECT, no proposal/audit/id), returning a `preview_fingerprint`; (2) the durable fence AND the run are minted **only** by the explicit Plan run (submit does proposals→rounds, proposal cached per submission so a retry converges on one run); (3) `create_proposal` gained an `expected` fingerprint — preview→submit generation drift fails closed with typed **`recommendation_stale`** BEFORE any insert, showing the refreshed recommendation for review. The provenance panel shows no proposal id at preview (none exists) and states it is minted on Plan run.
- **Discriminating persistence evidence (Codex point 4):** backend `run_mix_selftest §4a` (new) captures proposal-row/audit-event/round/slot/gate counts, runs a preview, and asserts every one is unchanged, then that only the explicit proposal call persists — plus the stale gate leaves counts unchanged and a fresh-preview submit is accepted. That is where proposal/audit discrimination lives, because the browser boundary deliberately cannot list proposals or read audit. Browser **MIX-01** asserts `/gw/rounds` empty after opening/editing + after preview; **MIX-04** (new) proves the stale gate in-browser.
- **Two correctness bugs the adversarial preflight/proofs caught earlier in the slice:** the `days` conflict was dissolved by `begin_binding`'s independent `days × posts_per_day` + `starts_on` cross-check (a miscomputed range is refused upstream), and the FullCalendar v7 day cells are addressed by their public `data-date` (the class names are hashed).
- **Evidence at the merged head `8ac41a0` (#370 fail-closed topology, `FIXTURE=zero-run GOVERNED_GEN_376=1`, serial/1-worker/0-retries, native exits):** v376 matrix **12/12 mandatory PASS → ACCEPT**, `reconciled:true`, exit 0, inventory `changed:{}`, served-source byte-bound, dep-lock consumed. #372+#373 regression **21/21 PASS, SATISFIED, exit 0**. Backend `gates/run_mix_selftest.py` **165 checks, 0 FAIL, exit 0** (incl. the new §4a preview + stale-gate proofs); `gates.selftest` **ALL PASSED, exit 0**, migration 035 rerun idempotent (`migration_035_idempotent: 0`), writer stub. Matrix-executor red proof (now matrix-parameterized — one audited executor for both #372 and #376) discriminates for both. `tsc` 0; production `next build` exit 0. Every one of these was re-run at the exact frozen head, not carried forward.
- **A disclosed transient, not buried:** one earlier v376 matrix attempt hit a `.fc-daygrid-day` selector miss (v7 class names are hashed) → fixed to `data-date`; one earlier #372/#373 attempt had a single `apiRequestContext disposed` fixture-setup transient in a #373 row untouched by #376, cleared by a clean re-run. Both attempts were reported.
- **Release ceiling:** passing authorizes only renewed human UAT of run planning and the next bounded UX correction. NOT production/media, NOT production readiness, NOT external-integration readiness, NOT analytics-driven adaptation. Automated green declares no human acceptance.
- **Residual follow-ups:** (a) the retained clean **MIX-01 human-UAT lane** (ruling E) is to be started SEPARATELY from committed `main` — `FIXTURE=zero-run GOVERNED_GEN_376=1 RUN_MIX_POLICY=1 KEEP=1` gives zero runs + a valid active generation + baseline eligibility + a current recommendation policy — and was deliberately NOT stood up during merge closeout; (b) GPT's non-blocking residuals: an explicit two-request submit interrupted between proposal creation and bind can leave a governed unbound proposal (expires; the bounded retention purge reclaims it), and retry convergence is strongest within one composer session; (c) the retained `tan-human372-0723` UAT containers remain down from an earlier unrelated Docker Desktop stop and were not touched (off-limits to the executor); (d) the pre-existing `gates.api_selftest` block (proven pre-existing at base by #377) is unowned test-harness debt, untouched here.

## 2026-07-23 · #377 CLOSED (directive:done) — governed run-mix recommendation authority + immutable proposal snapshot MERGED

- **PR #378 merged:** reviewed exact head `c7987c2f51fbdc91138797d85b45f8ff2a0674e3` squash-merged as `615e43d084ab66a0d2857b84232d1448d47e31f2` at `2026-07-23T14:47:34Z` onto `main@2900b844`. `git diff c7987c2 615e43d0` is **empty** and the two trees are the SAME object (`e02fa751…`) — byte-equivalent, and the merge parent is exactly the reviewed base. 6 files, +2496/−8. Codex exact-head review CLEAR, independent GPT review CLEAR, explicit operator merge authorization for that exact head.
- **Origin:** the prerequisite split out of **#376's STOP**. #376's preflight proved (a) NO governed run-mix recommendation authority existed anywhere in the repo — a mix recommendation would have had to be fabricated in the UI — and (b) the amendment-3 immutable proposal snapshot is **not representable migration-free**. #377 supplies the authority; **#376 was kept blocked and byte-untouched throughout**.
- **What it delivers:** `db/migrations/035_run_mix_recommendation.sql` (additive, guarded, single-transaction, rerun-safe, no backfill) + `gates/run_mix.py` (the authority) + the `/run-mix-policy`, `/run-mix-proposals`, purge and `/rounds/{id}/recommendation-snapshot` endpoints + an atomic proposal→round binding threaded through `planner/plan_round.py`, with `gates/run_mix_selftest.py` (150 discriminating checks) and `tools/run_mix_lane_377.mjs` (candidate-only evidence lane).
- **Deterministic posture, resolved by evidence not preference:** every governed model route in the repo is a **content writer**; no governed *planning* route exists. So the recommendation is **deterministic-only** — `largest_remainder_v1` reusing `planner.scale_distribution` (no reimplemented apportionment), `model_posture='not_applicable'`, and a `DETERMINISTIC_STATEMENT` embedded in EVERY rationale: *"No model was called. This is not an AI recommendation and makes no claim of optimization, personalization, learning or quality."* That also **empties the privacy surface entirely** — no prompt, no completion, no retained model I/O.
- **Policy authority = governed generations, never a hardcoded default.** `run_mix_recommendation_policy` is `status current|superseded` with a partial unique index enforcing **exactly one current**; creation is create-missing-only and reruns are idempotent and non-destructive (an operator-owned probe row survives apply→re-apply verbatim). Weights are keyed by `content_format_version.version_id`, so a **rename cannot re-point a governed weight**. `weight_source` admits only `'explicit'` — nothing is silently derived.
- **Codex review 4762785403 [P1], valid and load-bearing:** generation immutability was **application discipline only**. A direct `UPDATE` of `weights`/`algorithm`/`authority_version` would have changed future recommendations under a *stable* `(policy_id, generation)` citation and made every pinned provenance retroactively ambiguous. Fixed with a DB `BEFORE UPDATE` row trigger freezing 14 identity/configuration columns, permitting **only** the governed `current → superseded` lineage transition (reactivation impossible), with **write-once** `superseded_at`/`superseded_by`. It is UPDATE-only, so generation creation and migration rerun behaviour are preserved. 34 new red proofs run against **both** a current and a superseded row — a freeze that thawed once superseded would leave exactly the historical evidence unprotected — plus proof the authorized path still mints generation 3 with the supersession link intact.
- **Honest caveat kept in the evidence rather than engineered around:** `algorithm` and `weight_source` are enum-like, so their CHECK constraint catches a forged value *before* the trigger does. The proof asserts the edit cannot land and names which guard caught it; the CHECK was **not** weakened to route the case through the trigger.
- **Fence, digest, replay:** the proposal is a **durable server-side fence**, not a signed token — single-use `SELECT … FOR UPDATE`, `CHECK ((status='consumed') = (bound_round_id IS NOT NULL))`, unique `bound_round_id`, and a freeze trigger permitting only `pending→consumed`. The digest is versioned canonical JSON + SHA-256 (sorted keys, NFC, integers as integers, ISO dates) written **with** the row so it is digest-correct from birth. Idempotency keys are scoped-unique: a replay **converges** to the same round; a divergent reuse is a typed conflict. Snapshots are append-only (no-UPDATE trigger).
- **Typed blocked/refusal codes, never a silent fallback:** `no_current_recommendation_policy`, `baseline_eligibility_unavailable`, `no_eligible_frameworks`, `eligible_version_unweighted`, `all_weights_zero`, `minima_exceed_slots`, `maxima_below_slots`, `minimum_exceeds_maximum`; and on binding `proposal_expired`, `proposal_digest_mismatch`, `proposal_context_mismatch`, `idempotency_key_conflict`, `recommendation_policy_superseded`, `baseline_policy_superseded`, `eligible_set_changed`, `configuration_generation_changed`.
- **Two correctness bugs the adversarial proofs caught (both real, both fixed):** (1) a duration/posts-per-day mismatch surfaced as a planner **422** instead of the typed **409** — binding verification was moved AHEAD of `validate_format_mix` so the operator is told the cause, not a consequence; (2) that move then **leaked a connection holding the `FOR UPDATE` fence lock** when validation raised, which would have hung the operator's next attempt on the same proposal — fixed with rollback+close on every raising path. V1's proposal-less round creation is untouched.
- **Evidence at the merged head:** run-mix candidate lane **150 PASS / 0 FAIL**, native **exit 0**, `inventory_clean true`; `--induce-failure` native **exit 1** with teardown and clean inventory (the lane can actually fail); `PROOF=gates/selftest.py` **328 PASS, exit 0**; `migration_035_idempotent: 0`. The lane is `EXPECT_SHA`-bound to a clean worktree, pins pgvector by digest, verifies the gate API in **exact** `"writer_mode":"stub"`, byte-compares the served source, takes a BEFORE/AFTER inventory and tears down in `finally` — it touches no shared, operator, V1 or retained-UAT resource.
- **One pre-existing block, disclosed and proven pre-existing:** `gates.api_selftest` blocks at `api_selftest.py:423`. A **control run at the base SHA** produced an identical 95 PASS and a **byte-identical traceback** — it is not #377's, and #377 touches none of its tables.
- **Environment note:** Docker Desktop stopped mid-session (unrelated); the daemon was restarted to keep validating. That stop killed the retained human-UAT containers `tan-human372-0723-api` / `-db`. They were **deliberately not restarted** — that lane is off-limits to the executor — and were left untouched through closeout.
- **Residual follow-ups:** (a) **#376 may now renew its READ-ONLY preflight pinned to the new merged `origin/main`** — its blocker is cleared, but it is still `directive:running` from its STOP and needs an operator decision to resume; (b) the rerun-idempotency proof is **035-scoped**, because a full historical migration replay aborts on a pre-existing `008` (`asset_id_version_slot_uniq`) — a repo-wide rerun claim would have been a false green; (c) the `api_selftest.py:423` block is unowned test-harness debt; (d) the retained UAT lane containers are down and await an operator decision to restart.

## 2026-07-23 · #372 CLOSED (directive:done) — browser operator-journey acceptance matrix MERGED

- **PR #375 merged:** reviewed exact head `39797f77d0e18bf37f90575437ab8b908dc15e70` squash-merged as `8fc67c715a7a5ed72d88a6b7162b8eef5d539747` at `2026-07-23T02:08:04Z` onto `main@9b91378`. `git diff 39797f7 8fc67c7` is **empty**. 6 files, +1158/−3; **test-harness only** — no product/schema/authority/V1/provider/deploy/shared-data change.
- **What it delivers:** the operator-approved browser acceptance gate for Schedule → Topic → Script on the #370 fail-closed topology — a committed machine-readable matrix, a 14-row browser spec driven entirely through VISIBLE rendered controls, a generated evidence bundle (matrix ID → result → artifact) with a truthful ACCEPT/REJECT/CONDITIONAL, a 6-entry gap register, and a discriminating red proof for the matrix executor.
- **The three binding rulings, implemented literally:** PRE-01 **stage advancement is GOVERNED SETUP, never a claimed browser control** (V2 exposes no resolve/commit/advance write path; every transition runs through explicitly-named `governedSetup*` helpers). PRE-02 **recovery = `reopen`**; `restore_revision` is unrepresentable-by-design (GAP-01) and never counted as passed. PRE-03 **Drop is RECORD-ONLY** — TOP-05 proves a decision is recorded AND the item does not transition, so nothing implies V2 committed.
- **Rows (19 mandatory):** SCH-01 create-run · SCH-01N invalid-mix typed refusal with INDEPENDENT non-mutation proof · SCH-02 inspect + actually SWITCH a calendar view (`data-view` changes) · SCH-03 governed reorder · SCH-05 **true multi-context** stale-token refusal (two browser contexts, typed conflict, non-mutating) · SCH-04 focus retain/restore · TOP-01 inspect+history · TOP-02 edit · TOP-03 send-back · TOP-04 undo · TOP-05 record-only Drop · TOP-06 reopen · TOP-07 typed-unavailable · SCR-01 Script workspace · SCR-02 Script send-back (must be OFFERED + persisted tally) · SCR-03 visible **"Reopen"** 1:1 + no Restore alias · XC-01 reload/nav durability · XC-02 direction+theme · XC-03 375/768/1280 reachability. #373's already-green rows are CITED via a `PROOF_SPEC` multi-spec seam, never duplicated.
- **TWO Codex review cycles, every finding valid.** Cycle 1 (four false-green paths): SCH-02 asserted no view switch; SCR-03 asserted only the alias's absence (would pass with NO recovery control); SCR-02's offered/denied branch let a denied placeholder satisfy a mandatory VALID row; SCH-01N never proved non-mutation. All four hardened — mandatory accounting preserved, no row reclassified or dropped to reach green.
- **Product/boundary truths surfaced by the acceptance itself (each corrected INTO the matrix, never worked around):** (1) create-run does **not** gate submit client-side — the planner owns the mix contract and V2 relays its typed 422 verbatim; (2) `SERVED_GATES = ["script_review"]` — the `/gw` stage-state read is Script-only by design, so Topic rows take in-boundary principal-bound evidence (a decision exists ⇒ `undecide` becomes available); (3) an **unplaced** run renders `run-schedule-calendar-unplaced` and has no calendar to navigate (placement is now a recorded governed-setup prerequisite); (4) **GAP-06 — RTL direction is session-only**, it does not persist across reload while theme does.
- **Evidence at the merged head (fail-closed #370 topology; `EXPECT_SHA` clean tree; serial/1-worker/0-retries; unmasked native exits):** SUCCESS `discovered=21, {passed:21, failed:0, timedOut:0, interrupted:0, skipped:0, flaky:0}`, `reconciled=true`, **SATISFIED**, exit 0, every phase exit 0, inventory `changed:{}`. INDUCED-FAILURE native **exit 7** preserved + teardown/inventory verified. Evidence bundle **mandatory 19/19 → ACCEPT**. Matrix-executor red proof **11/11 DISCRIMINATE** (absent/failed/skipped/timedOut each flip the verdict away from ACCEPT). `#370` default single-spec path re-verified **3/3 SATISFIED** (the shared-harness seam is additive). `tsc --noEmit` exit 0.
- **Recommendation recorded: ACCEPT for the AUTOMATED gate only.** Human visual acceptance remains a separate explicit operator decision; passing authorizes **drafting/starting** the Production/media vertical-slice directive and claims no production readiness, no external-integration readiness, and no complete SDR delivery.
- **Gap register (6):** GAP-01 restore_revision unrepresentable-by-design · GAP-02 the commit floor is not a V2 control · GAP-03 no focus-trap (no modals exist at this source) · GAP-04 no unauthenticated/unauthorized browser posture (V2 signs one fixture principal) · GAP-05 no distinct 768/1280 layouts (reachability + no-overflow only) · **GAP-06 RTL direction does not persist across reload**.
- **A disclosed transient, not buried:** one SUCCESS attempt aborted mid-reprovision with `fetch failed` (transient connection error, two lanes back-to-back). It was not a code failure — the induced run at the same head cleared that phase — and both attempts were reported rather than only the passing one.
- **Residual follow-ups:** (a) **GAP-06** (direction persistence) is a genuine product finding worth its own directive; (b) `gates.api_selftest`'s RIDEM teardown vs the #359/#362 background workers remains a pre-existing test-harness fragility (carried from #373); (c) the Production/media vertical-slice directive may now be DRAFTED — not started — and human visual acceptance is still owed.

## 2026-07-22 · #373 CLOSED (directive:done) — restore/undo representability + focus recovery + responsive acceptance MERGED

- **PR #374 merged:** reviewed exact head `b8f2139d3e1906c4cbc7135cd8dfcbeb60608ec3` squash-merged as `e1922be800273cabfc0045c56eed339a0bbb67c1` at `2026-07-22T17:43:00Z` onto `main@350743f`. `git diff b8f2139 e1922be` is **empty**. 12 files, +786/−32; **0 files under `db/`** — no schema/migration; V1 + closed `next_action` union untouched. Product change scoped to the four #372 blockers only.
- **Origin:** the prerequisite correction split from #372's browser-acceptance STOP (its mandatory journeys — Topic restore, clear/undo, focus restoration, 768/1280 — were unrepresentable). Under three binding Codex reconciliation rulings.
- **Ruling 1 (reopen, no alias):** `engine.topic_item_actions` emits a typed `reopen` action whose availability matches `engine.reopen` EXACTLY (reject/approve state + a committed decision). DISTINCT from `restore`(=`restore_revision`, version-nav). Topic + Script render a 1:1 **"Reopen"** control → `POST /gw/slots/{id}/reopen`; the prior Script **"Restore"→reopen alias** (a reopen call gated on restore_revision eligibility, labelled "Restore") is corrected.
- **Ruling 2 (exact authoritative gate projection):** `topic_item_read_model` projects `authoritative_gate_id` ONLY when exactly one open gate applies (else null); a typed `undecide` action is emitted. Both panels render an **"Undo decision"** control → `POST /gw/gates/{authoritative_gate_id}/undecide`; the client consumes the id directly (never derives/sorts/searches/falls-back/chooses). Migration-free (read-time over existing `gate`/`gate_target`/`gate_decision`); V2-only (topic_item not read by V1); one optional additive read-model field.
- **Codex P1 correction (undecide correctness — the load-bearing fix):** availability is bound to the EFFECTIVE TRUSTED PRINCIPAL's OWN decision (`gate_decision … AND approver_id=actor`), never any approver; an unsigned read → `principal_missing`. The actor is threaded read_model→actions→_undecide_action; the API resolves the optional trusted principal; **V2's `/gw` signs `topic_item` reads** (same posture as the action-decision read) so "can I undo?" matches the principal the undo WRITE uses. `clear_decision` clears ONLY the caller's decisions and RAISES on a zero-delete (no phantom success). Before this, the projection checked ANY approver while the write cleared only the signed principal — a false-success gap.
- **Codex P2 correction (focus):** run-schedule focus restoration fires ONLY on a SETTLED outcome (`ok|error|conflict`); during `busy` (pending) focus is RETAINED on the initiating control. Focus restoration overall reuses the existing in-repo `statusRef`+`tabIndex=-1`+`role=status` pattern on the two unhandled unmount sites — no shell/global change.
- **Ruling 3 (responsive = acceptance coverage, NO CSS):** static measurement reproduced no 768/1280 defect (fluid layout; the one grid already authored for both widths), so no CSS was added; the acceptance asserts 375/768/1280 reachability + no page-level horizontal overflow. 375 regression preserved; FullCalendar untouched.
- **A genuine V2-semantic finding, surfaced:** per-item **Drop is record-only** ("advances at the human commit"), so `reopen` (which reverses a COMMITTED decision) is eligible only after a governed commit — the acceptance drives the drop as governed setup and Reopen as the UI action. Also: fresh candidate DBs have **no active workflow version**, so `/gw/workflow-stages/active` 404s and the stage rail is empty — the acceptance fixture seeds the baseline via `GET /workflow-versions/active` (why a browser acceptance had never before exercised the rendered item panels in this topology).
- **Evidence at the merged head `b8f2139` (fail-closed #370 topology reused via `PROOF_SPEC`; `EXPECT_SHA`-bound clean tree; serial/1-worker/0-retries):** browser operator-journey acceptance **7/7 PASSED, reconciled, SATISFIED** (visible-control-driven: R1 Reopen loop, R2 Undo-decision loop through the signed principal-bound read, R2 typed-unavailable, R3 schedule-focus retain/restore, R4 375/768/1280 reachability). INDUCED-FAILURE native **exit 7** preserved + teardown/inventory verified. Backend `gates.topic_recovery_selftest` **16/16** incl. the Codex P1 red proofs (A-vs-B, principal_missing, non-owner zero-delete raises + owner decision intact, owner-clear) and the B3 >1-gate no-latest-pick proof. `gates.selftest` ALL PASSED. Affected browser regressions **27/27** (`scripts-lifecycle-367` updated for the reopen relabel + `topic-item-governance` + `bilingual-review-ux`). `tsc` 0; engine py_compile OK.
- **One honest ceiling, disclosed:** `gates.api_selftest`'s reopen (§4) + topic_item (§11) sections pass with #373 (0 FAILs), but its RIDEM idempotency teardown fails on a fresh candidate lane — a `generation_job`/`script_provenance` FK chain + a lock deadlock with the #359/#362 background generation/drain workers in the API container — a PRE-EXISTING test-harness fragility unrelated to #373's logic. An out-of-scope patch attempt was reverted (untested); flagged for separate test-hardening.
- **Release ceiling:** passing does NOT accept the operator journey and does NOT authorize Production/media. It ONLY authorizes renewing #372's read-only preflight at the merged exact source.
- **Residual follow-ups:** (a) #372's read-only preflight must be RENEWED pinned to the new merged `origin/main` (baseline evidence cannot satisfy the post-correction #372 preflight); (b) `gates.api_selftest` RIDEM-teardown vs background-worker hardening (separate item).

## 2026-07-22 · #370 CLOSED (directive:done) — current-main deterministic V2 lifecycle validation topology MERGED

- **PR #371 merged:** reviewed exact head `8b7d5be301fdde09b9840cc9acfe5c0421bee0be` squash-merged as `a0b9c3fd52bbb2d076a41c650f8b74eb2fa715e0` at `2026-07-22T13:04:27Z` onto `main@b84efb5c`. `git diff 8b7d5be a0b9c3f` is **empty**. 2 files, +726/−0; **0** files under `db/` — validation-infrastructure only, no product/schema/authority change. Supersedes #345 (obsolete PR-#341 target) → #345 is now a closure candidate.
- **What it delivers:** a reusable, isolated, deterministic local topology that runs the REAL V2 workbench through canonical `/gw` to an exact-head stub gate API and a disposable synthetic Postgres — retiring the mocked-`/gw` false-green ceiling. Two authorized test-harness files: `workbench/scripts/v2-validation-lane.mjs` (Node orchestrator) + `workbench/e2e/v2-lifecycle-realroute-370.spec.ts` (browser-issued real-`/gw` proof). It freezes one governed action per Content stage — Schedule (#292 reorder), Topic (governed edit), Script (governed request_change) — each issued FROM THE BROWSER, observed via the page's response events, and correlated with an independent persistence read after reload.
- **Genuine finding the mocked specs never surfaced:** V2's per-item read boundary permits ONLY `artifact=script`, so Topic must be read via `topic_item` with NO artifact param — exactly the false-green class this topology exists to close.
- **The topology is FAIL-CLOSED across seven governed dimensions, each fail-closed on mismatch:** (1) EXACT-source — `EXPECT_SHA` is a REQUIRED full-40-hex input; the run refuses before startup unless the worktree is clean AND HEAD equals it, and asserts the API bind-mount + built workbench came from that accepted source (container-side `sha256sum` == host, fresh build id). (2) A PREDECLARED deterministic manifest (candidate/db/tenant-workspace/run/slot/lifecycle/count/ownership + identity hash) declared BEFORE startup and compared field-by-field against an independent DB read after BOTH the provision and a reset(`TRUNCATE round CASCADE`)+reprovision (deterministic identity + changed `xmin` = genuinely re-created rows); the ownership marker+hash persisted in candidate fixture state (a row in the disposable DB's existing `audit_log` — no DDL). (3) EXACT Script decision/audit — after a real `/gw` request_change, the precise `gate_decision` (decision/notes/approver) + correlated `audit_log` (`detail{gate_id,decision,notes}`) are read straight from the DB and correlated to the request by returned `gate_id` + a unique comment. (4) A candidate dependency LOCK generated before launch (full `pip freeze` from a disposable resolver, every package incl. the one ranged `openai` dep pinned `==`) and CONSUMED to build the gate API via `pip install --no-deps`; the running installed set is ASSERTED equal to the lock. (5) A STRICT six-category ledger (passed/failed/timedOut/interrupted/skipped/flaky) requiring `passed===discovered===EXPECTED` with every other category zero, discovery+proof exit 0, retries 0 — a skipped/timed-out run cannot satisfy. (6) A named BEFORE/AFTER unrelated-state inventory — containers, networks, volumes, worktrees, listeners, running-PostgreSQL-containers-discovered-by-image (+ their logical DB sets, no hard-coded operator name), tracked-file status, and bounded config content — compared in-process and failing on ANY difference, after waiting for the workbench to exit and its ports to release. (7) Independent native exit accounting for every phase, never masked; images pinned by DIGEST; a UNIQUE candidate network created and destroyed.
- **SIX Codex exact-head review cycles + GPT, every finding valid.** The arc: mocked-`/gw` inertness and aggregate-only assertions → real browser-issued actions + exact-record verification; recorded-but-unenforced identities → fail-closed enforcement (dirty/SHA, lock equality, served binding); ledger that could pass on skips → strict six-category model; inventory that missed listeners/logical-DBs/config and raced teardown → extended + port-release-gated; a hard-coded operator container name `tanaghom-db` → non-mutating PostgreSQL discovery by image metadata; optional `EXPECT_SHA` → REQUIRED full-40-hex. GPT CLEAR at `8b7d5be` (no remaining false-green risk). Codex #345-supersession reconciliation confirmed.
- **Evidence at the merged head (fresh candidate lane per run, `EXPECT_SHA`-bound to the committed head, clean tree, unpiped native exits read directly; serial `--workers=1 --retries=0`; own disposable Postgres — no shared-DB overlap #179):** SUCCESS → `SATISFIED`, process **exit 0**, every phase exit `0` (source_identity/network/db/migrate/lock/api/wb_build/wb_start/served_binding/deps_verify/fixture/reset/reprovision/decision_verify/discovery/proof/teardown), proof `categories={passed:3,failed:0,timedOut:0,interrupted:0,skipped:0,flaky:0} reconciled=true`, inventory `changed:{}`. INDUCED-FAILURE (`--induce-failure`) → a real child exits nonzero after resources exist, native **exit 7 preserved** (never masked), failure-path teardown + full inventory verified. Fail-closed proven: omitted/malformed/wrong `EXPECT_SHA` each refuse before startup creating nothing. `tsc --noEmit` exit 0; `next build` exit 0 in bring-up.
- **Evidence ceiling:** one isolated topology, exercised on this host; it is the VALIDATION INFRASTRUCTURE, not a product/full-suite/production-readiness claim (#285 stays separate). A `SATISFIED` outcome authorizes DRAFTING — not executing — the separate browser operator-journey acceptance directive on this topology, which must precede any Production/media implementation slice.
- **Two environmental issues hit and fixed truthfully, neither masked:** the tenant probe read the lazily-seeded `workflow_version` (empty) → switched to `methodology` (populated by load_methodology); the pgvector initdb readiness race (temp server answers, then restarts — socket-missing / shutting-down windows) → require two consecutive real queries + retry `CREATE DATABASE` across transient windows.
- **Teardown / ownership:** only the named candidate resources per run (disposable `tan-<lane>-db`/`tan-<lane>-api` containers with anonymous volumes removed via `rm -f -v`, unique `tan-<lane>-net` network, per-lane DB, runtime artifacts in tmp); the before/after inventory verified the shared `tanaghom-db`, all unrelated containers/networks/volumes/worktrees/listeners/logical-DBs, and the tracked tree were byte-identical. Container inventory 63→63 across every run.
- **Residual follow-ups:** (a) draft the browser operator-journey acceptance directive to run ON this topology (prerequisite for Production/media); (b) #345 is now a closure candidate (obsolete PR-#341 target superseded) — normalize/close under a separate pass; (c) the listener/logical-DB inventory depends on external quiescence during a run (a concurrent unrelated DB create would fail-closed) — acceptable per the contract, worth noting for CI placement.

## 2026-07-22 · #367 CLOSED (directive:done) — governed Script review lifecycle vertical slice MERGED

- **PR #368 merged:** reviewed exact head `dc7e5cf9e9367763fae0eb5c9e9eb8737977e25b` squash-merged as `3f7cb229329722caea10c7460b0495431cc23187` at `2026-07-22T07:03:22Z` onto `main@561ecb7`. `git diff dc7e5cf 3f7cb22` is **empty**. 8 files, +1012/−46; **0** files under `db/` — no schema, migration, or Topic-lifecycle change.
- **What it delivers:** the governed Script review lifecycle in V2 (inspect · immutable revision history · edit-appends · request-change + governed rework · approve a selected revision · recoverable drop/restore · clear/undo · typed states) over the CANONICAL, artifact-generic engine mechanism — plus the three cross-artifact backend defects the reconciliation named. Additive: no new lifecycle, no parallel state machine, no schema, no migration.
- **Reconciliation basis:** GPT amendment (comment 5041652384) + Codex reconciliation (5041934397) — R1 (no new non-latest approval semantics; canonical stable pin only), R2 (expose via the stage-scoped projection; NO new `next_action`/V1 union member), R3 (three additive artifact-threading corrections stay in-slice, including the durable Script rework worker).
- **The three R3 backend corrections (all artifact-generic reuse, not new mechanism):** (1) `decide()` CAS/eligibility thread the gate's `rework_mode` artifact instead of a topic literal — a script approve-with-CAS/drop previously validated against the TOPIC head. (2) `/slots/{id}/approve` + `/slots/{id}/drop` (and request_change) thread `artifact` (default topic, V1 unchanged). (3) the durable rework worker `run_rework_operation` dispatches on `op["artifact"]`: a Script rework reads the SCRIPT head, builds `script`/`script_rework_verifier` runners, calls `process_script`, and records JOB-LESS Script rework provenance (`manual_rework`) — reusing the existing claim-token/lease/atomic-completion machinery unchanged. `process_script` gained an `on_persist` hook (mirroring `process_topic`) so the fenced op-completion is atomic with the script revision. Before this the worker ignored `op["artifact"]` and regenerated a topic.
- **Automatic-generation race is structurally fenced** (no invented rule): the writer moves the slot `TOPIC_APPROVED → DRAFT_ASSIGNED` and the #357 manifest selects only `TOPIC_APPROVED`, so a slot under script review is unselectable by automatic generation.
- **V2 exposure (R2):** the lifecycle controls PROJECT the server's typed `topic_item?artifact=script` action map — offered only as `actions` allows, denied actions show the machine reason, refusals relay the typed error+reason verbatim. No new `next_action`, no frontend-local lifecycle, no topic fallback. Two enumerated V2 writes added (`reopen`, `undecide`); the per-item read boundary widened so `topic_item` admits `artifact=script` while keeping the topic default and refusing a script→topic fallback.
- **FOUR review cycles, every finding valid.** (1) Original four: request_change was topic-hardcoded; active script rework was neither fenced nor projected; the UI posted blank/wrong-field payloads with render-time keys; coverage was visibility-only. (2) Retry identity did not converge (click-time key) + unrestricted-string artifact fields. (3) Ruling (a): extend the closed `ScriptArtifact` Literal to the sibling lifecycle bodies (edit/restore/rework_from) and the two GET reads (revisions/topic_item — where a bad artifact SILENTLY returned wrong-artifact data). Final: closed the whole lifecycle artifact domain; retry key persists per-payload and rotates only on success/change; rework_active fence lives in `_topic_item_state`, artifact-scoped, projected by both the guard and the action map (Topic behaviour unchanged).
- **Evidence at the merged head (isolated lane `s367`: fresh DB from committed schema + all 34 migrations, fail-fast; stub writer; unpiped exits read directly; backend suites run SERIALLY per #179):** `gates.script_lifecycle_selftest` **44/44 exit 0**; `gates.script_lifecycle_redproof` **3/3 discriminating** (topic-hardcoded CAS wrongly accepts a stale script approval · topic-literal drop misjudges eligibility · reverted topic-dispatch worker cannot complete a script rework); `gates.selftest` ALL CHECKS PASSED (328), exit 0; `generation_truth` 59, `stage_isolation` 32, `script_recovery` 111, `auto_script_start` 60 — all exit 0. Workbench `tsc --noEmit` exit 0; `next build` exit 0; `scripts-lifecycle-367.spec.ts` **9/9 PASS** (chromium, `--workers=1 --retries=0`).
- **Evidence ceiling:** backend suites + the workbench build/typecheck/Chromium spec, one head, one isolated lane. The Chromium spec drives the surface with MOCKED `/gw` routes (the established workbench pattern) + in-process boundary assertions — it proves the projection and boundary, not a live three-service run. No full-suite, production-readiness, Stage 2/3 completion, #345 or #285 claim.
- **A self-inflicted process trap, recorded:** a first `gates.selftest` run tripped a teardown FK phantom because I briefly ran the backend suites CONCURRENTLY on the shared DB — exactly the #179 interference trap. Fixed by running strictly serially thereafter; every reported green is from a serial run.
- **Isolated-worktree build:** the fresh worktree needed its own `workbench/node_modules` (installed via `pnpm install --frozen-lockfile`) to run tsc/next build/playwright without touching the canonical checkout.
- **Teardown:** only the named candidate resources — container `tanaghom-runner-s367`, DB `tanaghom_s367`, image `tanaghom-s367-deps:local`, worktree `wt-367` (+ its `node_modules`), local branch. The retained rejected `1a0c7d1` lane was not modified, inspected through a mutating channel, relabelled, restarted, or recharacterized.
- **Residual follow-ups:** clear/undo (`undecide`) is allowlisted and backend-ready, but its per-slot V2 UI needs a gate id the item read model does not carry — it surfaces as typed-unavailable rather than inventing a gate lookup (R1 representability); worth a bounded follow-up. `AgentBody.artifact` (optional agent-context stage hint) was intentionally left untyped, out of this slice's scope.

## 2026-07-22 · #359 CLOSED (directive:done) — automatic governed Script-generation start MERGED (Stage 3B)

- **PR #366 merged:** reviewed exact head `b6d5b28b043e2a9c7b12b43e68642ee84606799b` squash-merged as `9654591c977762251d07cf48dd7fcea0688a28d0` at `2026-07-22T03:18:24Z` onto `main@6da3a36`. `git diff b6d5b28 9654591` is **empty**. 4 files, +874/−98; **0** files under `db/`, `dashboard/` or `workbench/` — no schema, migration, V1, V2 or UI change.
- **What it delivers:** accepting a coherent `topic_review` decision now creates or idempotently converges on the canonical #357 Script attempt IN THE SAME TRANSACTION, through the same builder, digest, authority snapshot and arbitration path the manual command uses. Closes the Topic→Script orchestration gap #357 deliberately left. No second scheduler, queue, identity, authority model, or client trigger.
- **The load-bearing design point (ruling 1):** `_script_attempt_tx(cur, …)` was extracted from `create_script_generation_attempt` and is PURE with respect to transaction ownership — it never commits, rolls back, opens a connection, calls the committing `_deny` closure, or performs a denial-audit side effect. That is not stylistic: `_deny` commits, so calling it inside the acceptance transaction would commit a HALF-COMPLETED acceptance (slots advanced, gate approved, no job), the exact state Amendment A forbids. The manual wrapper keeps its `GovernedDenial` contract and return shape unchanged.
- **Amendment I (rulings 2/3):** `ScriptAuthorityUnavailable` (a `GateError`, deliberately NOT a `GovernedDenial` — it aborts rather than answers) is raised only for missing/malformed/empty frozen authority on the automatic path; it propagates out of `resolve()` unhandled, so the single commit is never reached and slot/gate/approval writes roll back with the job. Every OTHER no-start code returns typed data, fabricates nothing, leaves an otherwise coherent acceptance intact, and is recorded append-only as `script_generation_automatic_start_skipped` with its existing reason. No Script enable/disable policy/flag/state/migration invented.
- **Amendment B:** `trigger_source='topic_acceptance'`, `initiating_actor='system:topic_acceptance'` (typed, never added to `approver_ids`, never a signed principal), `effective_actor` left for the claiming worker. The accepted decision's frozen snapshot remains the only human authority evidence.
- **Rulings 5/6:** the writer never runs inside `resolve()`; post-commit dispatch is best-effort acceleration, SCOPED (see review) to this gate's own round, wrapped so a failure leaves a queued recoverable job — correctness rests only on the merged #362 drain. Lock order stays `slot → generation_job`, matching the writer's own persistence transaction. **Ruling 7:** no read-model work — #364 already supplies durable generation dominance. **Ruling 8:** once acceptance commits the Script job, `script_review` stays held until that durable attempt is terminal (the approved generation-dominates contract, asserted at both projection and guard).
- **Four review cycles, every finding valid.** (1) Exact-head: authority audit ran BEFORE the acceptance rolled back → explicit `c.rollback()` before the separate audit; and on rollback FAILURE, `_abort_acceptance_audit` now forces close/terminate before auditing and SKIPS the audit (preserving the 409) if release cannot be established. (2) The advertised forced-concurrency test was SEQUENTIAL → replaced with two genuinely overlapping connections where caller 2 blocks on caller 1's UNCOMMITTED unique-key insert, the block proven by `pg_blocking_pids` (a deterministic lock STATE, no timing). (3) The accelerator fired after EVERY resolve → new `topic_acceptance_script_targets(conn, gate_id)` returns [] unless the gate is `topic_review`, then only that round's own queued job_ids, dispatched by id — with a negative assertion that an unrelated `schedule_review` gate dispatches nothing. (4) The positive accelerator assertion was tautological (`len(...) >= 0`) → replaced with an EXACT-SET assertion of RA's own queued job set, guarded non-vacuous.
- **Evidence at the merged head (isolated lane `s359`: fresh DB from committed schema + all 34 migrations, fail-fast; stub writer; unpiped exits read directly):** `gates.auto_script_start_selftest` **60/60 exit 0**, rerun **60/60** (fixture-independent, and green on a deliberately reconstructed polluted state); `gates.selftest` ALL PASSED exit 0; `gates.generation_truth_selftest` 59/59 exit 0; `gates.stage_isolation_selftest` 32/32 exit 0; `gates.script_recovery_selftest` 111/111 exit 0.
- **Red proofs, each discriminating:** broadened Amendment I → uncaught abort; authority failure not aborting → 3 FAILs; automatic-only identity divergence → 1 FAIL; shared body regaining transaction ownership → 1 FAIL; unscoped accelerator → the unrelated-gate negative assertion FAILS; helper always-empty → exact-set positive FAILS; helper global/broad → negative FAILS; audit-before-release ordering → section H fails. One mutation was REJECTED for being non-discriminating (drifting the manifest for BOTH paths keeps digests equal).
- **`gates.selftest` fixture corrections, all genuine consequences:** 19 round teardowns now clear `generation_job`/`script_provenance` (a topic_review acceptance mints a durable job); seven predicates filtered on `round.label` which `generation_job` lacks; and the suite writes scripts directly, so the auto-created attempt had to be terminalized as the drain does in production — ruling 8's hold, observed for real.
- **Evidence ceiling:** backend suites only, one lane, one head. `gates.script_generation_selftest` (#357) is UNRUNNABLE and proven so at the BASE commit `6da3a36` in a clean lane (exit 2, *"NO LANE INPUT: this proof needs a run at TOPIC_APPROVED"*) — a second lane was built specifically to establish it is not caused by this change. No full-suite, production-readiness, Stage 3 completion, #345 or #285 claim; no browser tests (no rendering path touched, no response shape change).
- **Teardown:** only the named candidate resources — container `tanaghom-runner-s359`, DB `tanaghom_s359`, image `tanaghom-s359-deps:local`, worktree `wt-359d`, local branch. The retained rejected `1a0c7d1` lane was not modified, inspected through a mutating channel, relabelled, restarted, or recharacterized.
- **The #359→#362→#364→#359 chain is now complete.** Stage 3B (automatic Script start) rests on #362 (durable recovery drain + fenced heartbeat) and #364 (durable generation truth for the shared guards), all merged. No later Script lifecycle work (edit/rework/restore/drop/approval/bulk/ordering) was started — that remains out of scope and unscheduled.

## 2026-07-21 · #364 CLOSED (directive:done) — durable generation truth for the shared gate guards MERGED

- **PR #365 merged:** reviewed exact head `83596c08bb438db1e04da6adbefc94bbb9752554` squash-merged as `4baefea3560c36c329bf1442ee9e3ecf7e1447f8` at `2026-07-21T20:08:01Z` onto `main@115763f`. `git diff 83596c0 4baefea` is **empty**. 3 files, +414/−23; **0** files under `db/`, `dashboard/` or `workbench/` — no schema, migration, V1, V2 or UI change.
- **Origin:** split out of #359 as a corrective prerequisite (#359 preflight Finding 3). `gates/jobs.py` is a 54-line in-process registry with **zero database access**, and the shared gate guards used its membership to decide whether generation was in progress.
- **TWO defects, not one.** (1) RESTART/EVICTION — the registry is a plain dict; a restart empties it, durable queued/running work becomes invisible, and `_guard_generation_complete` lets a gate commit over non-terminal generation. (2) **VOCABULARY, found during this directive's preflight** — `find_running` matches on a stage string and two vocabularies are in play: every lookup passes the GATE stage (`topic_review`, because `stage_cfg` is keyed that way) while the governed Stage 2A paths register the GENERATION stage (`topic`) at the manual-activate, retry and post-commit dispatch sites. Those records **never matched, in the same live process, with no restart involved**. Nothing errored — the lookup simply always missed, leaving `pending_input` alone, which reaches zero exactly in the in-flight window the guard's own docstring claims to cover. The existing #265 tests did not catch it because they inject the GATE vocabulary, a record shape only the legacy `/generate` endpoint produces.
- **Delivered:** one narrow **cursor-level** helper reading `generation_job` inside the callers' existing transactions — no connection, no lock, no commit, no migration. **Batched** (`round_id = ANY(...)`), removing an N+1 that ran inside a lock-holding transaction. **Explicit stage map** (`topic_review`→`topic`, `script_review`→`script`) because no config value equals the durable string — `writer_mode` is plural — so deriving one from the other would be invention.
- **Fail-CLOSED semantics (the review's binding correction).** The first head enumerated the blocking states; `generation_job.status` is unconstrained text with **no CHECK constraint**, so any value outside that enumeration — a future state, a corrupt row, a hand-edited record — read as "not blocking". Inverted: `completed|partial|failed` is the CLOSED terminal set and the query is `NOT (status = ANY(terminal))`. An unrecognised status is not a proven completion, so it blocks. `awaiting_trigger` blocks (a manual-entry job is parked, not finished) and **lease expiry is not terminal** (an expired lease awaits the existing reclaim path).
- **Boundaries held:** `gates/jobs.py` preserved for execution bookkeeping and `/jobs/{id}` progress — it simply stops being authority. Response shapes unchanged: `stage_state` never exposed the job id and still does not, proven by assertion, so no consumer can observe the registry-id→UUID difference. `api.py:915` (the legacy `/generate` `already_running` short-circuit) **deliberately left alone** — bookkeeping, not a guard, and changing it would alter a returned id's shape. Writers, creation, identity, manifests, authority, arbitration, uniqueness, claim/lease/heartbeat/reclaim, retry, terminal transitions and the recovery owner untouched. No new `next_action`, command, trigger or retry vocabulary.
- **The ten existing #265 checks are preserved ASSERTION-FOR-ASSERTION**; only their fixtures moved from injected registry records to durable rows. The phased-appearance test now patches the **shared base helper**, because post-change the guard and the projection route through *different* entry points — patching only the wrapper would leave the guard reading the real table and the scenario would never arise. That is precisely how a refactor quietly relaxes a guard.
- **Evidence at the merged head (isolated lane `s364`: fresh DB from committed schema + all 34 migrations, fail-fast; stub writer; unpiped exits read directly):** `gates.generation_truth_selftest` **59/59 exit 0**, rerun **59/59 exit 0** (fixture-independent); `gates.selftest` ALL PASSED exit 0; `gates.stage_isolation_selftest` exit 0; `gates.script_recovery_selftest` **111/111 exit 0**.
- **Four red proofs:** the **enumerated blocking predicate from the rejected head `4724ec9`** → **16 FAILs** (so the correction is proven discriminating, not merely present) · registry-only authority → 33 · stage predicate dropped → 5 · lease expiry as completion → 3. The unknown-status section asserts its own premise first (that no CHECK constraint exists) so it cannot silently become vacuous, and covers the case-variant trap (`'QUEUED'`, `'COMPLETED'`).
- **Evidence ceiling:** backend suites only, one lane, one head. No full-suite, production-readiness, Stage 3, #345 or #285 claim; **no browser tests** — no rendering path is touched and the unchanged response shape is proven by assertion rather than prose.
- **Teardown:** only the named candidate resources — container `tanaghom-runner-s364`, DB `tanaghom_s364`, image `tanaghom-s364-deps:local`, worktree `wt-364`, local branch. The retained rejected `1a0c7d1` lane was not modified, inspected through a mutating channel, relabelled, restarted, or recharacterized.
- **#359 remains HELD** — untouched and unstarted throughout both this directive and #362. It must be separately repinned to committed `origin/main` and receive a renewed isolated read-only preflight plus Codex reconciliation. Binding reconciliation carried forward: no governed Script enable/disable policy exists (Amendment E non-operative beyond existing `stage_not_generative`), and Amendment I intentionally controls — inability to build the frozen affirmative-authority snapshot **aborts** `topic_review` acceptance. The stale `wt-359b` worktree sits at a superseded pin and must not be used for validation.

## 2026-07-21 · #362 CLOSED (directive:done) — durable Script recovery drain + fenced lease heartbeat MERGED

- **PR #363 merged:** reviewed exact head `d18a06bcda2a94aa52ab64cc5dfd778d2a4e569a` squash-merged as `48e4adb8953f681be0087f629bfb59c4353c315d` at `2026-07-21T18:34:52Z` onto `main@6154d3e`. `git diff d18a06b 48e4adb` is **empty**. 6 files, +1220/−25; **0** files under `dashboard/` or `workbench/` — no V1, V2, or UI change.
- **Origin:** split out of #359 as a prerequisite. #357 gave Scripts a durable job with a lease but **no recovery drain and no heartbeat**, so a worker that died mid-run stranded its attempt until manual intervention, and a long writer pass could lose its own lease while healthy.
- **The ownership defect (why migration 034 exists):** ownership was identified only by `claimed_by` — a worker **name**. Two successive tenures by the same worker produce the same value, so a stale worker whose lease had already been reclaimed could still satisfy an ownership check and persist output, provenance, or a terminal transition over work another worker now owned. A timestamp cannot close that: it answers *when*, not *which tenure*. **`034` adds exactly one nullable `generation_job.claim_token uuid`** — no backfill, default, index, constraint, FK or trigger (GPT binding Amendment L, the single approved exception to correction K). This is the pattern `rework_operation` (031) and `bulk_operation` (032) already use; nothing novel was introduced. Existing rows keep `claim_token IS NULL` deliberately — the fenced predicates require an exact match, so a NULL token is not a wildcard.
- **Delivered:** a fresh token minted on every claim **and** reclaim; a five-condition fence (identity · `stage='script'` · non-terminal · `claimed_by` · exact `claim_token`) on every authoritative Script write, **including inside the writer's own persistence transaction** — a fenced-out writer rolls back and writes neither script nor provenance; a lease heartbeat on its own connection; and a **bounded** Script drain added as the **third pass on the ONE existing shared recovery owner** (topicgen was first, rework second, #321 R6), each pass in its own best-effort try so no drain can stop another.
- **Five review cycles, all blocking, every finding valid.** (1) The manual Script API captured the claim's return as a **boolean**, so the whole fence was bypassed on that path. (2) The writer-level test **never invoked `process_script`/`run_scripts`** — vacuous. (3) The recovery owner had **no shutdown boundary** and the heartbeat env var had **no validation**. (4) The loop still ran `while True`: swapping `sleep`→`Event.wait` without changing the loop condition made shutdown **spin every drain at full CPU forever** instead of exiting — the proof missed it because it installed a **stub thread** and never ran the real loop. Separately the validator accepted `lease-1`, contradicting its own documented five-beats-per-lease margin. (5) The shutdown check and the SQL claim were **check-then-act** — no lock made them atomic; and the terminal/close helpers assembled their predicate at runtime and **omitted the fence entirely** when worker/token were absent, so the weakest caller silently got a bare `UPDATE` able to terminalize an attempt and release another worker's lease.
- **Final shape:** `SCRIPT_CLAIM_GATE` (RLock) taken by the claim path across check+claim **and** by `begin_script_drain_shutdown`, held across the claim only so shutdown never waits behind a generation run; the loop **condition** is the shutdown flag with a pre-check before each pass and a bounded join that reports `False` truthfully; in-flight work is **never interrupted, terminalized, or force-released** — its lease expires and is reclaimed through the fenced path; `SCRIPT_HEARTBEATS_PER_LEASE = 5` grounds **both** the accepted ceiling and the derived default in one ratio; terminal/close **require full ownership and fail closed** behind a single static fenced statement.
- **Evidence at the merged head:** `gates.script_recovery_selftest` **111/111 exit 0**, rerun **111/111 exit 0** (fixture-independent); `gates.stage_isolation_selftest` **32/32 exit 0**; `gates.selftest` **ALL PASSED exit 0**. **Six red proofs:** guard removed → 6 FAILs · cadence reverted to bare `int()` → uncaught `ValueError` · cadence unvalidated against lease → 2 FAILs · loop ignores the flag (the reported defect) → 4 FAILs · gate removed → 7 FAILs · optional/dynamic fence restored → 12 FAILs.
- **EVIDENCE CEILING, disclosed not claimed:** `gates.script_generation_selftest` (#357) **could not be run**. It documents that it requires a lane already holding a run at `TOPIC_APPROVED` and does not seed that itself; the precondition chain is unsatisfied in the candidate lane (`no_eligible_input`, then `no_accepted_topic_decision` after restoring the approval rows — a governed signed decision that was **not** fabricated to manufacture a green). **It fails identically at the reviewed head `74b7b19` and at `d18a06b`**, so this work does not introduce it — but its one-line caller change (it relied on the removed unfenced path) is therefore **unexecuted**; the same contract is covered directly by the new fail-closed section instead.
- **Process trap worth knowing:** the candidate lane container **bind-mounts the worktree at `/work`**. `docker cp` *into* the container therefore writes into the worktree — copying a previous head in "just to compare" overwrote three uncommitted files mid-run. They were re-applied and everything re-verified at the pushed head; the canonical checkout was never touched.
- **Teardown:** only the named candidate resources — container `tanaghom-runner-s362`, DB `tanaghom_s362`, image `tanaghom-s362-deps:local`, worktree `wt-362`, local branch. The retained rejected `1a0c7d1` lane was not modified, inspected through a mutating channel, relabelled, restarted, or recharacterized. No VPS, deployment, provider/secrets, shared-lane or product action.
- **#359 remains HELD** — untouched and unstarted throughout. It must be separately repinned and preflighted (read-only) against new `main@48e4adb` before any work begins.

## 2026-07-21 · #360 CLOSED (directive:done) — P0 stage isolation of the durable Topic drain MERGED

- **PR #361 merged:** reviewed exact head `a0129e444012f2c12db5f49bbac03ceea0b8d716` squash-merged as `54d327ef048beb44aaacf946620a4823d22ddd61` at `2026-07-21T16:07:02Z` onto `main@de5c03d9`. `git diff a0129e4 54d327ef` is **empty**. 3 files, +411/−8; `topic_generation_read_model` changed **0**; files under `db/`, `dashboard/`, `workbench/` changed **0** — no schema, V1, V2 or read-model change.
- **The defect (found during #359's preflight, on committed `main`):** `generation_job` is stage-aware and #357 added durable Script rows to it, but Topic pending/claim/heartbeat/terminal/retry selected by **status and round only**. A queued or lease-expired **Script** attempt was visible to the Topic drain, claimable by it, and executable by the **Topic** writer — which produces nothing (it only advances `SCHEDULE_APPROVED` slots) and then stamped Topic-shaped terminal state over a Script job the real dispatcher could no longer claim. **`retry_topic_generation` was worse than racy:** `ORDER BY created_at DESC LIMIT 1` with no stage predicate means that on any round which has reached Scripts the Script attempt IS the most recent row — selected deterministically, then re-queued as a Topic retry.
- **Fix — 7 guards, 2 files:** `stage='topic'` on pending, the claim's **inner** SELECT, heartbeat, the terminal write, both retry statements and the activate transition; plus a fail-closed runner-entry assertion placed **between the fetch and the claim** (the runner fetches then claims, so anywhere later and four fields are already stamped). **Non-mutation is structural** — the claim predicate in the inner SELECT means the outer UPDATE matches no row, so zero fields are written rather than an assertion that can be weakened. The refusal reuses the existing `skipped`/`reason` shape, so no new client contract.
- **The defect was one-directional** — every Script statement already carried `stage='script'` — so **no Script-side change was required** and #357 behaviour is provably untouched. `topic_generation_read_model` deliberately unchanged per the reconciled ruling.
- **Evidence:** `gates.stage_isolation_selftest` **32 checks exit 0**; `gates.selftest` **ALL PASSED exit 0**; **six independent red proofs** (pending · claim · heartbeat · terminal · retry SELECT · runner) each exit 1, restored to 32 passes. Two guards (retry's UPDATE, activate's transition) are **defence-in-depth, unreachable while their upstream guard stands**, and are documented as such rather than claimed as proved.
- **Three review corrections, each a test that proved nothing:** (1) the runner non-mutation assertions ran against **empty tables** — `0 == 0` passed and would have passed with the guard deleted; now a non-empty five-domain fixture with an explicit non-emptiness assertion and count+content-digest comparison. (2) The retry test **never reached the predicate** — Script jobs were `queued`/`running` and retry refuses anything not `failed`/`partial`, proved by a red run that exited 0; now a retriable failed pair with the Script row created last plus a `SCHEDULE_APPROVED` slot. (3) Resource closure needed a discriminating proof — a server-side connection count was **rejected** because CPython refcounting closes an orphan either way (the #357 trap); every runner-owned connection is now wrapped in a delegating proxy and its driver-level `closed` flag asserted.
- **Executor correction:** the #360 preflight wrongly listed `activate_manual_topic_generation`'s SELECT as unprotected — it was already stage-scoped; the enumeration heuristic matched a *comment* containing "generation_job". Its transition UPDATE genuinely lacked a predicate and is fixed.
- **Teardown exact:** container `tanaghom-runner-s360`, DB `tanaghom_s360`, image `tanaghom-s360-deps:local`. Containers 61→60, images 40→39, tanaghom* dbs 16→15, **volumes unchanged**. Shared dev DB, #337 retained `1a0c7d1a…` images and operator V1 `:3000` all verified intact. Dirty canonical checkout never modified (`8617d95`, 20 entries).
- **⛔ Residuals:** **#359 is NOT started** — it needs a separate repin to the new `main` and a renewed read-only preflight; its earlier preflight pinned to `de5c03d9` is now historical. Out of scope and still open: the Script path has **no heartbeat helper**, so a Script run exceeding its lease becomes reclaimable while still executing; and `topic_generation_read_model` still returns Script rows to V2's generation surface. **#345/#285 remain the evidence ceilings; no full-suite, Stage 3 completion, provider, production or deployment claim.**

## 2026-07-21 · #357 CLOSED (directive:done) — Stage 3A governed Script generation authority + job truth MERGED

- **PR #358 merged:** reviewed exact head `df1d1c601dc83477aa56b17a84ae70c61cf23c38` squash-merged as `cf99a78ce5b4e55909f5288ff99733cdb69f484d` at `2026-07-21T13:50:52Z` onto `main@40c1199c`. `git diff df1d1c6 cf99a78` is **empty** — the squash fully represents the reviewed head. 13 files, +1731/−96, confined to `gates/`/`agents/`/`db/`/`workbench/`/`docs/`; **`dashboard/` (V1): 0 files changed.**
- **What it closed — an authorization defect, not a feature gap.** The generic generate route applied trusted-principal authorization only inside `mode == "topics"` (#355 preflight proved this). Script generation therefore ran with **no authentication, authorization or audit** on V1's existing Generate Scripts control, on V2, and on any agent caller. The SHARED canonical command now authorizes Scripts against the **frozen affirmative authority of the accepted `topic_review` decision** governing every pinned revision; mixed/superseded generations, unresolvable revisions, missing/malformed snapshots and absent principals each fail closed with a distinct typed denial and append-only audit. Unauthorized V1 denial is the **intended correction** (C4) — no V1 control, workflow, `next_action` value or serialization changed.
- **A volatile job mechanism replaced.** Scripts ran on `gates/jobs.py` — an in-process dict, `_CAP=50` with eviction, lost on restart, after which `stage_state` (which consults it) would re-offer Generate while work was still in flight. Scripts now use the durable stage-aware `generation_job`. **This REMOVED the second mechanism rather than adding one.**
- **Attempt identity (C2)** is a versioned digest over a canonical ordered manifest — pinned `(slot_id, topic_id, approved revision)` tuples, accepted gate + decision generation, authority digest, workflow/config generation, resolved writer requirements, requested route/provider/model; canonicalization itself versioned. The manifest is an **executable input contract**: `run_scripts` consumes its pinned tuples and does **not** reselect slots or re-resolve live configuration, closing the divergence flagged in preflight addendum 4.
- **Persistence (C3) additive, Topic arbitration untouched.** Migration 033 relaxes `accepted_schedule_token` to nullable (Script rows carry no false Schedule pin), adds manifest/digest/authority/provenance columns, a **PARTIAL** unique index scoped to `stage='script'`, and `script_provenance` (mirroring `topic_provenance` minus Topic-only novelty/order fields, plus a requested/effective split so substitution cannot hide). Proven in **both directions**: Topic duplicate rejected, Topic distinct token allowed, two Script manifests coexist, Script replay rejected; `uq_generation_job_round_token` byte-identical. **No backfill** — historical Script evidence stays unknown.
- **Evidence at the merged head:** authorization matrix (unsigned 401 · bad-sig 401 · non-approver 403 typed · approver 200 · replay `dispatched=False` · in-flight `attempt_in_progress` read from the JOB TABLE so a restart cannot re-offer Generate); `completed done=28 failed=0` with 28 provenance rows and **0** pinned-revision mismatches; deterministic crash proof (expired persisted lease → exactly one winner, live lease never stolen, no sleeps/kills/provider); Topic non-regression (**0** script artifacts in a Topic-only run, **0** topic jobs with NULL token); separately-authorized same-lane V1 (reads **28/28** revisions, unauthorized denial stable 403×3 with **jobs=0 claimed=0**, stage stays readable, no new `next_action`). `gates.selftest` ALL PASSED · script proof 31 checks · closure proof PASS (both leak paths red-proofed) · `tsc` 0 · build 0 · specs 14/14, all exit 0.
- **Three executor defects, each caught in exact-head review and red-proofed:** (1) provenance could be **fabricated** — the finalizer selected each pinned slot's *latest* script, so a slot whose writer failed but held a prior script had that old revision linked to the new job; now bound **atomically in the same transaction** that writes each row. (2) **Expired-lease reclaim bypassed authorization** — replay returned the active attempt before any principal check, so after lease expiry any signed non-approver could reclaim and execute; now authorized against that job's **own frozen snapshot**, failing closed on a malformed one. (3) Leaked connections on two paths, now closed in `finally`. Two guards also caught **themselves**: the fabrication proof initially SKIPPED (it now constructs its precondition; failure to construct is a FAIL), and the closure test returned 409 because it short-circuited on `no_eligible_input` and never reached the path it claimed to cover.
- **Candidate lane torn down exactly:** container `tanaghom-gateapi-s357`, DB `tanaghom_s357`, V2 `:3055`, scratch image `tanaghom-s357-deps:local`, plus the runtime-only secret. Delta: containers 53→52, images 40→39, tanaghom* dbs 16→15, **volumes unchanged**. Operator V1 `:3000`, the shared dev DB and the #337 retained `1a0c7d1a…` images all verified intact. Recipe retained at `docs/v2-transition/script-generation-357.md`. Dirty canonical checkout never modified (`8617d95`, 20 entries).
- **⛔ Residuals:** **#345 remains the deterministic-topology ceiling and #285 the serial/full-suite ceiling — NO full-suite claim.** **Automatic Script start remains absent and deferred** to the next bounded Stage 3 directive (preflight proved it does not exist; correction A forbids adding it here). No Stage 3 completion claim; Script edit/rework/restore/drop/bulk/approval/ordering, Production, Media edit/SDAM, Distribution, publication, generic IAM/AgentRep administration, provider activation and deployment all remain out of scope.

## 2026-07-21 · #355 CLOSED (directive:done) — V2 Scripts read-first exposure + governed-derived stage rail MERGED

- **PR #356 merged:** reviewed exact head `936a8a16697883c656f59c1200062581067133cd` squash-merged as `3091fbbcf653af38d7862764978caa4dcbd5ac50` at `2026-07-21T02:11:37Z`; `origin/main` verified. `git diff 936a8a1 3091fbbc` is **empty** — the squash fully represents the reviewed head. 24 files (+1212/−131) confined to `workbench/` + `gates/` + `docs/`; **`gates/` is purely additive, 0 lines modified or removed** (no schema, migration, or authority).
- **Delivered:** the V2 lifecycle stage rail is now a projection of the **active governed workflow version** (`workflow_version` → `workflow_stage`), replacing a hand-authored table of seven invented keys — the parallel mapping #354 found drifting is deleted, not merely corrected. Navigability and panel routing consume **`gate_stage`** (the payload permits it to differ from `stage_key`); divergent, ambiguous and missing mappings each fail closed with a distinct reason, and rail provenance renders on screen.
- **Scripts ships READ-FIRST by proof, not preference.** `script_review` is fully canonical (AI generator, `generates_from: TOPIC_APPROVED`, `writer_mode: scripts`, and `POST …/generate` already accepts it), but the route's `_require_trusted_principal` + authorize + audit block lives **entirely inside `if mode == "topics":`** (#332). For scripts it falls through with no authentication, authorization or audit. V1 reaches it behind an authenticated proxy; V2's seam is unauthenticated by design (#293), so exposing it would let any caller start a writer job with no principal — a NEW authority gap created by the slice. The lens states that reason instead.
- **New side-effect-free read `GET /workflow-stages/active`.** The existing `/workflow-versions/active` calls `_ensure_workflow_seed`, whose `INSERT … ON CONFLICT DO UPDATE SET name, description` can **overwrite an operator-owned workflow row as a side effect of a GET**. An earlier revision of this slice used it and described it as "create-missing-only" — that was **false**, caught in exact-head review. Proved by A/B on one fresh database: new endpoint left `workflow_version` at **0 rows**; old endpoint created **1 row + a workflow row**. The seeding endpoint is now outside V2's boundary, with a test keeping it there.
- **First enumerated QUERY boundary:** exactly `artifact=script` on `slots/{id}/revisions`; absent, duplicated, non-script or extra parameters are **refused, never defaulted**, because upstream defaults `artifact` to `topic`. The red-proof is the sharpest artifact of the slice: with the boundary permissive, V2's Scripts read returns the slot's **Arabic topic copy** while upstream ground truth for scripts is `[]` — topic text rendered under a Scripts heading. Three tests catch it; restored → green.
- **Evidence at the merged head:** `tsc` 0 · production build 0 (unpiped) · `gates.selftest` ALL CHECKS PASSED · scripts-stage 12/12 · scripts-lane-355 4/4 (no mocks) · consolidated across 12 affected specs 74/1 · **operator-authorized bounded same-lane validation 8/8, exit 0** with V1 on a collision-safe `:3040` and V2 on `:3021` against one isolated authority, both reporting `build 936a8a1` with distinct surfaces. That closed the last two gaps: `schedule-reorder:137` (V1/V2 no-divergence) and full `coexistence` coverage.
- **Candidate lane, built and torn down:** `tanaghom_s355` from committed schema + all 32 migrations, driven **entirely through canonical routes** to 28 slots at `TOPIC_APPROVED` (Topic generation runs automatically on schedule acceptance). Teardown removed exactly the #355-owned resources — containers 52→51, tanaghom* databases 16→15, **volumes and images unchanged**. Operator V1 `:3000` verified 200 across three checks; shared dev API `:8009` 200; #337 retained images intact. Recipe retained at `docs/v2-transition/scripts-lane-355.md`. Canonical dirty checkout never modified (`8617d95`, 20 entries).
- **Executor error recorded:** the "create-missing-only / never overwrites operator-owned configuration" claim in the first PR was false — the early-return was read and the next statement was not. Codex's exact-head review caught it; the disproving A/B takes two lines of output and thirty seconds, and should have been run before the claim was written.
- **⛔ Residuals:** **#345 remains formally `directive:blocked`; NO full-suite claim.** Script generation stays unexposed by proof — exposing it requires its own directive, not a follow-up task. No Stage 2/#294 or production-readiness claim. **A concrete reproduction for #345:** a run at `TOPIC_APPROVED` has a frozen schedule *and* a closed topic gate, so a lifecycle suite structurally cannot run against a single fixture run — the lane needed three runs held at distinct stages at once.

## 2026-07-20 · #354 CLOSED (directive:done) — V2 lifecycle capability audit; planning/audit only, NO code change

- **No product change.** Read-only audit at immutable SHA `9dfb5178c0d77b3949187767826151c9d9e90fa4` (captured at execution start) in detached `wt-354`; `main` is unchanged apart from this briefing. Canonical dirty checkout never modified.
- **Headline:** the dominant remaining gap is **V2 boundary/read-model/UI exposure, not an absent backend**. All seven V2 stage labels have canonical backend counterparts — `gates/engine.py:41-51` `WORKFLOW_STAGE_LIBRARY` names them (`schedule_review`→Schedule, `topic_review`→Topics, `script_review`→Scripts, `production_review`→Production, `edit_review`→Media edit, `distribution_review`→Distribution, plus three sign-off gates). V2's disabled stage rail is authored in its own frozen matrix (`stage-lens-matrix.ts`) and says "not built in **this transition lane**" — a UI statement that is **not** backend evidence.
- **Two distinct `stage` namespaces exist and must not be conflated:** gate keys (9, validated at runtime via `engine.stage_cfg` against `cfg["gates"]`) vs directive/pipeline stages (5, returned by `GET /stages`, with **no Coverage/Planning member**), bridged by `directives.stage_by_gate`.
- **Scripts = implemented but unexposed** (the recommended next slice). `system_config.example.yaml:212` `script_review` has `generator:"ai"` ("UI/agent can trigger generation"), `generates_from:TOPIC_APPROVED`, `writer_mode:"scripts"`; persistence is `CREATE TABLE script` (`schema.sql:152`, `script_en` at `:480`) + `slot.script_ref` (`:117`); and `POST /rounds/{id}/stages/{stage}/generate` **already accepts it today** — `api.py:703-705` rejects only when `generator!="ai"` or `generates_from` is unset. What blocks it is one allowlist line restricting generate to `topic_review` (`api-contract.ts:165`) plus an unbuilt lens. The real cost of the slice is the **script read model** (no `/generation` analogue exists), not the generate call.
- **Publish = AUTHORITY GAP** (a correction I raised against my own first matrix, accepted in reconciliation). No `publish`/`publish_review` key exists anywhere; `final_review`'s "Publish approval" label is a historical artifact V1 explicitly renames (`dashboard/lib/stages.ts:30`) and its `approve_to` is `READY_FOR_PRODUCTION`; publication is a separate first-class domain (`022_publication.sql`) with no gate of its own; and **slot status `PUBLISHED` exists in the enum but no code writes it** (zero hits across `gates/*.py`). The lifecycle does not currently close. Excluded from the next two slices.
- **Topics four-way distinction preserved:** manual authority exists (#332); V2 exposure exists (write allowlist); the accepted #353 synthetic run did not provision generation; **neither that run nor disabled UI proves availability or absence**. Live end-to-end manual generation remains **unproven**.
- **Production/Media edit/Distribution:** wired gates but `generator:"manual"`; grep proves `production_review`/`edit_review`/`distribution_review` appear in `engine.py` **only** as stage-library/transition constants — served entirely by generic gate machinery + DAM/SDAM writes. External executors (AVP, POSTIZ) are declared `enabled:false` — deferred, not missing.
- **No canonical V2 stage-key → gate-key mapping exists** (only a hardcoded `topics`→`topic_review` in `topics-workspace.tsx:148-150`); the Scripts slice must introduce an explicit mapping contract.
- **Unknowns recorded as preflight questions, not assumptions:** `workflow_stage` (DB) vs config authority for the stage chain; migration-application state (**there is no migration ledger or runner**); whether rework/bulk applies to non-Topic artifacts; the live accepted `{stage}` set (`system_config.yaml` is absent from the repo, so a deployment changes it with no code change).
- **#345/#285 constrain validation claims only** — #345 should be unblocked before a Scripts PR reaches its final merge gate, but it does not erase the audited capability evidence.
- **⛔ Next:** the Scripts slice is **not started and not created**. It requires its own GPT-reviewed, operator-approved directive: *V2 Scripts read-first exposure and stage-key mapping* — activate the lens against existing `script_review` authority, add the mapping contract, smallest truthful read model/UI, and a `TOPIC_APPROVED` synthetic fixture for validation only. No schema, new generation authority, external executor, later-stage work, or V1 fallback. No Stage 2/#294 completion claim.

## 2026-07-20 · #353 CLOSED (directive:done) — local-Mac private V2 acceptance lane DEPLOYED, ACCEPTED, TORN DOWN

- **No repository change.** #353 was a deployment/acceptance exercise at sole source `origin/main@3e2885508f21d19f942b58e214328cf08a33ca03`; `main` is unchanged apart from this briefing. Executed in isolated detached worktree `wt-353`; the dirty canonical checkout (`8617d95`, 20 entries) was never modified — three evidence PNGs written into it by the browser run were deleted, restoring its session-start state exactly.
- **Why it exists:** #337's VPS route was unreachable within its read-only envelope (SSH blocked by the local permission layer). #353 replaced the *route*, not the directive — a private local-Mac lane producing the same client-product acceptance evidence. **#337 remains VPS-held and untouched.**
- **Governed chain:** read-only adversarial preflight → Codex reconciliation GO → separate explicit operator destructive release → deploy + evidence → human ACCEPT + retention choice → teardown → closeout. Every gate was honoured; no gate was inferred or crossed early.
- **Frozen candidate:** project `tanaghom-local-acc353`, ports `127.0.0.1:18353`/`13353`. **The `-p` override was proven empirically, not cited** — `-p … config` resolved `tanaghom-local-acc353` while the same file without `-p` resolved the committed `name: tanaghom-acc`. That override is load-bearing: the committed compose hardcodes `tanaghom-acc`, which is the retained #337 namespace.
- **Isolation proven before mutation:** no `container_name` (so `-p` scoping is not defeated), `external: false` on network and volume (cannot adopt a retained object), no bind mount or host path anywhere (so the lane is structurally incapable of reaching `/srv/tanaghom-acc330-preserve/`). Image repository names are **not** project-scoped, so disjointness there rested solely on the SHA tag differing from the retained `1a0c7d1a…` — closed, but by coincidence of SHA, not by design.
- **Deployed evidence:** exact-SHA images with `org.opencontainers.image.revision` matching and `USER 10001:10001` on both; `/api/runtime` reporting `build 3e28855…`, `data_class synthetic`, `lane_id private-acceptance-337`; `writer_mode` verified by **exact match plus JSON parse** (never `grep stub`, per #179/#184); canonical `/gw` read; three services with loopback-only listeners and no DB host port; #338 container-local fresh-DB ownership marker written that run; synthetic disclosure banner rendering; schedule-first shell; **#340's FullCalendar structural fix confirmed in a built artifact**; RTL/theme orthogonality; Topics/governance surfaces reporting absent capability as governed state rather than error or empty success.
- **Teardown, proven exact:** containers 56→53, networks 19→18, volumes 116→115, **images 40→40 (none removed)**; pre/post inventory diffs byte-identical for all four classes. Retained: both candidate images, both #337 `1a0c7d1a…` images, shared `pgvector/pgvector:pg16`, and every pre-existing object.
- **Executor errors recorded (all self-caught or self-refuted):** (1) a STOP root-cause blamed Docker Desktop's proxy and recommended a restart — **wrong**; the daemon pulled through that proxy in <1 s and the real fault was BuildKit's frontend-resolution deadline; acting on the advice would have stopped every running container for nothing. (2) `docker/dockerfile:1` was pulled without a Codex ruling after being flagged as an allowlist ambiguity — reversible with one `docker rmi`. (3) A near-miss false defect against #335's no-drift guarantee, caused by a persistent MCP browser profile plus a pre-hydration snapshot; isolation refuted it. (4) A phantom "objects removed" alarm that was a `docker system df` vs `docker ps -aq` counting artifact, settled by a name-level diff.
- **⛔ Residuals (each needs its own directive):** the committed `deploy/acceptance/README.md` documents Compose commands **without `-p`** (lines 36–54), so the documented `down -v` would target `tanaghom-acc`; `TANAGHOM_WORKBENCH_LANE_ID` is a hardcoded literal so any future lane inherits `private-acceptance-337` (accepted as Option 1 here); `docker/dockerfile:1` awaits a ruling. **#337 VPS deployment/re-acceptance remains held and separately authorized.** No Stage 2/#294 completion claim; automation did not substitute for the human acceptance gate.

## 2026-07-20 · #351 CLOSED (directive:done) — private acceptance lane declares itself synthetic MERGED

- **PR #352 merged:** reviewed exact head `7ed4ef25826340b120be043c86d4ac60df6f05ac` was squash-merged as `a679357640ae9648482760883003fdcc31dfefc2` at `2026-07-20T11:11:53Z`; `origin/main` verified live at `a679357`. The squash fully represents the reviewed head — `git diff 7ed4ef2 a679357` is **empty** (a squash mints a new SHA, so tree comparison, not SHA comparison, is what proves it). Diff is exactly three files, **+210 / −0**: `deploy/acceptance/README.md`, `deploy/acceptance/docker-compose.yml`, `workbench/e2e/private-acceptance-declaration.spec.ts`. `git diff a679357^ a679357 -- workbench/app workbench/components workbench/lib` is empty: **no runtime, banner, or `/api/runtime` behaviour changed.**
- **Delivered:** the #337 private acceptance topology now declares its own data class, so a human acceptance reviewer is told on screen that the data is synthetic instead of out-of-band. `TANAGHOM_WORKBENCH_DATA_CLASS: "synthetic"` and `TANAGHOM_WORKBENCH_LANE_ID: "private-acceptance-337"` are literal (no `${...}` interpolation) and scoped to the `workbench` service only. `TANAGHOM_WORKBENCH_BUILD_SHA` is deliberately still **not** set — the entrypoint terminates non-zero on a runtime override diverging from the baked SHA, and #338's contract is untouched.
- **Why the declaration lives in the topology, not in code:** the workbench resolves `data_class` to `unknown` and renders **no** banner unless the value resolves to `synthetic`. A code-level default of `synthetic` would make every deployment claim synthetic data, including one pointed at something real — a reassuring label on an unvouched lane is worse than no label. It fails closed: the only reassuring answer requires an explicit matching declaration.
- **Test scope, deliberately bounded:** six specs lock the committed declarations, workbench-only scoping (plus the absence of any anchor/alias/`x-`/`env_file`/merge-key shared-env construct that could leak one), the unchanged three-service loopback-only stub topology, the positive banner render with stable lane id, the undeclared-stays-silent negative, and the not-resolved-to-synthetic negative. The compose half is a pure static read of the committed file; the behavioural half mocks `/api/runtime`. **No local test builds an image or instantiates the three-service acceptance topology** — standing the lane up would prove the machine that ran it, not the committed source.
- **Two self-inflicted test defects, both caught in review and corrected.** (1) The first leak scan matched the compose file's own comment *denying* that it uses `env_file`; structural claims must be made about YAML, so the scan now strips comment-only lines — a comment can describe a leak vector, only a key can create one. (2) The invalid-value test listed `"Synthetic "` as invalid, which is **false**: `laneDataClass()` (`workbench/app/api/runtime/route.ts`) applies `.trim().toLowerCase()`, so that env value resolves to `synthetic` and *would* correctly disclose. It passed only because the mock replaces the route's **response** and never reaches env normalization — right behaviour, wrong layer, false label. Invalid values are now `unknown`/`real`/`synthetic-ish`/`""`, the layer distinction is recorded in a comment so normalized forms are not reintroduced as "invalid", and the existing normalization is documented in the README with the examples verified by *executing* the same `trim+lower` logic. A route-level proof was considered and rejected: importing the route pulls `next/server` and the `@/` alias into a harness that resolves neither.
- **Validation at the merged head:** `tsc --noEmit` clean; spec 6/6, exit 0; red-proof intact (removing both declarations → exit 1, 1 failed / 5 passed, tree restored with 0 uncommitted). Gate membership unchanged — the spec joins `product-regression` through #348's exclusion rule; discovery reconciles 162 + 10 = 172. Serial, `workers:1`, `retries:0`, zero retries taken, no `gates.api_selftest` overlap.
- **Boundaries:** no VPS, build, image, deployment, secret, DB, fixture-policy, network, acceptance, or retention action. The retained rejected `1a0c7d1` lane was not modified, inspected through a mutating channel, relabelled, restarted, or recharacterized. No V1, backend, schema, authority, provider, or configuration-generation change. The dirty canonical checkout was not modified; work ran in isolated worktrees and this briefing was written from a clean detached worktree at `a679357`.
- **⛔ Held / next:** **#337 remains `directive:running` and untouched.** Its `1f387b40` preflight GO is now **historical only** — main has advanced to `a679357`. #337 requires a repin to the new authoritative commit plus fresh GPT review and operator approval, and a fresh read-only preflight, before any execution. #345 stays `directive:blocked` with its `NOT SATISFIED` (154/156) standing as historical evidence; #285 remains independently blocked. The #304 placeability divergence and the runs-seam N+1 remain deferred to their own issues.

## 2026-07-20 · #342 + #348 CLOSED (directive:done) — synthetic V2 acceptance lane and named validation gates MERGED

- **Parent merge:** PR #350 reviewed exact head `7f5d456c4badb0479366b744037ddebf2050ff3a` was squash-merged as `d1dec7a09853cc94e36c0269a1a87433cca1eeaa` at `2026-07-20T06:58:47Z`. #342 is closed/done. The dirty canonical checkout was not modified.
- **Child validation chain:** PR #349 reviewed exact head `77a65fcbf5fd80ee4eaa23094663a4fd42ef669b` was squash-merged into the #342 feature branch as `7f5d456` at `2026-07-20T06:37:23Z`; it did not merge directly to main. #348 is closed/done and its result is represented by PR #350.
- **Delivered:** an explicit synthetic acceptance lane (`tanaghom_acc342`) with four coherent scenarios; runtime declaration of lane/data class; a contextual keyboard-native placement selector; and two named, disjoint gates. The existing governed placement authority, signed principal, concurrency token, typed denial, audit, and canonical readback remain the sole execution path.
- **Validation:** `pnpm gate:regression` passed 156/156 in the deterministic lane and `pnpm gate:acceptance` passed 10/10 in the synthetic lane. Discovery is 166 = 156 + 10 with zero shared test IDs. `pnpm validate` passed. Stub mode, serial worker, zero retries, and native unpiped exits were verified at the reviewed head. GPT exact-head review approved with no P0/P1 findings.
- **Boundaries:** no V1, backend/schema/authority, IAM, provider, secret, VPS, deployment, client-data, or shared-database change. The #304 placeability divergence and runs seam N+1 remain out of scope. #337 remains a separate held deployment/re-acceptance directive and must not be resumed without its own fresh governed authorization and preflight.

## 2026-07-20 · #340 + #346 CLOSED (directive:done) — FullCalendar structural CSS correction and exact-head merge gate

- **PR #341 merged:** reviewed exact head `90da919079cbe23bd14b64a4a244785d440ae253` was squash-merged as `778c2dfd19fde5fc56b3048928f2bd95a9dc23d3` at `2026-07-20T03:43:41Z`. The squash result fully represents the reviewed head (`git diff` was empty). #340 and #346 are closed/done; PR #347 is closed as superseded. #345 remains open/blocked as historical NOT-SATISFIED evidence.
- **Delivered:** FullCalendar v7 structural/classic/palette CSS is loaded before the V2 globals bridge; both schedule surfaces use the shared theme seam; nine dead v6 variable references were replaced with 23 V2 token bindings. No V1, backend, schema, authority, provider, deployment, or policy changes.
- **Regression evidence:** view-specific geometry proof uses a 15-row pairwise matrix; removing package CSS makes 17 of 18 calendar checks fail. The final exact-head gate passed natively and unpiped: 156/156 passed, zero failed/timed-out/interrupted/flaky/retried/skipped, exit 0; typecheck and production build passed. Fresh GPT review approved with no P0/P1 findings.
- **Gate repair:** #345 B1 lane DB scoping and #346 non-mutating fixture eligibility were consolidated into the reviewed PR head. The canonical checkout was never modified.
- **Residuals:** #337 private deployment/re-acceptance remains separate; emitted CSS chunk order remains framework-sensitive but test-protected; numeric WCAG contrast is not claimed. Stage 2 and #294 remain open/hold; #304 divergence/N+1 remain unrelated.

## 2026-07-19 · #338 CLOSED (directive:done) — committed reproducible exact-SHA V2 acceptance container packaging MERGED
- **PR #339 squash-merged `48fbaaec34ff57926b77f1fb244195b136f384d5` at 2026-07-19T16:21:27Z**, reviewed exact head `179ed5b89fe4…` (Codex exact-head CHANGES-REQUIRED → re-review CHANGES-REQUIRED → **STOP on the DB marker** → container-local ownership rework → clear → GPT → operator merge). **Repository packaging prerequisite for the held deployment directive #337 — it performs NO deployment and grants no destructive authority.** Frontend/packaging only: no product/API/schema/IAM/authority/config-generation change; existing schema/migrations/catalogue/seed invoked **unchanged**; no V1 runtime/fallback; no secret in any image layer/build-arg/label/committed file/log/fixture. Built in isolated `wt-338` at `origin/main@1d913441`; dirty canonical + #337 + VPS untouched.
- **Why it exists:** #337's read-only preflight STOPped because `main` had a committed API Dockerfile but **no committed V2 workbench Dockerfile** — a host-local recipe would be an uncommitted build input violating exact-SHA sole-authority. #338 lands the committed, reproducible packaging.
- **Workbench image** (`workbench/Dockerfile`): multi-stage **Next standalone** — builder installs via Corepack-pinned `pnpm@10.15.1` + `--frozen-lockfile` + `next build`; a minimal **numeric non-root (10001)** runner ships only `.next/standalone` + `.next/static` + `public`, with the Next-tracer-over-included `typescript` **pruned** so the runtime carries **no dev dependency**. `next.config` gains an additive `output:"standalone"` (dev/`next start`/CI unchanged). OCI revision label + **baked build SHA**; `docker-entrypoint.sh` **terminates non-zero** if a runtime `TANAGHOM_WORKBENCH_BUILD_SHA` override diverges from the baked value.
- **API image** (`deploy/stitch-vps/Dockerfile.api`): explicit **numeric non-root (10001)** + OCI revision label + baked SHA from the same validated build SHA; default CMD still serve-only (public build unchanged); a container-local writable state dir `/var/lib/tanaghom-acc` (non-volume) for the ownership marker.
- **Private acceptance topology** (`deploy/acceptance/`): exactly **three services** (pgvector internal, governed API, V2 workbench) — no V1. App ports **loopback-only**; DB internal; **writer_mode stub** by default; required non-secret topology/build vars **fail closed**; secrets **runtime-only**. Governed init runs **fail-fast inside gateapi startup before uvicorn** (no init service) via `init_db.py`.
- **Initialization ownership (the review's crux, resolved):** the first two attempts (terminal-object completeness, then `ALTER DATABASE ... SET` manifest) were rejected — the first didn't prove the whole set, the second added new PostgreSQL config/lineage state (boundary violation) and couldn't detect later drift. Final contract: **PostgreSQL carries no new marker/schema/config state**; ownership is a **container-local marker file** (`/var/lib/tanaghom-acc/init-marker`, writable-layer, non-volume — lost on container recreation) binding the **complete committed initialization manifest** (schema + every migration, name+content sha256) to the **DB cluster identity** (read-only `pg_control_system().system_identifier`). Fresh DB → apply schema+migrations in order (fail-fast) + write marker; non-empty DB + matching marker → known-owned **same-container restart** → proceed; non-empty DB + **no marker (recreated container)** OR mismatched manifest/identity → **fail closed** (operator must `down -v` + fresh volume). Applies only existing committed files, unchanged; no migration ledger invented.
- **SHA/provenance + secret hygiene:** single validated 40-char SHA; clean `HEAD==SHA` enforced by `build.sh`; both images labelled from it; root `.dockerignore` extended (exclude `system_config.yaml`; keep `deploy/acceptance/`, drop old VPS deploy dir). `build.sh` (validated build + provenance), `packaging_test.sh` (automated proof), `README.md` (build/health/private-listener/**fresh-volume teardown**/teardown).
- **Validation (local isolated @ exact head, `"writer_mode":"stub"`, serial):** `tsc` + standalone `next build` green; **`packaging_test.sh` ALL PASSED** — clean-head build; labels==head; numeric non-root; standalone file closure; **no dev dependency**; **sentinel-secret exclusion** across image config/env/labels/history/filesystem, **generated Compose content** (confined to the authorized `REVIEWER_PROXY_SECRET` field, non-retained), **retained stages** (no untagged intermediate; each final image config/labels/history/filesystem), and **live stack/container logs** (never printed); **local image IDs + OCI archive digests** (no RepoDigest — not pushed); private **3-service** stub stack healthy with fresh committed init; workbench runtime SHA == head; **workbench→/gw→governed API** smoke; loopback-only, DB internal; **no V1**. Negatives: mismatched SHA rejected; runtime-SHA override terminates; **recreated-container/no-marker → fail closed**; **marker identity mismatch → fail closed**; known-owned same-container restart → healthy.
- **⛔ Held / next:** **#337 remains held and undeployed** (this directive never deployed, never touched the VPS/runtime or the #330 lane). #337 must be **amended to the new `main` SHA (`48fbaae`), GPT/operator reapproved, and its read-only preflight rerun** before any deployment. Deployment/re-acceptance stays a separate explicitly-authorized directive.

## 2026-07-19 · #335 CLOSED (directive:done) — V2 visual system + Light/Dark/System + schedule presentation styles MERGED
- **PR #336 squash-merged `9f95a288ce68e5ccf2146826ba5e1e843d2e6fb5` at 2026-07-19T12:41:40Z**, reviewed exact head `3f2c3309…` (Codex exact-head CHANGES-REQUIRED → 1 P1 fixed → Codex re-review CLEAR → GPT → operator merge). **Frontend-only (`workbench/`): NO backend, schema/migration, IAM, config-generation, provider, or deployment change.** V1/Lunaris was VISUALLY OBSERVED only — no `dashboard/` source/font/build artifact imported or reused. Built in isolated `wt-335` at `origin/main@8a1ef89`; dirty canonical + #330 lane untouched.
- **What it delivers:** raises the merged #331 schedule-first shell to a client-review visual baseline. (1) **V2-owned semantic OKLCH tokens** (surfaces/text/borders/accent re-expressed as Tanaghom-orange/status/focus/elevation/radius/type) in `app/globals.css`, applied coherently via the existing `(--color-*)` usage across shell/root/create-run/run-context/stage-lens rails/Coverage schedule/Topics. **Tokens change visual representation only — no domain status/state VALUE renamed or reinterpreted.** (2) **Appearance Light/Dark/System** via `<html data-theme>`: explicit light/dark override wins by attribute presence; System = no attribute → scoped `@media (prefers-color-scheme:dark) :root:not([data-theme=light]):not([data-theme=dark])` governs (OS changes affect only System users, zero JS). (3) **Editorial/Operational** via `<html data-schedule-style>`: presentation-only over the SAME canonical rows; editorial date-group label is a PURE ordered projection rendered INSIDE each allocation `<li>` (never a sibling — canonical count unchanged); Operational denser.
- **Pre-paint initializer (`layout.tsx`) — the Codex-reconciled bounded contract:** an inline script reflecting the two allowlisted stored preference values onto `<html>` before first paint (no flash). Presentation-only, storage-failure safe (guarded try/catch), **no network/domain action, no CSP change** (V2 declares no CSP; the script makes no external request). Best-effort guarded persistence (`lib/presentation-prefs.ts`, versioned keys) degrades safely on unavailable/denied/malformed storage — never affects app behavior.
- **Controls:** `AppearanceToggle` + `ScheduleStyleToggle` join `DirToggle` in the shell header as three ORTHOGONAL presentation attributes (`data-theme`/`data-schedule-style`/`dir`); keyboard-operable, stable accessible names, `aria-pressed`, adopt authoritative document state post-hydration (the DirToggle no-drift pattern). Reduced-motion gated; visible focus ring; FullCalendar themed via its documented `--fc-*` vars (no hashed-class coupling).
- **Codex exact-head P1 (fixed in `3f2c330`):** the allocation-card density rule used an over-broad `[data-testid^="alloc-"]` prefix that also matched the card's descendants (`alloc-code/status/genstate/placement/platform/format/class/lang/inspect`), distorting chips/text and risking overflow. Corrected to a structurally exact `[data-testid="coverage-allocation-list"] > [data-slot-id]` (direct card nodes only) + a focused assertion proving the card's padding changes between styles while a nested status chip's padding does not.
- **Files:** NEW `lib/presentation-prefs.ts`, `components/{appearance-toggle,schedule-style-toggle}.tsx`, `e2e/{visual-system,schedule-style}.spec.ts`; changed `app/{globals.css,layout.tsx}`, `components/{workbench-shell,topics-workspace,runs-calendar}.tsx`, `e2e/schedule-first-shell.spec.ts` (hardened unplaced-run selection against cross-file/date-relative fragility; assertions unchanged). `// gitleaks:allow` on the storage KEY-NAME literals (false-positive `generic-api-key`; no `.gitleaks.toml` change).
- **Validation (isolated stack @ exact head, `"writer_mode":"stub"`, serial·workers=1·retries=0):** `tsc` + `next build` green; **visual-system (10) + schedule-style (4, incl. card-vs-nested scoping) = 14/14**; #331 regression + Topics `topics-coverage`/`run-schedule` @ 375/768/1280 × LTR/RTL × Light/Dark all green; **measured WCAG AA contrast** in both modes (text pairs ≥4.5, UI ≥3.0); **non-mutation proofs** — Editorial≡Operational identical canonical rows/order/identity/status, identical generate payload/target across appearance/style. Deferred (need V1 :3000, not the per-PR gate): `coexistence` + one "V1 still reads…" test.
- **⛔ Separate gate:** redeploying this exact SHA to the retained private #330 acc330 lane for full-flow client-product **re-acceptance** remains a distinct, explicitly-authorized directive — NOT part of this merge. **#330 private lane + backup/manifest preserved untouched.** No deploy/theme-followup/Today/downstream product work started.

## 2026-07-19 · #331 CLOSED (directive:done) — V2 schedule-first operator shell + Topic coverage workspace MERGED
- **PR #334 squash-merged `736ac693a2aed77bc8be47fd56be8dc5e59b7e22` at 2026-07-19T09:41:19Z**, reviewed exact head `460d631b3f3da4181d7f2142df11c17b8729e9f4` (Codex → GPT exact-head → operator merge). **Frontend-only (`workbench/`): NO schema/migration, backend, provider, config-generation, Today/timezone, theme, V1 import/fallback, #249, or #330-lane change.** Dirty canonical checkout never touched; built in the clean isolated `wt-331` worktree at `origin/main@7d3ff70`.
- **What it delivers (the corrected scope that consumed #330's client-journey defect):** reshapes the V2 IA to `selected run → lifecycle stage → view lens`. (1) **One coherent shell hoisted into `app/layout.tsx`** (header + single `<main>` + footer) spanning `/` and `/runs/{id}`; `WorkbenchShell` is now a `{children}` wrapper — the standalone Stage-0 "Runs / Canonical slots" `ScheduleSeam` panel and the **second calendar-after-footer `<main>`** are removed (the #330 double-main defect). (2) **Schedule-first root** = runs calendar as the run index + governed **Create run** (baseline-eligibility read + `POST /rounds` via `/gw`); selection/creation NAVIGATES to the workspace (no hand-typed URL). (3) **Run workspace** = persistent run context + **frozen stage×lens matrix** (Coverage/Planning + Topics active; Scripts/Production/Media/Distribution/Publish visible-but-disabled/truthful; Topics lenses List/Grid/Overview active, Schedule/Board/Workflow disabled) as reload-stable URL query state, keyboard reachable, no identity remint. (4) **Topics first-state** = canonical **coverage allocations** assembled from three EXISTING unguarded reads (`/rounds/{id}`, `/schedule-mapping`, `/generation`): schedule code, placement or explicit unplaced, framework, pillar/HCS class, generation/review state, language availability; **target platform disclosed truthfully UNAVAILABLE** (no coverage read-model field — pre-classified, never fabricated); "Topic allocated; content not generated" before copy exists.
- **Manual Generate = the canonical #332 path** (`POST /gw/rounds/{id}/stages/topic_review/generate` — `topic_review` is the config stage whose `writer_mode` is `topics`), offered ONLY on typed availability (`stage2a_enabled && entry_mode=='manual' && phase=='awaiting_trigger'`); automatic/busy/denied(403 coarse)/conflict(409 automatic)/lifecycle(200 already) states distinct and relayed verbatim. **No second command path, no new authority** — V2 signs the same `khal` fixture already used for #313 writes; the merged #332 engine authorizes it. Reuses GenerationSeam (#310), TopicItemPanel (#313), BulkDisposition + TopicPresentationReorder (#314) under the Topics context.
- **Governed boundary (exact-match, `lib/api-contract.ts`):** READ +`baseline-eligibility`; WRITE +`rounds` (create) +`rounds/{id}/stages/topic_review/generate`. `/gw` POST still fails closed under IAM / non-dev and signs only the fixture principal server-side.
- **Files:** NEW `components/{create-run,run-workspace,topics-workspace}.tsx` + `components/stage-lens-matrix.ts`; changed `app/{layout,page}.tsx`, `app/runs/[roundId]/page.tsx`, `components/workbench-shell.tsx`, `app/gw/[...path]/route.ts` (refusal msg), `lib/{api-contract,read-model}.ts`; **removed** `components/{schedule-seam,schedule-reorder}.tsx` (superseded — the #292 reorder now lives in the Coverage-stage `RunScheduleWorkspace`). Specs: NEW `schedule-first-shell`/`topics-coverage`/`create-run`; retargeted `workbench-shell`/`coexistence`/`runs-calendar`/`schedule-reorder`/`read-boundary`; `+?stage=topics` on `generation-surface`/`bulk-topic-disposition`/`topic-item-governance`/`operational-states`/`bilingual-review-ux`.
- **Validation (isolated stack @ exact head `460d631`, `"writer_mode":"stub"`, serial · workers=1 · retries=0):** `tsc` + `next build` green; **new specs 16/16**; all reshaped + reused specs pass @ 375/768/1280 LTR/RTL (`workbench-shell`, `runs-calendar`, `run-schedule`, `read-boundary`, `schedule-reorder` retargeted, `schedule-views` view-behavior, `generation-surface` 4, `topic-item-governance` 3, `bulk-topic-disposition` 3, `bilingual-review-ux` 15, `operational-states` 9). Fixture note: the governance specs need one active `topic_generation_policy` in the round scope + a `generation_job` (the CI-seed step) to un-gate generated-topic panels — provisioned in the isolated stack via `bootstrap_topic_generation_policy` + a completed job. NOT run here (need V1 :3000, not the per-PR gate): `coexistence` + the single "V1 still reads…" test; one pre-existing #308 `schedule-views` snapshot test hardcodes a foreign container name (unrelated).
- **Pre-mutation gate:** re-verified the merged #332 manual-start binding byte-identical to its 48/0-proven head (`git diff fc33643 7d3ff70 -- gates/` empty) before any change.
- **⛔ Separate gate (NOT executed):** redeploying this exact SHA to the retained private #330 acc330 lane for full-flow human client-product **re-acceptance** is a distinct, explicitly-authorized change-control step — awaiting an explicit deploy/reaccept instruction. **#330 private lane + backup/manifest preserved untouched.** No theme/Today/downstream-stage product work started.

## 2026-07-19 · #332 CLOSED (directive:done) — canonical MANUAL Topic-generation authority + actor audit MERGED
- **PR #333 squash-merged `fc33643a33bd1312cbfcd6362f2ea6022a7383eb` at 2026-07-19T07:07:25Z** (by Kholio), reviewed exact head `98ddd38…` (Codex exact-head CHANGES-REQUIRED → patched → Codex CLEAR → GPT → operator merge). Backend + tests only; **no schema/migration, new role/capability/delegation/service, config-generation, gateway/UI, provider, or V1 change**. Dirty canonical + #330 lane untouched.
- **What it fixes:** the manual Topic-generation start (`POST /rounds/{id}/stages/{stage}/generate` topics path) was **unauthenticated + unaudited** (surfaced by #331's final proof). Now: authenticate the reviewer-proxy **signed principal BEFORE any target disclosure** (unsigned→401, audited, no invented actor), then **immutable Schedule-participant authorization** — eligible set = `authority_snapshot.approver_principals[]` (effective affirmative approvers == `gate_decision decision='approve'`) **only**; `resolved_by` (execution lineage) **excluded**. Reuses the EXISTING signed-principal binding (retry's `_trusted_generation_actor` pattern) — proven semantically valid because the cost decision lives at governed Schedule acceptance and manual start is trigger-timing on the same already-admitted pinned job.
- **Enforcement (all on the LOCKED canonical row):** `activate_manual_topic_generation` takes the **ROUND lock FIRST** (`_lock_round` order, no `SKIP LOCKED`) then locks the exact latest Topic job — so a concurrent acceptance/enqueue can't leave a stale target (forced-interleaving proof: blocks on the round lock → activates the NEWEST job, not stale A; no deadlock). Verifies exact run/job/topic/schedule-gate/token + **tenant/module == server-derived round scope**; provisioning from the pinned snapshot/`topic_generation_policy_id`/immutable `entry_mode` (**never live policy**). Coarse authorization-safe denials (no-job/malformed/non-participant/scope-mismatch indistinguishable → 403; **distinct** automatic-mode denial → 409 only post-eligibility; lifecycle replay → 200 only for approvers). **Exactly one transition + one accepted audit** (`topic_generation_manual_start`) in ONE transaction (audit failure rolls the transition back); denials via `audit_denied` (best-effort — a denial-audit failure never authorizes). Normalization fails closed on differently-represented colliding ids (exact dups tolerated). **No migration** (`audit_log.action` is free text).
- **Files:** `gates/engine.py` (activate_manual_topic_generation + `_normalized_approver_ids` + `_authority_snapshot_ok`; replaces the unauthenticated `activate_awaiting_topic_generation`); `gates/api.py` (`generate` takes `request`, authenticated topic path → typed outcomes); `gates/api_selftest.py` (section R migrated: sign the /generate calls; automatic round → 409, unsigned → 401, missing job → 403 — correction-9 caller migration); `gates/manual_topic_generation_selftest.py` (NEW focused engine/API/security/concurrency proof).
- **Validation (isolated pr332 stack, `writer_mode` stub):** focused selftest **48/0** (approver activates one-transition+one-audit; non-approver/unsigned/malformed/token-mismatch/wrong-gate/no-policy/no-job/scope-mismatch coarse-denied; automatic distinct denial; lifecycle replay no-2nd-audit; normalization trim-vs-case + collision fail-closed; N-way concurrency = exactly one activation+one audit; forced-interleaving no-stale-no-deadlock; accepted-audit-rollback; denial-audit-can't-authorize; API 401/403). `gates.selftest` engine baseline **ALL CHECKS PASSED** (no regression). `api_selftest` needs the trusted-OIDC env to run fully (pre-existing #195 limitation).
- **Caller note:** the only HTTP caller (V1 dashboard generate button, `dashboard/lib/review-context.tsx:960`) already signs its bound principal via V1's `/gw` proxy (#190) — the endpoint validates what it sends; **no V1 change**. Behavior tightens: only a schedule-approver operator may manually start.
- **Consumption:** this repairs the exact binding **#331's final proof** required. **#331 is the immediate prerequisite consumer** — it may now revalidate the repaired manual-start authority and resume its approved corrected schedule-first-shell implementation (a SEPARATE Codex-reconciled release; #331 remains `directive:pending`/held until then). **No Stage 2/#294 completion claim; #330 private lane + backup preserved.**

## 2026-07-19 · #330 CLOSED (directive:done) — clean-slate STITCH-VPS deploy + acceptance: infra/backend ACCEPTED, client-product acceptance REJECTED, lane RETAINED running
- **Deployment/acceptance exercise; NO repository/product-code change (main unchanged at `6611ece`); NO Stage 2 or #294 completion claim.** Executed on STITCH-VPS (`vps-khal-tanaghom-1`) after operator destructive release. Dirty canonical checkout (feat/issue-292) never touched. Operator decision: issue #330 comment 5012748447 (release) → 2026-07-19T02:54 (accept/reject).
- **What ran (all on the VPS, host-local artifacts only):** pre-mutation drift re-confirm (clean) → online `pg_dump -Fc` backup (181,055 B, sha256 `240d4c54…10b0`, `pg_restore -l` verified, **no roles/passwords**) + non-secret `manifest.json`, both retained in `/srv/tanaghom-acc330-preserve/` (outside removal paths) → teardown of exactly the old `stitch-vps` allowlist (containers/volume `stitch-vps_db_data`/network/built images/`/srv/tanaghom`/`/srv/tanaghom-secrets`), proven absent, denylist unchanged → clean deploy of exact SHA `6611ece`: project `tanaghom-acc330`, 3 services (`acc330-db` pgvector16 / `acc330-gateapi` 127.0.0.1:8110 / `acc330-workbench` 127.0.0.1:3101), **no V1 dashboard/proxy**, **`writer_mode:stub`**, synthetic data, temp acceptance-only secrets, fresh DB (schema+32 migrations+catalogs). Private-only (127.0.0.1, no funnel, Tailscale-IP probe refused).
- **Deployed evidence (accepted by operator):** item 1 canonical Schedule accept → auto Topic generation on the deployed stack (PASS 12/0: completed, population=4, idempotent, fail-closed, provenance stub, no live provider/secrets); items 2–4 via the actual deployed browser over the SSH tunnel — bilingual four-state/RTL-LTR/keyboard-focus/375·768·1280, per-item family + typed denied/stale/conflict, closed operational-state fault matrix, provenance read model, live byte-equality. (5 first-run failures were fixture-state from my own `/gw` evidence mutations, not deployed defects → clean-gate re-run 6/6.)
- **Operator acceptance decision — REJECT client-product acceptance** (infra/backend + governed evidence ACCEPTED). Rejection cause: **P1 information-architecture/discoverability defects the direct-route tests masked** — root exposes a standalone `Runs / Canonical slots` selector (should be schedule-first), two disjoint `main` regions, run selection doesn't establish/open operational context (functions hidden behind direct `/runs/{id}` URLs), no persistent run→stage→lens context, pre-generation Topic coverage allocations not shown as the first Topic state, missing client-facing schedule-code/date-grouping/platform/pillar/language context, custom-range vs relative-day mismatch, and a governed reorder-denial mislabeled "Could not read the schedule." **These defects are consumed by directive #331 (schedule-first operator shell), NOT by #330.**
- **Retention (operator):** **retain the clean acc330 lane RUNNING privately**; preserve backup + non-secret manifest; no public exposure, live provider, old-data restore, or host/network/provider change. **The acc330 lane + backup remain unchanged.**
- **Stage 2 and #294 remain OPEN/HOLD.** #294 DoD item-9 (client-product acceptance) is NOT satisfied — it is REJECTED pending deployed reacceptance after #331. Ordered path: #331 (schedule-first shell) → merge → separate explicit redeploy/reacceptance instruction → then #294 item-9 reconsideration. Provisional P2 `topic_generation_policy` authoring remains separately scheduled. Queue after closeout: #331 approved (next).

## 2026-07-18 · #328 CLOSED (directive:done) — Stage 2 exit-document correction MERGED (docs-only); Stage 2 stays OPEN/HOLD
- **PR #329 squash-merged `8338d776b5fe5045db15105ffe8dad2ee45b9591` at 2026-07-18T18:53:00Z** (by Kholio), reviewed exact head `cc4047fa735eb1158b7f63c838f7098940045b38` (Codex GO preflight → Codex exact-head re-review → GPT → operator merge). **Documentation-only: exactly two files, two sections (+24/−7). No product/runtime/schema/API/UI/deploy/provider/policy-authoring change.** Dirty canonical checkout (feat/issue-292) never touched.
- **What changed (aligning the Stage-2 transition docs with the #316 REJECT + #327 HOLD):**
  - `docs/v2-transition/README.md §8 item 3`: the Payload/NocoBase/Directus control-plane proof is **CLOSED as REJECT (#316)**; #294's external-adapter expectation **cancelled**; Tanaghom-governed authoring retained; no adapter dependency remains.
  - `docs/v2-transition/stage-2b3-evidence.md §Stage 2C`: reframed from "mandatory prerequisite" to **RESOLVED-as-REJECT**. States unambiguously that **Stage 2 remains OPEN/HOLD** — not on any adapter, but on **#294 DoD item 9 (post-merge deployment/client-acceptance)**, a **P1 pre-close gate that is NOT MET** (no deploy) requiring a separately authorized directive. Records `topic_generation_policy` create/activate authoring as **provisional P2 / non-blocking / separately scheduled** (retained safe path = default governed generation; **never direct DB**). Refs #316/#327/#294 added; CP ceilings + explicit non-claims unchanged; **no Stage-2-closed claim**.
  - Codex exact-head re-review fix (folded, head `f119be3`→`cc4047f`): scoped the adapter clause **"no external-adapter dependency or P0/P1 remains"** → **"…or external-adapter P0/P1 remains"** so it cannot contradict the item-9 Stage 2 P1 blocker.
- **Lifecycle state after merge (UNCHANGED by this docs correction): Stage 2 remains OPEN/HOLD; #294 remains OPEN.** Ordered remaining gates: **(1) separate authorized deployment/client-acceptance directive [P1 item-9 gate]** → **(2) #294 exit reconciliation** once item-9 lands. **Provisional P2 `topic_generation_policy` governed create/activate authoring remains separately scheduled** (default policy safe path; never direct DB). No directives/issues were created by #328.
- **Preserved:** PostgreSQL/Tanaghom sole authority; governed writer route (`gfws_ollama` deferred/untouched); V2-only, V1 immutable reference-only/no fallback; shared IAM/AgentRep/delegation/config-lineage/approvals/provenance; SDAM/AVP/BrandShield/Postiz contracts; initialization rule. Broader status docs (HANDOFF/BUILD_STATE/ROADMAP/00_INDEX) deliberately NOT touched (out of #328 scope; MODIFIED in dirty canonical — operator-owned). Queue after closeout: no `directive:approved` outstanding.

## 2026-07-18 · #327 CLOSED (directive:done) — V2 Stage 2 exit reconciliation → HOLD (near-close), Stage 2 NOT closed
- **Planning-only, read-only reconciliation; no product/docs mutation, tests, deploy, credentials, providers, issue creation, #294 close, or Stage 3.** Isolated worktree at `main@b353b063`; dirty canonical checkout (feat/issue-292) never touched. Report: issue #327 comment 5012327729; Codex reconciliation: 5012341642; ACK of correction: 5012347133.
- **Verdict: HOLD (shallow/near-close). Stage 2 is NOT closed and must not be claimed closed.** All 8 #294 Stage-2 behavior criteria MET (auto-start after acceptance; job truth+recovery; bounded novelty dedup `novelty-v1` [#268 full retrieval deferred, bounded brief satisfies the criterion]; pillar/HCS/framework propagation; full review family; bilingual four-state presentation; resolved provenance; V2 UX/V1-compat/audit/tests). Runtime authority COMPLETE (fail-closed resolution, immutable job pinning, no unauthorized activation).
- **Codex-CORRECTED pre-close blocker (P1): #294 DoD item 9 — client acceptance evidence = NOT MET.** No post-merge DEPLOYMENT / client-acceptance evidence exists; the per-slice immutable merge-head gates explicitly record **no deploy**, and the client-evidence record (`stage-2b3-evidence.md`) is deliberately weakest-defensible and makes NO closeout claim. (CC's initial pass over-credited this as "MET"; corrected to P1 NOT MET.) This P1 requires a **separate authorized deployment/client-acceptance directive** before Stage 2 can close.
- **`topic_generation_policy` generation authoring gap = provisional P2 (non-blocking), separately scheduled.** No governed create/activate endpoint (only create-missing bootstrap); no Stage-2 behavioral/operator-workflow/SDR dependency (default `automatic` policy produces the expected topic population); retained safe path = default policy now + a bounded governed endpoint later; **direct DB writes are NEVER the fallback**. `repetition_policy` already has governed `GET`+authority-gated `PUT` (`api.py:1119,1131`) — confirmed, not reopened.
- **Not Stage-2 blockers:** whole-job regenerate/retry is recommendation-only in V2 by conserved design (#293 — V2 signs nothing; per-topic rework IS a governed V2 write); CP-029/030 blocked-input (production OIDC/named-roles, availability/retention/recovery/KPI) + native-Levantine acceptance + promotion/campaign = later-stage/production-hardening **N.A. to Stage-2 exit** (disclosed non-claims); #237 CLOSED (evidence-doc's "#237 open" is stale); #249 reconsideration + stable cross-revision head-id = conserved/deferred, out-of-scope.
- **#316 consumed:** external adapters REJECTED, #294's Stage-2C expectation cancelled, **no hidden Payload/Directus/NocoBase dependency** anywhere in the merged Stage-2 surface (adapter appears only as REJECT text).
- **Documentation:** no doc falsely claims Stage 2 closed. Two Stage-2-exit docs carry a now-FALSE #316-pending statement and must be corrected pre-close (`docs/v2-transition/README.md §8`; `docs/v2-transition/stage-2b3-evidence.md §Stage-2C`). HANDOFF/BUILD_STATE/ROADMAP/00_INDEX are V1-era stale but emit no false Stage-2 claim (post-close housekeeping; already MODIFIED in dirty canonical — reconcile, don't duplicate).
- **Corrected ordered close-out (each a SEPARATE GPT-reviewed + operator-approved directive; #327 authorizes NONE, creates NO issues, does NOT close #294):** (1) docs-correction directive; (2) **authorized deployment/client-acceptance directive [P1 item-9 gate]**; (3) reconcile #294 once (1)+(2) land. `topic_generation_policy` endpoint scheduled separately as P2.
- **Contract freeze (completed Stage-2 backend/architecture boundary, stable for Stage 3):** migrations `028–032`; `generation_job` (lease/heartbeat/recovery, exactly-once) + `topic_provenance` (resolved provider/model/route + pinned generations + authority/writer-contract snapshot); canonical governed commands `decide`/`edit_revision`/`rework_from`/bulk-ledger/presentation-reorder; append-only `topic` revisions; versioned-generation config model (`methodology_version`, `content_format_version`, `topic_generation_policy`, `repetition_policy`) with exactly-one-active + create-missing-only init rule; V2 workbench lane over the same backend, V1 reference-only. The P2 policy-authoring endpoint is NOT a Stage-3 blocker.
- **Preserved:** PostgreSQL/Tanaghom authority; governed writer route (`gfws_ollama` deferred/untouched); V2-only, V1 immutable reference-only/no fallback; shared IAM/AgentRep/delegation/config-lineage/approvals/provenance; SDAM/AVP/BrandShield/Postiz contracts; initialization rule. Queue after closeout: no `directive:approved` outstanding.

## 2026-07-18 · #316 CLOSED (directive:done) — Stage 2C external control-plane adapter proof → REJECT / STOP (no build)
- **Read-only adversarial preflight ONLY; no product implementation, schema, adapter, prototype, import subsystem, credential, PR, deploy, Stage 3, or policy-authoring work.** Detached isolated worktree at `main@37a6121e`; dirty canonical checkout (feat/issue-292) never touched. `main` unchanged (a REJECT/STOP produces no code). Preflight: issue #316 comment 5011750250; Codex reconciliation: comment 5011843078.
- **Decision: REJECT** Payload, Directus, and NocoBase as Stage 2 external authoring/control-plane adapters; **verdict STOP** (build nothing). **#294's Stage-2 external-adapter expectation is CANCELLED as unnecessary** — retain Tanaghom-governed authoring. Codex accepted STOP as an authorized decision outcome (not scope drift), matching the #323/#324 on-merits feasibility-screen precedent.
- **Why (evidence-driven):** the operator-authored Stage-2 config surface is SMALL (topic-generation/repetition policy + methodology & content-format taxonomy incl. paired-field bilingual `name_en`/`name_ar`) and MOSTLY ALREADY has a mature governed versioned-generation authoring path in Tanaghom (markdown-digest sync + `POST /methodologies/{key}/versions/draft`→`activate` and `POST/PUT /content-formats`; exactly-one-active, human-commit-on-activate, create-missing-only init rule). The #313/#315 bilingual review fields (`change_summary_ar/en`, `text_ar`…) are model-GENERATED per-revision content and the #314 bulk/presentation ledgers are operational — NOT operator config, out of adapter scope. An external plane would only DUPLICATE existing authoring while adding an import/proposal/observation/version-compare/tombstone/conflict/drift/attribution subsystem PLUS a second-authority surface to fence (Payload `_status`/roles — moderate; Directus Flows/`status`/promote/RBAC — larger; NocoBase full workflow + native Approval trigger/node + IAM — largest) PLUS licensing/versioning risk, for a small single-operator rarely-authored trial taxonomy. No justified Stage-2 value.
- **Candidate ranking (if a narrow future need ever forces reconsideration):** Payload v3 (MIT, native per-field ar/en localization, immutable per-version identity `_id`+`parent`+`updatedAt`, cleanest authority fence) > Directus 12 (strong tech, but license CHURNED BSL→MSCL-1.0-GPL v12/May-2026 with a movable $5M/50-emp free-tier program term, →GPL after 4y) > NocoBase 2.0 (Apache-2.0 now, but NO native per-record bilingual values, NO OSS per-version identity — Record History is commercial with a first-write coverage gap + no documented version API, and the LARGEST second-authority surface). Reconsideration trigger is narrow: an evidenced multi-author rich-bilingual authoring requirement Tanaghom cannot meet → re-evaluate **Payload** first.
- **Codex factual correction (recorded):** the preflight wrongly said `repetition_policy` lacks an admin endpoint — merged main ALREADY has `GET /repetition-policy` + authority-gated/audited `PUT /repetition-policy` with sparse validation + selftest coverage. Therefore the SOLE remaining Stage-2 authoring gap is **governed creation/activation of new `topic_generation_policy` generations** (bootstrap is create-missing-only; runtime resolution/pinning already fail closed and preserve lineage; but operator authoring lacks a governed endpoint). This correction STRENGTHENS the REJECT.
- **Stage 2 disposition (do NOT approximate):** #316's external-adapter requirement is satisfied by explicit REJECT + cancellation; no external-adapter P0/P1 remains. The `topic_generation_policy` authoring gap must be **classified during the bounded Stage-2 exit reconciliation** (record severity/owner) — it is a separate small governed-config directive, NOT to be folded into #316 and NOT to be approximated with direct DB writes. **Stage 2 must NOT be claimed closed** until that reconciliation validates all #294 exit criteria.
- **Preserved:** shared IAM/AgentRep/delegation/methodology-config lineage/approvals/provenance/SDAM/AVP/BrandShield/Postiz contracts; V2-only; governed writer route; initialization rule; V1 reference-only. Queue after closeout: no `directive:approved` outstanding.

## 2026-07-18 · #315 CLOSED (directive:done) — V2 Stage 2B-3 bilingual/responsive/a11y Topic review UX + client evidence MERGED
- **PR #326 squash-merged `b18de776e2947951bcc39ba8beca1a75ec0714d3` at 2026-07-18T14:37:53Z**, reviewed exact
  head `f7ec459d60dd8f707103b9625cd217e8d2c12bf2`. Operator-authorized merge with Codex CLEAR + GPT APPROVE. The
  UX/accessibility/evidence completion of the V2 Topic review lane over the #313 per-item and #314 bulk/
  presentation-order semantics. **V2-only; V1 reference-only; no schema/backend-authority/provider/model-route/
  control-plane/deploy/#316 change. Dirty canonical checkout (feat/issue-292) never touched.** CLOSED. Mac only, no deploy.
- **What shipped (frontend + tests + evidence only):** (1) a V2-owned four-state bilingual utility
  (`workbench/lib/bilingual.ts` + `bilingual-text.tsx`) rendering the canonical `change_summary_ar`/`_en` pair as
  bilingual/arabic-only/english-only/**missing** — the missing state is RENDERED + disclosed ("not provided in
  either language"), never absence-of-UI, and never a fabricated counterpart; no V1 import/dep/fallback.
  (2) Truthful language semantics: chrome stays `lang="en"`; a shared `DirToggle` flips only `dir`, **adopts the
  authoritative `<html dir>` on mount** (proven across a client-side route remount — no drift), and exposes an
  explicit `aria-pressed` state with a stable accessible name; per-node `lang`/`dir` + bidi isolation on Arabic
  content (topic panel + generation-seam `title`/`meaning`). (3) The `DirToggle` was extracted from the shell and
  added to the run route, where the Topic/bulk/reorder surfaces actually live (previously RTL was unreachable there).
- **Source-byte integrity landed as Codex "Option B"** (the load-bearing reconciliation): V2 transmits the edit
  value **raw** on the wire (trim is only the non-empty submit predicate); the shared server `edit_revision` `strip()`
  is pre-existing V1/backend behavior LEFT UNCHANGED, so the e2e asserts + **discloses** the server-canonicalized
  persisted value (no false raw-whitespace-persistence claim). The byte proof was made **non-vacuous**: it discovers
  a deterministically eligible run and REQUIRES a successful live bulk disposition (`succeeded`) AND a successful
  live reorder (governed token ADVANCES) before proving canonical Topic **source** bytes are byte-for-byte unchanged;
  append-only history immutability + all non-content display paths also proven. Conflict path proven separately.
- **Accessibility evidence** is keyboard-only with focus restoration to an announced `role=status`/`alert` region
  after per-item, bulk AND reorder commands — SUCCESS and typed conflict/error (per-item stale 409, bulk
  whole-request 403, reorder conflict 409); plus a **closed deterministic operational-state matrix**
  (loading/empty/busy/denied/stale/conflict/partial/error) over per-item/bulk/reorder via controlled fixtures with
  typed reasons + roles, **no conditional skip**, and an ERROR case that asserts the named retry affordance + recovery.
- **Three Codex exact-head review cycles** drove this (2911e37 → 46cbc23 → f7ec459): (a) 6 impl findings — real
  missing-state, bulk/reorder focus, ops-state matrix, live byte execution, DirToggle sync, truthful wording;
  (b) 4 evidence findings — non-vacuous byte proof, typed-failure focus, determinism (min-slot discovery +
  remount proof), and stale-PR-body/named-retry. Each head movement restarted the merge checklist; no head reached
  GPT until Codex CLEAR.
- **Validation trap worth remembering:** this isolated pr315 stack seeds R1 at the Topic-review stage, so the #304
  `run-schedule`/`runs-calendar` placement specs (which need Schedule-stage/placeable/`RE2E` fixtures) are
  fixture-incompatible and NOT part of the #315-relevant pack — they resolve independent of this diff (which touches
  no slot-lifecycle/schedule logic). The canonical `RE2E` UI fixture (`gates/e2e_seed.py`) had to be seeded for the
  shell real-read test. Immutable merge-head gate: **#315-relevant pack 42/42, 0 skipped** at `f7ec459` in
  `writer_mode:stub`, serial/1-worker/0-retries, no `api_selftest` overlap, no V1 suite.
- **Stage 2 remains OPEN. #316 (Stage 2C — Payload vs NocoBase/Directus control-plane adapter proof) is a hard
  prerequisite; #315 makes NO Stage-2-closed claim and did NO #316 work.** Queue after closeout: no other
  `directive:approved` outstanding for this lane.

## 2026-07-18 · #314 CLOSED (directive:done) — V2 Stage 2B-2 bulk Topic disposition + governed presentation order MERGED
- **PR #325 squash-merged `dca8070656f1806a7e92164a6fb1ea71c2b31f02` at 2026-07-18T08:18:31Z**, reviewed exact
  head `93575b972058b13b0bf0a600f9aa2fda1044fd17`. First PostgreSQL-native product slice after the #323/#324
  architecture gate (both REJECTed Git-native/forge alternatives for this bounded scope). CLOSED. No deploy. Mac only.
- **The architecture detour is the headline.** Before a line of #314 shipped, two P0 adversarial evaluations ran
  read-only and both landed REJECT on the merits (not status-quo bias): **#323** (Git-native/opaque-manifest/
  workflow-engine durable record) — the exactly-one-winner serializer must be PostgreSQL, sensitive payload can't
  enter immutable Git (erasure), #314's core has no external effect; **#324** (Forgejo/Gitea forge control plane) —
  a forge replaces ~0 trial-critical work, has no embeddable widgets, RTL/WCAG UNKNOWN, and the forge-strong bits
  (notifications/queues/search) map to SDR-*deferred* needs. Both used the feasibility-screen-vs-scorecard
  discipline (scope is a hard screen, not a scaled penalty) and canonical REST-`.body` digests. GPT drove multiple
  REVISE-EVIDENCE cycles that materially improved the packages.
- **What shipped:** migration 032 (additive/idempotent, no runner) — (1) `bulk_operation`/`bulk_operation_item`
  durable per-item-commit ledger for `{bulk_approve, bulk_request_change, bulk_drop}`, each item mapped to the
  existing canonical `decide` (idempotent + head-stable) committed ATOMICALLY with its ledger outcome via
  `decide(_commit=False)`; truthful outcomes incl. `not_attempted`; `claim_token` fence; request-digest-bound
  idempotency (typed mismatch); mandatory positive `expected_revision` (no NULL=head); **creation authority
  enforced before any write** (unauthorized ⇒ zero rows). (2) `topic_presentation_generation`/`_position` —
  append-only PRESENTATION-only order, distinct from #292 (own token), exactly-one-winner `ON CONFLICT`. Plus 4
  `/gw` endpoints + V2 workbench UI (bulk-disposition + accessible reorder, typed partial/stale/denial + bidi,
  retry-stable idempotency key) + proof wired into `gates.api_selftest` + a production-shaped Playwright flow.
- **Codex exact-head review found real defects across three cycles, all reproduced-then-fixed:** (a) request-
  unbound idempotency, inert `pinned_topic_id`, unfenced `fail_bulk_operation` (not_attempted could race a
  committed effect), read-auth = any-signed-principal, missing membership validation; (b) `expected_revision`
  nullable, and K3–K6 were SEQUENTIAL not real interleavings; (c) creation authority weakened to any-signed-
  principal (durable writes before per-item denial), and the V2 idempotency key was `Date.now()` (a retry minted
  a new operation). Two genuinely load-bearing engine findings emerged from the *forced-interleaving proof itself*:
  a **real slot-FK serialization deadlock** between reorder and a concurrent edit (fixed: deterministic lock order
  round→slots ascending `FOR KEY SHARE` + residual surfaced as a RETRYABLE typed conflict, 409 never 500), and the
  **atomic decide+settle** requirement (a NULL-outcome item now provably has no committed effect, so
  `not_attempted` is truthful).
- **Testing lessons worth carrying:** (1) a "real forced-interleaving" claim must use actual threads/Barriers —
  sequential state setup asserted as concurrency is a false pass Codex will (correctly) reject; the six required
  pairings (reorder×reorder, reorder×drop, reorder×head/rework, bulk×individual, bulk×Stage-2A/recovery ownership,
  duplicate partial replay) each need real interleaving + DB/audit/batch assertions. (2) A test-authority probe
  must not consume the item it asserts on — the Playwright gate-discovery probe was moved to a SEPARATE sacrificial
  slot and the asserted item proven un-mutated (its head, pinned by the UI CAS on the wire). (3) `decide` is
  idempotent + head-STABLE — that's what makes per-item recovery safe; the atomic settle closes the last window.
  (4) An unauthorized-creation test must assert **zero** durable rows, not merely a typed denial.
- **Validation at `93575b9`** (isolated `tanaghom_pr314`, exact `"writer_mode":"stub"`, workers 1 / retries 0,
  no `api_selftest`↔Playwright DB overlap): migration 032 clean on 001→032 + idempotent; `gates.selftest` ALL
  PASSED; `gates.api_selftest` ALL API CHECKS PASSED — #314 proof A–K (creation-authority zero-write E + REAL
  threaded K1–K6) + all prior #313/#319/#321 proofs; workbench `tsc` clean; `next build` clean; Playwright 3/3.
- **Residuals:** V2-only; V1 immutable reference-only (no fallback / no V1 gate); #249 unconsumed (approved/
  downstream fail-closed, never reopened); writer route/Ollama/config unchanged; no new authority/semantics/schema
  beyond the two authorized resources. **#315/#316 remain blocked, not started.** Isolated `tanaghom-gateapi-314` +
  `tanaghom_pr314` torn down; local branch deleted (remote auto-removed on merge); local `main` advanced
  `d5e1219..dca8070` via **direct ref update** — the dirty canonical checkout was never touched (`feat/issue-292`
  @ `8617d95`, 20 dirty operator-owned files preserved).

## 2026-07-18 · #321 CLOSED (directive:done) — Topic governance authority/decision-validity/recovery/provenance/gate MERGED
- **PR #322 squash-merged 2026-07-17T21:25:26Z** (2026-07-18 01:25:26 +04:00) by `Kholio`, exact-head protection. Reviewed head
  (PR `headRefOid`) `e5b2a822a47ff8011ba81641732b06fdeb83b9c5`; squash `mergeCommit` `5ba561a5701386db2da59cbe60176812bc3325f6`
  (single parent `21500e5`). Because it is a squash, `e5b2a82` is deliberately **NOT** an ancestor of `5ba561a` — the reviewed head
  is the PR head-of-record, not in main's linear history. `origin/main == 5ba561a`. #321 `directive:done`, **closed**. No deploy. Mac only.
  Merge verified independently (state=MERGED, mergeCommit + reviewed head both matched, squash distinction confirmed) before any closeout mutation.
- **What shipped (additive, V2-only, fail-closed, ZERO migrations):** closes the reachable #318 P1 findings on post-#319 main —
  R3 lock/eligibility TOCTOU, R4 canonical authority, R5 exact decision validity, R6 bounded recovery ownership, R8 provenance truth,
  N1 rework lifecycle audit, R10 focused gate — establishing one concurrency-safe, authority-correct, recoverable, provenance-truthful
  Topic governance foundation for #314–#316.
  - **R3** — `edit_revision`/`restore_revision` acquire the canonical slot lock FIRST, then re-read authority + idempotency +
    eligibility + CAS UNDER the lock; any post-lock denial rolls back to release the lock (no leak). `begin_rework_operation` already
    lock-first.
  - **R4** — edit/restore/rework enforce the SAME existing `stage_approval_contract`/frozen-gate assignment + actor hard floor that
    decide/drop/approve use (via `_authorize_topic_item_mutation`); missing/ambiguous assignment fails closed typed. **Never
    `workflow.admin`** (that stays #319-terminalization-exclusive); no role-name inference, fixture bypass, or new permission.
  - **R5** — `resolve()` locks each slot and computes approval quorum/coverage ONLY from approvals on the EXACT current head; a
    superseded approval yields deterministic `stale_revision` (a not-yet-quorum on the head stays `pending`); the decision/pin is
    preserved (never deleted); the later head is never represented as approved; re-approval on the current head advances.
  - **R6** — bounded periodic rework drain on the existing #310 startup daemon (`TANAGHOM_REWORK_RECOVERY_BATCH`, validated positive;
    `TANAGHOM_REWORK_RECOVERY_DISABLED` for deterministic tests); claim/drive ONLY, no terminalization call path; overlap-safe via the
    atomic #319 claim; active/completed/terminal excluded. No new scheduler.
  - **R8** — rework provenance records the ACTUAL served provider/model from the runner (`chat.model`, fallback-aware), or NULL for
    genuine absence; never the config-preference dict or `"unknown"`. Governed route (OpenRouter Llama-4-Scout → Groq Llama-4-Scout →
    Groq Qwen3-32B → deferred `gfws_ollama`) unchanged; `gfws_ollama` unregistered; Ollama embeddings-only.
  - **N1** — immutable enumerated rework lifecycle audits: `rework_started`, `rework_claimed`/`rework_reclaimed`, `rework_failed`
    (clean owned failure only), `rework_completed`; the #319 `rework_operation_terminated` event retained unchanged.
  - **R10** — the previously-unwired #313 governance proof AND the new `tools/proof_topic_governance_321.py` are mechanically invoked
    by `gates.api_selftest`; the #319 proof is retained unchanged in substance.
- **P1.4 consistency (Codex exact-head cycles):** all reviewer-facing read models/audit made exact-current-head aware so there is ONE
  truth — persisted `gate_token_coverage` (head-filtered via `_recompute_slot_coverage`), `_authoritative_target_projection`, the
  decision-time `coverage_recomputed` audit, the legacy `_decision_rollup`/`_remaining_assignment_snapshots`, and
  `list_pending_approvals` "mine/currently decided". A new `_reproject_open_gate_coverage` recomputes derived open-gate coverage on
  head advance (edit/restore). reject/request_change stay revision-INDEPENDENT throughout; every `gate_decision` row and all audit/history preserved.
- **#249 UNCONSUMED (preserved):** approved/downstream reconsideration stays a typed denial; `request_change` received canonical
  locking + existing authority + typed errors + exact-revision only — it clears no approvals, reopens no items, alters no product meaning.
- **Codex exact-head review cycles (all at exact heads, STOP → patch → re-review):** STOP-1 `549612b`-equivalent... actually for #321:
  first STOP (P1.1 lock-before-authority/replay, P1.2 current-revision quorum, P1.3 real bounded-drain proof) → patched `13ac865`;
  STOP-2 (P1.4 two-truths: revision-blind coverage/read-models/audit) → patched `38a4252`; STOP-3 (two remaining reviewer projections:
  `list_pending_approvals` "mine" + legacy `_remaining_assignment_snapshots`) → patched `e5b2a82` → operator-authorized + squash-merged.
- **Exact-head evidence @ `e5b2a82`** (isolated per acceptance 10/11; purpose-built because canonical `tanaghom-gateapi` mounts the
  wrong tree): DB `tanaghom_pr321` (fresh schema + all migrations + loader), API :8022, `"writer_mode":"stub"` exact match, one worker,
  **zero retries**, no shared-DB overlap; V1 full suite NOT used as the V2 gate. `gates.api_selftest` (wired #319 + #313 + #321 proofs)
  ALL PASSED; `gates.selftest` ALL PASSED; confirmed deterministic across repeated pristine runs. No `db/` changes — **zero migrations**.
- **Scope discipline:** authority not broadened, ownership fencing not weakened, no schema/migration, no V1 change or fallback, no live
  provider or route change, no deploy, no secrets, no `gfws_ollama`, no capability-matrix work. #314–#316 (which #321 blocks) remain
  BLOCKED until this merged head passes the required gate — satisfied here. Canonical dirty checkout never modified — all work in
  isolated worktrees; local `main` fast-forwarded ref-only to `5ba561a`; feature branch/worktree removed (remote auto-deleted on
  squash-merge); isolated validation stack torn down.
- **RESIDUALS carried forward:** (1) the #318 **P2/P3** findings (deferred by the directive); (2) `list_dropped`'s `_slot_outcome` was
  left revision-independent (it lists rejected slots where reject precedence makes approvals moot) — flagged and Codex-accepted. Track
  with the #318 follow-up.

## 2026-07-17 · #319 CLOSED (directive:done) — P0 stale rework rollback + permanent-fence recovery MERGED
- **PR #320 squash-merged 2026-07-17T18:08:11Z** (22:08:11 +04:00) by `Kholio`. Exact reviewed head (PR `headRefOid`)
  `7637499225204869c890b0183620a91c5a0d0c63`; squash `mergeCommit` `7955270f1c6c782901c716648a733b99894eab0a`. Because it is a squash,
  `7637499` is deliberately **NOT** an ancestor of `7955270` — the reviewed head lives on as the PR head-of-record, not in main's linear
  history. `origin/main == 7955270`. Squash parent `ca3b685` (executor-log update 2). #319 `directive:done`, **closed**. No deploy. Mac only.
  Verified independently (state=MERGED, mergeCommit + reviewed head both matched, squash-head distinction confirmed) before any closeout mutation.
- **What shipped (additive, V2-only, fail-closed, ZERO migrations):** the #313 exactly-once/fail-closed rework contract is restored.
  `complete_rework_operation()` rejects a stale `claim_token` with a plain Python raise, which does NOT abort the SQL transaction — it
  stays open and committable; the worker's handler then committed the whole rejected generation on the SAME connection. Root cause:
  connection-scoped `commit()` + connection reuse, NOT the fence. Repair: (1) `run_rework_operation` rolls back FIRST, then records failure
  on a SEPARATE clean connection; (2) `fail_rework_operation` documents its commit scope, reports ownership, won't flip a terminalized op
  back to failed; (3) new `terminalize_rework_operation` — the one governed escape from a fence recovery can never clear: authority → slot
  lock → op-row FOR UPDATE → idempotency lookup → token revalidation → eligibility → transition → audit, all in ONE transaction under ONE
  lock (order slot→op matches `begin_rework_operation`; no deadlock); (4) the `rework_active` fence now excludes only the terminal state
  (`failed` still fences — genuinely resumable, releasing it would reopen the #313 P1-2 source-mutation hazard); (5) new
  `GET /rework_operations/{op_id}` + `POST /rework_operations/{op_id}/terminalize`. A provably-false comment claiming a raising persist
  hook rolls back was corrected.
- **ZERO migrations:** `rework_operation.state` is free-text (no CHECK), so the terminal state needs no DDL; `claim`/`recoverable` exclude
  an unknown state via existing predicates; the expected-op token derives from the row's own durable columns; idempotency rides the
  append-only `audit_log` (the audit row IS the receipt). `db/migrations/` was byte-identical between fixed and pre-fix trees.
- **Authority — narrowing bind, no broadening:** terminalization AND the recovery read both require the EXISTING explicit `workflow.admin`
  permission held by the principal. Deliberately NOT `actors._has_permission` (True-for-everyone while `require_permission` unseeded); role
  names confer nothing (`principal_role` has no permissions column, so a role cannot prove the permission); no `workflow.assign`/`config.write`
  fallback, no fixture bypass. IAM-on fail-closed. Read denies at the route (401 unsigned / 403 wrong-authority); the mutating write denies
  through the engine's typed + AUDITED `governed_denial` channel (409, `reason=unauthorized`) — the read-403/write-409 asymmetry was
  **explicitly accepted** by Codex.
- **#249 UNCONSUMED (preserved):** terminalization moves ONE op to ONE terminal state, releases that op's derived fence, appends ONE
  immutable audit row. It creates/selects NO revision, alters NO provenance, mutates NO approval/downstream state, confers NO reconsideration
  authority — an approved item stays `governed_denial(reason=approved)` after the fence releases (proof §6).
- **Codex exact-head review cycles (STOP → patch → re-review, all at exact heads):** STOP-1 at `549612b` (three P1s: anonymous recovery
  read, unexercised HTTP contract, empty `gate_decision` fixture) → patched at `45e9186` → re-review CLOSED the three findings and ACCEPTED
  the denial-code asymmetry, requiring one more live-HTTP case (active-owner) → patched test-only at `7637499` → merged. Determinism of the
  timing-sensitive §1 lease-expiry + §5 6-way race confirmed across repeated back-to-back runs.
- **Defect-specific proof — `tools/proof_rework_recovery_319.py`, mechanically invoked by `gates.api_selftest`** (importing it RUNS it;
  `SystemExit(1)` fails the mandatory command — wired so it cannot decay into an unwired narrative harness). Drives the REAL worker through
  a deterministic forced interleaving (real `begin` → real `run_rework_operation` in a thread → real lease expiry via a stalled heartbeat →
  real competing `claim` → real stale completion). All SEVEN generation-touched tables (topic, slot, gate_decision, audit_log, directive,
  topic_provenance, rework_operation) snapshotted BY VALUE. §1 defect (checkpoints A/B, incl. a REAL seeded open `topic_review`
  `gate_decision` that survives post-fix and is deleted pre-fix) · §2 competing ownership → exactly one revision + one provenance, fence
  released WITHOUT terminalization · §3 clean owner-failure delta · §4 terminalization authority/eligibility/bounds/immutable audit · §5
  6-way same-key concurrency race (exactly one transition, one audit row) · §6 no #249 authority · §7 LIVE HTTP contract incl. auth read
  boundary (401/403), token read→write round trip, actor mismatch, and both recoverable AND active-owner denials with no state/audit/fence
  effect.
- **Exact-head evidence @ `7637499`** (isolated per acceptance 10; purpose-built because canonical `tanaghom-gateapi` mounts the wrong tree
  and all containers had been `Exited (255)`): post-fix DB `tanaghom_pr319` + API :8019 (restarted), `"writer_mode":"stub"` exact match —
  `gates.api_selftest` (+ wired proof) ALL PASSED, `gates.selftest` ALL PASSED, serial / single process / **zero retries** / pristine DB /
  no shared-DB overlap; V1 full suite NOT used as the V2 gate; three green full runs at the merged head. Pre-fix @ `78e7ea3` (test-only
  port) exit=1 — checkpoint A CHANGED = topic, slot, gate_decision, audit_log, directive, topic_provenance, then the permanent fence
  reproduces (`head 3 != restored 2`). #318 items 1–4 reproduced, not asserted.
- **Disclosed during execution (no green claimed over it):** an early proof draft clobbered `khal`/`huda` permissions and silently broke 7
  `gates.selftest` authorization checks — caught, fixed with dedicated `p319.admin`/`p319.noauth` principals, re-verified (seeded principals
  end at `[]`). The `gate_decision` destructive-DELETE path, initially unexercised over an empty fixture, was made non-vacuous per Codex STOP-1.
- **RESIDUALS (carried to a subsequent directive, NOT bundled here):** (1) the **#318 P1 findings**; (2) the **unwired
  `tools/proof_topic_item_governance_313.py`** — #313's own governance proof is referenced by nothing and no gate executes it (verified by
  full-tree grep). Track both together.
- **Scope discipline:** authority not broadened, ownership fencing not weakened, no schema/migration, no V1 change or fallback, no live
  provider, no deploy, no secrets, no `gfws_ollama`, no capability-matrix work. #314–#316 (which #319 blocks) NOT started. Canonical dirty
  checkout never modified — all work in isolated worktrees; local `main` fast-forwarded ref-only to `7955270`; implementation
  branch/worktree removed (remote branch auto-deleted on squash-merge); isolated validation stack torn down.

## 2026-07-17 · #319 UPDATE 2 — Codex re-review at `45e9186` accepted 3 findings; new head `7637499` (still directive:running)
- **Supersedes the `45e9186` head in the entry below.** Codex exact-head re-review (PR #320 comment 5005202360) **closed the three
  production findings** and **accepted** the read-403/write-409 authorization-denial-code asymmetry (route authorization vs the audited
  governed-write channel). One evidence-only gap remained: §7 exercised `recoverable` but never drove the live POST route against an
  active/live-lease op.
- **Test-only patch at `7637499`** (`45e9186..7637499`), **no production change** — the engine + route already enforced it; the added
  proof exposed nothing to fix. §7 now claims `op7b` into `state='running'` under an explicit 3600s lease (the §1 env pins a 2s lease
  that would expire first), then over HTTP: authenticated `GET` returns a token with `terminalization_eligible=false` + `lease_valid=true`;
  `POST /rework_operations/{op_id}/terminalize` → **409 `governed_denial` `active_owner`**; and the denial has **no effect** — every
  generation-touched table unchanged, the op's state/token/lease unchanged, **zero audit rows**, and the `rework_active` fence **not
  released**.
- **Evidence at `7637499`** (isolated, acceptance-10): post-fix DB `tanaghom_pr319` + API :8019 (restarted), `"writer_mode":"stub"` exact
  match — `gates.api_selftest` **exit=0 ALL API CHECKS PASSED**, `gates.selftest` **exit=0 ALL CHECKS PASSED**, serial / single process /
  zero retries / pristine DB. Pre-fix reproduction unaffected (aborts in §2 before §7); the accepted `exit=1` evidence stands at
  `78e7ea3`. Also confirmed determinism earlier: the timing-sensitive §1 lease-expiry + §5 6-way race were green across repeated
  back-to-back runs.
- **Scope unchanged:** test-only, authority not broadened, engine race untouched, V1 untouched, #314–#316 not started, not merged, not
  self-merged. **Held for FINAL Codex re-review before GPT.** Next: Codex final verdict → GPT → operator merge → CC post-merge closeout.

## 2026-07-17 · #319 UPDATE — Codex exact-head STOP at `549612b` resolved; new head `45e9186` (still directive:running)
- **Supersedes the head in the entry below.** Codex exact-head review STOPped `549612b` on three bounded P1s (PR #320 comment
  5004682282). Patched at **`45e9186`** (pushed `549612b..45e9186`); the reviewed head of record is now `45e9186`, **not** `549612b`.
  Still `directive:running`, **not merged, not self-merged**, held for **renewed Codex exact-head review before GPT**.
- **P1-1 — governed recovery read was anonymous.** `GET /rework_operations/{op_id}` now requires the signed principal **and** the same
  explicit `workflow.admin` as the terminalize command it feeds (read authority IS terminalize authority — the read exists only to mint
  the token the fenced write revalidates). Fail-closed, no role/near-permission fallback: unsigned → 401, wrong-authority → 403.
- **P1-2 — the new HTTP contract was unexercised** (the proof drove the engine directly). Added proof **§7**: live-API coverage over the
  actual FastAPI routes — authenticated read, unsigned/wrong-authority read denials, the token **read→write round trip**, authorized
  terminalize, stale-token, active/recoverable denial, idempotent replay, different-key denial, actor mismatch, body validation. The
  engine-level **6-way same-key concurrency race (§5) is kept unchanged**. Denial-code note: READ denies at the route (403); WRITE denies
  through the engine's typed+audited `governed_denial` channel (409, `reason=unauthorized`) to preserve the in-engine denial audit —
  both fail closed; flagged for Codex ruling.
- **P1-3 — `gate_decision` was asserted over an EMPTY fixture.** §1 now seeds a **real open `topic_review` `gate_decision`** on the
  stale-worker slot before the checkpoint baseline. The rework path DELETEs it inside the generation transaction, so post-fix it
  **SURVIVES** checkpoints A/B (rollback preserves it) and the pre-fix port at `78e7ea3` **demonstrably deletes** it — the exact
  stale-commit consequence #318 omits. Post-fix checkpoint A now also proves the reviewer decision survives; pre-fix checkpoint A shows
  `gate_decision` among the CHANGED tables.
- **Evidence at `45e9186`** (isolated, acceptance-10; purpose-built because canonical `tanaghom-gateapi` mounts the wrong tree and all
  containers had been `Exited (255)`): post-fix DB `tanaghom_pr319` + API :8019 (restarted for the api/engine changes), `"writer_mode":
  "stub"` exact match — `gates.api_selftest` (+ §7) **exit=0 ALL API CHECKS PASSED**, `gates.selftest` **exit=0 ALL CHECKS PASSED**,
  serial / single process / zero retries / pristine DB / no shared-DB overlap; V1 full suite NOT used. Pre-fix DB `tanaghom_pr319pre` +
  API :8020 at `78e7ea3`, test-only port → **exit=1** (checkpoint A CHANGED = `topic, slot, gate_decision, audit_log, directive,
  topic_provenance`, then the permanent fence reproduces: `head 3 != restored 2`).
- **Scope unchanged:** authority not broadened, engine race kept, V1 untouched, #314–#316 not started. Canonical dirty checkout never
  modified. Next: Codex re-review of `45e9186` → (GO) GPT → operator merge → CC post-merge closeout.

## 2026-07-17 · #319 AT MERGE GATE (directive:running) — P0 stale rework rollback + permanent-fence recovery
- **PR #320 OPEN at `549612b`** (`agent:cc`), branch `feat/issue-319-stale-rework-rollback`, base `main` == `78e7ea3`. **Not merged, not
  self-merged** — held at the human merge gate awaiting Codex/GPT review. Directive #319 remains `directive:running`. No deploy. Mac only.
  Executed under Codex reconciliation GO (issue comment 5003852260) after a mandatory read-only adversarial preflight.
- **The defect (audit #318, confirmed at line level on `78e7ea3`):** `engine.complete_rework_operation()` rejects a stale `claim_token`
  with a **plain Python raise**. That is not a SQL error, so psycopg2 never marks the transaction aborted — it stays **open and still
  committable**. `process_topic`'s commit is skipped but **nothing rolls back**; the worker's handler then called
  `fail_rework_operation()` on the **same connection**, whose unconditional `conn.commit()` durably persisted the whole rejected
  generation. Root cause is **connection-scoped commit + connection reuse**, not the fence: the fence was correct throughout.
  Consequence: a topic revision + provenance + slot advance + audit rows committed while `generated_revision` stayed `NULL`, and the
  resulting head/op mismatch fenced the Topic item **forever** (`_topic_item_mutation_eligibility` derived `rework_active` from
  `generated_revision IS NULL` alone, ignoring `state`; recovery re-drove the op, the worker's fail-closed source check rejected it,
  repeat). The in-code comment at `run_writers.py` claiming a raising persist hook rolls back was **provably false** and is corrected.
- **What shipped (additive, V2-only, fail-closed, ZERO migrations):** (1) `run_rework_operation` **rolls back FIRST**, then records
  failure on a **separate clean connection** — both halves load-bearing (rollback makes the rejection real; the clean connection keeps
  it real, since no failure write may share a transaction with generation effects it rejected). (2) `fail_rework_operation` documents
  its commit scope, reports whether it actually owned the op, and refuses to flip a terminalized op back to `failed`. (3) NEW
  `terminalize_rework_operation` — the one governed escape: authority → slot lock → op row `FOR UPDATE` → idempotency lookup → token
  revalidation → eligibility → transition → audit, **all in ONE transaction under ONE lock** (lock order slot→op matches
  `begin_rework_operation`, so no deadlock). Eligible only when provably unre-drivable (`failed` + `generated_revision IS NULL` + lease
  expired + restored source no longer head). Typed denials: `unauthorized`, `not_stranded`, `active_owner`, `recoverable`,
  `stale_token`, `already_terminalized`. (4) Fence now excludes **only** the terminal state — `failed` still fences (genuinely
  resumable; releasing it would reopen the #313 P1-2 hazard of a competing mutation changing the restored source under a reclaiming
  worker). (5) NEW `GET /rework_operations/{op_id}` + `POST /rework_operations/{op_id}/terminalize`.
- **ZERO migrations (verified):** `rework_operation.state` is free-text with **no CHECK constraint**, so the terminal state needs no
  DDL; `claim_rework_operation` and `recoverable_rework_operations` exclude an unknown state via their **existing** predicates with no
  edit. The expected-op token derives from the row's own durable columns; idempotency rides the **append-only `audit_log`** — the audit
  row IS the receipt. `db/migrations/` is **byte-identical** between the fixed and pre-fix trees.
- **Authority — narrowing bind, no broadening (Codex ruling 1):** terminalization requires the **existing explicit `workflow.admin`
  permission** on the principal. Deliberately **NOT** `actors._has_permission` (it returns True for everyone while
  `require_permission` is unseeded — a fine ramp for advisory checks, unacceptable for a fence-releasing command). Role names confer
  **nothing**: `principal_role` has **no permissions column**, so a role cannot *prove* the permission and inferring it would invent
  authority. No `workflow.assign`/`config.write` fallback, no fixture bypass. Proof principal `p319.noauth` deliberately holds
  `workflow.assign` + `config.write` + `policy.admin` **and** an `admin` role name — and is still denied.
- **#249 UNCONSUMED (preserved):** terminalization moves ONE operation to ONE terminal state, releases that operation's derived fence,
  and appends ONE immutable audit row. It creates/selects **no** revision, alters **no** provenance, mutates **no** approval/downstream
  state, and confers **no** reconsideration authority — releasing the fence returns the item to the state it would have had if the
  rework had never started; an approved item stays `governed_denial(reason=approved)` (proof §6).
- **Defect-specific proof — `tools/proof_rework_recovery_319.py`, mechanically invoked by `gates.api_selftest`** (importing it RUNS it;
  `SystemExit(1)` fails the mandatory command — deliberately wired so it cannot decay into an unwired narrative harness). Drives the
  **real** worker through a deterministic forced interleaving: real `begin_rework_operation` → real `run_rework_operation` in a thread →
  real lease expiry (heartbeat interval pushed beyond the generation via the existing `TANAGHOM_REWORK_HEARTBEAT_SECONDS` hook,
  modelling a stalled/partitioned beat) → real competing `claim_rework_operation` → real stale completion. All **seven**
  generation-touched tables (`topic`, `slot`, `gate_decision`, `audit_log`, `directive`, `topic_provenance`, `rework_operation`)
  snapshotted **by value**, not by row count. §1 defect (checkpoints A/B) · §2 competing ownership → exactly one revision + one
  provenance, fence released **without** terminalization · §3 clean owner-failure delta · §4 terminalization authority/eligibility/
  bounds/immutable audit · §5 **6-way same-key concurrency race** · §6 no #249 authority.
- **Codex ruling 2 (the live STOP path) — CLEARED:** §5 races six independent connections behind a barrier through
  `terminalize_rework_operation`; exactly **one** performed the transition, **five** observed the receipt as replays, and **exactly one**
  audit row exists. Audit-backed idempotency holds under concurrency under the same lock → **no additive-migration authorization needed**.
- **Exact-head evidence @ `549612b`** — isolated per acceptance 10, purpose-built because **every Tanaghom container was `Exited (255)`**
  (Docker daemon restart) and **`tanaghom-gateapi` mounts the CANONICAL tree, not the worktree** (validating through it would have
  silently tested the wrong tree at the wrong SHA):
  - **Post-fix:** DB `tanaghom_pr319` (fresh schema + all migrations + `load_methodology` all counts verified), API `tanaghom-gateapi-319`
    :8019 mounting `/Users/Kay/Dev/tanaghom-wt-319`, `"writer_mode":"stub"` **exact match**. `python -m gates.api_selftest` (+ wired #319
    proof) → **exit=0, ALL API CHECKS PASSED**; `python -m gates.selftest` → **exit=0, ALL CHECKS PASSED**. **Serial, single process,
    zero retries**, from a pristine DB; `api_selftest` never overlapped Playwright or any other suite on the DB. **V1 full suite NOT used
    as the V2 gate.** No dashboard/V2 surface changed (zero files under `dashboard/`), so no browser spec is affected; the new read
    boundary is exercised through `api_selftest`.
  - **Pre-fix (acceptance 3/9):** DB `tanaghom_pr319pre`, API :8020 mounting a **detached worktree at `78e7ea3`** with **only the test
    ported** (`engine.py`/`run_writers.py`/`api.py` byte-unmodified) → **exit=1**. Checkpoint A fails on
    `['topic','slot','audit_log','directive','topic_provenance']` (stale worker durably committed **topic v3 + provenance + slot advance
    + audit + directive** while `generated_revision` stayed NULL), and the run then **spontaneously reproduced the permanent fence** —
    the next recovery attempt died with `rework source changed (head 3 != restored 2)`. #318 items 1–4 reproduced, not asserted.
- **Disclosed honestly (no green claimed over it):** (1) an earlier draft of the proof **clobbered `khal`/`huda` permissions and never
  restored them**, silently breaking 7 `gates.selftest` authorization checks — caught, fixed with dedicated `p319.admin`/`p319.noauth`
  principals that touch nothing shared, and **verified by re-running the exact failing sequence** (seeded principals end at `[]`).
  (2) `gate_decision` is in the snapshot set and the rework path **does** `DELETE` from it inside the generation transaction (a stale
  commit **silently destroys reviewer decisions** — an aggravating consequence NOT named in #318), but this fixture had no open-gate
  decisions, so that column reads UNCHANGED: covered by the snapshot, not exercised by the scenario.
- **Residual for the #318 P1 follow-up (NOT bundled, per the reconciliation):** **nothing in the repo references
  `tools/proof_topic_item_governance_313.py`** — #313's own governance proof is **unwired** and no gate executes it. Verified by
  full-tree grep. Track with the #318 P1s.
- **Scope discipline:** #314–#316 **untouched**. No V1 change or fallback, no live provider, no deploy, no secrets, no `gfws_ollama`, no
  capability-matrix work. Canonical dirty checkout **never modified** — all work in isolated worktrees.
- **Next:** Codex/GPT exact-head review of PR #320 @ `549612b` → operator merge → CC post-merge closeout (verify merge → sync main →
  delete branch → `directive:running`→`directive:done` → close #319 → final `## ✅ Done` with merge SHA/time/residuals).
- **Environment left running for review:** `tanaghom-db`, `tanaghom-gateapi-319` (:8019, DB `tanaghom_pr319`, stub). The pre-fix stack
  (`tanaghom-gateapi-319-pre`, DB `tanaghom_pr319pre`, worktree `tanaghom-wt-319-prefix`) was torn down after evidence capture.

## 2026-07-17 · #313 CLOSED (directive:done) — Stage 2B-1 canonical per-item Topic governance
- **PR #317 squash-merged at 2026-07-17T09:38:31Z.** Exact reviewed head (PR `headRefOid`) `be52c325fefaedba45041150c187a3be27857abf`;
  squash `mergeCommit` `4035245956a1975e7f2b992e2ba27bfcbc1cbe92`. Because it is a squash, `be52c32` is deliberately **NOT** an
  ancestor of `4035245` — the reviewed head lives on as the PR head-of-record, not in main's linear history. origin/main == `4035245`.
  #313 `directive:done`, closed. No deploy. Mac only.
- **What shipped (additive, V2-only, fail-closed):** a canonical per-item Topic governance command family over the V2 seam —
  inspect/history, structured edit, request_change, regenerate/rework, non-destructive drop, restore-as-new-revision, approve.
  Stable identity is `slot_id`; `topic_id` is minted **per-revision** (surfaced in an explicit `identity` disclosure), append-only
  revisions with `base_revision` lineage. Optimistic-concurrency CAS (`expected_revision` → 409 `stale_revision`), idempotency keys
  (topic-only column), typed errors (`RevisionConflict`/`GovernedDenial` → 409). Command-atomicity via slot `FOR UPDATE` inside
  `engine.decide`'s single transaction. Durable rework OPERATION state machine (`rework_operation`) — queued/running/completed/failed,
  idempotency-keyed, leased, claim-token ownership fencing, Stage 2A-style heartbeat reconnect, exactly-once fenced completion.
  Additive migrations 029/030/031 only; no schema change beyond them. Human commit floor preserved (approve/request_change/drop
  RECORD the gate decision; the advance/transition stays the human commit).
- **#249 UNCONSUMED (preserved):** reopening an approved/downstream-advanced Topic (edit/rework/restore/drop) returns a typed
  `governed_denial` (`reason=approved|downstream_advanced`) — never invents reconsideration authority. The sanctioned reversal is
  the existing `/reopen` reversible-commit; only once back in review may a mutation run.
- **Codex exact-head review cycles resolved (fail-before/pass-after each):** blockers 1–6 → P1-A/P1-B atomicity+durability →
  P1-1/P1-2 ownership/source fencing → #4 heartbeat lifecycle (Stage 2A rollback/reconnect, join-before-close, runtime lease) →
  **#5 heartbeat interval default now derives from the runtime-resolved lease** (`engine._resolve_rework_lease_seconds`, read at
  call time by claim/renewal/interval alike; unset `TANAGHOM_REWORK_HEARTBEAT_SECONDS` → `max(1, runtime_lease/4)`). Non-vacuous
  worker-level proof §21: heartbeat env unset, import-time constant pinned to a divergent 120 while runtime lease=3, derived
  interval (1.0s) proven strictly ahead of expiry (old code 30s), generation exceeds lease, induced hb-conn kill reconnects, no
  competing reclaim, exactly one revision + one provenance.
- **Test-only reconciliation (operator-authorized bundle at `be52c32`; no product code):** two pre-existing `api_selftest`
  assertions predated #313 behavior (file last touched at #310; assertions older) and were silently red on a clean re-clone —
  (1) §11 restore-from-v1 reconciled to the governed sequence (assert the #249 `governed_denial` on the approved item → `/reopen`
  → original restore→rework happy-path unchanged); (2) `/rounds/{id}/agent` made **configured-state-driven** so credential/readiness
  drift is never masked — GROQ absent → typed 503 with missing-credential detail and no fabricated reply; key-present live
  validation → 200+reply; this gate never calls a live provider.
- **Exact-head evidence @ `be52c32`** (isolated `tanaghom-gateapi-313` :8015 → wt313, DB `tanaghom_pr313` re-cloned from `pr310` to
  avoid #276/#278 remint pollution, `writer_mode":"stub"` exact-match, workers 1 / retries 0; workbench `/api/runtime` build=`be52c32`):
  ordered so `api_selftest` never overlaps Playwright on the shared DB — `gates.selftest` ALL PASSED (FIRST, clean DB) · governance
  proof incl. non-vacuous §21 ALL PASSED · `tsc --noEmit` 0 · `next build` OK · browser 11/11 (`topic-item-governance` + `read-boundary`)
  · `gates.api_selftest` ALL API CHECKS PASSED (LAST). Additive-only; no live provider call.
- **Residuals (deferred; not this directive):** (a) **provider/capability-matrix readiness** — derive live-provider readiness from
  the governed capability matrix rather than a bare env probe (noted in-line at the reconciled `/agent` assertion); (b) the governed
  temporary writer preference (OpenRouter Scout → Groq Scout → Groq Qwen → deferred `gfws_ollama`) remains unregistered by design —
  host-local Ollama is embeddings-only, the `GROQ_API_KEY` 503 on `/rounds/{id}/agent` is a conversational-agent exclusion, not a
  writer blocker; (c) **#318 audit deferred** — not started. No Stage 3, no V1 modification, retained lane infrastructure untouched.

## 2026-07-16 · #310 + #312 CLOSED (directive:done) — V2 Stage 2A automatic Topic generation + V2 clean cutover
- **PR #311 squash-merged at 2026-07-16T20:27:32Z.** GitHub PR #311 reports immutable `headRefOid`
  `a21df7f9dcf18d1465cebdd926b95932f0ff546a` (the exact reviewed head) and `mergeCommit`
  `607480539856912acfde1b4e53d8cd5a02027a61` — the latter is the **squash result** from that exact reviewed PR head.
  Because it is a squash, `a21df7f` is deliberately **NOT** an ancestor of `6074805` (`git merge-base --is-ancestor`
  correctly reports no ancestry); the reviewed head lives on as the PR head-of-record, not in main's linear history.
  origin/main == `6074805`. Both #310 and #312 CLOSED/COMPLETED, `directive:done`. No deploy. Mac only.
- **V1 reference boundary (#312 §1):** immutable **annotated** tag `v1/reference-2026-07-16-4ea1901` peels to
  `4ea1901a588e826e45497745457671e614a245ea` (Stage 1 COMPLETE tip). Operator-authorized and operator-created; CC
  only recommended the candidate SHA. V1 is reference/demo-only — no new features/compat fixes without a separate
  maintenance directive.
- **#310 (Stage 2A):** Schedule acceptance mints ONE durable canonical `generation_job` (automatic=`queued` +
  post-commit dispatch; manual=`awaiting_trigger`, non-drainable) run by the single canonical runner
  `run_writers.run_stage2a_topic_job` — proactive #268 novelty brief, atomic provenance, lease/heartbeat, bounded
  recovery, exactly-once claim. `entry_mode` (automatic|manual) is a governed versioned trigger-timing choice over
  the SAME job. Read-model resolves `entry_mode` from the immutable job snapshot, never live policy (no historical
  reinterpretation). Additive migration 028 only. AgentRep observe/explain/recommend + audited denial + retry via
  existing binding; V2 workbench live-population read surface.
- **#312 (V2 clean cutover) — what actually changed:** ONE product-code adaptation + a bounded wording reframe:
  - **Fail-closed (`gates/api.py` topic `generate`):** a topic round with NO canonical Stage 2A job now returns a
    governed **409** ("V2 does not execute legacy topic generation") instead of silently falling through to legacy
    `run_topics`. This is the single V2 execution mechanism — no legacy fallthrough. Scripts branch untouched (later slice).
  - **Codex exact-head BLOCK fixed (test-only):** the three new `api_selftest` poll loops now poll THROUGH
    `queued|awaiting_trigger|running` and stop only on terminal `completed|failed|partial` (a `!= running` break let an
    initial `queued` false-pass).
  - **Wording reframe (no behaviour):** manual = a V2-governed authorized trigger-timing choice over the same durable
    job; absent policy = Stage 2A **not provisioned / no generation command available** (retired the "pure Stage 1 /
    V1 Generate preserved" framing) across migration 028, engine acceptance+read-model comments, `api.py` read-model
    docstring, workbench seam+read-model copy, entry-mode proof labels/docstring.
  - **Validation boundary (#312 §4/§5):** the immutable V1 full-suite per-PR merge gate is RETIRED for V2 slices;
    replaced by focused Stage 2A + shared-invariant tests **+ one production-shaped V2 browser flow**. A V1 smoke is
    informational-only.
- **Exact-head evidence @ `a21df7f`** (isolated `tanaghom-gateapi-310` :8014 → wt310, DB `tanaghom_pr310`,
  `writer_mode":"stub"` exact-match, workers 1 / retries 0; workbench rebuilt, `/api/runtime` build=`a21df7f` via
  `TANAGHOM_WORKBENCH_BUILD_SHA`): `gates.selftest` ALL PASSED; `gates.api_selftest` Stage 2A path PASS incl.
  fail-closed 409 + read-model counts 4/14; `proof_stage2a_entry_mode` + `proof_stage2a_manual_trigger` ALL PASSED;
  production-shaped **`generation-surface.spec.ts` 4/4** (real V2 UI → `/gw` → live API → canonical durable job →
  read model → rendered result; fixtures via real acceptance→durable-job, no mocked client state).
- **Model-route clarification (operator, non-blocking):** governed TEMPORARY writer chain = OpenRouter Llama 4 Scout →
  Groq Llama 4 Scout → Groq Qwen3-32B → GFWS Ollama (only via a distinct verified `gfws_ollama` provider). The
  `GROQ_API_KEY` **503 in api_selftest is the conversational-agent endpoint, NOT the Stage 2A writer route** — a
  documented structural exclusion (Stage 2A validated in deterministic stub), never a merge blocker. **VPS/host-local
  Ollama is embeddings-only** (never a chat/writer fallback). **`gfws_ollama` is NOT registered — hop 4 is
  deferred/non-executable** until a separate governed config-generation change + focused proof. No provider was
  substituted and no historical provenance reinterpreted.
- **Residuals / deferred (NOT done here):** GFWS hop-4 `gfws_ollama` registration (separate governed config-gen +
  proof); Stage 2B (topic review/edit/drop/regenerate/bulk/ordering) and Stage 3; the Payload/NocoBase/Directus
  control-plane proof (per #294). No deploy, no live provider, no schema beyond additive 028.
- **Untouched:** dirty canonical checkout; V1 product UI; zero-Topic Stage-1 boundary for non-provisioned rounds
  (now fail-closed rather than legacy-executing).

## 2026-07-16 · #308 CLOSED (directive:done) — V2 Stage 1C adaptive schedule views · STAGE 1 COMPLETE
- **PR #309 squash-merged `93ea3636f2e3de94d88a5c3a4636ca334d869712` at 2026-07-16T11:18:08Z** from reviewed head
  `da5ee99654fb5d950f20f4a9d4e270ea63959ff0` (9 files, +484/−6). CLOSED/COMPLETED, `directive:done`. **This is
  the final Stage 1 slice — the V2 Schedule vertical slice is now COMPLETE.** No deploy. Mac only.
- **What shipped:** the two-level FullCalendar Standard six-view system (Day/Week/Month/List/Adaptive Run Range/
  presentation-only Custom Range) over v7 MIT subpaths already authorized by #304 (daygrid/timegrid/list) — NO
  Premium/Scheduler/resource/timeline, NO AGPL, NO new dependency (lockfile untouched). Level 1 (runs-calendar)
  gained the view toolbar + views + per-scope URL state; Level 2 (run-schedule-workspace — previously a custom
  list with NO calendar) gained a FullCalendar projection of the canonical slots over the run window, event
  identity = canonical `slot_id`, routine label = server `display_code`. Adaptive initial view is DETERMINISTIC
  from `period_len_days` (1→day, 2–7→exact range, longer→month, unplaced→explicit state), never viewport.
- **Bindings worth carrying:**
  - **A view/range is a PROJECTION.** Custom Range is presentation-only BY CONSTRUCTION: #304's read-boundary
    proves V2 navigation issues no upstream request, so a range change has no code path to mutate placement/slot
    day-time/mapping/history. Proved by a DB snapshot unchanged across every view/range change.
  - **Per-scope URL view state** (`v_<scope>` keyed by "runs" or a round_id) — shareable/restorable across
    reload+drill-down+back, and CANNOT leak across runs (each scope reads only its own keys).
  - The one backend change was a read-model EXPOSURE, not schema: `round_detail` already SELECTed `starts_on`
    (#304) but never RETURNED it, so Level 2 saw null and every placed run rendered as unplaced. Now returned
    (ISO string; null = unplaced). Guarded by a new `gates.selftest` assertion.
- **Process lessons:** two failures were purely environmental and correctly NOT counted — the isolated `:8013`
  DB had no runs seeded (empty seam, no toolbar) and V1 had no `node_modules` in the fresh worktree's dashboard
  (V1_URL cross-check specs failed because V1 wasn't serving). Both fixed; suites then fully green. Reinforces:
  a failure against an unseeded DB or a not-running dependency is an environment fault, never a product regression.
- **Validation:** #308 view spec 11/11 zero skips · full V2 Chromium 72/72 zero skips · `gates.selftest` EXIT=0
  (with the round_detail assertion) · concurrency 101/101 · V1 checkpoint EXIT=0 · ONE immutable V1 full suite
  220/4/0 `FULL_EXIT=0` at the exact head (shared `gates/engine.py` changed), via the reversible wt297
  hold/restore. MIT lockfile unchanged.
- **Untouched:** dirty canonical checkout (`8617d95`, 12 modified + 8 untracked); wt297 review lane (`ea97a14`)
  restored; zero-Topic boundary. #308 created no Topic job/row, novelty request, provider call or Topic mutation.
- **NEXT — Stage 2 (not started here):** per #294's ledger and #308's own boundary, the seam is preserved but
  never invoked. The next directive is **Stage 2 — Topic generation and review**: automatic start after Schedule
  approval, #268 proactive novelty retrieval (meaning-based, not wording-based dedup), topic review/edit/drop/
  regenerate/bulk/ordering with stable identity, version lineage to canonical slot/topic. Exit: approved Schedule
  slots deterministically produce the expected topic population, every topic governable without leaving the stage.
  Also deferred to Stage 2 by #294: the Payload/NocoBase/Directus control-plane proof (config/source authoring
  adapter only, never active-run authority).

## 2026-07-16 · #304 + #306 CLOSED (directive:done) — V2 Stage 1 run calendar + governed Pillar/HCS taxonomy contract
- **#304 / PR #305 squash-merged `508c7a3…`? no — #304 via PR #305 `db07a2e6495d1861644e306fbc41d3f60a6a54dd`;
  #306 / PR #307 squash-merged `77bae630b75d29256db8bf61470384ba05c0dd49` at 2026-07-16T09:30:55Z** from head
  `5a7b8aad048aa5fe1bdf86f480a6bff826418f71`. Both CLOSED/COMPLETED, `directive:done`. No deploy. Mac only.
- **#304 (V2 Stage 1):** authoritative absolute run placement (`round.starts_on`, nullable, additive — legacy runs
  render explicitly UNPLACED, `created_at` is never schedule truth), the two-level IA (runs calendar → run-scoped
  schedule route), FullCalendar Standard **v7.0.0** pinned exactly (MIT, zero premium/AGPL/v6), governed slot
  day/time/format revision, drag + keyboard reorder, sticky search/filter/sort, 375/tablet/desktop × LTR/RTL.
  `engine.place_run` reuses #271 authority + #292 lock/token + `_downstream_advanced` freeze + append-only audit.
- **#306 (V2 Stage 1B):** the governed **Pillar/HCS taxonomy revision** contract #304 hard-stopped on. Chosen shape
  (Codex-reconciled Contract A): a **run-local, cursor-neutral per-slot override**, because `hcs_cursor` is a
  per-pillar WATERMARK (not a ledger), `lens_history` is global, neither is round-scoped, and no DB constraint
  enforces no-repeat. Rewriting cursor/lens would let a past run reinterpret future runs; a replan would touch
  untouched slots. So: change one slot, touch nothing cross-run. `pillar_code`+`hcs_id` are an ATOMIC PAIR resolved
  against the run's PINNED methodology generation; lens AND `hook_type` re-resolved read-only from the same pinned
  `methodology_lens.default_hook_type`; `hcs_cursor`/`lens_history` byte-identical, `cycle_no` unchanged; accepted
  override mints one new mapping generation atomically and regenerates the display code; canonical `slot_id` stable.
  **No schema change.**
- **Bindings worth carrying:**
  - **Reusable classification lineage, NOT unique content identity** (operator correction to CC's preflight, which
    had wrongly proposed duplicate rejection): multiple slots may share the same pinned Pillar/HCS — NO uniqueness,
    NO duplicate rejection. Meaning-based Topic dedup is Stage 2.
  - **Category is projection-only:** no canonical Tanaghom category identity exists in the pinned generation, so per
    #306's boundary it stays a derived HCS label with no persistence/catalogue/generation/authority.
  - **Taxonomy WRITE fails closed without a pinned generation** — no live-catalogue fallback on the write path (that
    was P1 #1 in Codex's BLOCK; legacy read/display fallback stays in `_round_slots_ordered` only).
  - **Pin-aware display codes:** `_round_slots_ordered` now resolves from the run's pinned generation, so a later
    catalogue edit cannot re-mint an existing run's human-facing codes.
- **Process lessons (each caught by driving the real surface, not the build):** tsc + `next build` both passed while
  the route crashed on React #31 (`pinned_eligible_formats` is objects, not strings); a green suite EXIT with a
  **skipped** core test is not a pass (A6 keyboard placement was silently skipping); a v6-class-name probe read a
  valid v7 calendar as "renders nothing" (13,971 chars of DOM); the placement authority check **500'd instead of
  deciding** when the route omitted `cfg`; test run-selection must avoid **downstream-frozen** runs or reorder
  specs flake on a correct governed refusal. See [[false-pass-patterns]].
- **Validation topology unchanged:** isolated worktree + off-canonical gate API/DB, then a reversible wt297
  hold/restore (script written BEFORE the hold) for the single immutable V1 full suite at the exact head. Both
  directives ended green: V2 61/61 zero skips, concurrency selftest 101/101, V1 full 220/4/0 `FULL_EXIT=0`.
- **Untouched:** dirty canonical checkout (`8617d95`, 12 modified + 8 untracked); wt297 review lane (`ea97a14`);
  zero-Topic boundary. Groq agent `api_selftest` check remains structurally excluded (non-secret harness, no paid
  call). #304 stayed open until #306 merged; both now closed.

## 2026-07-16 · #297 CLOSED (directive:done) — both frontends off vulnerable Next 15.1.4 onto exact 15.4.11
- **PR #303 squash-merged `c07e4466bd4b130dade624f70f67c96c9ab8344a` at 2026-07-16T03:25:15Z**, at reviewed exact head
  `ea97a14092a06b9651baca87a260ea8d621e13d3` (11 files, +420/−444). Exact **Next 15.4.11** in `dashboard/` and
  `workbench/`, React/ReactDOM held at exact **19.0.0**, `packageManager: pnpm@10.15.1` in both roots, and the V1
  Dockerfile activating that exact version. No deploy. Mac only.
- **Why 15.4.11 is the right target — verified, not assumed:** the Dec 3 advisory fixes 15.4.x at `15.4.8`; the Dec 11
  set — whose first DoS fix was **incomplete**, completed under CVE-2025-67779 — raises the 15.4.x floor to `15.4.10`.
  `15.4.11 >= 15.4.10` and is the tip of its line, so it carries all four CVEs' fixes. React stays at 19.0.0 because
  `next@15.4.11` peers `react: ^19.0.0` AND the advisories' required action is a **Next-only** upgrade (patched Next
  ships the hardened RSC implementation) — holding React is the documented remediation, not a gap.
- **The adversarial preflight found a real hard stop, fixed rather than bypassed:** `dashboard` declared no
  `packageManager`, so the V1 image's `corepack enable` resolved pnpm to **whatever was registry-latest AT BUILD TIME**
  — measured **11.13.1** on `node:22-bookworm-slim`, while `workbench` pinned 10.15.1. Production's frozen-install
  contract drifted with the calendar instead of tracking the committed manifest. Now pinned end-to-end and proven in a
  real Node 22 build from the COMMITTED Dockerfile (`Preparing pnpm@10.15.1…` -> `Done in 11.6s using pnpm v10.15.1`).
  **Lesson: `corepack enable` without a `packageManager` field is not a pin.**
- **Lockfile discipline:** regenerated independently per root with pnpm 10.15.1; `lockfileVersion 9.0` unchanged. The
  ONLY direct dependency that moved in either root is `next`; all other churn is transitive (`sharp 0.33.5 -> 0.34.5`
  plus new `@img/*` platform variants — `sharp` is a direct dep of neither root). No second framework copy;
  react/react-dom resolve to 19.0.0 and nothing else. Frozen installs are byte-stable.
- **Validation at `ea97a14`:** V1 tsc + fresh build; **#152 fresh-build proof** (provenance route 200, zero
  client-reference-manifest failures — `React.lazy` + `Suspense` RETAINED and re-proved on 15.4.11); **V2 explicit
  method closure re-proved live** (HEAD/OPTIONS/PUT/DELETE -> 405, GET -> 200); V2 validate (exact canonical brand
  bytes) + 36 smoke; real Node 22 Docker build; and ONE immutable-head V1 full suite: **220 passed / 4 skipped /
  0 failed**, workers 1, retries 0, stub confirmed by READING `writer_mode` from `/health`.
- **Process lessons worth carrying:**
  - A gate preflight that PRINTS two values without COMPARING them proves nothing. A run was voided because the gate
    API had `DB_NAME=tanaghom_pr297` while the DB container still had `POSTGRES_DB=tanaghom_pr298`; `iam-admin`,
    `iam-login` and `publication` seed via `docker exec … psql -d "$POSTGRES_DB"`, so they wrote to one database while
    the app read another. It looked exactly like a Next 15.4.11 hard stop. The preflight now asserts the two AGREE.
  - Documentation currency is part of the change, not an afterthought: Codex BLOCKed on three stale current-state
    references, and a sweep found three more in the GOVERNING docs (`HANDOFF.md`, `AGENTS.md`, `CLAUDE.md`) that agents
    read first. All six now say #152 was proved ON 15.1.4, both roots pin 15.4.11/19.0.0, `React.lazy` remains the
    retained convention re-proved at 15.4.11, and whether the trap still reproduces there is deliberately UNTESTED.
  - Do not narrate in a governing doc. A sentence claiming the HANDOFF bullet "asserted 15.1.4 for months after it
    stopped being true" was FALSE — 15.1.4 was current until this very PR — and was removed with nothing in its place.
- **RESIDUAL, NOT CLOSED BY THIS PR — historic exposure / credential rotation remains under incident handling.** The
  Dec 3 advisory instructs rotating ALL secrets for any app online and unpatched as of 2025-12-04 13:00 PT;
  CVE-2025-55182 is CVSS 10.0 and was actively exploited, and Tanaghom ran 15.1.4 for ~7 months after that date
  (CVE-2025-55183 also exposes secrets inlined in code within Server Functions). This PR removes the vulnerable runtime
  GOING FORWARD ONLY. No rotation, assessment, or closure was performed here.
- **Log-durability gap (operator action):** this is the FIRST 2026-07-16 entry to reach `main`. The #292 and #299/#301
  closeout briefings were written only into the dirty canonical checkout and remain uncommitted there, so they never
  became durable. Protocol §6 treats this log as authoritative even if a hook wake is missed — which only holds if the
  briefing is committed. Those entries need reconciling from the canonical tree by their owner; CC must not touch it.

## 2026-07-15 · #293 CLOSED (directive:done) — V1 preserved byte-identical; V2 workbench transition lane established (Stage 0)
- **PR #296 squash-merged `e1aabee38153988312e5f2bdf379842be585c6de` at 2026-07-15T12:33:06Z**, at reviewed exact head
  `d9135aa` (after Codex BLOCKed `11db665` on three P1s — all reproduced, fixed, re-validated). Stage 0 of ledger #294,
  from evaluation #279. Branch deleted (remote auto-removed on merge); #293 CLOSED/COMPLETED. Pre-existing dirty docs +
  screenshots + `.ai-orchestrator/` untouched. No deploy, no tag, no client-data mutation. Mac only.
- **What shipped:** `workbench/` — a separate, reversible V2 frontend lane over the **same Tanaghom API authority** —
  plus `docs/v2-transition/README.md` (transition record). **V1 is BYTE-IDENTICAL**: `git diff bd93fda d9135aa --
  dashboard/ gates/ deploy/ .github/ .gitignore db/` → empty; out-of-scope paths → 0. V1 keeps its production
  build/start, env, API routing, runtime identity (#202), `127.0.0.1:3000:3000`, nginx root route, GFWS inputs, and
  `dashboard/pnpm-lock.yaml`. No V1/shared runtime change ⇒ **no full suite required**.
- **Packaging (D1):** `workbench/` is a self-contained pnpm project with its own lockfile + its own
  `pnpm-workspace.yaml` (`allowBuilds` only, **no `packages:` key**) — the existing `dashboard/` convention. **This repo
  is NOT a monorepo; never add a root workspace**: it would relocate `dashboard/pnpm-lock.yaml`, which
  `Dockerfile.dashboard` COPYs by exact path for `pnpm install --frozen-lockfile` → V1 deployment breaks. `#293`'s §2
  ("one authoritative lockfile strategy" + no monorepo conversion + add a separate package) is only satisfiable this way.
- **Read boundary (D2):** V2's seam is **GET-only over a closed allowlist** of endpoints the gate API already leaves
  unguarded — `GET /gw/health`, `/gw/rounds`, `/gw/rounds/{id}` (`gates/api.py:248,692,487`). V2 **signs no principal,
  holds no `REVIEWER_PROXY_SECRET`**, so it cannot become a parallel authority path; Tanaghom still decides at decide
  time (#10). Guarded → 403 · non-allowlisted → 403 · **HEAD/OPTIONS → 405** · other methods → 405 · IAM → 501.
- **TRAP worth carrying (P1.1, Codex-found):** exporting only `GET` does **NOT** close a Next 15 route. Next
  **synthesizes HEAD from GET** (running the handler → real upstream GET) and answers **OPTIONS** itself with
  `Allow: GET, HEAD, OPTIONS`. Reproduced at `11db665`: HEAD /gw/health → **200**, OPTIONS → **204**. CC's
  "structurally impossible" claim had reasoned from the module's source rather than framework behaviour, and its test
  only probed POST/PUT/DELETE. Now `HEAD`/`OPTIONS` are **declared handlers returning 405 + `Allow: GET`**. Any future
  Next route asserting method closure must do the same.
- **TRAP (P1.2):** a preflight that honours `PORT` while `package.json` hard-codes `-p 3001` is a **lie** — the passing
  check is disconnected from the process that starts. Port is now resolved ONLY in `scripts/preflight-port.mjs`;
  `dev`/`start` gate on it and take the port from `--print`. V1's port 3000 refused on every path incl. `--print`.
  Preflight **detects and refuses, never kills** (§6). `e2e/port-contract.spec.ts` locks both ends.
- **Two evidence lanes are now doctrine (P1.3):** induced `page.route(...).fulfill(...)` is valid **deterministic
  regression** evidence but is **NOT** operator-visible acceptance. The real-path lane uses **isolated ephemeral
  non-client** infra — an ephemeral DB from real `db/init/schema.sql` + 25 migrations behind a **REAL gate API on
  :8109**, throwaway V2 on :3002 — proving real empty / real failure / real recovery. Shared api, V1, V2 and the
  `tanaghom` DB untouched (61 rounds throughout); all ephemeral infra torn down and verified gone. Procedure documented
  in the transition record.
- **The real-path lane immediately found a defect the mocks were blind to:** `RuntimeStrip` used one `Promise.all` over
  `/api/runtime` + `/gw/health`; `Promise.all` rejects atomically, so an unreachable api **discarded V2's own successful
  identity read** and the header fell back to the `…` **LOADING** placeholder — misreporting "still loading" for a
  known, final build during an outage. Reads now independent; only `api writer` degrades to `unavailable`. Regression
  added. **Lesson: a mock lane cannot certify truthful-state behaviour it never exercised.**
- **Reproducibility:** `workbench/package.json` pins `packageManager: pnpm@10.15.1` (Codex's lane resolved 11.9.0 and
  aborted replacing `node_modules`). `dashboard/package.json` untouched.
- **Validation @ merged head `d9135aa`:** D6 V1 PR-checkpoint (`npm run test:pr -- e2e/runtime-truth.spec.ts
  e2e/responsive-shell.spec.ts`, cwd `dashboard/`, `DASH_URL=:3000 API_BASE=:8009`) — **exit 0 / 20 passed / 0 skips /
  0 retries / 0 flakes at BOTH baseline `bd93fda` AND head `d9135aa`** (identical code waived neither). V2: brand gate ✅
  (exact canonical bytes), `tsc` ✅, production build ✅, Stage 0 suite **29 passed / 0 failed / 0 skipped**,
  `workers:1`, `retries:0`, no sleeps.
- **Residual / boundaries (NOT discharged):** **#292 = Stage 1** (governed schedule ordering, display-code generations,
  optimistic concurrency). #293 deliberately did **not** pre-empt it — V2 renders canonical `slot_id` verbatim and
  derives **no** display code / **no** ordering; `dashboard/lib/content-id.ts`-style derivation is absent by design.
  **#268 = MANDATORY Stage 2**: proactive bounded history context in the FIRST generation prompt, **retaining**
  post-generation embedding comparison/retry as defence in depth — Stage 0 invoked **no writer, no generation, no client
  run, no content-quality claim**, so nothing here discharges it. Exit gate owned by **@Kholio**; #293 authorised **no**
  promote/retire/abandon/extension, no default-route switch, no automatic sunset. GFWS topology **proposed and
  unexecuted** — any dual-surface deploy needs its own reviewed directive. **D5 tag
  `v1/baseline-2026-07-15-bd93fda` is a PROPOSAL ONLY — not created/pushed/moved.** #187 secret authority (incl. the
  OpenBao reconsideration required by #223) stays in the independent lane.
- **Declared debt:** brand-copy drift (mitigated — `pnpm verify:brand` fails on sha256 drift vs
  `dashboard/public/brand/**`; residual: nothing forces it on a V1-only change) · typography divergence (V2 = system
  stack; §2 forbids bulk-copying V1's vendored fonts) · two lockfiles can drift (both pin Next 15.1.4 / React 19.0.0) ·
  dual-maintenance cost (bounded only by the exit gate) · V2 inherits the **#152** trap (`React.lazy` only, never
  `next/dynamic`).
- **Next order:** **#293 (done) → #292 Stage 1 Schedule → bounded Mobiscroll proof → separate Payload/NocoBase/Directus
  proof**; #268 mandatory at Stage 2.

## 2026-07-15 · #290 CLOSED (directive:done) — evidence pass: BOTH observations UNPROVEN; #285's load hypothesis DISPROVED
- **No code change, no branch, no PR** — the directive's explicit success condition for a trace-only outcome. Tested
  `main` @ `9065da2`; `dashboard/` + `gates/` trees clean. Nothing implemented; #286/#287 not duplicated.
- **`iam-admin:132` and `approval-visibility:6` did NOT reproduce** across two full serial suites. Stronger than
  "unproven": #285's stated cause — *"cumulative-load timeout exceedance"* — is **contradicted by measurement**. Under
  MAXIMUM cumulative load (200+ tests into a 13.4-min serial run) both run at **5–8× margin** under their 20 s budget:
  `iam-admin:132` **2.71 s** (isolation 2.99 s); `approval-visibility:6` **3.97 s** — **FASTER under full load than
  alone** (isolation 5.28 s). Load is demonstrably not reaching them. A 20 s web-first timeout off a ~3 s baseline
  needs a ~7× slowdown, implausible at `workers:1` where nothing competes for the browser; burning the full 20 s is the
  signature of a condition that **never became true**, not one that resolved slowly.
- **Falsified by evidence, not assumption:** (1) RE2E pushed out of a capped "My approvals" list — **no cap**,
  `overview-lens.tsx:148` `.map`s every row; (2) `/me/pending-approvals` slow — **30–470 ms**, 22 rows, **RE2E first**;
  (3) `user_identity` collision between the IAM specs — **distinct issuers** (`localhost:3106` vs `localhost:3108`);
  (4) leaked `next-server` holding :3107/:3109 — **ports free after the spec**, `kill("SIGTERM")` does reclaim them.
- **Class reframed (the substantive finding):** the flake class is **real and suite-wide but does not single out the two
  catalogued tests** — a different, non-overlapping set failed each run, never the two named. Reproduced instances:
  `schedule-and-topic-surface:79` (the **singleton `toast`** showed "Approval saved for R54-D01-AM…" / "Generated 2
  item(s)…" where `/decisions submitted/i` was expected; `5 ×` resolved to the wrong message) and
  `integrity-and-dispositions:96` (90 s timeout; `confirm-commit` resolved but never stable). Signature =
  **overlapping-async / shared-singleton overwrite** — same family as #286's proven `loadRounds` race, NOT timeout
  exceedance. **Therefore `iam-admin:132` / `approval-visibility:6` are most likely survivorship artifacts** — whichever
  test lost a race on the two runs #285 observed. Chasing those two names specifically is likely chasing noise. Not
  fixed here: outside #290's scope (`only` those two tests); hard stop respected.
- **Two disclosures against the executor's own work.** (1) **The first full-suite run was INVALID and is discarded in
  full** — it ran before build-currency was verified: `.next` built **10:33:45**, server up **10:33:53**, both
  **predating the #283 merge** (`95c164a`, 11:06:32) while the DB already carried migration 025 → a pre-#283
  frontend/API against a post-#283 schema (the `CLAUDE.md` stale-serving trap). Its lone failure
  (`production-chain-surface:98`, 49 s, **on the #282/#283 per-token coverage surface**) is **not reported as a
  finding** — unattributable; that test **passed at 8.11 s** on a correct build. Remediated by
  `docker restart tanaghom-gateapi` + `next build` + restart at `9065da2`. (2) **`runtime-truth:39` in run 2 was an
  executor artifact, not a flake** — the restart omitted `TANAGHOM_BUILD_SHA` so `/api/runtime` returned
  `"build":"unknown"` (#202: build identity is server-runtime truth from that env only). **Corrected** — restarted with
  short SHA `9065da2` → `"build":"9065da2"`, `runtime-truth` **9/9**. Excluded from the flake evidence.
- **Validation.** No code changed → **no `tsc`/build/immutable-head gate required and none claimed as a merge gate**;
  production `next build` passed at `9065da2` as part of the stale-build remediation only. All runs `workers:1`,
  `retries:0`, `fullyParallel:false` (config-enforced), stub writer verified by **exact** `"writer_mode":"stub"` match
  before each run, `gates.api_selftest` never overlapping Playwright on the shared DB. Isolation @ `9065da2`:
  `approval-visibility` 1/1, `iam-admin` 4/4, `production-chain-surface` 4/4. **Full suite run 2 @ `9065da2`:
  217 expected / 3 unexpected / 4 skipped**, retries 0 — of the 3, one is the corrected `TANAGHOM_BUILD_SHA` artifact,
  two are the residual class; **both #290 targets passed**. **No green run is claimed as proof**, and a red run
  elsewhere is not claimed as proof about these two tests.
- **Recommended follow-ups (NOT actioned; briefing only):** (1) **retire the two-test framing** — target the *class*
  (overlapping-async/shared-singleton overwrite), not these names; (2) bounded directive for the **singleton `toast`
  assertion surface** (`schedule-and-topic-surface:79` is the reproduced instance) — a shared toast makes every toast
  assertion in the suite race-prone; (3) trace pass for `integrity-and-dispositions:96`; (4) consider a **preflight
  build-currency assertion** for the suite — run 1 shows a stale build can silently produce a plausible-but-FALSE
  failure on a real product surface, which may explain some historical "flakes". #285 stays `directive:blocked` as the
  diagnosis record; its `empty-states:73` root cause remains fixed by #286.
- Mac dev checkout only; no deploy, no host switch, no schema/migration/seed/reset/config/IAM/authority/approval
  change; configuration generations remain append-only and non-destructive; pre-existing dirty docs batch untouched.

## 2026-07-15 · #288 CLOSED (directive:done) — SUPERSEDED, not executed; residual re-filed as #290
- **Nothing was implemented.** #288's Objective was **already met on `main` by #286 / PR #287** (`b0b3ae2`, merged
  2026-07-15T06:15:34Z), so items 1–2 would have duplicated merged code. Per #288's own hard stop ("stop and report
  rather than approximating") + the directive-bus conflict rule, CC **hard-stopped before any code change**, reported,
  and the operator chose **close-as-superseded**. `directive:running`→`directive:done`, #288 closed. No code/schema/
  config/branch/PR change; no deploy; no host switch; the pre-existing dirty docs batch was left untouched.
- **Verified stale premises** (Mac dev checkout `main` @ `1ae5ab3`): (1) #288 Evidence says "`loadRounds` does not [use
  the guard]" — **false at `main`**: `review-context.tsx:528-559` already carries `roundsSeq` + `latest()` (stale
  success AND stale failure discarded; `finally { if (latest()) setRoundsLoading(false) }`), attributed by
  `git log -S "roundsSeq"` to `b0b3ae2` (#286/#287). (2) The deterministic regression already exists —
  `empty-states.spec.ts:102` "overlapping loadRounds: a stale FAILED response cannot overwrite a newer SUCCESSFUL one
  (#286)", promise barrier, **no sleeps**. (3) #288 Dependency "PR #283 remains held" — **void**: PR #283 **MERGED**
  `95c164af` at 2026-07-15T07:06:32Z, #282 closed `directive:done`. The #283 gate needs no evidence from #288.
- **No validation run and none claimed** — there was no change to validate. **No green result is asserted for
  `1ae5ab3`.** Authoritative evidence for this path stays #286's `d418e5e` and #282's `63c9281` (each 220 passed /
  4 skipped / 0 failed; stub writer, `workers:1`, `retries:0`, no API-selftest overlap).
- **Residual re-filed → #290** (`directive:pending`, **NOT approved**; needs GPT review + operator approval): the only
  surviving #288 item — an evidence pass for **`iam-admin:132`** / **`approval-visibility:6`**, still UNRESOLVED /
  trace-only. #285 stays `directive:blocked` as the diagnosis record. #290 carries the hard stops forward and encodes
  the methodological trap explicitly: **a clean full suite is a load-dependent NEGATIVE observation, not proof** — both
  prior clean runs already passed without these flakes recurring, so a green run must never be reported as a fix; an
  explicit "unproven / load-induced" finding is a **success condition** for #290.
- **Flagged for a SEPARATE documentation directive (deliberately not actioned here):** repo notes claiming the client
  surface moved to macOS are **STALE**. Client GFWS runtime = the **Windows Tailscale host GFWS** at `100.119.170.109`,
  served at `https://gfws.taile18f28.ts.net:10000/`; the Mac checkout `/Users/Kay/Dev/tanaghom` is **development only**.
  Do not treat the stale macOS notes as deployment instructions. (Same host as the SDAM/ResourceSpace `base_url` in
  `system_config.example.yaml:409`.) This correction must not ride along with a stability directive.

## 2026-07-15 · #273 CLOSED (directive:done) — companion-system authority-mapping delta after #197 (read-only planning)
- Read-only/planning-only pass: **NO code/schema/migration/runtime/config/secret/credential/deploy/data change,
  no branch, no PR, no merge SHA** (same shape as #197). Deliverable = three issue comments (ACK · mapping delta ·
  **Amendment 1**). Codex review returned **BLOCK** on the first report; the amendment corrected it; GPT then returned
  **APPROVE** (no blocking findings) and the operator accepted. `directive:running`→`directive:done`, #273 closed.
  This briefing commit is the only repository artifact.
- **Central verified fact:** SDAM/ResourceSpace is the **ONLY** companion system with integration code. BrandShield has
  **no seam at all** (docs only; `TRACEABILITY.md:93` "Not integrated"); **AVP + Postiz are stubs that RAISE**
  (`integrations/stubs.py` → `contracts.py:39-42`; `gates/selftest.py:757` *asserts* the Postiz stub raises);
  `integrations.*` all `enabled: false` → `load_registry` returns **empty**. n8n runs as a container but is deliberately
  out of the path (`gates/bot.py:7`, `gates/README.md:17`). Publishing is **manual + first-class, NOT stubbed**
  (`publication.py:6-9`; `execution_source='provider'` exists in `022` but **no code writes it** — `publication.py:325`
  hardcodes `'manual'`). Consequence: BrandShield/AVP/Postiz can only get mode+pattern+unknowns — concrete rows would be
  inference, which the directive forbids.
- **F1 (highest-value finding, NOT fixed):** every SDAM operation is **one-sided**. `gates/sdam.py` contains **zero**
  Tanaghom authorization (no capability/role/assignment/`actors.` call); every `SdamUnauthorized` there is RS's own
  **native** denial. `POST /slots/{slot_id}/sdam/register-edit` gates on `_require_trusted_principal`
  (**HMAC authentication**, `api.py:83-101`) + RW-cred presence + the audit-verified pin — so **any validly-signed
  principal of any kind/role can register a completed edit to the live DAM**. Documented as intentional
  (`api.py:349-350`) ⇒ a **gap vs #238's two-sided rule, not a bug**. The **target** side IS enforced (RS returns bare
  `false` → typed denial, `sdam.py:121-124`).
- **A6 (reshaped the recommendation):** `principal.capabilities` is a **DORMANT seam** — never read by any code, never
  populated (`006_unified_actor_seams.sql:18`). `permissions` is the live ABAC seam but **soft by default**
  (`actors.py:66-70` returns True unless `require_permission`, and `system_config.yaml:307` = `false`). **Role
  membership is the only live authority.** ⇒ #238's "map capability meaning" has **no live capability primitive** →
  **HS-1**, which **blocks** the P1. Not invented.
- **A2/A4/A5:** SDAM authenticates as **two shared workload identities split by operation class** — reader
  `RESOURCESPACE_API_USER` (`api.py:311-313`) / writer `RESOURCESPACE_RW_USER` (`api.py:332-334`, field-scoped F99/F100,
  create-at-Pending −2, no delete); credential resolution is **principal-blind by construction** (no principal arg).
  **No principal↔external-identity mapping exists in any direction outbound** (verified negative grep). `user_identity`
  (`021`) is **inbound** OIDC→principal only, no provider column. Cross-system provenance records a **free-text** actor
  (`023:43,77-78`) with **no FK to `principal`**; `actor_type`'s 2-value CHECK cannot express #197's four kinds.
- **Amendment 1 (the Codex-BLOCK correction — the load-bearing model):** the first report called one artifact both
  "required-present for execution (missing ⇒ deny)" **and** "never grants" — incoherent. Corrected into **three layers**:
  (1) **authority source** (#197, unchanged) `principal`+`principal_role_member` — **confers**; (2) **operation policy**
  (new) — **AUTHORITATIVE, versioned, operator-owned, deny-by-absence, fail-closed**; *constrains, never confers*
  (a **requirement is not a grant**); (3) **mapping/provenance projection** — **derived, non-authoritative, never an
  execution precondition**, and **DEFERRED** out of P1. GPT's "derived read model" note applies to (3) only. Because
  (2)+(5) need no mapping row, deferring the projection costs the slice nothing.
- **The one P1 successor (drafted, NOT authorized):** *"Two-sided authorization for the single live cross-system write"*
  — strictly and **only** `POST /slots/{slot_id}/sdam/register-edit`; **reads out of scope** (the earlier "co-located
  reads" clause was removed per Codex). Adds the operation-policy record + enforcement + workload-reference-**category**
  assertion over the existing env writer ref + fail-closed attributable denial audit. **Schema: REQUIRED** — additive/
  non-destructive/idempotent `026`, operation-policy record **only** (precedents: `023` immutable policy + `policy_version`
  FK; `025` inspect-first guarded ALTERs). **NOT authorized by #273**; needs explicit operator authorization (as #197
  required of #282). ⛔ **Blocked on HS-1.** Not blocked by #21 (#21 later inserts effective-actor resolution *before*
  the check — the #9↔#21 boundary pattern), #187, or OIDC.
- **Open operator decisions:** **HS-1** (authority primitive + baseline default + override boundary) · **D-273-1/D-273-2**
  — **PD-1** ("mode H when the native permission model is unknown") and **PD-2** ("one workload identity per operation
  class") are **PROPOSED defaults only**, pending governed commit; the repo proves a *useful SDAM reader/writer precedent*
  (one instance), **not** authoritative cross-system policy. Neither may be cited as existing policy. · **HS-2/3/4**
  (BrandShield/AVP-MCP/Postiz native permission models absent from this repo → **stop**, propose H meanwhile) ·
  **HS-5/6/7** (SDAM group names live in an external repo & must never become Tanaghom authority · no target-tenant
  mapping · **F3** adjudication). Inherited: **#197 D2/D4/D5 remain open** (D1/D3/D6 consumed by #282).
- **Other findings (recorded, not fixed):** F2 provenance actor not principal-bound · **F3** `audit_log`-as-precondition
  (`sdam.py:449-456` blocks on an audit row's *absence*; `engine.py:4561-4566` gate-commit idempotency) vs #197's "never
  authorization state" — neither decides *authority*, flagged for adjudication · F4 the `sdam:` config block is **inert**
  (no Python reads it; absent from live `system_config.yaml`) · F5 `gates/sdam.py:1-7` still says "READ-ONLY" despite the
  #259 S2 write surface · F6 `provider_key` CHECK is single-valued (`023:40`) · F7 `db/init/schema.sql` has drifted from
  the migration chain (lacks the `025` tables; no ledger/runner, `025:16`).
- GPT's **six** non-blocking recommendations were already satisfied in place and carry forward as standing drafting
  constraints on the P1 successor. #197/#249/#271 semantics **unchanged**; #238 answered without reinterpretation.

## 2026-07-15 · #282 CLOSED (directive:done) — authoritative principal-neutral per-token ANY/ALL approval coverage (#9)
- PR #283 squash-merged to `main` as `95c164af493f1d32dc11fcf791d479d367e567d3` (2026-07-15 07:06:32 UTC),
  operator-authorized at exact head `63c9281` (the rebased head that also includes merged #286). main
  synced, local+remote branch `feat/issue-282-per-token-coverage` deleted, `directive:running`→
  `directive:done`, #282 closed. Implements the #197-frozen #9 contract via D1/D3/D6.
- Migration `025` (additive, non-destructive, idempotent, inspect-first): `gate_snapshot` /
  `gate_snapshot_token` / `gate_snapshot_eligible` (D3 open-time freeze of required tokens + eligible
  effective principals) / `gate_token_coverage`. The two coverage UNIQUE constraints ARE the D1
  distinctness invariants (a token covered once; one principal covers ≤1 token per slot), PLUS composite
  parent-consistency FKs `(gate_id,snapshot_id)`→gate_snapshot and `(snapshot_id,snapshot_token_id)`→
  gate_snapshot_token (a snapshot belongs to its gate, a token to its snapshot). NO backfill; pre-migration
  gates are legacy by the ABSENCE of a snapshot.
- Engine: `open_gate` freezes the snapshot; `decide` records the append-only decision then recomputes
  per-slot coverage as a MAXIMUM bipartite matching (Kuhn) over approving principals × frozen-eligible
  tokens; `resolve`/`get_gate` project ANY/ALL + remaining-per-token from the frozen snapshot + persisted
  coverage, NEVER live membership. Codex P1s folded in: P1.1 `decide` authorizes against frozen
  `gate_snapshot_eligible` (D3); P1.2 `list_pending_approvals` authoritative (frozen eligibility +
  coverage); P1.3 coverage audit outcome from the FULL slot decision set. Legacy gates keep the
  count-based path, marked legacy, never inferred/backfilled/converted; audit is a projection, never
  authorization state. UI: `authoritative`/`legacy` + per-token `coverage` types + a "Legacy approval" marker.
- Rebase onto `main` (to pick up #286's `loadRounds` guard) was CONFLICT-FREE (auto-merged
  `review-context.tsx`; #282 types vs #286 guard in different regions). Validation @ merged head `63c9281`
  (stub, workers:1, retries:0, no api_selftest/Playwright overlap): `gates.coverage_selftest` (coverage
  matrix + P1.1/P1.2/P1.3 + parent-consistency + migration verification), `gates.selftest`,
  `gates.api_selftest` all PASSED; `tsc` clean; `next build` ok; scoped approval-flow E2E green;
  immutable-head `test:full` **220 passed, 4 skipped, 0 failed** (clean).
- Residual (out of #282 scope): **#285 stays `directive:blocked`** (diagnosis record) — its cumulative-load
  flake class (`iam-admin:132`, `approval-visibility:6`, older `empty-states:73`) is NOT fully resolved;
  none recurred in the clean run, but `empty-states:73` flaked once in a loaded scoped run (passes in
  isolation). #286 fixed the confirmed `loadRounds` race; any remaining sensitivity is a future directive.
  **#197 later phases** (delegation/control/AgentRep runtime #21; independence/SoD) stay deferred — #9's
  authoritative coverage foundation is now delivered. No deploy/reset performed.

## 2026-07-15 · #286 CLOSED (directive:done) — monotonic stale-response guard for loadRounds
- PR #287 squash-merged to `main` as `b0b3ae2b5b1eef493c7679058a1f17d0c2d1792c` (2026-07-15 06:15:34 UTC),
  operator-authorized at exact head `d418e5e`. main synced, local branch
  `feat/issue-286-loadrounds-stale-guard` deleted, `directive:running`→`directive:done`, #286 closed.
- Fix (frontend-only, `dashboard/lib/review-context.tsx`): `loadRounds` gained the established `#215`
  monotonic sequence guard (a per-invocation `roundsSeq`; only the LATEST invocation commits
  `rounds`/`roundsLoading`/`roundsError`), so an older FAILED `/gw/rounds` response can no longer
  overwrite a newer SUCCESSFUL one. Mirrors `loadPendingApprovals`/`loadApprovalCatalog`; retry
  behaviour, run-selection, and APIs unchanged. Predates #282; unrelated to its coverage semantics.
- Regression (`e2e/empty-states.spec.ts`, deterministic, NO sleeps): a promise barrier orders the
  responses and a `500` (which `jget` does not retry, unlike an abort) keeps each failed load to one
  request; the older failed retry parks in-flight, the newer successful retry commits no-run, then the
  stale failure releases. FAILED before the guard (`87e44ab` — surface flipped to error), PASSES after
  (`d418e5e`), no retry.
- Validation @ merged head `d418e5e` (stub, workers:1, retries:0): `tsc` clean; `next build` ok; focused
  rounds-loading specs (empty-states 5 + runs-and-generation/review-header/working-view/stage-navigation
  16, no happy-path regression); immutable-head `test:full` **220 passed, 4 skipped, 0 failed** (clean).
- Boundaries: `workers:1`/`retries:0` preserved; no timeout inflation/sleeps/retries/force/weakened
  assertions/skips/execution-order gaming/DB reset/migration/config mutation/deploy. Isolated branch off
  `main`; validated with the local gate API pointed at `main` (no backend change in this slice).
- Related state (unchanged by this directive): **#285 stays `directive:blocked`** (open as the diagnosis
  record) — its catalogued cumulative-load flakes `iam-admin:132` / `approval-visibility:6` remain
  UNRESOLVED (did not recur in the clean run; trace-only, not fixed here). **PR #283 stays HELD at
  `87e44ab`** — untouched (not modified/rebased/merged); resuming it needs a local env rebuild.

## 2026-07-15 · #197 CLOSED (directive:done) — principal / AgentRep-delegation / approval-coverage / provenance contract (read-only planning)
- Read-only architecture/planning pass: NO code/schema/config/runtime/data change, no branch/PR, **no migration
  authorized**. Report comment + planning closeout only. Reconciles the 2026-07-11 operator deferral (which
  forbade *implementation*; this pass preserves the frozen compatibility contract that comment asked to keep).
  `directive:running`→`directive:done`, #197 closed.
- Froze the contract: `principal` is the sole authorization subject (kind ∈ user/agent/**agent_rep**/system;
  the `agent_rep` type + self-ref `owner_id` accountable-human seam already exist — `schema.sql:485-502`).
  Strict identity≠authority≠execution≠provenance separation (`user_identity` / roles+coverage / `actors.py`
  autonomy+hard-floors / `gate_decision`+`audit_log`). Two-sided authorization eval order; delegation invariants
  (attenuation, acyclic/fail-closed, expiry, immediate revocation, no credential delegation, immutable history).
- Central evidence-backed finding (confirms the #196 correction): ALL coverage is distinct-approver **COUNT vs
  quorum, NOT per-token** — `resolve_quorum('all')`=len(tokens); `_decision_rollup` counts distinct approver_ids;
  `decide` authorizes against ANY matching token (`engine.py:116/318/345/4185`). Two principals on the same token
  satisfy ALL while another token stays uncovered.
- #9↔#21 boundary: **#9 owns coverage persistence** keyed by `(required_token, covering_effective_principal)`,
  principal-neutral, no delegation → completable now; **#21** only inserts the effective-actor delegation-resolution
  step BEFORE #9's coverage check, never rewrites #9 rows. Ownership matrix spans #9/#21/IAM/#19/#187/#71.
- Exactly one next directive drafted: *"#9 authoritative ANY/ALL per-token approval-coverage foundation
  (principal-neutral)"* — does NOT implement delegation; **explicitly requires** operator authorization of an
  additive, non-destructive migration (NOT authorized here); blocked on operator decisions **D1** (ALL semantics)
  and **D3** (membership-vs-snapshot), **D6** sequencing.
- Six unresolved operator decisions posted (D1–D6) — stopped rather than invent org policy. All 9 mandatory
  adversarial scenarios walked through the contract; all hard stops honored (no `audit_log`-as-authorization,
  no universal policy DSL, no #19/#187/#71 redesign, no unproven AgentRep runtime claims). Canonical for
  principal-neutral authority; #238 intersects it without changing semantics. No deploy.

## 2026-07-15 · #280 CLOSED (directive:done) — workbench responsive shell, truthful empty states, bilingual a11y
- PR #281 squash-merged to `main` as `25dd831b993f3ae9d6f4f4aac0cd30e71d97cbb1` (2026-07-15 01:06:54 UTC),
  after GPT approval + operator exact-head authorization at tested head `86e7d8c`. main synced to the merge
  commit, local branch `feat/issue-280-responsive-shell-empty-states` deleted, `directive:running`→
  `directive:done`, #280 closed.
- Delivered (approved UI-quality scope only; NO API/lifecycle/authority/route/schema/source-data change):
  ONE shared truthful empty-state contract (no-run / no-items / loading / error) across Overview, Workflow,
  and the grid/calendar/list review surface — replacing blank areas + inconsistent copy; `role=status`,
  reduced-motion-safe, copy never implies generation/approval/publication occurred. Display-only bilingual
  presentation contract (`lib/bilingual.ts` + `<Bilingual>`: deterministic fallback + `dir`/`lang` + truthful
  absence; never parses/mutates/invents source). Rounds load lifecycle OWNED by `loadRounds` (error set on
  any failed attempt, cleared only after success, preserved through failed retries, self-contained/never
  rejects) with a recoverable "Try again". Populated-lens responsive overflow coverage at 375/768/1280.
- Two Codex P1 rounds folded in at fresh exact heads: (1) a failed `/gw/rounds` load must render the shared
  `error` variant, not `no-run` (`3964293`→`39f14c9`); (2) move loading/error ownership into `loadRounds`,
  preserve through failed retries, clear only on success, + refetch-failure coverage (`39f14c9`→`86e7d8c`).
- Fixed a latent pre-existing crash: the calendar interactive-decision block assumed every cell carried
  `decisions`, but #271 planning-only continuity cells do not — guarded to active-gate cells only.
- Final validation @ merged/tested head `86e7d8c` (stub, serial, workers:1, retries:0, no api_selftest/
  Playwright overlap): `tsc` clean; `next build` ok; `gates.selftest` + `gates.api_selftest` ALL PASSED;
  immutable-head `test:full` **219 passed, 4 skipped, 0 failed** on a CLEAN dev DB. (An earlier full run
  showed 3 unrelated mutation-spec flakes under transient system load; all passed in isolation at the same
  head. The operator-approved surgical cleanup then found **0 stray rounds** — run-derived tables already
  empty, governed/config/identity data untouched, no DB reset — and the clean re-run was 0-fail.)
- Residual (out of scope, non-blocking): #20 sticky control bar and #16 filter/search stay deferred to their
  own issues; bilingual source-model schema + load-error states for non-rounds data sources are future
  directives. No deploy performed.

## 2026-07-14 · #271 CLOSED (directive:done) — run planning + calendar continuity + governed schedule revision (on D1)
- PR #278 squash-merged to `main` as `ce7c74c1e8ab9bf09396591f1fdd3a11ca4a1977` at exact authorized head
  `ccc243528f3ac47e5eb0c7109b1340a2856cb0a9` (2026-07-14 17:38:51 UTC). main synced to the merge commit,
  local branch `feat/issue-271-schedule-revision-on-d1` deleted, `directive:running`→`directive:done`,
  #271 closed. Three Codex P1 review rounds folded in (b4ac005 → ccc2435), each re-validated at a fresh
  exact head before the next.
- Delivered (approved scope only): arbitrary operator `format_mix` via the merged D1 baseline-eligibility
  policy + immutable `round_policy_snapshot` (consumed, not duplicated); calendar continuity
  (`GET /rounds/{id}` `round_detail` — full slot set + truthful lifecycle counts + pinned snapshot);
  governed single-slot Schedule revision (`POST /slots/{id}/schedule-revision` — day/time/framework
  within the pinned D1 policy/topic guidance, day bounded to `1..period_len_days`, returns only that slot
  to RESERVED, existing reviewer authority only); pre-approval run-level mix revision
  (`POST /rounds/{id}/format-mix`, exact-total gating, fail-closed once any slot is committed).
- Supersedes PR #274 (closed unmerged); #275 stays closed (catalogue lifecycle is NOT the eligibility
  mechanism — D1 `baseline_eligibility_policy` is). No IAM, generic config UI, catalogue lifecycle
  mutation, fixed ratios/default allocation, provider governance, or deployment.
- Final validation @ merged head `ccc2435` (stub, serial, workers:1, retries:0, no api_selftest/Playwright
  overlap): `gates.selftest` §21 + full ALL PASSED; `gates.api_selftest` ALL API CHECKS PASSED; PR
  checkpoint `test:pr` 15 passed; immutable-head `test:full` **208 passed, 4 skipped, 0 failed**.
- Residual (out of scope, non-blocking): a slot already generating content must be reopened before a
  schedule revision (#51 deferred, no cascade); governed baseline-policy maintenance/refresh remains a
  separate directive. No deploy performed.

## 2026-07-14 · #271 / PR #278 — Codex P1 (calendar-continuity day bound) applied, new head `ccc2435`
- Codex P1 @ `b4ac005`: `revise_schedule_slot` accepted any positive `day`, unbounded by the run's
  `period_len_days`. The calendar renders only days `1..period_len_days`, so a revision to e.g. day 999
  kept the canonical slot but dropped it off the calendar — a continuity violation. Bounded fix, new
  head `ccc2435`, HELD at the merge gate.
- **Engine (`gates/engine.py`).** `revise_schedule_slot` now joins `round.period_len_days` and rejects
  any `day > period` with a governed `GateError` (→ 400). Writer's accepted domain re-coupled to the
  reader's rendered domain; in-period revisions unchanged.
- **UI (`schedule-revision-control.tsx`).** The control takes `maxDay = roundInfo.period_len_days`; the
  day input is `min=1 max=period` and clamps on change. Caller `review-surface.tsx` passes it. Server
  enforcement remains authoritative.
- **Regression.** `gates/selftest.py` §21 proves an out-of-period revision (`day:999` on a 2-day run) is
  rejected AND every canonical slot stays on the calendar (`1..period`). `run-planning-271.spec.ts`
  asserts the revise-day input's `max` equals the run's period.
- **Also in this head — test-only flake fix.** `sdam-readiness.spec.ts:66` (unrelated #250 surface)
  measured 375px document overflow the instant after `setViewportSize`, catching a mid-reflow frame
  under full-suite load (a transient +16px; passes in isolation, passed at `b4ac005`). Applied the same
  deterministic `expect.poll` settle already used in `run-planning-271` — web-first polling, NOT a test
  retry (config stays `retries:0`). Operator authorized a one-time scoped run-derived DB clear
  (backup-first) to rule out the badge-width accumulation theory; the failure reproduced on a clean DB,
  which is what identified it as a reflow flake rather than accumulation.
- Validation @ `ccc2435` (stub, serial, workers:1, retries:0, no api_selftest/Playwright overlap):
  `gates.selftest` §21 (+2 day-bound checks) + full ALL PASSED; `gates.api_selftest` ALL API CHECKS
  PASSED; PR checkpoint `test:pr` 15 passed; immutable-head `test:full` **208 passed, 4 skipped, 0
  failed**. New head reopens Codex/GPT review on PR #278. No self-merge, no deploy.

## 2026-07-14 · #271 / PR #278 — Codex P1 amendment applied, gate reopened at new head `b4ac005`
- Three Codex P1 gaps on PR #278 (@ `a4a7dd8`) resolved inside #271's approved API/UI scope; new head
  `b4ac005`, still HELD at the merge gate.
- **P1a pinned-policy determinism (`gates/engine.py`).** `_pinned_policy_eligible[_names]` now branches on
  the PRESENCE of a `round_policy_snapshot`, not the SUCCESS of resolving it: a snapshotted run whose
  pinned policy is invalid — missing policy row, empty `eligible_version_ids`, or ANY pinned `version_id`
  that no longer resolves (reminted) — raises `GateError` and fails closed. The current-policy fallback is
  reserved for a genuinely legacy run with NO snapshot. Fixes the old fail-open fallthrough where a
  zero-name pinned result silently adopted the current policy.
- **P1b full-eligibility revision UI.** `round_detail` now returns `pinned_eligible_formats` (the complete
  pinned set incl. zero-count frameworks, each with `framework_id`); read-model resilience catches
  `GateError` → empty set (calendar still renders) while mutations stay fail-closed. Dashboard
  `ScheduleRevisionControl` is fed `r.roundPinned` instead of `roundSlots.map(s=>s.format)`, so a
  pinned-eligible framework allocated zero at planning is now selectable (server enforcement retained).
- **P1c run-mix planning control.** New `dashboard/components/review/run-mix-control.tsx` on the Schedule
  surface invokes the EXISTING `POST /rounds/{id}/format-mix` with exact-total gating + truthful
  fail-closed feedback once any slot is committed. New ctx `roundPinned`/`roundMix`/`reviseRunMix` in
  `review-context.tsx`. No new endpoint/authority/policy mutation.
- Regression: `gates/selftest.py` §21 adds invalid-pinned-policy fail-closed (no current-policy fallback;
  read model empty-set + continuity), full pinned-set exposure, and a zero-count pinned framework as a
  valid revision target. `dashboard/e2e/run-planning-271.spec.ts` adds the zero-count revision proof + the
  run-mix planning-surface flow (both responsive to 375px).
- Validation @ `b4ac005` (stub, serial, workers:1, retries:0, no api_selftest/Playwright overlap):
  `gates.selftest` §21 + full ALL PASSED; `gates.api_selftest` ALL API CHECKS PASSED; PR checkpoint
  `test:pr` (run-planning-271 + schedule-and-topic-surface + runs-and-generation + framework-on-cards)
  15 passed; immutable-head `test:full` **208 passed, 4 skipped**.
- State: new head reopens Codex/GPT review on PR #278. No self-merge, no deploy.

## 2026-07-14 · #271 REWORKED ONTO D1 — PR #278 opened at gate; #274 & #275 closed/superseded
- **#275 closed unmerged** (catalogue-lifecycle config PR): catalogue lifecycle is NOT the
  eligibility mechanism — D1's `baseline_eligibility_policy` + governed `seed_source` selection is.
  No merge/rebase/deploy.
- **#274 closed unmerged, superseded by PR #278.** #271 was reworked onto current `main` so it
  CONSUMES the merged D1 seam (baseline-eligibility policy + immutable `round_policy_snapshot`)
  instead of #274's own duplicated format_mix/planner/snapshot (which also depended on the
  now-closed #275). #271's approved intent carried forward unchanged; no scope added.
- **PR #278 (head `a4a7dd8`, label `agent:cc`), HELD at the merge gate.** #271's unique scope only:
  - Calendar continuity — `GET /rounds/{id}` (`round_detail`) read model returns the COMPLETE
    planned slot set + truthful per-status lifecycle counts + the pinned D1 snapshot; the calendar
    keeps every positional cell after Schedule approval with its lifecycle status (not just the
    active-review subset).
  - Governed single-slot Schedule revision (`POST /slots/{id}/schedule-revision`) — one slot's
    day / time / framework (limited to the run's PINNED D1 policy via `round_policy_snapshot →
    baseline_eligibility_policy`, never `content_format.active`) / topic guidance; returns ONLY that
    slot to Schedule review (→ RESERVED), canonical id + append-only audit lineage preserved, reuses
    the EXISTING reviewer authority (`stage_approval_contract("schedule_review")`) only.
  - Pre-approval run-mix reconcile (`POST /rounds/{id}/format-mix`) — uncommitted RESERVED slots
    only, **fail-closed once any slot is committed**.
- Boundaries honored: no IAM/delegation, generic config UI, catalogue lifecycle mutation, fixed
  ratios/default allocation, provider/integration governance, or deployment. Dashboard changes limited
  to calendar continuity + the per-slot revision control.
- Files: `gates/engine.py` (`round_detail`, `revise_schedule_slot`, `revise_run_mix`,
  `_pinned_policy_eligible_names`, `_require_schedule_authority`, `_even_spread`), `gates/api.py`
  (3 endpoints), `gates/selftest.py` §21 (delta-based audit check; hardened §20 `_wipe276` to delete
  dependent `round_policy_snapshot` rows before the policy delete), `dashboard/lib/review-context.tsx`
  (`RoundSlot`, `roundSlots`, `loadRoundSlots`, `reviseSchedule`), `dashboard/components/review/`
  (`review-surface.tsx` calendar-continuity merge, new `schedule-revision-control.tsx`),
  `dashboard/e2e/run-planning-271.spec.ts`.
- Validation @ `a4a7dd8` (stub, serial, workers:1, retries:0, no api_selftest/Playwright overlap):
  engine `gates.selftest` §21 + full ALL PASSED; `gates.api_selftest` + `format_config_selftest`
  ALL PASSED; PR checkpoint `test:pr` (tsc + build + #271 & affected specs) 14 passed; immutable-head
  `test:full` **207 passed, 4 skipped**.
- State: GPT/Codex review reopens on PR #278 at `a4a7dd8` (patch/re-review resets the gate).
  No self-merge, no deploy. #271 issue comment posted with the same evidence.

## 2026-07-14 · #276 CLOSED (directive:done) — versioned baseline eligibility policy + immutable round snapshot (D1)
- PR #277 merged as squash `0216358` (final head `e825110`, two Codex P1-review rounds folded in);
  main synced, branches deleted, #276 closed. Implements D1 from audit #256 — unblocks #271 without
  catalogue archival as an eligibility proxy.
- Migration `024` (idempotent/inspect-first, no ledger): `baseline_eligibility_policy` (versioned
  generations, one-`current`-per-scope partial-unique index, `superseded_by`, deterministic
  supersession, append-only generations) + `round_policy_snapshot` (append-only, UPDATE-immutable
  trigger, round FK cascade). No `content_format` lifecycle change; no Pic + Caption archival.
- Engine (`gates/engine.py`): `ensure_baseline_policy` create-only seed of gen 1 from the AUTHORITATIVE
  GOVERNED selection — `content_format_version`s marked `seed_source=client_framework_bootstrap` (the
  three client frameworks; EXCLUDES `legacy_carry_forward`/Pic + Caption; INDEPENDENT of
  `content_format.active`; hard-stop if none). `current_baseline_policy` fail-closed on zero/ambiguous;
  `resolve_run_eligibility` (the read path #271 consumes) FAILS CLOSED if any pinned version no longer
  resolves (invalidated policy); `supersede_baseline_policy` (governed change, no new authority/UI);
  `pin_round_snapshot`/`round_snapshot`. `reset_content_format_registry` NEVER deletes/replaces/recreates
  policy generations (Codex P1) — a governed policy maintenance/refresh model is out of scope.
- Planner: eligibility resolves from the baseline policy; an exact `format_mix` is REQUIRED (Codex P1 —
  no `weekly_count`/default fallback; no-mix rejected); every run pins the immutable snapshot
  (policy gen + selected version IDs + exact mix + methodology/workflow versions; provider/model
  attribution excluded). API: `GET /baseline-eligibility`, required `format_mix` on `POST /rounds` (422),
  `GET /rounds/{id}/policy-snapshot`; 409 fail-closed. Dashboard: new-run dialog carries the required
  `format_mix` only (strictly-necessary create-contract change; #271 keeps calendar/revision UX).
- Evidence at `e825110`: selftest §20 (15 checks) + api_selftest #276 + format_config ALL PASSED;
  migration idempotent; `test:pr` green; immutable-head `test:full` 205/4/0.
- **NEXT: #271 must be reworked/rebased (PR #274) onto this seam** — consume `resolve_run_eligibility` +
  `round_policy_snapshot`, drop the audit_log snapshot approach and any #275 dependency. **PR #275 stays
  unmerged/superseded.** Telegram publish-role guard (#256 D2) is a separate future directive.

## 2026-07-14 · config-generation guardrail (docs) MERGED — PR #272 squash `b16275b`
- Documentation-only guardrail formalized across `AGENTS.md`, `CLAUDE.md`, and
  `docs/directive-bus/README.md` (codex-authored branch `codex/config-generation-guardrail`, final
  head `046d762`). No product/runtime/schema/code change. Main synced, worktree + branches removed.
- Establishes the mandatory cross-generation policy guardrail: product policy is dynamic only across
  GOVERNED configuration generations (methodology, framework/catalogue, model-route, roles,
  workflow/approval, integration selection) — baseline defaults, authorized override, AI
  recommend/human-commit boundary, per-run/action pinned policy/version snapshot, audit provenance,
  runtime/secret/topology stays file/env, and trial = ephemeral generated data + non-production
  topology only (never a separate product model). README `### Required distinction` gives the 6-point
  checklist every directive touching a mutable product setting must state.
- **New normative Initialization rule (applies to EVERY governed policy/configuration generation, not
  only trial):** "Bootstrap, seed, reset, and migration initialization operations must never overwrite
  existing operator-owned configuration. They may create missing baseline records only; reruns must be
  idempotent and non-destructive." Present verbatim in all three docs (README dedicated subsection;
  CLAUDE.md item 7; AGENTS.md guardrail bullet). Directly binds the loader/`/content-formats/reset`
  seed-sync behaviour touched by #269 and any future migration/bootstrap path.

## 2026-07-14 · #265 CLOSED (directive:done) — generated-slot ↔ review-gate convergence merged
- PR #267 merged as squash `b90728c` (final candidate head `1c3d161`); main synced, branches
  deleted, #265 closed. Live `R1` 6-vs-2 heals via reconcile-on-read once deployed — no manual repair.
- Engine (`gates/engine.py`): `_generation_pending` server-authoritative predicate (writer-input
  rows + in-flight job registry, never row counts); `GateNotReady` fail-closed holds on
  open/read/decide/resolve (API 409, never 404); `reconcile_gate_targets` atomic append-only
  reconcile on reuse and before EVERY gate use, idempotent `gate_targets_reconciled` audit
  (prior/added/resulting counts), prior decisions + `decided_at` untouched; stage_state generation
  DOMINANCE (no gate exposure mid-generation, truthful two-sided counts, held-gate warning —
  surfaced in dashboard `stage-action`); first-open serialized per round+stage via
  `pg_advisory_xact_lock` (Codex P1) and a mid-read `GateNotReady` re-snapshots into the truthful
  generate advisory instead of escaping a READ (Codex P1, was 404).
- Evidence at `1c3d161`: selftest §19 (incl. two-connection FIRST-open race + deterministic
  two-phase `find_running` held-read regression) + api_selftest 0b ALL PASSED; `test:pr` 33
  passed; immutable-head `test:full` 205/4/0 (6.7m), zero retries, stub-verified, no
  api_selftest overlap.
- Ops notes: gate API container remains STUB (`TANAGHOM_WRITER_STUB=1`, staged pre-session) —
  restore live writer before real runs (operator lane). Suite-state trap discovered: accumulated
  planner-spec rounds push global pending approvals to 3 digits → header badge ~16px wider →
  `sdam-readiness` 375px zero-overflow fails; interim = run-derived clear (backups in
  `~/Dev/tanaghom-db-backups/`), a scoped cleanup script is a candidate directive. Also
  re-confirmed: local `TANAGHOM_BUILD_SHA` must be the SHORT sha (full 40-char wraps the header
  at ≤820px and fails 12 viewport specs).

## 2026-07-14 · #263 CLOSED (directive:done) — GPT P1 wrapper repair merged, tiered-validation contract live
- PR #266 merged as squash `2ad59fe`; candidate head `53da4c4` (all-tiers-green SHA) squashed in.
  Main synced to `2ad59fe`, local branch deleted, `directive:running` → `directive:done`, #263 closed.
- GPT P1 fixed: `test:spec`/`test:pr` previously ran a bare `playwright test`, so a no-spec
  invocation silently ran the FULL suite. Both now route through `dashboard/e2e/run-affected.mjs`,
  a checked wrapper that requires ≥1 positional `*.spec.ts` and exits non-zero on empty/option-only
  input (incl. option VALUES like `--grep foo`); spec paths + flags pass through unchanged.
  `test:full` stays the unfiltered full suite by design. Serial/workers:1/retries:0 remain in
  playwright.config — wrapper never overrides. Verified on merged main: empty invocation → exit 2.
- Re-run tier evidence bound to `53da4c4` (stub writer, exact `"writer_mode":"stub"`, 0 retries, no
  api_selftest overlap): inner loop test:spec responsive-shell → 8 passed scoped to 1 file; PR
  test:pr → tsc + next build + 8 passed; IMMUTABLE HEAD test:full → 202 passed / 4 skipped / 0
  failed (7.1m), matching the cd57cc7 baseline (behaviour-neutral for product). Docs/tooling only —
  no app/workflow/schema/provider/live-writer change; #259/S2 untouched.

## 2026-07-13 · S2 directive DRAFTED as #259 (pending gate) — proceeding from closed #258 evidence
- Operator instructed proceed-with-no-cleanup → writer principal + proof fixtures RETAINED (U1 =
  provisioned). Executor drafted #259 "S2 completed-edit SDAM registration adapter" at
  `directive:pending` (the #234→#244 precedent): register the S1-pinned approved master edit as a
  new type-3 RS resource at Pending −2 (field 99 = canonical asset_id, field 100 = g1:registered
  token), bind via EXISTING create_binding + observe_readiness (expect not_ready_pending),
  explicit governed trigger endpoint (no gate/state-machine change), idempotent per
  (asset_id,version), RS-failure-before-binding leaves zero Tanaghom state. Boundaries: no
  publisher/AVP/analytics/S3-projection/schema. Requires GPT review + operator approval before
  execution — NOT started.

## 2026-07-13 · #258 addendum — operator-staged S2a WRITE PROOF executed, all cells VERIFIED
- One-resource reversible proof with the staged `tanaghom_sdam_trial_writer` (group 11, 64-char key
  re-staged after a truthful signature block; lengths-only disclosure): create_resource(type 3) →
  resource 9 at Pending −2 (normal-mode contribute prediction CONFIRMED — governed publish step
  exists) → field 99 uuid + field 100 `g1:proof-258` writes allowed (F99/F100 grants) → byte-exact
  verify via the READ principal (an initial token-absent reading was a probe truncation, corrected)
  → DENIALS proven: not-owned update_field(res6) false + unmutated; delete_resource(own) false.
  Fixtures res6 (SDAM252) + res8 (ACCEPT-254) byte-exact intact.
- U1 + U3 now LIVE-PROVEN (U2 was doc-decided) → S2 registration-adapter design inputs fully
  evidence-backed. Operator-lane cleanup pending: delete resource 9, retire/retain the writer
  identity + rs_rw.env (retain = U1 provisioned for S2), synchronous reindex 99+100 post-delete.

## 2026-07-13 · #263 tiered Playwright validation — PR #266 OPEN at merge gate (head `cd57cc7`)
- Bounded scripts/config/docs only (no app/workflow/schema/provider/live-writer change; #259/S2
  untouched): three dashboard scripts — test:spec (inner loop, affected spec[s]), test:pr (PR
  checkpoint: tsc --noEmit && next build && playwright over named specs), test:full (immutable head
  full Chromium, stub) — plus the one validation-tier contract in CLAUDE.md + directive-bus README,
  and a playwright.config comment anchoring zero-retry/workers:1/fullyParallel:false.
- Tier evidence (all zero-retry, serial, stub, no api_selftest overlap): inner loop test:spec on
  responsive-shell → 8 passed ALONE (no unrelated specs); PR test:pr → tsc+build+spec 8 passed;
  IMMUTABLE HEAD test:full at exact SHA cd57cc7 (unchanged, no post-run patch) → 202 passed / 4
  skipped / 0 failed (4 skipped = stub-only SDAM tests, baseline). Existing full-suite command
  unchanged and passing.
- Contract: any post-review patch/rebase/base-merge/SHA change invalidates the full-suite result
  and requires a fresh zero-retry full run at the new head before merge.
- **Gate: PR #266 HELD (Codex + GPT + exact-head operator).** #263 stays directive:running.

## 2026-07-13 · #259 S2 completed-edit registration — CLOSED (PR #260 merged as `63596ef`)
- Operator merged PR #260 (squash `63596ef4336c912a900b155fd38daaa47752135d`, 2026-07-13T18:54:54Z)
  from reviewed head `d4fde9f` (all recovery findings + the advanced-trail register-affordance P1
  resolved; Codex+GPT+operator passed). Closeout: main synced, branch deleted, relabeled done, CLOSED.
- On main: phase-audited convergent completed-edit registration adapter (register S1-pinned approved
  master edit as versioned SDAM resource at Pending -2; field99 uuid, field100 g1:registered token);
  deterministic recovery for all partial-failure/crash sequences, fail-closed unreconciled/ambiguous,
  typed retryable Phase-D; governed POST /slots/{id}/sdam/register-edit + least-privilege writer
  (env-name, 503 unconfigured); register + retry-projection affordances on active Edit cards AND the
  advanced trail (server pin+principal). Env-gated TANAGHOM_SDAM_STUB test seam (default off, /health).
- RESIDUALS: (1) LIVE one-item S2 trial proof — the one deferred deliverable; needs merged code on
  STITCH-VPS vs GFWS with the retained #258 writer (routine main deploy) — recommend post-merge
  acceptance per #250->#254; operator call. (2) S3 projection emitter / S4+S4a Postiz / S5 analytics
  = future slices (#251). (3) publication.py newest-across-variants intake -> S4 alignment.

## 2026-07-13 · #259 S2 P1 patch — PR #260 head now `d4fde9f` (gate reset per #188)
- Codex review at rebased 61e40f9 found a P1 lifecycle/UI gap: a normal single-item Edit approval
  produces the S1 pin and CLOSES/advances the gate, moving the item into the durable advanced trail
  — but that trail's SdamReadiness left canRegister=false, so the governed register action vanished
  exactly when the pin made it eligible.
- Fix (UI only, no S2 state-machine/endpoint change): the Edit advanced-trail row now passes
  canRegister = (edit stage && canDecideGate). canDecideGate is true once the approving gate closes,
  so an authorized session keeps the affordance; the server re-checks S1 pin + trusted principal.
- Proof: real post-approval e2e (approve master edit -> advances to trail -> invoke register from
  trail with ORDINARY click -> truthful 'Registered — resource' + persisted binding after reload) at
  1280px & 375px (stub-on). Stub-OFF full suite 202 passed/4 skipped; tsc/build clean; live restored.
- Live one-item trial proof still DEFERRED (operator call).
- **Gate: PR #260 HELD for fresh Codex + GPT + exact-head operator review of `d4fde9f`.**

## 2026-07-13 · #261 CLOSED (merged `3e477bd`) + #260 rebased onto repaired shell (head `61e40f9`)
- #261 responsive-shell repair merged as `3e477bd` from reviewed head `efc8da7` (Codex+GPT+operator).
  Closeout: main synced, branch deleted, relabeled done, issue CLOSED. On main: sticky display
  chrome pointer-transparent + live --review-sticky-h scroll-padding budget + xl workspace fill;
  responsive-shell.spec.ts 8/8 at 375/768/1280/1920 (Edit+Distribution), ordinary click().
- #260/#259 REBASED onto current main (clean 4-commit replay; S2 code byte-identical to reviewed
  26dc422). The one shell-dependent test switched: the 375px SDAM projection retry now converges via
  an ORDINARY click() on the repaired shell — dispatchEvent workaround removed; no bypass remains in
  any S2 test. New head `61e40f9`, force-pushed. PR #260 merge gate reopened.
- Validation at 61e40f9: stub-ON retry-click converges 375px+1280px (ordinary click); stub-OFF
  edit-pin(503)+responsive-shell pass; full suite 202 passed/2 skipped; tsc/build clean; live restored.
- Deferred (unchanged): the live one-item S2 trial proof (needs VPS branch deploy — operator call).
- **Gate: PR #260 HELD at Codex+GPT+exact-head operator on `61e40f9`.** #259 stays directive:running.

## 2026-07-13 · #261 responsive-shell repair — PR #262 OPEN at merge gate (head `efc8da7`)
- Root cause of the sticky/header intercepting card+control interaction: the sticky review control
  region's display chrome sat in a full-width pointer-events-auto band. Fix (presentation only, no
  sticky disabled / no overflow masked): display chrome pointer-transparent + interactive leaves
  re-enable pointer events; --review-sticky-h (live ResizeObserver height) drives
  scroll-padding-top = min(h+0.75rem, 40vh) on review-main; xl list workspace fills (no 1920 dead
  gutter), sticky inset tracks the padding.
- Reusable e2e responsive-shell.spec.ts: 375/768/1280/1920 × Edit + Distribution (8/8) — overflow
  ≤ 0, workspace gap < 25% at ≥1280, ordinary click() lands on controls under the sticky header
  (NO force/dispatchEvent/coordinate/CSS/pointer-event bypass). tsc/build clean; full suite 199
  passed (stub). An earlier LIVE-writer run's only 4 failures were the #179/#184 generation/SHA
  trap (not this change); live restored.
- Documented #20/#136 deviations: xl workspace widen (reassessed #136 budget vs the 1920 dead-gutter
  regression) + sticky pointer-events refinement.
- Files: app-shell.tsx, review-surface.tsx, responsive-shell.spec.ts. Changed files list on the PR.
- **Gate: PR #262 HELD (Codex + GPT + exact-head operator).** #261 stays directive:running.
  #259/#260 KEPT HELD, S2 untouched; post-merge, #260 must rebase onto the repaired shell and
  switch its 375px SDAM retry proof to an ordinary click() before its gate reopens.

## 2026-07-13 · #259 S2 test patch — PR #260 head now `26dc422` (gate reset per #188)
- Codex follow-up on `57568f7`: the browser tests proved pending + reload-stability but never
  CLICKED the retry (used a DB shortcut). Added a bounded env-gated in-memory SDAM stub
  (sdam.StubRS + TANAGHOM_SDAM_STUB, default OFF, surfaced in /health as sdam_stub; mirrors
  TANAGHOM_WRITER_STUB) so the governed action drives end-to-end without a live provider. New e2e
  (stub ON): seeds a realistic projection-pending fixture (S1 pin + binding + registered audit —
  the missing pin was an early 409), CLICKS Retry-projection, asserts pending clears reload-stably
  with exactly one binding (Phase D only) at 1280px & 375px (click dispatched directly — the
  pre-existing sticky header intercepts pointer hit-testing at narrow widths). Skip-guards: the
  503-unconfigured test skips when stub on, the click-convergence tests skip when off — both truths
  covered, no env conflict; pure server-read-model tests retained.
- Validation at 26dc422: stub-OFF full suite 194 passed/2 skipped + api_selftest green; stub-ON
  edit-pin retry-click converges both widths; endpoint directly verified (POST 200 written, one
  binding). tsc/build clean, live writer restored.
- Live one-item trial proof still DEFERRED (unchanged operator decision).
- **Gate: PR #260 HELD for fresh Codex + GPT + exact-head operator review of `26dc422`.**

## 2026-07-13 · #259 S2 review follow-up — PR #260 head now `57568f7` (gate reset per #188)
- Codex follow-up on `822e560`: the typed projection-pending state wasn't reload-stable/actionable,
  and the docstring contradicted the code. BOTH patched: projection_pending is now derived in
  list_slot_bindings from pure audit truth (sdam_edit_registered ∧ ¬sdam_edit_projection_written
  for the binding) — server-observable, reload-stable, no live read; the bound card renders a
  persistent pending badge + governed Retry-projection action (same convergent endpoint, Phase D
  only). Docstring corrected: lost-create-response -> retry STOPs unreconciled_intent (fail-closed),
  bounded orphan residual, never a duplicate binding.
- Proofs: sdam_selftest +2 (derives True / clears after projection-only retry); edit-pin e2e +2
  (pending action rendered + reload-stable + clears after convergence, 1280px & 375px). Baseline:
  selftests + api_selftest green (stub health verified before run — the 2 transient failures seen
  mid-review were a live-writer run, corrected), tsc/build clean, Playwright 194/194 zero retries.
- Live one-item trial proof still DEFERRED (unchanged operator decision).
- **Gate: PR #260 HELD for fresh Codex + GPT + exact-head operator review of `57568f7`.**

## 2026-07-13 · #259 S2 review patches — PR #260 head now `822e560` (gate reset per #188)
- Codex review of `b1d833f` found 2 P1 items — BOTH patched: (P1a) fresh-vs-pre-existing-intent
  gate before Phase A — only a fresh call may create-on-zero; a prior intent with no created-ref
  recovers via resolve_unique and STOPs fail-closed on zero, so a crash-after-intent-before-create
  can never blind-create (recovery-1e proof: STOP unreconciled_intent, zero create; plus recovery-1d
  create-then-field99-fail convergence + documented lost-response residual). (P1b) Phase D is now a
  TYPED per-phase outcome (_finish_projection): binding-exists + field-100 failure returns
  {registered, projection_status: pending, retryable} — API 200 not 5xx, refusals bounded 409 code
  with no detail, UI renders projection-pending truth. Proven at adapter + in-process API (TestClient).
- Validation at `822e560`: sdam_selftest ALL (S2 = 16 checks) · selftest ALL · api_selftest ALL
  (stub verified, live restored) · tsc/build clean · Playwright 192/192 zero retries.
- Live one-item trial proof still DEFERRED (unchanged operator decision on the PR).
- **Gate: PR #260 HELD for fresh Codex + GPT + exact-head operator review of `822e560`.**

## 2026-07-13 · #259 S2 completed-edit registration adapter — PR #260 OPEN at merge gate (head `b1d833f`)
- Phase-audited convergent registration (sole write path): A intent -> B create_resource(3,-2) +
  field99 + durable created-ref audit -> C create_binding + registered audit (one txn) + first
  observe_readiness (not_ready_pending) -> D field-100 g1:registered token. Refuses without an
  audit-verified S1 pin; binds exactly the pinned (asset_id,version,slot_id).
- Deterministic recovery (Codex-amended): binding exists -> Phase D only; created-event -> ADOPT
  recorded ref (index-independent verify-on-read, never a 2nd resource); crash-before-created ->
  resolve_unique adopt; recorded-ref-lacks-id / ambiguous -> truthful STOP no re-create;
  Phase-D failure -> projection-only retry. RSClient gains field-scoped create_resource/
  update_field/field_value; writer = separate least-privilege principal (env NAME only, 503 when
  unconfigured). Governed POST /slots/{id}/sdam/register-edit + one Edit-card action.
- Validation at b1d833f: sdam_selftest ALL (+10 incl. both recovery cases + crash variants
  1b/1c) · selftest ALL · api_selftest ALL (+2 401/503, stub verified, live restored) · tsc/build
  clean · Playwright 192/192 zero retries.
- LIVE one-item trial proof DEFERRED for operator decision: needs the branch on STITCH-VPS vs GFWS
  (local can't reach GFWS; #252 SSH-write grant was scoped to #252 only). Options on the PR:
  merge-then-post-merge-acceptance (#250->#254 precedent) OR authorize a pre-merge branch deploy.
- **Gate: PR #260 HELD (Codex + GPT + exact-head operator).** #259 stays directive:running.

## 2026-07-13 · #258 S2a RS write-capability discovery — CLOSED (discovery-only, no PR, no provider write)
- U1/U2/U3 all explicitly CHOSEN with evidence (RS knowledge base + frozen #234/#252/#254 deployed
  proofs; no new write attempts — denials cited, not re-run):
  U1 = dedicated least-privilege write principal (contribute NORMAL mode preferred → resources land
  at Pending −2 = the adapter's proven pending≠missing semantics), trial-bridged by operator-lane
  registration; exact permission-code string = the one remaining UNVERIFIED cell.
  U2 = one new RS resource per approved edit version — DECISIVE: alternatives carry no own metadata
  fields (can't hold a per-version canonical UUID); native version control is revert/replace-in-place
  (no coexisting addressable identities); 1:1 preserves the #244 identity contract with zero adapter
  changes.
  U3 = dedicated metadata field (tanaghom_readiness, generation token embedded in the value,
  blank-unset reversible) over tags/collections — mirrors the proven field-99 discipline; no tag
  taxonomy invented; index-staleness caveat carried, neutralized by verify-on-read.
- ONE remaining operator-only reversible proof posted (provision writer group + field; one-resource
  create/update/verify/deny/delete script; records the permission string) — closes every unverified
  cell before the S2 design freeze.
- Acceptance: no provider write occurred; every S2 action has authority + rollback; #251/#255
  authority rules intact (projection never publication authority). Issue relabeled done + CLOSED.

## 2026-07-13 · #255 S1 approved-master-edit pin — CLOSED (PR #257 merged as `588d5e3`)
- Operator merged PR #257 (squash `588d5e33a3fb440cc495752d1a2c2e3835e49c96`, 2026-07-13T09:50:25Z)
  from reviewed exact head `ed81254` (three-finding Codex patch round + body-only gate correction
  resolved; GPT + operator exact-head gate passed). Closeout done: main synced, branch deleted,
  #255 relabeled `directive:done` and CLOSED, Done audit posted.
- On main now: atomic approved-MASTER-edit pin at edit_review (exactly-one-active-master or
  fail-closed full rollback; STRICT in-transaction media-edit directive emission; immutable
  `approved_edit_master_pinned` audit) + read-only pinned-vs-current-master truth on the
  Edit/Production inspection path (audit-derived identity, truthful pin_evidence, drift explicit).
- BEHAVIOR CHANGE LIVE: edit approval requires exactly one attached master edit (fail-closed).
- RESIDUALS (on the issue): S2a SDAM write discovery = next slice decision (separate/unapproved);
  S4 = publisher-side selection alignment (publication.py newest-across-variants noted); operator
  guide line for the new edit-approval requirement (fold into #169); VPS picks up S1 next deploy.

## 2026-07-13 · #255 S1 review patches — PR #257 head now `ed81254` (gate reset per #188)
- Codex review of `bd55d6d` found 3 items — ALL patched: (P1) media-edit handoff emission is now
  STRICT inside the atomic contract (failure propagates → whole resolution rolls back; legacy
  stages keep best-effort; injected-failure proof shows zero surviving state + legacy tolerance);
  (P1) pinned asset identity now derives from the newest matching immutable
  `approved_edit_master_pinned` event verified against asset truth, with truthful `pin_evidence`
  (audit/unavailable/inconsistent) surfaced read-only — duplicate same-revision master adversarial
  fixture cannot corrupt the display, pointer-without-event reports unavailable; (P2) the
  two-connection proof now overlaps the REAL resolve() path (add_asset commits internally — the
  competing supersession holds its own uncommitted txn body): resolve blocks mid-path, one
  serialized outcome, zero partial state on fail-closed overlap, retry pins the single master,
  exactly one immutable event.
- Validation at `ed81254`: selftest ALL (§14b = 17 checks) · api_selftest ALL (stub verified,
  live restored) · tsc/build clean · Playwright 191/191 zero retries.
- **Gate: PR #257 HELD for fresh Codex + GPT + exact-head operator review of `ed81254`.**

## 2026-07-13 · #255 S1 approved-master-edit pin — PR #257 OPEN at merge gate (head `bd55d6d`)
- Code-only S1 (from the #251 contract): inside resolve()'s approval transaction, exactly ONE
  active MASTER edit (media_edit/edit/variant-NULL/active) resolved FOR UPDATE → pinned via
  slot_approval(slot,'edit') + immutable `approved_edit_master_pinned` audit — atomic with status
  change + directive emission. Zero/multiple masters FAIL CLOSED (full rollback, NO cleanup).
  Reopen semantics unchanged. inspect_slot.approved_edit + TrailInspect show pinned-vs-current
  master distinctly (drift explicit, approved display never moves), read-only, 375px proven.
- Proofs: selftest §14b (11 checks incl. adversarial same-revision variant sibling, fail-closed
  zero/ambiguous, TWO-CONNECTION lock/serialization — blocked writer completes after release,
  single-master pin, never divergent/partial); api_selftest +2; new edit-pin e2e. Baseline:
  all selftests ALL PASSED, tsc/build clean, Playwright 191/191 zero retries; stub verified,
  LIVE writer restored + verified.
- Behavior change per the directive's own rule: edit_review approval now REQUIRES exactly one
  attached master edit (existing flows already comply). Folded test-hygiene fix: suite-unique
  binding fixture refs (60006/70006/70007) — cures a pre-existing #250 cross-suite
  (provider,external_ref) collision. Noted for S4: publication.py edit-output intake still
  selects newest-across-variants (publisher-side alignment = S4 per #251).
- **Gate: PR #257 HELD at the full Codex + GPT + exact-head operator merge gate.** #255 remains
  `directive:running` until merge + closeout. S2a stays separate/unapproved.

## 2026-07-13 · #251 completed-edit/publication/analytics lineage contract — CLOSED (planning-only, no PR)
- Planning report v1 posted on the issue: authority/projection matrix (Tanaghom decisions/lineage
  authoritative; SDAM labels = non-authoritative projection, structurally unable to publish);
  lifecycle/reviewer-action matrix (candidate ≠ canonical completed edit; edit_review approval +
  approved-edit PIN + SDAM registration + derived eligibility as four distinct boundaries);
  version/identity contract (asset_id is one-per-version — uuid pins exact version; mapping/
  projection generations additive, never reinterpreted); publisher/receipt contract (exact
  eligibility predicate; receipts only via governed pub.v1 write — tag-alone publishing
  structurally impossible); analytics correlation (pub.v1 already persists edit_output_asset_id +
  frozen raw-asset junction — verified; BrandShield proposal-only via #249 lane).
- #254 facts reconciled explicitly: raw-media evidence RETAINED; synthetic pub.v1 receipt RETAINED
  + EXTENDED (same spine); `SCHEDULED` status RETAINED with rename decision = U4. Nothing
  reinterpreted as completed-edit registration or external publication.
- Ordered slices: S1 approved-edit pin (code-only, slot_approval.artifact unconstrained — verified;
  NARROWEST NEXT DECISION) → S2a SDAM write-capability discovery (UNVERIFIED) → S2 registration
  adapter → S3 projection emitter → S4a Postiz discovery (UNVERIFIED) → S4 publisher adapter →
  S5 analytics joins. Unresolved choices U1–U7 recorded with bounded alternatives (write principal,
  RS edit-version representation, projection medium, SCHEDULED naming, eligibility read shape,
  Postiz surface, return-to-edit authority via #249/#238).
- Hard stops: none tripped; every provider capability marked verified/unverified/discovery. No
  implementation performed. Issue relabeled done + CLOSED per planning precedent (#128–132/#233).

## 2026-07-13 · #254 isolated SDAM-backed lifecycle acceptance on STITCH-VPS — CLOSED (FULL SUCCESS, no PR)
- Deployed exact main `77f9cab` (⊇ fd9ec2c/#250) via verified bundle; 023 matched (#252 shape, not
  reapplied); RS config activated (3 values secret-file→deploy .env in root shell, gateapi-only,
  configured proof through the deployed API). Backup evidenced first.
- Candidate rule hit its documented STOP truthfully (resource 6 consumed by SDAM252 binding +
  field-99 identity) → operator created synthetic resource 8 (field-99 = acceptance asset UUID) →
  read-only discovery: complete scan resolved ONE carrier = ref 8 (browser `field99:` search quirk
  remains non-authoritative; verify-on-read decisive).
- BOTH acceptance boundaries proven: (1) SDAM — binding `6c775d34…` (asset `eba14f8f…` v1, slot
  R3-D01-S1, ref 8) fresh-`ready` seq 1; deployed UI showed truthful not-bound→fresh-ready on
  Production AND Edit; Edit-input summary exact; explicit media resolution SUCCEEDED live (signed
  URL kept out of evidence); #237 inspect read-only; no gate advanced by SDAM reads; 375px OK.
  (2) manual lifecycle — R3 "ACCEPT-254 (synthetic…)" end-to-end in the deployed UI with LIVE
  generation (groq llama-4-scout, truthful attribution), AND-quorum persona switch, raw_cut+edit
  assets, pub.v1 receipt telegram · "synthetic-manual-trial (ACCEPT-254 — no external publication)"
  · attested khal · 3 events. NO external-publication claim.
- Reconciled: 8 decisions/7 stages; zero orphans; SDAM252 fixture untouched (ref 6, 4 obs);
  R1/R2 preserved; live writer NEVER changed. Fixture RETAINED (convention; durable evidence).
- Residual observations: post-distribution slot status = `SCHEDULED` (existing approve_to config —
  input for #251 planning); no defect found, nothing patched. #254 relabeled done + CLOSED.
- Evidence prerequisite for the AVP/SDAM completed-edit slice selection is now satisfied.

## 2026-07-13 · #250 SDAM readiness/Edit-input visibility — CLOSED (PR #253 merged as `fd9ec2c`)
- Operator merged PR #253 (squash `fd9ec2c032f895a2bc0b36f1c6f859adb1fff09a`, 2026-07-13T05:48:16Z)
  from reviewed exact head `0121cb2`. Closeout done: main synced, branch deleted (remote auto +
  local), #250 relabeled `directive:done` and CLOSED, Done audit posted.
- On main now: slot-keyed read-only SDAM visibility (`list_slot_bindings` + `GET /slots/{id}/sdam`
  + `GET /sdam/bindings/{id}/handoff` via existing build_handoff authorization) + `SdamReadiness`
  on Production/Edit cards + trail rows (five truthful states, Edit-input summary, explicit media
  resolve, #237 inspect alongside, zero mutation controls) + compose RS key-NAMES passthrough.
- RESIDUALS (on the issue): VPS live-media activation = operator copies 3 RESOURCESPACE_* values
  from #252's root-only secret file into deploy .env + recreate gateapi (next VPS deploy also
  ships this UI); runbook touch-ups (no git remote on VPS / OIDC+dev-mode envs / short BUILD_SHA);
  readiness-gates-Edit enforcement deliberately NOT built (separate state-machine proposal if
  wanted); CP-012/CP-013/CP-024 ledger advance = operator/docs lane.

## 2026-07-13 · #250 SDAM readiness/Edit-input visibility — PR #253 OPEN at merge gate (head `0121cb2`)
- Directive #250 resumed on operator green-light after #252's GO; relabeled `running` at
  implementation start. Delivered the bounded READ-ONLY slice: `sdam.list_slot_bindings`
  (additive; bindings + newest persisted observation, bound-no-evidence distinct from provider
  pending) + `GET /slots/{id}/sdam` + `GET /sdam/bindings/{id}/handoff` (existing build_handoff
  authorization; truthful configured:false / not-fresh-ready / provider-error outcomes), both
  behind the signed /gw boundary; `SdamReadiness` surface on Production/Edit active cards + trail
  rows (five distinct truthful states, provider-neutral Edit-input summary, explicit lazy media
  resolve, #237 inspect affordance alongside, zero mutation controls); compose/.env.example RS key
  NAMES passthrough (empty = truthful absence).
- Boundaries held: no schema, gate/state-machine, authority, RS-write, AVP, or task-engine work;
  #244 invariants + #237 surface untouched; fixtures only via existing sole write paths.
  sdam-aware teardowns added to api_selftest + e2e_ops_seed (NO ACTION FK would block reseeds).
- Validation at `0121cb2`: sdam_selftest ALL (+3) · gates.selftest ALL · api_selftest ALL (+7,
  stub verified, LIVE restored) · tsc/build clean · Playwright 190/190 zero retries (+2-test spec).
- **Gate: PR #253 HELD at the full Codex + GPT + exact-head operator merge gate.** #250 remains
  `directive:running` until merge + closeout. VPS note: copying the three RS values from #252's
  root-only secret file into deploy `.env` (per .env.example) activates live media resolution
  there — operator step; readiness visibility works without it.

## 2026-07-13 · #252 SDAM readiness prerequisite deployed to STITCH-VPS — CLOSED (no PR; #250 dependency = GO)
- Environment directive (like #234/#225): redacted backup (`tanaghom-252-pre-20260713T034342Z.sql.gz`,
  52,367 B, sha256 recorded) → exact remote `main` `38ef82f` deployed via VERIFIED GIT BUNDLE
  (VPS checkout has NO git remote — #225 runbook's `git fetch` step is broken as written; runbook
  touch-up candidate) → migration 023 inspect-first (0 objects) applied EXACTLY ONCE from the
  byte-identical merged file (3 tables + append fn + seeded policy 1/900/30) → RS read config
  provisioned root-only (#187 discipline: /srv/tanaghom/secrets/rs_ro.env root:root 600, names-only
  evidence, value root-file→root-file).
- Live proof via existing #244 paths only: synthetic `SDAM252-1` slot + dam asset v1
  (`3f882f51-5b55-4dd6-840b-2584537a13ac`) + binding `4f15ac47…0897` → external_ref 6. Directive
  stop condition hit truthfully (fixture field-99 = `TANAGHOMSYNTH0001` can never byte-equal a
  canonical UUID; RS write = operator lane) → STOP report → operator set field-99 to the asset UUID
  + synchronous `reindex_field.php 99` (the #234 index lesson held) → observation `ready` (seq 2,
  fresh) → `build_handoff` provider-neutral projection (media access key redacted) → gateapi
  RESTART → same success (`ready` seq 3) → `/root/rs_ro_key` shredded. Pre-fix `not_ready_missing`
  (seq 1) retained as the fail-closed proof on the same runtime.
- Final: runtime `38ef82f`, live writer, `/sdam` routes present (unsigned 401), pre-#244 WIP
  `sdam.py` image drift GONE (hash = merged), env-name audit clean. Proof residue retained
  deliberately as #250's trial fixture (SDAM252-*, binding, 3 observations).
- **#250 dependency = GO** (posted there). #250 remains HELD at `directive:approved` per the Codex
  handoff correction; it resumes only on operator green-light, relabeling to `running` at
  implementation start.

## 2026-07-13 · #237 Slice A — CLOSED (PR #248 merged as `381bdfb`)
- Operator merged PR #248 (squash `381bdfb701f45da02fe3904c1eae2c9b4dcd11bf`, 2026-07-13T01:53:38Z)
  from the authorized exact head `fb2c2e3`; Codex + GPT exact-head reviews clear. Closeout done:
  main synced, branch deleted (remote auto + local), #237 relabeled `directive:done` and CLOSED,
  Done audit posted.
- On main now: `engine.inspect_slot` + `GET /slots/{id}/inspect` (signed /gw boundary) + read-only
  `TrailInspect` lazy expansion — approved items keep full inspection depth (pinned revisions,
  provenance, lineage, truthful absence) with zero mutation affordances.
- RESIDUALS (recorded on the issue): Slice B governed-edit eligibility = separate future directive;
  optional slot-keyed SDAM lineage read; HANDOFF runbook env touch-up (OIDC issuer + dev-mode envs,
  short BUILD_SHA convention); CP-024 ledger status advance = operator/docs-lane call.

## 2026-07-13 · #237 Slice A approved-content inspection parity — PR #248 OPEN at merge gate (head `fb2c2e3`)
- Directive #237 Slice A (read-only inspection parity; GPT approve + CC GO + operator handoff)
  executed: `engine.inspect_slot` status-independent read-only projection (slot_approval-PINNED
  topic/script revisions, labeled head-fallback, decision provenance, assets) + `GET
  /slots/{id}/inspect` behind the existing signed /gw boundary (401 unsigned, 404 unknown,
  publications composed server-side) + dedicated non-mutating `TrailInspect` lazy expansion on
  completed-trail rows at every density/ID mode. No schema, no mutation affordance, no SDAM lookup
  (truthful "not surfaced yet"), #219 controls untouched. Issue relabeled `directive:running`.
- Codex review of local head `3a211f8` found 2 blockers — BOTH patched in `fb2c2e3`: (P1) diverged
  `slot.topic_angle` vs pinned `topic.text_ar` now BOTH render, truthfully labeled, with
  adversarial engine+e2e fixtures; (P2) script-stage approval-transition parity acceptance-proven
  end-to-end on RSCR (registry beats, delivery direction, final line, verbatim #154 model
  attribution, pinned-revision label, read-only negatives, 375px).
- Validation at `fb2c2e3`: gates.selftest ALL PASSED (7 new #237 checks) · api_selftest ALL PASSED
  (stub mode verified exact; 3 new checks; LIVE writer mode restored+verified after runs) · tsc +
  next build clean · Playwright 188/188 zero retries.
- Environment findings (no product-code impact): the "flaky" 167px narrow-viewport overflow class
  was a local full-40-char TANAGHOM_BUILD_SHA stamp (convention: `git rev-parse --short HEAD`);
  HANDOFF's gate-API run command lacks `-e TANAGHOM_OIDC_ISSUER=http://localhost:3108` and
  `-e TANAGHOM_DEV_MODE=1` (api_selftest #194/#195 precondition fails without the issuer). A
  transient invalid GitHub token also blocked push mid-cycle; operator re-auth resolved it.
- **Gate state: PR #248 HELD at the human merge gate; a fresh review of exact head `fb2c2e3` is
  required (#188 — the `3a211f8` review does not carry over the patch).** Issue #237 remains
  `directive:running` until merge + closeout.

## 2026-07-13 · PR #246 clean-history client-SRD replacement — MERGED (closes out the #239 supersession)
- Operator merged PR #246: squash `a72c437cd855f89f5a264af962cb76a9ccd071e8` at 2026-07-12T23:21:31Z
  from exact reviewed head `02d3751`. `main` now carries the external-authority manifest +
  split-authority checkpoint ledger `mv2` on an ancestry that never contained a client binary.
- Closeout done: local `main` synced to the merge commit; branch `docs/client-srd-clean-replacement`
  deleted (origin auto-deleted on merge; local removed); ✅ Done comment posted on #246.
- Residuals for the queue: (1) `refs/pull/239/head` retains the old binary commits until GitHub GC —
  purge would be a GitHub Support action, declined at this stage; (2) all 32 checkpoints have
  `decision_owner = unassigned` — assignment is the ledger's next traceability action; (3) CP-032's
  operator clarification needs a formal SRD amendment record before routing automation; (4) external
  source placement remains `placement pending`.

## 2026-07-13 · PR #239 client-SRD ledger — CLOSED UNMERGED; clean-history replacement PR #246 open at gate
- Executed the explicit operator authorization posted on PR #239: created fresh branch
  `docs/client-srd-clean-replacement` from verified `origin/main` (`01c383b`) and reconstructed ONLY
  the three sanitized Markdown files (`docs/00_INDEX.md`, `docs/client-source/README.md`,
  `docs/client-source/2026-07-08/TRACEABILITY.md`). No force-push, no `main` rewrite, no
  directive-state mutation.
- Review corrections applied in the reconstruction: split authority fields (`source_authority` /
  `interpretation_authority` / `clarification_evidence`; never combined); mixed-authority checkpoints
  split into linked rows (CP-001↔CP-031 derived-mapping, CP-003↔CP-032 operator-clarification with
  evidence honestly marked "formal amendment record pending"); external locator explicitly
  `placement pending`; per-checkpoint `decision_owner` (`unassigned`; one-owner-decision claim
  withheld); weakest-defensible coverage (CP-024 held at `partially-covered` while #237 is open);
  explicit `mv1`→`mv2` supersession (mv1 = the unmerged #239 draft).
- Binary-free proof at head `02d3751` pre-push: exactly 1 commit atop `origin/main`; new objects =
  3 Markdown blobs + trees only; old client-binary blobs `792a4437…`/`9546c6de…` unreachable from
  HEAD; zero ancestry commits ever touched those paths; HEAD tree binary set identical to main's.
- **PR #246** opened (head `02d3751`, exactly 3 files, +211) and verified server-side; then PR #239
  closed UNMERGED with a traceable supersession comment and branch `codex/client-srd-sources`
  deleted (remote + local). Retention limitation recorded on #239: binary-bearing commits remain
  fetchable via immutable `refs/pull/239/head` until GitHub GC; server-side purge = separate GitHub
  Support action, NOT requested at this stage per the authorization.
- **PR #246 is HELD at the full fresh review gate** (Codex + CC + GPT + exact-head operator merge).
  No merge action will be taken by the executor. Codex lane: #239's queue entry can be normalized as
  superseded-by-#246.

## 2026-07-12 · #244 Production→SDAM readiness adapter (dual-identity binding) — CLOSED (PR #245 merged)
- Two-gate directive: Phase A schema preflight (multiple Codex+GPT rounds: dual-ID composite FK,
  digest/retry/timestamp/idempotency DB-enforcement, stable pagination, F1 privilege boundary,
  minimum-persistence re-audit, and the F4 honest one-shot decision) → explicit operator authorization
  of the EXACT one-shot migration 023 (incl. additive `asset UNIQUE(asset_id,version,slot_id)`) →
  implementation. PR #245 squash-merged from authorized head `72d2ceb` as
  `ef64ba1903455194dfa00252359ed5f7cccbe5b0` at 2026-07-12T19:15:31Z; main synced; branch deleted.
- Migration 023 (transactional ONE-SHOT, not an idempotent runner — repo has no ledger): asset
  composite UNIQUE; `sdam_freshness_policy` (immutable+seeded 1/900/30); `sdam_asset_binding`
  (immutable; native composite FK binds asset+version+slot to one truth; `(provider_key,external_ref)`
  cardinality uniqueness; OPAQUE external_ref — RS numeric shape validated in the adapter, not DB);
  `sdam_readiness_observation` (append-only; DB-assigned `observation_seq` = ordering authority; full
  9-result digest/mismatch/retry CHECK matrix; DB-forced times + policy-derived expiry; `stale` is
  derived-only); `sdam_append_observation()` sole write path (advisory-lock finalization, revalidate
  binding, converge-or-conflict idempotency). Fresh apply + clean-abort rerun proven.
- `gates/sdam.py` read-only RS userkey adapter: readiness ENFORCES RS uniqueness (complete canonical-id
  scan → exactly one byte-exact match == bound external_ref before `ready`; else typed fail-closed);
  `resolve_unique` compares complete `(resource_ref, field-99 bytes, archive)` tuples across two scans;
  pending≠missing; handoff (fresh+ready only; media resolved live). `gates/api.py` bounded read-only
  API read model (`GET /sdam/bindings/{id}` + `/readiness`) gated by the existing `/gw`
  signed-principal boundary. Audit events (`sdam_binding_created`/`sdam_readiness_observed`, actor_kind
  = actor_type). Observation+audit atomic in the CALLER's txn (no internal commit).
- Codex merge-gate found 5 then 4 more blockers across two patch rounds — all fixed: uniqueness in
  readiness, tuple double-scan, real independent-connection concurrency (all-N converge + same-key/
  different-payload race + consecutive seqs), caller-owned txn/atomic rollback, signed-principal API
  auth (401/401/401/200), audit attribution, test-residue (policy 999) + digest matrix. `sdam_selftest`
  all pass rerun-clean; `gates.selftest` green; live read-only proof vs retained resource 6.
- Boundaries: SDAM authoritative; Tanaghom persists only opaque binding + minimum decision evidence;
  RS principal read-only; write guard is a TRIAL CONVENTION, not a DB authority boundary.
  RESIDUALS (recorded): `schema_migrations` ledger + dedicated non-superuser runtime role deferred;
  a true live end-to-end canonical binding needs a separately authorized RS fixture aligning field-99
  with a synthetic asset_id UUID; migration 023 applied to DEV DB only (VPS deploy is a separate step).

## 2026-07-12 · #234 provision + prove live SDAM readiness prerequisites — CLOSED (no PR; CONDITIONAL GO)
- Sole mutation surface = GFWS ResourceSpace 10.7 (privileged provisioning done in the OPERATOR admin
  lane; CC ran all read-only proofs from the VPS gate-API container with the restricted principal).
  No Tanaghom/AVP/BrandShield/client/schema/migration/PR/branch mutation. Key/$api_scramble_key/signed
  URLs never printed; access_key redacted. Auth freeze: RS `authmode=userkey`, sign=SHA256(privkey+exact
  query) concat (NOT HMAC/bearer); group perms = real authz boundary.
- BOUNDARY: CC cannot create accounts / define access-control / enter admin creds / edit GFWS config →
  operator performed P1-P4 + all remediations; CC posted exact runbooks + rollback and ran every proof.
- PROVEN (restricted user `stitch_readonly` ref2 → group `Tanaghom SDAM Reader` ref7 = `s,g,f*,j*,z1,z2,z3,`):
  valid signed read 200 / invalid + tampered-query 401; genuinely read-only — create/update/delete/
  **add_alternative_file all denied** (false) AFTER the group was tightened; byte-exact field-99 storage
  (`TANAGHOMSYNTH0001`, no trim/fold/stem); lookup = token search bounded to resource_type 3 + field-99
  **verify-on-read byte-compare** → AMBIGUOUS(2)→ONE(res6)→ZERO, all normalization variants REJECTED
  (RS search normalizes/partial-matches; verify-on-read is the exactness guarantee); pending(-2)≠missing
  via preserved resource.ref; resource.ref preserved across -2→0; media URL reachable from the container
  on `$baseurl=http://100.119.170.109:8088` (Tailscale IP; MagicDNS unresolvable in-container); RS health OK.
- HARD-STOP caught + remediated: pre-tightening Reader allowed add_alternative_file → CC-caused 2 stray
  alternatives on res6 (disclosed) → operator removed them + tightened group. Field 99 first created
  keywords_index=0 (unsearchable) → operator set kw=1/partial=0; index only populated after a SYNCHRONOUS
  `php reindex_field.php 99` (RS cron FAIL ~2.4d blocked the offline job).
- Config IDs frozen: field ref **99** (tanaghom_asset_id, type0), video resource_type **3**, base_url
  Tailscale IP. Retained: group7, field99, baseurl, fixture X=resource6 (Active). Cleaned: duplicate
  D=resource7 (deleted), stray alternatives. Secret ref names only (RESOURCESPACE_API_USER/KEY/BASE_URL,
  TANAGHOM_ASSET_ID_FIELD_REF=99, VIDEO_RESOURCE_TYPE_ID=3); key at /root/rs_ro_key → recommend shred +
  re-provision via #187 at adapter time.
- Verdict CONDITIONAL GO; one unposted adapter directive DRAFTED, classified MIGRATION AUTHORIZATION
  REQUIRED (additive `sdam_readiness_observation` keyed (asset_id,version), FK NO ACTION; readiness by
  workflow-state + identity/version/role/taxonomy/lineage; provider-neutral AVP externalRef; versioned
  mapping layer; progressive minimal Tanaghom UI). RESIDUALS (recorded only): stalled RS cron, the
  non-authoritative `field99:`-scoped search quirk (moot via verify-on-read), `SDAM-stitch-stack#1`
  (metadata-macro warning), production TLS/secret-authority for replayable signed URLs.

## 2026-07-12 · #233 live SDAM identity + readiness contract freeze — CLOSED (no PR, read-only; CONDITIONAL GO)
- Read-only cross-system freeze (Tanaghom + live GFWS ResourceSpace SDAM via VPS gate-API container
  over Tailscale; SDAM-stitch-stack + Agentic-Video-Producer repos read-only; brand-shield name-only).
  NO code/PR/branch/schema/migration/config/credential/SDAM/AVP/live-record mutation; no secret printed.
- LIVE-CONFIRMED: gate-API CONTAINER → GFWS `100.119.170.109:8088` reachable (hard-stop #1 CLEARED;
  `/login.php`→200 ResourceSpace; `:8080` there is Adminer not RS). Auth = native REST per-user
  PRIVATE-KEY SIGNED scheme (`/api/?user=&function=&…&sign=`; unsigned → HTTP 401 "Invalid signature";
  keyed by `$api_scramble_key`). Tanaghom has NO RS credential/endpoint wired today (gate-API env has
  zero DAM/RS vars; `dam:` config is the minimal internal asset model). RS `$baseurl` =
  host.docker.internal:8088 (local-only) → RS absolute URLs won't resolve from the VPS (external-compat).
- IDENTITY: opaque `asset.asset_id`(uuid) stored in a dedicated RS custom field → exactly one immutable
  RS `resource.ref`; corroborate slot_id/script_id/edit_output_version + verify-on-read (defends against
  `$stemming=true`). RS custom field/type/node/resource_type IDs are LIVE-DB-ONLY (SDAM repo is a deploy
  wrapper, no schema/fields committed). RS uniqueness NOT enforced → writer-side unique + read-only
  principal + verify-on-read. Resource(resource.ref)/alternative(alternative_files.ref)/rendition
  ((ref,size)) kept distinct from Tanaghom asset_id/version/platform_variant; new version = new resource.
- RAW ROLES: `raw_cut`@production (+`raw` alias in publication.py:135) + single active `edit`@media_edit.
  AVP boundary = Asset{id,kind∈video/image/audio,src,externalRef{system,id},generation}; SDAM id rides
  in externalRef={system:sdam,id:resource.ref}. AVP has NO captions/brand/script role vocab.
- PERSISTENCE: does NOT fit migration-022 (external_ref=destination not source DAM; no digest/freshness/
  retry/result columns; publication_raw_asset is frozen membership; `asset` has no typed external-id/
  digest column). → ADDITIVE MIGRATION: new `sdam_readiness_observation` keyed (asset_id,version), FK
  NO ACTION to asset, 022-style freeze. Result codes: ready/not_ready_missing/_lineage_mismatch/
  _taxonomy_mismatch/_ambiguous/stale/unavailable/unauthorized/malformed. Deterministic timeout/
  count=1/payload-cap/retry/freshness-TTL/redaction rules frozen.
- VERDICT CONDITIONAL GO. Next implementation directive DRAFTED (classified MIGRATION AUTHORIZATION
  REQUIRED; embeds external-compat fix + read-only-principal/opaque-ID-field provisioning + credential
  wiring via #187 env/config mutation dependency + a synthetic live-proof record) — NOT posted/executed.
  Gating conditions all outside this read-only pass. No safe live-proof record designated yet.

## 2026-07-12 · #230 reversible OpenRouter-first trial generation routing — CLOSED (PR #231 merged; VPS activation NOT done)
- Config-only implementation of #227's CONDITIONAL GO. PR #231 squash-merged from head
  `0b2f34f` as `21b51190a382ff5896f07e7f7fe5d8c3e7e95f37` at 2026-07-12T09:15:05Z; local main
  synced; branch deleted. Held at + reset through the full Codex+GPT+operator gate (patched once).
- EXECUTABLE trial route for `models.topic_hook` + `models.script`:
  **OpenRouter Scout → Groq Scout → Groq Qwen** (Qwen operator-authorized). Uses the existing
  provider registry + StageRunner ordered fall-through; temperatures (0.85/0.8), token limits
  (1500/2500), prompts, exemplars, validators, regeneration, per-hop attribution UNCHANGED;
  reversal = pure config edit. Three tracked files: `system_config.example.yaml`,
  `deploy/stitch-vps/config/README.md`, `gates/selftest.py`. Dirty operator-doc batch untouched.
- Codex merge-gate patch (operator-amended): (1) Groq Qwen kept per explicit operator auth;
  (2) removed the FALSE GFWS/`ollama:qwen3.5:latest` executable hop — the shared `ollama` provider
  resolves to `host.docker.internal` (host-local, embeddings-only Ollama), NOT the separate GFWS
  machine. GFWS recorded as the authorized final LOGICAL hop, DEFERRED until a distinct verified
  `gfws_ollama` Tailscale endpoint exists (no networking work in this bounded PR). `ollama_embed`
  documented embeddings-only; `ollama` chat documented host-local (not GFWS).
- Validation: `gates.selftest` GREEN — 22 #230 checks (exact 3-hop order; NO false GFWS/ollama
  executable hop; induced-failure failover to Groq Scout; no silent model substitution — `.model`
  reports the ACTUAL served hop; config-only reversibility; exact-fallback + preserved temps/tokens
  tracked-default assertions) + full pipeline passes. Local out-of-band synthetic smoke PASS
  (OpenRouter primary serves topic+script; induced HTTP-400 primary failure → Groq Scout, truthful
  attribution). tsc clean. api_selftest/Playwright orthogonal (running API loads the gitignored
  runtime config, not the edited example).
- NOT claimed: OpenRouter-first is NOT activated on STITCH-VPS; no deploy performed; runtime
  behavior unchanged until residuals clear. RESIDUALS (operator-owned): (1) ROTATE exposed
  GROQ_API_KEY + OPENROUTER_API_KEY (a `docker inspect` ENV dump surfaced their values in CC tool
  output; nothing committed) — CC now uses name/status only; (2) provision the rotated
  OPENROUTER_API_KEY on STITCH-VPS via approved secret handling (#187) before activation, then
  runbook deploy + exact-build/live-writer verify + persisted smoke; (3) GFWS deferred as above;
  (4) #229 quality track pending/non-blocking.

## 2026-07-12 · #227 OpenRouter-Scout evaluation for temporary ar-PS trial routing — CLOSED (no PR, planning-only)
- Planning/evaluation directive: evidence-backed GO/CONDITIONAL-GO/NO-GO on OpenRouter-hosted
  Llama 4 Scout as the TEMPORARY primary topic/script generator vs proven Groq Scout. NO branch/PR/
  routing/config/schema/deployment/runtime/data mutation; R1/R2/queues/DB untouched. All calls
  direct + out-of-band from the LOCAL gate container (both keys present locally; VPS container has
  `OPENROUTER_API_KEY` MISSING and routes topic/script groq-scout→groq-qwen only).
- Preflight PASS (key-NAME/status only, never value): OPENROUTER_API_KEY present+callable; quota
  $7 limit / ~$6.9995 remaining, non-free-tier; slug `meta-llama/llama-4-scout` (sole match/345);
  **same checkpoint confirmed at RUNTIME** — OpenRouter's served-model echo returns the exact Groq
  slug `meta-llama/llama-4-scout-17b-16e-instruct`; advertises response_format+structured_outputs.
  OpenRouter Scout is ALREADY the 2nd fallback in local `models.topic_hook`+`models.script` → a GO
  is a config REORDER of an already-wired route (honors the temporary-routing boundary).
- Method: imported the REAL writer contract (run_writers SYSTEM_VOICE/topic_prompt/script_prompt/
  parse_json/validate_hook/script_hard_fails/dialect_violations), swapped only the provider; stage
  params exact (topic 0.85/1500, script 0.8/2500); 3 fixed SYNTHETIC ar-PS wounds (no client
  content); topic=same input both, script=same fixed approved-topic both; one raw pass (no regen
  loop). 12 calls.
- Results: 12/12 valid JSON, all required fields, finish_reason=stop (zero truncation) BOTH
  providers on the prompt-driven contract. Latency Groq 528–1824ms vs OpenRouter 3450–7986ms
  (~3.5–5.5× slower, LPU; descriptive). First-pass dialect hard-fails: Groq ×2 (C2 شلون/ده/كده,
  C3 دلوقتي), OpenRouter ×0 — SAMPLING NOISE at n=3/temp0.8, both self-heal via the prod regen loop.
- Gap inventory (code-grounded): validate_hook scans hook_text only (:951); script_hard_fails
  scans script_ar only (:1004); every dialect script → needs_native_review (:1291). `topic_angle`/
  `rationale_ar`/`delivery_notes`/structure text are NEVER dialect/register-checked; guard is a
  fixed blocklist (blind to stiff MSA, unlisted non-PS phrasing, grammar, naturalness, semantic
  fit). Live proof: C1-OpenRouter angle is heavily Egyptian yet recorded 0 violations.
- Verdict **CONDITIONAL GO** (ceiling without native sign-off). Deliverables incl. private native-
  review side-by-side artifact + a DRAFT implementation directive (config-only, temporary,
  reversible) quoted in the report but deliberately NOT posted/executed. Two open human gates:
  native-reviewer parity sign-off + operator authorization. Closed = evaluation delivered, NOT
  routing approved. Container/quota left as found; harness removed post-run.

## 2026-07-12 · #225 STITCH-VPS customer-journey acceptance at df559ea — CLOSED (no PR, no defect)
- Deployed authorized main `df559ea` to STITCH-VPS via runbook (backup verified first
  `tanaghom-20260712T065354Z.sql.gz`; migrations 001-022 unchanged, no new
  migration/dependency/schema/secret/host change; #215/#218/#219 dashboard+list_advanced code
  arrived via image rebuild). Runtime + both badges (#205 desktop+compact) show `df559ea`; live
  writer; public 200; catalogues 5/5/5/42/4/1; embeddings viable (#211 host config persisted).
- ONE fresh canonical run R2 (`ACCEPT-225`) traversed END-TO-END through the real UI; R1
  preserved (2 rounds). Schedule→topic(live writer, groq/llama-4-scout, #207 truthful)→script→
  pre-prod AND-quorum (khal+huda, #215 persona transition clean)→production/edit/distribution
  MANUAL-BUT-TRACKED→**pub.v1 manual publication on plain HTTP** (dialog opens, #212 fix live;
  UUIDv4 idempotency key via getRandomValues; events seq 1-3; attested khal; reload-persistent).
- #219 completed-item inspection controls EFFECTIVE on the read-only trail (Detailed = canonical
  code + `Self · Anxiety and overthinking` descriptor; Full = topic/attribution/timestamp);
  #218 funnel shows `Run complete 1` + non-interactive Analytics→Learning→Optimize
  planned-not-connected.
- Reconciliation pristine: 2 runs, R2 7 gates all approved (correct attribution, no dup/orphan),
  raw+edit+post assets, edit_output+raw-junction lineage, 0 non-approved gates, 0 orphan intents.
  No product defect; no deployment defect; all prior fixes (#205/#207/#211/#212/#215/#218/#219)
  verified live at df559ea.
- Verdict: **CONDITIONALLY SAFE for controlled (supervised internal/demo) review** — proven
  boundary = governed workflow + manual production/edit/distribution + manual publication
  receipt; NOT external distribution/analytics/integration (disclosed not-connected); condition =
  internal-review HTTP + demo identity (OIDC/TLS/domain deferred). Client-readiness claim →
  **GPT review + Codex UI spot-check required before the verdict is final** (per directive).
- R1+R2 preserved for inspection; #197/#169 untouched; #187 secret-authority direction stands.

## 2026-07-12 · #223 bounded Infisical OSS infra pilot — CLOSED (live infra, fully reversible, no PR)
- Isolated, private-only, single-node Infisical OSS pilot on STITCH-VPS (own compose project /
  network / volumes / operator path, backend bound 127.0.0.1:8222 only, public :8222 refused).
  Strict pre-mutation GO/STOP passed (all conservative thresholds; no separate host available).
  `infisical/infisical:v0.162.3` + postgres:16-alpine + redis:7-alpine (digests recorded).
  Steady-state pilot ~834 MiB < 1.0 GiB cap; zero tanaghom impact throughout.
- Proof matrix 8/9 PASS: scoped retrieval (value MATCH, never exposed), out-of-scope denial
  (403), unauthorized denial (401/403), fail-closed on manager-down (HTTP 000, no host plaintext
  fallback), rotation (new version supersedes), revocation (existing token also killed),
  backup+restore (601-row parity, sentinel+identity survive), full rollback (ZERO residual,
  exact baseline parity).
- **MATERIAL FINDING — audit logging is a PAID/enterprise feature on self-hosted Infisical**
  (audit_logs/streams/outbox all 0 rows despite auditLogStorageDisabled:false; verified official
  docs 2026-07-12). Corrects an imprecise #221 claim that audit was free-core. Custom env/path
  RBAC roles are also enterprise-gated (used free built-in `viewer`, proved scope at the PROJECT
  boundary). No paid feature used.
- Hygiene: sentinel value / tokens / infra creds never printed/logged/committed (host-side
  chmod-600, destroyed at rollback); only sha256 correlation used. Full adversarial self-review
  clean; host restored to exact baseline; R1/DB/proxy/ports/OIDC/routing untouched.
- Verdict: **GO for one separate bounded resolver-seam PROOF** (manager-agnostic seam, one
  credential, fail-closed) — with a HARD operator prerequisite before PRODUCTION: free-OSS
  Infisical lacks the audit trail #187/#221 mandate, so choose (a) Infisical self-hosted
  enterprise (audit+RBAC+OIDC all paid) or (b) OpenBao (MPL-2.0, audit in free core). Not
  implemented/authorized here. #187 stays OPEN; #216 open; #218 pending; #197/#169 untouched.

## 2026-07-12 · #221 secret-authority evaluation for #187 — CLOSED (PLANNING-ONLY, no PR)
- Read-only security-architecture pass; zero code/schema/runtime/VPS/secret/env mutation, no
  secret VALUE handled, no manager installed. One evidence-backed decision report posted on #221.
- Current state: config already separates the secret REFERENCE (`api_key_env` name) + non-secret
  routing (`base_url`) from the VALUE (gitignored `.env`, resolved in `agents/providers.py` via
  `os.environ`). The gap #187 names: the host env is the de-facto secret AUTHORITY (no workload
  identity / rotation / revocation / audit).
- Three planes kept non-interchangeable: external OIDC (human auth) ≠ Tanaghom
  principals/AgentReps/capability matrix (product authority) ≠ secret manager (stores+delivers
  values; its IAM governs only its own resources).
- Verified time-sensitive licensing (primary sources, reviewed 2026-07-12): Infisical core MIT
  except `ee/`; OIDC/SAML SSO + OIDC group-mapping are PAID self-hosted; Google/GitHub SSO free;
  **machine identities + dynamic secrets + audit are in the FREE OSS core** — so the workload
  credential-resolution path is fully covered free (paid SSO affects only human admin-UI login,
  avoidable).
- Recommendation: **GO — adopt self-hosted Infisical** as the target secret authority. Named
  NO-GO alternative = OpenBao (MPL-2.0); plaintext DB vault rejected. One bounded next slice
  drafted (NOT started): STITCH-VPS machine-identity pilot resolving ONE provider credential
  (Groq key) at runtime with fail-closed + rotation/revocation audit, no paid features, no prod
  cutover, R1 untouched. Operator input flagged: VPS RAM headroom (~5.8GB box already loaded).
- #187 stays OPEN (standing). #218 independent/pending; #216 open; #197/#169 untouched.

## 2026-07-12 · #218 planned lifecycle after run completion — MERGED + CLOSED
- PR #222 squash-merged (SAFE TO MERGE, Codex+GPT, authorized head `337484c`) → merge `2c5961d`;
  #218 relabeled `directive:done`, closed; branch cleaned; main synced.
- Fix (two-file boundary: `review-surface.tsx` funnel strip + `run-funnel.spec.ts`): the run
  funnel no longer ends at a terminal `→ N done`. FULL completion
  (`funnel.total > 0 && funnel.completed === funnel.total`) → distinct truthful `Run complete N`
  + compact NON-INTERACTIVE `Analytics → Learning → Optimize · planned next loop, not connected`
  (plain spans, aria-hidden arrows, labeled group, one shared #186 disclosure, zero
  links/buttons/controls). PARTIAL (`0 < completed < total`) → truthful `N completed`, no
  terminal word, no continuation.
- Codex re-review caught the first head using `completed > 0` (a COUNT) as the completion
  gate — patched to the `completed === total` funnel-truth predicate + a partial-run test.
- No authoritative change: counts/arithmetic/status/gates/API/engine untouched; completed
  rendered verbatim; Analytics/Learning/Optimize implemented NOWHERE (labels only). Proofs:
  partial-absent + full-present + non-interactive + no document overflow at 1280/375. Focused
  spec 6/6; full Chromium 184/184 in VERIFIED stub (pre-suite exact stub check honored); live
  writer restored.
- Scope: #216 left OPEN (umbrella); #197/#169 pending untouched; preserved R1 unmutated; lands
  on VPS with the next deploy.

## 2026-07-12 · #219 completed-item inspection controls — MERGED + CLOSED
- PR #220 squash-merged (SAFE TO MERGE, Codex+GPT, authorized head `4ec4051`) → merge `e3b1b61`;
  #219 relabeled `directive:done`, closed; branch cleaned; main synced.
- Fix: completed stages (`targets===0`, `advancedTrail>0`) previously lost ALL inspection
  controls (gated on `targets>0`). Now the existing density (Chip/Compact/Full) + ID-mode
  (Compact/Expanded/Detailed) switchers show when active targets OR completed advanced items
  exist, and are EFFECTIVE on the read-only trail via the same density/idMode state +
  `contentIdLabel` — no second display system, no mutation affordance, publication behavior
  unchanged.
- Conditional canonical read-model extension (DISCLOSED field-by-field pre-mutation on #219;
  additive/read-only, no schema/migration/persistence/write/API-contract): `list_advanced` +4
  canonical fields (`pillar_short_code`, `seq_in_pillar`, `pillar_name_en`, `hcs_name_en`) via
  LEFT JOIN pillar/hcs (the active-target selection's proven joins; PK joins → no row
  multiplication; LEFT → trail membership unchanged; null-not-fabricated). `AdvancedItem` type +
  §14 selftest proof updated; `/advanced` endpoint unchanged (dict passthrough).
- Trail rows react to density (chip=code+location; compact adds format+hook; full adds
  topic+attribution+time+slot_id) and idMode (canonical code via formatter; Detailed adds the
  descriptor — its only materially-distinct part). Canonical code only when fields present, else
  raw slot_id (never fabricated). Read-only every mode.
- Validation: tsc+build clean; selftest 217/0 (§14 proves the 4 fields); api_selftest ALL PASS
  (engine touched); focused approved-trail spec proves controls present/effective/distinct +
  read-only + NO document overflow at 1280/656/375px; full Chromium 180/180 in VERIFIED stub
  (pre-suite exact stub check honored); live writer restored.
- Scope: #218 was the dependent — now UNBLOCKED (prerequisite merged+closed), stays pending for
  separate approval; #216 left open; preserved R1/#197/#169 untouched. #214 still a pending
  DUPLICATE of merged #215 (recommend closing). Lands on VPS with the next deploy.

## 2026-07-12 · #215 stale persona-scoped responses — MERGED + CLOSED (browser baseline fully green)
- PR #217 squash-merged from SAFE-TO-MERGE authorized head `8f27891` → merge `9f7a79e`;
  #215 relabeled `directive:done`, closed; branch cleaned; main synced.
- Fix (`review-context.tsx`, +authority-only): request-versioning guard (last-STARTED wins) on
  the persona-scoped AUTHORITY loaders `loadPendingApprovals` + `loadApprovalCatalog`; PLUS
  synchronous `invalidatePersonaAuthority()` on an actual persona transition (enterPersona when
  target differs; syncApprover) that bumps both sequences and clears pendingApprovals/roles/
  groups/approvalAdmin/policies — so a superseded persona can neither overwrite via late success
  NOR linger under the new badge when the new persona's authority load rejects/hangs. Same-
  persona refreshes never flicker; round/view/display state untouched.
- Proofs: two deterministic network-boundary tests (held default-persona response released after
  the picked persona commits; held new-persona authority requests never resolve → prior approvals
  vanish immediately and stay gone). persona spec 7/7; **full Chromium 176/176 (verified stub)**
  — the persona-entry two-window isolation test (the #213-era 173/174 failure) passes UNMODIFIED
  against the same accumulated DB. Baseline fully green again.
- OPERATIONAL NOTE: during validation a full-suite run was accidentally launched while the gate
  API was in LIVE writer mode (not re-stubbed after a prior restore) — several generation tests
  hit live Groq before the exact-match health check caught it; stopped, re-created stub, re-ran
  clean. Disclosed on the PR. Lesson: the pre-suite exact `"writer_mode":"stub"` check is
  mandatory before EVERY full-suite run (#179/#184 discipline).
- Residuals: `loadChanges` shares the stale-overwrite shape for round-scoped DISPLAY data (not
  authority) — disclosed, unchanged; future persona-scoped loaders must join the invalidation
  discipline; lands on STITCH-VPS with the next deploy. #214 is a pending DUPLICATE of #215
  (recommend closing as dup). #197/#169 pending untouched.

## 2026-07-12 · #212 HTTP-safe publication keys + R1 completion — MERGED + CLOSED
- PR #213 squash-merged from operator-authorized exact head `99f0c50` → merge `e405dca`;
  #212 relabeled `directive:done`, closed; branch cleaned; main synced.
- Fix: `mintOperationKey` (`lib/publication-key.ts`, disclosed proven-helper) — secure-context
  `crypto.randomUUID()` OR `getRandomValues()`-built RFC 4122 UUIDv4 (bits masked+asserted);
  no non-cryptographic fallback; no-crypto → visible plain-language failure (#186 copy fixed
  after Codex review), zero requests. Key lifecycle unchanged (mint-once per dialog open).
- Proofs: 400-key bit/uniqueness assertions both paths; real dialog without randomUUID submits
  ONE identical v4 key under duplicate-click pressure, one publication survives reload;
  no-crypto → dialog never opens, zero POSTs, jargon absent page-wide. Suite 173/174 — the one
  failure (persona-entry) REPRODUCED ON CLEAN origin/main: pre-existing stale-response race in
  loadPendingApprovals (no request versioning), made deterministic by local test-data growth;
  now pending as #215. Process note: one patch-evidence comment was posted before its commit
  was pushed — self-corrected on the PR with the verifiable head.
- Post-merge acceptance: backup verified (`tanaghom-20260711T212753Z.sql.gz`); VPS deployed at
  exact `e405dca` (runtime + both badges); the #211 crash point retested — the dialog OPENS on
  plain HTTP; ONE synthetic publication recorded on preserved R1 (instagram /
  @synthetic-acceptance-211); reconciliation pristine: 1 pub/1 occurrence, DB-regex-verified v4
  idempotency key (the getRandomValues path on the real surface), immutable events seq 1-3,
  raw junction intact, edit/post lineage, full khal attribution, reload-persistent, 1 run,
  0 non-approved gates. **The governed workflow is proven END-TO-END on STITCH-VPS through the
  durable pub.v1 receipt — the #204 objective, complete.**
- Residuals: #215 (stale-response race) pending untouched; #197/#169 pending untouched; local
  dev-DB growth noted as the #215 amplifier. R1 preserved with its completed publication.

## 2026-07-11 · #211 STITCH-VPS embeddings + R1 resume — CLOSED (STOPPED one step from receipt; no PR)
- Backup verified first (`tanaghom-20260711T191902Z.sql.gz`, sha256 `1d3c73b5…`). VPS-local
  embeddings restored: private `tanaghom-ollama` container (127.0.0.1 bind + internal network,
  never public), model `mxbai-embed-large` (config default, 1024-dim = schema), ONE host-local
  config line changed (`ollama_embed.base_url` → container address; generation routing
  untouched), container-internal probe green (dim=1024).
- Deployed exact `origin/main` `3bc290f` via runbook: runtime + BOTH badges (#205 compact 375px
  + full desktop) report the exact SHA; health live; public 200.
- **#204's boundary broken through:** R1 resumed — topic generated by the LIVE writer
  (effective route evidence: groq/llama-4-scout) + new embeddings, persisted truthfully (#207
  behavior verified: success only with persisted evidence); topic/script approved; final_review
  AND-quorum resolved with khal+huda (2 decisions); production/edit/distribution
  MANUAL-BUT-TRACKED with placeholder lineage; slot SCHEDULED; funnel → 1 done.
- **STOPPED at pub.v1 manual recording (product defect, hard stop honored, no workaround):**
  `publication-record.tsx` uses `crypto.randomUUID()` — a SECURE-CONTEXT-ONLY API, undefined
  over plain HTTP on a public IP — so the recording dialog cannot open on the internal-review
  deployment. Zero partial state (no POST, 0 publication rows). Local e2e missed it because
  http://localhost IS a secure context.
- Reconciliation pristine: 1 run, 7 gates all approved (no dupes/orphans), full attribution
  (khal 7 / huda 1 decisions), assets raw+edit+post, reload-persistent trail. **R1 PRESERVED
  one step from durable publication receipt.**
- Draft follow-up posted on #211 (not implemented): secure-context-independent idempotency-key
  generation in publication-record.tsx + focused non-secure-context test, then resume R1's
  final step. Residual: tanaghom-ollama container is now VPS runtime state. #197/#169 untouched.

## 2026-07-11 · #209 Codex-CC directive-bus bridge — CLOSED as PLANNING/STOP (PR #210 NOT adopted)
- Operator stopped #209 without merge: PR #210 closed UNMERGED, branch deleted, **zero bridge
  code on main** (verified unchanged at `3a07360`). GitHub stays the sole bus state.
- Durable findings preserved on #209/#210 (audit record; starting point for any future slice):
  * **Identity-provenance hard stop:** all bus agents share ONE GitHub account → comment
    authorship is unprovable → comment text can NEVER carry review/authorization/actor
    authority. Only label state and API-recorded actions (merges) are identity-independent
    evidence. This constrains ANY future bus automation.
  * **Live-adapter STOP:** no documented operator-configured live delivery mechanism exists
    for both clients (`codex exec` = new-session-only; CC hooks = session-boundary-only).
  * **Delivery-truth limits:** exactly-once notification only per bookkeeping epoch (GitHub
    records bus events, not delivery receipts); retry/poison needs a real delivery channel
    (future-adapter requirement, not implementable in a dry-run bridge).
  * Frozen contract decisions: 6 identity-independent state/action events; markers →
    non-authoritative candidates; transition-keyed head observations (A→B→A = new events);
    completeness-guarded gh reads (fail closed at the pagination cap); fail-closed local
    bookkeeping; universal redaction incl. local untrusted input.
- Four full Codex+GPT review cycles hardened the prototype (42/42 fixture selftests at final
  head `62375a9`) before the operator chose the STOP boundary. #209 relabeled `directive:done`,
  closed. Queue swept. No follow-up drafted — future bridge work needs a fresh directive.

## 2026-07-11 · #207 truthful generation completion — MERGED + CLOSED
- PR #208 squash-merged by the operator (merge `e84562b`, approved head `a49b682`, 16:21Z);
  #207 relabeled `directive:done`, closed; branches cleaned; main synced.
- Root cause (from preserved #204 evidence): jobs.py marks a job "done" whenever the writer
  returns, and the writer swallows per-item failures — a zero-artifact generation finished as a
  "done" job and the dashboard settled success from job status alone.
- Fix (dashboard convergence only, `review-context.tsx`): success settles ONLY on positive
  persisted stage evidence; finished-but-empty jobs fail truthfully after a 5s grace that
  re-checks fresh stage truth every poll; known job errors settle immediately with FIXED retryable
  #186 copy; raw job diagnostics are BACKEND-ONLY (page + console clean — console gets only a
  fixed job-id correlation line); evicted-/jobs recovery + timeout backstop preserved; same
  evidence gate + sanitization applied to regenerate() (shared-defect clause).
- Proofs: deterministic empty-false-success repro + console-aware hostile-text test (endpoint/
  host/traceback/token fragments absent from page AND console). Suite 171/171; tsc/build clean.
- Residuals: reaches STITCH-VPS with the next runbook deployment (with #205); partial-count
  wording out of slice; no dedicated rework-failure e2e; #204 residuals stand (embedding
  endpoint decision + preserved R1). #209 PENDING — not started. #197/#169 pending untouched.

## 2026-07-11 · #205 responsive build reference — MERGED + CLOSED
- PR #206 squash-merged by the operator (merge `3bc5af6`, approved head `429ef7a`, 14:32Z);
  #205 relabeled `directive:done`, closed; branches cleaned; main synced.
- Below `md` the header now shows a compact always-visible `build <sha>` indicator
  (`runtime-badge-compact` / `runtime-build-compact` / `reset-local-state-compact`) fed by the
  SAME /api/runtime state — TANAGHOM_BUILD_SHA-only truth, `unknown` when unstamped, no new
  fallbacks — and carrying the scoped reset action. Desktop full badge + testids unchanged.
- Proofs: 5 responsive Playwright checks (375/700 compact + controls intact + zero horizontal
  overflow; 768/1280 full badge exact + compact yields; persona-entry fresh-window coverage).
  tsc/build clean; suite 169/169.
- NOT deployed to STITCH-VPS in this closeout (explicit instruction) — lands with the next
  runbook deployment. #204 residuals stand: embedding endpoint decision, preserved run R1,
  generation false-success toast. #197/#169 pending untouched.

## 2026-07-11 · #204 STITCH-VPS clean-slate acceptance — CLOSED (STOPPED at first invariant failure; no PR)
- Operational acceptance only. VPS updated to exact `a3d94dc`: backup verified FIRST
  (`tanaghom-20260711T133920Z.sql.gz`, sha256 `37a9aadb…`), copied tree converted to a REAL git
  checkout via content-only bundle over operator SSH (zero tracked drift), images rebuilt,
  proxy refreshed. ALL #202 readiness checks PASS on the VPS: runtime build `a3d94dc` exact,
  live writer, least-privilege key-name audits, public 200, canonical `5|5|5|42|4|1|0`, 0 runs.
- ONE synthetic run `R1` (label SYNTH-ACCEPT-204, 1 slot `R1-D01-S1`) via the normal UI:
  schedule gate `9f76cc57…` opened→decided→resolved by khal, slot `SCHEDULE_APPROVED`,
  moved-forward trail durable across reload. Run PRESERVED — do not purge.
- **STOPPED at topic generation (hard stop honored, nothing repaired):** job `0fec046c9501`
  failed — host-local `config/system_config.yaml` points embeddings/Ollama at
  `host.docker.internal:11434` (workstation assumption; unresolvable on Linux Docker, no
  embedding service on the VPS). 0 topics persisted; writer-LLM viability on the VPS UNPROVEN.
  Secondary PRODUCT defect: UI toast claimed "Generated 1 item(s) — ready to review" for the
  failed job (server state stayed correct).
- Reconciliation at stop: exactly 1 run, 1 gate (approved, attributed), no duplicate/orphan
  gates, 0 publications. Matrix + verdict + ONE draft follow-up directive (embedding endpoint
  decision, resume acceptance on preserved R1) posted on #204.
- Residuals: stale VPS `.env` keys (`POSTGRES_PASSWORD`, `NEXT_PUBLIC_BUILD_SHA`) = dead config
  flagged for operator cleanup; inert `dashboard/Dockerfile.dashboard` leftover on VPS tree;
  row-13 false-success toast needs its own small product directive; #197/#169 untouched.

## 2026-07-11 · #202 STITCH-VPS deployment baseline — MERGED + CLOSED
- PR #203 squash-merged by the operator (merge `daaca71`, approved head `04ec13d`, 12:50Z);
  #202 relabeled `directive:done`, closed; branches cleaned; main synced.
- Tracked scaffold: `deploy/stitch-vps/**` (compose/Dockerfiles/nginx/scripts/runbook,
  placeholder-only `.env.example` with `!.env.example` negation past the repo-wide `*.env.*`
  ignore) + root `.dockerignore` (build context excludes `.git`, all `.env*`, `deploy/`,
  backups, dumps). Only port 80 public; app/API localhost-bound.
- Hardening from review + self-review: SINGLE DB credential source (host `DB_PASSWORD`
  interpolated to db as `POSTGRES_PASSWORD` and to gateapi, both `:?`-required — drift class
  eliminated, clean-volume auth proof green); `/api/runtime` build identity is server-runtime
  `TANAGHOM_BUILD_SHA` ONLY (exact or explicit `unknown`; baked `NEXT_PUBLIC_BUILD_SHA` never
  consulted — real-image proofs stamped/unstamped+stale-bake); writer-live = empty/absent
  (`"0"` is stub-truthy — example fixed); API image no longer ingests backups/host config.
- Product touches: `Optional run name` placeholder (#186); operator-authorized one-liner
  `dashboard/pnpm-workspace.yaml` allowBuilds fix (clean-host `pnpm install --frozen-lockfile`
  was failing on the tracked placeholder — proven from a detached worktree, Option 1 recorded
  on #202).
- Runbook + checklist: backup-before-update, schema/idempotent migrations, catalog loader,
  build stamping, `up -d --build`, PROXY UPSTREAM REFRESH after dashboard recreation, env
  key-name audit (names only), runtime identity, live-writer exact match, health, public HTTP,
  canonical baseline `5|5|5|42|4|1|0` (SQL validated against the real schema).
- Validation at merge: tsc + build clean; Playwright 164/164 (3 new focused checks); both
  images built from a clean worktree at head; clean-volume + real-image runtime proofs.
- NOTE for local suites: start the dashboard with `TANAGHOM_BUILD_SHA=$(git rev-parse --short
  HEAD)` — the #180 badge asserts a non-unknown build and the route no longer reads the bake.
- Residuals: NEXT directive = clean-slate e2e acceptance on STITCH-VPS (no run created; update
  the VPS to `daaca71` via the runbook first). OIDC + TLS/domain deferred; #187 = secret
  authority.

## 2026-07-11 · #200 pub.v1 publication persistence + governed manual recording — MERGED + CLOSED
- PR #201 merged by the operator (squash `5e2bb0e`, reviewed head `360c96f`, 09:12Z); #200
  relabeled `directive:done` and closed; local/remote branches cleaned; main synced.
- Schema (migration 022, operator-authorized incl. the recorded junction amendment):
  `publication` (intent + ≤1 set-once occurrence, frozen identity/lineage/destination, occurrence
  evidence frozen after recording), `publication_event` (append-only, per-intent UNIQUE seq,
  `event_seq >= 1` CHECK), `publication_raw_asset` junction (native NO ACTION FKs both sides —
  MVCC-correct, race-proven; freeze trigger pins set membership). Intent creation is DB-atomic:
  DEFERRABLE INITIALLY DEFERRED constraint requires ≥1 junction row AND the canonical
  seq=1 `intent_created` event at COMMIT of the creating transaction.
- Semantics: caller-reserved idempotency key (exact replay converges, changed-data = 409);
  eligibility = RESOLVED approved gates only; authority = DIRECT user gate assignment only
  (role/group grants nothing, #9-safe); success re-verifies the COMPLETE frozen lineage
  (3 gates, script, edit asset+version+rendition, raw set) — drift denies with `stale_lineage`
  audit naming fields; scoped-unique external refs; corrected repost = new linked intent.
- Surfaces: 4 signed endpoints (`POST /publications`, `POST …/manual-outcome`,
  `GET /publications`, `GET /platforms`) + distribution-stage recording UI (#186 language).
- Resets: selftest/api_selftest/Playwright + demo round-purge all purge publication truth
  (junction → events → publications) inside single transactions with guard triggers re-enabled.
- Validation at merge: selftest 216/216 (§18=34 incl. MVCC overlap races + per-field stale
  proofs), api ALL PASS, tsc clean, Playwright 161/161, live writer restored.
- Residuals: trial-stack refresh bundle = migrations 020+021+022; reserved lifecycle events typed
  but command-less (future slice); B1 batch-resolve UX + B3 direct-user-only authority stand as
  accepted reviewed behavior; migration fails explicitly on preexisting invalid event sequences.

## 2026-07-11 · #199 publication-receipt contract freeze (planning) — CLOSED (no PR, no mutations)
- Read-only; `pub.v1` contract frozen on the issue. Adversarial review ran FIRST over the amended
  chain Production (governed, manual-executed — NOT missing) → SDAM raw readiness → Edit → exact
  final approved Edit output → Publication; all ~16 adversarial cases answered inline.
- Contract: SEPARATE `publication_intent_id` vs `publication_occurrence_id`; monotonic attempts;
  DB-enforced idempotency domain (provider_key, destination_account_ref, idempotency_key) with
  bound immutable fields + hard conflict on reuse-with-different-data; provider-local external_ref
  scoped by account; exact FK lineage incl. distinct gate/SDAM-readiness prerequisites; two
  authority predicates (content eligibility ≠ actor execute/attest authority); reconciliation
  links provider receipts to the SAME occurrence or flags divergence — never overwrites;
  corrected repost = new linked intent; retraction = event, original immutable; BrandShield joins
  by occurrence id + scoped external ref, never URL/title.
- **Persistence verdict: REQUIRES EXPLICIT ADDITIVE MIGRATION AUTHORIZATION** — asset table has
  PK+indexes only (no idempotency uniqueness; media semantics = prohibited overload, per the #198
  correction), audit_log jsonb = prohibited free-form invariants. Bounded 2-table shape defined.
- Draft implementation directive included, classified **BLOCKED PENDING EXPLICIT OPERATOR
  MIGRATION AUTHORIZATION** — not posted, not executable. #9 stays PARTIAL (no closure claim).

## 2026-07-11 · #198 M9 lifecycle rebaseline (planning) — CLOSED (no PR, no mutations)
- Read-only stage matrix + ownership + lineage posted on the issue; done + closed.
- Key truth: the M9 contract layer is richer than narrative suggests — directives/DAM/manual
  executors/gates BUILT or MANUAL-BUT-TRACKED through edit (e2e-proven RPROD/REDIT/RDIST);
  AVP/POSTIZ/analytics are honest CONTRACT/STUB ONLY (`integrations/`, all enabled:false);
  lineage breaks AFTER approved edit: no publication/receipt entity, nothing for BrandShield
  to join. Two n8n planes kept distinct; Tanaghom n8n = documented intentional deferment.
- **Selected slice (drafted, NOT implemented, SAFE TO IMPLEMENT IMMEDIATELY): manual publication
  completion with truthful receipts** — record the operator's real publish as a governed audited
  receipt (existing asset model, NO schema), closing plan→publish visibly and creating the exact
  join point POSTIZ/BrandShield need later.
- Smallest external inputs requested: (1) a BrandShield-side interface note (its stack composition
  is operator-confirmed, not repo-verifiable); (2) POSTIZ reachability + receipt shape (needed
  before ITS adapter, not before the slice). Falsification review performed (11 checks; two
  partial falsifications honestly recorded: external-ref discipline + provider descriptors).

## 2026-07-11 · #196 reconcile #9 approval semantics (planning) — CLOSED (no PR, no mutations)
- Read-only reconciliation posted on the issue; done + closed. #9 state deliberately NOT changed
  (recommendation only).
- Matrix: A (ANY/ALL, test-backed) DELIVERED · B (snapshots vs membership churn) DELIVERED ·
  C (reviewer visibility = engine truth, incl. #175) DELIVERED · **D (audit basis) PARTIAL** —
  the matched assignment token (user: vs role:) is not persisted per decision; role/group-
  satisfied approvals lose explainability after membership churn.
- Implementation-derived semantics recorded: ALL = one approval per assignment TOKEN (not per
  member), quorum frozen at gate open, matching live at decide, membership changes affect future
  eligibility only, reject > request_change > approve precedence.
- **Recommendation: KEEP #9 OPEN** for exactly ONE closing slice (drafted on #196, not
  implemented): persist `assignment_basis` in the decide audit detail — engine-only, NO schema.
- Adversarial self-review performed: all cells cited; nothing marked missing; basis gap verified
  against schema + repo-wide grep; follow-up duplicates nothing.

## 2026-07-11 · #194 governed identity-binding lifecycle + immediate revocation (#172 S2) — CLOSED
- PR #195 squash-merged `854cc9d` (approved head `7d02476`) at 2026-07-10T22:57:06Z; issue done +
  closed; branches deleted; queue swept (only #169 pending, legitimately deferred).
- Delivered through TWO merge-gate review rounds (6 findings + 2 blockers, all proof-backed):
  bounded /admin/identity "Sign-in connections" surface; insert-only create + CAS lifecycle
  (principal_id in NO update — reassignment structurally impossible); advisory-lock-serialized
  last-usable-admin lockout guard scoped to the trusted issuer; per-request binding revalidation
  on BOTH authority-bearing BFF routes (/gw + /api/chat — chat no longer honors client-supplied
  actors under IAM); authenticate-then-parse create (signed malformed input attributably audited;
  unauthenticated noise never audited); exact opaque subjects; canonical issuer from server config
  ONLY. Audit events: identity_binding.{created,deactivated,reactivated,denied,conflict}.
- **Accepted residual: gate-API TANAGHOM_OIDC_ISSUER must be configured + verified before IAM
  lifecycle administration is enabled — absent config FAILS CLOSED** (with TANAGHOM_SESSION_SECRET,
  these are the IAM deployment requirements).
- Other residuals: reassignment = future governed design; S3 (signature/JWKS, per-session proof,
  #10 resolve); offboarding semantics; broad /principals readability = pre-existing hardening
  note; trial refresh bundle now = migrations 020+021 + #177 sync + #180. Baseline 158/158 green.

## 2026-07-10 · #192 #157 seed/spec reconciliation (validation stabilizer) — CLOSED
- PR #193 squash-merged `7b2934f` at 2026-07-10T17:23:53Z; issue done + closed (stale `running`
  label fixed); branches deleted.
- Verdict: STALE SPEC ONLY — #157's seed/UI/doc contract is coherent; the inline-edit spec's
  clean-state subject moved RSCR-1 → RSCR-3 (seeded clean since #177), preserving the flip-proof.
  No seeded product truth changed; no hard-stop.
- **Baseline fully green: chromium 154/154, zero residuals** — the #157 conflict is retired from
  the standing-residuals list. Remaining residuals: trial-stack refresh bundle (020+021, #177
  sync, #180), IAM S2/S3 candidates, #169/#179-drill deferred, #186/#187 reference-only.

## 2026-07-10 · #190 user_identity binding + flagged OIDC at the BFF (#172 S1) — CLOSED
- PR #191 squash-merged `b8e7c4b` at 2026-07-10T16:45:12Z (incl. re-review patch `64ac55e`);
  issue done + closed; branches deleted.
- IAM proves identity; Tanaghom decides authority — implemented: migration 021 `user_identity
  (issuer,subject)→principal` (additive, authorized); SELECT-only resolver refusing inactive/
  non-user bindings; system-gated `GET /identity/binding`; flagged OIDC (code+PKCE, discovery,
  provider-pluggable) at the BFF; httpOnly HMAC session carries the principal resolved once at
  callback; /gw signs ONLY the bound principal (401 no session / 403 unbound, truthful screen);
  persona mechanisms ignored + switch endpoint 403 under IAM; flag off = byte-identical demo.
- Self-review findings fixed pre-PR (unbound badge lie; silent demo fallback on half-config;
  constant-time cookie compare) + merge-gate patch (strict aud/azp per OIDC Core 3.1.3.7 with 5
  pure-logic tests; #186 plain-language copy). Suite 148/149 flag-off (lone red = #157).
- Residuals: S2 bind/unbind surface; S3 signature verification + per-session proof + #10 resolve
  residual; provider procurement = operator call pre-production; TANAGHOM_SESSION_SECRET required
  (fail-closed) outside dev; migration 021 joins the trial-stack refresh bundle.

## 2026-07-10 · #188 protocol/skill hardening + protocol-doc landing — CLOSED
- PR #189 squash-merged `cc96d3f` at 2026-07-10T15:12:29Z; issue done + closed; branches deleted.
- Repo now carries the protocol: mandatory ordered merge-gate sequence (GPT review BEFORE merge
  when applicable; patch resets the gate) + consumed-directive normalization/queue sweep in
  `docs/directive-bus/README.md`; CLAUDE.md landed with the executor mirror (check latest comments
  for pause/supersession before pickup) + test-ops traps (exact writer_mode match; no concurrent
  api_selftest+e2e). AGENTS.md + THIS log are now tracked files (append-only in-repo record —
  future entries show as pending repo changes until batched).
- Machine-local `~/.codex/skills` hardened in place (loop: 8-step merge-gate checklist + queue
  normalization; browser: claim-visible-tab, composer disambiguation + fill verification,
  final-verdict wait signals, finalize-on-correct-tab). Not repo files.

## 2026-07-10 · #172 IAM strategy + user→principal mapping (planning) — CLOSED (no PR)
- Read-only planning; full architecture note on the issue; issue done + closed (no mutations).
- Decision: OIDC at the dashboard BFF (provider-pluggable; develop vs self-hosted Keycloak-class,
  hosted IdP stays a drop-in later — NO vendor procurement made); **`principal` stays canonical**
  with a new `user_identity (issuer,subject) → principal` binding (super-admin-gated, audited);
  `/gw` signs the AUTHENTICATED principal — the x-principal-* contract and the entire authority
  plane (assignments/policies/hard-floors/policy_admin) are untouched. IdP claims never drive
  authorization. AgentRep = agent principals owned via `owner_id` (asymmetric authority preserved).
- #170 persona entry stays demo-mode-only (#180 server-declared); later becomes governed
  impersonation. Slices: S1 binding+flagged login → S2 bind/unbind surface → S3 per-session proof
  (+ #10 resolve residual) → S4 impersonation/tenants. S1 is the recommended next directive.
- Risks logged: provider ops vs procurement, binding lifecycle, agent machine identity,
  library-version verification deferred to S1, trial-stack flag isolation.

## 2026-07-10 · #184 managed topic-repetition policy (strict default + governed exceptions) — CLOSED
- PR #185 squash-merged `283ab75` at 2026-07-10T14:02:12Z (incl. review patch `ced2964`); issue
  done + closed; branches deleted.
- Topic generation now defaults to NO same-topic reuse across ALL prior history (replaces the
  too-narrow config `scope: hcs`, #183). Policy is DB-managed (operator-authorized additive
  migration 020) with one central engine resolver; repeats only under explicit managed modes —
  supported set is exactly [cross_format], flagged `repeat_allowed_cross_format` + audited
  (`repetition_policy_exception_used`) on every use; own-slot revisions never count as repeats.
- Governance: `GET/PUT /repetition-policy` on the signed-principal path, gated via the
  config-driven `engine.policy_admin` seam (content_owner/khal = today's top authority;
  AgentRep-remappable). Writes audited before/after; denials audited. PUT is a SPARSE update
  (review fix): omitted fields preserve managed state. `/admin/methodology` discloses the active
  policy read-only.
- Validation: selftest §15 + api_selftest #184 (9 checks) all green; suite 145/146 (#157 lone red).
  NOTE: Groq TPD quota nearly exhausted today by earlier live-mode test accidents — agent-endpoint
  sections 429 until the window rolls; test runs must stay stub + sequential.
- Residuals: trial stack needs migration 020 (+#177 sync, #180 hardening) at next operator-scoped
  refresh; Slice-2 candidates (policy-edit UI, cross_platform when slot-level platform exists,
  card-level repeat flags). #186/#187 = standing audit/reference issues, not active execution.

## 2026-07-10 · #180 runtime-mode truth + stale-state resilience — CLOSED
- PR #182 squash-merged `ae64997` at 2026-07-10T11:52:11Z; issue done + closed; branches deleted.
- The Opera stale-cookie incident fixed at three layers: operator middleware DELETES stale
  `client_trial` cookies; new `/api/runtime` declares surface (same env middleware enforces) +
  build sha (baked at build: env → git rev-parse → unknown); `useClientTrialMode` treats the
  cookie as advisory pre-paint and adopts the server answer. Persona-entry gating follows.
- Shell self-identifies: `operator/internal · stub|live writer · <sha>` badge + "Reset local view
  state" (clears ONLY tanaghom-* keys, trial cookie, reviewer cookie via scoped DELETE; reloads).
- Genuine trial mode regression-proven against a REAL CLIENT_TRIAL_MODE instance (locked, labeled,
  /admin bounces). `runtime-truth.spec.ts` (4 tests); persona-entry stale-cookie expectation
  updated to the new truth. Suite 145/146 — lone red still the #157 seed/spec conflict.
- Residual: trial-stack instance gets this + #177 registry sync at the next operator-scoped trial
  refresh; badge sha updates on the next routine rebuild (cosmetic).

## 2026-07-10 · #179 durable approved-items trail (post-commit visibility) — CLOSED
- PR #181 squash-merged `0d406d4` at 2026-07-10T11:02:31Z; issue done + closed; branches deleted.
- Committed stages now keep a durable read-only "Approved & moved forward" panel: item-level
  (id/hook/format/approver/time) + current location, derived from EXISTING resolved-gate decision
  rollups + live slot rows via new read-only `GET /rounds/{id}/stages/{stage}/advanced`
  (`engine.list_advanced` + config-driven `_slot_location`). No new persistence; survives reload;
  staged-uncommitted approvals excluded; reopened items truthfully return to the queue.
- selftest §14 (6 checks) + `approved-trail.spec.ts` (2 tests incl. reload persistence). Full suite
  141/142 — lone red is still the #157 seed/spec conflict.
- Test-ops lessons (for the next CLAUDE.md batch): never run api_selftest concurrently with the e2e
  suite on the shared DB; verify writer mode with an exact `"writer_mode"` match (`grep stub` also
  matches `"writer_stub":false` — this silently ran one suite against live Groq, 429s).
- Deferred: optional Overview drill-through into the approved set (follow-up candidate).

## 2026-07-10 · #177 framework registry truth + fallback transparency (#50/#93/#149) — CLOSED
- PR #178 squash-merged `895ebb7` at 2026-07-10T09:05:18Z; issue done + closed; branches deleted.
- Root cause: the Hero Reel 10-beat structure was keyed `reel_studio` (retired CANON name) in
  CONTENT_FRAMEWORK_RULES → never merged into the operational `hero_reel` registry entry → UI
  silently showed generic BUILD/TURN/CLOSE as client framework. Re-keyed; live dev registry now
  hero_reel v2 `bootstrap-sync` 10 steps via the new idempotent `sync_content_format_seed()`
  (digest-based, versioned, never overrides operator-authored versions).
- UI: script cards disclose fallback/legacy/stale structure states; truthful counts (Carousel =
  "7 framework steps" + promoted-hook badge); methodology admin states configured vs legacy vs
  missing. Pic + Caption explicitly `legacy_carry_forward` (no fabricated structure).
- RSCR fixture now 4 slots (managed hero RSCR-3, legacy pic RSCR-4); selftest §13 added.
- **Residuals:** trial-stack registry still has old hero data (operator-scoped sync at next trial
  refresh); #157 seed/spec conflict unchanged; `co-creation:47` flake now 2/4 recent full runs —
  stabilization follow-up directive recommended.
- **Post-merge runtime reset (operator-requested, confirmed):** dev DB purged of all 21 test rounds
  (run-derived state only, FK-safe, catalogues intact; pre-reset pg_dump kept LOCALLY in the session
  scratchpad — not uploaded). Stack verified green: live writer, :3000 serving `895ebb7`, empty
  rounds, registry truth live. Verification comment posted on #177. E2E fixture rounds (RE2E/RSCR/…)
  are gone until the next suite run reseeds them — expected.

## 2026-07-10 · #175 not-assigned reviewer UX (#9/#13, urgent trial fix) — CLOSED
- PR #176 squash-merged `be3cd8d` at 2026-07-10T08:10:02Z; issue done + closed; branches deleted.
- Non-assigned personas now get a view-only banner (who's acting, who the gate requires, how to
  proceed) with all decision controls disabled; assignment judged from SERVER truth only (gate
  snapshot direct-user match + `/me/pending-approvals` for role/group — client never re-derives
  membership); backend `not configured`/`not_assigned` denials map to client-safe guidance.
  Engine decide/audit untouched (#10 evidence cited). #170 persona behavior intact.
- New reusable fixture: `gates/e2e_schedule_seed.py` → RSCH round with an open khal-only
  `schedule_review` gate (the live-trial scenario). Full suite 136/137 — lone red is still the
  pre-existing #157 seed-vs-spec conflict (`script-inline-edit.spec.ts:34`), follow-up candidate.
- Executor idle: next execution waits for the framework-registry directive (operator instruction).

## 2026-07-10 · #170 internal/demo persona entry (#13 S1) — CLOSED
- PR #173 squash-merged `6caa071` at 2026-07-10T07:03:43Z; issue done + closed; branches deleted.
- Fresh internal browser windows now pick a known persona on an entry overlay (select-only, labeled
  internal/demo, "not a login"); persona is window-scoped (`sessionStorage` → `x-tanaghom-persona`
  header on `/gw`; proxy validates then signs server-side) so parallel windows hold different
  personas; always-visible "acting as" badge in the shell; client-trial mode unaffected; inline
  switcher pins only its own window. #10 decide-time enforcement untouched.
- e2e note: playwright.config now starts contexts as an established `khal` session (storageState);
  `persona-entry.spec.ts` (5 tests) opts out to cover the fresh-browser path.
- **Pre-existing defect found on `main` (not #170):** `script-inline-edit.spec.ts:34` fails since
  #157's seed set RSCR-1 `needs_native_review: True` while the pre-#157 spec asserts `false` at the
  seed assertion. Deterministic; latent (post-#157 runs were targeted). Follow-up directive
  candidate: test-only fixture reconciliation.
- Also deferred: #169 (operator-guide screenshot refresh) stays `directive:pending` per operator.

## 2026-07-10 · #167 living operator guide (#46 S2 execution) — CLOSED
- PR #168 squash-merged `3bc7249` at 2026-07-10T06:09:37Z; issue done + closed; branches deleted.
- New `docs/product-help/operator-guide.md` (internal-only banner, 12 stable anchors) + 5 `op-`
  screenshots; README manifest row + `op-` convention. Deployment state (ports/DBs/links/creds)
  generalized to verify-at-use-time — none in the guide. Persona switching = operational identity
  (not auth, #13) with the #123/#147 decide-time authorization nuance.
- Deferred: recapture `op-01`/`op-04`/`op-05` post-#134/#136 header (`screenshot refresh pending`
  markers in the guide). `client-guide.md` untouched; `artifacts/` untouched.

## 2026-07-10 · #166 operator-guide truth contract (#46 S2 planning) — CLOSED (no PR)
- Read-only planning; report on the issue; issue done + closed (filing directive, no code).
- Contract: `docs/product-help/operator-guide.md` (internal-only banner, mirrored anchors, `op-`
  screenshot prefix); 5/8 seed screenshots reusable, 3 refresh-pending (pre-funnel-strip header);
  deploy-state facts (ports/ngrok/creds) stay "verify at use time", never client-side.
- Recommended next slice: bounded docs-only operator-guide adaptation — independent of #13/#20/#44/#45.

## 2026-07-10 · #164 living user-guide source of truth (#46 S1) — CLOSED
- PR #165 squash-merged `99dedbc` at 2026-07-09T23:01Z; issue done + closed; branches deleted.
- New `docs/product-help/`: living `client-guide.md` (stable section anchors for #44/#45,
  Last-reviewed header), feedback template, 8 screenshots, README maintenance manifest
  (owner-review gate, refresh checklist, `screenshot refresh pending` rule — 2 markers open).
- Finding: `artifacts/` is gitignored by design → dated trial snapshots are a LOCAL operator
  archive; documented truthfully, snapshots untouched.

## 2026-07-10 · #159 Arabic/RTL card readability (#54 S1) — CLOSED
- PR #162 merged `a2a69e0` at 2026-07-09T20:27Z; issue done + closed; branches deleted.
- Blueprint-header badge cluster now one wrapped group (dropped the `ml-auto` on the #154 model
  badge — it tore the cluster apart in the two-column layout); English "Topic through-line" label
  stacked above the Arabic quote (was trailing inline in the RTL hero column).
- 11/11 targeted Playwright at 1440px + 820px; tsc clean. Semantics/testids from #149/#154/#157 intact.

## 2026-07-09 · #157 dialect target context (#151 S2) — CLOSED
- PR #158 merged `b8752a1` at 19:50Z; issue `directive:done` + closed; branches deleted.
- Script review cards now show a stage-level `target · Arabic (Palestinian dialect / ar-PS)` badge
  (intent, per the #156 truth contract) + a separate `marked for native review` badge from the
  persisted `needs_native_review`. No residuals.

## 2026-07-09 · #154 script model attribution (#151 S1) — CLOSED
- PR #155 merged `c364c17` at 16:53Z; issue closed.
- Review card + version history surface the persisted `script.model` (`provider:model` label) with an
  explicit "model not recorded" state; topics intentionally show nothing (no persisted equivalent).

## 2026-07-09 · #152 fresh-build provenance fix — CLOSED
- PR #153 merged `ca7d961` at 16:10Z; issue closed.
- Root cause: any `next/dynamic()` inside a client-entry module breaks Next 15.1.4 RSC
  client-manifest registration → fresh builds 500 the route. **Repo rule: use `React.lazy`, never
  `next/dynamic`.** Also: kill dashboard by port (`kill $(lsof -tnP -iTCP:3000 -sTCP:LISTEN)`) —
  `pkill -f "next start"` misses the renamed `next-server` process.

## 2026-07-09 · #149 registry-driven script structure (#146 S2) — CLOSED
- PR #150 merged `33d20fb`; issue closed.
- Writer emits/validates structure keys from the content-format registry
  (`production_rules.structure`); review cards label beats from the same registry map; explicit
  4-beat fallback; hero opening registry-aware. `formatFamily` headings deferred to S3.
