// #410 — focused unit + type validation for the canonical product-surface registry and the safe
// "Return to Workbench" contract. Pure functions; no browser, no network, no stack. Run:
//   node --experimental-strip-types scripts/product-surface.test.ts
// Kept out of e2e/ so Playwright never collects it.
import { strict as assert } from "node:assert";
import {
  PRODUCT_SURFACES,
  navigationSurfaces,
  childrenOf,
  topLevelSurfaces,
  productLedger,
  getSurface,
  surfaceTone,
  isNavigable,
  validateRegistry,
} from "../lib/product-surface.ts";
import { safeInternalPath } from "../lib/safe-return.ts";

let failures = 0;
function check(name: string, cond: boolean) {
  if (cond) console.log(`  [PASS] ${name}`);
  else {
    failures += 1;
    console.log(`  [FAIL] ${name}`);
  }
}

// ── registry structural integrity ─────────────────────────────────────────────────────────────────
const errs = validateRegistry();
check(`registry validates clean (${errs.join("; ") || "no errors"})`, errs.length === 0);

// ── the complete planned map is present, in canonical ledger order ──────────────────────────────────
const topIds = topLevelSurfaces().map((s) => s.id);
check(
  "ledger top-level order is canonical",
  JSON.stringify(topIds) ===
    JSON.stringify([
      "workbench",
      "process-studio",
      "inbox-tasks",
      "content",
      "analytics-learning",
      "agents",
      "administration",
    ]),
);
const ledger = productLedger();
check("ledger renders the complete planned set of 7 roots", ledger.length === 7);
check(
  "ledger includes every named planned surface",
  ["Workbench", "Process Studio", "Inbox & Tasks", "Content", "Analytics & Learning", "Agents", "Administration"].every(
    (label) => ledger.some((n) => n.label === label),
  ),
);

// ── navigation: exactly Identity, Secrets, Process Studio, in that order ────────────────────────────
const nav = navigationSurfaces();
check(
  "nav = identity, secrets, process-studio (order preserved, Studio last)",
  JSON.stringify(nav.map((s) => s.id)) === JSON.stringify(["identity", "secrets", "process-studio"]),
);
check("Process Studio is the only NEWLY navigable destination", nav.filter((s) => s.id === "process-studio").length === 1);
check("existing Identity href/testId preserved", getSurface("identity")?.route === "/admin/identity" && getSurface("identity")?.testId === "identity-admin-link");
check("existing Secrets href/testId preserved", getSurface("secrets")?.route === "/admin/secrets" && getSurface("secrets")?.testId === "secrets-admin-link");
check("Process Studio routes to /studio", getSurface("process-studio")?.route === "/studio");
check("every nav entry is genuinely navigable", nav.every(isNavigable));

// ── planned, non-navigable surfaces never claim a route ─────────────────────────────────────────────
const nonNav = PRODUCT_SURFACES.filter((s) => !s.showInNavigation && s.id !== "workbench");
check("planned/non-nav surfaces are not navigable", nonNav.every((s) => !isNavigable(s)));

// ── Process Studio's children are exactly the six planned capabilities ──────────────────────────────
const caps = childrenOf("process-studio").map((s) => s.label);
check(
  "planned capabilities are the six named builder functions",
  JSON.stringify(caps) ===
    JSON.stringify([
      "Node palette",
      "Graph validation",
      "Releases & version history",
      "Archive / restore",
      "Methodology bindings",
      "Approval bindings",
    ]),
);
check("no planned capability is navigable", childrenOf("process-studio").every((s) => !isNavigable(s)));

// ── the visual state language: independent dimensions + correct tone split ──────────────────────────
check("operational/implemented tone is active", surfaceTone("operational") === "active" && surfaceTone("implemented") === "active");
check(
  "scaffolded/deferred/blocked/unavailable tone is dimmed",
  ["scaffolded", "deferred", "blocked", "unavailable"].every((s) => surfaceTone(s as any) === "dimmed"),
);
// Administration is dimmed (scaffolded) yet has navigable operational children — dimensions independent.
check(
  "a dimmed parent can own active navigable children (independent dimensions)",
  surfaceTone(getSurface("administration")!.implementationState) === "dimmed" &&
    isNavigable(getSurface("identity")!),
);

// ── owner never names a person/team ─────────────────────────────────────────────────────────────────
check(
  "owner names product area + authority only (no @handle/email)",
  PRODUCT_SURFACES.every((s) => !/@/.test(s.owner.productArea) && !/@/.test(s.owner.authority)),
);

// ── validateRegistry catches injected violations ────────────────────────────────────────────────────
check(
  "validateRegistry rejects a dangling parentId",
  validateRegistry([{ ...PRODUCT_SURFACES[0], id: "x", parentId: "nope" }]).some((e) => e.includes("does not exist")),
);
check(
  "validateRegistry rejects navigable-without-route",
  validateRegistry([
    { ...getSurface("process-studio")!, id: "y", route: undefined, routeAvailability: "planned" },
  ]).some((e) => e.includes("routable") || e.includes("route")),
);

// ── safe-return contract (reconciliation C) ─────────────────────────────────────────────────────────
check("valid internal path preserved with query+hash", safeInternalPath("/runs/RE2E?lens=grid#top") === "/runs/RE2E?lens=grid#top");
check("root passes through", safeInternalPath("/") === "/");
check("empty/undefined -> /", safeInternalPath("") === "/" && safeInternalPath(undefined) === "/" && safeInternalPath(null) === "/");
check("protocol-relative // -> /", safeInternalPath("//evil.example/x") === "/");
check("absolute http URL -> /", safeInternalPath("http://evil.example/x") === "/");
check("scheme (javascript:) -> /", safeInternalPath("javascript:alert(1)") === "/");
check("backslash smuggling -> /", safeInternalPath("/\\evil.example") === "/" && safeInternalPath("\\evil") === "/");
check("non-leading-slash relative -> /", safeInternalPath("runs/RE2E") === "/");
check("control/whitespace -> /", safeInternalPath("/a b") === "/" && safeInternalPath("/a\nb") === "/");

console.log(failures === 0 ? "\nALL PRODUCT-SURFACE CHECKS PASSED" : `\nFAILURES: ${failures}`);
process.exit(failures === 0 ? 0 : 1);
