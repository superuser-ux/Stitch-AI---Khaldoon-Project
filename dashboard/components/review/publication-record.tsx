"use client";
import { useRef, useState } from "react";
import { useReview } from "@/lib/review-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Send, CheckCircle2 } from "lucide-react";
// #212 — HTTP-surface-safe key minting (secure-context randomUUID OR getRandomValues UUIDv4;
// throws with no cryptographic source, which this dialog turns into a visible no-request failure)
import { mintOperationKey } from "@/lib/publication-key";

// #200 (pub.v1) — governed manual publication recording for ONE approved distribution item.
// The server decides eligibility and who may record on every call; this UI only offers the action
// and shows the recorded truth. Platform choices come from the platform registry (never hardcoded).
// The operation key is generated ONCE when the dialog opens and reused across retries, so
// double-clicks and retried requests converge on a single recorded publication.

export function PublicationRecord({ slotId }: { slotId: string }) {
  const r = useReview();
  const pubs = r.publications.filter((p) => p.slot_id === slotId);
  const published = pubs.filter((p) => p.publication_occurrence_id);
  const unfinished = pubs.filter((p) => !p.publication_occurrence_id
    && p.current_state !== "cancelled" && p.current_state !== "corrected" && p.current_state !== "retracted");
  const [open, setOpen] = useState(false);
  const [platform, setPlatform] = useState("");
  const [destination, setDestination] = useState("");
  const [url, setUrl] = useState("");
  const [keyUnavailable, setKeyUnavailable] = useState(false);
  const opKey = useRef("");

  const openDialog = (next: boolean) => {
    if (next) {
      try {
        opKey.current = mintOperationKey();  // one key per dialog open; retries reuse it
      } catch {
        // fail SAFELY and VISIBLY: no key -> no dialog, no request, no partial state
        setKeyUnavailable(true);
        setOpen(false);
        return;
      }
      setKeyUnavailable(false);
      setPlatform(r.platforms.length === 1 ? r.platforms[0].platform_key : "");
      setDestination(""); setUrl("");
    }
    setOpen(next);
  };
  const submit = async () => {
    if (!platform || !opKey.current) return;
    await r.recordPublication({
      slot_id: slotId, platform_key: platform, idempotency_key: opKey.current,
      destination: destination.trim() || undefined, url: url.trim() || undefined,
    });
    setOpen(false);
  };

  return (
    <div data-testid={`publication-record-${slotId}`} className="flex w-full flex-wrap items-center gap-2 pl-5 text-xs">
      {published.length === 0 && unfinished.length === 0 && (
        <span data-testid={`publication-state-${slotId}`} className="text-muted-foreground">Not recorded as published yet.</span>
      )}
      {keyUnavailable && (
        <span data-testid={`publication-key-unavailable-${slotId}`} className="text-destructive">
          Publication recording couldn&apos;t start in this browser — nothing was sent.
          Try a different browser or contact your administrator.
        </span>
      )}
      {published.map((p) => (
        <span key={p.publication_intent_id} data-testid={`publication-state-${slotId}`} className="inline-flex items-center gap-1.5">
          <Badge variant="success"><CheckCircle2 className="size-3" /> Published — {p.platform_key}</Badge>
          {p.url && <a href={p.url} target="_blank" rel="noreferrer" className="underline underline-offset-2 text-muted-foreground">view post</a>}
          <span className="text-muted-foreground">recorded by {p.attested_by}</span>
        </span>
      ))}
      {unfinished.map((p) => (
        <span key={p.publication_intent_id} className="inline-flex items-center gap-1.5">
          <Badge variant="warning">Recording started — {p.platform_key}</Badge>
          <Button data-testid={`publication-complete-${slotId}`} size="sm" variant="outline" disabled={r.busy}
            onClick={() => r.completePublication(p.publication_intent_id)}>
            It&apos;s live — finish recording
          </Button>
        </span>
      ))}
      <Dialog open={open} onOpenChange={openDialog}>
        <DialogTrigger asChild>
          <Button data-testid={`record-publication-${slotId}`} size="sm" variant="outline" className="ml-auto" disabled={r.busy}>
            <Send className="size-3.5" /> Record a publication
          </Button>
        </DialogTrigger>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Record where this was published</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3 text-sm">
            <p className="text-xs text-muted-foreground">
              For posts you published yourself. This saves a permanent record of what went out and
              where — it does not post anything.
            </p>
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium">Platform</span>
              <Select value={platform} onValueChange={setPlatform}>
                <SelectTrigger data-testid={`publication-platform-${slotId}`}><SelectValue placeholder="Choose a platform" /></SelectTrigger>
                <SelectContent>
                  {r.platforms.map((pl) => (
                    <SelectItem key={pl.platform_key} value={pl.platform_key}>{pl.name || pl.platform_key}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium">Account or channel <span className="font-normal text-muted-foreground">(optional)</span></span>
              <Input data-testid={`publication-destination-${slotId}`} value={destination}
                onChange={(e) => setDestination(e.target.value)} placeholder="e.g. @tanaghom" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium">Link to the post <span className="font-normal text-muted-foreground">(optional)</span></span>
              <Input data-testid={`publication-url-${slotId}`} value={url}
                onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
            </label>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            <Button data-testid={`publication-submit-${slotId}`} disabled={!platform || r.busy} onClick={submit}>
              It&apos;s published — save the record
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
