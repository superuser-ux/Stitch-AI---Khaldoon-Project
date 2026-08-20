"use client";

import { useEffect, useState } from "react";
import { Check, X, Pencil, ChevronDown, ChevronRight, ChevronUp, FileText, Undo2, Minimize2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { approvalAssignmentLabel, contentIdLabel, useReview, type ContentIdMode, type Framework, type Target } from "@/lib/review-context";
import { SdamReadiness } from "./sdam-readiness";
import { TrailInspect } from "./trail-inspect";
import { isMeaningfulRationale } from "@/lib/rationale";
import { getScriptOpeningBeat } from "@/lib/script";

// A FLUID, RTL-native review card. The Arabic hook is the hero (right column, large Arabic display type); the
// left column carries meta (pillar/status/version) + the English rationale; the decide bar spans
// full width beneath. Three densities — chip (scan) → compact (default) → full (co-creation
// detail). Actions + version history + script stay live in compact; every data-testid is preserved.
export type Density = "chip" | "compact" | "full";

function primaryCodeLabel(stageKey: string) {
  if (stageKey === "schedule") return "Schedule Code";
  if (stageKey === "topic") return "Topic Code";
  if (stageKey === "script") return "Script Code";
  if (stageKey === "final") return "Approval Code";
  if (stageKey === "production") return "Production Code";
  if (stageKey === "edit") return "Edit Code";
  if (stageKey === "distribution") return "Distribution Code";
  return "Content Code";
}

function slotWindowLabel(time: string) {
  const hour = Number.parseInt((time || "00:00").split(":")[0] || "0", 10);
  if (hour < 12) return "Morning";
  if (hour < 17) return "Midday";
  return "Evening";
}

function slotPostLabel(slotId: string) {
  const suffix = slotId.split("-").pop() || "";
  if (suffix === "AM") return "Post 1";
  if (suffix === "PM") return "Post 2";
  const match = suffix.match(/^S(\d+)$/);
  if (match) return `Post ${match[1]}`;
  return "Planned post";
}

export function lensBadgeLabel(lensId: string, lensName?: string | null, full = false) {
  const match = lensId.match(/^L(\d+)$/i);
  const lensNumber = match?.[1];
  if (full && lensNumber && lensName) return `Lens ${lensNumber} · ${lensName}`;
  if (full && lensName) return `${lensId} · ${lensName}`;
  return lensId;
}

function formatFamily(format: string) {
  const value = format.toLowerCase();
  if (value.includes("carousel")) return "carousel";
  if (value.includes("pic") || value.includes("post")) return "static";
  if (value.includes("reel") || value.includes("video")) return "video";
  return "generic";
}

export function structureSectionTitle(format: string) {
  const family = formatFamily(format);
  if (family === "carousel") return "Panel flow";
  if (family === "static") return "Post flow";
  if (family === "video") return "Beat flow";
  return "Narrative flow";
}

// #157 (#151 S2, per the #156 truth contract) — the SYSTEM/STAGE-LEVEL generation target for the
// script path, hardcoded from the canonical repo contract (`system_config.example.yaml`
// `default_language: "ar-PS"`; `agents/run_writers.py` spoken-Palestinian prompts + dialect guard;
// `agents/README.md`; `docs/01_Blueprint_v2.md`). This is the INTENDED target of generation — the
// repo persists no per-revision dialect verification, so the UI must never present it as one.
const SCRIPT_DIALECT_TARGET = "Arabic (Palestinian dialect / ar-PS)";
const SCRIPT_DIALECT_TARGET_TITLE =
  "Stage-level generation target — what the system is configured to produce. Not a per-revision dialect verification.";
const NATIVE_REVIEW_TITLE =
  "Review-state signal — this revision was marked for native-speaker review. Separate from the generation target, and not proof the target was met or missed.";

export function directionSectionTitle(format: string) {
  const family = formatFamily(format);
  if (family === "carousel") return "Layout direction";
  if (family === "static") return "Publishing direction";
  if (family === "video") return "Performance direction";
  return "Production direction";
}

// #149 (#146 S2) — label a script structure key from the format's REGISTRY structure first
// (production_rules.structure step→label, carried on the Framework), then the canonical 4-beat
// dict, then a generic title-case. No per-format hardcoding: registry-present formats (e.g.
// Carousel's slide_1…slide_7) get their real labels; formats without registry structure
// (Hero Reel) degrade cleanly to the 4-beat dict.
function structureStepLabel(key: string, fw?: Framework) {
  const registryLabel = fw?.structureLabels?.[key];
  if (registryLabel) return registryLabel;
  const normalized = key.toLowerCase();
  if (normalized === "hook") return "Opening hook";
  if (normalized === "body") return "Build";
  if (normalized === "turn") return "Turn";
  if (normalized === "close") return "Close";
  return key.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function structureEntries(structure: Target["script_structure"], fw?: Framework) {
  if (!structure || typeof structure !== "object" || Array.isArray(structure)) return [];
  // order by the registry structure when present, else the canonical 4-beat.
  const order = fw?.structureOrder?.length ? fw.structureOrder : ["hook", "body", "turn", "close"];
  return Object.entries(structure)
    .filter(([, value]) => typeof value === "string" && value.trim().length > 0)
    .sort(([left], [right]) => {
      const leftIndex = order.indexOf(left.toLowerCase());
      const rightIndex = order.indexOf(right.toLowerCase());
      if (leftIndex === -1 && rightIndex === -1) return left.localeCompare(right);
      if (leftIndex === -1) return 1;
      if (rightIndex === -1) return -1;
      return leftIndex - rightIndex;
    })
    .map(([key, value], index) => ({ key, label: structureStepLabel(key, fw), value, index }));
}

export function deliveryChecks(checks: Target["delivery_check"]) {
  if (!checks || typeof checks !== "object" || Array.isArray(checks)) return [];
  return Object.entries(checks).map(([key, value]) => ({
    key,
    label: key.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase()),
    ok: Boolean(value),
  }));
}

export function ReviewItem({
  t,
  density = "compact",
  idMode = "expanded",
  layout = "list",
  highlight = false,
}: {
  t: Target;
  density?: Density;
  idMode?: ContentIdMode;
  layout?: "list" | "grid" | "calendar";
  highlight?: boolean;   // #49 — the content-ID lookup matched this card (ring + scroll target)
}) {
  const r = useReview();
  const { g, busy, isTopic, dam, gate, stageKey } = r;
  // #175 — a non-assigned persona sees the cards view-only: decision controls stay visible but
  // disabled (the review surface's not-assigned banner carries the why). Server still enforces.
  const actionBusy = busy || r.reviewerSyncing || !r.canDecideGate;
  const isSchedule = stageKey === "schedule";
  const isScript = stageKey === "script";
  const isGrid = layout === "grid";
  const myDecision = t.decisions.filter((d) => d.approver_id === r.approver).slice(-1)[0];
  const canAct = t.current_outcome === "pending";
  const decided = Boolean(myDecision);
  const lastDecision = myDecision || t.decisions[t.decisions.length - 1];
  const writerFlags = (t.flags || []).filter((f) => f !== "needs_scholar_review" && f !== "needs_native_review");
  const rev = (isTopic ? t.topic_revision : t.script_revision) || t.topic_revision || 1;
  const hasRisk = writerFlags.length > 0 || (t.review_blockers?.length ?? 0) > 0;
  const placement = `Day ${t.day} • ${slotPostLabel(t.slot_id)}`;
  const cadence = `${slotWindowLabel(t.time_uae)} • ${t.time_uae}`;
  const contentId = contentIdLabel(t, idMode);
  const contentDescriptor = `${t.pillar_name_en} · ${t.hcs_name_en}`;
  const codeLabel = primaryCodeLabel(stageKey);
  // #93/#50 — the ACTUAL selected framework for this topic's format (name + component step labels),
  // from the managed content-format registry loaded in review-context. Undefined when the format has
  // no managed framework — the card then falls back to the plain "Framework: {format}" badge, never a
  // generic placeholder structure.
  const fw = r.frameworks?.[t.format];
  const remainingLabel = gate?.rule_key === "all" ? "Still required:" : "Any of:";
  // #22 — on the Scripts stage the hero is the script's own opening; the parent topic hook is demoted
  // to a labeled "Topic through-line". Elsewhere the hero is unchanged (topic hook).
  // #149 — registry-shaped structures have no `hook` key; the opening is the first beat in the
  // format's registry order (e.g. Carousel slide_1, registry-labeled "Hook").
  const openingBeat = isScript ? getScriptOpeningBeat(t, fw?.structureOrder) : { key: null, text: null };
  const scriptOpening = openingBeat.text;
  const topicHook = (t.hook_text && t.hook_text.trim()) || "";
  const heroText = scriptOpening
    || topicHook
    || (isSchedule ? (t.hcs_name_ar || t.hcs_name_en) : "Pending title generation");
  const showTopicThroughLine = Boolean(scriptOpening) && Boolean(topicHook) && topicHook !== scriptOpening;
  const selected = r.selectedSlotIds.has(t.slot_id);
  // when the script's opening beat is promoted to the hero, don't repeat it in the blueprint
  const allBeats = structureEntries(t.script_structure, fw);
  const promotedBeats = allBeats.filter(
    (e) => Boolean(scriptOpening) && (e.key === openingBeat.key || e.key.toLowerCase() === "hook"),
  );
  const flow = allBeats.filter((e) => !promotedBeats.includes(e));
  // #177 — framework truthfulness: how do the SAVED beats relate to the managed registry structure?
  //   legacy   — the registry explicitly marks this format legacy_carry_forward (no client framework);
  //   fallback — the format has no registry structure at all (generic 4-beat labels in use);
  //   stale    — the format HAS a registry structure but this script predates it (none of its saved
  //              keys exist in the registry order) → regenerating applies the current framework;
  //   managed  — saved beats match the registry structure (no disclosure needed).
  // Generic/fallback labels are never presented silently as client framework truth.
  const registryOrder = fw?.structureOrder || [];
  const savedMatchesRegistry = registryOrder.length > 0
    && allBeats.some((e) => registryOrder.includes(e.key.toLowerCase()));
  const structureDisclosure = allBeats.length === 0 ? null
    : fw?.frameworkStatus === "legacy_carry_forward"
      ? { testid: "structure-legacy", text: "Legacy format — no client framework configured" }
      : registryOrder.length === 0
        ? { testid: "structure-fallback", text: "Generic fallback — no framework structure configured" }
        : !savedMatchesRegistry
          ? { testid: "structure-stale", text: "Generated with older structure — regenerate for current framework" }
          : null;
  const totalBeats = flow.length + promotedBeats.length;
  const checks = deliveryChecks(t.delivery_check);
  const hasScriptBlueprint = !isTopic && (flow.length > 0 || Boolean(t.delivery_notes) || checks.length > 0);

  const [mode, setMode] = useState<Density>(density);
  useEffect(() => setMode(density), [density]);   // follow the section-level density unless overridden
  // Which OLDER revision (if any) is pending an explicit "discard newer & rework" confirmation.
  const [confirmDiscard, setConfirmDiscard] = useState<number | null>(null);
  // #14 Phase 1 — inline title (hook_text) edit for topic review items.
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const canEditTitle = isTopic && !isSchedule;
  const beginTitleEdit = () => { setTitleDraft(topicHook); setEditingTitle(true); };
  const saveTitleEdit = () => { r.editField(t.slot_id, "topic", "hook_text", titleDraft); setEditingTitle(false); };
  // #14 — inline edit of the topic BODY (text_ar, shown as t.topic_angle). Same safe append-only path.
  const [editingBody, setEditingBody] = useState(false);
  const [bodyDraft, setBodyDraft] = useState("");
  const canEditBody = isTopic && !isSchedule;
  const beginBodyEdit = () => { setBodyDraft(t.topic_angle || ""); setEditingBody(true); };
  const saveBodyEdit = () => { r.editField(t.slot_id, "topic", "text_ar", bodyDraft); setEditingBody(false); };
  // #66 — inline edit of the SCRIPT body (script_ar) and the final line (final_line) on the script stage.
  // Same audited append-only path; a manual script edit re-opens language/religious sign-off server-side.
  const canEditScript = isScript && !isSchedule;
  const [editingScript, setEditingScript] = useState(false);
  const [scriptDraft, setScriptDraft] = useState("");
  const beginScriptEdit = () => { setScriptDraft(t.script_ar || ""); setEditingScript(true); };
  const saveScriptEdit = () => { r.editField(t.slot_id, "script", "script_ar", scriptDraft); setEditingScript(false); };
  const [editingFinal, setEditingFinal] = useState(false);
  const [finalDraft, setFinalDraft] = useState("");
  const beginFinalEdit = () => { setFinalDraft(t.final_line || ""); setEditingFinal(true); };
  const saveFinalEdit = () => { r.editField(t.slot_id, "script", "final_line", finalDraft); setEditingFinal(false); };
  const full = mode === "full";
  // #20/#55 — kept in LOCKSTEP with the sticky review-header height (review-surface.tsx). A lookup-scrolled
  // card must land BELOW the sticky header, never behind it. After the #20 header compaction the sticky
  // header is ≈316px (wide) / ≈340px (narrow); 20rem/22rem clears both with a small buffer that also absorbs
  // taller badge-heavy states. If the header grows past this budget, raise these values in step.
  const cardScrollMargin = "scroll-mt-[22rem] md:scroll-mt-[20rem]";

  const dot = (t.slot_status === "APPROVED_ASSIGNED" || t.slot_status === "TOPIC_APPROVED") ? "bg-success"
    : t.current_outcome === "rejected" ? "bg-destructive"
    : t.current_outcome === "changes_requested" ? "bg-warning"
    : t.current_outcome === "approved" ? "bg-success"
    : "bg-muted-foreground/40";

  const decidedBadge = myDecision && (
    <Badge variant={lastDecision.decision === "approve" ? "success" : lastDecision.decision === "reject" ? "destructive" : "warning"}>{g("decision", lastDecision.decision)}</Badge>
  );

  // CHIP — one scannable line; click to open. Actions intentionally hidden at this density.
  if (mode === "chip") {
    return (
      <Card data-testid={`card-${t.slot_id}`} data-status={t.slot_status} data-rev={rev} data-lookup={highlight ? "match" : undefined} className={`${cardScrollMargin} py-0 ${highlight ? "ring-2 ring-primary ring-offset-2 ring-offset-background" : ""}`}>
        <button onClick={() => setMode("compact")} className="flex w-full items-center gap-2 px-3 py-2 text-left">
          {canAct && (
            <input
              type="checkbox"
              checked={selected}
              data-testid={`select-${t.slot_id}`}
              aria-label={`Select ${codeLabel} ${contentId}`}
              className="size-4 shrink-0 accent-primary"
              onClick={(event) => event.stopPropagation()}
              onChange={() => r.toggleSelected(t.slot_id)}
            />
          )}
          <span className={`size-2 shrink-0 rounded-full ${dot}`} />
          <span className="shrink-0 text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">{codeLabel}</span>
          <Badge className="shrink-0 border border-primary/30 bg-primary/10 font-mono text-[11px] text-foreground hover:bg-primary/10">{contentId}</Badge>
          {idMode === "detailed" && <span className="hidden text-[11px] text-muted-foreground md:inline">{contentDescriptor}</span>}
          <span className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">{placement}</span>
          <span data-testid={`hero-${t.slot_id}`} dir="auto" title={heroText ?? undefined} className="ar-hook min-w-0 flex-1 truncate text-base">{isSchedule ? heroText : `«${heroText}»`}</span>
          {decidedBadge}
          {rev > 1 && <Badge variant="warning">v{rev}</Badge>}
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
        </button>
      </Card>
    );
  }

  return (
    <Card data-testid={`card-${t.slot_id}`} data-status={t.slot_status} data-rev={rev} data-lookup={highlight ? "match" : undefined} className={`${cardScrollMargin} ${highlight ? "ring-2 ring-primary ring-offset-2 ring-offset-background" : ""}`}>
      {/* slim header — identity + density controls */}
      <CardHeader className="pb-2">
        <div className="flex items-start gap-3">
          <div className="flex items-center gap-2">
            {canAct && (
              <input
                type="checkbox"
                checked={selected}
                data-testid={`select-${t.slot_id}`}
                aria-label={`Select ${codeLabel} ${contentId}`}
                className="size-4 shrink-0 accent-primary"
                onChange={() => r.toggleSelected(t.slot_id)}
              />
            )}
            <span className={`size-2 shrink-0 rounded-full ${dot}`} />
          </div>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2 rounded-md border border-primary/20 bg-primary/5 px-2.5 py-1">
                <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">{codeLabel}</span>
                <Badge data-testid={`content-id-${t.slot_id}`} className="border border-primary/30 bg-primary/10 px-2.5 py-1 font-mono text-[12px] font-semibold tracking-[0.14em] text-foreground hover:bg-primary/10">
                  {contentId}
                </Badge>
              </div>
              <Badge variant="outline" className="text-[10px]">{placement}</Badge>
              <Badge variant="outline" className="text-[10px]">{cadence}</Badge>
              {rev > 1 && <Badge variant="warning">v{rev}</Badge>}
              {decidedBadge}
            </div>
            {idMode === "detailed" && (
              <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span className="font-medium text-foreground/90">{contentDescriptor}</span>
                <span>System ID: <span className="font-mono">{t.slot_id}</span></span>
              </div>
            )}
          </div>
          <div className="ml-auto flex items-center gap-1">
            <button onClick={() => setMode(full ? "compact" : "full")} title={full ? "Less detail" : "More detail"}
              className="rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
              {full ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
            </button>
            <button onClick={() => setMode("chip")} title="Collapse"
              className="rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
              <Minimize2 className="size-3.5" />
            </button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* two-column, RTL-native: meta + English (left) · Arabic hook hero (right) */}
        <div className={`grid grid-cols-1 gap-4 ${isGrid ? "2xl:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]" : "md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]"}`}>
          {/* LEFT — meta + English rationale */}
          <div className="order-2 space-y-2 md:order-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="secondary">{t.pillar_name_en}</Badge>
              <Badge variant={t.slot_status === "APPROVED_ASSIGNED" || t.slot_status === "TOPIC_APPROVED" ? "success" : "outline"}>{g("status", t.slot_status)}</Badge>
              <Badge variant="outline">Framework: {t.format}</Badge>
              <Badge variant="outline">Lens: {lensBadgeLabel(t.lens, t.lens_name_en, full)}</Badge>
            </div>
            <div className="text-xs text-muted-foreground">Human struggle: {t.hcs_name_en} · HCS {t.hcs_id} · {placement} · {cadence}</div>
            {isSchedule && <div className="text-xs text-muted-foreground">Topic titles are generated only after this planned schedule slot is approved.</div>}
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <Badge variant="outline">{t.approval_count} approved</Badge>
              {t.current_outcome === "pending" && (
                <Badge variant="outline">
                  {t.remaining_approvals} more approval{t.remaining_approvals === 1 ? "" : "s"} required
                </Badge>
              )}
            </div>
            {t.current_outcome === "pending" && t.remaining_assignments.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                <span>{remainingLabel}</span>
                {t.remaining_assignments.map((assignment) => (
                  <Badge
                    key={`${t.slot_id}-${assignment.assignment_kind}-${assignment.assignment_key}`}
                    variant="outline"
                  >
                    {approvalAssignmentLabel(assignment)}
                  </Badge>
                ))}
              </div>
            )}

            {full && isTopic && isMeaningfulRationale(t.rationale_en) && (
              <div data-testid={`why-now-${t.slot_id}`} className="rounded-md border-l-2 border-primary/60 bg-secondary/40 px-3 py-2">
                <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Why this topic now</div>
                <div className="text-sm">{t.rationale_en}</div>
              </div>
            )}

            {hasRisk && (
              <div className="flex flex-wrap items-center gap-1.5">
                {(t.review_blockers || []).map((b) => <Badge key={b} variant="warning">⏳ awaiting {g("stage", b)}</Badge>)}
                {writerFlags.map((f) => <Badge key={f} variant="destructive">{g("flag", f)}</Badge>)}
              </div>
            )}

            {full && decided && (
              <div className="text-xs text-muted-foreground">
                {t.decisions.map((d, i) => (
                  <span key={i}>{i > 0 && " · "}{d.approver_id}: <b className="text-foreground">{g("decision", d.decision)}</b>{d.notes ? ` — “${d.notes}”` : ""}</span>
                ))}
              </div>
            )}
          </div>

          {/* RIGHT — the Arabic hook hero */}
          <div
            dir={isSchedule ? "auto" : "rtl"}
            className={`order-1 space-y-2 text-right ${isGrid ? "border-t pt-3" : "md:order-2 md:border-l md:pl-4"} border-border/60`}
          >
            {editingTitle && canEditTitle ? (
              <div className="space-y-2" data-testid={`edit-title-panel-${t.slot_id}`}>
                <Textarea
                  data-testid={`edit-title-input-${t.slot_id}`}
                  dir="rtl"
                  rows={2}
                  value={titleDraft}
                  onChange={(event) => setTitleDraft(event.target.value)}
                  className="ar-hook text-right leading-snug"
                  style={{ fontSize: full ? "1.5rem" : "1.2rem" }}
                />
                <div className="flex items-center justify-end gap-2">
                  <Button data-testid={`edit-title-save-${t.slot_id}`} size="sm" disabled={busy || !titleDraft.trim()} onClick={saveTitleEdit}>Save</Button>
                  <Button data-testid={`edit-title-cancel-${t.slot_id}`} size="sm" variant="ghost" disabled={busy} onClick={() => setEditingTitle(false)}>Cancel</Button>
                </div>
              </div>
            ) : (
              <div className="flex items-start justify-end gap-1.5">
                <div data-testid={`hero-${t.slot_id}`} className="ar-hook leading-snug text-foreground" style={{ fontSize: full ? "1.9rem" : "1.35rem", lineHeight: 1.35 }}>
                  {isSchedule ? heroText : `«${heroText}»`}
                </div>
                {canEditTitle && (
                  <button
                    data-testid={`edit-title-${t.slot_id}`}
                    aria-label="Edit title"
                    disabled={busy}
                    className="mt-1 shrink-0 text-muted-foreground/60 hover:text-foreground disabled:opacity-40"
                    onClick={beginTitleEdit}
                  >
                    <Pencil className="size-3.5" />
                  </button>
                )}
              </div>
            )}
            {/* #159 — stack the English label ABOVE the Arabic quote: inline they sit in an RTL
                hero column, so the label visually trails mid-flow and reads as part of the quote.
                Stacking removes the mixed-direction ordering ambiguity; meaning unchanged. */}
            {showTopicThroughLine && (
              <div data-testid={`topic-throughline-${t.slot_id}`} className="text-xs text-muted-foreground">
                <div data-testid={`topic-throughline-label-${t.slot_id}`} className="font-medium uppercase tracking-[0.14em]">Topic through-line</div>
                <div dir="auto" data-testid={`topic-throughline-text-${t.slot_id}`} className="mt-0.5 text-[13px] leading-6">«{topicHook}»</div>
              </div>
            )}
            {full && isSchedule && (
              <div className="text-sm text-muted-foreground">
                Planned framework: {t.format} · {t.pillar_name_en} · {t.hcs_name_en}
              </div>
            )}
            {full && !isSchedule && (t.topic_angle || editingBody) && (
              editingBody && canEditBody ? (
                <div className="space-y-2" data-testid={`edit-body-panel-${t.slot_id}`}>
                  <Textarea
                    data-testid={`edit-body-input-${t.slot_id}`}
                    dir="rtl"
                    rows={3}
                    value={bodyDraft}
                    onChange={(event) => setBodyDraft(event.target.value)}
                    className="text-right text-sm leading-relaxed"
                  />
                  <div className="flex items-center justify-end gap-2">
                    <Button data-testid={`edit-body-save-${t.slot_id}`} size="sm" disabled={busy || !bodyDraft.trim()} onClick={saveBodyEdit}>Save</Button>
                    <Button data-testid={`edit-body-cancel-${t.slot_id}`} size="sm" variant="ghost" disabled={busy} onClick={() => setEditingBody(false)}>Cancel</Button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start justify-end gap-1.5">
                  <div data-testid={`topic-body-${t.slot_id}`} dir="auto" className="ar-body min-w-0 flex-1 text-right text-sm leading-7 text-muted-foreground">{t.topic_angle}</div>
                  {canEditBody && (
                    <button
                      data-testid={`edit-body-${t.slot_id}`}
                      aria-label="Edit topic body"
                      disabled={busy}
                      className="mt-0.5 shrink-0 text-muted-foreground/60 hover:text-foreground disabled:opacity-40"
                      onClick={beginBodyEdit}
                    >
                      <Pencil className="size-3.5" />
                    </button>
                  )}
                </div>
              )
            )}
            {full && isTopic && isMeaningfulRationale(t.rationale_ar) && <div dir="auto" className="ar-body text-right text-sm leading-7 text-muted-foreground">{t.rationale_ar}</div>}
          </div>
        </div>

        {/* #93/#50 — the ACTUAL selected framework for this topic (name + component steps), not a generic
            placeholder. Renders only when the format maps to a managed framework with components. */}
        {full && isTopic && fw && fw.components.length > 0 && (
          <div data-testid={`framework-${t.slot_id}`} className="rounded-xl border border-primary/25 bg-primary/[0.03] p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Selected framework</span>
              <Badge variant="secondary" data-testid={`framework-name-${t.slot_id}`}>{fw.frameworkName || fw.name}</Badge>
              <Badge variant="outline" className="text-[10px]">{fw.name}</Badge>
            </div>
            {fw.summary && <p className="mt-1.5 text-xs text-muted-foreground">{fw.summary}</p>}
            <div className="mt-2 flex flex-wrap gap-1.5" data-testid={`framework-components-${t.slot_id}`}>
              {fw.components.map((c, i) => (
                <Badge key={`${c}-${i}`} variant="outline" className="text-[11px]">{i + 1}. {c}</Badge>
              ))}
            </div>
          </div>
        )}

        {hasScriptBlueprint && (
          <div className={`grid gap-3 ${isGrid ? "grid-cols-1" : "xl:grid-cols-[minmax(0,1.25fr)_minmax(19rem,1fr)]"}`}>
            <div className="rounded-xl border bg-secondary/20 p-3">
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <div className="text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">{structureSectionTitle(t.format)}</div>
                <Badge variant="outline" className="text-[10px]">{t.format}</Badge>
                {/* #177 — never show generic/legacy/stale structure as if it were the client
                    framework: the disclosure is compact but always visible on the card. */}
                {structureDisclosure && (
                  <Badge variant="warning" className="text-[10px]" data-testid={`${structureDisclosure.testid}-${t.slot_id}`}>
                    {structureDisclosure.text}
                  </Badge>
                )}
                {/* #157 — target CONTEXT (system/stage-level intent) and the native-review
                    REVIEW-STATE signal are deliberately separate statements; neither implies the
                    other, and neither claims per-revision dialect verification. */}
                <Badge variant="outline" className="text-[10px]" title={SCRIPT_DIALECT_TARGET_TITLE} data-testid={`script-target-${t.slot_id}`}>
                  target · {SCRIPT_DIALECT_TARGET}
                </Badge>
                {t.needs_native_review && (
                  <Badge variant="warning" className="text-[10px]" title={NATIVE_REVIEW_TITLE} data-testid={`script-native-review-${t.slot_id}`}>
                    marked for native review
                  </Badge>
                )}
                {/* #154 — truthful generation attribution: the persisted provider:model that produced
                    THIS script revision, or an explicit not-recorded state. Never inferred. */}
                {/* #159 — no ml-auto here: with the two-column card the header is ~half width and an
                    auto margin tears the wrapped badge cluster apart with a dead gap; the cluster
                    reads best as one continuous wrapped group (identity → intent → state → provenance). */}
                {t.script_model ? (
                  <Badge variant="outline" className="font-mono text-[10px]" data-testid={`script-model-${t.slot_id}`}>{t.script_model}</Badge>
                ) : (
                  <Badge variant="outline" className="text-[10px] text-muted-foreground" data-testid={`script-model-missing-${t.slot_id}`}>model not recorded</Badge>
                )}
              </div>
              {flow.length > 0 ? (
                <div className={`grid gap-2 ${isGrid ? "grid-cols-1" : "md:grid-cols-2"}`}>
                  {flow.map((step) => (
                    <div key={`${t.slot_id}-${step.key}`} className="rounded-lg border bg-background/80 p-3">
                      <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">{step.label}</div>
                      <div dir="auto" className="mt-1 text-sm leading-6 text-foreground">{step.value}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">This script has no structured beats saved yet.</div>
              )}
            </div>

            <div className="space-y-3">
              <div className="rounded-xl border bg-secondary/20 p-3">
                <div className="mb-2 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">{directionSectionTitle(t.format)}</div>
                <div dir="auto" className="text-sm leading-6 text-foreground">
                  {t.delivery_notes || "No delivery direction has been captured for this script yet."}
                </div>
                {checks.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {checks.map((check) => (
                      <Badge key={`${t.slot_id}-${check.key}`} variant={check.ok ? "success" : "warning"} className="text-[10px]">
                        {check.label}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              {stageKey === "script" && (
                <div className="rounded-xl border border-primary/30 bg-primary/5 p-3">
                  <div className="mb-2 text-xs font-medium uppercase tracking-[0.18em] text-primary/90">Production handoff preview</div>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="secondary">{t.format}</Badge>
                    {/* #177 — truthful count: include the beat promoted to the card headline (the
                        Carousel's slide 1 hook) instead of implying the framework has one step less,
                        and only call them "framework steps" when they actually match the registry. */}
                    {totalBeats > 0 && (
                      <Badge variant="outline" data-testid={`structure-count-${t.slot_id}`}>
                        {totalBeats} {savedMatchesRegistry ? "framework step" : "structured beat"}{totalBeats === 1 ? "" : "s"}
                      </Badge>
                    )}
                    {promotedBeats.length > 0 && (
                      <Badge variant="outline" data-testid={`structure-promoted-${t.slot_id}`}>
                        “{promotedBeats[0].label}” shown as the headline
                      </Badge>
                    )}
                    {t.delivery_notes && <Badge variant="outline">Direction included</Badge>}
                    {t.final_line && <Badge variant="outline">Final line preserved</Badge>}
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">
                    On approval, production receives this format, the preserved final line, the delivery direction, and the structured flow shown here.
                  </p>
                  {full && t.final_line && (
                    <div className="mt-3 rounded-lg border bg-background/70 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Locked final line</div>
                        {canEditScript && !editingFinal && (
                          <button
                            data-testid={`edit-final-${t.slot_id}`}
                            aria-label="Edit final line"
                            disabled={busy}
                            className="shrink-0 text-muted-foreground/60 hover:text-foreground disabled:opacity-40"
                            onClick={beginFinalEdit}
                          >
                            <Pencil className="size-3.5" />
                          </button>
                        )}
                      </div>
                      {editingFinal && canEditScript ? (
                        <div className="mt-2 space-y-2" data-testid={`edit-final-panel-${t.slot_id}`}>
                          <Textarea
                            data-testid={`edit-final-input-${t.slot_id}`}
                            dir="rtl"
                            rows={2}
                            value={finalDraft}
                            onChange={(event) => setFinalDraft(event.target.value)}
                            className="text-right text-base leading-7"
                          />
                          <div className="flex items-center justify-end gap-2">
                            <Button data-testid={`edit-final-save-${t.slot_id}`} size="sm" disabled={busy || !finalDraft.trim()} onClick={saveFinalEdit}>Save</Button>
                            <Button data-testid={`edit-final-cancel-${t.slot_id}`} size="sm" variant="ghost" disabled={busy} onClick={() => setEditingFinal(false)}>Cancel</Button>
                          </div>
                        </div>
                      ) : (
                        <div data-testid={`final-line-${t.slot_id}`} dir="rtl" className="mt-1 text-base leading-7 text-foreground">«{t.final_line}»</div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* version history — LINEAR chain, per-version actions. Live in compact (co-creation path). */}
        {!isSchedule && rev > 1 && (
          <div>
            <button data-testid={`history-${t.slot_id}`} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => r.toggleHistory(t.slot_id)}>
              {r.history.has(t.slot_id) ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />} version history ({rev} revisions)
            </button>
            {r.history.has(t.slot_id) && (() => {
              const revList = r.revisions[t.slot_id] || [];
              const headRev = revList.length ? Math.max(...revList.map((rv) => rv.revision)) : rev;
              return (
              <div className="mt-2 space-y-2" data-testid={`versions-${t.slot_id}`}>
                {revList.map((v) => {
                  const isHead = v.revision === headRev;
                  const key = `${t.slot_id}:${v.revision}`;
                  return (
                  <div key={v.revision} data-testid={`version-${t.slot_id}-${v.revision}`} data-approved={v.approved} data-head={isHead} className={`rounded-md border-l-2 px-3 py-2 text-sm ${v.approved ? "border-success/60 bg-success/5" : "border-border bg-secondary/30"}`}>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={v.approved ? "success" : "outline"}>v{v.revision}{v.approved ? " · approved" : ""}</Badge>
                      {isHead && <Badge variant="outline" data-testid={`version-head-${t.slot_id}-${v.revision}`}>current</Badge>}
                      {v.base_revision && <span className="text-xs text-muted-foreground">based on v{v.base_revision}</span>}
                      {/* #154 — script revisions carry the persisted model (key present, maybe null);
                          topic revisions omit the key entirely (no persisted equivalent) and show nothing. */}
                      {v.model !== undefined && (v.model ? (
                        <span className="font-mono text-[11px] text-muted-foreground" data-testid={`version-model-${t.slot_id}-${v.revision}`}>{v.model}</span>
                      ) : (
                        <span className="text-[11px] text-muted-foreground" data-testid={`version-model-missing-${t.slot_id}-${v.revision}`}>model not recorded</span>
                      ))}
                    </div>
                    {typeof v.hook_text === "string" && v.hook_text.trim() && (
                      <div dir="rtl" className="ar-hook mt-1 text-base text-foreground">«{v.hook_text}»</div>
                    )}
                    {v.body && <div dir="auto" className="mt-1 text-muted-foreground">{v.body}</div>}
                    {v.feedback && <div dir="auto" className="mt-1 text-xs"><span className="text-muted-foreground">comment: </span>“{v.feedback}”</div>}
                    {v.change_summary_en && <div className="text-xs"><span className="text-muted-foreground">addressed: </span>{v.change_summary_en}</div>}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      {gate && canAct && (
                        <Button data-testid={`approve-rev-${t.slot_id}-${v.revision}`} size="sm" variant="outline" disabled={actionBusy} onClick={() => r.approveVersion(t.slot_id, v.revision)}><Check /> Approve this version</Button>
                      )}
                      <input data-testid={`reworkfrom-text-${t.slot_id}-${v.revision}`} dir="auto" placeholder={isHead ? "rework from the current version — what to change?" : "rework from this older version — what to change?"}
                        className="flex h-8 min-w-[16rem] flex-1 rounded-md border border-input bg-transparent px-2 text-xs"
                        value={r.reworkFromDraft[key] || ""}
                        onChange={(e) => r.setReworkFromDraft((m) => ({ ...m, [key]: e.target.value }))} />
                      <Button
                        data-testid={`reworkfrom-${t.slot_id}-${v.revision}`}
                        size="sm"
                        variant="warning"
                        disabled={actionBusy}
                        onClick={() => { if (isHead) r.reworkFrom(t.slot_id, v.revision); else setConfirmDiscard(v.revision); }}
                      ><Pencil /> Rework from this</Button>
                    </div>
                    {!isHead && confirmDiscard === v.revision && (
                      <div data-testid={`reworkfrom-warning-${t.slot_id}-${v.revision}`} className="mt-2 space-y-1.5 rounded-md border border-warning/40 bg-warning/10 p-2 text-xs">
                        <div className="text-foreground">
                          ⚠ Reworks from <b>v{v.revision}</b>, not the latest. This restores v{v.revision} as the working version, so the newer revision{headRev > v.revision + 1 ? "s" : ""} <b>v{v.revision + 1}{headRev > v.revision + 1 ? `–v${headRev}` : ""}</b> stop{headRev > v.revision + 1 ? "" : "s"} being the head (they stay in history). To refine the latest instead, rework from <b>v{headRev} · current</b>.
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <Button data-testid={`reworkfrom-confirm-${t.slot_id}-${v.revision}`} size="sm" variant="destructive" disabled={actionBusy} onClick={() => { r.reworkFrom(t.slot_id, v.revision); setConfirmDiscard(null); }}>Discard newer &amp; rework</Button>
                          <Button data-testid={`reworkfrom-cancel-${t.slot_id}-${v.revision}`} size="sm" variant="ghost" onClick={() => setConfirmDiscard(null)}>Cancel</Button>
                        </div>
                      </div>
                    )}
                  </div>
                  );
                })}
                {!r.revisions[t.slot_id] && <div className="text-xs text-muted-foreground">loading versions…</div>}
              </div>
              );
            })()}
          </div>
        )}

        {/* script preview — toggle, live in compact. #66: inline-edit the script body (script_ar) when open. */}
        {!isTopic && t.script_ar && (
          <div>
            <div className="flex items-center gap-3">
              <button className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground" onClick={() => r.toggleScript(t.slot_id)}>
                <FileText className="size-3" /> {r.openScript.has(t.slot_id) ? "hide script" : "show script"}
              </button>
              {canEditScript && r.openScript.has(t.slot_id) && !editingScript && (
                <button
                  data-testid={`edit-script-${t.slot_id}`}
                  aria-label="Edit script"
                  disabled={busy}
                  className="flex items-center gap-1 text-xs text-muted-foreground/70 hover:text-foreground disabled:opacity-40"
                  onClick={beginScriptEdit}
                >
                  <Pencil className="size-3" /> edit
                </button>
              )}
            </div>
            {r.openScript.has(t.slot_id) && (
              editingScript && canEditScript ? (
                <div className="mt-2 space-y-2" data-testid={`edit-script-panel-${t.slot_id}`}>
                  <Textarea
                    data-testid={`edit-script-input-${t.slot_id}`}
                    dir="rtl"
                    rows={6}
                    value={scriptDraft}
                    onChange={(event) => setScriptDraft(event.target.value)}
                    className="ar-script text-right text-sm leading-7"
                  />
                  <div className="flex items-center justify-end gap-2">
                    <Button data-testid={`edit-script-save-${t.slot_id}`} size="sm" disabled={busy || !scriptDraft.trim()} onClick={saveScriptEdit}>Save</Button>
                    <Button data-testid={`edit-script-cancel-${t.slot_id}`} size="sm" variant="ghost" disabled={busy} onClick={() => setEditingScript(false)}>Cancel</Button>
                  </div>
                </div>
              ) : (
                <pre data-testid={`script-body-${t.slot_id}`} dir="rtl" className="ar-script mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md border bg-secondary/30 p-3 text-sm leading-7">
                  {t.script_ar}{t.final_line ? `\n\n— ${t.final_line}` : ""}
                </pre>
              )
            )}
          </div>
        )}

        {/* DIRECTIVE — full only (what this stage was handed) */}
        {full && t.directive && (
          <div className="rounded-md border-l-2 border-primary/40 bg-secondary/30 px-3 py-2">
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {dam ? "Directive — what to deliver" : "Stage brief — what this stage must satisfy"}
            </div>
            {t.directive.payload?.intent?.en && <div className="text-sm">{t.directive.payload.intent.en}</div>}
            {!!t.directive.payload?.acceptance_criteria?.length && (
              <div className="mt-1 flex flex-wrap gap-1">
                {t.directive.payload.acceptance_criteria.map((a) => <Badge key={a} variant="outline" className="text-[10px]">{a}</Badge>)}
              </div>
            )}
          </div>
        )}

        {/* DAM media — full only */}
        {full && dam && (
          <div className="rounded-md border bg-secondary/20 p-2">
            <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Media ({dam.kind})</div>
            {(t.assets || []).filter((a) => a.stage === dam.stage).length > 0 ? (
              <ul className="mb-2 space-y-0.5 text-xs">
                {(t.assets || []).filter((a) => a.stage === dam.stage).map((a) => (
                  <li key={a.asset_id} className="flex items-center gap-2">
                    <Badge variant="secondary" className="text-[10px]">{a.kind} v{a.version}{a.platform_variant ? ` · ${a.platform_variant}` : ""}</Badge>
                    <span dir="ltr" className="truncate text-muted-foreground">{a.uri}</span>
                  </li>
                ))}
              </ul>
            ) : <div className="mb-2 text-xs text-muted-foreground">No media yet — add a reference before approving.</div>}
            <div className="flex gap-2">
              <input dir="ltr" placeholder="media reference (path or URL)"
                className="flex h-8 w-full rounded-md border border-input bg-transparent px-2 text-sm"
                value={r.assetUri[t.slot_id] || ""} onChange={(e) => r.setAssetUri((m) => ({ ...m, [t.slot_id]: e.target.value }))} />
              <Button size="sm" variant="outline" disabled={actionBusy} onClick={() => r.addAsset(t.slot_id)}>Add media</Button>
            </div>
          </div>
        )}

        {/* #250 — read-only SDAM readiness + provider-neutral Edit-input visibility on the
            Production/Edit surfaces, plus the #237 approved-content inspection affordance
            (status-independent, non-mutating). Persisted truth only; never a workflow control. */}
        {full && (stageKey === "production" || stageKey === "edit") && (
          <div className="flex flex-col gap-1 rounded-md border bg-secondary/20 p-2">
            <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">SDAM readiness</div>
            <SdamReadiness slotId={t.slot_id} canRegister={stageKey === "edit" && r.canDecideGate} />
            <TrailInspect slotId={t.slot_id} />
          </div>
        )}

        {/* inline change-request composer */}
        {r.supportsRework && t.slot_id in r.changing && (
          <div className="rounded-md border bg-secondary/30 p-2">
            <Textarea data-testid={`change-text-${t.slot_id}`} dir="auto" placeholder="What should change? (injected into the regeneration)"
              className="scroll-mt-80"
              value={r.changing[t.slot_id]} onChange={(e) => r.setChanging((c) => ({ ...c, [t.slot_id]: e.target.value }))} />
            <div className="mt-2 flex gap-2">
              <Button className="scroll-mt-80" data-testid={`submit-change-${t.slot_id}`} size="sm" variant="warning" disabled={actionBusy} onClick={() => r.submitChange(t.slot_id)}>Send back for changes</Button>
              <Button className="scroll-mt-80" size="sm" variant="ghost" onClick={() => r.setChanging((c) => { const n = { ...c }; delete n[t.slot_id]; return n; })}>Cancel</Button>
            </div>
          </div>
        )}
      </CardContent>

      {/* PRIMARY per-item decisions — full width beneath, live in compact + full */}
      <Separator />
      <div className="flex flex-wrap items-center gap-2 p-3">
        {canAct && !(t.slot_id in r.changing) && (
          <>
            <Button className="scroll-mt-80" data-testid={`approve-${t.slot_id}`} size="sm" variant="success" disabled={actionBusy} onClick={() => r.decide("approve", [t.slot_id])}><Check /> Approve</Button>
            {r.supportsRework && (
              <Button className="scroll-mt-80" data-testid={`request-${t.slot_id}`} size="sm" variant="warning" disabled={actionBusy} onClick={() => r.setChanging((c) => ({ ...c, [t.slot_id]: "" }))}><Pencil /> Request change</Button>
            )}
            <Button className="scroll-mt-80" data-testid={`reject-${t.slot_id}`} size="sm" variant="destructive" disabled={actionBusy} onClick={() => r.decide("reject", [t.slot_id])} title="Drop from the batch — recoverable (undo or restore anytime)">
              <X /> Drop (recoverable)
            </Button>
          </>
        )}
        {myDecision && (
          <>
            <span className="text-xs text-muted-foreground">
              your decision: <b className="text-foreground">{g("decision", lastDecision.decision)}</b>
              {t.current_outcome === "pending" ? " — waiting for the remaining approver(s)" : ""}
            </span>
            <Button className="scroll-mt-80" data-testid={`undo-${t.slot_id}`} size="sm" variant="ghost" disabled={actionBusy} onClick={() => r.undecide(t.slot_id)}><Undo2 /> Undo</Button>
          </>
        )}
        {!myDecision && t.current_outcome !== "pending" && (
          <span className="text-xs text-muted-foreground">
            resolved: <b className="text-foreground">{g("outcome", t.current_outcome) !== t.current_outcome ? g("outcome", t.current_outcome) : t.current_outcome}</b>
          </span>
        )}
      </div>
    </Card>
  );
}
