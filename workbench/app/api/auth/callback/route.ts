import { NextRequest, NextResponse } from "next/server";
import {
  IAM_SESSION_COOKIE,
  OIDC_FLOW_COOKIE,
  exchangeCode,
  iamEnabled,
  oidcConfig,
  readFlow,
  resolveBinding,
  sessionValue,
} from "@/lib/iam-session";

function browserOrigin(req: NextRequest, redirectUri: string | null): string {
  return redirectUri ? new URL(redirectUri).origin : req.nextUrl.origin;
}

function fail(req: NextRequest, reason: string, redirectUri: string | null) {
  const target = new URL("/", browserOrigin(req, redirectUri));
  target.searchParams.set("auth_error", reason);
  const response = NextResponse.redirect(target);
  response.cookies.delete(OIDC_FLOW_COOKIE);
  response.cookies.delete(IAM_SESSION_COOKIE);
  return response;
}

export async function GET(req: NextRequest) {
  if (!iamEnabled()) return NextResponse.json({ error: "iam disabled" }, { status: 404 });
  const config = oidcConfig();
  const flow = readFlow(req.cookies.get(OIDC_FLOW_COOKIE)?.value);
  const code = req.nextUrl.searchParams.get("code") || "";
  const state = req.nextUrl.searchParams.get("state") || "";
  if (!flow) return fail(req, "login flow expired; try again", config.redirectUri);
  if (!code || !state || state !== flow.state) return fail(req, "state mismatch", config.redirectUri);

  const redirectUri = config.redirectUri || new URL("/api/auth/callback", req.nextUrl.origin).toString();
  try {
    const { payload } = await exchangeCode(code, flow.verifier, flow.nonce, redirectUri);
    const subject = String(payload.sub);
    const binding = await resolveBinding(config.issuer, subject);
    const response = NextResponse.redirect(new URL("/", browserOrigin(req, config.redirectUri)));
    response.cookies.delete(OIDC_FLOW_COOKIE);
    response.cookies.set(IAM_SESSION_COOKIE, sessionValue({
      iss: config.issuer,
      sub: subject,
      principal_id: binding.principal_id,
      display: binding.display_name_en || (typeof payload.name === "string" ? payload.name : null),
      email: typeof payload.email === "string" ? payload.email : null,
    }), {
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: 8 * 60 * 60,
    });
    return response;
  } catch (error) {
    return fail(
      req,
      `sign-in rejected: ${error instanceof Error ? error.message : "verification failed"}`,
      config.redirectUri,
    );
  }
}
