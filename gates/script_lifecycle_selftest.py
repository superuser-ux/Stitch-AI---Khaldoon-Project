"""#367 — governed Script review lifecycle vertical slice.

Proves the reconciled backend corrections (R3.1/R3.2/R3.3) over CANONICAL seams, with red/green on
each load-bearing control. Deterministic: the durable Script rework op is arbitrated by persisted
claim tokens and lease timestamps, never sleeps or process kills; the stub writer supplies content.

Sections:
  A  script generated v1 is inspectable with truthful (script) provenance
  B  edit appends v2, v1 byte-immutable
  C  approve threads the SCRIPT artifact; CAS validates against the SCRIPT head (R3.1/R3.2)
  D  drop threads the SCRIPT artifact; restore returns through the canonical transition
  E  durable Script rework produces a SCRIPT revision (not a topic), fenced by claim token (R3.3)
  F  non-latest / stale approval is typed and never silently moves the pin (R1)

Run: docker exec -e PYTHONPATH=/work:/work/gates:/work/agents <lane> python -m gates.script_lifecycle_selftest
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import engine  # noqa: E402
import run_writers as W  # noqa: E402

FAILS = []
RID = "RSL367"
APPROVER = "khal"


def check(label, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(label)


def _cur(conn):
    return conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)


def wipe(conn):
    c = conn.cursor()
    for stmt in (
        "DELETE FROM script_provenance WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM rework_operation WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM script_provenance WHERE job_id IN (SELECT job_id FROM generation_job WHERE round_id=%s)",
        "DELETE FROM generation_job WHERE round_id=%s",
        "DELETE FROM audit_log WHERE entity_id=%s",
        "DELETE FROM gate_decision WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)",
        "DELETE FROM gate_target WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM gate WHERE gate_id NOT IN (SELECT gate_id FROM gate_target)",
        "DELETE FROM directive WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM slot_review WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM slot_approval WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM script WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM topic WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)",
        "DELETE FROM slot WHERE round_id=%s",
        "DELETE FROM round WHERE round_id=%s",
    ):
        c.execute(stmt, (RID,) if "%s" in stmt else None)
    conn.commit(); c.close()


def seed_script_at_review(conn, cfg):
    """CANONICAL seam: a slot carrying an APPROVED topic, run through the real `process_script` (stub
    writer) so it holds a genuine generated Script v1 at DRAFT_ASSIGNED with a pinned topic approval.
    No authoritative-row fabrication — the script is produced by the writer path itself."""
    wipe(conn)
    c = conn.cursor()
    c.execute("""INSERT INTO round (round_id, period_len_days, posts_per_day, post_times,
                                    pillar_distribution, format_distribution, status)
                 VALUES (%s,7,1,'["09:00"]'::jsonb,'{}'::jsonb,'{}'::jsonb,'active')""", (RID,))
    c.execute("SELECT pillar_code FROM pillar ORDER BY pillar_code LIMIT 1")
    pil = c.fetchone()[0]
    c.execute("SELECT hcs_id FROM hcs WHERE pillar_code=%s ORDER BY hcs_id LIMIT 1", (pil,))
    hcs = c.fetchone()[0]
    c.execute("SELECT lens_id FROM lens ORDER BY lens_id LIMIT 1")
    lens = c.fetchone()[0]
    sid = f"{RID}-1"
    c.execute("""INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, format,
                                   hcs_id, lens, status)
                 VALUES (%s,%s,1,'09:00',%s,'Hero Reel',%s,%s,'TOPIC_APPROVED')""",
              (sid, RID, pil, hcs, lens))
    c.execute("""INSERT INTO topic (slot_id, hcs_id, lens, text_ar, hook_text, revision)
                 VALUES (%s,%s,%s,'موضوع','هوك',1)""", (sid, hcs, lens))
    c.execute("""INSERT INTO slot_approval (slot_id, artifact, revision, approver)
                 VALUES (%s,'topic',1,%s)""", (sid, APPROVER))
    conn.commit(); c.close()
    # the REAL writer path: TOPIC_APPROVED -> DRAFT_ASSIGNED, appends script v1
    scur = _cur(conn); scur.execute("SELECT * FROM slot WHERE slot_id=%s", (sid,))
    slot = scur.fetchone(); scur.close()
    W.process_script(conn, W._StubRunner(), None, cfg, slot, dry_run=False)
    return sid


def script_rows(conn, sid):
    c = _cur(conn)
    c.execute("SELECT revision, script_ar, final_line FROM script WHERE slot_id=%s ORDER BY revision", (sid,))
    r = c.fetchall(); c.close()
    return r


def topic_count(conn, sid):
    c = conn.cursor(); c.execute("SELECT count(*) FROM topic WHERE slot_id=%s", (sid,))
    n = c.fetchone()[0]; c.close(); return n


def open_script_gate(conn, cfg, sid):
    return engine.open_gate(conn, "script_review", round_id=RID, actor="t367", cfg=cfg)


def main():
    conn = engine.db_connect()
    cfg = engine.load_config()

    # ---------------------------------------------------------------- A
    print("\nA · GENERATED SCRIPT v1 IS INSPECTABLE WITH TRUTHFUL PROVENANCE")
    sid = seed_script_at_review(conn, cfg)
    rows = script_rows(conn, sid)
    check("exactly one script revision exists", len(rows), 1)
    check("it is v1", rows[0]["revision"], 1)
    revs = engine.list_revisions(conn, sid, artifact="script")
    check("list_revisions(script) returns the chain", len(revs), 1)
    c = _cur(conn)
    c.execute("SELECT status FROM slot WHERE slot_id=%s", (sid,))
    check("slot advanced to DRAFT_ASSIGNED", c.fetchone()["status"], "DRAFT_ASSIGNED")
    c.close()

    # ---------------------------------------------------------------- B
    print("\nB · EDIT APPENDS v2; v1 IS BYTE-IMMUTABLE")
    v1_before = script_rows(conn, sid)[0]
    engine.edit_revision(conn, sid, "script", "final_line", "سطر جديد", actor=APPROVER)
    rows = script_rows(conn, sid)
    check("a v2 was appended", [r["revision"] for r in rows], [1, 2])
    check("v1 content is byte-identical after the edit",
          (rows[0]["script_ar"], rows[0]["final_line"]),
          (v1_before["script_ar"], v1_before["final_line"]))
    check("v2 carries the edited field", rows[1]["final_line"], "سطر جديد")

    # ---------------------------------------------------------------- C
    print("\nC · APPROVE THREADS THE SCRIPT ARTIFACT; CAS VALIDATES THE SCRIPT HEAD (R3.1/R3.2)")
    # head is now script v2 (topic head is still 1). Gate open.
    gid = open_script_gate(conn, cfg, sid)
    # CAS against the SCRIPT head FIRST (gate still open): a stale expected_revision (1, while the
    # SCRIPT head is 2) must conflict — and it must conflict on the SCRIPT head. The topic head is 1,
    # so a topic-hardcoded CAS (the R3.1 defect) would have WRONGLY accepted expected_revision=1.
    conflicted = None
    try:
        engine.decide(conn, gid, APPROVER, "approve", slot_ids=[sid], revision=1,
                      expected_revision=1, cfg=cfg)
        conflicted = False
    except engine.RevisionConflict as e:
        conflicted = ("current head 2" in str(e))
    check("stale CAS against the SCRIPT head raises RevisionConflict (not the topic head)",
          conflicted, True)
    # now approve the real head (v2) with correct CAS, then resolve to PIN it.
    engine.decide(conn, gid, APPROVER, "approve", slot_ids=[sid], revision=2,
                  expected_revision=2, cfg=cfg)
    engine.resolve(conn, gid, actor="t367", cfg=cfg)
    c = _cur(conn)
    c.execute("SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact='script'", (sid,))
    check("script approval pinned the exact head (v2)", c.fetchone()["revision"], 2)
    c.execute("SELECT status FROM slot WHERE slot_id=%s", (sid,))
    check("the slot advanced to APPROVED_ASSIGNED on the head approval",
          c.fetchone()["status"], "APPROVED_ASSIGNED")
    c.close()

    # ---------------------------------------------------------------- D
    print("\nD · DROP THREADS THE SCRIPT ARTIFACT; RESTORE RETURNS CANONICALLY")
    # reset: fresh script item, no prior approval
    sid = seed_script_at_review(conn, cfg)
    gid = open_script_gate(conn, cfg, sid)
    engine.decide(conn, gid, APPROVER, "reject", slot_ids=[sid], cfg=cfg)
    engine.resolve(conn, gid, actor="t367", cfg=cfg)
    c = _cur(conn); c.execute("SELECT status FROM slot WHERE slot_id=%s", (sid,))
    check("drop moved the slot to REJECTED", c.fetchone()["status"], "REJECTED"); c.close()
    engine.reopen(conn, sid, actor="t367", cfg=cfg)
    c = _cur(conn); c.execute("SELECT status FROM slot WHERE slot_id=%s", (sid,))
    check("restore returned it to the script review status", c.fetchone()["status"],
          "DRAFT_ASSIGNED"); c.close()

    # ---------------------------------------------------------------- E
    print("\nE · DURABLE SCRIPT REWORK PRODUCES A SCRIPT REVISION, FENCED BY CLAIM TOKEN (R3.3)")
    sid = seed_script_at_review(conn, cfg)
    topics_before = topic_count(conn, sid)
    scripts_before = len(script_rows(conn, sid))
    began = engine.begin_rework_operation(conn, sid, 1, "make it punchier", APPROVER,
                                          idempotency_key=f"{sid}-rw1", artifact="script", cfg=cfg)
    op_id = began["op_id"]
    c = _cur(conn); c.execute("SELECT artifact FROM rework_operation WHERE op_id=%s", (op_id,))
    check("the op recorded artifact=script", c.fetchone()["artifact"], "script"); c.close()
    # the durable worker (begin restores base->new head, worker then reworks that head)
    W.run_rework_operation(cfg, op_id)
    after = script_rows(conn, sid)
    check("the SCRIPT chain grew (rework produced a new script revision)",
          len(after) > scripts_before, True)
    check("NO topic revision was produced (the R3.3 defect: worker regenerated a topic)",
          topic_count(conn, sid), topics_before)
    c = _cur(conn)
    c.execute("SELECT state, generated_revision FROM rework_operation WHERE op_id=%s", (op_id,))
    _op = c.fetchone()
    check("the op completed", _op["state"], "completed")
    check("the op's generated revision is the current SCRIPT head",
          _op["generated_revision"], after[-1]["revision"])
    # provenance is SCRIPT provenance, job-less, manual_rework (stored in effective_route)
    c.execute("""SELECT sp.effective_route FROM script_provenance sp JOIN script s
                   ON s.script_id=sp.script_id
                  WHERE s.slot_id=%s AND sp.job_id IS NULL ORDER BY sp.revision DESC LIMIT 1""", (sid,))
    _prov = c.fetchone(); c.close()
    check("a job-less SCRIPT rework provenance row exists (manual_rework)",
          _prov and _prov["effective_route"], "manual_rework")

    # E2 — the claim-token FENCE: a stale token cannot complete the op.
    sid = seed_script_at_review(conn, cfg)
    began = engine.begin_rework_operation(conn, sid, 1, "again", APPROVER,
                                          idempotency_key=f"{sid}-rw2", artifact="script", cfg=cfg)
    op_id = began["op_id"]
    claimed = engine.claim_rework_operation(conn, op_id)   # mints the real tenure token
    fenced = None
    c = conn.cursor()
    try:
        # a WRONG token must match zero rows -> GateError, no completion
        engine.complete_rework_operation(c, op_id, "00000000-0000-0000-0000-000000000000", 2,
                                         controller=APPROVER)
        fenced = False
    except engine.GateError:
        fenced = True
    conn.rollback(); c.close()
    check("a stale claim token cannot complete the Script rework op (fence holds)", fenced, True)
    assert claimed

    # ---------------------------------------------------------------- F
    print("\nF · STALE / NON-LATEST APPROVAL IS TYPED AND NEVER SILENTLY MOVES THE PIN (R1)")
    sid = seed_script_at_review(conn, cfg)                 # script v1
    gid = open_script_gate(conn, cfg, sid)
    engine.decide(conn, gid, APPROVER, "approve", slot_ids=[sid], revision=1, cfg=cfg)
    # now advance the head past the approved revision via an edit -> v2
    engine.edit_revision(conn, sid, "script", "final_line", "أحدث", actor=APPROVER)
    out = engine.resolve(conn, gid, actor="t367", cfg=cfg)
    check("resolving a superseded approval yields the typed stale_revision outcome",
          out.get(sid), "stale_revision")
    c = _cur(conn)
    c.execute("SELECT status FROM slot WHERE slot_id=%s", (sid,))
    check("the slot did NOT advance to APPROVED_ASSIGNED (pin never silently moved)",
          c.fetchone()["status"], "DRAFT_ASSIGNED")
    c.execute("SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact='script'", (sid,))
    _pin = c.fetchone(); c.close()
    check("no script pin was written for the superseded approval", _pin, None)

    # ---------------------------------------------------------------- G
    print("\nG · REQUEST-CHANGE THREADS THE SCRIPT ARTIFACT; TOPIC IS NOT MUTATED (finding 1/4)")
    import contract as K
    sid = seed_script_at_review(conn, cfg)
    topics_g = topic_count(conn, sid)
    scripts_g = len(script_rows(conn, sid))
    gid = open_script_gate(conn, cfg, sid)
    res = K.request_change(RID, "script", sid, "tighten the hook", actor=APPROVER)
    check("script request_change is accepted (routes to the script gate)", res.get("ok"), True)
    engine.resolve(conn, gid, actor="t367", cfg=cfg)
    c = _cur(conn); c.execute("SELECT status FROM slot WHERE slot_id=%s", (sid,))
    check("the slot moved to CHANGES_REQUESTED (script send-back)", c.fetchone()["status"],
          "CHANGES_REQUESTED"); c.close()
    check("NO topic revision was created by the script request_change (Topic non-mutation)",
          topic_count(conn, sid), topics_g)
    check("NO extra script revision either (request_change records a decision, not a write)",
          len(script_rows(conn, sid)), scripts_g)

    # ---------------------------------------------------------------- H
    print("\nH · ACTIVE SCRIPT REWORK FENCES + PROJECTS rework_active (finding 2/4)")
    sid = seed_script_at_review(conn, cfg)
    began = engine.begin_rework_operation(conn, sid, 1, "reworking", APPROVER,
                                          idempotency_key=f"{sid}-h", artifact="script", cfg=cfg)
    # the op is queued/un-generated -> the item is fenced. Do NOT run the worker, so it stays active.
    acts = engine.topic_item_actions(_cur(conn), sid, "script")
    check("the typed action map projects edit as denied:rework_active",
          (acts["edit"]["allowed"], acts["edit"].get("reason")), (False, "rework_active"))
    check("...and rework/drop/approve are likewise denied:rework_active",
          [acts[k].get("reason") for k in ("rework", "drop", "approve")],
          ["rework_active", "rework_active", "rework_active"])
    # the guard itself fails a competing mutation closed
    denied = None
    try:
        engine.edit_revision(conn, sid, "script", "final_line", "race", actor=APPROVER)
        denied = False
    except engine.GovernedDenial as e:
        denied = (getattr(e, "reason", None) == "rework_active")
    check("a competing edit is fenced closed while the script rework is active", denied, True)
    # and a TOPIC rework on a different slot is NOT affected by this script fence (artifact-scoped)
    assert began

    # ---------------------------------------------------------------- I
    print("\nI · TYPED ARTIFACT BOUNDARY — closed topic|script, topic default (review gap 2)")
    import api as _api
    from pydantic import ValidationError as _VE
    # absent -> topic default (V1 compatibility): the request body validates and defaults topic
    check("RequestChangeBody defaults artifact=topic", _api.RequestChangeBody(comment="x").artifact, "topic")
    check("ApproveBody defaults artifact=topic",
          _api.ApproveBody(expected_revision=1).artifact, "topic")
    check("DropBody defaults artifact=topic", _api.DropBody().artifact, "topic")
    # a script value is accepted
    check("artifact=script is accepted",
          _api.RequestChangeBody(comment="x", artifact="script").artifact, "script")
    # an INVALID value is a typed validation error (surfaces as 422 before the handler, so it never
    # reaches contract._artifact's unhandled ValueError)
    # the THREE bodies I introduced PLUS the sibling lifecycle bodies (edit/restore/rework_from) the V2
    # controls POST to — the whole mutation family is now a closed domain (Codex ruling: option a).
    check("EditBody defaults artifact=topic",
          _api.EditBody(field="final_line", value="x").artifact, "topic")
    check("RestoreBody defaults artifact=topic", _api.RestoreBody(revision=1).artifact, "topic")
    check("ReworkFromBody defaults artifact=topic",
          _api.ReworkFromBody(revision=1, comment="c").artifact, "topic")
    for M, kw in ((_api.RequestChangeBody, {"comment": "x", "artifact": "bogus"}),
                  (_api.ApproveBody, {"expected_revision": 1, "artifact": "nope"}),
                  (_api.DropBody, {"artifact": "topics"}),
                  (_api.EditBody, {"field": "final_line", "value": "x", "artifact": "bad"}),
                  (_api.RestoreBody, {"revision": 1, "artifact": "xx"}),
                  (_api.ReworkFromBody, {"revision": 1, "comment": "c", "artifact": "nope"})):
        rejected = False
        try:
            M(**kw)
        except _VE:
            rejected = True
        check(f"{M.__name__} rejects an out-of-domain artifact (typed 4xx, not ValueError)", rejected, True)
    # the GET reads (revisions, topic_item) are the same class — a bad artifact previously fell to the
    # SCRIPT branch and silently returned wrong-artifact data. Their query param is now the closed
    # Literal too, so FastAPI 422s an out-of-domain value at parsing (V2 was already fenced by
    # resolveAllowedQuery; this closes the direct-caller read path).
    import typing as _t
    for fn in (_api.revisions, _api.topic_item):
        ann = _t.get_type_hints(fn).get("artifact")
        vals = set(_t.get_args(ann))
        check(f"GET {fn.__name__} artifact is the closed topic|script domain", vals, {"topic", "script"})

    wipe(conn)
    print("\n" + "=" * 60)
    if FAILS:
        print(f"{len(FAILS)} CHECK(S) FAILED")
        for f in FAILS:
            print(f"  - {f}")
        print("=" * 60)
        sys.exit(1)
    print("ALL CHECKS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
