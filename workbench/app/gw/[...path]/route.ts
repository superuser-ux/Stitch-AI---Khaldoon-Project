import { NextRequest, NextResponse } from "next/server";
import { API_BASE, iamEnabled, resolveAllowedPath, resolveAllowedQuery, resolveAllowedWritePath } from "@/lib/api-contract";
import { devMode, principalProxyHeaders, workbenchPrincipal } from "@/lib/principal-proxy";
import { IAM_SESSION_COOKIE, readSession, revalidateBinding } from "@/lib/iam-session";

// #293 Stage 0 — V2's read-only seam onto the Tanaghom API.
//
// METHOD CLOSURE (corrected after Codex's exact-head review of 11db665):
// Exporting only GET does NOT close every other method. Next 15 SYNTHESIZES `HEAD` from a GET
// handler (running this route and issuing a real upstream GET) and answers `OPTIONS` itself with
// `Allow: GET, HEAD, OPTIONS`. The earlier claim that "only GET is exported, therefore everything
// else is 405" reasoned from this module's source rather than from the framework's actual
// behaviour, and it was wrong — reproduced live: HEAD /gw/health -> 200, OPTIONS -> 204.
//
// So the closure is now EXPLICIT rather than inherited: HEAD and OPTIONS are exported solely to
// refuse them with 405, and every remaining method is refused by Next because it has no handler.
// D2's ruling ("non-GET requests fail closed") is enforced by declared code, not by a framework
// default we assumed.
//
// Tanaghom remains sole authority. This route adds NO policy, NO identity assertion, and NO
// interpretation of the payload — it forwards an allowlisted read and returns the upstream status
// and body verbatim, so a typed upstream error stays a typed error rather than becoming a
// frontend-invented one.

export const dynamic = "force-dynamic";

async function iamPrincipal(req: NextRequest): Promise<{ principal: string } | { response: NextResponse }> {
  const session = readSession(req.cookies.get(IAM_SESSION_COOKIE)?.value);
  if (!session) {
    return { response: NextResponse.json({ detail: "not authenticated" }, { status: 401 }) };
  }
  if (!session.principal_id) {
    return { response: NextResponse.json({ detail: "access not configured" }, { status: 403 }) };
  }
  const binding = await revalidateBinding(session);
  if (binding === "unavailable") {
    return { response: NextResponse.json({ detail: "identity check unavailable; try again" }, { status: 503 }) };
  }
  if (binding !== "ok") {
    const response = NextResponse.json(
      binding === "unbound" ? { detail: "access not configured" } : { detail: "reauthentication required" },
      { status: binding === "unbound" ? 403 : 401 },
    );
    response.cookies.delete(IAM_SESSION_COOKIE);
    return { response };
  }
  return { principal: session.principal_id };
}

/** The single refusal used for every non-GET method, including the ones Next would otherwise
 *  answer on our behalf. 405 + Allow: GET states the boundary truthfully. */
function methodNotAllowed(method: string) {
  return NextResponse.json(
    {
      detail:
        `${method} is not permitted on the workbench read boundary. V2 Stage 0 is GET-only and ` +
        "issues no mutating or implicit upstream request.",
    },
    { status: 405, headers: { allow: "GET" } },
  );
}

// #292/#331 — the ENUMERATED governed writes. POST is served only for paths resolveAllowedWritePath
// admits (schedule/topic governance, run creation, canonical Topic generation); every other path is
// refused before any upstream request, so this is not a general write proxy.
export async function POST(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;

  // #292 — with IAM off, V2 signs a FIXTURE principal; it proves no caller identity. That path is only
  // defensible where every caller is already trusted, so the posture must be enforced EXPLICITLY
  // rather than inferred from "IAM happens to be disabled". Outside an operator-declared
  // local/dev/test runtime this route refuses to sign at all — otherwise any caller who can reach V2
  // in a demo/production runtime (one with REVIEWER_PROXY_SECRET set, where signing would succeed)
  // obtains the fixture principal's signed authority, i.e. a forged request that works. Failing
  // closed keeps "IAM proves identity; Tanaghom decides authority" intact without expanding IAM.
  if (!iamEnabled() && !devMode()) {
    return NextResponse.json(
      {
        detail:
          "workbench (V2) writes only in an explicit local/dev/test runtime (TANAGHOM_DEV_MODE). It " +
          "signs a fixture principal and proves no caller identity, so it refuses to write in a " +
          "runtime where callers are not already trusted.",
      },
      { status: 501 },
    );
  }

  const allowed = resolveAllowedWritePath(path);
  if (!allowed) {
    return NextResponse.json(
      {
        detail:
          `not in the workbench write boundary: POST /${path.join("/")}. V2 writes only the enumerated ` +
          "governed operations in resolveAllowedWritePath — every other path is refused before any " +
          "upstream request.",
      },
      { status: 403 },
    );
  }

  const headers = new Headers({ "content-type": "application/json" });
  let principal: string;
  if (iamEnabled()) {
    const auth = await iamPrincipal(req);
    if ("response" in auth) return auth.response;
    principal = auth.principal;
  } else {
    principal = workbenchPrincipal();
  }
  // Identity is asserted SERVER-SIDE only. The body actor is never trusted; the gate API still
  // authorizes this resolved principal against persisted Tanaghom authority.
  for (const [k, v] of Object.entries(principalProxyHeaders(principal))) headers.set(k, v);

  let res: Response;
  try {
    res = await fetch(new URL(`${API_BASE}/${allowed.segments.map(encodeURIComponent).join("/")}`), {
      method: "POST",
      headers,
      body: await req.text(),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "tanaghom api unreachable" }, { status: 503 });
  }

  // Status and body are forwarded VERBATIM — a typed 409 stays a typed 409 with its refresh
  // evidence intact, never reinterpreted into a frontend-invented error.
  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") || "application/json" },
  });
}

// Next auto-derives HEAD from GET, which would run the handler and perform a real upstream GET.
// Declaring it lets us refuse it instead of silently honouring a non-GET request.
export async function HEAD() {
  return methodNotAllowed("HEAD");
}

// Next answers OPTIONS itself (204, `Allow: GET, HEAD, OPTIONS`) — advertising methods this
// boundary does not accept. Declaring it keeps the advertised surface equal to the real one.
export async function OPTIONS() {
  return methodNotAllowed("OPTIONS");
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;

  let authenticatedPrincipal: string | null = null;
  if (iamEnabled()) {
    const auth = await iamPrincipal(req);
    if ("response" in auth) return auth.response;
    authenticatedPrincipal = auth.principal;
  }

  const allowed = resolveAllowedPath(path);
  if (!allowed) {
    return NextResponse.json(
      {
        detail:
          `not in the workbench read-only boundary: /${path.join("/")}. V2 Stage 0 may read only ` +
          "GET health, rounds, rounds/{id} — the endpoints the gate API leaves unguarded.",
      },
      { status: 403 },
    );
  }

  // #355 — the enumerated QUERY boundary. Historically this route forwarded NO query string, which
  // is safe for every path-only read but unsafe for `slots/{id}/revisions`: upstream defaults
  // `artifact` to `topic`, so a Scripts request that lost its parameter would return TOPIC history
  // for a Scripts surface to render. resolveAllowedQuery refuses rather than defaults, so the
  // absence of a topic fallback is enforced by the boundary instead of by caller discipline.
  const query = resolveAllowedQuery(allowed.segments, req.nextUrl.searchParams);
  if (query === null) {
    return NextResponse.json(
      {
        detail:
          `not in the workbench query boundary: /${path.join("/")}?${req.nextUrl.searchParams.toString()}. ` +
          "V2 forwards exactly one enumerated parameter (artifact=script on slots/{id}/revisions) and " +
          "never an arbitrary query; an absent, duplicated or non-script artifact is refused rather " +
          "than defaulted, so a Scripts read can never silently return Topic history.",
      },
      { status: 403 },
    );
  }

  const target = new URL(
    `${API_BASE}/${allowed.segments.map(encodeURIComponent).join("/")}${query ? `?${query}` : ""}`,
  );

  // #357 — the ACTION DECISION is evaluated FOR a principal, so it must be asked as one.
  //
  // Every other read here is principal-free and stays that way. But "may I start this?" is not a
  // property of the run — it is a property of the run AND the actor. Asking it unsigned always yields
  // `principal_missing`, so the control could never become available and the surface would silently
  // contradict a backend that would have authorized the very same caller.
  //
  // The identity asserted is exactly the one the WRITE would use, under the SAME guards (IAM-on and
  // non-dev runtimes already returned above / below), so "can I?" and "do it" can never disagree. V2
  // still mints no authority: it asserts server-side who is asking and relays the server's answer.
  const isActionDecision = allowed.segments.length === 5 && allowed.segments[0] === "rounds"
    && allowed.segments[2] === "stages" && allowed.segments[4] === "action";
  // #373 (Codex P1) — the per-item read is signed too, for the SAME reason as the action decision: the
  // `undecide` availability it projects is a property of the item AND the caller (undecide clears only
  // the calling principal's decision). Signing binds that projection to the exact principal the undo
  // WRITE would use, so "can I undo?" and "do it" can never disagree. Still a read; V2 mints no
  // authority — it asserts server-side who is asking and relays the server's typed answer.
  const isTopicItem = allowed.segments.length === 3 && allowed.segments[0] === "slots"
    && allowed.segments[2] === "topic_item";
  const isSecretsAdmin = allowed.segments.length === 3 && allowed.segments[0] === "admin"
    && allowed.segments[1] === "secrets" && allowed.segments[2] === "status";
  // #443 — the Settings-truth read is a bounded admin read (provider/model/route metadata, no secret
  // material). Like the secrets-status read it requires the signed principal upstream, so it is signed
  // server-side in an explicit dev/test runtime; IAM-on uses the authenticated principal.
  const isSettingsAdmin = allowed.segments.length === 3 && allowed.segments[0] === "admin"
    && allowed.segments[1] === "settings" && allowed.segments[2] === "truth";
  const isIdentityAdmin = (allowed.segments.length === 2 && allowed.segments[0] === "identity"
      && allowed.segments[1] === "bindings")
    || (allowed.segments.length === 1 && allowed.segments[0] === "principals");
  if (isSecretsAdmin && !devMode() && !authenticatedPrincipal) {
    return NextResponse.json(
      { detail: "secret operations status is available only in an explicit local/dev/test runtime" },
      { status: 501 },
    );
  }
  const headers = new Headers();
  const signedPrincipal = authenticatedPrincipal
    || ((isActionDecision || isTopicItem || isSecretsAdmin || isIdentityAdmin || isSettingsAdmin)
      && devMode()
      ? workbenchPrincipal()
      : null);
  if (signedPrincipal) {
    for (const [k, v] of Object.entries(principalProxyHeaders(signedPrincipal))) headers.set(k, v);
  }

  let res: Response;
  try {
    res = await fetch(target, { method: "GET", headers, cache: "no-store" });
  } catch {
    // Truthful transport failure — never a fabricated empty success.
    return NextResponse.json(
      { detail: "tanaghom api unreachable" },
      { status: 503 },
    );
  }

  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") || "application/json" },
  });
}
