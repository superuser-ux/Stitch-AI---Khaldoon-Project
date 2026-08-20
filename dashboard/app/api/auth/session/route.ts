import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { IAM_SESSION_COOKIE, iamEnabled, readSession } from "@/lib/iam-session";

// #190 — session read model for the UI. Truthful three-state: unauthenticated (show sign-in),
// authenticated-but-unbound (show no-operating-identity — NEVER a persona/demo fallback),
// authenticated + bound (operate as the mapped principal).
export async function GET() {
  if (!iamEnabled()) return NextResponse.json({ iam: false });
  const jar = await cookies();
  const session = readSession(jar.get(IAM_SESSION_COOKIE)?.value);
  if (!session) return NextResponse.json({ iam: true, authenticated: false });
  return NextResponse.json({
    iam: true,
    authenticated: true,
    principal_id: session.principal_id,
    unbound: session.principal_id === null,
    display: session.display,
    email: session.email,
  });
}
