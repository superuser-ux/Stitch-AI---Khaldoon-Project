import { NextRequest, NextResponse } from "next/server";

// Locked-down client-trial mode (Refs #13). When CLIENT_TRIAL_MODE=true (a RUNTIME env, so the same
// build serves the normal dev dashboard when it is unset), this is the SERVER-ENFORCED access gate:
//  - admin/dev routes are hard-blocked (redirected) regardless of any client-side tampering;
//  - a readable `client_trial` cookie tells the UI to hide operator/admin controls + show the trial banner.
// Security lives in the route block here; the cookie only drives cosmetics, so a tampered cookie cannot
// reach a blocked route.
const BLOCKED_PREFIXES = ["/admin"];

export function middleware(req: NextRequest) {
  if (process.env.CLIENT_TRIAL_MODE !== "true") {
    // #180 — server truth beats stale browser state: an operator/dev surface actively CLEARS any
    // trial cookie left behind by a visit to a trial surface on the same host (browsers share
    // localhost cookies across ports), so stale state can never dress the operator surface as the
    // locked client UI (the Opera incident).
    if (req.cookies.get("client_trial")) {
      const res = NextResponse.next();
      res.cookies.delete("client_trial");
      return res;
    }
    return NextResponse.next();
  }

  const { pathname } = req.nextUrl;
  if (BLOCKED_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + "/"))) {
    const url = req.nextUrl.clone();
    url.pathname = "/";
    return NextResponse.redirect(url);
  }

  const res = NextResponse.next();
  res.cookies.set("client_trial", "1", { path: "/", sameSite: "lax", httpOnly: false });
  return res;
}

// run on pages/proxy but skip static assets
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|brand|icon.svg).*)"],
};
