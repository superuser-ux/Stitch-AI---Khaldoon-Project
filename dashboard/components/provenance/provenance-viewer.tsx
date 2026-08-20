"use client";

import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ShieldAlert, Network, List as ListIcon } from "lucide-react";
import { GW } from "@/lib/review-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

// #81 — the React Flow canvas stays a lazy separate chunk; it only mounts after the user toggles
// to the graph view (default is "list"), so it never SSR-renders. #152 — this must be React.lazy,
// NOT next/dynamic: on Next 15.1.4 — where the defect was discovered and proved — any next/dynamic()
// call inside this module stopped the RSC bundler from registering it in the client-reference
// manifest, and every fresh production build then 500s the route with "Could not find the module
// …#ProvenanceViewer in the React Client Manifest".
// #297 — the runtime is now exact Next 15.4.11 with React 19.0.0. React.lazy + Suspense stays the
// retained repository convention and was RE-PROVED at 15.4.11: fresh production build, this route
// serving 200, no client-reference-manifest failure. Whether next/dynamic still reproduces #152 on
// 15.4.11 is deliberately UNTESTED — nothing depends on the answer, and swapping back would need its
// own evidenced directive rather than an assumption that a newer bundler must have fixed it.
const ProvenanceGraph = lazy(() => import("./provenance-graph").then((m) => ({ default: m.ProvenanceGraph })));
const GraphLoading = () => (
  <div data-testid="prov-graph-loading" className="flex h-[600px] items-center justify-center rounded-xl border text-sm text-muted-foreground">
    Loading graph…
  </div>
);

// M7 provenance viewer SHELL (#71 / directive #74) — a read-only, honesty-first LIST view over the
// GET /rounds/{round_id}/provenance read model (PR #73). NOT the graph canvas: no layout library,
// no node-edge rendering. Every node/edge/timeline row shows its data-source citation, and the
// unsupported[] list is surfaced as a first-class "what this does NOT claim" legend.

type Cite = { table: string; field: string };
type PNode = { id: string; type: string; label: string; cite?: Cite; source_id?: string; deep_link?: string | null; meta?: Record<string, unknown> };
type PEdge = { id: string; type: string; source: string; target: string; cite?: Cite; source_id?: string; meta?: Record<string, unknown> };
type PEvent = { id: string; at: string | null; entity: string; entity_id: string; action: string; actor: string | null; actor_kind: string | null; cite?: Cite };
type Unsupported = { concept: string; reason: string; would_require: string };
type Graph = {
  round_id: string; generated_at: string;
  nodes: PNode[]; edges: PEdge[]; timeline: PEvent[]; unsupported: Unsupported[];
};
type Load =
  | { status: "loading" }
  | { status: "ok"; data: Graph }
  | { status: "notfound" }
  | { status: "error"; detail: string };

function groupByType<T extends { type: string }>(items: T[]): [string, T[]][] {
  const groups: Record<string, T[]> = {};
  for (const it of items) (groups[it.type] ||= []).push(it);
  return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
}

// Defensive: a row must never crash the page if the backend ever omits a citation.
function CiteTag({ cite }: { cite?: Cite }) {
  if (!cite?.table) return <span data-testid="cite-missing" className="text-[11px] text-destructive/80">(no citation)</span>;
  return (
    <span data-testid="cite" className="rounded bg-secondary/60 px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
      {cite.table}{cite.field ? `.${cite.field}` : ""}
    </span>
  );
}

export function ProvenanceViewer({ roundId }: { roundId: string }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [view, setView] = useState<"list" | "graph">("list");

  useEffect(() => {
    let alive = true;
    setLoad({ status: "loading" });
    (async () => {
      try {
        const res = await fetch(`${GW}/rounds/${encodeURIComponent(roundId)}/provenance`, { cache: "no-store" });
        if (res.status === 404) { if (alive) setLoad({ status: "notfound" }); return; }
        if (!res.ok) { if (alive) setLoad({ status: "error", detail: `HTTP ${res.status}` }); return; }
        const data = (await res.json()) as Graph;
        if (alive) setLoad({ status: "ok", data });
      } catch (e) {
        if (alive) setLoad({ status: "error", detail: (e as Error).message || "request failed" });
      }
    })();
    return () => { alive = false; };
  }, [roundId]);

  const nodeGroups = useMemo(() => (load.status === "ok" ? groupByType(load.data.nodes) : []), [load]);
  const edgeGroups = useMemo(() => (load.status === "ok" ? groupByType(load.data.edges) : []), [load]);

  return (
    <div className="mx-auto max-w-6xl space-y-4 px-5 py-6" data-testid="provenance-viewer" data-round={roundId}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Run provenance — <span className="font-mono">{roundId}</span></h1>
          <p className="text-sm text-muted-foreground">Read-only activity/provenance map over persisted data.</p>
        </div>
        <Button asChild variant="outline" size="sm"><Link href="/" data-testid="provenance-back"><ArrowLeft />Back to operations</Link></Button>
      </div>

      {/* Honesty banner — first-class, never hidden. States exactly what this view is and is NOT. */}
      <Card data-testid="provenance-honesty" className="border-primary/30 bg-primary/[0.04] p-3 text-sm">
        <div className="flex items-start gap-2">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-primary/80" />
          <p className="text-muted-foreground">
            This page is <b>read-only</b>, <b>run-scoped</b>, and <b>derived entirely from persisted data</b> — every
            row cites its source table. It is <b>not</b> a live multi-agent animation and <b>not</b> an execution or
            control surface. Concepts without persisted backing are listed under “Not claimed yet”.
          </p>
        </div>
      </Card>

      {load.status === "loading" && (
        <div data-testid="provenance-loading" className="rounded-md border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">Loading provenance…</div>
      )}

      {load.status === "notfound" && (
        <div data-testid="provenance-notfound" className="rounded-md border border-destructive/40 bg-destructive/5 px-4 py-8 text-center text-sm text-destructive">
          No run <span className="font-mono">{roundId}</span> was found. Nothing is rendered rather than a fabricated empty graph.
        </div>
      )}

      {load.status === "error" && (
        <div data-testid="provenance-error" className="rounded-md border border-destructive/40 bg-destructive/5 px-4 py-8 text-center text-sm text-destructive">
          Could not load provenance for <span className="font-mono">{roundId}</span> ({load.detail}).
        </div>
      )}

      {load.status === "ok" && (() => {
        const g = load.data;
        const empty = g.nodes.length === 0 && g.edges.length === 0 && g.timeline.length === 0;
        return (
          <>
            {/* Summary — count-first + list/graph toggle */}
            <Card data-testid="provenance-summary" className="flex flex-wrap items-center gap-2 p-3 text-sm">
              <Badge variant="outline" data-testid="prov-generated">generated {g.generated_at?.slice(0, 19).replace("T", " ") || "—"}</Badge>
              <Badge variant="outline" data-testid="prov-count-nodes">{g.nodes.length} nodes</Badge>
              <Badge variant="outline" data-testid="prov-count-edges">{g.edges.length} edges</Badge>
              <Badge variant="outline" data-testid="prov-count-timeline">{g.timeline.length} events</Badge>
              <Badge variant="outline" data-testid="prov-count-unsupported">{g.unsupported.length} not-claimed</Badge>
              <div className="ml-auto flex items-center gap-0.5 rounded-lg border bg-card/60 p-0.5" data-testid="prov-view-toggle" role="group" aria-label="Provenance view mode">
                {([["list", ListIcon, "List"], ["graph", Network, "Graph"]] as const).map(([key, Icon, label]) => (
                  <button key={key} data-testid={`prov-view-${key}`} aria-pressed={view === key} onClick={() => setView(key)}
                    className={`inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                      view === key ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/50"}`}>
                    <Icon className="size-3.5" /> {label}
                  </button>
                ))}
              </div>
            </Card>

            {empty && (
              <div data-testid="provenance-empty" className="rounded-md border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
                This run has no persisted provenance yet.
              </div>
            )}

            {/* Graph canvas — same payload as the list, rendered as a node-edge graph */}
            {view === "graph" && !empty && (
              <Suspense fallback={<GraphLoading />}><ProvenanceGraph graph={{ round_id: g.round_id, nodes: g.nodes, edges: g.edges }} /></Suspense>
            )}

            {view === "list" && (<>
            {/* Nodes grouped by type */}
            {g.nodes.length > 0 && (
              <section data-testid="provenance-nodes" className="space-y-3">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Nodes</h2>
                {nodeGroups.map(([type, items]) => (
                  <Card key={type} data-testid={`prov-node-group-${type}`} className="p-3">
                    <div className="mb-2 flex items-center gap-2"><Badge variant="secondary">{type}</Badge><span className="text-xs text-muted-foreground">{items.length}</span></div>
                    <ul className="space-y-1.5">
                      {items.map((n) => (
                        <li key={n.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                          <span dir="auto" className="min-w-0 flex-1 truncate">{n.label}</span>
                          <span className="font-mono text-[11px] text-muted-foreground">{n.id}</span>
                          {n.source_id && <span className="font-mono text-[11px] text-muted-foreground/70">#{n.source_id}</span>}
                          <CiteTag cite={n.cite} />
                          {n.deep_link && <Link href={n.deep_link} className="text-[11px] text-primary underline">open</Link>}
                        </li>
                      ))}
                    </ul>
                  </Card>
                ))}
              </section>
            )}

            {/* Edges grouped by type */}
            {g.edges.length > 0 && (
              <section data-testid="provenance-edges" className="space-y-3">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Edges</h2>
                {edgeGroups.map(([type, items]) => (
                  <Card key={type} data-testid={`prov-edge-group-${type}`} className="p-3">
                    <div className="mb-2 flex items-center gap-2"><Badge variant="secondary">{type}</Badge><span className="text-xs text-muted-foreground">{items.length}</span></div>
                    <ul className="space-y-1.5">
                      {items.map((e) => (
                        <li key={e.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                          <span className="font-mono text-[11px]">{e.source}</span>
                          <span className="text-muted-foreground">→</span>
                          <span className="font-mono text-[11px]">{e.target}</span>
                          {e.source_id && <span className="font-mono text-[11px] text-muted-foreground/70">#{e.source_id}</span>}
                          <CiteTag cite={e.cite} />
                        </li>
                      ))}
                    </ul>
                  </Card>
                ))}
              </section>
            )}

            {/* Timeline */}
            {g.timeline.length > 0 && (
              <section data-testid="provenance-timeline" className="space-y-2">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Timeline</h2>
                <Card className="p-3">
                  <ul className="space-y-1.5">
                    {g.timeline.map((ev) => (
                      <li key={ev.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                        <span className="font-mono text-[11px] text-muted-foreground">{ev.at ? ev.at.slice(0, 19).replace("T", " ") : "—"}</span>
                        <Badge variant="outline">{ev.action}</Badge>
                        <span className="text-xs text-muted-foreground">{ev.entity}:{ev.entity_id}</span>
                        {ev.actor && <span className="text-xs">by {ev.actor}{ev.actor_kind ? ` (${ev.actor_kind})` : ""}</span>}
                        <CiteTag cite={ev.cite} />
                      </li>
                    ))}
                  </ul>
                </Card>
              </section>
            )}
            </>)}

            {/* Unsupported — first-class honesty legend */}
            <section data-testid="provenance-unsupported" className="space-y-2">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Not claimed yet (no persisted backing)</h2>
              <Card className="border-warning/40 bg-warning/[0.05] p-3">
                <ul className="space-y-2">
                  {g.unsupported.map((u) => (
                    <li key={u.concept} data-testid={`prov-unsupported-${u.concept}`} className="text-sm">
                      <Badge variant="outline" className="border-warning/50 text-warning">{u.concept}</Badge>
                      <span className="ml-2 text-muted-foreground">{u.reason}</span>
                      <span className="ml-2 text-[11px] text-muted-foreground/70">would require: {u.would_require}</span>
                    </li>
                  ))}
                </ul>
              </Card>
            </section>
          </>
        );
      })()}
    </div>
  );
}
