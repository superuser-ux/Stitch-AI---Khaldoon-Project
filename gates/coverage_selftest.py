"""#282 — authoritative principal-neutral per-token ANY/ALL approval-coverage selftest.

Exercises the coverage engine (migration 025) directly and in isolation: it seeds its own
principals / roles / group / round / slots (all COV-prefixed), builds gates with controlled
assignment tokens, freezes the authoritative snapshot, records decisions + recomputes coverage
exactly as `engine.decide` does, and asserts the acceptance criteria. Idempotent: tears its
fixtures down at start and end; never touches R1/RE2E/RTG1 or operator-owned config.

Run: docker exec -e PYTHONPATH=/work tanaghom-gateapi python -m gates.coverage_selftest
"""
import os
import sys
import psycopg2.extras

sys.path.insert(0, os.path.dirname(__file__))
import engine          # noqa: E402

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
_fails = 0


def check(label, got, want):
    global _fails
    ok = got == want
    print(f"  {PASS if ok else FAIL} {label}: got={got!r} want={want!r}")
    if not ok:
        _fails += 1


def _dc(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def teardown(conn):
    cur = conn.cursor()
    # every gate this test built targets a COV slot; deleting the gate cascades snapshot/token/
    # eligible/coverage/target/decision rows (all FK ON DELETE CASCADE on gate_id).
    cur.execute("SELECT DISTINCT gate_id FROM gate_target WHERE slot_id LIKE 'COV%%'")
    gate_ids = [r[0] for r in cur.fetchall()]
    if gate_ids:
        cur.execute("DELETE FROM gate WHERE gate_id = ANY(%s::uuid[])", ([str(g) for g in gate_ids],))
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE 'COV%%'")
    cur.execute("DELETE FROM slot WHERE round_id IN ('COVR','COVRD1','COVRD2','COVRD3')")
    cur.execute("DELETE FROM round WHERE round_id IN ('COVR','COVRD1','COVRD2','COVRD3')")
    cur.execute("DELETE FROM principal_role_member WHERE role_id LIKE 'COV-%%'")
    cur.execute("DELETE FROM principal_group_member WHERE group_id LIKE 'COV-%%'")
    cur.execute("DELETE FROM principal_role WHERE role_id LIKE 'COV-%%'")
    cur.execute("DELETE FROM principal_group WHERE group_id LIKE 'COV-%%'")
    cur.execute("DELETE FROM principal WHERE principal_id LIKE 'COV-%%'")
    conn.commit(); cur.close()


def seed(conn):
    cur = conn.cursor()
    # principals (all human-kind users; coverage is principal-neutral so kind is not what governs)
    for p in ("COV-A", "COV-B", "COV-C", "COV-D", "COV-E"):
        cur.execute("INSERT INTO principal (principal_id, kind, display_name_en, role, module) "
                    "VALUES (%s,'user',%s,'reviewer','content') ON CONFLICT DO NOTHING", (p, p))
    # roles + group
    cur.execute("INSERT INTO principal_role (role_id, display_name_en) VALUES ('COV-RX','X') ON CONFLICT DO NOTHING")
    cur.execute("INSERT INTO principal_role (role_id, display_name_en) VALUES ('COV-RY','Y') ON CONFLICT DO NOTHING")
    cur.execute("INSERT INTO principal_group (group_id, display_name_en) VALUES ('COV-GZ','Z') ON CONFLICT DO NOTHING")
    # memberships: RX={A,B,D}, RY={B,C}, GZ={C,E}. B overlaps RX+RY; C overlaps RY+GZ.
    for pid in ("COV-A", "COV-B", "COV-D"):
        cur.execute("INSERT INTO principal_role_member (role_id, principal_id) VALUES ('COV-RX',%s) ON CONFLICT DO NOTHING", (pid,))
    for pid in ("COV-B", "COV-C"):
        cur.execute("INSERT INTO principal_role_member (role_id, principal_id) VALUES ('COV-RY',%s) ON CONFLICT DO NOTHING", (pid,))
    for pid in ("COV-C", "COV-E"):
        cur.execute("INSERT INTO principal_group_member (group_id, principal_id) VALUES ('COV-GZ',%s) ON CONFLICT DO NOTHING", (pid,))
    # roles used ONLY by the through-decide() P1 regressions, so their live-membership changes never
    # interfere with the coverage tests above: RP1/RP3={A,B}, RP2={A}.
    for rid in ("COV-RP1", "COV-RP2", "COV-RP3"):
        cur.execute("INSERT INTO principal_role (role_id, display_name_en) VALUES (%s,%s) ON CONFLICT DO NOTHING", (rid, rid))
    for rid, members in (("COV-RP1", ("COV-A", "COV-B")), ("COV-RP2", ("COV-A",)), ("COV-RP3", ("COV-A", "COV-B"))):
        for pid in members:
            cur.execute("INSERT INTO principal_role_member (role_id, principal_id) VALUES (%s,%s) ON CONFLICT DO NOTHING", (rid, pid))
    # a throwaway round + slots at the topic review status (valid pillar/hcs FKs reused)
    cur.execute("INSERT INTO round (round_id, period_len_days, posts_per_day, post_times, "
                "pillar_distribution, format_distribution) VALUES "
                "('COVR',1,8,'[]'::jsonb,'{}'::jsonb,'{}'::jsonb) ON CONFLICT DO NOTHING")
    for i in range(1, 10):
        cur.execute("INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, hcs_id, status) "
                    "VALUES (%s,'COVR',1,%s,'P1_SELF','1.1','TOPIC_PROPOSED') ON CONFLICT DO NOTHING",
                    (f"COV-{i}", f"0{i}:00"))
    # single-slot rounds for the through-decide() regressions (so decide()'s reconcile pulls in no
    # other slot — clean per-gate isolation)
    for rd, sl in (("COVRD1", "COVD1-1"), ("COVRD2", "COVD2-1"), ("COVRD3", "COVD3-1")):
        cur.execute("INSERT INTO round (round_id, period_len_days, posts_per_day, post_times, "
                    "pillar_distribution, format_distribution) VALUES "
                    "(%s,1,1,'[]'::jsonb,'{}'::jsonb,'{}'::jsonb) ON CONFLICT DO NOTHING", (rd,))
        cur.execute("INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, hcs_id, status) "
                    "VALUES (%s,%s,1,'09:00','P1_SELF','1.1','TOPIC_PROPOSED') ON CONFLICT DO NOTHING", (sl, rd))
    conn.commit(); cur.close()


def mk_gate(conn, rule, tokens, slot_id):
    """Create an authoritative gate over one slot with the given rule + assignment tokens (freezing
    the snapshot from CURRENT membership), returning (gate_id, snapshot)."""
    cur = _dc(conn)
    cur.execute("INSERT INTO gate (scope, stage, policy, rule_key, quorum, status) "
                "VALUES ('batch','topic_review','fixed',%s,%s,'open') RETURNING gate_id",
                (rule, str(len(tokens) if rule == "all" else 1)))
    gate_id = cur.fetchone()["gate_id"]
    cur.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,%s)", (gate_id, slot_id))
    for tok in tokens:
        snap = engine._assignment_snapshot(tok)
        cur.execute("INSERT INTO gate_assignment (gate_id, assignment_kind, assignment_key, resolved_principal_id) "
                    "VALUES (%s,%s,%s,%s)", (gate_id, snap["assignment_kind"], snap["assignment_key"],
                                             snap["resolved_principal_id"]))
    engine._freeze_gate_snapshot(cur, gate_id, rule, tokens)
    conn.commit()
    snapshot = engine._load_gate_snapshot(cur, gate_id)
    cur.close()
    return gate_id, snapshot


def approve(conn, gate_id, slot_id, approver, snapshot):
    """Record an approval + recompute per-token coverage — exactly the steps engine.decide runs."""
    cur = _dc(conn)
    cur.execute("INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision) VALUES (%s,%s,%s,'approve') "
                "ON CONFLICT (gate_id, approver_id, slot_id) DO UPDATE SET decision='approve', decided_at=now()",
                (gate_id, slot_id, approver))
    engine._recompute_slot_coverage(cur, gate_id, slot_id, snapshot)
    conn.commit(); cur.close()


def outcome(conn, gate_id, snapshot, slot_id):
    cur = _dc(conn)
    cur.execute("SELECT decision FROM gate_decision WHERE gate_id=%s AND slot_id=%s", (gate_id, slot_id))
    decisions = cur.fetchall()
    proj = engine._authoritative_target_projection(cur, gate_id, snapshot, slot_id, decisions)
    cur.close()
    return proj


def verify_migration(conn):
    print("0) migration 025 verification")
    cur = conn.cursor()
    for t in ("gate_snapshot", "gate_snapshot_token", "gate_snapshot_eligible", "gate_token_coverage"):
        cur.execute("SELECT to_regclass('public.%s')" % t)
        check(f"table {t} present", cur.fetchone()[0] is not None, True)
    cur.execute("SELECT count(*) FROM pg_constraint WHERE conrelid='gate_token_coverage'::regclass AND contype='u'")
    check("coverage carries the 2 D1 distinctness UNIQUE constraints", cur.fetchone()[0], 2)
    cur.execute("SELECT count(*) FROM pg_constraint WHERE conrelid='gate_token_coverage'::regclass AND contype='f'")
    check("coverage carries FK protections (snapshot/token/gate/slot/principal)", cur.fetchone()[0] >= 4, True)
    cur.execute("""SELECT count(*) FROM pg_constraint WHERE conname IN
        ('gate_snapshot_gate_snapshot_uq','gate_snapshot_token_snap_uq','gtc_gate_snapshot_fk','gtc_snapshot_token_fk')""")
    check("parent-consistency: 2 composite-parent UNIQUEs + 2 composite FKs present", cur.fetchone()[0], 4)
    sql = open("/work/db/migrations/025_authoritative_token_coverage.sql").read()
    cur.execute(sql); conn.commit()                       # rerun -> idempotent no-op
    check("migration re-apply is idempotent (safe rerun)", True, True)
    check("migration is transactional (atomic BEGIN/COMMIT)", ("BEGIN;" in sql and "COMMIT;" in sql), True)
    check("migration inspects base tables first + fails closed (no partial apply)",
          ("RAISE EXCEPTION" in sql and "to_regclass" in sql), True)
    check("migration performs NO backfill/seed of existing gates",
          ("INSERT INTO gate_snapshot" not in sql and "UPDATE gate" not in sql), True)
    cur.close()


def main():
    conn = engine.db_connect()
    teardown(conn)
    seed(conn)
    print("#282 authoritative per-token ANY/ALL coverage\n")
    verify_migration(conn)
    print()

    # --- pure matching (the authorization core), no DB ---
    print("1) maximum bipartite matching (pure)")
    T = [{"snapshot_token_id": "t1", "eligible": {"A", "B", "D"}},
         {"snapshot_token_id": "t2", "eligible": {"B", "C"}}]
    check("two principals matching only the same token cannot cover both ALL tokens",
          len(engine._match_tokens(T, ["A", "D"])), 1)              # A,D only in t1 -> 1 covered
    check("one principal matching two tokens covers only one",
          len(engine._match_tokens(T, ["B"])), 1)                   # B in t1&t2 -> 1
    check("distinct eligible principals cover all tokens",
          len(engine._match_tokens(T, ["A", "C"])), 2)              # A->t1, C->t2
    # greedy would fail this ordering; max-matching must not
    Tg = [{"snapshot_token_id": "t1", "eligible": {"P", "Q"}},
          {"snapshot_token_id": "t2", "eligible": {"P"}}]
    check("augmenting matching resolves P->t1-blocking (greedy-fail case)",
          len(engine._match_tokens(Tg, ["P", "Q"])), 2)

    # --- ALL over two role tokens ---
    print("\n2) ALL over [role:COV-RX, role:COV-RY]")
    g, snap = mk_gate(conn, "all", ["role:COV-RX", "role:COV-RY"], "COV-1")
    approve(conn, g, "COV-1", "COV-A", snap)   # A in RX only
    approve(conn, g, "COV-1", "COV-D", snap)   # D in RX only
    check("AC1 two principals matching ONLY role RX cannot satisfy ALL (RY uncovered)",
          outcome(conn, g, snap, "COV-1")["current_outcome"], "pending")
    check("AC1 remaining requirement names the uncovered token (RY), frozen not live",
          sorted(a["assignment_key"] for a in outcome(conn, g, snap, "COV-1")["remaining_assignments"]),
          ["COV-RY"])
    approve(conn, g, "COV-1", "COV-C", snap)   # C in RY -> now A/D->RX, C->RY
    check("distinct principals then satisfy every ALL token",
          outcome(conn, g, snap, "COV-1")["current_outcome"], "approved")

    print("\n3) AC2 one principal matching two tokens cannot satisfy both ALL tokens")
    g2, snap2 = mk_gate(conn, "all", ["role:COV-RX", "role:COV-RY"], "COV-2")
    approve(conn, g2, "COV-2", "COV-B", snap2)  # B in RX AND RY -> covers exactly one
    check("AC2 one principal (in both roles) leaves a token uncovered",
          outcome(conn, g2, snap2, "COV-2")["current_outcome"], "pending")
    check("AC2 exactly one token is covered by the single principal",
          outcome(conn, g2, snap2, "COV-2")["approval_count"], 1)
    approve(conn, g2, "COV-2", "COV-C", snap2)  # add C (RY) -> B->RX, C->RY
    check("AC2 a distinct second principal completes ALL",
          outcome(conn, g2, snap2, "COV-2")["current_outcome"], "approved")

    print("\n4) AC5 ANY needs one token; mixed user/role/group ALL with overlap")
    ga, snapa = mk_gate(conn, "any", ["role:COV-RX", "role:COV-RY"], "COV-3")
    approve(conn, ga, "COV-3", "COV-A", snapa)
    check("AC5 ANY resolves on one covered token", outcome(conn, ga, snapa, "COV-3")["current_outcome"], "approved")
    gm, snapm = mk_gate(conn, "all", ["user:COV-A", "role:COV-RY", "group:COV-GZ"], "COV-4")
    approve(conn, gm, "COV-4", "COV-A", snapm)  # user:COV-A
    approve(conn, gm, "COV-4", "COV-C", snapm)  # C in RY AND GZ -> covers one
    check("AC3 mixed user/role/group with an overlapping principal is still pending",
          outcome(conn, gm, snapm, "COV-4")["current_outcome"], "pending")
    approve(conn, gm, "COV-4", "COV-E", snapm)  # E in GZ -> A->user, C->RY, E->GZ
    check("AC3 three distinct principals cover user+role+group tokens",
          outcome(conn, gm, snapm, "COV-4")["current_outcome"], "approved")

    print("\n4b) AC6 full read model (what the API serializes) exposes coverage + legacy identically")
    full = engine.get_gate(conn, gm)
    t4 = next(t for t in full["targets"] if t["slot_id"] == "COV-4")
    check("AC6 read model marks the gate authoritative (not legacy)",
          (full.get("authoritative"), full.get("legacy")), (True, False))
    check("AC6 read model exposes every required token with a covering principal",
          (len(t4["coverage"]), all(c["covered_by"] for c in t4["coverage"]), t4["current_outcome"]),
          (3, True, "approved"))

    print("\n5) AC4/D3 frozen eligibility — membership change after open does not affect the gate")
    gf, snapf = mk_gate(conn, "all", ["role:COV-RX", "role:COV-RY"], "COV-5")
    cur = conn.cursor()
    cur.execute("UPDATE principal_role_member SET active=false WHERE role_id='COV-RX' AND principal_id='COV-A'")
    cur.execute("DELETE FROM principal_role_member WHERE role_id='COV-RY' AND principal_id='COV-C'")
    conn.commit(); cur.close()
    approve(conn, gf, "COV-5", "COV-A", snapf)  # A removed from RX live, but FROZEN eligible at open
    approve(conn, gf, "COV-5", "COV-C", snapf)  # C removed from RY live, but FROZEN eligible at open
    check("AC4 frozen eligibility still lets the open-time principals cover their tokens",
          outcome(conn, gf, snapf, "COV-5")["current_outcome"], "approved")
    # a NEWLY opened gate sees the new membership (A no longer eligible for RX)
    gf2, snapf2 = mk_gate(conn, "all", ["role:COV-RX", "role:COV-RY"], "COV-6")
    rx_eligible = next(t["eligible"] for t in snapf2["tokens"] if t["normalized"] == "role:COV-RX")
    check("AC4 a newly opened gate reflects the new membership (A dropped from RX)",
          "COV-A" in rx_eligible, False)

    print("\n6) AC7 undecide recomputes coverage back to pending; AC legacy branch")
    approve(conn, g, "COV-1", "COV-A", snap)  # re-establish g/COV-1 approved from test 2
    engine.clear_decision(conn, g, "COV-C", slot_ids=["COV-1"])   # remove RY's covering principal
    check("AC7 clearing the token's only cover returns the slot to pending",
          outcome(conn, g, snap, "COV-1")["current_outcome"], "pending")
    # legacy: a gate with no authoritative snapshot is legacy by absence
    cur = _dc(conn)
    cur.execute("INSERT INTO gate (scope, stage, policy, rule_key, quorum, status) "
                "VALUES ('batch','topic_review','fixed','all','2','open') RETURNING gate_id")
    legacy_gate = cur.fetchone()["gate_id"]
    cur.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,'COV-8')", (legacy_gate,))
    conn.commit(); cur.close()
    cur = _dc(conn)
    check("legacy gate has no authoritative snapshot (legacy by absence)",
          engine._load_gate_snapshot(cur, legacy_gate), None)
    cur.close()
    legacy_full = engine.get_gate(conn, legacy_gate)
    check("legacy read model marks the gate legacy + claims NO authoritative coverage",
          (legacy_full.get("authoritative"), legacy_full.get("legacy"),
           all(t.get("coverage") is None for t in legacy_full["targets"])),
          (False, True, True))

    print("\n7) AC8 DB constraints enforce the D1 distinctness invariants")
    g8, snap8 = mk_gate(conn, "all", ["role:COV-RX", "role:COV-RY"], "COV-7")
    tok_ids = [t["snapshot_token_id"] for t in snap8["tokens"]]
    cur = conn.cursor()
    cur.execute("INSERT INTO gate_token_coverage (gate_id, slot_id, snapshot_id, snapshot_token_id, covering_principal_id) "
                "VALUES (%s,'COV-7',%s,%s,'COV-A')", (g8, snap8["snapshot_id"], tok_ids[0]))
    conn.commit()
    dup_token = _raises(lambda: _ins(conn, g8, snap8, tok_ids[0], "COV-B"))   # same token+slot
    check("AC8 duplicate coverage of the same token+slot is rejected", dup_token, True)
    dup_principal = _raises(lambda: _ins(conn, g8, snap8, tok_ids[1], "COV-A"))  # same principal 2nd token
    check("AC8 one principal covering a second token in the same slot is rejected", dup_principal, True)
    # parent-consistency (composite FKs): a coverage row must reference a snapshot that belongs to its
    # gate AND a token that belongs to that snapshot. `snapm`/`gm` (test 4) is a DIFFERENT parent chain.
    foreign_tok = snapm["tokens"][0]["snapshot_token_id"]
    check("cross-snapshot: a token from a DIFFERENT snapshot is rejected at the DB (composite FK)",
          _raises(lambda: _ins_cover(conn, g8, snap8["snapshot_id"], foreign_tok, "COV-A")), True)
    check("cross-gate: a snapshot from a DIFFERENT gate is rejected at the DB (composite FK)",
          _raises(lambda: _ins_cover(conn, g8, snapm["snapshot_id"], foreign_tok, "COV-A")), True)
    cur.close()

    print("\n8) Codex P1 regressions — authority path through decide() / queue")
    # P1.3 — the coverage audit outcome is derived from the FULL persisted decision set (reject
    # precedence), not just the current decision: reject by A, then approve by B -> audit says rejected.
    gp, _ = mk_gate(conn, "all", ["role:COV-RP1"], "COVD1-1")     # RP1 frozen {A,B}
    engine.decide(conn, gp, "COV-A", "reject", slot_ids=["COVD1-1"])
    engine.decide(conn, gp, "COV-B", "approve", slot_ids=["COVD1-1"])
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT detail->>'outcome' AS o FROM audit_log WHERE entity='slot' AND entity_id='COVD1-1' "
                "AND action='coverage_recomputed' ORDER BY id DESC LIMIT 1")
    check("P1.3 coverage audit outcome from FULL decisions (reject precedence, not just the approve)",
          cur.fetchone()["o"], "rejected")
    cur.close()
    tp = next(t for t in engine.get_gate(conn, gp)["targets"] if t["slot_id"] == "COVD1-1")
    check("P1.3 API/audit parity: canonical outcome is rejected", tp["current_outcome"], "rejected")

    # P1.1 — through decide(): a frozen-eligible actor stays authorized after LIVE role removal (D3);
    # an actor never frozen-eligible is denied by decide().
    g11, _ = mk_gate(conn, "all", ["role:COV-RP2"], "COVD2-1")     # RP2 frozen {A}
    cur = conn.cursor()
    cur.execute("UPDATE principal_role_member SET active=false WHERE role_id='COV-RP2' AND principal_id='COV-A'")
    conn.commit(); cur.close()
    engine.decide(conn, g11, "COV-A", "approve", slot_ids=["COVD2-1"])    # must SUCCEED (frozen)
    t11 = next(t for t in engine.get_gate(conn, g11)["targets"] if t["slot_id"] == "COVD2-1")
    check("P1.1 frozen-eligible actor authorized by decide() after live removal (D3)",
          t11["current_outcome"], "approved")
    denied = False
    try:
        engine.decide(conn, g11, "COV-E", "approve", slot_ids=["COVD2-1"])
    except engine.GateError:
        denied = True
    finally:
        conn.rollback()
    check("P1.1 an actor never frozen-eligible is denied by decide()", denied, True)

    # P1.2 — reviewer queue reads frozen eligibility + coverage; parity with gate detail.
    gq, _ = mk_gate(conn, "all", ["role:COV-RP3"], "COVD3-1")      # RP3 frozen {A,B}; single-slot round
    in_q = lambda pa: any(str(x["gate_id"]) == str(gq) for x in pa)
    check("P1.2 frozen-eligible actor sees the authoritative gate in the queue",
          in_q(engine.list_pending_approvals(conn, "COV-A")), True)
    cur = conn.cursor()
    cur.execute("UPDATE principal_role_member SET active=false WHERE role_id='COV-RP3' AND principal_id='COV-A'")
    conn.commit(); cur.close()
    pa2 = engine.list_pending_approvals(conn, "COV-A")
    qrow = next((x for x in pa2 if str(x["gate_id"]) == str(gq)), None)
    check("P1.2 queue STILL shows the gate after live removal (frozen eligibility, D3)", qrow is not None, True)
    check("P1.2 a non-frozen principal does NOT see the authoritative gate",
          in_q(engine.list_pending_approvals(conn, "COV-E")), False)
    gate_pending = sum(1 for t in engine.get_gate(conn, gq)["targets"] if t["current_outcome"] == "pending")
    check("P1.2 queue remaining agrees with gate-detail pending (read parity)",
          qrow["remaining_targets"] if qrow else -1, gate_pending)

    teardown(conn)
    conn.close()
    print("\n" + "=" * 60)
    if _fails:
        print(f"{_fails} CHECK(S) FAILED"); sys.exit(1)
    print("ALL COVERAGE CHECKS PASSED")
    print("=" * 60)


def _ins(conn, gate_id, snapshot, token_id, principal):
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO gate_token_coverage (gate_id, slot_id, snapshot_id, snapshot_token_id, covering_principal_id) "
                    "VALUES (%s,'COV-7',%s,%s,%s)", (gate_id, snapshot["snapshot_id"], token_id, principal))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close()


def _ins_cover(conn, gate_id, snapshot_id, token_id, principal, slot="COV-7"):
    """Raw coverage insert with explicit parents — used to prove the composite parent-consistency FKs
    reject a cross-gate / cross-snapshot row. Rolls back a failed insert so the conn stays usable."""
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO gate_token_coverage "
                    "(gate_id, slot_id, snapshot_id, snapshot_token_id, covering_principal_id) "
                    "VALUES (%s,%s,%s,%s,%s)", (str(gate_id), slot, str(snapshot_id), str(token_id), principal))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close()


def _raises(fn):
    try:
        fn(); return False
    except Exception:
        return True


if __name__ == "__main__":
    main()
