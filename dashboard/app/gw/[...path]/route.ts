import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { principalProxyHeaders, REVIEWER_COOKIE } from "@/lib/reviewer-session";
import { PERSONA_HEADER, PERSONA_ID_RE } from "@/lib/persona-session";
import { IAM_SESSION_COOKIE, iamEnabled, readSession, revalidateBinding } from "@/lib/iam-session";

const API = process.env.API_BASE || "http://localhost:8009";
const DEFAULT_REVIEWER = "khal";

async function proxy(req: NextRequest, path: string[]) {
  const url = new URL(req.url);
  const target = new URL(`${API}/${path.join("/")}`);
  target.search = url.search;

  const jar = await cookies();
  let reviewer: string;
  if (iamEnabled()) {
    // #190 — IAM mode: the ONLY identity the proxy signs is the authenticated session's BOUND
    // principal. No session → 401; authenticated-but-unbound → 403 (truthful, never a default).
    // The #170 persona header and reviewer cookie are demo-mode mechanisms and are deliberately
    // IGNORED here — they must never become a parallel authority path in production.
    const session = readSession(jar.get(IAM_SESSION_COOKIE)?.value);
    if (!session) {
      return NextResponse.json({ detail: "not authenticated" }, { status: 401 });
    }
    if (!session.principal_id) {
      return NextResponse.json({ detail: "no operating identity assigned" }, { status: 403 });
    }
    // #194 — immediate revocation: the session principal is honored ONLY while its binding still
    // resolves identically right now. Absent/deactivated → access not configured; re-mapped →
    // reauthentication required (a session never silently switches principal); gate API down →
    // fail closed WITHOUT ending the session (transient).
    const binding = await revalidateBinding(session);
    if (binding === "unavailable") {
      return NextResponse.json({ detail: "identity check unavailable — try again" }, { status: 503 });
    }
    if (binding !== "ok") {
      const res = NextResponse.json(
        binding === "unbound"
          ? { detail: "access not configured" }
          : { detail: "reauthentication required" },
        { status: binding === "unbound" ? 403 : 401 },
      );
      res.cookies.delete(IAM_SESSION_COOKIE);
      return res;
    }
    reviewer = session.principal_id;
  } else {
    // #170 — demo/internal mode: per-window persona header (sessionStorage-backed) overrides the
    // profile-wide reviewer cookie so parallel windows can act as different personas. Same trust
    // level as the cookie (client-selected operational identity, not auth); signing stays
    // server-side and the gate API still enforces assignments at decide time (#10).
    const headerPersona = (req.headers.get(PERSONA_HEADER) || "").trim();
    reviewer = (headerPersona && PERSONA_ID_RE.test(headerPersona))
      ? headerPersona
      : (jar.get(REVIEWER_COOKIE)?.value || DEFAULT_REVIEWER);
  }
  const headers = new Headers();
  const contentType = req.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  for (const [key, value] of Object.entries(principalProxyHeaders(reviewer))) {
    headers.set(key, value);
  }

  const init: RequestInit = {
    method: req.method,
    headers,
    cache: "no-store",
  };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }

  const res = await fetch(target, init);
  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") || "application/json" },
  });
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(req, path);
}

export async function POST(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(req, path);
}

export async function PUT(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  return proxy(req, path);
}
