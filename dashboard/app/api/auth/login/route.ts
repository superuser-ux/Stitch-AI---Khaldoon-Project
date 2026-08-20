import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import {
  OIDC_FLOW_COOKIE, discover, flowValue, iamEnabled, oidcConfig, pkceChallenge, randomToken,
} from "@/lib/iam-session";

// #190 — start the OIDC authorization-code + PKCE flow. Only exists when the IAM flag is on.
export async function GET(req: NextRequest) {
  if (!iamEnabled()) return NextResponse.json({ error: "iam disabled" }, { status: 404 });
  const cfg = oidcConfig();
  if (!cfg.issuer) {
    // misconfiguration is loud, not a demo-mode downgrade
    return NextResponse.json({ error: "TANAGHOM_OIDC_ISSUER is not configured" }, { status: 500 });
  }
  const doc = await discover(cfg.issuer);
  const state = randomToken();
  const nonce = randomToken();
  const verifier = randomToken();
  const redirectUri = cfg.redirectUri || new URL("/api/auth/callback", req.nextUrl.origin).toString();

  const url = new URL(doc.authorization_endpoint);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", cfg.clientId);
  url.searchParams.set("redirect_uri", redirectUri);
  url.searchParams.set("scope", "openid profile email");
  url.searchParams.set("state", state);
  url.searchParams.set("nonce", nonce);
  url.searchParams.set("code_challenge", pkceChallenge(verifier));
  url.searchParams.set("code_challenge_method", "S256");

  const jar = await cookies();
  jar.set(OIDC_FLOW_COOKIE, flowValue({ state, nonce, verifier }), {
    httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/",
    maxAge: 600,
  });
  return NextResponse.redirect(url);
}
