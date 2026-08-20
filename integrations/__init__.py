"""Integration providers (M9 · Block B2) — external executors that fill a stage's generator slot.

DEFINED + STUBBED here, NOT integrated (every provider is `enabled: false` in config until its
Phase-C block is wired). Each provider implements the SAME contract: it receives a stage's INPUT
directive (the B1 package) + the DAM assets that directive references, does its work via its own
integration shape (API / MCP / file), and returns artifacts + the next-stage directive. This is the
seam that lets AVP / POSTIZ / the analytics system drop into the pipeline without touching the
engine — the gate/review structure is uniform across all of them.

See docs/INTEGRATION_CONTRACTS.md for the full mapping to the directive schema.
"""
from .contracts import StageExecutor, ExecutorResult, load_registry  # noqa: F401
from .stubs import AVPExecutor, PostizExecutor, AnalyticsExecutor  # noqa: F401
