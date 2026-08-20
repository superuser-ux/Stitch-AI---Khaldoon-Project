# Directive Bus

A low-friction, human-gated channel for moving directives from **GPT/Codex planning**
to **Claude Code** (primary executor) using **GitHub issues** as the shared bus.

Why this shape: GPT/Codex can inspect the repo, issues, PRs, reports, and runtime evidence; Claude Code
executes the bounded implementation pass and writes the corresponding GitHub artifacts. GitHub is the
shared audit medium across both sides of the loop.

## Lifecycle (labels)

| Label | Meaning | Set by |
|-------|---------|--------|
| `directive:pending` | queued, awaiting human approval | ChatGPT's Action (or a manual paste) |
| `directive:approved` | cleared to run | **you** (the gate) |
| `directive:running` | Claude Code is executing | Claude Code |
| `directive:done` | finished; see the report comment | Claude Code |
| `directive:blocked` | stopped; needs a human decision | Claude Code |

## Attribution (who did what)

All three agents act under one GitHub account, so every artifact is also stamped with an **agent label**
for traceability, filterable in GitHub (`label:agent:gpt`, etc.):

| Label | Applied by | To |
|-------|-----------|-----|
| `agent:gpt` | ChatGPT's Action | every directive it posts (alongside `directive:pending`) |
| `agent:cc` | Claude Code | the PRs (and issues) it opens |
| `agent:codex` | Codex | the work it opens |

Additionally, GPT **assigns each directive to `Kholio`** so it appears in the operator's GitHub
"Assigned to me" inbox. Commit `Co-Authored-By` trailers and body signatures further distinguish authors.

## Flow

1. **ChatGPT** drafts a directive and (on your confirmation) posts it as an issue labelled
   `directive:pending`. See [`SETUP.md`](./SETUP.md) for the one-time GPT Action wiring; if the Action
   isn't set up yet, you can paste the directive into a new issue yourself and add the label.
2. **You** review the issue and replace **`directive:pending`** with **`directive:approved`** — the only
   thing that authorises execution.
3. **Claude Code**: run `tools/next-directive.sh` (or just say *"run the next directive"*). It picks the
   oldest `directive:approved` issue, posts a short **ACK/plan** comment, relabels `directive:running`,
   executes (branch → PR → merge, per the directive), then posts its standard **report** comment and
   relabels `directive:done` before closing the issue (or `directive:blocked` with a precise reason).
   The closed issue remains the audit record for that directive.
4. **ChatGPT** reads the report + merged PR and plans the next directive.

## Working loop (Codex + GPT + CC)

The current operating pattern is slightly stricter than the basic bus:

1. **Codex/GPT review gate**: before a new directive is approved, GPT reviews it for duplication, scope
   drift, missing acceptance, and whether it should be approved, deferred, or split.
2. **Operator approval gate**: execution starts only after the operator replaces `directive:pending` with
   `directive:approved`.
3. **CC execution gate**: Claude Code flips `directive:approved` to `directive:running` only when it
   actually starts work, not earlier.
4. **PR merge gate**: CC holds at the merge gate after opening the PR and posting validation evidence.
   GPT/Codex may review the PR, but merge happens only after explicit operator approval.
5. **Closeout gate**: after merge, the executor syncs state, relabels the issue `directive:done`, closes
   it, and reports any follow-up directive candidate separately.

## ETA-based execution monitoring

Every dispatched or long-running directive-bus task must have an explicit ETA and observation schedule.
This applies to CC implementation, validation, GPT review, merge follow-through, and post-merge closeout.
The ETA is an operational estimate, not an authorization boundary or permission to broaden scope.

At dispatch, the orchestrator records the current state, concrete next checkpoint, ETA or bounded ETA
range, scheduled inspection times, and the primary expected risk or long-running command.

Minimum inspection cadence:

| ETA | Required checks |
|-----|-----------------|
| 5 minutes or less | at the ETA |
| 6-10 minutes | midpoint and ETA |
| 11-15 minutes | 5, 10, and 15 minutes |
| more than 15 minutes | roughly one-third intervals, never more than 10 minutes unobserved; use 5-minute checks for elevated risk, session saturation, or recent instability |

Each check uses live evidence rather than requesting a recap. Verify material progress, the active
command/process, scope adherence, duplicate or repeated work, blockers or approval requests, session
saturation, transport failures, and branch/head/worktree/GitHub state when relevant.

Checkpoint reports use:

```text
state | evidence of progress | revised ETA | next check | risk
```

The orchestrator revises the ETA after every inspection. Shorten it when completion is near. Extend it
when a healthy long-running step legitimately needs more time, and reschedule the next check instead of
polling unnecessarily. Intervene immediately when progress is abnormal, a command exceeds a credible
duration, the executor cycles or repeats work, scope expands, or a genuine blocker appears; do not wait
for the original ETA. A revised ETA never hides a blocker or delays a human gate.

Do not claim automatic monitoring unless a real wake, timer, automation, or active orchestration wait is
in place. After a restart or missed wakeup, reconstruct the ETA from live session/process/GitHub evidence
and resume the cadence from the current state.

## Product configuration-generation guardrail

This guardrail applies to **every** directive, review, handoff, implementation, and acceptance pass.
It prevents trial shortcuts or bootstrap defaults from becoming accidental product architecture.

### Core rule

Tanaghom is adaptive across **governed configuration generations**, not arbitrary within an active
generation. A policy change applies prospectively; a run, action, or external handoff records the
resolved policy/version that governed it. Historical evidence is never silently reinterpreted.

This applies to methodology, framework/catalogue, model-route preference, roles/capabilities,
workflow and approval policy, and integration selection. It does **not** mean every value belongs in
the database: secrets, endpoint/topology wiring, build identity, and non-user-editable runtime safety
limits remain environment/file managed.

### Required distinction

Every directive that reads or changes a mutable product setting must state:

1. the baseline default and its authoritative source;
2. the authorized organization/user override boundary;
3. whether AI may recommend a change, and the human/governed commit point;
4. the policy/version snapshot boundary for active runs/actions and external handoffs;
5. audit/provenance behavior for a later policy change; and
6. which values remain runtime/deployment/secret configuration.

Do not use a static code allowlist, a seed synchronizer, or a trial-only lifecycle mutation as a
substitute for a governed default. Do not let a bootstrap seed overwrite operator-owned policy.
If the existing model cannot preserve the required snapshot/version truth without a schema or authority
change, stop and report that requirement rather than approximate it.

### Initialization rule

This rule applies to **every governed policy/configuration generation**, not only to trial or
non-production topology. Bootstrap, seed, reset, and migration initialization operations must never
overwrite existing operator-owned configuration. They may create missing baseline records only;
reruns must be idempotent and non-destructive. An initialization path that would change an
operator-set value must instead leave it unchanged (or stop and report), never silently reconcile a
governed default over an authorized override.

### Trial rule

Trial status means generated workflow data may be reset and the current deployment topology is
non-production. It does not create a separate framework, methodology, model, role, workflow, or
integration semantics. A current baseline default remains a real product default even when it is being
exercised in a trial.

### Directive overlap rule

Before a directive is approved, the planner must check the delivery clusters recorded in #242 and state
which existing issue it consumes, links, or defers. One coherent slice owns a user-facing API/read-model/
UI/lifecycle correction; adjacent work must not reopen the same surface independently.

## GitHub transport precedence (Codex lane)

Codex must use the GitHub transports in this order for directive-bus reads and writes:

1. **Codex app GitHub connector** — default for private-repository issue/PR state, comments, labels,
   review evidence, and merge-gate checks. Verify it with a real repository read, not only the green
   connection indicator in app Settings.
2. **`gh` CLI** — fallback only when its authenticated account can read `Kholio/tanaghom`.
3. **In-app GitHub browser session** — interactive recovery/login fallback only; do not make it the
   normal transport for mechanical directive-bus work.

Do not substitute an unrelated or legacy MCP GitHub connection for the Codex app connector. A connector
being reachable but returning `404`/unauthorized for the private repository is not a valid bus path.
If the primary connector is available, use it even when the local `gh` token is stale. If no path can
perform a real repository read, stop GitHub state-changing work, report the authentication boundary, and
resume from the shared GitHub artifact after access is restored. Never fall back to copying private issue
or PR state through chat as if it were authoritative.

## Merge-gate order (mandatory, #188)

The merge sequence is ordered and verifiable — never from memory:

1. verify live PR state (open, mergeable, current head, validation evidence posted);
2. decide whether GPT review is required — **when required, the GPT review happens BEFORE merge**,
   and a patch/re-review cycle restarts this sequence (an earlier review does not carry over a patch);
3. verify explicit operator approval for the current head — GPT approval never authorizes a merge;
4. merge only after BOTH gates are satisfied;
5. verify post-merge normalization (labels `running` → `done`, issue closed, branches cleaned);
6. executor closeout (the 7-step protocol), then verify the final closed state.

## Playwright validation tiers (#263 — one contract, zero retries)

Every tier is serial, single-worker, **zero-retry** (config-enforced); a failure is reported
truthfully, never retried until it passes; `gates.api_selftest` never overlaps Playwright on the
shared DB (#179). Commands run from `dashboard/`. See `CLAUDE.md` "Validation tiers".

- **Inner loop:** affected spec(s) only — `npm run test:spec -- e2e/<file>.spec.ts`.
- **PR checkpoint:** explicit relevant spec pack **+ `tsc --noEmit` + production build** —
  `npm run test:pr -- e2e/<relevant>.spec.ts`. The build is mandatory; a targeted run never claims
  unrelated coverage.
- **Immutable merge head:** exactly **one** full Chromium suite in **stub writer mode** against the
  **exact merge-approved SHA**, after all patches/reviews — `npm run test:full`. Any code change,
  rebase, base merge, or SHA change invalidates it and requires a fresh full-suite gate at the new
  head — this is the merge-gate order's SHA-freshness rule (#188) made concrete for the full suite.

The completion report binds evidence to the exact tested SHA: tier + command, exact included specs,
writer mode, worker/retry config, retry count, result, and the api-selftest non-overlap confirmation.

## Consumed-directive normalization (queue verifiability, #188)

The `directive:approved` queue must only contain directives that are genuinely executable right now:

- a planning/diagnosis directive **consumed or superseded** by a later directive must not remain
  `approved` or otherwise look executable — leave a traceable GitHub note naming what consumed it,
  then relabel (`done` if satisfied, `pending` if deferred) and close when satisfied;
- a paused/reordered directive gets its label normalized immediately — executors must never have to
  discover a pause buried in comments;
- **after every merge/closeout, sweep the queue** and normalize anything the merge made moot. Queue
  verifiability is part of closeout, not optional hygiene.

## Ownership boundaries

- **Codex** is the protocol/orchestration owner for the loop: queue checks, GPT review prompts, PR-readiness
  checks, and post-merge normalization.
- **Claude Code** is the primary execution worker for implementation directives.
- **Planning-only directives** may be executed by Codex directly when they stay read-only and do not touch
  the active execution surface.
- **Never run Codex and Claude Code as parallel implementers on the same directive/files/runtime surface.**

## Proportional safeguards for trial work

Trial and demo data is ephemeral by default unless a directive explicitly says otherwise. Keep safeguards
proportional so the bus does not turn reversible trial work into production ceremony:

- use synthetic fixtures, record the few values being changed, keep direct rollback steps, and run focused
  validation;
- do not add full backups, disaster-recovery drills, production hardening, procurement, or migration-level
  governance merely because trial state is being changed;
- retain strict handling for secrets, client or production data, irreversible/destructive actions, authority
  and security boundaries, schema commitments, and production deployments;
- if an executor believes stronger safeguards are materially necessary, stop before adding them and surface
  the reason, cost, and scope impact for an explicit operator decision.

## Claude Code Codex plugin policy

If Claude Code has the official `openai/codex` plugin installed, it remains **out of the protocol by
default**.

Allowed use, only when explicitly invoked:
- bounded `rescue` on a blocked directive
- bounded adversarial/review pass on a PR
- bounded transfer into a Codex thread

Not allowed:
- acting as a second orchestrator
- GitHub label/issue-state authority
- merge authority
- unbounded parallel implementation on the active directive

If the plugin is used, CC must say so explicitly, state the bounded target problem, and route any scope or
merge recommendation changes back through the normal GitHub/GPT/operator gate.

## Guarantees / oversight

- **Nothing runs without your `directive:approved` label**, applied with your own GitHub account.
- Claude Code **ACKs its understanding before touching code**, so a mis-parse is caught first.
- Every step is a GitHub artifact (issue, labels, comments, PR) — fully auditable and readable by ChatGPT.
- The GPT's token is scoped to **Issues read+write and Pull-requests: read on this one repo** — propose-only.
  It has **no** merge, PR-write, or contents-write authority: GPT can *read* PR state to plan, but cannot
  perform the merge itself. Merge still requires explicit operator approval even if a human or Codex runs
  the merge command after that approval. Never grant the bus token merge rights.

## Transport note (why the proxy)

ChatGPT custom-GPT Actions cannot call the GitHub REST API directly: they send **no `User-Agent`** header
and **ignore** any header you add in the schema, and GitHub 403s every request without one. So the GPT
talks to a tiny **Cloudflare Worker proxy** (`ops/directive-proxy/`) that adds the User-Agent + the real
GitHub token and forwards only the whitelisted issue operations. **Use the proxy schema/setup below** —
the direct `gpt-action-schema.json` is kept only as a record of the direct-API attempt.

## Files

- [`PROXY-SETUP.md`](./PROXY-SETUP.md) — **deploy the Worker (wrangler) + wire the GPT.** ← start here.
- [`gpt-action-schema.proxy.json`](./gpt-action-schema.proxy.json) — the GPT Action schema (points at the Worker).
- [`gpt-instructions.md`](./gpt-instructions.md) — paste into the GPT's Instructions.
- [`project-context.md`](./project-context.md) — stable context primer for the GPT.
- `../../ops/directive-proxy/` — the Cloudflare Worker (`worker.js` + `wrangler.toml`).
- `../../tools/next-directive.sh` — Claude Code's fetch helper.
- [`SETUP.md`](./SETUP.md) / [`gpt-action-schema.json`](./gpt-action-schema.json) — superseded direct-API
  attempt, kept for reference.
