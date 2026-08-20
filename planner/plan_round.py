#!/usr/bin/env python3
"""
Tanaghom Planner (M2) — deterministic round generation.

Implements Phase1_Build_Spec §3 / CANON-015:

  plan   Given a round request, read system_config.yaml (calendar template) and
         generate the round's slots:
           - pillar distribution per round (e.g. 22/17/9/4/4)
           - format distribution per week  (e.g. 4/1/2/2/3/1/1, x weeks)
           - HCS assigned sequentially via per-pillar hcs_cursor, walking
             hcs.seq_in_pillar; when a pillar's list is exhausted the cursor
             wraps and cycle_no increments (carried across rounds).
           - lens chosen from the HCS's recommended_lenses, excluding the lens
             used in the previous cycle; written to lens_history.
           - hook_type defaulted from the lens.
           - slots created at status RESERVED.
         Prints the generated calendar + summary and verifies the mix.

  verify Print the per-pillar cursor state and the lens-by-cycle history, proving
         the cursor advanced and lenses rotated for repeated HCS (acceptance #5).

All behavior comes from system_config.yaml — nothing about the mix is hardcoded.
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
import yaml
from psycopg2.extras import Json

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO / "system_config.yaml"

sys.path.insert(0, str(REPO / "gates"))
import engine as _engine  # noqa: E402  (#276 — baseline eligibility policy + round snapshot seam)


# ---------------------------------------------------------------------------
# Config + small helpers
# ---------------------------------------------------------------------------
def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def get_template(cfg: dict, name: str | None):
    cal = cfg["calendar"]
    name = name or cal["default_template"]
    if name not in cal["templates"]:
        raise SystemExit(f"unknown calendar template: {name!r}")
    return name, cal["templates"][name]


def even_spread(items_counts: list[tuple[str, int]]) -> list[str]:
    """Round-robin spread: emit one of each item per pass while any remain, so
    occurrences are distributed across the sequence rather than clustered.
    Consumes the exact counts, preserving the given item order."""
    remaining = {k: c for k, c in items_counts}
    order = [k for k, _ in items_counts]
    total = sum(c for _, c in items_counts)
    out: list[str] = []
    while len(out) < total:
        for k in order:
            if remaining[k] > 0:
                out.append(k)
                remaining[k] -= 1
                if len(out) == total:
                    break
    return out


def scale_distribution(ratios: dict, total: int) -> dict:
    """Scale a weighted distribution to exactly `total` integer units using the largest-remainder
    (Hamilton) method, preserving key order. Works for any total >= 0, including total < #keys
    (the largest weights win the scarce units; others get 0). Never returns negatives."""
    keys = list(ratios)
    weight_sum = sum(ratios.values())
    if total <= 0 or weight_sum <= 0:
        return {k: 0 for k in keys}
    raw = {k: ratios[k] * total / weight_sum for k in keys}
    floors = {k: int(raw[k]) for k in keys}
    used = sum(floors.values())
    remainder = total - used
    # hand out the leftover units to the largest fractional parts (ties: input order)
    order = sorted(keys, key=lambda k: (raw[k] - floors[k]), reverse=True)
    for k in order[:remainder]:
        floors[k] += 1
    return floors


def synth_post_times(ppd: int, base_times: list) -> list:
    """`ppd` posting times. Use the configured times when the count matches; otherwise spread
    evenly across the active day (09:00–21:00) so any posts_per_day works (parametric)."""
    if len(base_times) == ppd:
        return list(base_times)
    if ppd <= 1:
        return ["09:00"]
    start, end = 9 * 60, 21 * 60
    step = (end - start) // (ppd - 1)
    return [f"{(start + i*step)//60:02d}:{(start + i*step)%60:02d}" for i in range(ppd)]


def effective_template(tmpl: dict, days: int, ppd: int) -> dict:
    """A template copy scaled to days × ppd: scaled pillar/format mixes + synthesized times."""
    total = days * ppd
    et = dict(tmpl)
    et["period_len_days"] = days
    et["posts_per_day"] = ppd
    et["post_times"] = synth_post_times(ppd, tmpl.get("post_times", []))
    et["pillar_distribution"] = scale_distribution(tmpl["pillar_distribution"], total)
    et["format_distribution_weekly"] = scale_distribution(tmpl["format_distribution_weekly"], ppd * 7)
    return et


def default_round_label(round_id: str, days: int, posts_per_day: int) -> str:
    """Dynamic fallback label for unlabeled runs.

    Avoids leaking the source template name (for example "28-day") into runs that
    were actually planned at different dimensions like 3 days x 2/day.
    """
    return f"{days}-day run {round_id} ({posts_per_day}/day)"


def validate_format_mix(format_mix, eligible, total):
    """#276/#271 — validate an explicit operator per-run mix against the resolved baseline eligibility
    set: reject missing / non-object / unknown-or-ineligible framework / non-integer / negative /
    non-total. Zero is valid for an eligible framework. Raises ValueError (API → 422)."""
    if format_mix is None:
        raise ValueError("format_mix is required: an integer count per eligible framework")
    if not isinstance(format_mix, dict) or not format_mix:
        raise ValueError("format_mix must be a non-empty object of {framework: count}")
    eligible_names = {e["name"] for e in eligible}
    for name, count in format_mix.items():
        if name not in eligible_names:
            raise ValueError(f"framework {name!r} is not in the current baseline eligibility policy "
                             f"(eligible: {sorted(eligible_names)})")
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError(f"count for {name!r} must be a non-negative integer")
        if count < 0:
            raise ValueError(f"count for {name!r} must be >= 0")
    if sum(format_mix.values()) != total:
        raise ValueError(f"format_mix total {sum(format_mix.values())} must equal "
                         f"days×posts_per_day = {total}")


def assign_pillars_formats_exact(grid, tmpl, format_mix, eligible_order):
    """#276/#271 — assign the operator's EXACT counts across the COMPLETE run (even_spread, not a
    repeated weekly template). Assumes format_mix validated to sum to len(grid)."""
    total = len(grid)
    pillar_seq = even_spread(list(tmpl["pillar_distribution"].items()))
    if len(pillar_seq) != total:
        raise SystemExit(f"pillar_distribution sums to {len(pillar_seq)} but the run has {total} slots")
    fmt_seq = even_spread([(n, int(format_mix.get(n, 0))) for n in eligible_order])
    if len(fmt_seq) != total:
        raise SystemExit(f"format_mix sums to {len(fmt_seq)} but the run has {total} slots")
    for i, slot in enumerate(grid):
        slot["pillar_code"] = pillar_seq[i]
        slot["format"] = fmt_seq[i]
    return grid


def apply_managed_format_distribution(cur, tmpl: dict, eligible_names=None) -> dict:
    """If active managed content types define planning.weekly_count, prefer that over the
    static config template so format administration affects future planning.

    #276 — when `eligible_names` is given the weekly weights are read ONLY for those baseline-eligible
    formats; eligibility is governed by the baseline policy, never a hard-coded allowlist."""
    params = ["default", "content"]
    name_filter = ""
    if eligible_names is not None:
        name_filter = " AND f.name = ANY(%s)"
        params.append(list(eligible_names))
    cur.execute(
        """SELECT f.name, v.production_rules
           FROM content_format f
           JOIN content_format_version v ON v.content_format_id=f.content_format_id
           WHERE f.tenant_id=%s AND f.module=%s
             AND f.active=true AND coalesce(f.lifecycle_status, 'active')='active'
             AND v.status='active'""" + name_filter +
        """ ORDER BY coalesce((v.production_rules->'planning'->>'sort_order')::int, 9999), f.name""",
        tuple(params)
    )
    managed = {}
    for name, rules in cur.fetchall():
        rules = rules or {}
        planning = rules.get("planning") if isinstance(rules, dict) else {}
        weekly = planning.get("weekly_count") if isinstance(planning, dict) else None
        try:
            weekly = int(weekly)
        except (TypeError, ValueError):
            weekly = 0
        if weekly > 0:
            managed[name] = weekly
    if not managed:
        return tmpl
    out = dict(tmpl)
    slots_per_week = tmpl["posts_per_day"] * 7
    managed_total = sum(managed.values())
    # Admin-managed content types should influence planning, but an incomplete weekly mix must
    # never take down the run planner. Normalize the active weights to the required weekly slots.
    out["format_distribution_weekly"] = managed if managed_total == slots_per_week else scale_distribution(managed, slots_per_week)
    return out


# ---------------------------------------------------------------------------
# Cursor walk + lens rotation
# ---------------------------------------------------------------------------
class PillarWalker:
    """Walks one pillar's HCS list in seq_in_pillar order, continuing from the
    persisted cursor. Wraps to the top and bumps cycle_no when exhausted."""

    def __init__(self, pillar_code, ordered_hcs, last_hcs_id, cycle_no):
        self.pillar_code = pillar_code
        self.hcs = ordered_hcs                 # [hcs_id, ...] by seq_in_pillar
        self.cycle = cycle_no
        if last_hcs_id and last_hcs_id in ordered_hcs:
            self.pos = ordered_hcs.index(last_hcs_id) + 1
        else:
            self.pos = 0                        # fresh pillar: start at the top
        self.last_emitted = last_hcs_id

    def next(self):
        if self.pos >= len(self.hcs):           # exhausted -> wrap, new cycle
            self.pos = 0
            self.cycle += 1
        hcs_id = self.hcs[self.pos]
        self.pos += 1
        self.last_emitted = hcs_id
        return hcs_id, self.cycle


def pick_lens(hcs_id, cycle, recommended, hist, enforce_rotation):
    """Choose a lens from recommended_lenses, rotating by cycle and excluding the
    lens used in the previous cycle (when rotation is enforced). Records the
    choice in `hist` so later cycles in the same run can see it."""
    if not recommended:
        raise SystemExit(f"HCS {hcs_id} has no recommended_lenses")
    prior = hist.get((hcs_id, cycle - 1)) if enforce_rotation else None
    start = (cycle - 1) % len(recommended)
    rotated = recommended[start:] + recommended[:start]
    chosen = next((l for l in rotated if l != prior), rotated[0])
    hist[(hcs_id, cycle)] = chosen
    return chosen


# ---------------------------------------------------------------------------
# DB reads
# ---------------------------------------------------------------------------
def db_connect():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "tanaghom"),
        user=os.environ.get("DB_USER", "tanaghom"),
        password=os.environ["DB_PASSWORD"],
    )


def load_methodology(cur):
    cur.execute("SELECT hcs_id, pillar_code, name_en, recommended_lenses "
                "FROM hcs ORDER BY pillar_code, seq_in_pillar")
    pillar_hcs, hcs_lenses, hcs_name = {}, {}, {}
    for hcs_id, pillar_code, name_en, rec_lenses in cur.fetchall():
        pillar_hcs.setdefault(pillar_code, []).append(hcs_id)
        hcs_lenses[hcs_id] = rec_lenses or []
        hcs_name[hcs_id] = name_en
    cur.execute("SELECT lens_id, name_en, default_hook_type FROM lens")
    lens_name, lens_hook = {}, {}
    for lens_id, name_en, hook in cur.fetchall():
        lens_name[lens_id] = name_en
        lens_hook[lens_id] = hook
    return pillar_hcs, hcs_lenses, hcs_name, lens_name, lens_hook


def load_cursors(cur):
    cur.execute("SELECT pillar_code, last_hcs_id, cycle_no FROM hcs_cursor")
    return {p: (last, cyc) for p, last, cyc in cur.fetchall()}


def load_lens_history(cur):
    cur.execute("SELECT hcs_id, cycle_no, lens FROM lens_history")
    return {(h, c): l for h, c, l in cur.fetchall()}


def next_round_id(cur):
    cur.execute("SELECT round_id FROM round")
    nums = []
    for (rid,) in cur.fetchall():
        if rid and rid[0] in ("R", "r") and rid[1:].isdigit():
            nums.append(int(rid[1:]))
    return f"R{(max(nums) + 1) if nums else 1}"


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
def build_grid(round_id, tmpl):
    """Ordered list of slot scaffolds (day, time, suffix) for the whole period."""
    days = tmpl["period_len_days"]
    ppd = tmpl["posts_per_day"]
    times = tmpl["post_times"]
    if len(times) != ppd:
        raise SystemExit("post_times length must equal posts_per_day")
    suffixes = ["AM", "PM"] if ppd == 2 else [f"S{i+1}" for i in range(ppd)]
    grid = []
    for day in range(1, days + 1):
        for i in range(ppd):
            grid.append({
                "slot_id": f"{round_id}-D{day:02d}-{suffixes[i]}",
                "day": day,
                "time_uae": times[i],
            })
    return grid


def assign_pillars_formats(grid, tmpl):
    """Assign a pillar to every slot (round-level distribution) and a format to
    every slot (weekly distribution, repeated each week)."""
    total = len(grid)
    ppd = tmpl["posts_per_day"]

    pillar_seq = even_spread(list(tmpl["pillar_distribution"].items()))
    if len(pillar_seq) != total:
        raise SystemExit(
            f"pillar_distribution sums to {len(pillar_seq)} but period has {total} slots")

    slots_per_week = ppd * 7
    weekly_fmt = even_spread(list(tmpl["format_distribution_weekly"].items()))
    if len(weekly_fmt) != slots_per_week:
        raise SystemExit(
            f"format_distribution_weekly sums to {len(weekly_fmt)} but a week has "
            f"{slots_per_week} slots")

    for i, slot in enumerate(grid):
        slot["pillar_code"] = pillar_seq[i]
        slot["format"] = weekly_fmt[i % slots_per_week]
    return grid


def _plan_with_template(cfg, tmpl_name, tmpl, round_id=None, label=None, format_mix=None,
                        starts_on=None, proposal_id=None, principal=None, idempotency_key=None):
    """Core planning: walk cursors, persist round+slots+lens_history+cursor+audit. Returns
    (round_id, n_slots). Shared by the API `plan_round_api` (the CLI `plan` keeps its own body).

    #377 — when `proposal_id` is given, the governed run-mix proposal is verified, locked and CONSUMED
    and its immutable recommendation snapshot is pinned INSIDE THIS TRANSACTION, so no accepted
    proposal can ever be consumed or recorded outside the transaction that creates the run (Codex
    ruling 3). Omitting it preserves V1's proposal-less creation byte-for-byte: the run is created
    exactly as before and truthfully has no recommendation snapshot (ruling 2) — nothing is inferred
    or backfilled for it.

    #276 — eligibility for a new run resolves from the CURRENT baseline eligibility policy (fail-closed),
    NOT from a hard-coded allowlist or content_format.active. An explicit `format_mix` is validated
    against that set and allocated exactly; a legacy no-mix caller uses the managed weekly weights of the
    eligible formats. After planning, an IMMUTABLE round policy snapshot is pinned (append-only)."""
    eng = cfg.get("engine", {})
    carry = eng.get("carry_cursor_across_rounds", True)
    enforce_rotation = eng.get("enforce_lens_rotation", True)
    conn = db_connect(); conn.autocommit = False
    cur = conn.cursor()
    round_id = round_id or next_round_id(cur)
    cur.execute("SELECT 1 FROM round WHERE round_id=%s", (round_id,))
    if cur.fetchone():
        raise SystemExit(f"round {round_id} already exists")
    pillar_hcs, hcs_lenses, hcs_name, lens_name, lens_hook = load_methodology(cur)
    if not pillar_hcs:
        # No methodology to plan against: without this guard the slot loop KeyErrors on
        # walkers[pillar_code]. Fail with an actionable reason (the API maps it to a clean 500).
        conn.close()
        raise SystemExit("methodology catalogue is empty — seed HCS before planning a round")
    cursors = load_cursors(cur) if carry else {}
    hist = load_lens_history(cur)
    # #276 — bootstrap the baseline policy (create-only) then resolve eligibility from it (fail-closed).
    _engine.ensure_baseline_policy(conn)
    elig = _engine.resolve_run_eligibility(cur)
    policy = elig["policy"]
    eligible = elig["eligible"]
    eligible_names = [e["name"] for e in eligible]
    version_by_name = {e["name"]: e["version_id"] for e in eligible}
    total = tmpl["period_len_days"] * tmpl["posts_per_day"]
    # #276 P1a — resolved policy + an exact caller-supplied mix are the ONLY new-run planning path.
    # A no-mix request is rejected (never silently allocated from weekly_count / a fixed default).
    if format_mix is None:
        conn.close()
        raise ValueError("format_mix is required: an exact count per baseline-eligible framework "
                         "(no weekly_count / default-allocation fallback is applied)")
    # #377 phase 1+2 — fence and generation checks BEFORE any durable run state exists, and before the
    # planner's own validation: a run whose duration or posts/day differs from what was proposed must
    # be told THAT, not a downstream "the mix does not sum" that describes a consequence rather than
    # the cause. A refusal here raises with nothing written; the connection is rolled back and closed
    # so no lock is left behind.
    rec_cur = rec_row = rec_req_digest = None
    if proposal_id is not None:
        import run_mix as _run_mix  # local: run_mix imports scale_distribution from THIS module
        rec_cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            outcome = _run_mix.begin_binding(
                rec_cur, proposal_id=proposal_id, principal=principal,
                days=tmpl["period_len_days"], posts_per_day=tmpl["posts_per_day"],
                starts_on=starts_on, format_mix=format_mix, label=label,
                idempotency_key=idempotency_key)
            if outcome[0] == "replay":
                # This exact request already produced a run: converge on it rather than creating a
                # second one. Nothing is written, so the transaction is simply discarded.
                bound = outcome[1]["round_id"]
                rec_cur.execute("SELECT count(*) AS n FROM slot WHERE round_id=%s", (bound,))
                n_existing = rec_cur.fetchone()["n"]
                conn.rollback(); conn.close()
                return bound, n_existing
            _, rec_row, rec_req_digest = outcome
            _run_mix.verify_generations(rec_cur, rec_row, elig)
        except Exception:
            conn.rollback(); conn.close()
            raise
    # The planner's own validation is unchanged and still binding: a proposal never makes a mix valid.
    # The rollback/close is load-bearing now that a fence may be locked FOR UPDATE by this transaction
    # — leaking the connection here would hold that row lock until GC and block the operator's next
    # attempt on the same proposal.
    try:
        validate_format_mix(format_mix, eligible, total)
    except Exception:
        conn.rollback(); conn.close(); raise
    resolved_mix = {n: int(format_mix.get(n, 0)) for n in eligible_names}
    try:
        grid = assign_pillars_formats_exact(build_grid(round_id, tmpl), tmpl, resolved_mix, eligible_names)
    except Exception:
        # Explicit, not GC-dependent: a failure between fence verification and the first durable write
        # must leave the proposal pending and nothing created.
        conn.rollback(); conn.close(); raise
    walkers = {p: PillarWalker(p, ordered, *cursors.get(p, (None, 1)))
               for p, ordered in pillar_hcs.items()}
    new_lens_history = {}
    for slot in grid:
        hcs_id, cycle = walkers[slot["pillar_code"]].next()
        lens = pick_lens(hcs_id, cycle, hcs_lenses[hcs_id], hist, enforce_rotation)
        slot.update(hcs_id=hcs_id, cycle_no=cycle, lens=lens, hook_type=lens_hook.get(lens))
        new_lens_history[(hcs_id, cycle)] = lens
    cur.execute(
        # #304 — starts_on is the run's authoritative absolute placement, written in the SAME
        # transaction as the round and its slots. None is a truthful "unplaced" (V1's form supplies
        # no placement); it is never defaulted to today, and never derived from created_at.
        """INSERT INTO round (round_id, label, period_len_days, posts_per_day, post_times,
                              pillar_distribution, format_distribution, status, starts_on)
           VALUES (%s,%s,%s,%s,%s,%s,%s,'planned',%s)""",
        (round_id, label or default_round_label(round_id, tmpl["period_len_days"], tmpl["posts_per_day"]), tmpl["period_len_days"],
         tmpl["posts_per_day"], Json(tmpl["post_times"]),
         Json(tmpl["pillar_distribution"]), Json(resolved_mix), starts_on))
    # #276 — pin the immutable resolved policy snapshot (append-only planning evidence). selected_version
    # IDs are the baseline policy's eligible versions for the formats this run actually allocated.
    selected_version_ids = {n: version_by_name[n] for n, c in resolved_mix.items()
                            if c > 0 and n in version_by_name}
    _engine.pin_round_snapshot(
        cur, round_id, policy, selected_version_ids, resolved_mix,
        _engine._active_version_id(cur, "methodology_version", "methodology_id"),
        _engine._active_version_id(cur, "workflow_version", "workflow_id"))
    # #377 phase 3 — the recommendation snapshot and the fence consumption ride the SAME transaction as
    # the round it describes. If anything below fails, both vanish with the run.
    if rec_row is not None:
        import run_mix as _run_mix
        try:
            _run_mix.bind_snapshot(rec_cur, row=rec_row, round_id=round_id, submitted_mix=resolved_mix,
                                   principal=principal, request_digest=rec_req_digest,
                                   idempotency_key=idempotency_key)
        except Exception:
            # The round row is already INSERTed in this transaction. Rolling back here is what makes
            # "no run without its snapshot" true rather than merely intended.
            conn.rollback(); conn.close(); raise
    psycopg2.extras.execute_batch(cur,
        """INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, format,
                             hcs_id, lens, hook_type, cycle_no, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RESERVED')""",
        [(s["slot_id"], round_id, s["day"], s["time_uae"], s["pillar_code"], s["format"],
          s["hcs_id"], s["lens"], s["hook_type"], s["cycle_no"]) for s in grid])
    psycopg2.extras.execute_batch(cur,
        """INSERT INTO lens_history (hcs_id, cycle_no, lens) VALUES (%s,%s,%s)
           ON CONFLICT (hcs_id, cycle_no) DO UPDATE SET lens=EXCLUDED.lens""",
        [(h, c, l) for (h, c), l in new_lens_history.items()])
    for pillar_code, w in walkers.items():
        cur.execute(
            """INSERT INTO hcs_cursor (pillar_code, last_hcs_id, cycle_no) VALUES (%s,%s,%s)
               ON CONFLICT (pillar_code) DO UPDATE
                 SET last_hcs_id=EXCLUDED.last_hcs_id, cycle_no=EXCLUDED.cycle_no""",
            (pillar_code, w.last_emitted, w.cycle))
    cur.execute("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                   VALUES ('round', %s, 'planned', 'planner', %s)""",
                (round_id, Json({"template": tmpl_name, "slots": len(grid)})))
    psycopg2.extras.execute_batch(cur,
        """INSERT INTO audit_log (entity, entity_id, action, actor, detail)
           VALUES ('slot', %s, 'status_change', 'planner', %s)""",
        [(s["slot_id"], Json({"from": "EMPTY", "to": "RESERVED", "hcs_id": s["hcs_id"],
                              "cycle_no": s["cycle_no"], "lens": s["lens"]})) for s in grid])
    # #292 — a NEW round is governed FROM BIRTH. Generation 1 is created inside the SAME transaction
    # as the round and its slots, so no committed round can exist without its governed mapping, and
    # there is no second connection that could fail after the round is already durable.
    # initialize_schedule_mapping commits this transaction on success and rolls it back on failure,
    # so a mapping error discards the whole run rather than leaving it half-governed. This covers the
    # API path; the CLI `plan()` below is a SEPARATE creation path with its own transaction and is
    # covered by the same step there. Pre-#292 rounds are still never touched: this runs only for a
    # round created in this transaction.
    try:
        _engine.initialize_schedule_mapping(conn, round_id, actor="system", cfg=cfg)
        # Authoritative when initialize_schedule_mapping returned early (nothing to map); a harmless
        # no-op when it already committed this transaction.
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return round_id, len(grid)


def plan_round_api(cfg: dict, days: int, posts_per_day: int, label=None, format_mix=None,
                   starts_on=None, proposal_id=None, principal=None, idempotency_key=None) -> dict:
    """Plan a fresh round scaled to days × posts_per_day. Returns {round_id, total}.

    #276 — eligibility resolves from the current baseline policy; `format_mix` (optional) is validated
    against that set and pins the exact per-run selection. `format_mix=None` uses the eligible formats'
    managed weekly weights (legacy planner behaviour, now policy-gated).

    #377 — `proposal_id` (with the signed `principal`, and an optional `idempotency_key`) binds a
    governed recommendation proposal to this creation, atomically. Omitting it is the unchanged legacy
    path."""
    if days < 1 or posts_per_day < 1:
        raise ValueError("days and posts_per_day must be >= 1")
    tmpl_name, base = get_template(cfg, None)
    et = effective_template(base, days, posts_per_day)
    rid, n = _plan_with_template(cfg, tmpl_name, et, label=label, format_mix=format_mix,
                                starts_on=starts_on, proposal_id=proposal_id, principal=principal,
                                idempotency_key=idempotency_key)
    return {"round_id": rid, "total": n,
            "starts_on": starts_on.isoformat() if hasattr(starts_on, "isoformat") else starts_on}


def baseline_eligibility_api(cfg: dict) -> dict:
    """#276 read/selection path (consumed by #271): the current baseline eligibility policy + its
    eligible frameworks, resolved from the versioned policy seam. Fails closed if no current policy."""
    conn = db_connect()
    try:
        _engine.ensure_baseline_policy(conn)
        cur = conn.cursor()
        return _engine.resolve_run_eligibility(cur)
    finally:
        conn.close()


def plan(args):
    cfg = load_config(Path(args.config))
    tmpl_name, tmpl = get_template(cfg, args.template)
    engine = cfg.get("engine", {})
    carry = engine.get("carry_cursor_across_rounds", True)
    enforce_rotation = engine.get("enforce_lens_rotation", True)

    conn = db_connect()
    conn.autocommit = False
    cur = conn.cursor()

    round_id = args.round_id or next_round_id(cur)
    cur.execute("SELECT 1 FROM round WHERE round_id=%s", (round_id,))
    if cur.fetchone():
        raise SystemExit(f"round {round_id} already exists")

    pillar_hcs, hcs_lenses, hcs_name, lens_name, lens_hook = load_methodology(cur)
    cursors = load_cursors(cur) if carry else {}
    hist = load_lens_history(cur)
    tmpl = apply_managed_format_distribution(cur, tmpl)

    cursor_before = {p: cursors.get(p, (None, 1)) for p in pillar_hcs}

    # one walker per pillar, continuing from the persisted cursor
    walkers = {}
    for pillar_code, ordered in pillar_hcs.items():
        last, cyc = cursors.get(pillar_code, (None, 1))
        walkers[pillar_code] = PillarWalker(pillar_code, ordered, last, cyc)

    grid = assign_pillars_formats(build_grid(round_id, tmpl), tmpl)

    # walk: assign HCS (cursor) + lens (rotation) + hook (lens default)
    new_lens_history = {}     # (hcs_id, cycle) -> lens, written this round
    for slot in grid:
        hcs_id, cycle = walkers[slot["pillar_code"]].next()
        lens = pick_lens(hcs_id, cycle, hcs_lenses[hcs_id], hist, enforce_rotation)
        slot["hcs_id"] = hcs_id
        slot["cycle_no"] = cycle
        slot["lens"] = lens
        slot["hook_type"] = lens_hook.get(lens)
        new_lens_history[(hcs_id, cycle)] = lens

    # ---- persist (atomic) ------------------------------------------------
    cur.execute(
        """INSERT INTO round (round_id, label, period_len_days, posts_per_day,
                              post_times, pillar_distribution, format_distribution, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,'planned')""",
        (round_id, args.label or default_round_label(round_id, tmpl["period_len_days"], tmpl["posts_per_day"]),
         tmpl["period_len_days"], tmpl["posts_per_day"], Json(tmpl["post_times"]),
         Json(tmpl["pillar_distribution"]), Json(tmpl["format_distribution_weekly"])),
    )

    psycopg2.extras.execute_batch(cur,
        """INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, format,
                             hcs_id, lens, hook_type, cycle_no, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RESERVED')""",
        [(s["slot_id"], round_id, s["day"], s["time_uae"], s["pillar_code"],
          s["format"], s["hcs_id"], s["lens"], s["hook_type"], s["cycle_no"])
         for s in grid])

    # lens_history: idempotent on (hcs_id, cycle_no)
    psycopg2.extras.execute_batch(cur,
        """INSERT INTO lens_history (hcs_id, cycle_no, lens) VALUES (%s,%s,%s)
           ON CONFLICT (hcs_id, cycle_no) DO UPDATE SET lens=EXCLUDED.lens""",
        [(h, c, l) for (h, c), l in new_lens_history.items()])

    # advance the cursor per pillar
    for pillar_code, w in walkers.items():
        cur.execute(
            """INSERT INTO hcs_cursor (pillar_code, last_hcs_id, cycle_no)
               VALUES (%s,%s,%s)
               ON CONFLICT (pillar_code) DO UPDATE
                 SET last_hcs_id=EXCLUDED.last_hcs_id, cycle_no=EXCLUDED.cycle_no""",
            (pillar_code, w.last_emitted, w.cycle))

    # audit: round planned + every slot reserved
    cur.execute(
        """INSERT INTO audit_log (entity, entity_id, action, actor, detail)
           VALUES ('round', %s, 'planned', 'planner', %s)""",
        (round_id, Json({"template": tmpl_name, "slots": len(grid)})))
    psycopg2.extras.execute_batch(cur,
        """INSERT INTO audit_log (entity, entity_id, action, actor, detail)
           VALUES ('slot', %s, 'status_change', 'planner', %s)""",
        [(s["slot_id"], Json({"from": "EMPTY", "to": "RESERVED",
                              "hcs_id": s["hcs_id"], "cycle_no": s["cycle_no"],
                              "lens": s["lens"]})) for s in grid])

    # #292 — governed from birth applies to EVERY path that creates a round, including this CLI one:
    # a round planned here is as new as one planned through the API, so it gets mapping generation 1
    # in the SAME transaction. Without this the CLI would mint rounds that are ungoverned at birth
    # and then indistinguishable from genuine pre-#292 rounds (legacy by absence) — a silent
    # contradiction of the guarantee. Failure rolls the whole round back rather than committing a
    # half-governed run.
    try:
        _engine.initialize_schedule_mapping(conn, round_id, actor="system", cfg=cfg)
        # Authoritative when initialize_schedule_mapping returned early (nothing to map); a harmless
        # no-op when it already committed this transaction.
        conn.commit()
    except Exception:
        conn.rollback()
        cur.close(); conn.close()
        raise

    print_calendar(round_id, tmpl_name, tmpl, grid, hcs_name, lens_name,
                   cursor_before, walkers)
    verify_mix(grid, tmpl)

    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def print_calendar(round_id, tmpl_name, tmpl, grid, hcs_name, lens_name,
                   cursor_before, walkers):
    ppd = tmpl["posts_per_day"]
    slots_per_week = ppd * 7
    print(f"\n{'='*100}\nROUND {round_id}  —  template '{tmpl_name}'  "
          f"({tmpl['period_len_days']} days, {ppd}/day = {len(grid)} slots)\n{'='*100}")

    hdr = f"{'slot_id':<13} {'time':<6} {'pillar':<17} {'format':<20} " \
          f"{'hcs':<5} {'cyc':<3} {'lens':<5} {'hook':<14} {'HCS name'}"
    for w in range(0, len(grid), slots_per_week):
        week = grid[w:w + slots_per_week]
        print(f"\n--- Week {w // slots_per_week + 1} "
              f"(days {week[0]['day']}-{week[-1]['day']}) ---")
        print(hdr)
        print("-" * len(hdr))
        for s in week:
            print(f"{s['slot_id']:<13} {s['time_uae']:<6} {s['pillar_code']:<17} "
                  f"{s['format']:<20} {s['hcs_id']:<5} {s['cycle_no']:<3} "
                  f"{s['lens']:<5} {str(s['hook_type']):<14} {hcs_name.get(s['hcs_id'],'')}")

    print(f"\n--- Cursor advance (per pillar) ---")
    print(f"{'pillar':<17} {'before (last/cycle)':<24} {'after (last/cycle)'}")
    for pillar_code, wk in walkers.items():
        b_last, b_cyc = cursor_before[pillar_code]
        print(f"{pillar_code:<17} {str(b_last)+' / '+str(b_cyc):<24} "
              f"{wk.last_emitted} / {wk.cycle}")


def verify_mix(grid, tmpl):
    print(f"\n--- Mix verification ---")
    ok = True

    # pillar totals across the round
    pc = {}
    for s in grid:
        pc[s["pillar_code"]] = pc.get(s["pillar_code"], 0) + 1
    for pillar, want in tmpl["pillar_distribution"].items():
        got = pc.get(pillar, 0)
        flag = "OK" if got == want else "MISMATCH"
        ok &= got == want
        print(f"  pillar {pillar:<17} want {want:>2}  got {got:>2}  [{flag}]")

    # format totals per week
    ppd = tmpl["posts_per_day"]
    slots_per_week = ppd * 7
    weeks = len(grid) // slots_per_week
    for wk in range(weeks):
        fc = {}
        for s in grid[wk * slots_per_week:(wk + 1) * slots_per_week]:
            fc[s["format"]] = fc.get(s["format"], 0) + 1
        for fmt, want in tmpl["format_distribution_weekly"].items():
            got = fc.get(fmt, 0)
            if got != want:
                ok = False
                print(f"  week {wk+1} format {fmt:<20} want {want} got {got}  [MISMATCH]")
    if ok:
        print(f"  weekly format mix: all {weeks} weeks match "
              f"{tmpl['format_distribution_weekly']}  [OK]")
    print(f"\nRESULT: {'ALL CHECKS PASSED' if ok else 'CHECKS FAILED'}")
    if not ok:
        sys.exit(1)


def verify(args):
    conn = db_connect()
    cur = conn.cursor()

    print(f"\n{'='*70}\nHCS CURSOR STATE (per pillar)\n{'='*70}")
    cur.execute("SELECT pillar_code, last_hcs_id, cycle_no FROM hcs_cursor "
                "ORDER BY pillar_code")
    print(f"{'pillar':<17} {'last_hcs_id':<12} {'cycle_no'}")
    for p, last, cyc in cur.fetchall():
        print(f"{p:<17} {str(last):<12} {cyc}")

    # lens rotation: lens per cycle for each HCS; flag any consecutive repeat
    cur.execute("SELECT hcs_id, cycle_no, lens FROM lens_history "
                "ORDER BY hcs_id, cycle_no")
    by_hcs = {}
    for h, c, l in cur.fetchall():
        by_hcs.setdefault(h, []).append((c, l))

    print(f"\n{'='*70}\nLENS ROTATION (lens used per cycle, per HCS)\n{'='*70}")
    violations = 0
    repeated = []
    for h in sorted(by_hcs, key=lambda x: (len(x), x)):
        seq = by_hcs[h]
        if len(seq) > 1:
            repeated.append(h)
        trail = "  ".join(f"c{c}:{l}" for c, l in seq)
        bad = any(seq[i][1] == seq[i - 1][1] for i in range(1, len(seq)))
        if bad:
            violations += 1
        print(f"  {h:<5} {trail}{'   <-- REPEAT LENS' if bad else ''}")

    # HCS that appear in the two most recent rounds = the cross-round proof
    cur.execute("SELECT round_id FROM round ORDER BY created_at DESC, round_id DESC LIMIT 2")
    rounds = [r for (r,) in cur.fetchall()]
    if len(rounds) == 2:
        r_new, r_old = rounds[0], rounds[1]
        cur.execute("""SELECT DISTINCT a.hcs_id FROM slot a
                       JOIN slot b ON a.hcs_id=b.hcs_id
                       WHERE a.round_id=%s AND b.round_id=%s ORDER BY a.hcs_id""",
                    (r_old, r_new))
        shared = [h for (h,) in cur.fetchall()]
        print(f"\n{'='*70}\nCROSS-ROUND PROOF — HCS appearing in both {r_old} and {r_new}\n{'='*70}")
        for h in shared:
            cur.execute("""SELECT s.round_id, s.lens, count(*) FROM slot s
                           WHERE s.hcs_id=%s AND s.round_id IN (%s,%s)
                           GROUP BY s.round_id, s.lens ORDER BY s.round_id, s.lens""",
                        (h, r_old, r_new))
            rows = cur.fetchall()
            summary = "  ".join(f"{rid}:{lens}(x{n})" for rid, lens, n in rows)
            print(f"  {h:<5} {summary}")

    print(f"\nRESULT: lens rotation violations (consecutive-cycle repeats): {violations}")
    cur.close()
    conn.close()
    if violations:
        sys.exit(1)


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Tanaghom Planner (M2)")
    ap.add_argument("mode", nargs="?", default="plan", choices=["plan", "verify"])
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--template", default=None, help="calendar template name")
    ap.add_argument("--round-id", default=None, help="override round id (default: next Rn)")
    ap.add_argument("--label", default=None)
    args = ap.parse_args()
    (plan if args.mode == "plan" else verify)(args)


if __name__ == "__main__":
    main()
