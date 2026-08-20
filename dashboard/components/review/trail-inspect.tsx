"use client";
import { useState } from "react";
import { useReview, type SlotInspect } from "@/lib/review-context";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronUp, Lock } from "lucide-react";
import { isMeaningfulRationale } from "@/lib/rationale";
import {
  deliveryChecks, directionSectionTitle, lensBadgeLabel, structureEntries, structureSectionTitle,
} from "./review-item";

// #237 Slice A — read-only inspection of ONE completed-trail item. Approval changes mutation
// authority, not information: this panel shows the SAME content definition the active review card
// shows (pinned/approved revision, provenance, lineage), fetched lazily on expansion from the
// status-independent /slots/{id}/inspect projection. STRICTLY non-mutating by design: it renders
// no edit, decide, regenerate, reopen, or restore affordance for any principal — the governed
// change path is a later, separately authorized slice. Absent fields say so truthfully; nothing
// is inferred or fabricated.

function AbsenceLine({ slotId, field, children }: { slotId: string; field: string; children: React.ReactNode }) {
  return (
    <div data-testid={`trail-inspect-absent-${field}-${slotId}`} className="text-[11px] italic text-muted-foreground">
      {children}
    </div>
  );
}

function revisionLabel(a: { revision: number; approved: boolean; head_revision: number | null }) {
  const head = a.head_revision != null && a.head_revision !== a.revision ? ` of ${a.head_revision}` : "";
  return a.approved ? `v${a.revision}${head} · approved` : `v${a.revision}${head} · latest (no approved pin)`;
}

export function TrailInspect({ slotId }: { slotId: string }) {
  const r = useReview();
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<SlotInspect | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true); setError(null);
    try { setDetail(await r.inspectSlot(slotId)); }
    catch (e) { setError((e as Error).message || "Could not load the item detail"); }
    finally { setLoading(false); }
  };
  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && !detail && !loading) void load();
  };

  const fw = detail?.format ? r.frameworks?.[detail.format] : undefined;
  const beats = detail?.script ? structureEntries(detail.script.structure, fw) : [];
  const checks = detail?.script ? deliveryChecks(detail.script.delivery_check) : [];
  // Both topic bodies are independently persisted truth: topic.text_ar is the approved/pinned
  // revision's body; slot.topic_angle is the slot's LIVE working body (updated by edits/restores).
  // When they differ, BOTH must stay visible with truthful labels — parity never drops a persisted
  // pre-approval field, and the approved version is never silently replaced by the live one.
  const approvedBody = detail?.topic?.text_ar?.trim() || null;
  const slotBody = detail?.topic_angle?.trim() || null;
  const bodiesDiffer = Boolean(approvedBody && slotBody && approvedBody !== slotBody);
  const rationale = detail?.topic
    ? (isMeaningfulRationale(detail.topic.rationale_en) ? detail.topic.rationale_en
       : isMeaningfulRationale(detail.topic.rationale_ar) ? detail.topic.rationale_ar : null)
    : null;

  return (
    <div className="flex w-full flex-col gap-1">
      <button
        data-testid={`trail-inspect-toggle-${slotId}`}
        aria-expanded={open}
        onClick={toggle}
        className="inline-flex w-fit items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
      >
        {open ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
        Inspect
      </button>
      {open && (
        <div data-testid={`trail-inspect-${slotId}`} className="flex w-full flex-col gap-2 rounded-xl border border-border/60 bg-background/80 p-2.5 text-xs">
          <div data-testid={`trail-inspect-readonly-${slotId}`} className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            <Lock className="size-3" />
            <span>Approved content — read-only. Changes go through the governed rework path, not this view.</span>
          </div>

          {loading && <div data-testid={`trail-inspect-loading-${slotId}`} className="text-muted-foreground">Loading item detail…</div>}
          {error && (
            <div data-testid={`trail-inspect-error-${slotId}`} className="flex flex-wrap items-center gap-2 text-destructive">
              <span>{error}</span>
              <button data-testid={`trail-inspect-retry-${slotId}`} className="rounded-md border px-1.5 py-0.5 text-[11px]" onClick={() => void load()}>Retry</button>
            </div>
          )}

          {detail && (
            <>
              {/* the same definitional context the active card leads with */}
              <div data-testid={`trail-inspect-meta-${slotId}`} className="flex flex-wrap items-center gap-1.5">
                {detail.pillar_name_en && <Badge variant="secondary">{detail.pillar_name_en}</Badge>}
                {detail.hcs_name_en && <Badge variant="secondary">{detail.hcs_name_en}</Badge>}
                {detail.lens && <Badge variant="outline">{lensBadgeLabel(detail.lens, detail.lens_name_en, true)}</Badge>}
                {detail.format && <Badge variant="outline">{detail.format}</Badge>}
                {detail.hook_type && <Badge variant="outline">{detail.hook_type}</Badge>}
                <span className="text-muted-foreground">Day {detail.day} · {detail.time_uae}</span>
              </div>
              {(detail.pillar_name_ar || detail.hcs_name_ar) && (
                <div dir="auto" className="text-[11px] text-muted-foreground">
                  {[detail.pillar_name_ar, detail.hcs_name_ar].filter(Boolean).join(" · ")}
                </div>
              )}

              {/* topic definition */}
              <div data-testid={`trail-inspect-topic-${slotId}`} className="flex flex-col gap-1 border-t border-border/50 pt-1.5">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Topic</div>
                {detail.hook_text && <div dir="auto" className="text-foreground">«{detail.hook_text}»</div>}
                {approvedBody
                  ? <div dir="auto" data-testid={`trail-inspect-topic-body-${slotId}`} className="whitespace-pre-wrap text-foreground">{approvedBody}</div>
                  : slotBody
                    ? <div dir="auto" data-testid={`trail-inspect-topic-body-${slotId}`} className="whitespace-pre-wrap text-foreground">{slotBody}</div>
                    : <AbsenceLine slotId={slotId} field="topic">No topic text recorded for this item.</AbsenceLine>}
                {bodiesDiffer && (
                  <div data-testid={`trail-inspect-slot-body-${slotId}`} className="flex flex-col">
                    <span className="text-[11px] text-muted-foreground">Current working body (slot) — differs from the approved revision shown above</span>
                    <div dir="auto" className="whitespace-pre-wrap text-foreground">{slotBody}</div>
                  </div>
                )}
                {rationale
                  ? <div dir="auto" data-testid={`trail-inspect-rationale-${slotId}`} className="text-muted-foreground">{rationale}</div>
                  : <AbsenceLine slotId={slotId} field="rationale">No rationale recorded.</AbsenceLine>}
                {detail.topic && (
                  <div className="text-[11px] text-muted-foreground">
                    {revisionLabel(detail.topic)}
                    {detail.topic.approved && detail.topic.approved_by && (
                      <> · approved by <span className="font-medium text-foreground/80">{detail.topic.approved_by}</span>
                        {detail.topic.approved_at && <> · {new Date(detail.topic.approved_at).toLocaleString()}</>}</>
                    )}
                  </div>
                )}
              </div>

              {/* approved script definition */}
              <div data-testid={`trail-inspect-script-${slotId}`} className="flex flex-col gap-1 border-t border-border/50 pt-1.5">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  {detail.format ? structureSectionTitle(detail.format) : "Script"}
                </div>
                {detail.script ? (
                  <>
                    {beats.length > 0 ? beats.map((b) => (
                      <div key={b.key} className="flex flex-col">
                        <span className="text-[11px] text-muted-foreground">{b.label}</span>
                        <span dir="auto" className="whitespace-pre-wrap text-foreground">{b.value}</span>
                      </div>
                    )) : detail.script.script_ar
                      ? <div dir="auto" className="whitespace-pre-wrap text-foreground">{detail.script.script_ar}</div>
                      : <AbsenceLine slotId={slotId} field="script-body">No script body recorded.</AbsenceLine>}
                    {detail.script.final_line && (
                      <div dir="auto" className="text-foreground"><span className="text-[11px] text-muted-foreground">Final line · </span>{detail.script.final_line}</div>
                    )}
                    {detail.script.delivery_notes && (
                      <div className="flex flex-col">
                        <span className="text-[11px] text-muted-foreground">{detail.format ? directionSectionTitle(detail.format) : "Direction"}</span>
                        <span dir="auto" className="whitespace-pre-wrap text-muted-foreground">{detail.script.delivery_notes}</span>
                      </div>
                    )}
                    {checks.length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {checks.map((c) => <Badge key={c.key} variant={c.ok ? "success" : "secondary"}>{c.label}</Badge>)}
                      </div>
                    )}
                    {(detail.script.flags || []).length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {(detail.script.flags || []).map((f) => <Badge key={f} variant="outline">{f}</Badge>)}
                      </div>
                    )}
                    <div data-testid={`trail-inspect-attribution-${slotId}`} className="text-[11px] text-muted-foreground">
                      {revisionLabel(detail.script)}
                      {detail.script.approved && detail.script.approved_by && (
                        <> · approved by <span className="font-medium text-foreground/80">{detail.script.approved_by}</span>
                          {detail.script.approved_at && <> · {new Date(detail.script.approved_at).toLocaleString()}</>}</>
                      )}
                      {detail.script.model
                        ? <> · generated by <span className="font-mono">{detail.script.model}</span></>
                        : <> · generation model not recorded</>}
                    </div>
                  </>
                ) : (
                  <AbsenceLine slotId={slotId} field="script">No script exists for this item yet.</AbsenceLine>
                )}
              </div>

              {/* decision provenance — who moved it, when, with what notes */}
              <div data-testid={`trail-inspect-decisions-${slotId}`} className="flex flex-col gap-0.5 border-t border-border/50 pt-1.5">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Decisions</div>
                {detail.decisions.length > 0 ? detail.decisions.map((d, i) => (
                  <div key={i} className="text-[11px] text-muted-foreground">
                    <span className="font-medium text-foreground/80">{d.approver_id}</span> · {d.decision} · {d.stage}
                    {" · "}{new Date(d.decided_at).toLocaleString()}
                    {d.notes && <span dir="auto"> — {d.notes}</span>}
                  </div>
                )) : <AbsenceLine slotId={slotId} field="decisions">No gate decisions recorded.</AbsenceLine>}
              </div>

              {/* downstream lineage as it exists TODAY — absent parts named, never implied */}
              <div data-testid={`trail-inspect-lineage-${slotId}`} className="flex flex-col gap-0.5 border-t border-border/50 pt-1.5">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Downstream lineage</div>
                {/* #255 S1 — the pinned APPROVED master edit vs the CURRENT master, always
                    distinct: a newer master version shows as drift; the approved pin never moves.
                    Read-only truth from the exact master predicate; no mutation affordance. */}
                {detail.approved_edit && (
                  <div data-testid={`trail-inspect-approved-edit-${slotId}`} className="text-[11px] text-muted-foreground">
                    Approved master edit: <span className="font-medium text-foreground/80">v{detail.approved_edit.pinned_revision}</span>
                    {detail.approved_edit.approved_by && <> · approved by <span className="font-medium text-foreground/80">{detail.approved_edit.approved_by}</span></>}
                    {detail.approved_edit.drifted ? (
                      <span data-testid={`trail-inspect-edit-drift-${slotId}`}>
                        {" "}· current master is v{detail.approved_edit.current_master_revision} — newer than the approved pin (approved display does not move)
                      </span>
                    ) : detail.approved_edit.current_master_revision != null ? (
                      <> · this is the current master</>
                    ) : null}
                    {detail.approved_edit.current_master_ambiguous && (
                      <span data-testid={`trail-inspect-edit-ambiguous-${slotId}`}> · current master state ambiguous (multiple active) — needs reconciliation</span>
                    )}
                    {detail.approved_edit.pin_evidence !== "audit" && (
                      <span data-testid={`trail-inspect-pin-unverified-${slotId}`}>
                        {" "}· exact pinned asset identity {detail.approved_edit.pin_evidence === "inconsistent"
                          ? "is INCONSISTENT with asset truth — needs reconciliation"
                          : "is not audit-verified (no matching immutable pin event)"}
                      </span>
                    )}
                  </div>
                )}
                {detail.assets.length > 0 ? detail.assets.map((a) => (
                  <div key={a.asset_id} className="text-[11px] text-muted-foreground">
                    {a.stage} · {a.kind} v{a.version}{a.platform_variant ? ` · ${a.platform_variant}` : ""}
                    {a.uri && <span className="font-mono"> · {a.uri}</span>}
                  </div>
                )) : <AbsenceLine slotId={slotId} field="assets">No production assets recorded yet.</AbsenceLine>}
                {detail.publications.length > 0 ? detail.publications.map((p) => (
                  <div key={p.publication_intent_id} className="text-[11px] text-muted-foreground">
                    Published · {p.platform_key} · {p.current_state}
                    {p.url && <span className="font-mono"> · {p.url}</span>}
                  </div>
                )) : <AbsenceLine slotId={slotId} field="publications">No publication recorded yet.</AbsenceLine>}
                <AbsenceLine slotId={slotId} field="sdam">SDAM/edit lineage is not surfaced here yet.</AbsenceLine>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
