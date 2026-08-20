// #293 Stage 0 — the exact, closed boundary V2 is allowed to consume.
//
// WHY AN ALLOWLIST, NOT A PASS-THROUGH PROXY:
// V1's /gw is an authority-bearing proxy: it resolves an IAM session to a bound principal,
// revalidates the binding on every request for immediate revocation (#194), and signs
// x-principal-id/x-principal-signature so the gate API can authorise at decide time (#10).
// Re-implementing any of that in V2 would be a frontend-local replacement of a conserved contract
// — an explicit #293 hard stop.
//
// It is also unnecessary. The gate API deliberately splits its read model:
//   - GET /health, GET /rounds, GET /rounds/{id}  -> no principal required (verified against
//     gates/api.py:248,487,692 and by live request: 200 with no principal header)
//   - GET /me/pending-approvals and friends       -> _require_trusted_principal (verified: 401)
// So V2's Stage 0 seam reads ONLY what the API itself leaves unguarded. V2 signs nothing, holds no
// REVIEWER_PROXY_SECRET, and cannot become a parallel authority path.
//
// This list is the whole contract. Anything not matched here is refused by V2 before a request is
// ever made — V2 cannot reach a guarded endpoint even by accident or by a future careless edit.
// Widening it is a governed decision for the slice that needs it, never an incidental change.

/** A round identifier as issued by Tanaghom. Canonical IDs are opaque to V2 — never parsed,
 *  derived, or reinterpreted here; this pattern only bounds what may be put in a URL path. */
const ROUND_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/;

/** #355 — the gates whose generic per-stage READS this slice serves. Exactly the Scripts gate for
 *  now; widening it is a governed decision for the slice that needs it. */
const SERVED_GATES: ReadonlySet<string> = new Set(["script_review"]);

/** R1 Stage 4 — the canonical gate whose Final Review surface THIS BUILD serves.
 *
 *  A build declaration, not a workflow assumption. It states which canonical gate V2 has a surface
 *  for, exactly as `stage-rail.ts`'s IMPLEMENTED_GATES does, and it can only ever NARROW what the
 *  governed workflow artifact already authorises. It does not declare that a Tanaghom workflow has a
 *  final-review stage, does not enable one, and does not make one appear: a governed version that
 *  omits or disables `final_review` yields no rail entry, no panel, and no reachable read — this
 *  constant simply never matches. */
const FINAL_REVIEW_GATE = "final_review";

export type AllowedPath = { readonly segments: readonly string[] };

/** Returns the upstream path if it is inside V2's READ boundary, else null. */
export function resolveAllowedPath(segments: string[]): AllowedPath | null {
  // Defence in depth: reject traversal/empty segments before any pattern matching.
  if (segments.some((s) => !s || s === "." || s === ".." || s.includes("/") || s.includes("\\"))) {
    return null;
  }
  if (segments.length === 1 && segments[0] === "health") return { segments };
  // Developer operations status: one exact guarded read, signed server-side by the /gw route.
  // It returns only materialization freshness/source metadata and can never enumerate or read OpenBao.
  if (segments.length === 3 && segments[0] === "admin"
      && segments[1] === "secrets" && segments[2] === "status") {
    return { segments };
  }
  // #443 — the read-only Settings-truth projection: provider kind, safe endpoint identity, model
  // identity + existing route-role labels, presence/type-only secret references, and
  // configured-state-only availability. Exposes NO secret value/name and mutates nothing; signed
  // server-side by the /gw route exactly like the secrets-status read (a bounded admin read).
  if (segments.length === 3 && segments[0] === "admin"
      && segments[1] === "settings" && segments[2] === "truth") {
    return { segments };
  }
  // IAM administration reuses the gate API's audited, policy-admin-authorized binding lifecycle.
  // These exact reads expose no credential material and mint no product authority.
  if (segments.length === 2 && segments[0] === "identity" && segments[1] === "bindings") {
    return { segments };
  }
  if (segments.length === 1 && segments[0] === "principals") return { segments };
  if (segments.length === 1 && segments[0] === "rounds") return { segments };
  // #331 — the current baseline-eligibility policy + its eligible frameworks (the exact read #276/#271
  // expose to the governed New-run form). Unguarded upstream (gates/api.py:507, no principal required),
  // exactly like the rest of the run read model, so it belongs on the READ allowlist. A pure read: V2
  // renders the eligible frameworks and validates nothing — the planner owns the mix contract.
  if (segments.length === 1 && segments[0] === "baseline-eligibility") return { segments };
  if (segments.length === 2 && segments[0] === "rounds" && ROUND_ID.test(segments[1])) {
    return { segments };
  }
  // #292 — the round's accepted display mapping + combined schedule token (unguarded upstream,
  // same as the rest of the round read model).
  if (segments.length === 3 && segments[0] === "rounds" && ROUND_ID.test(segments[1])
      && segments[2] === "schedule-mapping") {
    return { segments };
  }
  // #314 Stage 2B-2 — the round's accepted Topic-workbench PRESENTATION order + its token (distinct
  // from #292 schedule order). Unguarded upstream, exactly like the rest of the round read model, so it
  // belongs on the READ allowlist; the governed reorder WRITE is added separately to
  // resolveAllowedWritePath. A pure read: V2 renders it and interprets nothing.
  if (segments.length === 3 && segments[0] === "rounds" && ROUND_ID.test(segments[1])
      && segments[2] === "topic-presentation") {
    return { segments };
  }
  // #310 §F — the round's Stage 2A Topic-generation read model (job phase/counts/error + per-slot
  // results + provenance disclosure). Unguarded upstream, exactly like the rest of the round read
  // model, so it belongs on the READ allowlist. It stays a pure read: the retry WRITE is deliberately
  // NOT added to resolveAllowedWritePath — retry requires a SIGNED principal (the existing binding)
  // and V2 signs nothing (#293). A V2-initiated signed retry would be the forbidden frontend-local
  // authority replacement; V2 observes here and routes any retry to the authorized surface instead.
  if (segments.length === 3 && segments[0] === "rounds" && ROUND_ID.test(segments[1])
      && segments[2] === "generation") {
    return { segments };
  }
  // #313 Stage 2B-1 — the canonical per-item Topic read model (topic_item: status, head/approved
  // revision, immutable revision history + parent/base lineage, and the typed available/denied action
  // map) and the raw revision chain. Both are unguarded upstream reads — topic angle/hook are already
  // surfaced via /rounds/{id}/generation — so they belong on the READ allowlist. The surface renders
  // the server-owned action map verbatim; it never infers which actions are permitted.
  if (segments.length === 3 && segments[0] === "slots" && ROUND_ID.test(segments[1])
      && (segments[2] === "topic_item" || segments[2] === "revisions")) {
    return { segments };
  }
  // #419 — the read-only Stage 4 approval-package preflight for one canonical slot. An unguarded
  // upstream pure-read (gates/api.py `slot_stage4_preflight`) that aggregates existing canonical
  // records into stable typed reason/denial codes + structured evidence (consumed vs active workflow
  // identity kept distinct; fail-closed). GET only; it mutates nothing and generates no production
  // direction, so it belongs on the READ allowlist. The surface renders the server verdict verbatim.
  if (segments.length === 3 && segments[0] === "slots" && ROUND_ID.test(segments[1])
      && segments[2] === "stage4_preflight") {
    return { segments };
  }
  // #423 — the read-only immutable final-review target-package evidence for one (gate, slot). An
  // unguarded upstream pure-read (gates/api.py `gate_slot_target_package`) returning typed
  // recorded/unknown_history/unavailable evidence. GET only; it mutates nothing and invokes no
  // attachment/authority logic, so it belongs on the READ allowlist. The surface renders it verbatim.
  if (segments.length === 5 && segments[0] === "gates" && ROUND_ID.test(segments[1])
      && segments[2] === "slots" && ROUND_ID.test(segments[3]) && segments[4] === "target-package") {
    return { segments };
  }
  // #427/#429 — the read-only Stage 4 final-review projection for one admitted (gate, slot). An
  // unguarded upstream pure-read (gates/api.py `gate_slot_final_review_projection`) returning the
  // authoritative typed projection (independent evidence groups, fail-closed uncertainty, gate-scoped
  // non-slot-attributable audit). GET only; it mutates nothing and invokes no attachment/authority
  // logic, so it belongs on the READ allowlist. Same closed (gate, slot) identifier boundary as the
  // adjacent #423 target-package entry; the surface renders it verbatim.
  if (segments.length === 5 && segments[0] === "gates" && ROUND_ID.test(segments[1])
      && segments[2] === "slots" && ROUND_ID.test(segments[3]) && segments[4] === "final-review-projection") {
    return { segments };
  }
  // #447 — the read-only Stage 4 approval-package preflight for one admitted (gate, slot). An
  // unguarded upstream pure-read (gates/api.py `gate_slot_approval_preflight`) returning the
  // unconditional six-member immutable package tuple, the current governed workflow version, present
  // final-review eligibility, the STRUCTURAL human hard-floor, and the existing production direction
  // as downstream evidence — or canonical typed denials in deterministic precedence order. GET only;
  // it mutates nothing, generates no production direction, evaluates no caller, discloses no
  // principal, and cannot authorize production, so it belongs on the READ allowlist. Same closed
  // (gate, slot) identifier boundary as the adjacent #423/#427 entries; the surface renders it
  // verbatim.
  if (segments.length === 5 && segments[0] === "gates" && ROUND_ID.test(segments[1])
      && segments[2] === "slots" && ROUND_ID.test(segments[3]) && segments[4] === "approval-preflight") {
    return { segments };
  }
  // #355 — the ACTIVE governed workflow version: the single configuration-generation artifact that
  // declares the lifecycle stages (stage_key, gate_stage, enabled, label, ordinal, generator_kind,
  // writer_mode, generates_from) for the current generation. Unguarded upstream (gates/api.py:1358
  // takes no Request and asserts no principal), exactly like the rest of the read model.
  //
  // V2 derives its ENTIRE stage rail from this and nothing else — there is deliberately no local
  // stage table to drift from it. See lib/stage-rail.ts.
  //
  // SIDE-EFFECT-FREE BY CONSTRUCTION, and that is why it is this endpoint and not
  // `/workflow-versions/active`. That one calls `_ensure_workflow_seed`, which — when no active
  // version exists — INSERTs the workflow row with `ON CONFLICT ... DO UPDATE SET name,
  // description`, i.e. it can OVERWRITE an operator-owned workflow row's metadata as a side effect
  // of a GET. An earlier revision of this slice used it and described it as merely
  // "create-missing-only"; that was wrong, and ordinary navigation must never mutate what it is
  // describing. `/workflow-stages/active` is a pure SELECT that 404s when nothing is active.
  if (segments.length === 2 && segments[0] === "workflow-stages" && segments[1] === "active") {
    return { segments };
  }
  // #376 ruling A — the CANONICAL ACTIVE-STAGE PROJECTION: the same governed generation, reduced by
  // the server to the stages it actually enables. The rail consumes THIS, so a disabled stage is
  // absent because the generation disabled it — not because a client filtered it out. Consuming
  // `/workflow-stages/active` and dropping `enabled=false` here would be a client-local policy
  // decision about which governed stages count, i.e. the omission list #376 forbids. Same posture as
  // the endpoint above: unguarded, side-effect-free, 404 when nothing is active.
  if (segments.length === 2 && segments[0] === "workflow-stages" && segments[1] === "active-enabled") {
    return { segments };
  }
  // #376/#377 — the governed run-mix recommendation READS.
  //
  // `run-mix-policy` is the CURRENT recommendation-policy generation (or a truthful `absent`), and
  // `recommendation-snapshot` is a run's IMMUTABLE recommendation evidence, resolved only from the
  // pinned snapshot. Both are unguarded upstream (no principal asserted, gates/api.py) exactly like
  // the rest of the run read model, and both are pure reads: V2 renders what the authority computed
  // and recomputes, re-derives and re-weighs nothing. The POLICY-ADMINISTRATION write
  // (`POST /run-mix-policy`) and retention (`/run-mix-proposals/purge`) are deliberately NOT here —
  // declaring governed weights and purging retention are not workbench controls.
  if (segments.length === 1 && segments[0] === "run-mix-policy") return { segments };
  if (segments.length === 3 && segments[0] === "rounds" && ROUND_ID.test(segments[1])
      && segments[2] === "recommendation-snapshot") {
    return { segments };
  }
  // #355 — the generic per-stage read model for the Scripts stage: lifecycle state (+ advisory) and
  // the committed approved/advanced trail. Both unguarded upstream (gates/api.py:1453, :1540).
  // Restricted to `script_review` so the boundary stays exactly as wide as this slice needs; a
  // different stage is a governed decision for the slice that needs it.
  // The gate is supplied by the GOVERNED mapping (`workflow_stage.gate_stage`), so it is matched as
  // a bounded identifier rather than a literal — a version may map the Scripts stage to a renamed
  // key. It stays narrow: only `state`/`advanced`, only for gates this slice serves. A governed
  // mapping pointing at a gate outside this set is refused here, which is the fail-closed outcome.
  if (segments.length === 5 && segments[0] === "rounds" && ROUND_ID.test(segments[1])
      && segments[2] === "stages" && SERVED_GATES.has(segments[3])
      && (segments[4] === "state" || segments[4] === "advanced" || segments[4] === "action")) {
    return { segments };
  }
  // R1 Stage 4 — the Final Review stage's LIFECYCLE STATE read, and ONLY `state`.
  //
  // Deliberately a separate entry rather than a widening of SERVED_GATES. That set admits
  // `state|advanced|action` together, and neither of the other two belongs here: `action` is a
  // literal `/stages/script_review/action` route upstream (a final-review request would 404), and
  // `advanced` is a post-commit trail this slice does not render. Adding the gate to SERVED_GATES
  // would have quietly opened both. The boundary stays exactly as wide as the slice needs.
  //
  // This read is what makes Final Review reachability SERVER-DERIVED: it returns the canonical
  // `gate_id` of the stage's active open gate (or null), the lifecycle `state`, the governed counts,
  // and the server's own warnings/recommendation. V2 renders that and concludes nothing — it does not
  // decide whether a final review exists, which gate it is, or whether anything may advance.
  // Unguarded upstream (`gates/api.py stage_state` takes no Request), exactly like the reads above.
  if (segments.length === 5 && segments[0] === "rounds" && ROUND_ID.test(segments[1])
      && segments[2] === "stages" && segments[3] === FINAL_REVIEW_GATE && segments[4] === "state") {
    return { segments };
  }
  // R1 Stage 4 — the CANONICAL gate detail for one gate: its status, governed assignments, and the
  // server-authored TARGET list with each target's `current_outcome`.
  //
  // WHY THIS READ IS NECESSARY AND WHY NOTHING ELSE WOULD DO. The Final Review surface must act on the
  // exact slots the canonical gate governs. The only alternatives are client-side inference — reading
  // `/rounds/{id}` and selecting slots by status, or assuming the round's slots are the gate's targets
  // — and both are the forbidden client-side eligibility determination: they would silently disagree
  // with the gate whenever reconciliation, partial batches, or a re-escalated sign-off gate made the
  // target set a subset. The gate's own target list is the only truthful source, and `current_outcome`
  // is likewise the server's, never re-derived from decisions here.
  //
  // Unguarded upstream (`gates/api.py gate_detail` takes no Request), like the rest of the read model.
  // It is READ-ONLY from V2's side; the self-heal reconcile it performs upstream is the gate API's own
  // long-standing behaviour on every gate view (V1 included), not something this seam introduces.
  if (segments.length === 2 && segments[0] === "gates" && ROUND_ID.test(segments[1])) {
    return { segments };
  }
  return null;
}

/**
 * #355 — the COMPLETE enumerated QUERY boundary. Exactly one parameter, on exactly one path.
 *
 * WHY THIS EXISTS AT ALL. Until now `/gw` built the upstream URL from path segments only and
 * forwarded no query string. That is safe for every existing read, but it makes one upstream read
 * actively DANGEROUS to consume: `GET /slots/{id}/revisions` takes `artifact` and **defaults to
 * `topic`** (gates/api.py, engine.list_revisions:1626). A Scripts lens that requested revisions
 * without the parameter would silently receive TOPIC history and render it as script history —
 * fabricated evidence under a truthful-looking heading.
 *
 * So the capability is deliberately not "forward the query string". It is: forward exactly
 * `artifact=script`, on exactly this path, or refuse. There is no default and no fallback:
 *   - artifact ABSENT      -> refused (never silently the topic default)
 *   - artifact DUPLICATED  -> refused (no last-wins ambiguity)
 *   - artifact != "script" -> refused
 *   - ANY other parameter  -> refused (nothing arbitrary is ever forwarded)
 *   - a query on any OTHER allowlisted path -> refused
 *
 * The refusal is what makes "no topic fallback" structural rather than a convention someone must
 * remember: if the parameter is ever dropped, the request FAILS instead of returning the wrong
 * artifact. Widening this is a governed decision for the slice that needs it, never an incidental
 * edit — exactly like the path allowlists above.
 */
export function resolveAllowedQuery(segments: readonly string[], search: URLSearchParams): string | null {
  const keys = [...search.keys()];
  if (segments.length === 2 && segments[0] === "identity" && segments[1] === "bindings") {
    if (keys.length !== 2 || !keys.includes("limit") || !keys.includes("offset")) return null;
    const limit = search.getAll("limit");
    const offset = search.getAll("offset");
    if (limit.length !== 1 || offset.length !== 1) return null;
    if (!/^\d+$/.test(limit[0]) || !/^\d+$/.test(offset[0])) return null;
    const limitNumber = Number(limit[0]);
    const offsetNumber = Number(offset[0]);
    if (limitNumber < 1 || limitNumber > 100 || offsetNumber < 0) return null;
    return `limit=${limitNumber}&offset=${offsetNumber}`;
  }
  if (segments.length === 1 && segments[0] === "principals") {
    const expected = new Set(["kind", "active", "module"]);
    if (keys.length !== expected.size || keys.some((key) => !expected.has(key))) return null;
    if (search.getAll("kind").length !== 1 || search.get("kind") !== "user") return null;
    if (search.getAll("active").length !== 1 || search.get("active") !== "true") return null;
    if (search.getAll("module").length !== 1 || search.get("module") !== "content") return null;
    return "kind=user&active=true&module=content";
  }
  const slotPath = segments.length === 3 && segments[0] === "slots" && ROUND_ID.test(segments[1]);
  // `revisions` defaults to TOPIC upstream and is actively dangerous to consume without pinning, so
  // artifact is REQUIRED and must be exactly "script".
  const isRevisions = slotPath && segments[2] === "revisions";
  // #367 — `topic_item` also defaults to topic upstream, but the EXISTING topic workbench reads it
  // with NO artifact (the topic default). So here artifact is OPTIONAL: absent keeps that topic
  // default unchanged; present must be exactly a single "script". Widening for the Script slice that
  // needs it, without breaking the topic surface — and never a silent script→topic fallback.
  const isTopicItem = slotPath && segments[2] === "topic_item";
  if (keys.length === 0) return isRevisions ? null : "";        // revisions requires artifact
  if (!isRevisions && !isTopicItem) return null;
  if (keys.length !== 1 || keys[0] !== "artifact") return null;
  const values = search.getAll("artifact");
  if (values.length !== 1 || values[0] !== "script") return null;
  return "artifact=script";
}

/**
 * #292 — the COMPLETE enumerated WRITE boundary. Exactly one operation.
 *
 * This is the minimum #292 requires and nothing more (Codex secondary ruling 2): not a general
 * write proxy, not a prefix match, not "POST anything under /rounds". Adding an entry here is a
 * governed decision for the slice that needs it — never an incidental edit.
 *
 * The upstream endpoint enforces authority itself (_require_schedule_authority) and the token
 * contract; V2 asserts identity server-side only and interprets nothing.
 */
export function resolveAllowedWritePath(segments: string[]): AllowedPath | null {
  if (segments.some((s) => !s || s === "." || s === ".." || s.includes("/") || s.includes("\\"))) {
    return null;
  }
  if (segments.length === 3 && segments[0] === "rounds" && ROUND_ID.test(segments[1])
      && segments[2] === "schedule-reorder") {
    return { segments };
  }
  if (segments.length === 2 && segments[0] === "identity" && segments[1] === "bindings") {
    return { segments };
  }
  if (segments.length === 4 && segments[0] === "identity" && segments[1] === "bindings"
      && ROUND_ID.test(segments[2])
      && (segments[3] === "deactivate" || segments[3] === "reactivate")) {
    return { segments };
  }
  // #304 — the run's governed absolute placement: the SECOND enumerated write, added as a governed
  // decision for the slice that needs it (a truthful run calendar is impossible without an
  // authoritative start, and #304 forbids deriving one from created_at). It stays an EXACT match,
  // not a prefix — POST elsewhere under /rounds is still refused and V2 is still not a general write
  // proxy. Upstream owns authority, the freeze predicate and the token contract; V2 interprets none
  // of them and merely relays the typed refusal.
  if (segments.length === 3 && segments[0] === "rounds" && ROUND_ID.test(segments[1])
      && segments[2] === "placement") {
    return { segments };
  }
  // #304 Level 2 — the governed single-slot schedule revision (#271). Third enumerated write, added
  // as a governed decision for the slice that needs it. Upstream owns the ENTIRE decision: which
  // fields are revisable (_SCHEDULE_REVISION_FIELDS = day, time_uae, format, topic_guidance),
  // pinned-policy eligibility, the schedule_review authority, the token, and the downstream freeze.
  // V2 proposes and renders the typed refusal; it validates nothing itself.
  if (segments.length === 3 && segments[0] === "slots" && ROUND_ID.test(segments[1])
      && segments[2] === "schedule-revision") {
    return { segments };
  }
  // #313 Stage 2B-1 — the governed per-item Topic MUTATIONS: structured edit and restore-as-new-
  // revision. Fourth/fifth enumerated writes, added as a governed decision for the slice that needs
  // them, under the SAME posture as the schedule writes above: EXACT match (not a prefix — POST
  // elsewhere under /slots is still refused), upstream owns the ENTIRE decision (whitelisted fields,
  // expected-revision CAS, idempotency replay, and fail-closed eligibility that leaves #249
  // unconsumed), and the /gw route asserts the signed principal server-side ONLY in an explicit
  // dev/test runtime (IAM-on fails closed). V2 proposes and relays the typed 409 refusal; it validates
  // and reinterprets nothing, and mints no authority of its own.
  if (segments.length === 3 && segments[0] === "slots" && ROUND_ID.test(segments[1])
      && (segments[2] === "edit" || segments[2] === "restore")) {
    return { segments };
  }
  // #313 Stage 2B-1 — the rest of the governed per-item Topic action family, same EXACT-match posture:
  //   rework_from     — restore-then-regenerate (inherits eligibility + CAS; records job-less provenance);
  //   drop            — reversible governed disposition (fail-closed on approved/downstream-advanced);
  //   request_change  — governed send-back with an attributable rationale (routes to the gate);
  //   approve         — RECORDS a governed approval decision through the gate (authority + quorum). It
  //                     never advances or pins: the advance/pin is the HUMAN commit floor, never run by
  //                     V2's signed principal. Upstream owns all authority; V2 relays the typed refusal.
  if (segments.length === 3 && segments[0] === "slots" && ROUND_ID.test(segments[1])
      && (segments[2] === "rework_from" || segments[2] === "drop"
          || segments[2] === "request_change" || segments[2] === "approve")) {
    return { segments };
  }
  // #367 — the governed Script review lifecycle completes the per-item action family with the two
  // recovery/undo transitions, SAME EXACT-match posture as the family above: `reopen` reverses a
  // dropped OR just-approved item back to the review status (recoverable drop-restore), and `undecide`
  // clears an UNCOMMITTED gate decision (clear/undo) without touching committed history. Upstream owns
  // the ENTIRE decision (canonical transition, authority, and the fact that neither deletes committed
  // decision history); V2 proposes and relays the typed refusal, and mints no authority of its own.
  if (segments.length === 3 && segments[0] === "slots" && ROUND_ID.test(segments[1])
      && segments[2] === "reopen") {
    return { segments };
  }
  if (segments.length === 3 && segments[0] === "gates" && ROUND_ID.test(segments[1])
      && segments[2] === "undecide") {
    return { segments };
  }
  // #314 Stage 2B-2 — the governed BULK Topic disposition and the Topic-workbench PRESENTATION reorder.
  // Same EXACT-match posture: POST elsewhere under /rounds is still refused. Upstream owns the ENTIRE
  // decision — the closed action set, per-item exact-revision CAS + idempotency (bound to a canonical
  // request digest), fail-closed membership/authority/eligibility, the truthful per-item outcome ledger,
  // and (for the reorder) the presentation token + exactly-one-winner. V2 proposes and renders the typed
  // partial/stale/denial/conflict results; it validates and mints nothing.
  if (segments.length === 3 && segments[0] === "rounds" && ROUND_ID.test(segments[1])
      && (segments[2] === "bulk-operations" || segments[2] === "topic-presentation-reorder")) {
    return { segments };
  }
  // #331 — governed RUN CREATION. `POST /rounds` (the single planner entry, gates/api.py:519) plans a
  // fresh governed-from-birth run and returns {round_id,total}. It is body-only upstream (the planner
  // owns the entire mapping/eligibility contract; V2 asserts nothing and relays the typed 409/422). Added
  // as a governed decision for the schedule-first Create-run slice — still an EXACT single-segment match,
  // never a prefix, so V2 remains not a general write proxy.
  if (segments.length === 1 && segments[0] === "rounds") {
    return { segments };
  }
  // #376/#377 — the governed run-mix RECOMMENDATION request. `POST /run-mix-proposals` asks the
  // canonical authority what mix a prospective run should have; it returns either a typed
  // recommendation with immutable provenance or a typed BLOCKED state, and a blocked result persists
  // nothing at all. It creates NO run: no slots, no gates, no history, no workflow — only a durable
  // single-use fence that expires. That is why it can be reached from an ephemeral composer without
  // breaking "a date gesture never creates durable run state": the run itself is still minted only by
  // the explicit `POST /rounds` above, and the fence is what makes the submitted mix provably the one
  // the operator was shown. Upstream owns the entire decision (owner binding, generations in force,
  // digest); V2 renders the typed result and computes no mix of its own.
  if (segments.length === 1 && segments[0] === "run-mix-proposals") {
    return { segments };
  }
  // #376 — the SIDE-EFFECT-FREE recommendation preview. It is a POST only because it carries a body and
  // signs the owner (same posture as run-mix-proposals), NOT because it mutates: upstream persists no
  // proposal, no audit and no reserved identifier. The composer shows THIS while the operator composes;
  // a durable proposal is minted only by the explicit Plan run (`POST /run-mix-proposals`). Keeping the
  // preview off the durable path is what makes GPT amendment 4 — "no durable side effect before submit"
  // — structural rather than a UI promise. Upstream owns the calculation; V2 computes no mix of its own.
  if (segments.length === 1 && segments[0] === "run-mix-recommendation-preview") {
    return { segments };
  }
  // #331 — the CANONICAL manual Topic generation start (#332). `POST /rounds/{id}/stages/topic_review/
  // generate` is the SINGLE governed generation mechanism (never a second command path): the merged #332
  // engine AUTHENTICATES the /gw-signed principal and AUTHORIZES it against the run's immutable Schedule
  // affirmative-approver set, then activates the pinned manual job. Restricted to the `topic_review`
  // stage — the config stage whose writer_mode is `topics` (system_config `gates.topic_review`), the
  // only stage this lane triggers — so the write boundary stays exactly as wide as the slice needs. V2
  // mints no authority: it proposes and relays the typed activated/lifecycle/automatic/denied outcome.
  if (segments.length === 5 && segments[0] === "rounds" && ROUND_ID.test(segments[1])
      && segments[2] === "stages" && segments[3] === "topic_review" && segments[4] === "generate") {
    return { segments };
  }
  // #449 — the CANONICAL final-review SIGN-OFF command (#439/#440). Added as a governed decision for
  // the V2 action slice that needs it, under the same EXACT-match posture as every entry above: a
  // 5-segment match, never a prefix, so POST elsewhere under /gates is still refused and V2 remains
  // not a general write proxy.
  //
  // Upstream owns the ENTIRE decision and V2 duplicates none of it. `SignOffBody` is `extra="forbid"`
  // with exactly five fields, so no actor/principal/role/authority field can be sent even by mistake;
  // the signed principal is resolved SERVER-SIDE by this route and authorized by the gate API against
  // persisted Tanaghom authority; `engine.sign_off` owns the package comparison, the idempotency
  // digest, the one-time tuple rule, present-state revalidation, the receipt and its audit, and the
  // typed refusal. V2 forwards the four binding fields exactly as the #447/#448 preflight authored
  // them, adds an opaque idempotency key for deduplication only, and relays the typed result verbatim.
  // It infers no authority, re-derives no tuple, and mints nothing of its own.
  if (segments.length === 5 && segments[0] === "gates" && ROUND_ID.test(segments[1])
      && segments[2] === "slots" && ROUND_ID.test(segments[3]) && segments[4] === "sign-off") {
    return { segments };
  }
  // R1 Stage 4 — the CANONICAL gate APPROVAL AUTHORITY and the CANONICAL LIFECYCLE TRANSITION. The two
  // enumerated writes that complete the Final Review vertical, added as a governed decision for this
  // slice, under the same EXACT-match posture as every entry above: three segments, never a prefix, so
  // POST elsewhere under /gates is still refused and V2 remains not a general write proxy.
  //
  // THESE ARE THE EXISTING AUTHORITY, NOT A NEW ONE. `decide` is `engine.decide` — the same command V1
  // and every other caller uses, owning the open-gate check, the frozen-eligibility authorization, the
  // assignment/quorum contract, the per-slot audit, and the typed refusal. `resolve` is
  // `engine.resolve` — the same single lifecycle transition, owning quorum application, the governed
  // `approve_to` move, loopback, generation guards, idempotency and reconciliation. V2 creates no
  // second decision service, no second resolve service, and no new transition.
  //
  // WHY BOTH, AND WHY SEPARATELY. Recording a decision and applying it are DISTINCT server operations
  // with distinct authority, and the current governed workflow behaviour is that a human invokes each
  // explicitly. Exposing only one would have made the vertical unreachable; fusing them behind a single
  // seam entry would have hidden that ordering and pre-empted a future governed policy's freedom to
  // trigger the pair server-side. They are therefore two entries, invoked by two explicit gestures.
  //
  // NO AUTHORITY IS MINTED HERE. `DecideBody.approver_id` and `ResolveBody.actor` exist upstream for
  // legacy/low-level callers; V2 sends NEITHER. The /gw POST route resolves and signs the principal
  // SERVER-SIDE (and refuses to sign at all outside a declared local/dev/test runtime when IAM is off),
  // and `_trusted_approval_actor` authorizes that principal against persisted Tanaghom authority. V2
  // forwards only the canonical target and the server-authored revision, and relays the typed result.
  if (segments.length === 3 && segments[0] === "gates" && ROUND_ID.test(segments[1])
      && (segments[2] === "decide" || segments[2] === "resolve")) {
    return { segments };
  }
  // #357 — the CANONICAL Script generation command. Sixth enumerated write, added as a governed
  // decision for the slice that needs it, under the same exact-match posture.
  //
  // #355 kept this OFF the boundary for a specific, proven reason: the route applied trusted-principal
  // authorization only inside `mode == "topics"`, so exposing it would have put an UNAUTHENTICATED
  // write on V2's seam. #357 closes exactly that gap — the shared command now authorizes Script
  // generation against the frozen affirmative authority of the accepted topic_review decision on every
  // caller (V1, V2, agents). The precondition that blocked exposure is gone, so the entry is added.
  //
  // Upstream owns the ENTIRE decision: authority, the pinned manifest, replay, concurrency and the
  // typed denial. V2 proposes and relays; it mints nothing and re-derives no eligibility.
  if (segments.length === 5 && segments[0] === "rounds" && ROUND_ID.test(segments[1])
      && segments[2] === "stages" && segments[3] === "script_review" && segments[4] === "generate") {
    return { segments };
  }
  return null;
}

/** True when the runtime has IAM/OIDC turned on. */
export function iamEnabled(): boolean {
  return ["1", "true", "yes", "on"].includes(
    (process.env.TANAGHOM_OIDC_ENABLED || "").trim().toLowerCase(),
  );
}

export const API_BASE = process.env.API_BASE || "http://localhost:8009";
