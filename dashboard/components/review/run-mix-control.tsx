"use client";
// #278 P1 (#271 scope) — pre-Schedule-approval run-level format-mix revision through the planning
// surface. The operator re-allocates the per-run framework counts across the FULL pinned eligibility
// set (incl. zero-count frameworks). The server reconciles only uncommitted (RESERVED) slots and fails
// closed once any slot is committed; this control mirrors that: exact-total gating + truthful
// committed-state feedback. It never supersedes the pinned policy — only redistributes within it.
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "@/components/ui/dialog";

export function RunMixControl({
  pinned, currentMix, plannedTotal, committed, onRevise,
}: {
  pinned: { name: string; framework_id: string | null }[];
  currentMix: Record<string, number>;
  plannedTotal: number;
  committed: boolean;
  onRevise: (formatMix: Record<string, number>) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [mix, setMix] = useState<Record<string, number>>(() =>
    Object.fromEntries(pinned.map((f) => [f.name, currentMix[f.name] ?? 0])));
  const [busy, setBusy] = useState(false);
  const allocated = pinned.reduce((s, f) => s + (mix[f.name] || 0), 0);
  const exact = allocated === plannedTotal && plannedTotal > 0;

  const set = (name: string, raw: string) =>
    setMix((m) => ({ ...m, [name]: Math.max(0, parseInt(raw || "0", 10) || 0) }));

  const submit = async () => {
    setBusy(true);
    try { await onRevise(mix); setOpen(false); } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => {
      // re-seed from the live persisted mix each time it opens, so it reflects the latest allocation
      if (o) setMix(Object.fromEntries(pinned.map((f) => [f.name, currentMix[f.name] ?? 0])));
      setOpen(o);
    }}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" className="h-6 px-2 text-[11px]"
                data-testid="run-mix-open" disabled={pinned.length === 0}>Revise run mix</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Revise run format mix</DialogTitle></DialogHeader>
        {committed ? (
          <p className="py-2 text-sm text-destructive" data-testid="run-mix-committed">
            One or more slots have advanced past Schedule review, so the run-level mix is locked —
            committed content is never remapped. Revise those slots individually instead.
          </p>
        ) : (
          <div className="space-y-3 py-2 text-sm">
            {pinned.map((f) => (
              <label key={f.name} className="flex items-center justify-between gap-3">
                <span className="truncate" title={f.framework_id || undefined}>{f.name}</span>
                <Input type="number" min={0} className="w-24"
                       data-testid={`run-mix-${f.framework_id || f.name}`}
                       value={mix[f.name] ?? 0}
                       onChange={(e) => set(f.name, e.target.value)} />
              </label>
            ))}
            <p className="text-xs">
              <b data-testid="run-mix-total" className={exact ? "text-emerald-600" : "text-destructive"}>{allocated}</b>
              {" "}allocated of <b>{plannedTotal}</b> planned posts. Reconciles only uncommitted slots.
            </p>
          </div>
        )}
        <DialogFooter>
          <Button data-testid="run-mix-submit" disabled={busy || committed || !exact} onClick={submit}>
            Apply run mix
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
