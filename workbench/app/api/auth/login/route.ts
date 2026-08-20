import { NextRequest, NextResponse } from "next/server";
import {
  OIDC_FLOW_COOKIE,
  discover,
  flowValue,
  iamEnabled,
  oidcConfig,
  pkceChallenge,
  randomToken,
} from "@/lib/iam-session";

export async function GET(req: NextRequest) {
  if (!iamEnabled()) return NextResponse.json({ error: "iam disabled" }, { status: 404 });
  const config = oidcConfig();
  if (!config.issuer) {
    return NextResponse.json({ error: "TANAGHOM_OIDC_ISSUER is not configured" }, { status: 500 });
  }
  if (!config.clientId) {
    return NextResponse.json({ error: "TANAGHOM_OIDC_CLIENT_ID is not configured" }, { status: 500 });
  }
  const document = await discover(config.issuer, config.internalBaseUrl);
  const state = randomToken();
  const nonce = randomToken();
  const verifier = randomToken();
  const redirectUri = config.redirectUri || new URL("/api/auth/callback", req.nextUrl.origin).toString();
  const target = new URL(document.authorization_endpoint);
  target.searchParams.set("response_type", "code");
  target.searchParams.set("client_id", config.clientId);
  target.searchParams.set("redirect_uri", redirectUri);
  target.searchParams.set("scope", "openid profile email");
  target.searchParams.set("state", state);
  target.searchParams.set("nonce", nonce);
  target.searchParams.set("code_challenge", pkceChallenge(verifier));
  target.searchParams.set("code_challenge_method", "S256");

  const response = NextResponse.redirect(target);
  response.cookies.set(OIDC_FLOW_COOKIE, flowValue({ state, nonce, verifier }), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 10 * 60,
  });
  return response;
}
