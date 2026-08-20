// #410 — the one typed demonstration fixture for Process Studio.
//
// FIXTURE OWNERSHIP: Process Studio demonstration only. This is NOT execution truth, NOT activation
// evidence, and NOT a seed. It is never loaded from active runtime configuration. React Flow
// serialization is never the backend execution contract; these node/edge ids are UI-only and are
// deliberately distinct from any canonical stage identifier or executable capability identifier.

// The exact disclosure copy the /studio surface must render verbatim (asserted by tests).
export const FIXTURE_DISCLOSURE =
  "Illustrative social workflow template — not loaded from active runtime configuration.";

export interface StudioNodeData {
  label: string;
  // A human description shown in the selected-node details panel. UI copy only.
  summary: string;
  // The canonical stage identifier this UI node ILLUSTRATES — shown to make the id separation explicit
  // (UI node id ≠ canonical stage id ≠ executable capability id). Not an execution binding.
  illustratesStage: string;
}

export interface StudioNode {
  id: string;
  position: { x: number; y: number };
  data: StudioNodeData;
}

export interface StudioEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
}

export interface IllustrativeWorkflow {
  templateName: string;
  familyLabel: string;
  versionNo: number;
  status: string; // an illustrative version/status label, e.g. "Draft (demonstration)"
  disclosure: string;
  nodes: StudioNode[];
  edges: StudioEdge[];
}

export const illustrativeSocialWorkflow: IllustrativeWorkflow = {
  templateName: "Illustrative social workflow",
  familyLabel: "Social content (demonstration family)",
  versionNo: 1,
  status: "Draft (demonstration)",
  disclosure: FIXTURE_DISCLOSURE,
  nodes: [
    {
      id: "ui-node-intake",
      position: { x: 0, y: 40 },
      data: {
        label: "Topic intake",
        summary: "Collect the campaign brief and candidate topics for the cycle.",
        illustratesStage: "intake",
      },
    },
    {
      id: "ui-node-plan",
      position: { x: 240, y: 40 },
      data: {
        label: "Plan & schedule",
        summary: "Allocate topics to slots across platforms and dates.",
        illustratesStage: "planning",
      },
    },
    {
      id: "ui-node-generate",
      position: { x: 480, y: 40 },
      data: {
        label: "Generate drafts",
        summary: "Produce candidate content for each allocated slot.",
        illustratesStage: "generation",
      },
    },
    {
      id: "ui-node-review",
      position: { x: 720, y: 40 },
      data: {
        label: "Review & approve",
        summary: "Human review gate before anything is eligible to publish.",
        illustratesStage: "review",
      },
    },
    {
      id: "ui-node-publish",
      position: { x: 960, y: 40 },
      data: {
        label: "Publish",
        summary: "Deliver approved content to the target platforms.",
        illustratesStage: "delivery",
      },
    },
  ],
  edges: [
    { id: "ui-edge-1", source: "ui-node-intake", target: "ui-node-plan", label: "topics" },
    { id: "ui-edge-2", source: "ui-node-plan", target: "ui-node-generate", label: "schedule" },
    { id: "ui-edge-3", source: "ui-node-generate", target: "ui-node-review", label: "drafts" },
    { id: "ui-edge-4", source: "ui-node-review", target: "ui-node-publish", label: "approved" },
  ],
};
