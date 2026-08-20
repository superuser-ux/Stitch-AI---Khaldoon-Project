// #410 — the product-surface ledger. A rendered, READ-ONLY, NON-navigational panel that shows the
// COMPLETE planned product map, driven by the same canonical registry. Deferred/scaffolded surfaces
// are never clickable and never imply operational behavior; their state is shown through the shared
// semantic tone (dimmed) PLUS visible status copy (color is never the sole signal).

import {
  productLedger,
  surfaceTone,
  isNavigable,
  type ProductSurface,
  PRODUCT_STATUS_LABEL,
  IMPLEMENTATION_STATE_LABEL,
  ROUTE_AVAILABILITY_LABEL,
} from "@/lib/product-surface";

function OwnerLine({ s }: { s: ProductSurface }) {
  return (
    <span className="text-[11px] text-(--color-subtle)">
      {s.owner.productArea} · {s.owner.authority}
      {s.owner.trackingIssue ? ` · ${s.owner.trackingIssue}` : ""}
    </span>
  );
}

function StatusChips({ s }: { s: ProductSurface }) {
  return (
    <span className="flex flex-wrap items-center gap-1">
      <span
        data-testid={`ledger-status-${s.id}`}
        className="rounded-full border border-(--color-border-subtle) px-1.5 py-0.5 text-[10px] text-(--color-muted)"
      >
        {PRODUCT_STATUS_LABEL[s.productStatus]}
      </span>
      <span
        data-testid={`ledger-impl-${s.id}`}
        className="rounded-full border border-(--color-border-subtle) px-1.5 py-0.5 text-[10px] text-(--color-muted)"
      >
        {IMPLEMENTATION_STATE_LABEL[s.implementationState]}
      </span>
      <span className="rounded-full border border-(--color-border-subtle) px-1.5 py-0.5 text-[10px] text-(--color-muted)">
        Route: {ROUTE_AVAILABILITY_LABEL[s.routeAvailability]}
      </span>
      {s.showInNavigation && (
        <span className="rounded-full border border-(--color-border-subtle) px-1.5 py-0.5 text-[10px] text-(--color-muted)">
          In navigation
        </span>
      )}
    </span>
  );
}

function SurfaceRow({
  s,
  nested,
  children,
}: {
  s: ProductSurface;
  nested?: boolean;
  children?: React.ReactNode;
}) {
  const tone = surfaceTone(s.implementationState);
  const navigable = isNavigable(s);
  return (
    <li
      // The single shared semantic-state hook: `.surface-tone` + data-surface-tone drives the visual
      // treatment from registry state (globals.css). Never a per-component opacity guess.
      className={`surface-tone ${nested ? "ms-4" : ""} rounded-md border border-(--color-border-subtle) p-2`}
      data-testid={`ledger-surface-${s.id}`}
      data-surface-tone={tone}
      data-implementation-state={s.implementationState}
      // Disabled semantics for non-navigable surfaces — legible + discoverable, but never operable.
      aria-disabled={navigable ? undefined : true}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-1">
        <span className="text-sm font-medium">{s.label}</span>
        <StatusChips s={s} />
      </div>
      <p className="mt-0.5 text-xs text-(--color-muted)">{s.description}</p>
      <div className="mt-0.5">
        <OwnerLine s={s} />
      </div>
      {/* Children nest INSIDE this <li> (valid: a <ul> may live in an <li>, never directly in a <ul>). */}
      {children}
    </li>
  );
}

export function ProductSurfaceLedger() {
  const ledger = productLedger();
  return (
    <section data-testid="product-surface-ledger" aria-label="Product-surface ledger" className="space-y-2">
      <div>
        <h2 className="text-sm font-semibold">Product-surface ledger</h2>
        <p className="text-xs text-(--color-muted)">
          The complete planned product map. Deferred surfaces are roadmap truth, not simulated
          functionality — they are shown dimmed with their status and are never navigable.
        </p>
      </div>
      <ul className="space-y-2">
        {ledger.map((node) => (
          <SurfaceRow key={node.id} s={node}>
            {node.children.length > 0 && (
              <ul className="mt-2 space-y-2">
                {node.children.map((c) => (
                  <SurfaceRow key={c.id} s={c} nested />
                ))}
              </ul>
            )}
          </SurfaceRow>
        ))}
      </ul>
    </section>
  );
}
