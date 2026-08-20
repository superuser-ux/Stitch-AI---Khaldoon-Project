"use client";
import { type ReactNode, useEffect, useState } from "react";
import { useReview } from "@/lib/review-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";

// Start a run from the UI: days × posts/day (open range, defaults 28×2) -> POST /rounds.
export function NewRunDialog({
  triggerLabel = "New run",
  triggerContent,
  triggerVariant = "outline",
  triggerSize = "sm",
  triggerClassName = "",
  triggerTitle,
}: {
  triggerLabel?: string;
  triggerContent?: ReactNode;
  triggerVariant?: "default" | "destructive" | "outline" | "secondary" | "ghost" | "success" | "warning" | "link";
  triggerSize?: "default" | "sm" | "lg" | "icon";
  triggerClassName?: string;
  triggerTitle?: string;
}) {
  const r = useReview();
  const getBaselineEligibility = r.getBaselineEligibility;   // stable useCallback — safe effect dep
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState(28);
  const [ppd, setPpd] = useState(2);
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  // #276 — the operator supplies an exact per-run count for each currently-eligible framework (from the
  // baseline eligibility policy). The server requires it; their sum must equal the run total.
  const [eligible, setEligible] = useState<{ name: string; framework_id: string }[]>([]);
  const [mix, setMix] = useState<Record<string, number>>({});
  const total = Math.max(0, (days || 0) * (ppd || 0));
  const mixTotal = eligible.reduce((s, f) => s + (mix[f.name] || 0), 0);
  const mixValid = eligible.length > 0 && mixTotal === total;

  useEffect(() => {
    if (!open) return;
    getBaselineEligibility().then((p) => {
      setEligible(p.eligible);
      setMix(Object.fromEntries(p.eligible.map((f) => [f.name, 0])));   // zero mix — no inferred default
    }).catch(() => setEligible([]));
  }, [open, getBaselineEligibility]);

  const setCount = (name: string, v: number) =>
    setMix((m) => ({ ...m, [name]: Math.max(0, Number.isFinite(v) ? v : 0) }));

  const submit = async () => {
    setBusy(true);
    try { await r.plan(days, ppd, label.trim() || undefined, mix); setOpen(false); }
    finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          data-testid="new-run"
          size={triggerSize}
          variant={triggerVariant}
          className={triggerClassName}
          title={triggerTitle}
          aria-label={triggerTitle || triggerLabel}
        >
          {triggerContent || triggerLabel}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Start a run</DialogTitle></DialogHeader>
        <div className="space-y-4 py-2">
          <label className="space-y-1 text-sm">Run label
            <Input data-testid="label-input" placeholder="Optional run name" value={label}
                   onChange={(e) => setLabel(e.target.value)} />
          </label>
          <div className="grid grid-cols-2 gap-4">
          <label className="space-y-1 text-sm">Days
            <Input data-testid="days-input" type="number" min={1} value={days}
                   onChange={(e) => setDays(Math.max(1, parseInt(e.target.value || "1", 10)))} />
          </label>
          <label className="space-y-1 text-sm">Posts / day
            <Input data-testid="ppd-input" type="number" min={1} value={ppd}
                   onChange={(e) => setPpd(Math.max(1, parseInt(e.target.value || "1", 10)))} />
          </label>
          </div>
          <div className="space-y-2" data-testid="format-mix">
            <p className="text-sm font-medium">Framework mix <span className="text-muted-foreground">(exact count per framework — must total {total})</span></p>
            {eligible.map((f) => (
              <label key={f.name} className="flex items-center justify-between gap-3 text-sm">
                <span className="truncate" title={f.framework_id}>{f.name}</span>
                <Input data-testid={`mix-${f.framework_id || f.name}`} type="number" min={0} className="w-24"
                       value={mix[f.name] ?? 0}
                       onChange={(e) => setCount(f.name, parseInt(e.target.value || "0", 10))} />
              </label>
            ))}
          </div>
        </div>
        <p className="text-sm text-muted-foreground">
          = <b data-testid="run-total">{total}</b> planned posts;{" "}
          <b data-testid="mix-total" className={mixValid ? "text-emerald-600" : "text-destructive"}>{mixTotal}</b> allocated.
        </p>
        <DialogFooter>
          <Button data-testid="new-run-submit" disabled={busy || days < 1 || ppd < 1 || !mixValid} onClick={submit}>
            Plan run
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
