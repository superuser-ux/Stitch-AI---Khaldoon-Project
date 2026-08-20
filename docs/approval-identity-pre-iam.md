# Approval identity — the temporary pre-IAM trust model (#10)

**Status:** interim model, deliberately minimal. This documents how the acting user behind an
approval action is established **today**, what it does and does not protect against, and the
upgrade path to a real IAM. It exists so nobody mistakes the current mechanism for enterprise
authentication — and so the eventual IAM swap is a bounded, already-mapped change.

## The chain (who the server believes you are)

1. **Self-asserted reviewer selection (dev/trial only).** The browser picks a reviewer id via
   `POST /api/reviewer` (`dashboard/app/api/reviewer/route.ts`); it is stored in an `httpOnly`
   cookie (`tanaghom_reviewer`, default `khal`). There is **no password or credential** — in the
   pre-IAM model, identity is asserted at the dashboard boundary, not proven.
2. **Server-side signing at the proxy.** Every API call goes through the Next.js `/gw/[...path]`
   route, which reads that cookie **server-side** and forwards the request with
   `x-principal-id` + `x-principal-signature` — an HMAC-SHA256 of the principal id under
   `REVIEWER_PROXY_SECRET` (`dashboard/lib/reviewer-session.ts`). The browser never holds or
   sends the signature itself.
3. **Verification at the gate API.** `gates/api.py::_trusted_principal` recomputes the HMAC and
   rejects missing/invalid signatures (401). The signed principal is **the only acting identity**:
   `_trusted_actor` rejects any request whose body actor contradicts the header (400
   `actor mismatch`) — body fields like `approver_id`/`actor` may only echo the principal and are
   otherwise non-authoritative context.
4. **Assignment authorization at decide time.** Being authenticated is not being allowed:
   `gates/engine.py::decide` resolves the gate's allowed assignments — the `gate_assignment`
   snapshot taken at gate-open, else the stage approval contract (DB-backed `approval_policy`
   ahead of `system_config.yaml gates.<stage>.approval`) — and requires the acting principal to
   match one of them via `_principal_matches_assignment`:
   - `user:<id>` — direct id equality;
   - `role:<id>` — active row in `principal_role_member`;
   - `group:<id>` — active row in `principal_group_member`.
   Hard floors (`gates/actors.py`) additionally bar non-human principals from deciding
   hard-floor gates regardless of assignment.
5. **Denials are audited.** Since #10, rejected approval attempts write `audit_log` rows that
   survive the error rollback (`engine.audit_denied`, own committed transaction):
   - `approval_denied` (entity `gate`) — unsigned callers and body/principal mismatch (spoof)
     attempts at the API boundary (`_trusted_approval_actor` on decide/undecide/resolve);
   - `gate_decision_denied` (entity `gate`) — authenticated principals rejected by assignment
     authorization (`reason: not_assigned`, with the allowed assignments) or by a hard floor
     (`reason: hard_floor`).

## What this protects against — and what it does not

Protects (by design, today):

- A client cannot make the API act as a different user than the one the dashboard proxy signed
  (body-actor spoofing is rejected and audited).
- A caller without the proxy secret cannot talk to approval endpoints at all (unsigned → 401,
  audited).
- An authenticated principal cannot approve on a gate they are not assigned to directly or via
  role/group membership (→ 400, audited).

Does NOT protect (accepted pre-IAM gaps):

- **Identity is self-asserted at the dashboard.** Anyone who can reach the dashboard and set the
  reviewer cookie can act as any reviewer id. Browser-boundary authentication is what IAM adds.
- **One shared HMAC secret.** `REVIEWER_PROXY_SECRET` authenticates the *proxy*, not the person;
  anyone holding it can mint any principal (this is how the test suites sign as `khal`/`huda`).
  The dev default (`dev-internal-reviewer-proxy-secret`) must be overridden outside dev.
- **Gate commit (`resolve`) is not assignment-checked.** Any signed principal may commit a gate's
  recorded decisions (it cannot fabricate approvals — quorum applies only committed decisions by
  assigned approvers). Whether committing requires an assignment of its own is an open product
  decision, tracked as a residual of #10.

## Upgrade path to IAM

The seams are already in place; the swap replaces step 1 only:

1. Replace the self-asserted cookie with an authenticated session (OIDC/SSO or credentialed
   login) that resolves to a `principal` row; the `/gw` proxy then signs the *authenticated*
   principal — nothing downstream changes.
2. Move from the shared proxy secret to per-session/per-user proof (e.g. short-lived signed
   session tokens), keeping `x-principal-*` as the API contract.
3. The authorization layer (assignments, role/group membership, hard floors, denial audit) is
   IAM-agnostic and carries over unchanged — `principal`, `principal_role_member`,
   `principal_group_member` become IAM-provisioned instead of hand-seeded.
4. Rotate `REVIEWER_PROXY_SECRET` out of `.env` into a managed secret when the trial hardens.
