import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { REVIEWER_COOKIE } from "@/lib/reviewer-session";
import { iamEnabled } from "@/lib/iam-session";

const DEFAULT_REVIEWER = "khal";
const REVIEWER_RE = /^[A-Za-z0-9._-]+$/;

export async function GET() {
  const jar = await cookies();
  const cookieReviewer = jar.get(REVIEWER_COOKIE)?.value || "";
  // #170 — `explicit` tells the client whether this browser ever chose a reviewer (cookie present)
  // or is falling back to the default. A fresh internal browser (explicit=false) gets the demo
  // persona entry surface; an established session skips it.
  return NextResponse.json({ reviewer: cookieReviewer || DEFAULT_REVIEWER, explicit: Boolean(cookieReviewer) });
}

// #180 — scoped recovery: clears ONLY the Tanaghom reviewer cookie (httpOnly, so the client's
// "Reset local view state" action cannot expire it itself). Part of resetting Tanaghom-owned
// browser state; a fresh window then re-enters via the #170 persona surface.
export async function DELETE() {
  const jar = await cookies();
  jar.delete(REVIEWER_COOKIE);
  return NextResponse.json({ ok: true });
}

export async function POST(req: NextRequest) {
  // #190 — persona/reviewer switching is a demo-mode mechanism; in IAM mode identity comes only
  // from the authenticated session and this endpoint must not offer a parallel identity path.
  if (iamEnabled()) {
    return NextResponse.json({ error: "reviewer switching is disabled under IAM" }, { status: 403 });
  }
  const body = await req.json().catch(() => ({}));
  const reviewer = typeof body?.reviewer === "string" ? body.reviewer.trim() : "";
  if (!reviewer || !REVIEWER_RE.test(reviewer)) {
    return NextResponse.json({ error: "bad reviewer id" }, { status: 400 });
  }
  const jar = await cookies();
  jar.set(REVIEWER_COOKIE, reviewer, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  return NextResponse.json({ reviewer });
}

