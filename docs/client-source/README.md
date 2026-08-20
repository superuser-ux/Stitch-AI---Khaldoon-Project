# External Client SRD Source Manifest

Client SRDs are **external authoritative documents** held under controlled document governance. **This
repository stores no original client binaries, no unrestricted source text, and no confidential
document content.** It retains only the sanitized manifest below — a stable identity + cryptographic
fingerprint + authority/status for each external source, so derived issues, directives, PRs, and
proofs stay traceable without importing the source into application history.

Requirement-to-work traceability is recorded separately as a versioned checkpoint ledger:
[`2026-07-08/TRACEABILITY.md`](2026-07-08/TRACEABILITY.md). The ledger records source and
interpretation authority in **separate fields** (`source_authority` / `interpretation_authority` /
`clarification_evidence`) — mixed authority is never encoded in a single value.

## Source manifest

Location class = where the authoritative original is governed (out-of-repo). No private path, URL,
credential, or signed link is stored here; the fingerprint is the integrity anchor.

| source_id | class | title | version / date | fingerprint (SHA-256) | source_authority | status |
|---|---|---|---|---|---|---|
| `SRC-SMA-SRD-2026-07-08` | external · operator-governed document store (**placement pending**) | Social Media & Content Automation System — SRD | v0.4 draft · dated 2026-07-08 | `d1d643162b970ae579337bccab83227f8a547cd1b132775c43a1fcde8c22da65` | client-authored (prepared for the CCO/Owner) | draft — pending technical feasibility review + owner sign-off |
| `SRC-SMA-ONEPAGER-2026-07-08` | external · operator-governed document store (**placement pending**) | Social Media & Content Automation — One-Pager overview | dated 2026-07-08 | `b9bc71ea27ddc716c9a2e8d30f5c4cd3473fa8ba3fef135e1c72adfefaf822cb` | client-authored | companion overview to the SRD |

The fingerprints match the operator-supplied external originals; any manifest change must re-verify
them against those originals. Provenance: supplied by the operator in the Tanaghom Codex session on
2026-07-12.

## Authority, revision, and supersession rules

- The manifest is a **reference**, not the source: it does not make source clauses executable
  configuration or immutable product architecture. Interpretation lives in the checkpoint ledger and
  remains **non-authoritative** relative to the client-authored original.
- Distinguish authority classes and never collapse them: **client-authored requirement**,
  **operator clarification** (an explicit amendment, recorded + cited — never a silent rewrite of
  source text), and **derived mapping** (Tanaghom-internal interpretation). The ledger carries these
  as separate fields per checkpoint; a claimed operator clarification requires a
  `clarification_evidence` citation.
- A later client revision is added as a **new dated `source_id` row with its own fingerprint**; the
  prior row is retained and marked superseded. Fingerprints are frozen per version; a changed
  fingerprint means a new source version, never an in-place edit.
- Internal plans may phase delivery, but **deferral must be explicit** and must not be reported as
  delivered functionality.
- Boundary: this source set defines the **Social Media & Content Automation** product requirements;
  the separate STITCH platform SRD defines the broader governed-platform direction and cannot be used
  to declare a product requirement absent.

## External authority location — status: `placement pending` (separate operator decision)

The authoritative originals should live in an **operator-governed external document store** (candidate:
the SDAM/ResourceSpace controlled-document space or an equivalent governed store) referenced only by
`source_id` + fingerprint. **The external locator status is explicitly `placement pending`: a
`source_id` + fingerprint proves the identity of an original, but does not yet provide retrieval.**
Final placement is a separate operator decision and does not block this manifest/ledger design; until
it is fixed, `class` reads `operator-governed document store (placement pending)`.
