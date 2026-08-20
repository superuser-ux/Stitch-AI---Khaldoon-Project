import type { View } from "./review-context";

// #15 — a working view (lens) may persist across stage navigation only when it is valid for the
// destination stage. Views that expose per-item review cards + actions ("inbox", "grid") are valid
// everywhere; the round-level lenses ("overview", "workflow") and the schedule week-board ("calendar")
// hide per-item review, so they are invalid for content review stages and fall back to "inbox".

// views that render the per-item review card list with approve/request/reject actions
export const REVIEW_CARD_VIEWS: View[] = ["inbox", "grid"];

// content review stages require a per-item card view (topic/script/final/edit/distribution).
// the schedule/planning stage is not a per-item content review, so it may use any view (incl. calendar).
export const CONTENT_REVIEW_STAGES = ["topic", "script", "final", "edit", "distribution"];

export function isViewValidForStage(view: View, stageKey: string): boolean {
  if (!CONTENT_REVIEW_STAGES.includes(stageKey)) return true;   // schedule/planning: any view is fine
  return REVIEW_CARD_VIEWS.includes(view);                       // content review: card views only
}

// keep the view if valid for the stage, otherwise fall back to the per-item review surface (inbox)
export function coerceViewForStage(view: View, stageKey: string): View {
  return isViewValidForStage(view, stageKey) ? view : "inbox";
}
