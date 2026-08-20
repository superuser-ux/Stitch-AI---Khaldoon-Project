import { ProvenanceViewer } from "@/components/provenance/provenance-viewer";

// #74 (M7 / #71) — run-scoped, read-only provenance viewer shell at /runs/:roundId/provenance.
export default async function ProvenancePage({ params }: { params: Promise<{ roundId: string }> }) {
  const { roundId } = await params;
  return <ProvenanceViewer roundId={roundId} />;
}
