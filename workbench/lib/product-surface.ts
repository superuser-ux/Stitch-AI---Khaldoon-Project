// #410 — the SINGLE canonical product-surface metadata registry.
//
// This is the sole source of product-surface identity, ownership, and the four INDEPENDENT status
// dimensions the SRD requires (navigation presence, implementation state, route availability, product
// status). Runtime consumers read it through FILTERED views and may never independently redefine a
// label, a state dimension, or ownership:
//   - the V2 global shell renders only `showInNavigation` entries (navigationSurfaces)
//   - Process Studio renders its own children (childrenOf("process-studio"))
//   - the non-navigational product-surface ledger renders the COMPLETE planned map (productLedger)
//
// It is NOT a second navigation authority and does not replace #331: run/stage/lens context stays with
// ShellNavProvider. This registry only names product destinations and their truthful state. It is a
// pure module (no React/Next imports) so the Node unit test can validate it directly.

export type ProductStatus = "operational" | "preview" | "planned";

// The canonical implementation-state vocabulary. The FIRST two are "active" (normal foreground +
// interaction); the remaining four are "dimmed" (theme-aware supportive treatment). This split is the
// single authority behind the visual implementation-state language — see surfaceTone().
export type ImplementationState =
  | "operational"
  | "implemented"
  | "scaffolded"
  | "deferred"
  | "blocked"
  | "unavailable";

export type RouteAvailability = "available" | "planned" | "none";

export interface SurfaceOwner {
  productArea: string;
  authority: string;
  // Optional governance pointer. `owner` NEVER names a person or team — only a product area + authority.
  trackingIssue?: string;
}

export interface ProductSurface {
  id: string;
  parentId: string | null;
  label: string;
  description: string;
  productStatus: ProductStatus;
  implementationState: ImplementationState;
  routeAvailability: RouteAvailability;
  showInNavigation: boolean;
  owner: SurfaceOwner;
  // ── rendering bindings — NOT status dimensions ─────────────────────────────────────────────────
  // `route` is the href and is present IFF routeAvailability === "available". `testId` is the stable
  // e2e hook (existing IDs preserved verbatim). `navOrder` orders the global nav for nav consumers
  // only; it is presentation ordering, never a product-status meaning.
  route?: string;
  testId?: string;
  navOrder?: number;
}

// The complete planned product map. Top-level order is the canonical ledger order the SRD names:
// Workbench, Process Studio, Inbox & Tasks, Content, Analytics & Learning, Agents, Administration.
// Only Process Studio is newly navigable in this slice; Identity and Secrets (existing, operational)
// remain represented and navigable under Administration.
export const PRODUCT_SURFACES: readonly ProductSurface[] = [
  {
    id: "workbench",
    parentId: null,
    label: "Workbench",
    description:
      "The operational schedule-first Workbench: runs, lifecycle stages, and lenses (#331 authority).",
    productStatus: "operational",
    implementationState: "operational",
    routeAvailability: "available",
    showInNavigation: false, // the root/home — represented by the brand, not a global nav button
    route: "/",
    owner: { productArea: "Workbench", authority: "SRD #331 shell/context authority", trackingIssue: "#331" },
  },
  {
    id: "process-studio",
    parentId: null,
    label: "Process Studio",
    description:
      "Read-only product-authoring context for the generic workflow graph direction. Demonstration only in this slice; never a run, lifecycle stage, or Workbench lens.",
    productStatus: "preview",
    implementationState: "implemented",
    routeAvailability: "available",
    showInNavigation: true,
    navOrder: 3,
    route: "/studio",
    testId: "process-studio-link",
    owner: { productArea: "Process Studio", authority: "SRD generic-workflow architecture", trackingIssue: "#410" },
  },
  {
    id: "inbox-tasks",
    parentId: null,
    label: "Inbox & Tasks",
    description: "Planned operator inbox and task queue. Roadmap truth — not built in this slice.",
    productStatus: "planned",
    implementationState: "deferred",
    routeAvailability: "planned",
    showInNavigation: false,
    owner: { productArea: "Inbox & Tasks", authority: "SRD roadmap" },
  },
  {
    id: "content",
    parentId: null,
    label: "Content",
    description:
      "Planned content library and delivery surfaces. #294 remains the social-content delivery ledger, not a universal workflow definition.",
    productStatus: "planned",
    implementationState: "deferred",
    routeAvailability: "planned",
    showInNavigation: false,
    owner: { productArea: "Content", authority: "SRD roadmap", trackingIssue: "#294" },
  },
  {
    id: "analytics-learning",
    parentId: null,
    label: "Analytics & Learning",
    description: "Planned analytics and learning surfaces. Roadmap truth — not built in this slice.",
    productStatus: "planned",
    implementationState: "deferred",
    routeAvailability: "planned",
    showInNavigation: false,
    owner: { productArea: "Analytics & Learning", authority: "SRD roadmap" },
  },
  {
    id: "agents",
    parentId: null,
    label: "Agents",
    description:
      "Planned first-class Agents surface. The in-workbench agent panel is not this destination.",
    productStatus: "planned",
    implementationState: "scaffolded",
    routeAvailability: "planned",
    showInNavigation: false,
    owner: { productArea: "Agents", authority: "SRD roadmap" },
  },
  {
    id: "administration",
    parentId: null,
    label: "Administration",
    description:
      "Operator administration. Identity and Secrets are already operational; the consolidated surface is planned.",
    productStatus: "planned",
    implementationState: "scaffolded",
    routeAvailability: "planned",
    showInNavigation: false,
    owner: { productArea: "Administration", authority: "SRD roadmap" },
  },
  // ── Administration children (existing, operational, navigable) ─────────────────────────────────
  {
    id: "identity",
    parentId: "administration",
    label: "Identity",
    description: "Identity administration.",
    productStatus: "operational",
    implementationState: "operational",
    routeAvailability: "available",
    showInNavigation: true,
    navOrder: 1,
    route: "/admin/identity",
    testId: "identity-admin-link",
    owner: { productArea: "Administration", authority: "IAM" },
  },
  {
    id: "secrets",
    parentId: "administration",
    label: "Secrets",
    description: "Secrets administration.",
    productStatus: "operational",
    implementationState: "operational",
    routeAvailability: "available",
    showInNavigation: true,
    navOrder: 2,
    route: "/admin/secrets",
    testId: "secrets-admin-link",
    owner: { productArea: "Administration", authority: "Secrets custody" },
  },
  // ── Process Studio children — the "Planned capabilities" list, rendered NON-interactively ───────
  {
    id: "ps-palette",
    parentId: "process-studio",
    label: "Node palette",
    description: "Add and configure stage-type / capability nodes.",
    productStatus: "planned",
    implementationState: "deferred",
    routeAvailability: "none",
    showInNavigation: false,
    owner: { productArea: "Process Studio", authority: "SRD roadmap", trackingIssue: "#39" },
  },
  {
    id: "ps-validation",
    parentId: "process-studio",
    label: "Graph validation",
    description: "Validate graph structure against stage-type compatibility constraints.",
    productStatus: "planned",
    implementationState: "deferred",
    routeAvailability: "none",
    showInNavigation: false,
    owner: { productArea: "Process Studio", authority: "SRD roadmap", trackingIssue: "#39" },
  },
  {
    id: "ps-releases",
    parentId: "process-studio",
    label: "Releases & version history",
    description: "Publish and browse workflow versions across a family lifecycle.",
    productStatus: "planned",
    implementationState: "deferred",
    routeAvailability: "none",
    showInNavigation: false,
    owner: { productArea: "Process Studio", authority: "SRD roadmap", trackingIssue: "#6" },
  },
  {
    id: "ps-archive",
    parentId: "process-studio",
    label: "Archive / restore",
    description: "Archive and restore workflow families and versions.",
    productStatus: "planned",
    implementationState: "deferred",
    routeAvailability: "none",
    showInNavigation: false,
    owner: { productArea: "Process Studio", authority: "SRD roadmap", trackingIssue: "#6" },
  },
  {
    id: "ps-methodology",
    parentId: "process-studio",
    label: "Methodology bindings",
    description:
      "Bind methodology profiles that modify planning/generation without becoming workflow identity.",
    productStatus: "planned",
    implementationState: "deferred",
    routeAvailability: "none",
    showInNavigation: false,
    owner: { productArea: "Process Studio", authority: "SRD roadmap", trackingIssue: "#242" },
  },
  {
    id: "ps-approvals",
    parentId: "process-studio",
    label: "Approval bindings",
    description: "Workflow-version-scoped approval requirements (#9 approval semantics).",
    productStatus: "planned",
    implementationState: "deferred",
    routeAvailability: "none",
    showInNavigation: false,
    owner: { productArea: "Process Studio", authority: "SRD roadmap", trackingIssue: "#9" },
  },
] as const;

// ── derived, filtered views (the only sanctioned consumers) ──────────────────────────────────────

/** Global-shell consumer: navigable destinations only, in presentation order. */
export function navigationSurfaces(): ProductSurface[] {
  return PRODUCT_SURFACES.filter((s) => s.showInNavigation).sort(
    (a, b) => (a.navOrder ?? 0) - (b.navOrder ?? 0),
  );
}

/** Process Studio consumer (and the ledger's nesting): children of a surface, in declaration order. */
export function childrenOf(id: string): ProductSurface[] {
  return PRODUCT_SURFACES.filter((s) => s.parentId === id);
}

/** The complete planned map's roots, in canonical ledger order. */
export function topLevelSurfaces(): ProductSurface[] {
  return PRODUCT_SURFACES.filter((s) => s.parentId === null);
}

export interface LedgerNode extends ProductSurface {
  children: ProductSurface[];
}

/** Ledger consumer: the COMPLETE planned set as roots + their children. */
export function productLedger(): LedgerNode[] {
  return topLevelSurfaces().map((s) => ({ ...s, children: childrenOf(s.id) }));
}

export function getSurface(id: string): ProductSurface | undefined {
  return PRODUCT_SURFACES.find((s) => s.id === id);
}

// ── the visual implementation-state language (shared, not per-component) ──────────────────────────

export type SurfaceTone = "active" | "dimmed";

const ACTIVE_STATES: ReadonlySet<ImplementationState> = new Set(["operational", "implemented"]);

/** The single mapping from implementation state to visual tone. Both the nav and the ledger consume
 *  THIS, so a surface's treatment changes consistently the instant its registry state changes. */
export function surfaceTone(state: ImplementationState): SurfaceTone {
  return ACTIVE_STATES.has(state) ? "active" : "dimmed";
}

/** A destination is navigable only when it declares nav presence AND a real available route. */
export function isNavigable(s: ProductSurface): boolean {
  return s.showInNavigation && s.routeAvailability === "available" && typeof s.route === "string";
}

// Human-facing status copy — color is never the sole signal, so every surface carries visible text.
export const PRODUCT_STATUS_LABEL: Record<ProductStatus, string> = {
  operational: "Operational",
  preview: "Preview",
  planned: "Planned",
};
export const IMPLEMENTATION_STATE_LABEL: Record<ImplementationState, string> = {
  operational: "Operational",
  implemented: "Implemented",
  scaffolded: "Scaffolded",
  deferred: "Deferred",
  blocked: "Blocked",
  unavailable: "Unavailable",
};
export const ROUTE_AVAILABILITY_LABEL: Record<RouteAvailability, string> = {
  available: "Available",
  planned: "Planned",
  none: "None",
};

// ── validation (used by the unit test and safe to call anywhere) ──────────────────────────────────

/** Returns a list of structural violations. Empty ⇒ the registry is internally consistent. */
export function validateRegistry(surfaces: readonly ProductSurface[] = PRODUCT_SURFACES): string[] {
  const errors: string[] = [];
  const ids = new Set<string>();
  for (const s of surfaces) {
    if (ids.has(s.id)) errors.push(`duplicate id: ${s.id}`);
    ids.add(s.id);
  }
  const navOrders = new Set<number>();
  for (const s of surfaces) {
    if (s.parentId !== null && !surfaces.some((p) => p.id === s.parentId)) {
      errors.push(`${s.id}: parentId "${s.parentId}" does not exist`);
    }
    if (!s.label.trim()) errors.push(`${s.id}: empty label`);
    if (!s.description.trim()) errors.push(`${s.id}: empty description`);
    if (!s.owner.productArea.trim()) errors.push(`${s.id}: owner.productArea empty`);
    if (!s.owner.authority.trim()) errors.push(`${s.id}: owner.authority empty`);
    // owner must never name a person/team — reject an @handle / email shape as a cheap guard.
    if (/@/.test(s.owner.productArea) || /@/.test(s.owner.authority)) {
      errors.push(`${s.id}: owner must name a product area + authority, never a person/team`);
    }
    // route availability ⇔ route presence
    if (s.routeAvailability === "available" && !s.route) {
      errors.push(`${s.id}: routeAvailability "available" but no route`);
    }
    if (s.routeAvailability !== "available" && s.route) {
      errors.push(`${s.id}: route present but routeAvailability is "${s.routeAvailability}"`);
    }
    // a route must be an internal absolute path
    if (s.route && !s.route.startsWith("/")) errors.push(`${s.id}: route must be an absolute path`);
    // navigable entries need a real route + stable testId + unique navOrder
    if (s.showInNavigation) {
      if (!isNavigable(s)) errors.push(`${s.id}: showInNavigation but not routable`);
      if (!s.testId) errors.push(`${s.id}: navigable surface needs a stable testId`);
      if (typeof s.navOrder !== "number") errors.push(`${s.id}: navigable surface needs a navOrder`);
      else {
        if (navOrders.has(s.navOrder)) errors.push(`duplicate navOrder: ${s.navOrder}`);
        navOrders.add(s.navOrder);
      }
    }
  }
  return errors;
}
