import { NextRequest, NextResponse } from "next/server";
import {
  IAM_SESSION_COOKIE,
  OIDC_FLOW_COOKIE,
  discover,
  iamEnabled,
  oidcConfig,
} from "@/lib/iam-session";

export async function POST(req: NextRequest) {
  let redirect = "/";
  if (iamEnabled()) {
    const config = oidcConfig();
    try {
      const document = await discover(config.issuer, config.internalBaseUrl);
      if (document.end_session_endpoint) {
        const target = new URL(document.end_session_endpoint);
        target.searchParams.set("client_id", config.clientId);
        target.searchParams.set(
          "post_logout_redirect_uri",
          config.postLogoutRedirectUri || new URL("/", req.nextUrl.origin).toString(),
        );
        redirect = target.toString();
      }
    } catch {
      // Local session termination remains successful when the provider is unavailable.
    }
  }
  const response = NextResponse.json({ ok: true, redirect });
  response.cookies.delete(IAM_SESSION_COOKIE);
  response.cookies.delete(OIDC_FLOW_COOKIE);
  return response;
}
