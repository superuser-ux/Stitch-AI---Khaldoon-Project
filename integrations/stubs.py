"""Provider stubs (M9 · Block B2) — contract only, NOT integrated.

Each stub declares which stage it fills + which directive it consumes/emits, and raises on
`execute` (the real integration is a Phase-C task). They exist so the seam is registrable and
documented now. Nothing here calls an external service.
"""
from .contracts import StageExecutor, register


@register
class AVPExecutor(StageExecutor):
    """Agentic Video Producer -> the media_edit generator slot.
    In : media_directive (approved script + production directions + raw assets in the DAM).
    Out: edit options (DAM assets) + the distribution_directive for review.
    The edit options STILL pass edit_review before moving on — AI proposes, human disposes."""
    name = "avp"
    stage = "media_edit"
    consumes = "media_directive"
    emits = "distribution_directive"


@register
class PostizExecutor(StageExecutor):
    """POSTIZ -> the distribution executor behind the publish gate.
    In : distribution_directive (formatted assets + platform targets + schedule windows).
    Out: scheduled/published posts. Nothing publishes without passing distribution_review first
    (the hard floor); POSTIZ only acts on already-approved state and records back as events."""
    name = "postiz"
    stage = "distribution"
    consumes = "distribution_directive"
    emits = None


@register
class AnalyticsExecutor(StageExecutor):
    """The user's analytics system -> feedback into Strategy. INTERFACE, don't rebuild.
    In : platform KPIs (read from their system). Out: strategy proposals as strategy_directives.
    High-stakes: proposals are NOT applied silently — they pass a hard-floor human review gate
    (propose -> review -> approve), like every other handoff."""
    name = "analytics"
    stage = "strategy"
    consumes = None
    emits = "strategy_directive"
