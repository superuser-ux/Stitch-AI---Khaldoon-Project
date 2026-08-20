"use client";

// #410 — Process Studio landing view. Read-only product-authoring context; NOT a run, lifecycle
// stage, or Workbench lens. Entering it never creates or reinterprets a run. Composes: workflow/
// template identity + demonstration provenance + version/status banner, the exact fixture disclosure,
// the read-only graph (lazy), selected-node details, one compact "Editing not available" explanation,
// the non-interactive Planned capabilities list, and the product-surface ledger. A safe internal
// "Return to Workbench" link preserves the originating URL (already validated server-side).

import { Suspense, lazy, useState } from "react";
import Link from "next/link";
import {
  illustrativeSocialWorkflow,
  FIXTURE_DISCLOSURE,
} from "./illustrative-social-workflow";
import { ProductSurfaceLedger } from "./product-surface-ledger";
import { childrenOf, surfaceTone, IMPLEMENTATION_STATE_LABEL } from "@/lib/product-surface";

// #152 — lazy client chunk via React.lazy + Suspense (NEVER next/dynamic on Next 15.4.11).
const WorkflowGraph = lazy(() => import("./workflow-graph"));

const EDITING_NOT_AVAILABLE =
  "Editing not available — Process Studio is a read-only demonstration in this slice. Builder functions below are planned, not active.";

function SelectedNodeDetails({ selectedId }: { selectedId: string | null }) {
  const node = selectedId
    ? illustrativeSocialWorkflow.nodes.find((n) => n.id === selectedId)
    : null;
  return (
    <div
      data-testid="studio-node-details"
      className="rounded-md border border-(--color-border-subtle) bg-(--color-card) p-3 text-sm"
    >
      <h3 className="text-xs font-semibold uppercase tracking-wide text-(--color-muted)">
        Selected node
      </h3>
      {node ? (
        <div className="mt-1 space-y-1">
          <p className="font-medium">{node.data.label}</p>
          <p className="text-xs text-(--color-muted)">{node.data.summary}</p>
          <p className="text-[11px] text-(--color-subtle)">
            UI node <code className="font-mono">{node.id}</code> · illustrates stage{" "}
            <code className="font-mono">{node.data.illustratesStage}</code>
          </p>
          <p className="text-[11px] text-(--color-subtle)">
            UI graph ids are display-only and separate from canonical stage / executable capability
            identifiers. React Flow serialization is never the backend execution contract.
          </p>
        </div>
      ) : (
        <p className="mt-1 text-xs text-(--color-muted)">
          Select a node to inspect its illustrative details. Inspection only — nothing here mutates data.
        </p>
      )}
    </div>
  );
}

function PlannedCapabilities() {
  const items = childrenOf("process-studio");
  return (
    <section aria-label="Planned capabilities" data-testid="studio-planned-capabilities" className="space-y-2">
      <div>
        <h2 className="text-sm font-semibold">Planned capabilities</h2>
        <p className="text-xs text-(--color-muted)">
          Later builder functions, shown for roadmap truth only. None are interactive in this slice.
        </p>
      </div>
      {/* Non-interactive on purpose: a plain list, no buttons/links, so nothing looks operable. */}
      <ul className="grid gap-2 sm:grid-cols-2">
        {items.map((c) => (
          <li
            key={c.id}
            data-testid={`planned-capability-${c.id}`}
            className="surface-tone rounded-md border border-(--color-border-subtle) p-2"
            data-surface-tone={surfaceTone(c.implementationState)}
            data-implementation-state={c.implementationState}
            aria-disabled
          >
            <div className="flex flex-wrap items-baseline justify-between gap-1">
              <span className="text-sm font-medium">{c.label}</span>
              {/* Canonical visible implementation-state text — color is never the sole signal. */}
              <span
                data-testid={`planned-capability-state-${c.id}`}
                className="rounded-full border border-(--color-border-subtle) px-1.5 py-0.5 text-[10px] text-(--color-muted)"
              >
                {IMPLEMENTATION_STATE_LABEL[c.implementationState]}
              </span>
            </div>
            <p className="mt-0.5 text-xs text-(--color-muted)">{c.description}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function StudioView({ returnTo }: { returnTo: string }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const wf = illustrativeSocialWorkflow;

  return (
    <div data-testid="studio-view" className="mx-auto flex max-w-5xl flex-col gap-4">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h1 className="text-lg font-semibold">Process Studio</h1>
            <p className="text-xs text-(--color-muted)">
              Read-only demonstration of the generic workflow graph direction.
            </p>
          </div>
          <Link
            href={returnTo}
            data-testid="studio-return-link"
            className="shrink-0 rounded-md border border-(--color-border) px-2.5 py-1 text-xs hover:bg-(--color-bg)"
          >
            ← Return to Workbench
          </Link>
        </div>

        {/* workflow/template identity + demonstration provenance + version/status banner */}
        <div
          data-testid="studio-identity-banner"
          className="rounded-md border border-(--color-border-subtle) bg-(--color-elevated) p-3"
        >
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-sm font-medium">{wf.templateName}</span>
            <span className="text-xs text-(--color-muted)">{wf.familyLabel}</span>
            <span
              data-testid="studio-version-status"
              className="rounded-full border border-(--color-border) px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-(--color-muted)"
            >
              v{wf.versionNo} · {wf.status}
            </span>
          </div>
          <p data-testid="studio-fixture-disclosure" className="mt-1 text-xs text-(--color-muted)">
            {FIXTURE_DISCLOSURE}
          </p>
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_280px]">
        <Suspense
          fallback={
            <div
              data-testid="studio-graph-loading"
              className="flex h-[460px] items-center justify-center rounded-xl border border-(--color-border) text-xs text-(--color-muted)"
            >
              Loading demonstration graph…
            </div>
          }
        >
          <WorkflowGraph onSelectNode={setSelectedId} />
        </Suspense>

        <div className="space-y-3">
          <SelectedNodeDetails selectedId={selectedId} />
          <p
            data-testid="studio-editing-unavailable"
            className="rounded-md border border-(--color-border-subtle) bg-(--color-sunken) p-2 text-xs text-(--color-muted)"
          >
            {EDITING_NOT_AVAILABLE}
          </p>
        </div>
      </div>

      <PlannedCapabilities />
      <ProductSurfaceLedger />
    </div>
  );
}
