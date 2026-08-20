import { NextRequest, NextResponse } from "next/server";
import { IAM_SESSION_COOKIE, iamEnabled, readSession } from "@/lib/iam-session";

export async function GET(req: NextRequest) {
  if (!iamEnabled()) return NextResponse.json({ iam: false });
  const session = readSession(req.cookies.get(IAM_SESSION_COOKIE)?.value);
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
