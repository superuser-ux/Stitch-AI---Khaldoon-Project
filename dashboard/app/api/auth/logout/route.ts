import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { IAM_SESSION_COOKIE, OIDC_FLOW_COOKIE, discover, iamEnabled, oidcConfig } from "@/lib/iam-session";

// #388-B — always end the local BFF session; when discovery advertises RP-initiated logout, return
// the provider URL so the browser can terminate that session too. Provider failure never preserves
// the local cookie.
export async function POST(req: NextRequest) {
  let redirect = "/";
  if (iamEnabled()) {
    const config = oidcConfig();
    try {
      const document = await discover(config.issuer);
      if (document.end_session_endpoint) {
        const target = new URL(document.end_session_endpoint);
        target.searchParams.set("client_id", config.clientId);
        target.searchParams.set("post_logout_redirect_uri", new URL("/", req.nextUrl.origin).toString());
        redirect = target.toString();
      }
    } catch {
      // Local termination is independent of provider availability.
    }
  }
  const jar = await cookies();
  jar.delete(IAM_SESSION_COOKIE);
  jar.delete(OIDC_FLOW_COOKIE);
  return NextResponse.json({ ok: true, redirect });
}
