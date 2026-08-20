"use client";
// #271 — governed single-slot schedule revision proposal. A reviewer may propose a change to one
// slot's planned day / time / framework (within the run's pinned policy) / topic guidance. The server
// returns ONLY that slot to Schedule review (existing reviewer authority); nothing is silently committed.
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter,
} from "@/components/ui/dialog";
import type { Target } from "@/lib/review-context";

export function ScheduleRevisionControl({
  slot, eligibleFormats, maxDay, onRevise,
}: {
  slot: Target;
  eligibleFormats: string[];
  maxDay?: number;   // #278 P1 — the run's period_len_days; a revised day must stay on the calendar
  onRevise: (slotId: string, changes: Record<string, unknown>) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [day, setDay] = useState<number>(slot.day);
  const [time, setTime] = useState<string>(slot.time_uae);
  const [format, setFormat] = useState<string>(slot.format);
  const [guidance, setGuidance] = useState<string>("");
  const [busy, setBusy] = useState(false);
  // the run's in-use frameworks (all valid under the pinned policy); always include the slot's own.
  const formats = Array.from(new Set([slot.format, ...eligibleFormats]));

  const submit = async () => {
    const changes: Record<string, unknown> = {};
    if (day !== slot.day) changes.day = day;
    if (time !== slot.time_uae) changes.time_uae = time;
    if (format !== slot.format) changes.format = format;
    if (guidance.trim()) changes.topic_guidance = guidance.trim();
    if (Object.keys(changes).length === 0) { setOpen(false); return; }
    setBusy(true);
    try { await onRevise(slot.slot_id, changes); setOpen(false); } finally { setBusy(false); }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]"
                data-testid={`revise-${slot.slot_id}`}>Revise</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Revise schedule — {slot.slot_id}</DialogTitle></DialogHeader>
        <div className="space-y-3 py-2 text-sm">
          <label className="flex items-center justify-between gap-3">Day
            <Input type="number" min={1} max={maxDay} className="w-24" value={day}
                   data-testid={`revise-day-${slot.slot_id}`}
                   onChange={(e) => {
                     const v = Math.max(1, parseInt(e.target.value || "1", 10));
                     setDay(maxDay ? Math.min(v, maxDay) : v);   // #278 P1 — keep the day on the calendar
                   }} />
          </label>
          <label className="flex items-center justify-between gap-3">Time
            <Input className="w-28" value={time} data-testid={`revise-time-${slot.slot_id}`}
                   onChange={(e) => setTime(e.target.value)} />
          </label>
          <label className="flex items-center justify-between gap-3">Framework
            <select className="w-48 rounded-md border bg-background px-2 py-1" value={format}
                    data-testid={`revise-format-${slot.slot_id}`}
                    onChange={(e) => setFormat(e.target.value)}>
              {formats.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </label>
          <label className="block space-y-1">Topic guidance (optional)
            <Input value={guidance} data-testid={`revise-guidance-${slot.slot_id}`}
                   placeholder="Planned brief guidance"
                   onChange={(e) => setGuidance(e.target.value)} />
          </label>
          <p className="text-xs text-muted-foreground">
            Returns only this slot to Schedule review; other slots are unaffected and its canonical ID is kept.
          </p>
        </div>
        <DialogFooter>
          <Button data-testid={`revise-submit-${slot.slot_id}`} disabled={busy} onClick={submit}>
            Propose revision
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
