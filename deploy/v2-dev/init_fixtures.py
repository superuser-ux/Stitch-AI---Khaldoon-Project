"""#414 — EXPLICIT synthetic-fixture initializer for the isolated developer `v2-dev-389` lane.

This is the deliberate, evidenced counterpart to the now-read-only ordinary Gate API startup
(deploy/v2-dev/init_db.py). It is NEVER run by the container entrypoint; an operator runs it on purpose,
e.g.:

    docker exec tanaghom-v2-dev-gateapi-1 python /work/deploy/v2-dev/init_fixtures.py --confirm

Contract (matches the governed configuration-generation rule — create missing baseline records only,
never overwrite operator-owned configuration):

  * BOUNDED TO THE SYNTHETIC LANE. It refuses (non-zero, no writes) unless the environment declares the
    synthetic developer lane (`TANAGHOM_LANE_ID=v2-dev-389` AND `TANAGHOM_DATA_CLASS=synthetic`) and the
    caller passes the explicit `--confirm` flag. It never runs implicitly.
  * IDEMPOTENT / CREATE-MISSING-ONLY. Each step is check-then-act: the methodology catalogue is loaded
    only if absent; the RE2E fixture round is inserted only if absent; the fixture review gate is opened
    only if not already open. Nothing existing is overwritten or deleted (no teardown, no DO UPDATE of a
    present catalogue), so a rerun against a fully-initialized database makes ZERO database writes.
  * EVIDENCED, REVISION-BOUND, FAIL-CLOSED. A persisted, candidate-local FIXTURE marker (separate from the
    ownership marker) is the fixture GENERATION IDENTITY: the fixture GENERATION + the SOURCE REVISION (the
    baked build SHA) + the DATABASE IDENTITY — no secrets. A no-op requires ALL THREE to match (#414
    correction 4 — the source revision is part of the match, not merely recorded). When the marker does not
    fully match, the initializer NEVER re-attests arbitrary pre-existing data (#414 correction 5):
      - marker present but generation/db_identity differ  -> UNRECOGNIZED ownership: FAIL CLOSED (mirrors
        init_db.py's unrecognized-non-empty-DB refusal; run the documented teardown + recreate);
      - no marker but the lane already holds ANY fixture-related data (catalogue, the RE2E round, OR its
        dependent slots/topics/RE2E-targeted gates) -> attest ONLY if it fully validates as the COMPLETE
        expected synthetic fixture (complete canon catalogue + exact RE2E round/slots + the EXACT committed
        RE2E topic set, refusing missing/extra/substituted/duplicated topics + open RE2E-targeted gate),
        otherwise FAIL CLOSED;
      - fresh slate, or a same-generation/same-identity SOURCE-REVISION refresh -> create-missing, then
        FULLY validate the complete expected set BEFORE (re)writing the marker.
    The marker lives on the same candidate-owned volume as the ownership marker, so it survives ordinary
    gate recreation.

Ordinary startup (init_db.py) writing zero rows + this being the only fixture writer is what makes a
literal persisted-data fingerprint (including audit_log count and max id) valid for #412/#413.
"""
import os
import subprocess
import sys

# /work/deploy/v2-dev/init_fixtures.py -> /work ; put the script dir (for the init_db sibling), /work, and
# /work/gates on the path so the committed engine + fixture helpers import exactly as they do at runtime.
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
for _p in (HERE, REPO, os.path.join(REPO, "gates")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import init_db   # noqa: E402  (sibling module: _connect, _db_identity helpers reused verbatim)
import engine    # noqa: E402  (gates/engine.py — open_gate, load_config)
import e2e_seed  # noqa: E402  (gates/e2e_seed.py — RID + create-missing seed(); NOT its teardown main())

GENERATION = "v2-dev-389-synthetic-fixtures-v1"
LANE_ID = "v2-dev-389"
FIXTURE_MARKER_PATH = os.environ.get(
    "TANAGHOM_V2DEV_FIXTURE_MARKER", "/var/lib/tanaghom-acc/v2dev-fixture-marker")

# Complete expected synthetic catalogue — mirrors loader/load_methodology.py's end-of-load count
# assertions (the catalogue's single source of truth). Used to VALIDATE that the catalogue is genuinely
# complete (not merely "count > 0") before a missing/mismatched marker is (re)written — #414 correction 5.
EXPECTED_CANON_COUNTS = {"pillar": 5, "hcs": 42, "lens": 5, "hook_type": 5, "format": 4}
EXPECTED_METHODOLOGY_KEY = "tanaghom_core"


def _fail(msg, code=2):
    print(f"[fixture-init] REFUSED: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def _guard(argv):
    """Bounded to the explicit synthetic developer lane — refuse (no writes) otherwise."""
    lane = os.environ.get("TANAGHOM_LANE_ID", "")
    dclass = os.environ.get("TANAGHOM_DATA_CLASS", "")
    if lane != LANE_ID:
        _fail(f"bounded to the synthetic '{LANE_ID}' lane; TANAGHOM_LANE_ID='{lane}'")
    if dclass != "synthetic":
        _fail(f"bounded to synthetic data only; TANAGHOM_DATA_CLASS='{dclass}'")
    if "--confirm" not in argv:
        _fail("explicit --confirm is required (this initializer never runs implicitly)")


def _source_revision():
    for p in ("/work/BUILD_SHA", os.path.join(REPO, "BUILD_SHA")):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                v = fh.read().strip()
                if v:
                    return v
        except OSError:
            pass
    return (os.environ.get("TANAGHOM_GATEAPI_BUILD_SHA")
            or os.environ.get("TANAGHOM_GATEAPI_EXPECTED_SHA") or "unknown")


def _read_fixture_marker():
    try:
        with open(FIXTURE_MARKER_PATH, "r", encoding="utf-8") as fh:
            d = {}
            for line in fh.read().splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    d[k.strip()] = v.strip()
            if d.get("fixture_generation") and d.get("db_identity"):
                return d
    except OSError:
        pass
    return None


def _write_fixture_marker(generation, revision, db_identity):
    os.makedirs(os.path.dirname(FIXTURE_MARKER_PATH), exist_ok=True)
    tmp = FIXTURE_MARKER_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(f"fixture_generation: {generation}\n")
        fh.write(f"source_revision: {revision}\n")
        fh.write(f"db_identity: {db_identity}\n")
    os.replace(tmp, FIXTURE_MARKER_PATH)


def _ensure_methodology(conn):
    """Load the committed catalogue only if it is absent — never overwrite an existing catalogue."""
    cur = conn.cursor()
    cur.execute("SELECT to_regclass('public.methodology')")
    if cur.fetchone()[0] is not None:
        cur.execute("SELECT count(*) FROM methodology")
        if cur.fetchone()[0] > 0:
            cur.close()
            return "present"
    cur.close()
    path = os.path.join(REPO, "loader", "load_methodology.py")
    print("[fixture-init] methodology catalogue absent — loading committed catalogue", flush=True)
    subprocess.run([sys.executable, path], check=True, env=dict(os.environ))
    return "loaded"


def _ensure_fixture(conn):
    """Insert the RE2E synthetic fixture round only if it is absent (create-missing; no teardown)."""
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM round WHERE round_id=%s", (e2e_seed.RID,))
    exists = cur.fetchone() is not None
    cur.close()
    if exists:
        return "present"
    e2e_seed.seed(conn)   # committed create-only inserts (round + 3 slots + 3 topics); commits itself
    return "created"


def _ensure_fixture_gate(conn):
    """Open the RE2E topic-review gate only if one is not already open (avoids a gate_reused audit)."""
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM gate g WHERE g.stage='topic_review' AND g.status='open' AND EXISTS ("
        " SELECT 1 FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id "
        " WHERE t.gate_id=g.gate_id AND s.round_id=%s) LIMIT 1", (e2e_seed.RID,))
    exists = cur.fetchone() is not None
    cur.close()
    if exists:
        return "present"
    engine.open_gate(conn, "topic_review", round_id=e2e_seed.RID, actor="fixture-init")
    return "opened"


def _marker_matches(marker, generation, revision, db_identity):
    """#414 correction 4 — the marker is the fixture GENERATION IDENTITY: generation + database identity +
    SOURCE REVISION. A no-op requires all three to match. The previous implementation recorded the source
    revision but ignored it in the match, so a new build silently re-attested the prior generation."""
    return bool(marker
                and marker.get("fixture_generation") == generation
                and marker.get("db_identity") == db_identity
                and marker.get("source_revision") == revision)


def _fixture_state(cur):
    """Presence probe across EVERY fixture-related surface — methodology catalogue, the RE2E round, AND
    its dependent slots / topics / RE2E-targeted gates. #414 correction 5: the markerless fresh-slate
    path must be taken ONLY for a genuinely empty slate. Counting methodology + round alone left orphan
    fixture-adjacent rows (e.g. RE2E slots/topics/gates with no round row) undetected, so unexpected data
    could slip into create-missing; probing all surfaces routes any such data into full validation (which
    fails closed) instead."""
    state = {}
    cur.execute("SELECT count(*) FROM methodology")
    state["methodology"] = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM round WHERE round_id=%s", (e2e_seed.RID,))
    state["re2e_round"] = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM slot WHERE round_id=%s", (e2e_seed.RID,))
    state["re2e_slots"] = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM topic WHERE round_id=%s", (e2e_seed.RID,))
    state["re2e_topics"] = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM gate g WHERE EXISTS ("
                " SELECT 1 FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id "
                " WHERE t.gate_id=g.gate_id AND s.round_id=%s)", (e2e_seed.RID,))
    state["re2e_gates"] = cur.fetchone()[0]
    return state


def _validate_complete_fixture(cur):
    """#414 correction 5 — return a list of reasons the database is NOT the COMPLETE expected synthetic
    fixture; an empty list means fully validated. This is what lets a missing/mismatched marker be
    (re)written WITHOUT re-attesting arbitrary data — the alternative being to fail closed. A round-id-only
    and any-open-gate check is explicitly insufficient; this verifies the complete canon catalogue, the
    EXACT RE2E round/slots/topics, and an OPEN topic_review gate that TARGETS the RE2E round."""
    problems = []
    # (a) complete canon catalogue — EXACT counts (mirrors the loader's own end-of-load assertions).
    for tbl in sorted(EXPECTED_CANON_COUNTS):
        cur.execute(f"SELECT count(*) FROM {tbl}")
        got = cur.fetchone()[0]
        if got != EXPECTED_CANON_COUNTS[tbl]:
            problems.append(f"canon {tbl}: expected {EXPECTED_CANON_COUNTS[tbl]}, found {got}")
    # (b) the versioned methodology registry row with an active version.
    cur.execute("SELECT count(*) FROM methodology WHERE methodology_key=%s", (EXPECTED_METHODOLOGY_KEY,))
    if cur.fetchone()[0] != 1:
        problems.append(f"methodology registry row '{EXPECTED_METHODOLOGY_KEY}' not present exactly once")
    else:
        cur.execute("SELECT count(*) FROM methodology_version mv JOIN methodology m "
                    "ON m.methodology_id=mv.methodology_id "
                    "WHERE m.methodology_key=%s AND mv.status='active'", (EXPECTED_METHODOLOGY_KEY,))
        if cur.fetchone()[0] < 1:
            problems.append(f"methodology '{EXPECTED_METHODOLOGY_KEY}' has no active version")
    # (c) the RE2E round exists exactly once.
    cur.execute("SELECT count(*) FROM round WHERE round_id=%s", (e2e_seed.RID,))
    if cur.fetchone()[0] != 1:
        problems.append("RE2E round not present exactly once")
    # (d) EXACTLY the expected slots (id + pillar + hcs + format).
    expected_slots = {sid: (pillar, hcs, fmt) for sid, pillar, hcs, _angle, fmt in e2e_seed.SLOTS}
    cur.execute("SELECT slot_id, pillar_code, hcs_id, format FROM slot WHERE round_id=%s ORDER BY slot_id",
                (e2e_seed.RID,))
    got_slots = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
    if got_slots != expected_slots:
        problems.append(f"RE2E slots mismatch: expected {expected_slots}, found {got_slots}")
    # (d2) EXACTLY the committed RE2E topic set — identity (slot_id, hcs_id, text_ar) derived from
    # e2e_seed.SLOTS (text_ar is the committed topic_angle). #414 correction 5: this refuses missing,
    # extra, substituted, OR duplicated topics — `count(topic) >= 1` per slot accepted all of those.
    # Set equality catches missing/substituted/extra-identity; the row-count guard additionally catches a
    # duplicate topic (identical identity inserted twice, which a set would silently absorb).
    expected_topics = {(sid, hcs, angle) for sid, _pillar, hcs, angle, _fmt in e2e_seed.SLOTS}
    cur.execute("SELECT slot_id, hcs_id, text_ar FROM topic WHERE round_id=%s", (e2e_seed.RID,))
    got_rows = [tuple(r) for r in cur.fetchall()]
    got_topics = set(got_rows)
    if len(got_rows) != len(expected_topics) or got_topics != expected_topics:
        problems.append(
            f"RE2E topics mismatch: count={len(got_rows)} expected={len(expected_topics)} "
            f"missing={sorted(expected_topics - got_topics)} extra={sorted(got_topics - expected_topics)} "
            f"duplicates={len(got_rows) - len(got_topics)}")
    # (e) an OPEN topic_review gate that TARGETS a RE2E slot (target + state — not any-open-gate).
    cur.execute(
        "SELECT count(*) FROM gate g WHERE g.stage='topic_review' AND g.status='open' AND EXISTS ("
        " SELECT 1 FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id "
        " WHERE t.gate_id=g.gate_id AND s.round_id=%s)", (e2e_seed.RID,))
    if cur.fetchone()[0] < 1:
        problems.append("no OPEN topic_review gate targeting the RE2E round")
    return problems


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    _guard(argv)

    revision = _source_revision()
    conn = init_db._connect()
    try:
        cur = conn.cursor()
        # Schema must already be present — ordinary startup (init_db.py) applies committed schema+migrations
        # and writes the ownership marker. This initializer never applies schema; it only creates/validates
        # baseline fixture records on top of an initialized database.
        cur.execute("SELECT to_regclass('public.round')")
        if cur.fetchone()[0] is None:
            cur.close()
            _fail("database schema is not initialized — run ordinary startup (init_db.py) first", 3)
        db_identity = init_db._db_identity(cur)

        marker = _read_fixture_marker()

        # (1) Marker fully matches (generation + db_identity + source_revision) — proven no-op, zero writes.
        if _marker_matches(marker, GENERATION, revision, db_identity):
            cur.close()
            print(f"[fixture-init] NO-OP: fixtures already initialized "
                  f"(generation={GENERATION}, db_identity={db_identity}, "
                  f"source_revision={revision}); zero database writes.", flush=True)
            return 0

        # (2) Marker present but UNRECOGNIZED ownership (different generation or database identity): FAIL
        # CLOSED (mirrors init_db.py's unrecognized-non-empty-DB refusal). Never re-attest under a foreign
        # ownership marker — the operator must run the documented candidate-only teardown + recreate.
        if marker is not None and (marker.get("fixture_generation") != GENERATION
                                   or marker.get("db_identity") != db_identity):
            cur.close()
            _fail("fixture marker present but UNRECOGNIZED (generation/db_identity mismatch): "
                  f"marker_generation={marker.get('fixture_generation')!r} "
                  f"marker_db_identity={marker.get('db_identity')!r} vs current db_identity={db_identity!r}; "
                  "refusing to re-attest — run the documented candidate-only teardown and recreate with a "
                  "fresh volume.", 4)

        # (3) No marker at all: NEVER bless arbitrary data. If the lane already holds fixture data, attest
        # ONLY if it fully validates as the complete expected synthetic fixture; otherwise FAIL CLOSED. A
        # genuinely fresh slate falls through to create-missing below.
        if marker is None:
            state = _fixture_state(cur)
            # #414 correction 5: ANY pre-existing fixture-related row (catalogue, RE2E round, or its
            # dependent slots/topics/gates) diverts to full validation — the fresh-slate create-missing
            # path is reserved for a genuinely empty slate so unexpected/orphan data cannot be blessed.
            if any(count > 0 for count in state.values()):
                problems = _validate_complete_fixture(cur)
                cur.close()
                if problems:
                    _fail("no fixture marker and pre-existing data is NOT the complete expected synthetic "
                          "fixture; refusing to re-attest arbitrary/partial data "
                          f"(state={state}): " + "; ".join(problems), 4)
                _write_fixture_marker(GENERATION, revision, db_identity)
                print("[fixture-init] DONE: re-attested a COMPLETE pre-existing synthetic fixture "
                      "(methodology=validated fixture_round=validated fixture_gate=validated) "
                      f"generation={GENERATION} revision={revision} db_identity={db_identity}", flush=True)
                return 0
            cur.close()  # genuinely fresh slate
        else:
            # (4) Marker present, same generation + same db_identity, only the SOURCE REVISION differs: a
            # declared bounded refresh — create-missing, then FULLY validate before rewriting the marker.
            cur.close()

        # (3-fresh / 4) Create-missing, then FULLY validate the complete expected set BEFORE (re)writing the
        # marker — so the marker is never written over an incomplete initialization.
        meth = _ensure_methodology(conn)
        fix = _ensure_fixture(conn)
        gate = _ensure_fixture_gate(conn)
        vcur = conn.cursor()
        problems = _validate_complete_fixture(vcur)
        vcur.close()
        if problems:
            _fail("post-initialization validation failed — the complete expected synthetic fixture is not "
                  "present; NOT writing the fixture marker: " + "; ".join(problems), 5)
        _write_fixture_marker(GENERATION, revision, db_identity)
        print(f"[fixture-init] DONE: methodology={meth} fixture_round={fix} fixture_gate={gate} "
              f"generation={GENERATION} revision={revision} db_identity={db_identity}", flush=True)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
