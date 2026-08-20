#!/usr/bin/env python3
"""#423 — ISOLATED ephemeral-Postgres test harness for immutable final-review target-package snapshots.

Creates its OWN throwaway Postgres cluster in a temp dir (`initdb` + `pg_ctl` on a PRIVATE unix socket,
no TCP), applies the committed `db/init/schema.sql` + every `db/migrations/*.sql` (including this
slice's 036), runs the #423 discriminators against real Postgres, then tears the cluster down. It
NEVER contacts the shared dev DB, Docker, Compose, browser, or VPS — the only DB it touches is the one
it just created and will delete.

    python3 gates/final_review_target_package_harness.py

Proves: additive migration applies clean; PK uniqueness + DB update/delete immutability rejection;
package derivation pinnable/unpinnable; whole-batch reconcile rollback on an unpinnable candidate with
zero residue; accepted late batch + replay idempotency + audit-from-insert-only; gate-wide snapshot
inheritance; post-attachment canonical mutation cannot alter recorded evidence; legacy unknown_history
read; initial-open whole-batch helper contract; and the typed read model shapes.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
import engine  # noqa: E402
import final_review_target_package as frtp  # noqa: E402
import final_review_projection as frp  # noqa: E402  (#427 — additive final-review read projection)

FAIL = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    if not cond:
        FAIL.append(name)


def _scrub_pg_env():
    """#425 finding 5 — reject inherited connection settings that could resolve to a running/shared DB:
    strip every PG*/service var so neither libpq nor pg_ctl can reach a non-harness instance. We then
    connect only via this harness's own unix socket in a temp dir."""
    for k in [k for k in list(os.environ)
              if k.startswith("PG") or k in ("PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR")]:
        os.environ.pop(k, None)


def _pg_env():
    # macOS Postgres 18 aborts startup ("postmaster became multithreaded") without a plain C locale.
    return dict(os.environ, LC_ALL="C", LANG="C")


def _run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, env=_pg_env())


class _InjectedFailure(RuntimeError):
    """Deterministic failure injected into start_pg() at a named phase (test-only)."""


_OWNED_ROOTS = []   # every temp root start_pg has created (for ownership-scoped cleanup proofs)


def start_pg(_fail_at=None):
    """Create an OWNED ephemeral cluster and return (root, data, sock). #426 finding 1 — exception-safe
    before it returns: owned root/data/socket and started-state are tracked before each risky step, and
    on ANY failure (directory creation, initdb, PostgreSQL startup, or post-start/pre-return) it stops
    only the owned cluster (iff it started), removes the owned resources, and RE-RAISES the original
    exception. `cleanup()` is idempotent, so this is safe to combine with the caller's finally.
    `_fail_at` in {'pre_initdb','startup','post_start'} injects a deterministic failure for the proofs."""
    d = tempfile.mkdtemp(prefix="fr-tpkg-pg-")
    _OWNED_ROOTS.append(d)
    data, sock, log = os.path.join(d, "data"), os.path.join(d, "sock"), os.path.join(d, "pg.log")
    started = False
    try:
        if _fail_at == "pre_initdb":
            raise _InjectedFailure("injected pre-initdb failure")
        os.makedirs(sock)
        _run("initdb", "-D", data, "-U", "postgres", "--auth=trust", "-E", "UTF8", "--locale=C")
        if _fail_at == "startup":
            raise _InjectedFailure("injected startup failure")
        _run("pg_ctl", "-D", data, "-l", log, "-w", "-o", f"-k {sock} -c listen_addresses=''", "start")
        started = True
        if _fail_at == "post_start":
            raise _InjectedFailure("injected post-start/pre-return failure")
        return d, data, sock
    except BaseException:
        # stop only THIS owned cluster (if it started) then remove the owned root; preserve the original
        # exception. cleanup() tolerates a not-running cluster and an already-gone dir (idempotent).
        cleanup(d, data if started else None)
        raise


def cleanup(d, data):
    """#425 finding 5 — idempotent, no-process-tolerant teardown of ONLY this harness's owned cluster.
    Safe at any failure point (before/during initdb, startup, schema, or an assertion); it stops only the
    cluster in `data` (never a non-harness/shared instance) and removes the owned socket + data dirs. It
    raises nothing, so it preserves the caller's original error."""
    try:
        if data and os.path.isdir(data):
            # no check=: the cluster may never have started; a stop failure must not mask the real error.
            subprocess.run(["pg_ctl", "-D", data, "-m", "immediate", "stop"],
                           capture_output=True, text=True, env=_pg_env())
    except Exception:
        pass
    if d and os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)


def _strip_pgvector(sql):
    """Vanilla local Postgres has no pgvector; the `embedding vector(1024)` column + its ivfflat index
    are irrelevant to #423. Drop only those lines so the rest of the committed schema applies faithfully."""
    out = []
    for line in sql.splitlines():
        low = line.lower()
        if "vector(1024)" in low or "ivfflat" in low or "create extension" in low and "vector" in low:
            continue
        out.append(line)
    return "\n".join(out)


def apply_schema(conn, has_vector):
    conn.autocommit = True
    cur = conn.cursor()
    files = [os.path.join(REPO, "db", "init", "schema.sql")]
    files += sorted(__import__("glob").glob(os.path.join(REPO, "db", "migrations", "*.sql")))
    for path in files:
        sql = open(path, "r", encoding="utf-8").read()
        if not has_vector:
            sql = _strip_pgvector(sql)
        cur.execute(sql)
    cur.close()
    conn.autocommit = False


CFG = {"gates": {"final_review": {"reviews_status": "APPROVED_ASSIGNED"}}}
# For the real open_gate() path: the approval contract (both approvers must sign) + reviews status.
CFG_OPEN = {"gates": {"final_review": {"scope": "batch", "policy": "fixed",
                                       "approval": {"rule": "and", "users": ["khal", "huda"]},
                                       "reviews_status": "APPROVED_ASSIGNED",
                                       "approve_to": "READY_FOR_PRODUCTION"}}}


def seed_principals(cur):
    cur.execute("INSERT INTO principal (principal_id, kind) VALUES ('khal','user'),('huda','user') "
                "ON CONFLICT DO NOTHING")


def seed_common(cur):
    """A workflow_version to reference, plus a helper to mint a fully-pinnable final-review slot."""
    wf = str(uuid.uuid4())
    cur.execute("INSERT INTO workflow (workflow_id, workflow_key, name) VALUES (%s,'wf','WF')", (wf,))
    wv = str(uuid.uuid4())
    cur.execute("INSERT INTO workflow_version (version_id, workflow_id, version_no, status) "
                "VALUES (%s,%s,1,'active')", (wv, wf))
    # canonical dimension rows the slot/topic/script FKs need
    cur.execute("INSERT INTO pillar (pillar_code, code_short, name_en, name_ar) "
                "VALUES ('P1','P1','Pillar','بيلار') ON CONFLICT DO NOTHING")
    cur.execute("INSERT INTO hcs (hcs_id, pillar_code, seq_in_pillar, name_en) "
                "VALUES ('1.1','P1',1,'HCS') ON CONFLICT DO NOTHING")
    return wv


def mint_round(cur, rid):
    cur.execute("INSERT INTO round (round_id, label, period_len_days, posts_per_day, post_times, "
                "pillar_distribution, format_distribution, status) "
                "VALUES (%s,'r',1,1,'[]','{}','{}','planning')", (rid,))


def mint_slot(cur, rid, sid, wv, *, pinnable=True, script_rev=1):
    cur.execute("INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, hcs_id, status) "
                "VALUES (%s,%s,1,'09:00','P1','1.1','APPROVED_ASSIGNED')", (sid, rid))
    tid = str(uuid.uuid4())
    cur.execute("INSERT INTO topic (topic_id, slot_id, hcs_id, round_id, revision) VALUES (%s,%s,'1.1',%s,1)",
                (tid, sid, rid))
    scid = str(uuid.uuid4())
    cur.execute("INSERT INTO script (script_id, slot_id, hcs_id, revision) VALUES (%s,%s,'1.1',%s)",
                (scid, sid, script_rev))
    cur.execute("INSERT INTO slot_approval (slot_id, artifact, revision) VALUES (%s,'topic',1)", (sid,))
    cur.execute("INSERT INTO slot_approval (slot_id, artifact, revision) VALUES (%s,'script',%s)",
                (sid, script_rev))
    if pinnable:
        cur.execute("INSERT INTO script_provenance (script_id, revision, workflow_version_id) "
                    "VALUES (%s,%s,%s)", (scid, script_rev, wv))
    return tid, scid


def mint_gate(cur, rid, target_slots):
    gid = str(uuid.uuid4())
    cur.execute("INSERT INTO gate (gate_id, scope, stage, policy, rule_key, quorum, status) "
                "VALUES (%s,'batch','final_review','fixed','all','all','open')", (gid,))
    snap = str(uuid.uuid4())
    cur.execute("INSERT INTO gate_snapshot (snapshot_id, gate_id, rule_key) VALUES (%s,%s,'all')", (snap, gid))
    for s in target_slots:
        cur.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,%s)", (gid, s))
    return gid, snap


def audit_count(cur, gid, action):
    cur.execute("SELECT count(*) AS n FROM audit_log WHERE entity='gate' AND entity_id=%s AND action=%s",
                (gid, action))
    return cur.fetchone()["n"]


def snap_count(cur, gid, sid=None):
    if sid:
        cur.execute("SELECT count(*) AS n FROM final_review_target_package WHERE gate_id=%s AND slot_id=%s",
                    (gid, sid))
    else:
        cur.execute("SELECT count(*) AS n FROM final_review_target_package WHERE gate_id=%s", (gid,))
    return cur.fetchone()["n"]


def main():
    print("#423/#425 final_review_target_package isolated ephemeral-Postgres harness")
    _scrub_pg_env()

    # #425 finding 5 — partial-startup cleanup proof, BEFORE any real cluster: teardown must tolerate a
    # cluster that never started, remove the owned temp dir, and be idempotent / no-process-tolerant.
    pd = tempfile.mkdtemp(prefix="fr-tpkg-partial-")
    cleanup(pd, os.path.join(pd, "data"))
    check("partial-startup cleanup removes the owned temp dir when no cluster was created", not os.path.isdir(pd))
    idem_ok = True
    try:
        cleanup(pd, os.path.join(pd, "data"))
    except Exception:
        idem_ok = False
    check("cleanup is idempotent / no-process-tolerant (raises nothing on an already-gone dir)", idem_ok)

    # #426 finding 1 — start_pg() exception-safety: each injected failure phase (pre-initdb / startup /
    # post-start-pre-return) must leave no owned process, socket, data dir, or temporary root, and must
    # preserve the ORIGINAL exception.
    for phase in ("pre_initdb", "startup", "post_start"):
        preserved = False
        try:
            start_pg(_fail_at=phase)
        except _InjectedFailure:
            preserved = True
        except BaseException:
            preserved = False
        root = _OWNED_ROOTS[-1]
        noproc = subprocess.run(["pgrep", "-f", root], capture_output=True, text=True).returncode != 0
        check(f"start_pg failure@{phase}: original exception preserved", preserved)
        check(f"start_pg failure@{phase}: owned root/socket/data removed", not os.path.isdir(root))
        check(f"start_pg failure@{phase}: no owned postgres process remains", noproc)

    d = data = None
    try:
        d, data, sock = start_pg()
        conn = psycopg2.connect(host=sock, dbname="postgres", user="postgres",
                                cursor_factory=psycopg2.extras.RealDictCursor)
        # pgvector availability
        conn.autocommit = True
        c0 = conn.cursor()
        has_vector = True
        try:
            c0.execute("CREATE EXTENSION IF NOT EXISTS vector")
            c0.execute("DROP EXTENSION vector")
        except Exception:
            has_vector = False
        c0.close()
        conn.autocommit = False
        print(f"  (pgvector available: {has_vector}; applying committed schema + migrations 001..036)")
        apply_schema(conn, has_vector)

        cur = conn.cursor()
        # migration 036 objects exist
        cur.execute("SELECT to_regclass('public.final_review_target_package') AS t")
        check("migration 036 applied — final_review_target_package table exists", cur.fetchone()["t"] is not None)
        conn.commit()

        wv = seed_common(cur); conn.commit()

        # ---- Scenario 1: accepted LATE reconcile batch + legacy unknown + replay idempotency ----
        mint_round(cur, "R1")
        mint_slot(cur, "R1", "R1-A", wv)          # initial target (seeded without a snapshot = legacy)
        mint_slot(cur, "R1", "R1-B", wv)          # new eligible, pinnable
        g1, snap1 = mint_gate(cur, "R1", ["R1-A"])
        conn.commit()
        added = engine.reconcile_gate_targets(cur, g1, cfg=CFG, actor="system")
        conn.commit()
        check("late reconcile appends the pinnable candidate", added == ["R1-B"])
        check("snapshot recorded for the appended target (R1-B)", snap_count(cur, g1, "R1-B") == 1)
        check("no snapshot fabricated for the legacy target (R1-A)", snap_count(cur, g1, "R1-A") == 0)
        check("attachment audit emitted once from the successful insert",
              audit_count(cur, g1, "final_review_target_package_attached") == 1)
        # gate-wide inheritance: the target-package references the gate-wide frozen snapshot
        cur.execute("SELECT snapshot_id::text AS s FROM final_review_target_package WHERE gate_id=%s AND slot_id='R1-B'", (g1,))
        check("target-package inherits the gate-wide snapshot id (not a per-target freeze)",
              cur.fetchone()["s"] == snap1)
        # replay: re-reconcile — no new target, snapshot, or audit
        added2 = engine.reconcile_gate_targets(cur, g1, cfg=CFG, actor="system")
        conn.commit()
        check("replay of an accepted reconcile is a no-op (no new target)", added2 == [])
        check("replay creates no duplicate snapshot", snap_count(cur, g1, "R1-B") == 1)
        check("replay creates no duplicate attachment audit",
              audit_count(cur, g1, "final_review_target_package_attached") == 1)

        # ---- Scenario 2: WHOLE-BATCH rollback on an unpinnable candidate — zero residue ----
        mint_round(cur, "R2")
        mint_slot(cur, "R2", "R2-D", wv)                       # initial target
        mint_slot(cur, "R2", "R2-E", wv)                       # pinnable candidate
        mint_slot(cur, "R2", "R2-F", wv, pinnable=False)       # UNPINNABLE (no provenance, no round snapshot)
        g2, _ = mint_gate(cur, "R2", ["R2-D"])
        conn.commit()
        raised = False
        try:
            engine.reconcile_gate_targets(cur, g2, cfg=CFG, actor="system")
        except engine.TargetPackageNotReady as e:
            raised = True
            conn.rollback()
            check("unpinnable candidate raises TargetPackageNotReady naming the candidate", "R2-F" in e.candidates)
        if not raised:
            conn.rollback(); check("unpinnable candidate raises TargetPackageNotReady naming the candidate", False)
        check("TargetPackageNotReady is a readiness failure, not authorization",
              issubclass(engine.TargetPackageNotReady, engine.GateNotReady)
              and not issubclass(engine.TargetPackageNotReady, engine.GovernedDenial))
        # zero residue after rollback: no E/F target, no snapshot, no attachment audit for this gate
        cur.execute("SELECT count(*) AS n FROM gate_target WHERE gate_id=%s AND slot_id IN ('R2-E','R2-F')", (g2,))
        check("rollback left zero new gate_target rows", cur.fetchone()["n"] == 0)
        check("rollback left zero snapshot rows for the batch", snap_count(cur, g2) == 0)
        check("rollback left zero attachment audit for the batch",
              audit_count(cur, g2, "final_review_target_package_attached") == 0)

        # ---- Scenario 3: DB immutability (UPDATE + DELETE rejected) + PK uniqueness ----
        upd_blocked = del_blocked = pk_blocked = False
        try:
            cur.execute("UPDATE final_review_target_package SET script_revision=99 WHERE gate_id=%s AND slot_id='R1-B'", (g1,))
        except Exception:
            upd_blocked = True; conn.rollback()
        try:
            cur.execute("DELETE FROM final_review_target_package WHERE gate_id=%s AND slot_id='R1-B'", (g1,))
        except Exception:
            del_blocked = True; conn.rollback()
        try:
            cur.execute("INSERT INTO final_review_target_package (gate_id, slot_id, snapshot_id, round_id, "
                        "topic_id, topic_revision, script_id, script_revision, workflow_version_id, "
                        "workflow_version_source) VALUES (%s,'R1-B',%s,'R1',%s,1,%s,1,%s,'script_provenance')",
                        (g1, snap1, str(uuid.uuid4()), str(uuid.uuid4()), wv))
        except Exception:
            pk_blocked = True; conn.rollback()
        check("DB trigger rejects UPDATE of the immutable evidence", upd_blocked)
        check("DB trigger rejects DELETE of the immutable evidence", del_blocked)
        check("PK (gate_id, slot_id) rejects a duplicate snapshot", pk_blocked)

        # ---- Scenario 4: post-attachment canonical mutation cannot alter recorded evidence ----
        cur.execute("SELECT script_revision FROM final_review_target_package WHERE gate_id=%s AND slot_id='R1-B'", (g1,))
        before = cur.fetchone()["script_revision"]
        cur.execute("INSERT INTO script (script_id, slot_id, hcs_id, revision) VALUES (%s,'R1-B','1.1',2)", (str(uuid.uuid4()),))
        cur.execute("UPDATE slot_approval SET revision=2 WHERE slot_id='R1-B' AND artifact='script'")
        conn.commit()
        cur.execute("SELECT script_revision FROM final_review_target_package WHERE gate_id=%s AND slot_id='R1-B'", (g1,))
        check("recorded evidence is unchanged after a later current-state mutation",
              before == 1 and cur.fetchone()["script_revision"] == 1)

        # ---- Scenario 5: initial-open whole-batch helper contract ----
        mint_round(cur, "R3"); mint_slot(cur, "R3", "R3-G", wv); mint_slot(cur, "R3", "R3-H", wv, pinnable=False)
        conn.commit()
        pkgs = engine._validate_final_review_batch(cur, ["R3-G"])
        check("initial-open helper pins an all-pinnable batch", "R3-G" in pkgs)
        bad = False
        try:
            engine._validate_final_review_batch(cur, ["R3-G", "R3-H"])
        except engine.TargetPackageNotReady as e:
            bad = "R3-H" in e.candidates
        check("initial-open helper refuses a batch containing an unpinnable target", bad)

        # ---- Scenario 6: typed read model ----
        r = frtp.read(cur, g1, "R1-B")
        check("read: recorded -> status recorded + evidence present",
              r["recorded"] and r["status"] == "recorded" and r["evidence"]["script_revision"] == 1
              and r["evidence"]["workflow_version_source"] == "script_provenance")
        r = frtp.read(cur, g1, "R1-A")
        check("read: legacy target -> unknown_history, no reconstruction",
              (not r["recorded"]) and r["status"] == "unknown_history" and r["evidence"] is None)
        r = frtp.read(cur, g1, "not-a-target-slot")
        check("read: non-target pair -> unavailable", r["status"] == "unavailable")
        r = frtp.read(cur, "not-a-uuid", "R1-B")
        check("read: malformed gate id -> unavailable (no error)", r["status"] == "unavailable")

        # ---- #425 finding 3 — stage-aware read: a target on a NON-final_review gate is `unavailable` ----
        cur.execute("INSERT INTO gate (gate_id, scope, stage, policy, rule_key, quorum, status) "
                    "VALUES (%s,'batch','topic_review','fixed','any','any','open') RETURNING gate_id",
                    (str(uuid.uuid4()),))
        gtr = cur.fetchone()["gate_id"]
        cur.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,'R1-A')", (gtr,))
        conn.commit()
        check("read: target on a non-final_review gate -> unavailable (not unknown_history)",
              frtp.read(cur, gtr, "R1-A")["status"] == "unavailable")

        # ---- #425 finding 4 — DB rejects direct package evidence for a NON-final_review gate ----
        nonfinal_blocked = False
        try:
            cur.execute("INSERT INTO final_review_target_package (gate_id, slot_id, snapshot_id, round_id, "
                        "topic_id, topic_revision, script_id, script_revision, workflow_version_id, "
                        "workflow_version_source) VALUES (%s,'R1-A',%s,'R1',%s,1,%s,1,%s,'script_provenance')",
                        (gtr, snap1, str(uuid.uuid4()), str(uuid.uuid4()), wv))
        except Exception:
            nonfinal_blocked = True; conn.rollback()
        check("DB trigger rejects package evidence for a non-final_review gate", nonfinal_blocked)

        # ---- #425 finding 2 — REAL open_gate() path: initial open, rollback, replay/reuse ----
        seed_principals(cur); conn.commit()
        mint_round(cur, "R4"); mint_slot(cur, "R4", "R4-A", wv); mint_slot(cur, "R4", "R4-B", wv); conn.commit()
        g4 = engine.open_gate(conn, "final_review", round_id="R4", cfg=CFG_OPEN, actor="system")
        cur.execute("SELECT stage FROM gate WHERE gate_id=%s", (g4,))
        check("open_gate persisted a final_review gate", cur.fetchone()["stage"] == "final_review")
        cur.execute("SELECT count(*) AS n FROM gate_target WHERE gate_id=%s", (g4,))
        check("open_gate persisted both initial targets", cur.fetchone()["n"] == 2)
        check("open_gate persisted the gate-wide snapshot", engine._gate_snapshot_id(cur, g4) is not None)
        check("open_gate persisted an immutable package per target", snap_count(cur, g4) == 2)
        check("open_gate correlated an attachment audit per target",
              audit_count(cur, g4, "final_review_target_package_attached") == 2)
        cur.execute("SELECT count(*) AS n FROM gate_target gt WHERE gt.gate_id=%s AND NOT EXISTS "
                    "(SELECT 1 FROM final_review_target_package p WHERE p.gate_id=gt.gate_id "
                    "AND p.slot_id=gt.slot_id)", (g4,))
        check("no durable target was attached without its validated package", cur.fetchone()["n"] == 0)

        mint_round(cur, "R5"); mint_slot(cur, "R5", "R5-C", wv)
        mint_slot(cur, "R5", "R5-D", wv, pinnable=False); conn.commit()

        # #426 finding 2 — capture correlated global counts to prove ZERO transaction residue on the
        # underivable-candidate rollback (gate, gate_snapshot, gate_target, package, both audit kinds).
        def _open_counts():
            cur.execute("SELECT (SELECT count(*) FROM gate) AS gates, "
                        "(SELECT count(*) FROM gate_snapshot) AS snaps, "
                        "(SELECT count(*) FROM audit_log WHERE action='gate_opened') AS opened, "
                        "(SELECT count(*) FROM audit_log WHERE action='final_review_target_package_attached') AS att")
            return cur.fetchone()
        before = _open_counts()
        open_raised = False
        try:
            engine.open_gate(conn, "final_review", round_id="R5", cfg=CFG_OPEN, actor="system")
        except engine.TargetPackageNotReady as e:
            open_raised = True; conn.rollback()
            check("open_gate rollback names the underivable candidate", "R5-D" in e.candidates)
        if not open_raised:
            conn.rollback(); check("open_gate rollback names the underivable candidate", False)
        after = _open_counts()
        cur.execute("SELECT count(*) AS n FROM gate_target WHERE slot_id IN ('R5-C','R5-D')")
        check("open_gate rollback left zero target rows for the batch", cur.fetchone()["n"] == 0)
        cur.execute("SELECT count(*) AS n FROM final_review_target_package WHERE slot_id IN ('R5-C','R5-D')")
        check("open_gate rollback left zero package rows", cur.fetchone()["n"] == 0)
        check("open_gate rollback added no gate row", after["gates"] == before["gates"])
        check("open_gate rollback added no gate_snapshot row", after["snaps"] == before["snaps"])
        check("open_gate rollback added no gate_opened audit row", after["opened"] == before["opened"])
        check("open_gate rollback added no package-attachment audit row", after["att"] == before["att"])
        check("open_gate readiness refusal is not authorization",
              issubclass(engine.TargetPackageNotReady, engine.GateNotReady)
              and not issubclass(engine.TargetPackageNotReady, engine.GovernedDenial))

        g4b = engine.open_gate(conn, "final_review", round_id="R4", cfg=CFG_OPEN, actor="system")
        check("re-open of the same round reuses the existing gate", g4b == g4)
        check("reuse creates no duplicate package rows", snap_count(cur, g4) == 2)
        check("reuse creates no duplicate attachment audit",
              audit_count(cur, g4, "final_review_target_package_attached") == 2)

        # ---- #425 finding 1 — a legacy final_review gate (no gate-wide snapshot) refuses new targets ----
        mint_round(cur, "R6"); mint_slot(cur, "R6", "R6-A", wv); mint_slot(cur, "R6", "R6-B", wv)
        gleg = str(uuid.uuid4())
        cur.execute("INSERT INTO gate (gate_id, scope, stage, policy, rule_key, quorum, status) "
                    "VALUES (%s,'batch','final_review','fixed','all','all','open')", (gleg,))
        cur.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,'R6-A')", (gleg,))  # legacy, no snapshot
        conn.commit()
        # #426 finding 3 — repeat the SAME no-snapshot reconcile against the SAME legacy gate/candidates:
        # both attempts return the same typed readiness error + canonically-equivalent candidate set, and
        # each leaves zero new residue.
        def _legacy_attempt():
            try:
                engine.reconcile_gate_targets(cur, gleg, cfg=CFG, actor="system")
                return None   # a missing raise is a test failure
            except engine.TargetPackageNotReady as e:
                conn.rollback()
                return list(e.candidates)   # .candidates is canonically sorted
        c1 = _legacy_attempt()
        c2 = _legacy_attempt()
        check("legacy no-snapshot reconcile refuses on attempt 1 (names R6-B)", c1 == ["R6-B"])
        check("repeat refusal returns the same typed error + canonically-equivalent candidate set",
              c2 is not None and c1 == c2)
        cur.execute("SELECT (SELECT count(*) FROM gate_target WHERE gate_id=%s AND slot_id='R6-B') AS t, "
                    "(SELECT count(*) FROM final_review_target_package WHERE gate_id=%s) AS p, "
                    "(SELECT count(*) FROM audit_log WHERE entity='gate' AND entity_id=%s AND action IN "
                    "('final_review_target_package_attached','gate_targets_reconciled')) AS a",
                    (gleg, gleg, gleg))
        row = cur.fetchone()
        check("repeat legacy refusal left zero new target / package / attachment-audit rows",
              row["t"] == 0 and row["p"] == 0 and row["a"] == 0)
        check("legacy pre-existing target still reads unknown_history (not backfilled)",
              frtp.read(cur, gleg, "R6-A")["status"] == "unknown_history")

        # ---- #427 — additive final-review READ PROJECTION over real persisted evidence ----
        # A controlled recorded target: gate-wide snapshot with one role token + two frozen-eligible
        # principals, an immutable package referencing that gate-wide snapshot, one approve decision,
        # and its head-correct persisted coverage. Proves the composed groups, invariance against
        # later current-state changes, no target-level snapshot, and frozen-eligibility != authority.
        seed_principals(cur)
        mint_round(cur, "R7"); mint_slot(cur, "R7", "R7-A", wv); conn.commit()
        g7 = str(uuid.uuid4()); snap7 = str(uuid.uuid4()); stok = str(uuid.uuid4())
        cur.execute("INSERT INTO gate (gate_id, scope, stage, policy, rule_key, quorum, status) "
                    "VALUES (%s,'batch','final_review','fixed','any','any','open')", (g7,))
        cur.execute("INSERT INTO gate_snapshot (snapshot_id, gate_id, rule_key) VALUES (%s,%s,'any')", (snap7, g7))
        cur.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,'R7-A')", (g7,))
        cur.execute("INSERT INTO gate_snapshot_token (snapshot_token_id, snapshot_id, token_kind, "
                    "token_key, normalized_token) VALUES (%s,%s,'role','reviewer','role:reviewer')", (stok, snap7))
        cur.execute("INSERT INTO gate_snapshot_eligible (snapshot_token_id, principal_id) "
                    "VALUES (%s,'khal'),(%s,'huda')", (stok, stok))
        tid7, scid7 = str(uuid.uuid4()), str(uuid.uuid4())
        cur.execute("INSERT INTO final_review_target_package (gate_id, slot_id, snapshot_id, round_id, "
                    "topic_id, topic_revision, script_id, script_revision, workflow_version_id, "
                    "workflow_version_source) VALUES (%s,'R7-A',%s,'R7',%s,1,%s,1,%s,'script_provenance')",
                    (g7, snap7, tid7, scid7, wv))
        cur.execute("INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision) "
                    "VALUES (%s,'R7-A','khal','approve')", (g7,))
        cur.execute("INSERT INTO gate_token_coverage (gate_id, slot_id, snapshot_id, snapshot_token_id, "
                    "covering_principal_id) VALUES (%s,'R7-A',%s,%s,'khal')", (g7, snap7, stok))
        cur.execute("INSERT INTO audit_log (entity, entity_id, action, actor) "
                    "VALUES ('gate',%s,'gate_opened','system')", (g7,))
        conn.commit()

        p = frp.read(cur, g7, "R7-A")
        check("projection: recorded status + available", p["status"] == "recorded" and p["available"] is True)
        check("projection: zero uncertainty for a complete recorded target", p["uncertainty"] == [])
        check("projection: target identity is final_review + admitted + persisted lifecycle status",
              p["target_identity"]["gate_stage"] == "final_review" and p["target_identity"]["admitted"] is True
              and p["target_identity"]["gate_status"] == "open")
        check("projection: package evidence references the gate-wide snapshot",
              p["package"]["status"] == "recorded" and p["package"]["evidence"]["snapshot_id"] == snap7)
        check("projection: governing assignment is the gate-wide snapshot (id matches package)",
              p["assignment"]["snapshot_id"] == snap7)
        check("projection: frozen tokens + eligible principals recorded (sorted, both frozen)",
              p["assignment"]["tokens"][0]["normalized_token"] == "role:reviewer"
              and p["assignment"]["tokens"][0]["eligible_principals"] == ["huda", "khal"])
        check("projection: decision/coverage attributable to this (gate, slot, snapshot)",
              p["decision_evidence"]["governing_snapshot_id"] == snap7
              and p["decision_evidence"]["outcome"] == "approved"
              and p["decision_evidence"]["approval_count"] == 1
              and p["decision_evidence"]["distinct_principal_coverage"] == 1
              and p["decision_evidence"]["coverage"][0]["covered_by"] == "khal")
        check("projection: raw decision identifiers/timestamps surfaced",
              [d["approver_id"] for d in p["decision_evidence"]["decisions"]] == ["khal"]
              and p["decision_evidence"]["decisions"][0]["decided_at"] is not None)
        # #429 — audit is a SEPARATE, gate-scoped group, never nested in slot decision evidence, and
        # never reported as slot-attributable or `recorded`.
        check("projection: audit is a separate group, NOT nested in decision_evidence",
              "audit" not in p["decision_evidence"] and p["audit_evidence"] is not None)
        check("projection: audit group is gate-scoped, not slot-attributable, never recorded",
              p["audit_evidence"]["scope"] == "gate" and p["audit_evidence"]["slot_attributable"] is False
              and p["audit_evidence"]["status"] != "recorded"
              and frp.R_AUDIT_GATE_SCOPED_ONLY in p["audit_evidence"]["reasons"])
        check("projection: gate-scoped audit history surfaced as gate_scoped_history (not decision evidence)",
              p["audit_evidence"]["status"] == "gate_scoped_history"
              and any(e["action"] == "gate_opened" for e in p["audit_evidence"]["events"]))
        check("projection: frozen eligibility is NOT presented as present authorization",
              "authorized" not in p["assignment"]["tokens"][0] and "can_act" not in p["assignment"]["tokens"][0])
        check("projection: read created no target-level snapshot — exactly one gate-wide snapshot",
              snap_count(cur, g7) == 1)
        cur.execute("SELECT count(*) AS n FROM gate_snapshot WHERE gate_id=%s", (g7,))
        check("projection: still exactly one gate-wide gate_snapshot row (no per-target freeze)",
              cur.fetchone()["n"] == 1)

        # invariance — later CURRENT-state changes cannot alter the recorded projection.
        before = json.dumps(p, sort_keys=True, default=str)
        cur.execute("INSERT INTO topic (topic_id, slot_id, hcs_id, round_id, revision) VALUES (%s,'R7-A','1.1','R7',2)",
                    (str(uuid.uuid4()),))
        cur.execute("INSERT INTO script (script_id, slot_id, hcs_id, revision) VALUES (%s,'R7-A','1.1',2)",
                    (str(uuid.uuid4()),))
        cur.execute("UPDATE slot SET status='READY_FOR_PRODUCTION' WHERE slot_id='R7-A'")
        wf2 = str(uuid.uuid4())
        # move the CURRENT active workflow version: retire wv, activate a new one (one-active constraint
        # kept). The package's frozen workflow_version_id must remain wv regardless.
        cur.execute("UPDATE workflow_version SET status='retired' WHERE version_id=%s", (wv,))
        cur.execute("INSERT INTO workflow_version (version_id, workflow_id, version_no, status) "
                    "SELECT %s, workflow_id, 2, 'active' FROM workflow_version WHERE version_id=%s", (wf2, wv))
        cur.execute("INSERT INTO audit_log (entity, entity_id, action, actor) VALUES ('slot','R7-A','status_change','system')")
        conn.commit()
        after = json.dumps(frp.read(cur, g7, "R7-A"), sort_keys=True, default=str)
        check("projection: invariant against later topic/script/workflow/slot current-state changes",
              after == before)

        # package missing but governing gate snapshot present -> unknown_history w/ package codes, no missing-snapshot code.
        pa = frp.read(cur, g1, "R1-A")     # g1 has a gate_snapshot; R1-A is a legacy (no-package) target
        check("projection: legacy target w/ governing snapshot -> unknown_history + package codes, snapshot present",
              pa["status"] == "unknown_history" and frp.R_MISSING_PACKAGE in pa["uncertainty"]
              and frp.R_LEGACY in pa["uncertainty"] and frp.R_MISSING_GATE_SNAPSHOT not in pa["uncertainty"]
              and pa["assignment"] is not None)

        # legacy gate with NO governing snapshot -> unknown_history + missing-snapshot, null assignment/decision.
        pl = frp.read(cur, gleg, "R6-A")
        check("projection: legacy gate (no snapshot) -> missing-gate-snapshot + null assignment/decision",
              pl["status"] == "unknown_history" and frp.R_MISSING_GATE_SNAPSHOT in pl["uncertainty"]
              and pl["assignment"] is None and pl["decision_evidence"] is None)

        # non-admitted pair on a real final_review gate -> typed unavailable (not an error).
        pn = frp.read(cur, g7, "R7-NOPE")
        check("projection: non-admitted pair -> typed unavailable",
              pn["status"] == "unavailable" and pn["available"] is False)

        # no whole-batch (slot NULL) decisions are possible under the PK -> ambiguous code never fires here.
        check("projection: no ambiguous-attribution code for a clean per-slot target",
              frp.R_AMBIGUOUS_DECISION not in p["uncertainty"])

        # ---- #429 — corrected audit attribution + fail-closed ambiguity/incompleteness ----
        # (A) Slot-unattributable audit is NEVER promoted to slot decision evidence. Add a gate-scoped
        #     audit row with an unrelated action/actor, plus a SLOT-entity audit row for the SAME slot.
        #     The projection exposes only entity='gate' rows as gate-scoped history; the slot-entity row
        #     (no canonical gate/snapshot linkage) never appears, and decision_evidence carries no audit.
        cur.execute("INSERT INTO audit_log (entity, entity_id, action, actor) VALUES ('gate',%s,'note','someone_else')", (g7,))
        cur.execute("INSERT INTO audit_log (entity, entity_id, action, actor) VALUES ('slot','R7-A','slot_only_event','x')")
        conn.commit()
        pau = frp.read(cur, g7, "R7-A")
        gate_actions = {e["action"] for e in pau["audit_evidence"]["events"]}
        check("#429: audit_evidence surfaces only gate-scoped rows (unrelated gate event included)",
              "note" in gate_actions and "gate_opened" in gate_actions)
        check("#429: a slot-entity audit row is NOT admitted as this target's evidence",
              "slot_only_event" not in gate_actions and "audit" not in pau["decision_evidence"])
        check("#429: gate-scoped audit never marked slot-attributable or recorded",
              pau["audit_evidence"]["slot_attributable"] is False and pau["audit_evidence"]["status"] != "recorded")
        check("#429: decision/coverage remain recorded alongside gate-scoped audit (independent groups)",
              pau["decision_evidence"]["recorded"] is True and pau["status"] == "recorded")

        # (B) Incomplete/unavailable audit is NOT hidden behind recorded decision/coverage. A recorded
        #     target with NO gate-scoped audit rows: audit group is unavailable + incomplete, yet
        #     decision/coverage and the top-level slot status remain honestly recorded.
        mint_round(cur, "R8"); mint_slot(cur, "R8", "R8-A", wv); conn.commit()
        g8 = str(uuid.uuid4()); snap8 = str(uuid.uuid4()); stok8 = str(uuid.uuid4())
        cur.execute("INSERT INTO gate (gate_id, scope, stage, policy, rule_key, quorum, status) "
                    "VALUES (%s,'batch','final_review','fixed','any','any','open')", (g8,))
        cur.execute("INSERT INTO gate_snapshot (snapshot_id, gate_id, rule_key) VALUES (%s,%s,'any')", (snap8, g8))
        cur.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,'R8-A')", (g8,))
        cur.execute("INSERT INTO gate_snapshot_token (snapshot_token_id, snapshot_id, token_kind, "
                    "token_key, normalized_token) VALUES (%s,%s,'role','reviewer','role:reviewer')", (stok8, snap8))
        cur.execute("INSERT INTO gate_snapshot_eligible (snapshot_token_id, principal_id) VALUES (%s,'khal')", (stok8,))
        cur.execute("INSERT INTO final_review_target_package (gate_id, slot_id, snapshot_id, round_id, "
                    "topic_id, topic_revision, script_id, script_revision, workflow_version_id, "
                    "workflow_version_source) VALUES (%s,'R8-A',%s,'R8',%s,1,%s,1,%s,'script_provenance')",
                    (g8, snap8, str(uuid.uuid4()), str(uuid.uuid4()), wv))
        cur.execute("INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision) VALUES (%s,'R8-A','khal','approve')", (g8,))
        cur.execute("INSERT INTO gate_token_coverage (gate_id, slot_id, snapshot_id, snapshot_token_id, "
                    "covering_principal_id) VALUES (%s,'R8-A',%s,%s,'khal')", (g8, snap8, stok8))
        conn.commit()   # deliberately NO audit_log row for g8
        pnoaud = frp.read(cur, g8, "R8-A")
        check("#429: no gate audit -> audit group unavailable + incomplete code (not recorded)",
              pnoaud["audit_evidence"]["status"] == "unavailable"
              and frp.R_INCOMPLETE_AUDIT in pnoaud["audit_evidence"]["reasons"]
              and pnoaud["audit_evidence"]["status"] != "recorded")
        check("#429: unavailable audit is NOT hidden — decision/coverage + top-level still recorded",
              pnoaud["decision_evidence"]["recorded"] is True and pnoaud["status"] == "recorded"
              and pnoaud["available"] is True)

        # (C) Schema-impossible ambiguity boundary: a whole-batch (NULL-slot) gate_decision cannot be
        #     persisted — gate_decision PK (gate_id, approver_id, slot_id) forbids a NULL slot_id. Prove
        #     the write is rejected rather than simulating an impossible ambiguous row.
        null_slot_rejected = False
        try:
            cur.execute("INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision) "
                        "VALUES (%s,NULL,'khal','approve')", (g8,))
            conn.commit()
        except psycopg2.errors.NotNullViolation:
            null_slot_rejected = True; conn.rollback()
        except Exception:
            conn.rollback()
        check("#429: NULL-slot (whole-batch) gate_decision is schema-impossible (PK NOT NULL rejects it)",
              null_slot_rejected)

        cur.close(); conn.close()
    finally:
        cleanup(d, data)

    print()
    if FAIL:
        print(f"FAILED ({len(FAIL)}): " + "; ".join(FAIL))
        return 1
    print("ALL #423 target-package harness checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
