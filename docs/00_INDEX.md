# Documentation Index

This file is the top-level index for tracked repository documentation.

## Primary Client Requirements Sources

Client SRDs are **external authoritative documents** under controlled document governance; the
repository holds **no original client binaries** — only a sanitized manifest + a versioned checkpoint
ledger keyed by stable `source_id` + cryptographic fingerprint.

- `client-source/README.md`
  - **External-source manifest** — `source_id`/class, title, version/date, SHA-256 fingerprints,
    source authority/status, and revision/supersession rules (no binaries, paths, URLs, or secrets).
    External locator status: `placement pending`.
- `client-source/2026-07-08/TRACEABILITY.md`
  - **Versioned checkpoint ledger** — many-to-many `FR-*`→checkpoint mapping with **split authority
    fields** (`source_authority` / `interpretation_authority` / `clarification_evidence`), frozen
    coverage-status vocabulary at weakest-defensible status, per-checkpoint `decision_owner`,
    evidence links, exclusions, unresolved inputs, and explicit supersession. Derived interpretation;
    non-authoritative; creates no product/architecture/status.
- `design/lunaris/05-content-schedule-current-reference.docx`
- `design/lunaris/06-carousel-framework.docx`
- `design/lunaris/07-hero-reel-framework.docx`
- `design/lunaris/08-3sec-caption-framework.docx`
  - Pre-existing content-format framework references (unchanged by this update).

Derived planning, GitHub issues, and client reports must remain traceable to the external sources via
their `source_id` + fingerprint. The separate STITCH platform SRD governs the broader platform
architecture and does not replace this product-specific client SRD.

## Canonical Program Governance

- `14_Tanaghom_AI_Content_Department_Program_Evolution_Report_v1_0.md`
  - Canonical change request, implementation status, and release-readiness report for the current repository worktree.
  - Current shared client/internal reference baseline: **Issue 1.2 dated July 2, 2026**. Keep internal notes and client-facing artifacts aligned to this same issue until a newer issue is formally published.
  - Current client-facing edition includes verified companion-system status for Analytics, SDAM, and AVP, plus screenshot/placeholder appendix support for direct distribution.
  - Tracked report visual assets used to keep internal and client-facing references aligned live under `docs/assets/program_evolution_report_v1_0/`.
  - Client-facing deliverables generated from this source live in `output/doc/`:
    - `Tanaghom_AI_Content_Department_Program_Evolution_Report_v1_0.docx`
    - `Tanaghom_AI_Content_Department_Program_Evolution_Report_v1_0.pdf`

## Core Orientation

- `README.md` — repository entry point and operating principles.
- `BUILD_STATE.md` — continuity log and execution tracking.
- `HANDOFF.md` — current worktree continuity notes and immediate next steps.
- `ARCHITECTURE.md` — governing architecture and lifecycle principles.
- `ROADMAP.md` — consolidated phased roadmap.

## Change Request And Control-Plane Planning

- `10_Change_Request_01_Internal_Assessment.md`
- `11_Change_Request_01_Phased_Backlog.md`
- `12_CR01_Parallel_Execution_Map.md`
- `16_Release_Gate_and_Delivery_Control.md`
- `17_Agent_First_Cowork_Surface_Feature_Request.md`

## Product And UX References

- `UI_VISION.md`
- `design/PENPOT_MCP_LOCAL_SETUP.md`
- `design/lunaris/05-content-schedule-reference.md`
- `design/lunaris/09-content-framework-alignment.md`
- `design/lunaris/SYNC_POLICY.md`

## Methodology, Quality, And Operations References

- `approval-identity-pre-iam.md`
- `05_Voice_Performance_Calibration.md`
- `07_Test_Drive_Real_vs_Generated.md`
- `QUALITY_BACKLOG.md`
- `13_Codex_Network_Sandbox_Runbook.md`
- `16_Release_Gate_and_Delivery_Control.md`
