import { test, expect } from "@playwright/test";
import { spawn } from "node:child_process";
import { WB_URL, FIXTURE_ROUND } from "./surfaces";

// #293 D2 evidence — V2's read seam is an explicit, CLOSED, GET-only allowlist over endpoints
// Tanaghom already leaves intentionally unguarded. This spec enumerates the exact method/path
// patterns and proves the three required rejections:
//   1. a guarded endpoint,
//   2. a non-allowlisted GET,
//   3. a mutating request.
//
// These are proven against the running V2 server — the real boundary, not a unit test of the
// matcher.

// ---- The complete Stage 0 boundary. Anything not listed here is refused. ----
const ALLOWLIST = [
  { method: "GET", path: "/gw/health" },
  { method: "GET", path: "/gw/admin/secrets/status" },
  { method: "GET", path: "/gw/rounds" },
  { method: "GET", path: `/gw/rounds/${FIXTURE_ROUND}` }, // GET /gw/rounds/{round_id}
  { method: "GET", path: "/gw/baseline-eligibility" },    // #331 — the New-run eligibility read
] as const;

test("the complete allowlist is reachable — and it is only these", async ({ request }) => {
  for (const entry of ALLOWLIST) {
    const res = await request.get(`${WB_URL}${entry.path}`);
    expect(res.status(), `${entry.method} ${entry.path} must be inside the boundary`).toBe(200);
  }
});

test("REJECTS a guarded endpoint (V2 never reaches an authority-bearing read)", async ({ request }) => {
  // /me/pending-approvals is guarded by _require_trusted_principal on the gate API (401 without a
  // signed principal). V2 refuses it at its OWN boundary — the upstream request is never made, so
  // V2 cannot become a parallel authority path even if it later held a secret.
  const res = await request.get(`${WB_URL}/gw/me/pending-approvals`);
  expect(res.status()).toBe(403);
  expect(await res.text()).toContain("not in the workbench read-only boundary");
});

test("REJECTS a non-allowlisted GET (unguarded upstream is still refused)", async ({ request }) => {
  // /principals is NOT principal-guarded upstream, so this proves the allowlist is a closed list
  // rather than a mirror of the API's own guarding — V2 exposes only what Stage 0 needs.
  const res = await request.get(`${WB_URL}/gw/principals`);
  expect(res.status()).toBe(403);

  // Path traversal is refused by the same closed list.
  const traversal = await request.get(`${WB_URL}/gw/rounds/..%2Fprincipals`);
  expect([403, 404]).toContain(traversal.status());
});

test("REJECTS Next's auto-synthesized HEAD and OPTIONS (regression: 11db665 review P1.1)", async ({ request }) => {
  // Next 15 derives HEAD from a GET handler and answers OPTIONS itself with
  // `Allow: GET, HEAD, OPTIONS`. At 11db665 this meant HEAD /gw/health returned 200 and performed
  // a real upstream GET, contradicting the GET-only boundary — the framework default silently
  // widened a boundary the code believed it had closed. Both are now explicitly refused.
  const head = await request.head(`${WB_URL}/gw/health`);
  expect(head.status(), "HEAD must be refused — it would issue an implicit upstream GET").toBe(405);
  expect(head.headers()["allow"]).toBe("GET");

  const options = await request.fetch(`${WB_URL}/gw/health`, { method: "OPTIONS" });
  expect(options.status(), "OPTIONS must be refused, not advertise HEAD/OPTIONS").toBe(405);
  expect(options.headers()["allow"]).toBe("GET");

  // The refusal must hold on every allowlisted path, not just /gw/health.
  const headRounds = await request.head(`${WB_URL}/gw/rounds`);
  expect(headRounds.status()).toBe(405);
});

test("the WRITE boundary is exactly the enumerated governed operations — everything else refused", async ({ request }) => {
  // The write boundary is a CLOSED enumerated set of governed operations, each added for the slice
  // that needed it (schedule-reorder #292; placement + schedule-revision #304; the per-item Topic
  // family #313; bulk + presentation-reorder #314; and #331's run creation + canonical Topic
  // generation). They stay EXACT matches, not prefixes — POST elsewhere is still refused and V2 is
  // still not a general write proxy. Upstream owns authority, pinned policy, token and freeze for all.
  //
  // #331 — run creation is now INSIDE the boundary, so it is NOT refused as out-of-boundary: the
  // planner decides it on its merits (an absent format_mix is a typed 422), never with the 403 that
  // means "not in V2's boundary".
  const createRound = await request.post(`${WB_URL}/gw/rounds`, { data: { round_id: "SHOULD-NEVER-EXIST" } });
  expect(await createRound.text(), "run creation is inside the boundary; the planner decides it")
    .not.toContain("not in the workbench write boundary");
  expect(createRound.status(), "an absent format_mix is the planner's typed 422, not a boundary 403").toBe(422);

  // #331 — canonical manual Topic generation (stage topic_review, the #332 authority path) is now
  // INSIDE the boundary. It is forwarded and the merged #332 engine decides it (activated / lifecycle
  // replay / automatic-mode 409 / coarse authorization 403) — so it must NOT be the V2 out-of-boundary
  // refusal. A generation 403 here, if any, is the engine's coarse governed denial, not the boundary's.
  const generate = await request.post(`${WB_URL}/gw/rounds/${FIXTURE_ROUND}/stages/topic_review/generate`);
  expect(await generate.text(), "generation is inside the boundary; the #332 engine decides it")
    .not.toContain("not in the workbench write boundary");

  // …but generation for a NON-topic_review stage stays OUT of the boundary — the lane triggers only
  // the canonical Topic generation, nothing else.
  const otherGen = await request.post(`${WB_URL}/gw/rounds/${FIXTURE_ROUND}/stages/script_review/generate`);
  expect(otherGen.status(), "only topic_review generation is in the boundary").toBe(403);
  expect(await otherGen.text()).toContain("not in the workbench write boundary");

  // schedule-revision is now IN the boundary (#304 Level 2), so it must NOT be refused as
  // out-of-boundary. The upstream still decides it — an empty body is rejected on its merits
  // (no governed field / stale token), never with the 403 that means "not in V2's boundary".
  const revise = await request.post(`${WB_URL}/gw/slots/${FIXTURE_ROUND}-1/schedule-revision`, { data: {} });
  expect(revise.status(), "schedule-revision is inside the #304 boundary; upstream decides it").not.toBe(403);

  // #313 Stage 2B-1 adds the governed per-item Topic action family — edit, restore, rework_from, drop,
  // request_change, approve. All are inside the boundary now, so NOT refused as out-of-boundary; upstream
  // owns the entire decision (whitelisted fields, CAS, idempotency, fail-closed eligibility, gate
  // authority/quorum for the decisions) and rejects an empty/ineligible body on its merits, never with
  // the 403 that means "not in V2's boundary".
  for (const verb of ["edit", "restore", "rework_from", "drop", "request_change", "approve"]) {
    const res = await request.post(`${WB_URL}/gw/slots/${FIXTURE_ROUND}-1/${verb}`, { data: {} });
    expect(res.status(), `per-item ${verb} is inside the #313 boundary; upstream decides it`).not.toBe(403);
  }

  // …but a NON-enumerated slot write is still refused by the boundary itself — commit stays OUT of the
  // V2 boundary (the human advance/pin floor is never a V2 write).
  const bogus = await request.post(`${WB_URL}/gw/slots/${FIXTURE_ROUND}-1/commit`, { data: {} });
  expect(bogus.status(), "a non-enumerated slot write must be refused").toBe(403);

  // Methods with no handler at all stay closed.
  const put = await request.put(`${WB_URL}/gw/stages/topic_review/approval-policy`, { data: {} });
  expect(put.status(), "PUT must be refused").toBe(405);

  const del = await request.delete(`${WB_URL}/gw/rounds/${FIXTURE_ROUND}`);
  expect(del.status(), "DELETE must be refused").toBe(405);
});

test("the enumerated write is UNAVAILABLE in a non-dev, non-IAM runtime (#292)", async () => {
  test.setTimeout(180_000);
  // V2 signs a FIXTURE principal; it proves no caller identity. With IAM off that is only defensible
  // where every caller is already trusted, so the posture must be enforced EXPLICITLY. Otherwise any
  // caller who can reach V2 in a demo/production runtime — one with REVIEWER_PROXY_SECRET set, where
  // signing SUCCEEDS — obtains that principal's signed authority: a forged request that works. This
  // spawns exactly that runtime (IAM off, secret present, TANAGHOM_DEV_MODE ABSENT) and proves the
  // write refuses rather than signs.
  const port = 3117;
  const srv = spawn("./node_modules/.bin/next", ["start", "-p", String(port)], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      TANAGHOM_DEV_MODE: "",                                          // posture NOT declared
      REVIEWER_PROXY_SECRET: "a-real-looking-secret-for-this-probe",  // signing would otherwise work
      TANAGHOM_OIDC_ENABLED: "",                                      // IAM off — the gap under test
      TANAGHOM_OIDC_ISSUER: "https://iam.dev.example/",               // pre-binding configuration
      API_BASE: process.env.API_BASE || "http://localhost:8009",
    },
    stdio: "ignore",
  });
  try {
    const base = `http://localhost:${port}`;
    await expect(async () => {
      const up = await fetch(`${base}/api/runtime`).catch(() => null);
      expect(up?.ok).toBe(true);
    }).toPass({ timeout: 120_000 });

    // Binding an external identity is deliberately completed before IAM activation. The issuer is
    // non-secret configuration and must remain visible to Identity Admin while identity is still
    // the dev fixture; exposing it does not activate authentication.
    const runtime = await (await fetch(`${base}/api/runtime`)).json();
    expect(runtime.identity).toBe("dev-fixture");
    expect(runtime.issuer).toBe("https://iam.dev.example");

    // The seam still READS — this narrows the write, it does not break Stage 0.
    const read = await fetch(`${base}/gw/health`);
    expect(read.status, "reads stay available in a non-dev runtime").toBe(200);

    // …but the ONE enumerated write refuses to sign anyone.
    const write = await fetch(`${base}/gw/rounds/${FIXTURE_ROUND}/schedule-reorder`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ order: [], schedule_token: 1 }),
    });
    expect(write.status, "the write must be unavailable outside an explicit dev posture").toBe(501);
    expect(JSON.stringify(await write.json())).toMatch(/TANAGHOM_DEV_MODE|local\/dev\/test/i);
  } finally {
    srv.kill("SIGTERM");
  }
});

test("a client cannot assert who it is: the signed principal stays server-resolved (#292)", async ({ request }) => {
  // The body's actor is never trusted. A caller asserting someone else's identity must not change
  // the principal V2 signs: the gate API rejects a body actor that contradicts the signed one, so a
  // forged assertion fails rather than silently taking effect under the asserted identity.
  const forged = await request.post(`${WB_URL}/gw/rounds/${FIXTURE_ROUND}/schedule-reorder`, {
    data: { order: [], schedule_token: 1, actor: "sheikh" },
  });
  expect(forged.status(), "a client-asserted actor must never be honoured").not.toBe(200);
  expect(await forged.text(), "the refusal must not report acting as the asserted principal")
    .not.toMatch(/"actor"\s*:\s*"sheikh"/);
});

test("V2 declares its own runtime identity, distinct from V1", async ({ request }) => {
  const res = await request.get(`${WB_URL}/api/runtime`);
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.surface).toBe("workbench");
  expect(body.lane).toBe("v2-transition");
  // The current dev lane signs the explicitly declared fixture principal; IAM mode reports OIDC.
  expect(body.identity).toBe("dev-fixture");
  expect(body.build).not.toBe("unknown");
});
