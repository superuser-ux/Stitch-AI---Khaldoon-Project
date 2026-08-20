"""#342 — seed/reset the SYNTHETIC V2 schedule acceptance lane.

WHY THIS EXISTS. The corrected FullCalendar preview proved geometry against a database carrying
~102 legacy synthetic runs. That is not client data, but it is not credible acceptance evidence
either: a human cannot read a coherent schedule out of a hundred unrelated leftovers, and no
screenshot of it earns the claim "a reviewer can inspect this". This seeds the smallest scenario
that exercises every placement state a reviewer must be able to see, and nothing else.

FOUR SCENARIOS, one per placement state the UI must distinguish:
  ACC342-MULTI  placed, multi-day window   -> a run that spans days on the grid
  ACC342-ONEDAY placed, single-day window  -> the degenerate window, where off-by-one shows up
  ACC342-PLAN   unplaced (planning)        -> stated as unplaced, never drawn at a guessed date
  ACC342-FROZEN placed, downstream-advanced-> placement is refused by the server

The FROZEN case is built by advancing ONE slot past the schedule stage (TOPIC_PROPOSED). That
satisfies the first disjunct of the server's `_downstream_advanced` predicate — "its lifecycle left
the schedule stage" — so the refusal comes from the real governed predicate rather than from a flag
this script invented. Nothing here teaches the server a new rule.

AUTHORITY BOUNDARY. This writes fixture ROWS only. It sets no policy, no configuration generation,
no feature flag, and no runtime default; it opens the same `schedule_review` gate the product opens;
and placement is written through the same `round.starts_on` column the governed command owns. It is
evidence, never authority.

ISOLATION. It writes wherever `DB_NAME` points, so it MUST be run against a dedicated lane database
(see docs/v2-transition/acceptance-lane-342.md). It deliberately does not create or select a
database itself: a seed script that silently creates its own target is exactly how a "safe" fixture
ends up in a shared one.

RESET. `teardown()` removes every row this script can create, scoped to the ACC342- prefix, so a
re-run is idempotent and leaves no residue. Run:

  docker exec -w /work <gateapi-container> python gates/acc342_lane_seed.py
"""
import os
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(__file__))
import engine  # noqa: E402

PREFIX = "ACC342"
TENANT = "acc342"

MULTI = f"{PREFIX}-MULTI"
ONEDAY = f"{PREFIX}-ONEDAY"
PLAN = f"{PREFIX}-PLAN"
FROZEN = f"{PREFIX}-FROZEN"

# Fixed dates, never "today": a lane that drifts with the wall clock cannot be re-inspected next
# week and cannot be compared against an earlier screenshot. The caller may override the anchor to
# re-seed the scenario into a month they are looking at.
ANCHOR = os.environ.get("ACC342_ANCHOR", "2026-07-13")   # a Monday


def _anchor_plus(days: int) -> str:
    import datetime
    return (datetime.date.fromisoformat(ANCHOR) + datetime.timedelta(days=days)).isoformat()


# (round_id, label, period_len_days, starts_on, slots) — slots are (day, time_uae, format)
SCENARIOS = [
    (MULTI, "Acceptance — placed multi-day", 4, _anchor_plus(1),
     [(1, "09:00", "Hero Reel"), (2, "13:00", "Carousel"), (3, "09:00", "Hero Reel"), (4, "17:00", "Carousel")]),
    (ONEDAY, "Acceptance — placed one-day", 1, _anchor_plus(2),
     [(1, "10:00", "Hero Reel")]),
    (PLAN, "Acceptance — unplaced planning", 3, None,
     [(1, "09:00", "Hero Reel"), (2, "09:00", "Carousel"), (3, "09:00", "Hero Reel")]),
    (FROZEN, "Acceptance — placement frozen", 2, _anchor_plus(3),
     [(1, "09:00", "Hero Reel"), (2, "15:00", "Carousel")]),
]

ALL_RIDS = [s[0] for s in SCENARIOS]


def teardown(conn):
    """Remove every row this script can create. Ordered child-first so FKs never block the delete,
    and scoped to the ACC342- prefix so it can never widen into unrelated data even if it is run
    (wrongly) against a populated database."""
    cur = conn.cursor()
    cur.execute("SELECT slot_id FROM slot WHERE round_id = ANY(%s)", (ALL_RIDS,))
    slot_ids = [r[0] for r in cur.fetchall()]

    cur.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t "
                "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id = ANY(%s))", (ALL_RIDS,))
    if slot_ids:
        for tbl in ("slot_approval", "slot_review", "directive", "asset", "topic", "script"):
            cur.execute(f"DELETE FROM {tbl} WHERE slot_id = ANY(%s)", (slot_ids,))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE %s", (f"{PREFIX}-%",))
    cur.execute("DELETE FROM slot  WHERE round_id = ANY(%s)", (ALL_RIDS,))
    cur.execute("DELETE FROM round WHERE round_id = ANY(%s)", (ALL_RIDS,))
    conn.commit()


def seed(conn):
    cur = conn.cursor()
    for rid, label, period_len, starts_on, slots in SCENARIOS:
        cur.execute(
            """INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                                  pillar_distribution,format_distribution,status,tenant_id,starts_on)
               VALUES (%s,%s,%s,%s,'["09:00"]','{}','{}','planning',%s,%s)""",
            (rid, label, period_len, max(1, len(slots) // max(1, period_len)), TENANT, starts_on))
        for i, (day, t, fmt) in enumerate(slots, start=1):
            cur.execute(
                """INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                                     hook_type,status,cycle_no,format,tenant_id)
                   VALUES (%s,%s,%s,%s,'P1_SELF','1.1','L1','Painful Truth','RESERVED',1,%s,%s)""",
                (f"{rid}-S{i}", rid, day, t, fmt, TENANT))
    conn.commit()

    # FROZEN only: advance ONE slot past the schedule stage so the SERVER's own predicate freezes
    # placement. Done after the clean insert so the difference between this run and the others is
    # exactly one status value — the thing under demonstration, and nothing else.
    cur.execute("UPDATE slot SET status='TOPIC_PROPOSED' WHERE slot_id=%s", (f"{FROZEN}-S1",))
    conn.commit()


def verify(conn) -> int:
    """Print the shape a reviewer should see, and return the number of ACC342 rounds. Printing is
    not proving, so this ASSERTS the placement/freeze split rather than only displaying it."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT round_id, starts_on, period_len_days FROM round "
                "WHERE round_id = ANY(%s) ORDER BY round_id", (ALL_RIDS,))
    rounds = cur.fetchall()
    placed = [r for r in rounds if r["starts_on"]]
    unplaced = [r for r in rounds if not r["starts_on"]]
    assert len(rounds) == 4, f"expected 4 ACC342 rounds, found {len(rounds)}"
    assert len(placed) == 3 and len(unplaced) == 1, f"expected 3 placed + 1 unplaced, got {len(placed)}/{len(unplaced)}"

    cur.execute("SELECT count(*) AS n FROM slot WHERE round_id=%s AND status='TOPIC_PROPOSED'", (FROZEN,))
    assert cur.fetchone()["n"] == 1, "FROZEN run must have exactly one downstream-advanced slot"

    for r in rounds:
        print(f"  {r['round_id']:<16} starts_on={str(r['starts_on'] or '—'):<12} period={r['period_len_days']}d")
    return len(rounds)


def main():
    conn = engine.db_connect()
    dbname = conn.get_dsn_parameters().get("dbname", "?")
    # Refuse the shared/default database outright. The lane is only credible if it CANNOT be seeded
    # into `tanaghom` by a forgotten env var, so this is a hard refusal rather than a warning.
    if dbname in ("tanaghom", "postgres"):
        raise SystemExit(
            f"refusing to seed the ACC342 acceptance lane into '{dbname}'. "
            "Point DB_NAME at a dedicated lane database (see docs/v2-transition/acceptance-lane-342.md).")

    teardown(conn)
    seed(conn)
    for rid in ALL_RIDS:
        engine.open_gate(conn, "schedule_review", round_id=rid, actor="acc342")
    print(f"seeded ACC342 acceptance lane into '{dbname}' (anchor {ANCHOR}):")
    n = verify(conn)
    print(f"  {n} synthetic rounds — reset by re-running this script.")
    conn.close()


if __name__ == "__main__":
    main()
