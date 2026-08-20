"""The stage-executor contract + a config-driven registry.

An external executor is interchangeable with the AI generators (topic/script) and the manual
stages: all three are "a stage transform with a pluggable executor". The contract is expressed in
terms of the B1 directive schema, so an executor never sees engine internals — only directives +
assets in, artifacts + the next directive out. The gate that follows checks the output against the
incoming directive's acceptance_criteria, exactly as for AI/manual stages.
"""
from dataclasses import dataclass, field


@dataclass
class ExecutorResult:
    """What an executor returns. `artifacts` are DAM asset specs (dicts ready for dam.add_asset);
    `next_directive` is the directive the next stage consumes (or None for a terminal stage).
    `notes` carry provenance/telemetry for the audit/event log."""
    artifacts: list = field(default_factory=list)
    next_directive: dict | None = None
    notes: dict = field(default_factory=dict)


class StageExecutor:
    """Contract for an external executor that fills a stage's `generator` slot.

    Subclasses set `name`, `stage`, `consumes` (input directive type), `emits` (output directive
    type, or None). `execute` receives the incoming directive (B1 package) + the DAM assets it
    references and returns an ExecutorResult. Implementations live in Phase C; the stubs here only
    declare the contract so the seam is real and registrable now.
    """
    name = "abstract"
    stage = None
    consumes = None
    emits = None

    def __init__(self, spec=None):
        self.spec = spec or {}
        self.enabled = bool(self.spec.get("enabled", False))

    def execute(self, directive: dict, assets: list) -> ExecutorResult:
        raise NotImplementedError(
            f"{self.name}: external integration not wired yet (M9·B2 declares the contract; "
            f"Phase C implements it). See docs/INTEGRATION_CONTRACTS.md")

    def describe(self):
        return {"name": self.name, "stage": self.stage, "consumes": self.consumes,
                "emits": self.emits, "enabled": self.enabled, "kind": "external"}


# Registry — built from config `integrations.*`. Only ENABLED providers are returned, so with the
# default config (all disabled) the registry is empty: nothing is integrated, the seam is just ready.
_STUBS = {}


def register(cls):
    _STUBS[cls.name] = cls
    return cls


def load_registry(cfg):
    """{stage: executor_instance} for every ENABLED integration in config. Empty by default."""
    reg = {}
    for name, spec in (cfg.get("integrations") or {}).items():
        cls = _STUBS.get(name)
        if cls and spec.get("enabled"):
            reg[spec.get("stage", cls.stage)] = cls(spec)
    return reg


def available(cfg):
    """All declared providers (enabled or not) with their contract — for surfacing the seams."""
    out = []
    for name, spec in (cfg.get("integrations") or {}).items():
        cls = _STUBS.get(name)
        if cls:
            out.append(cls(spec).describe())
    return out
