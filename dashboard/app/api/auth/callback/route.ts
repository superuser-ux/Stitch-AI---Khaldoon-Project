import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import {
  IAM_SESSION_COOKIE, OIDC_FLOW_COOKIE, discover, iamEnabled, oidcConfig,
  readFlow, sessionValue, verifyIdToken,
} from "@/lib/iam-session";
import { principalProxyHeaders } from "@/lib/reviewer-session";

const API = process.env.API_BASE || "http://localhost:8009";

function fail(req: NextRequest, reason: string) {
  // no session is set on any failure — the UI shows the sign-in screen with the error
  const url = new URL("/", req.nextUrl.origin);
  url.searchParams.set("auth_error", reason);
  const res = NextResponse.redirect(url);
  res.cookies.delete(OIDC_FLOW_COOKIE);
  return res;
}

// #190/#388-B — OIDC callback: validate the flow, exchange the code (PKCE), cryptographically
// verify the ID token against the discovered JWKS (including rotation refresh),
// then resolve (issuer, subject) → bound principal ONCE via the gate API's system-gated
// /identity/binding read. The session carries the BOUND principal (or null = truthfully unbound).
export async function GET(req: NextRequest) {
  if (!iamEnabled()) return NextResponse.json({ error: "iam disabled" }, { status: 404 });
  const cfg = oidcConfig();
  const jar = await cookies();
  const flow = readFlow(jar.get(OIDC_FLOW_COOKIE)?.value);
  const code = req.nextUrl.searchParams.get("code") || "";
  const state = req.nextUrl.searchParams.get("state") || "";
  if (!flow) return fail(req, "login flow expired — try again");
  if (!code || !state || state !== flow.state) return fail(req, "state mismatch");

  const doc = await discover(cfg.issuer);
  const redirectUri = cfg.redirectUri || new URL("/api/auth/callback", req.nextUrl.origin).toString();
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: redirectUri,
    client_id: cfg.clientId,
    code_verifier: flow.verifier,
  });
  if (cfg.clientSecret) body.set("client_secret", cfg.clientSecret);
  const tokenRes = await fetch(doc.token_endpoint, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: body.toString(),
    cache: "no-store",
  }).catch(() => null);
  if (!tokenRes || !tokenRes.ok) return fail(req, "token exchange failed");
  const tokens = (await tokenRes.json().catch(() => null)) as { id_token?: string } | null;
  if (!tokens?.id_token) return fail(req, "no id_token in token response");

  let payload: Record<string, unknown>;
  try {
    payload = await verifyIdToken(tokens.id_token, {
      issuer: cfg.issuer,
      clientId: cfg.clientId,
      nonce: flow.nonce,
      jwksUri: doc.jwks_uri,
    });
  } catch (error) {
    return fail(req, `id_token rejected: ${error instanceof Error ? error.message : "verification failed"}`);
  }

  // Identity → operating principal: ONE lookup, server-to-server, signed as the system principal
  // (only the BFF holds the proxy secret). IdP claims beyond (iss, sub) are display hints only.
  let principalId: string | null = null;
  let principalDisplay: string | null = null;
  try {
    const bind = await fetch(
      `${API}/identity/binding?issuer=${encodeURIComponent(cfg.issuer)}&subject=${encodeURIComponent(String(payload.sub))}`,
      { headers: principalProxyHeaders("system"), cache: "no-store" },
    );
    if (bind.ok) {
      const data = await bind.json();
      principalId = data.principal_id ?? null;
      principalDisplay = data.display_name_en ?? null;
    }
  } catch { /* unresolved lookup = unbound session; never a fallback identity */ }

  const res = NextResponse.redirect(new URL("/", req.nextUrl.origin));
  res.cookies.delete(OIDC_FLOW_COOKIE);
  res.cookies.set(IAM_SESSION_COOKIE, sessionValue({
    iss: cfg.issuer,
    sub: String(payload.sub),
    principal_id: principalId,
    display: principalDisplay || (payload.name ? String(payload.name) : null),
    email: payload.email ? String(payload.email) : null,
  }), {
    httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/",
    maxAge: 8 * 60 * 60,
  });
  return res;
}
