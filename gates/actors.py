"""Unified Actor Model policy resolver (M9 · Block B3).

Implements the architecture's "behavior is COMPUTED: propose vs request-review vs act =
f(autonomy × stage-policy × permissions)" for the FIRST instance the architecture names — the
reviewer-disposition (escalate / waive) decision — plus a hard-floor guard on gate decisions.

PURE module: it takes a config dict + a principal row (dict) and returns a verdict. No engine /
db dependency (the caller loads the principal and audits). The per-principal dimensions live as
DATA on `principal` (migration 006): kind, autonomy_level, capabilities, permissions, scope.

Guardrails (non-negotiable, encoded here):
- default-LOW autonomy (a principal with none set is treated as `propose_only`).
- HARD FLOORS always keep a human gate (publish / spend / religious) regardless of autonomy —
  most-restrictive-wins.
- agents never SELF-escalate: autonomy is read, never written here; a low-autonomy actor simply
  cannot act as a higher one (there is no path to raise one's own level).
- escalation (asking for MORE oversight) is always permitted — only WAIVE (reducing oversight) and
  approving a hard-floor gate are gated.
- every autonomous decision is surfaced to the caller (verdict["autonomous"]) to be logged +
  remains human-overridable (a later human disposition overrides it).
"""

# Ordered low -> high. A non-human must reach `autonomous_min_level` to act without prior approval.
AUTONOMY_RANK = {"propose_only": 0, "recommend": 1, "act_with_approval": 2,
                 "act_and_notify": 3, "autonomous": 4}


def _am(cfg):
    return cfg.get("actor_model") or {}


def enabled(cfg):
    return bool(_am(cfg).get("enabled", True))


def _floors(cfg):
    return _am(cfg).get("hard_floors") or {}


def is_hard_floor_review(cfg, review):
    return review in (_floors(cfg).get("reviews") or [])


def is_hard_floor_gate(cfg, stage):
    return stage in (_floors(cfg).get("gates") or [])


def load_principal(cur, principal_id):
    cur.execute("SELECT * FROM principal WHERE principal_id=%s", (principal_id,))
    return cur.fetchone()


def _kind(principal):
    return (principal or {}).get("kind", "user")


def _autonomy(cfg, principal):
    return (principal or {}).get("autonomy_level") or _am(cfg).get("default_autonomy", "propose_only")


def _can_act_autonomously(cfg, level):
    floor = _am(cfg).get("autonomous_min_level", "act_and_notify")
    return AUTONOMY_RANK.get(level, 0) >= AUTONOMY_RANK.get(floor, 3)


def _has_permission(cfg, principal, token):
    if not _am(cfg).get("require_permission", False):
        return True                                   # read but don't hard-enforce until perms are seeded
    perms = (principal or {}).get("permissions") or []
    return token in perms


def authorize_disposition(cfg, principal, review, action):
    """May `principal` perform `action` ('escalate' | 'waive') on `review`?
    Returns {allowed, autonomous, autonomy_level, hard_floor, actor_kind, reason}. The caller
    raises on allowed=False and logs `autonomous=True` decisions."""
    kind = _kind(principal)
    human = kind == "user"
    level = _autonomy(cfg, principal)
    hard = is_hard_floor_review(cfg, review)
    base = {"autonomy_level": level, "actor_kind": kind, "hard_floor": hard}

    if action == "escalate":
        # asking for MORE oversight is always the safe direction — always permitted
        return {**base, "allowed": True,
                "autonomous": (not human) and _can_act_autonomously(cfg, level),
                "reason": "escalation always permitted (increases oversight)"}

    # action == 'waive' (reducing oversight)
    if human:
        return {**base, "allowed": True, "autonomous": False, "reason": "human disposition"}
    if hard:
        return {**base, "allowed": False, "autonomous": False,
                "reason": f"hard floor: '{review}' review must keep a human gate (no autonomous waive)"}
    if not _can_act_autonomously(cfg, level):
        return {**base, "allowed": False, "autonomous": False,
                "reason": f"autonomy '{level}' too low to waive without human review"}
    if not _has_permission(cfg, principal, _am(cfg).get("waive_permission", "review.waive")):
        return {**base, "allowed": False, "autonomous": False,
                "reason": "missing permission to waive (review.waive)"}
    return {**base, "allowed": True, "autonomous": True,
            "reason": f"autonomous waive by {kind} at autonomy '{level}'"}


def authorize_gate_decision(cfg, principal, stage):
    """Hard floor on gate approvals: a non-human can never decide a hard-floor gate
    (publish / scholar / content sign-off), regardless of autonomy. Returns (allowed, reason)."""
    if is_hard_floor_gate(cfg, stage) and _kind(principal) != "user":
        return False, f"hard floor: '{stage}' must be decided by a human"
    return True, "ok"
