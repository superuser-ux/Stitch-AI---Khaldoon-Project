"use client";
import { useEffect, useState } from "react";
import { useReview, type SdamBinding, type SdamHandoff, type SlotSdam } from "@/lib/review-context";
import { Badge } from "@/components/ui/badge";
import { ChevronDown, ChevronUp } from "lucide-react";

// #250 — read-only SDAM readiness + Edit-input visibility for the Production/Edit surfaces.
// Every rendered state traces to PERSISTED #244 truth (bindings + newest observation) or to a
// truthful runtime condition (fetch failed / live read not configured). It never claims SDAM
// availability, edit completion, or workflow advancement, and renders no mutation control —
// the only interactions are read fetches. Five visibly-distinct states per the directive:
// not bound · pending · unavailable/blocked · stale · fresh ready (+ bound-with-no-evidence,
// shown distinctly from provider-observed pending).

type ChipTone = "secondary" | "outline" | "success" | "warning" | "destructive";

function stateChip(b: SdamBinding): { label: string; tone: ChipTone } {
  if (b.effective_state === null) return { label: "Bound — no readiness evidence yet", tone: "outline" };
  if (b.effective_state === "ready") return { label: "SDAM: fresh ready", tone: "success" };
  if (b.effective_state === "stale") return { label: "SDAM: evidence stale", tone: "warning" };
  if (b.effective_state === "not_ready_pending") return { label: "SDAM: pending", tone: "warning" };
  if (b.effective_state === "unavailable" || b.effective_state === "unauthorized" || b.effective_state === "malformed")
    return { label: `SDAM: unavailable/blocked (${b.effective_state})`, tone: "destructive" };
  return { label: `SDAM: blocked (${b.effective_state})`, tone: "destructive" };
}

function BindingRow({ binding, slotId, canRegister, onChanged }:
  { binding: SdamBinding; slotId: string; canRegister: boolean; onChanged: () => Promise<void> }) {
  const r = useReview();
  const [open, setOpen] = useState(false);
  const [handoff, setHandoff] = useState<SdamHandoff | null>(null);
  const [handoffErr, setHandoffErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [retryErr, setRetryErr] = useState<string | null>(null);
  const chip = stateChip(binding);

  const resolveHandoff = async () => {
    setLoading(true); setHandoffErr(null);
    try { setHandoff(await r.sdamHandoff(binding.binding_id)); }
    catch (e) { setHandoffErr((e as Error).message || "handoff read failed"); }
    finally { setLoading(false); }
  };

  // #259 P1b — the governed projection-only retry for a registered-but-projection-pending binding.
  // Calls the SAME convergent endpoint (binding exists -> Phase D only; never a second resource/
  // binding) and reloads the server truth so the pending state clears on success.
  const retryProjection = async () => {
    setRetrying(true); setRetryErr(null);
    try { await r.sdamRegisterEdit(slotId); await onChanged(); }
    catch (e) { setRetryErr((e as Error).message || "projection retry failed"); }
    finally { setRetrying(false); }
  };

  return (
    <div data-testid={`sdam-binding-${binding.binding_id}`} className="flex w-full flex-col gap-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant={chip.tone} data-testid={`sdam-state-${binding.binding_id}`}>{chip.label}</Badge>
        {binding.observed_at && (
          <span className="text-[11px] text-muted-foreground">observed {new Date(binding.observed_at).toLocaleString()}</span>
        )}
        <button
          data-testid={`sdam-detail-toggle-${binding.binding_id}`}
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="inline-flex items-center gap-0.5 rounded-md px-1 py-0.5 text-[11px] text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
        >
          {open ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />} Details
        </button>
      </div>
      {/* #259 P1b — registered but the discovery projection is pending: a reload-stable truth
          (server-derived) with a governed projection-only retry that never re-creates. */}
      {binding.projection_pending && (
        <div data-testid={`sdam-projection-pending-${binding.binding_id}`} className="flex flex-wrap items-center gap-1.5 text-[11px]">
          <Badge variant="warning">Registered — discovery projection pending</Badge>
          {canRegister && (
            <button
              data-testid={`sdam-projection-retry-${binding.binding_id}`}
              disabled={retrying}
              onClick={() => void retryProjection()}
              className="rounded-md border px-1.5 py-0.5 hover:bg-secondary/50"
            >
              {retrying ? "Retrying…" : "Retry projection"}
            </button>
          )}
          {retryErr && <span className="text-destructive">{retryErr}</span>}
        </div>
      )}
      {open && (
        <div data-testid={`sdam-detail-${binding.binding_id}`} className="flex flex-col gap-1 rounded-lg border border-border/60 bg-background/70 p-2 text-[11px] text-muted-foreground">
          {/* provider-neutral Edit-input summary — persisted binding/observation truth only */}
          <div>
            Canonical asset <span className="font-mono text-foreground/80">{binding.asset_id}</span> · v{binding.asset_version}
          </div>
          <div>
            Provider ref <span className="font-mono">{binding.provider_key}:{binding.external_ref}</span> (opaque) · mapping v{binding.mapping_version}
          </div>
          {binding.expires_at && binding.effective_state === "ready" && (
            <div>Evidence fresh until {new Date(binding.expires_at).toLocaleString()}</div>
          )}
          {binding.handoff_ready ? (
            <div className="flex flex-col gap-1">
              {!handoff && (
                <button
                  data-testid={`sdam-media-resolve-${binding.binding_id}`}
                  disabled={loading}
                  onClick={() => void resolveHandoff()}
                  className="w-fit rounded-md border px-1.5 py-0.5 text-[11px] hover:bg-secondary/50"
                >
                  {loading ? "Resolving…" : "Resolve media source (read-only)"}
                </button>
              )}
              {handoffErr && <span className="text-destructive">{handoffErr}</span>}
              {handoff && !handoff.configured && (
                <span data-testid={`sdam-media-unconfigured-${binding.binding_id}`} className="italic">
                  {handoff.reason || "live SDAM read is not configured on this runtime"}
                </span>
              )}
              {handoff && handoff.configured && !handoff.handoff && (
                <span className="italic">{handoff.reason || "not fresh ready"}</span>
              )}
              {handoff?.handoff && (
                <a data-testid={`sdam-media-source-${binding.binding_id}`} className="break-all font-mono text-foreground/80 underline decoration-dotted"
                   href={handoff.handoff.media_source} target="_blank" rel="noreferrer">
                  media source (read-only, resolved live)
                </a>
              )}
            </div>
          ) : (
            <span className="italic">Edit input becomes available only on fresh <span className="font-mono">ready</span> evidence.</span>
          )}
          <span className="italic">Approved content definition: open Inspect on this item (#237 view). Readiness shown here never advances the workflow.</span>
        </div>
      )}
    </div>
  );
}

export function SdamReadiness({ slotId, canRegister = false }: { slotId: string; canRegister?: boolean }) {
  const r = useReview();
  const [state, setState] = useState<SlotSdam | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [registering, setRegistering] = useState(false);
  const [registerMsg, setRegisterMsg] = useState<string | null>(null);

  const load = async () => {
    setError(null);
    try { setState(await r.sdamState(slotId)); }
    catch (e) { setError((e as Error).message || "could not load SDAM state"); }
  };
  useEffect(() => { void load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [slotId]);

  // #259 S2 — the ONE governed registration action. Explicit (never auto); the server re-checks the
  // audit-verified S1 pin + trusted principal and returns a truthful typed outcome. Not idempotent
  // client-side, so it is never auto-retried; the panel reloads the persisted truth on completion.
  const register = async () => {
    setRegistering(true); setRegisterMsg(null);
    try {
      const res = await r.sdamRegisterEdit(slotId) as
        { state?: string; external_ref?: string; projection_status?: string; retryable?: boolean };
      // surface the TYPED per-phase truth: a projection-pending outcome is still a successful
      // registration — the completed edit is registered, only the discovery projection is retryable.
      setRegisterMsg(res.projection_status === "pending"
        ? `Registered — resource ${res.external_ref ?? "?"} (Pending in SDAM); discovery projection pending — retry`
        : `Registered — resource ${res.external_ref ?? "?"} (Pending in SDAM)`);
      await load();
    } catch (e) {
      setRegisterMsg((e as Error).message || "registration failed");
    } finally {
      setRegistering(false);
    }
  };

  return (
    <div data-testid={`sdam-readiness-${slotId}`} className="flex w-full flex-col gap-1 text-xs">
      {error && (
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="destructive" data-testid={`sdam-error-${slotId}`}>SDAM state unavailable (fetch failed)</Badge>
          <button className="rounded-md border px-1.5 py-0.5 text-[11px]" onClick={() => void load()}>Retry</button>
        </div>
      )}
      {!error && !state && <Badge variant="outline" data-testid={`sdam-loading-${slotId}`}>SDAM: checking…</Badge>}
      {state && state.bindings.length === 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="secondary" data-testid={`sdam-notbound-${slotId}`}>SDAM: not bound</Badge>
          {canRegister && (
            <button
              data-testid={`sdam-register-edit-${slotId}`}
              disabled={registering}
              onClick={() => void register()}
              className="rounded-md border px-1.5 py-0.5 text-[11px] hover:bg-secondary/50"
            >
              {registering ? "Registering…" : "Register completed edit in SDAM"}
            </button>
          )}
        </div>
      )}
      {registerMsg && (
        <span data-testid={`sdam-register-msg-${slotId}`} className="text-[11px] text-muted-foreground">{registerMsg}</span>
      )}
      {state && state.bindings.map((b) => (
        <BindingRow key={b.binding_id} binding={b} slotId={slotId} canRegister={canRegister} onChanged={load} />
      ))}
    </div>
  );
}
