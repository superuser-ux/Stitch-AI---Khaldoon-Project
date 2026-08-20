"use client";

import { useMemo, useState } from "react";
import {
  ReactFlow, Background, Controls, Handle, Position, MarkerType,
  BaseEdge, EdgeLabelRenderer, getBezierPath,
  type NodeProps, type EdgeProps, type Node as RFNode, type Edge as RFEdge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

// M7 provenance GRAPH CANVAS (#71 / directive #81) — renders the SAME GET /rounds/{id}/provenance
// payload (PR #73) as a node-edge graph, sharing the #75 viewer's honesty pattern: every node/edge
// exposes its data-source citation + source_id, nothing unbacked is drawn, deep_link stays reserved
// when null. Read-only: no write/act-through-map controls. Deterministic layered layout for testability.

type Cite = { table: string; field: string };
export type PNode = { id: string; type: string; label: string; cite?: Cite; source_id?: string; deep_link?: string | null; meta?: Record<string, unknown> };
export type PEdge = { id: string; type: string; source: string; target: string; cite?: Cite; source_id?: string; meta?: Record<string, unknown> };
export type ProvGraph = { round_id: string; nodes: PNode[]; edges: PEdge[] };

// One column per node type → deterministic x; stacked by index → deterministic y. Stable for tests.
const NODE_COL: Record<string, number> = { round: 0, stage: 1, slot: 2, topic: 3, script: 4, asset: 5, actor: 6 };
const NODE_TYPES = ["round", "stage", "slot", "topic", "script", "asset", "actor"];
const EDGE_TYPES = ["scopes", "transition", "handoff", "produced", "revised-from", "approved-by", "request-change", "reviewed-by"];
const NODE_TONE: Record<string, string> = {
  round: "border-primary/60 bg-primary/10 text-primary",
  stage: "border-blue-500/60 bg-blue-500/10 text-blue-600 dark:text-blue-300",
  slot: "border-foreground/40 bg-card text-foreground",
  topic: "border-green-500/60 bg-green-500/10 text-green-700 dark:text-green-300",
  script: "border-purple-500/60 bg-purple-500/10 text-purple-700 dark:text-purple-300",
  asset: "border-cyan-500/60 bg-cyan-500/10 text-cyan-700 dark:text-cyan-300",
  actor: "border-amber-500/60 bg-amber-500/10 text-amber-700 dark:text-amber-300",
};
const swatch: Record<string, string> = {
  round: "bg-primary", stage: "bg-blue-500", slot: "bg-foreground/50", topic: "bg-green-500",
  script: "bg-purple-500", asset: "bg-cyan-500", actor: "bg-amber-500",
};

function ProvNode({ data }: NodeProps) {
  const n = data.pnode as PNode;
  return (
    <div data-testid={`gnode-${n.id}`} data-node-type={n.type}
      className={`min-w-[130px] max-w-[190px] rounded-md border px-2 py-1.5 text-xs shadow-sm ${NODE_TONE[n.type] || NODE_TONE.slot}`}>
      <Handle type="target" position={Position.Left} className="!bg-muted-foreground/50" />
      <div className="text-[9px] font-semibold uppercase tracking-[0.16em] opacity-70">{n.type}</div>
      <div dir="auto" className="truncate font-medium text-foreground">{n.label}</div>
      <Handle type="source" position={Position.Right} className="!bg-muted-foreground/50" />
    </div>
  );
}

function ProvEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd }: EdgeProps) {
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const e = data!.pedge as PEdge;
  const onSelect = data!.onSelect as (e: PEdge) => void;
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={{ stroke: "var(--xy-edge-stroke, #99a1af)", strokeWidth: 1.5 }} />
      <EdgeLabelRenderer>
        <button
          data-testid={`gedge-${e.id}`}
          data-edge-type={e.type}
          onClick={() => onSelect(e)}
          style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          className="pointer-events-auto absolute rounded-full border border-border bg-background/95 px-1.5 py-0.5 text-[9px] text-muted-foreground shadow-sm hover:text-foreground"
        >
          {e.type}
        </button>
      </EdgeLabelRenderer>
    </>
  );
}

const nodeTypes = { prov: ProvNode };
const edgeTypes = { prov: ProvEdge };

function layout(nodes: PNode[]): Record<string, { x: number; y: number }> {
  const rowByCol: Record<number, number> = {};
  const pos: Record<string, { x: number; y: number }> = {};
  // deterministic order: by column, then by original index
  for (const n of nodes) {
    const col = NODE_COL[n.type] ?? 7;
    const row = (rowByCol[col] = (rowByCol[col] ?? 0) + 1) - 1;
    pos[n.id] = { x: col * 230, y: row * 82 };
  }
  return pos;
}

type Sel = { kind: "node"; node: PNode } | { kind: "edge"; edge: PEdge } | null;

function CiteLine({ cite }: { cite?: Cite }) {
  if (!cite?.table) return <span data-testid="cite-missing" className="text-destructive/80">(no citation)</span>;
  return <span data-testid="cite" className="font-mono text-muted-foreground">{cite.table}{cite.field ? `.${cite.field}` : ""}</span>;
}

export function ProvenanceGraph({ graph }: { graph: ProvGraph }) {
  const [sel, setSel] = useState<Sel>(null);

  const rfNodes: RFNode[] = useMemo(() => {
    const pos = layout(graph.nodes);
    return graph.nodes.map((n) => ({ id: n.id, type: "prov", position: pos[n.id] || { x: 0, y: 0 }, data: { pnode: n } }));
  }, [graph.nodes]);

  const rfEdges: RFEdge[] = useMemo(() => graph.edges.map((e) => ({
    id: e.id, source: e.source, target: e.target, type: "prov",
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
    data: { pedge: e, onSelect: (pe: PEdge) => setSel({ kind: "edge", edge: pe }) },
  })), [graph.edges]);

  const presentNodeTypes = NODE_TYPES.filter((t) => graph.nodes.some((n) => n.type === t));
  const presentEdgeTypes = EDGE_TYPES.filter((t) => graph.edges.some((e) => e.type === t));

  return (
    <div data-testid="provenance-graph" className="grid gap-3 md:grid-cols-[minmax(0,1fr)_260px]">
      <div className="h-[600px] rounded-xl border bg-card/30" data-testid="prov-graph-canvas">
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodeClick={(_, node) => setSel({ kind: "node", node: node.data.pnode as PNode })}
          onPaneClick={() => setSel(null)}
          fitView
          proOptions={{ hideAttribution: true }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>

      <div className="space-y-3">
        {/* Legend — node + edge types present in this run */}
        <div data-testid="prov-graph-legend" className="rounded-xl border bg-card/40 p-3 text-xs">
          <div className="mb-1 font-semibold uppercase tracking-wide text-muted-foreground">Node types</div>
          <ul className="mb-2 space-y-1">
            {presentNodeTypes.map((t) => (
              <li key={t} className="flex items-center gap-2"><span className={`size-2.5 rounded-full ${swatch[t]}`} />{t}</li>
            ))}
          </ul>
          <div className="mb-1 font-semibold uppercase tracking-wide text-muted-foreground">Edge types</div>
          <ul className="flex flex-wrap gap-1">
            {presentEdgeTypes.map((t) => (
              <li key={t} className="rounded-full border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">{t}</li>
            ))}
          </ul>
        </div>

        {/* Detail panel — selected node/edge, with its data-source citation (honesty inherited) */}
        <div data-testid="prov-graph-detail" className="rounded-xl border bg-card/40 p-3 text-xs">
          <div className="mb-1 font-semibold uppercase tracking-wide text-muted-foreground">Details</div>
          {!sel && <div className="text-muted-foreground">Select a node or edge to inspect its backing record.</div>}
          {sel?.kind === "node" && (
            <dl className="space-y-1" data-testid="prov-detail-node">
              <div><dt className="inline text-muted-foreground">type: </dt><dd className="inline">{sel.node.type}</dd></div>
              <div><dt className="inline text-muted-foreground">label: </dt><dd dir="auto" className="inline">{sel.node.label}</dd></div>
              <div><dt className="inline text-muted-foreground">id: </dt><dd className="inline font-mono">{sel.node.id}</dd></div>
              <div><dt className="inline text-muted-foreground">source_id: </dt><dd data-testid="prov-detail-source" className="inline font-mono">{sel.node.source_id || "—"}</dd></div>
              <div><dt className="inline text-muted-foreground">cite: </dt><CiteLine cite={sel.node.cite} /></div>
              <div><dt className="inline text-muted-foreground">deep link: </dt><dd className="inline">{sel.node.deep_link ? <a className="text-primary underline" href={sel.node.deep_link}>open</a> : "reserved (none yet)"}</dd></div>
            </dl>
          )}
          {sel?.kind === "edge" && (
            <dl className="space-y-1" data-testid="prov-detail-edge">
              <div><dt className="inline text-muted-foreground">type: </dt><dd className="inline">{sel.edge.type}</dd></div>
              <div><dt className="inline text-muted-foreground">id: </dt><dd className="inline font-mono">{sel.edge.id}</dd></div>
              <div><dt className="inline text-muted-foreground">source: </dt><dd className="inline font-mono">{sel.edge.source}</dd></div>
              <div><dt className="inline text-muted-foreground">target: </dt><dd className="inline font-mono">{sel.edge.target}</dd></div>
              <div><dt className="inline text-muted-foreground">source_id: </dt><dd data-testid="prov-detail-source" className="inline font-mono">{sel.edge.source_id || "—"}</dd></div>
              <div><dt className="inline text-muted-foreground">cite: </dt><CiteLine cite={sel.edge.cite} /></div>
            </dl>
          )}
        </div>
      </div>
    </div>
  );
}
