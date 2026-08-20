"""#414 — STATIC unit tests for deploy/v2-dev/init_fixtures.py (corrections 4 & 5).

Runtime-free: it stubs psycopg2 / engine / e2e_seed / init_db in sys.modules BEFORE importing the module,
so it exercises the pure decision logic with NO database, container, or network. Run:

    python3 deploy/v2-dev/init_fixtures_test.py

Proves:
  * correction 4 — the fixture marker match includes the SOURCE REVISION (a no-op requires generation +
    db_identity + source_revision to all match; a new revision is NOT a silent no-op);
  * correction 5 — a missing/mismatched marker never re-attests arbitrary data: unrecognized ownership and
    incomplete pre-existing data FAIL CLOSED; only the COMPLETE expected fixture (validated) is (re)written;
    the completeness check verifies the full canon catalogue + exact RE2E round/slots/topics + open gate.
"""
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))

# --- Stub every heavy/absent dependency BEFORE importing the module under test. -----------------------
_psycopg2 = types.ModuleType("psycopg2")
_psycopg2.extras = types.ModuleType("psycopg2.extras")
sys.modules["psycopg2"] = _psycopg2
sys.modules["psycopg2.extras"] = _psycopg2.extras

_engine = types.ModuleType("engine")
_engine.open_gate = lambda *a, **k: "gate-stub"
_engine.load_config = lambda *a, **k: None
sys.modules["engine"] = _engine

_e2e = types.ModuleType("e2e_seed")
_e2e.RID = "RE2E"
# (slot_id, pillar_code, hcs_id, topic_angle, format) — mirrors the real e2e_seed.SLOTS shape.
_e2e.SLOTS = [("RE2E-1", "P1", "1.1", "angleA", "F1"),
              ("RE2E-2", "P2", "2.1", "angleB", "F2"),
              ("RE2E-3", "P3", "3.1", "angleC", "F3")]
_e2e.seed = lambda conn: None
sys.modules["e2e_seed"] = _e2e

_init_db = types.ModuleType("init_db")
_init_db._connect = lambda: None          # patched per-test
_init_db._db_identity = lambda cur: "DBID1"
sys.modules["init_db"] = _init_db

if HERE not in sys.path:
    sys.path.insert(0, HERE)
import init_fixtures as fx  # noqa: E402

GEN = fx.GENERATION
REV = "REVX"

# The full shape _fixture_state() now returns (every fixture-related surface). Helpers below spread this
# and override the surfaces a scenario wants non-empty.
ZERO_STATE = {"methodology": 0, "re2e_round": 0, "re2e_slots": 0, "re2e_topics": 0, "re2e_gates": 0}

FAILURES = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    if not cond:
        FAILURES.append(name)


# --- A scripted cursor for _validate_complete_fixture (returns queued results in call order). ---------
class ScriptCursor:
    def __init__(self, fetchones, fetchalls):
        self._ones = list(fetchones)
        self._alls = list(fetchalls)

    def execute(self, *a, **k):
        return None

    def fetchone(self):
        return self._ones.pop(0)

    def fetchall(self):
        return self._alls.pop(0)

    def close(self):
        return None


def _complete_fixture_results():
    """fetchone/fetchall queues, in the exact order _validate_complete_fixture issues them, for a
    fully-complete database (so it returns NO problems). fetchone and fetchall are drawn from independent
    queues, so only the within-type order has to match the code."""
    # canon: sorted(EXPECTED_CANON_COUNTS) == ['format','hcs','hook_type','lens','pillar']
    ones = [(4,), (42,), (5,), (5,), (5,)]      # format, hcs, hook_type, lens, pillar
    ones += [(1,), (1,)]                          # methodology registry present; 1 active version
    ones += [(1,)]                               # RE2E round exactly once
    ones += [(1,)]                               # one open RE2E-targeted topic_review gate
    # (d) slots fetchall (matches _e2e.SLOTS projected to (slot_id, pillar, hcs, format)); then
    # (d2) topics fetchall — identity (slot_id, hcs_id, text_ar) == committed (slot_id, hcs, angle).
    slots = [("RE2E-1", "P1", "1.1", "F1"), ("RE2E-2", "P2", "2.1", "F2"), ("RE2E-3", "P3", "3.1", "F3")]
    topics = [("RE2E-1", "1.1", "angleA"), ("RE2E-2", "2.1", "angleB"), ("RE2E-3", "3.1", "angleC")]
    alls = [slots, topics]
    return ones, alls


# --- FakeConn/cursor for main(): only the schema-regclass fetchone is used unpatched. -----------------
class MainCursor:
    def execute(self, *a, **k):
        return None

    def fetchone(self):
        return ("public.round",)  # schema present (non-None)

    def close(self):
        return None


class MainConn:
    def cursor(self):
        return MainCursor()

    def close(self):
        return None


def run_main_scenario(marker, revision, state=None, validate_problems=None):
    """Drive fx.main(['--confirm']) with the decision-relevant helpers patched. Returns a record of what
    happened: return code / SystemExit code, whether the marker was written (+ args), whether create-missing
    ran."""
    rec = {"wrote": None, "ensured": [], "rc": None, "exit": None}

    def fake_write(generation, rev, db_identity):
        rec["wrote"] = (generation, rev, db_identity)

    orig = {n: getattr(fx, n) for n in (
        "_read_fixture_marker", "_source_revision", "_fixture_state", "_validate_complete_fixture",
        "_ensure_methodology", "_ensure_fixture", "_ensure_fixture_gate", "_write_fixture_marker")}
    orig_connect = fx.init_db._connect
    try:
        fx._read_fixture_marker = lambda: marker
        fx._source_revision = lambda: revision
        fx._fixture_state = lambda cur: (state or ZERO_STATE)
        fx._validate_complete_fixture = lambda cur: list(validate_problems or [])
        fx._ensure_methodology = lambda conn: rec["ensured"].append("methodology") or "loaded"
        fx._ensure_fixture = lambda conn: rec["ensured"].append("fixture") or "created"
        fx._ensure_fixture_gate = lambda conn: rec["ensured"].append("gate") or "opened"
        fx._write_fixture_marker = fake_write
        fx.init_db._connect = lambda: MainConn()
        os.environ["TANAGHOM_LANE_ID"] = fx.LANE_ID
        os.environ["TANAGHOM_DATA_CLASS"] = "synthetic"
        try:
            rec["rc"] = fx.main(["--confirm"])
        except SystemExit as e:
            rec["exit"] = e.code
    finally:
        for n, v in orig.items():
            setattr(fx, n, v)
        fx.init_db._connect = orig_connect
    return rec


def main():
    print("#414 init_fixtures unit tests (corrections 4 & 5)")

    # --- correction 4: _marker_matches binds generation + db_identity + source_revision ---------------
    full = {"fixture_generation": GEN, "db_identity": "DBID1", "source_revision": REV}
    check("marker_matches: full match -> True", fx._marker_matches(full, GEN, REV, "DBID1") is True)
    check("marker_matches: revision differs -> False (correction 4)",
          fx._marker_matches({**full, "source_revision": "OLD"}, GEN, REV, "DBID1") is False)
    check("marker_matches: db_identity differs -> False",
          fx._marker_matches({**full, "db_identity": "OTHER"}, GEN, REV, "DBID1") is False)
    check("marker_matches: generation differs -> False",
          fx._marker_matches({**full, "fixture_generation": "X"}, GEN, REV, "DBID1") is False)
    check("marker_matches: None -> False", fx._marker_matches(None, GEN, REV, "DBID1") is False)

    # --- correction 5: _validate_complete_fixture ----------------------------------------------------
    ones, alls = _complete_fixture_results()
    check("validate: complete fixture -> no problems",
          fx._validate_complete_fixture(ScriptCursor(ones, alls)) == [])

    ones, alls = _complete_fixture_results()
    ones[1] = (41,)  # hcs = 41 (incomplete canon)
    probs = fx._validate_complete_fixture(ScriptCursor(ones, alls))
    check("validate: incomplete canon (hcs=41) -> problem reported",
          any("hcs" in p for p in probs))

    ones, alls = _complete_fixture_results()
    alls[0] = [("RE2E-1", "P1", "1.1", "F1")]  # only 1 of 3 slots
    probs = fx._validate_complete_fixture(ScriptCursor(ones, alls))
    check("validate: partial RE2E slots -> problem reported",
          any("slots mismatch" in p for p in probs))

    # correction 5 follow-up (1): exact committed RE2E topic set — refuse missing/extra/substituted/dup.
    ones, alls = _complete_fixture_results()
    alls[1] = [("RE2E-1", "1.1", "angleA"), ("RE2E-2", "2.1", "angleB")]  # missing RE2E-3 topic
    probs = fx._validate_complete_fixture(ScriptCursor(ones, alls))
    check("validate: MISSING RE2E topic -> problem reported",
          any("topics mismatch" in p for p in probs))

    ones, alls = _complete_fixture_results()
    # substituted topic: RE2E-1's committed angle replaced with a foreign text_ar.
    alls[1] = [("RE2E-1", "1.1", "SUBSTITUTED"), ("RE2E-2", "2.1", "angleB"), ("RE2E-3", "3.1", "angleC")]
    probs = fx._validate_complete_fixture(ScriptCursor(ones, alls))
    check("validate: SUBSTITUTED/mismatched RE2E topic -> problem reported",
          any("topics mismatch" in p for p in probs))

    ones, alls = _complete_fixture_results()
    # extra topic: an unexpected 4th topic identity beyond the committed set.
    alls[1] = [("RE2E-1", "1.1", "angleA"), ("RE2E-2", "2.1", "angleB"), ("RE2E-3", "3.1", "angleC"),
               ("RE2E-1", "1.1", "angleEXTRA")]
    probs = fx._validate_complete_fixture(ScriptCursor(ones, alls))
    check("validate: EXTRA RE2E topic -> problem reported",
          any("topics mismatch" in p for p in probs))

    ones, alls = _complete_fixture_results()
    # duplicated topic: identical identity inserted twice (a set would absorb it; the count guard catches).
    alls[1] = [("RE2E-1", "1.1", "angleA"), ("RE2E-1", "1.1", "angleA"),
               ("RE2E-2", "2.1", "angleB"), ("RE2E-3", "3.1", "angleC")]
    probs = fx._validate_complete_fixture(ScriptCursor(ones, alls))
    check("validate: DUPLICATED RE2E topic -> problem reported (count guard)",
          any("topics mismatch" in p and "duplicates=1" in p for p in probs))

    ones, alls = _complete_fixture_results()
    ones[-1] = (0,)  # no open RE2E-targeted gate
    probs = fx._validate_complete_fixture(ScriptCursor(ones, alls))
    check("validate: no open RE2E gate -> problem reported",
          any("gate" in p for p in probs))

    # --- correction 4/5: main() decision matrix ------------------------------------------------------
    # (1) full match -> NO-OP, zero writes.
    r = run_main_scenario(full, REV)
    check("main: full match -> NO-OP (rc 0, no write, no create)",
          r["rc"] == 0 and r["wrote"] is None and r["ensured"] == [])

    # (4) same gen+id, different revision -> create-missing + validate + rewrite marker with new revision.
    r = run_main_scenario({**full, "source_revision": "OLD"}, REV)
    check("main: revision refresh -> create + write marker(new rev) (correction 4)",
          r["rc"] == 0 and r["wrote"] == (GEN, REV, "DBID1") and r["ensured"] == ["methodology", "fixture", "gate"])

    # (2) generation mismatch -> FAIL CLOSED, no write.
    r = run_main_scenario({**full, "fixture_generation": "OTHER"}, REV)
    check("main: generation mismatch -> fail closed (exit!=0, no write)",
          r["exit"] not in (None, 0) and r["wrote"] is None)

    # (2) db_identity mismatch -> FAIL CLOSED, no write.
    r = run_main_scenario({**full, "db_identity": "OTHER"}, REV)
    check("main: db_identity mismatch -> fail closed (exit!=0, no write)",
          r["exit"] not in (None, 0) and r["wrote"] is None)

    # (3-fresh) no marker + empty slate -> create + validate + write.
    r = run_main_scenario(None, REV, state=dict(ZERO_STATE))
    check("main: no marker + fresh slate -> create + write marker",
          r["rc"] == 0 and r["wrote"] == (GEN, REV, "DBID1") and r["ensured"] == ["methodology", "fixture", "gate"])

    # (3) no marker + COMPLETE pre-existing -> attest (write) WITHOUT create-missing.
    r = run_main_scenario(None, REV, state={**ZERO_STATE, "methodology": 1, "re2e_round": 1,
                                            "re2e_slots": 3, "re2e_topics": 3, "re2e_gates": 1},
                          validate_problems=[])
    check("main: no marker + complete pre-existing -> attest (write, no create) (correction 5)",
          r["rc"] == 0 and r["wrote"] == (GEN, REV, "DBID1") and r["ensured"] == [])

    # (3) no marker + INCOMPLETE pre-existing -> FAIL CLOSED, no write, no create.
    r = run_main_scenario(None, REV, state={**ZERO_STATE, "methodology": 1},
                          validate_problems=["canon hcs: expected 42, found 41"])
    check("main: no marker + incomplete pre-existing -> fail closed (correction 5)",
          r["exit"] not in (None, 0) and r["wrote"] is None and r["ensured"] == [])

    # (3) no marker + UNEXPECTED fixture-adjacent rows ONLY (orphan RE2E slots; methodology + round both
    # empty) -> the expanded _fixture_state routes this to validation, NOT the fresh-slate create path,
    # and it FAILS CLOSED (correction 5 follow-up: unexpected pre-existing fixture-related rows).
    r = run_main_scenario(None, REV, state={**ZERO_STATE, "re2e_slots": 1},
                          validate_problems=["RE2E slots mismatch: ..."])
    check("main: no marker + orphan fixture-adjacent rows -> fail closed, no create (correction 5)",
          r["exit"] not in (None, 0) and r["wrote"] is None and r["ensured"] == [])

    # (create path) post-init validation fails -> FAIL CLOSED, marker NOT written even though create ran.
    r = run_main_scenario(None, REV, state=dict(ZERO_STATE),
                          validate_problems=["RE2E slots mismatch: ..."])
    check("main: create then post-init validation fails -> fail closed, no marker written",
          r["exit"] not in (None, 0) and r["wrote"] is None and r["ensured"] == ["methodology", "fixture", "gate"])

    # --- guard refusals (unchanged behavior, sanity) -------------------------------------------------
    os.environ["TANAGHOM_LANE_ID"] = "prod-lane"
    os.environ["TANAGHOM_DATA_CLASS"] = "synthetic"
    try:
        fx._guard(["--confirm"])
        check("guard: wrong lane refused", False)
    except SystemExit as e:
        check("guard: wrong lane refused (exit!=0)", e.code not in (None, 0))

    os.environ["TANAGHOM_LANE_ID"] = fx.LANE_ID
    os.environ["TANAGHOM_DATA_CLASS"] = "synthetic"
    try:
        fx._guard([])  # no --confirm
        check("guard: missing --confirm refused", False)
    except SystemExit as e:
        check("guard: missing --confirm refused (exit!=0)", e.code not in (None, 0))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("ALL init_fixtures unit tests PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
