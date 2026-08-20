"use client";

import { useEffect, useState } from "react";
import { readJson, ReadError, type ApiHealth, type RuntimeIdentity } from "@/lib/read-model";

// #293 A4 — V2's own runtime identity + the LIVE gate-API health, both read at runtime.
//
// Truthfulness rules honoured here:
//   - V2's build/lane/surface come from V2's own /api/runtime (server-declared), never guessed.
//   - Writer mode is reported VERBATIM from the gate API's /health read model — V2 neither
//     interprets nor caches it. Stage 0 invokes no writer at all; this is a read, and displaying
//     it is how an operator can see WHICH api build V1 and V2 are both talking to.
//   - A failed read renders an explicit failure, never a blank or an optimistic default.

export function RuntimeStrip() {
  const [runtime, setRuntime] = useState<RuntimeIdentity | null>(null);
  const [health, setHealth] = useState<ApiHealth | null>(null);
  const [err, setErr] = useState<string | null>(null);

  // These two reads are INDEPENDENT and must commit independently.
  //
  // Defect found by the real-path evidence lane at 11db665 (#293 P1.3): a single Promise.all over
  // both reads rejects atomically, so when the gate API was genuinely unreachable the successful
  // /api/runtime result was discarded too — and the header fell back to the "…" LOADING
  // placeholder for a surface/build that were already known and final. That misreports "still
  // loading" during an outage, exactly when an operator most needs truthful runtime identity.
  //
  // /api/runtime is V2's own server truth and does not depend on the gate API being up. So it is
  // committed on its own, and only the api-writer field degrades to "unavailable".
  useEffect(() => {
    const ac = new AbortController();
    readJson<RuntimeIdentity>("/api/runtime", ac.signal)
      .then(setRuntime)
      .catch((e) => {
        if ((e as Error)?.name !== "AbortError") setRuntime(null);
      });
    readJson<ApiHealth>("/gw/health", ac.signal)
      .then((h) => {
        setHealth(h);
        setErr(null);
      })
      .catch((e) => {
        if ((e as Error)?.name === "AbortError") return;
        setErr(e instanceof ReadError ? e.message : "api health read failed");
      });
    return () => ac.abort();
  }, []);

  return (
    <span
      data-testid="wb-runtime"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-(--color-muted)"
    >
      <span>
        surface <b data-testid="wb-runtime-surface" className="font-mono text-(--color-fg)">{runtime?.surface ?? "…"}</b>
      </span>
      <span>
        build <b data-testid="wb-runtime-build" className="font-mono text-(--color-fg)">{runtime?.build ?? "…"}</b>
      </span>
      <span>
        api writer{" "}
        <b data-testid="wb-api-writer" className="font-mono text-(--color-fg)">
          {err ? "unavailable" : (health?.writer_mode ?? "…")}
        </b>
      </span>
      {err && (
        <span data-testid="wb-runtime-error" className="text-(--color-danger)">
          api health read failed: {err}
        </span>
      )}
    </span>
  );
}
