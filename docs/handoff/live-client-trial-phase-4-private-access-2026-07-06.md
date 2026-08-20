# Live Client Trial — Phase 4: Private Access Activation

Author: CC · Date: 2026-07-06
Prompt: "Phase 4 — Activate Private Client Trial Access — CC only (OR)"
Result: **READY_FOR_OWNER_SEND — the locked client dashboard is now exposed PRIVATELY (Tailscale tailnet-only, no public funnel). All smoke tests pass. No access has been sent; the client must be invited to the tailnet first.**

---

## 1. Access-method change (important)

The **public funnel** put on `:10000` in the previous turn was **removed** (`tailscale funnel --https=10000 off`) because Phase 4 forbids public-funnel-without-auth. Replaced with **Tailscale Serve (tailnet-only)**.

| Access method | Chosen |
|---------------|--------|
| Tailscale **tailnet-only** serve → `:3002` | ✅ **active** (private) |
| Public funnel → `:3002` | ❌ removed / not used |
| Reverse proxy + basic auth | not needed (tailnet is viable) |

## 2. Exposed URL + target-port proof

- **Client trial URL (tailnet-only):** `https://mac-2-608.taile18f28.ts.net:10000/`
- Proxies to **`http://127.0.0.1:3002`** (the locked client dashboard) — verified in `tailscale serve status`.
- **Privacy proof (authoritative):** `tailscale serve status --json` → `AllowFunnel` = **`{ "…:443": true }` only**. Port `:10000` is **not** in `AllowFunnel` → **tailnet-only**. Only `:443` (→ dev `:3000`) is public, and that is the owner's pre-existing dev access, not the client URL.

```
:443   -> 127.0.0.1:3000   (Funnel on / PUBLIC)   [dev dashboard — owner's existing access, NOT the client URL]
:8443  -> 127.0.0.1:18789  (tailnet only)         [pre-existing, unrelated]
:10000 -> 127.0.0.1:3002   (tailnet only)         [<-- the client trial surface, PRIVATE]
```

Operator trial dashboard `:3001` is **not** in the serve config → not exposed. Trial API `:8012` and dev API `:8009` are not exposed.

## 3. Smoke test (over the tailnet URL, clean headless session)

| Check | Result |
|-------|--------|
| Loads | 200 |
| Trial banner | visible — "Live client trial · Data is temporary and may be purged" |
| Generation indicator | **"Generation: Live"** |
| `/gw/health` | `writer_stub:false, writer_mode:live` |
| Rounds visible | **2 (trial only)** — no dev/e2e clutter |
| `/admin/workflows` | **307 → blocked** |
| `/admin/methodology` | **307 → blocked** |
| New-run planner | absent (0) |
| Persona switcher | **absent from DOM (0)** |
| Open trial round "Round A" (R2) | selectable + review reachable |
| Live action | **not exercised** (view-only; no extra live-generation call made) |
| Operator `:3001` exposed | **no** |

All required smoke tests pass.

## 4. Trial / live-mode proof

Trial API still `writer_mode:live`; the private URL reaches only the trial DB `tanaghom_trial` (2 seeded rounds). Dev stack untouched (`:3000` 200, `:8009` 209 rounds).

## 5. Credential status

- **No credentials created / none printed.** The access gate is **tailnet membership** — a device must be on the owner's tailnet to reach the URL. There is no app login (that is the full #13).
- Access is **not sent**.

## 6. Feedback path (draft — not created)

Recommended: a **shared Google Doc** for the first trial (GitHub is operator-internal and must not be client-facing). Sections to include:

1. First impression
2. Usability / clarity of the review flow
3. Generated **topic** quality
4. Generated **script** quality
5. Request-change / regenerate behavior
6. Approval flow
7. Confusing labels
8. Missing controls
9. Bugs / screenshots
10. Overall readiness

*(Document not created or shared — owner to create, or approve me to draft it elsewhere.)*

## 7. Client access pack (draft — for owner review; DO NOT SEND YET)

- **URL:** `https://mac-2-608.taile18f28.ts.net:10000/` *(reachable only after the client's device joins your Tailscale tailnet)*
- **Access method:** private Tailscale tailnet-only. The client must accept a Tailscale invite / join the tailnet; no password.
- **Allowed:** view trial rounds · open review surfaces · inspect generated topics/scripts · request changes · regenerate items (live) · approve items · progress the review flow · submit feedback via the shared doc.
- **Blocked (enforced):** methodology/workflow admin, workflow/stage/gate config, persona/admin switching, dev/debug/admin routes, dev DB/API, environment/writer settings, config/secrets, destructive cleanup; dev/e2e clutter is invisible.
- **Temporary-data warning:** all trial data is disposable and may be reset/purged after evaluation.
- **Live-generation warning:** outputs are real live-model generations (not stubs) — treat as trial content.
- **Confidentiality warning:** do not enter confidential production data unless explicitly approved.
- **Known limitations:** single fixed reviewer identity; scripts generate on demand (approve a topic to generate its script); trial, not production; no persistence guarantee.

### Client access note (ready to send once invited + approved)
> This is a live client trial environment. Generated outputs are real trial outputs, but all trial data is temporary and may be reset or purged after evaluation.
>
> Please test: (1) usability and clarity of the review flow, (2) quality of generated topics and scripts, (3) request-change / regenerate behavior, (4) approval flow, (5) confusing labels or missing controls, (6) bugs, slow screens, broken states, or unexpected output, (7) anything that would block real operational use.
>
> Please do not enter confidential production data unless explicitly approved.

## 8. Exact owner action needed to send access

1. **Invite the client's device to your Tailscale tailnet** (Tailscale admin console → share/invite). Tailnet-only access requires this; I did not invite anyone.
2. *(Optional stronger control)* add a **Tailscale ACL** limiting that node to the `:10000` service only.
3. **Create the shared feedback doc** (§6) and add its link to the access pack.
4. Then send the client the **URL + the §7 access note + feedback-doc link**.

If the client **cannot** join Tailscale, tell me and I'll set up the **reverse-proxy + basic-auth fallback** to `:3002` (credentials handled in your password manager, never printed/committed).

## 9. Status marker

**READY_FOR_OWNER_SEND** — private access is active and proven; awaiting (a) tailnet invite of the client and (b) feedback-doc creation before anything is sent.

## 10. Attestation

- Public funnel to `:3002` removed; access is now **tailnet-only** (proven via `AllowFunnel`). Dev `:443→:3000` funnel left as-is (owner's pre-existing access — flagged, not changed).
- Client URL reaches only the **locked** `:3002`; admin blocked, planner/persona absent, live/trial banner shown, trial data only. Operator `:3001`, dev, and both APIs not exposed.
- **No credentials created/printed; no secrets; no `.env*`.** No client access sent. No new live-generation call (view-only smoke test). No code/DB/backlog changes. This report is **uncommitted**.
