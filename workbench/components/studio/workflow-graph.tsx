"use client";

// #410 — the read-only Process Studio graph. Renders ONE typed demonstration fixture as a React Flow
// canvas. It is strictly read-only: nodes cannot be dragged, connected, added, or deleted; there is no
// palette, no edge editing, no delete key. Selecting a node reports upward so the parent can show
// details — that is inspection, never mutation. This component is the lazy-loaded chunk (React.lazy +
// Suspense on the parent) per the repo's Next 15 trap (#152 — never next/dynamic).

import { useMemo } from "react";
import {
  ReactFlow, Background, Controls, Handle, Position, MarkerType,
  type NodeProps, type Node as RFNode, type Edge as RFEdge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { illustrativeSocialWorkflow, type StudioNodeData } from "./illustrative-social-workflow";

function StudioFlowNode({ data }: NodeProps) {
  const d = data as unknown as StudioNodeData;
  return (
    <div
      data-testid={`studio-node-${d.illustratesStage}`}
      className="min-w-[140px] max-w-[200px] rounded-md border border-(--color-border) bg-(--color-card) px-2.5 py-1.5 text-xs shadow-(--shadow-sm)"
    >
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="text-[9px] font-semibold uppercase tracking-[0.16em] text-(--color-muted)">
        {d.illustratesStage}
      </div>
      <div dir="auto" className="truncate font-medium text-(--color-fg)">{d.label}</div>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
}

const nodeTypes = { studio: StudioFlowNode };

export function WorkflowGraph({
  onSelectNode,
}: {
  onSelectNode: (id: string | null) => void;
}) {
  const rfNodes: RFNode[] = useMemo(
    () =>
      illustrativeSocialWorkflow.nodes.map((n) => ({
        id: n.id,
        type: "studio",
        position: n.position,
        data: n.data as unknown as Record<string, unknown>,
        draggable: false,
        connectable: false,
      })),
    [],
  );

  const rfEdges: RFEdge[] = useMemo(
    () =>
      illustrativeSocialWorkflow.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      })),
    [],
  );

  return (
    <div className="h-[460px] rounded-xl border border-(--color-border) bg-(--color-bg)" data-testid="studio-graph-canvas">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelectNode(node.id)}
        onPaneClick={() => onSelectNode(null)}
        fitView
        proOptions={{ hideAttribution: true }}
        // Read-only: every mutation affordance is disabled. No palette, no edge editing, no deletion.
        nodesDraggable={false}
        nodesConnectable={false}
        edgesReconnectable={false}
        elementsSelectable
        deleteKeyCode={null}
        selectionKeyCode={null}
        multiSelectionKeyCode={null}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

export default WorkflowGraph;
