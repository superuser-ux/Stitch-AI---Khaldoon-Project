"""Gate + two-stage flow proof (M4.1). Runs the FULL corrected pipeline on an isolated
throwaway round (RSELF) with a fake LLM (no Groq), leaving the real R1 batch untouched:

  plan(seed) -> topics -> topic_review (approve some; request-change one WITH a comment ->
  topic regenerates as a new revision) -> scripts for APPROVED topics ONLY -> script_review
  -> APPROVED_ASSIGNED -> multi-approver final_review (quorum all) -> SCHEDULED.

Asserts an audit_log row for every transition. Idempotent (tears RSELF down at start+end).

  docker run --rm --network tanaghom_default --env-file .env -e DB_HOST=db -e DB_PORT=5432 \
    -v "$PWD":/work -w /work python:3.12-slim \
    bash -lc "pip install -q -r gates/requirements.txt -r agents/requirements.txt && python gates/selftest.py"
"""
import hashlib
import json
import math
import os
import sys
import copy
import re

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # repo root, for integrations/
import engine          # noqa: E402
import run_writers as W  # noqa: E402

FAILS = []
RID = "RSELF"
SLOTS = [("RSELF-1", "P1_SELF", "1.1"), ("RSELF-2", "P1_SELF", "1.2"),
         ("RSELF-3", "P2_RELATIONSHIPS", "2.1"), ("RSELF-4", "P3_PARENTING", "3.1")]


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got} want={want}")
    if not ok:
        FAILS.append(label)


def _raises(fn):
    try:
        fn()
        return False
    except engine.GateError:
        return True


def _raises_nyi(fn):
    try:
        fn()
        return False
    except NotImplementedError:
        return True


def guard_slot(slot_id):
    """ISOLATION GUARD — this proof must NEVER write to a real round. Every mutating call goes
    through a slot id that starts with the throwaway prefix; anything else aborts the run."""
    if not str(slot_id).startswith(RID + "-"):
        raise AssertionError(f"ISOLATION VIOLATION: selftest tried to touch non-{RID} slot {slot_id!r}")


# --- fake LLM (deterministic, no network) ---------------------------------- #
class FakeEmbed:
    def embed(self, text):
        out = []
        i = 0
        while len(out) < 1024:
            d = hashlib.sha256(f"{text}|{i}".encode()).digest()
            out.extend((b / 127.5 - 1.0) for b in d)   # centred -> near-orthogonal -> low cos sim
            i += 1
        v = out[:1024]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


class FakeChat:
    def __init__(self, kind):
        self.kind, self.model, self.n = kind, "fake:test", 0

    def complete(self, system, user):
        self.n += 1
        rework = "REWORK DIRECTIVE" in user or "REVIEWER COMMENT" in user
        wants_family = bool(re.search(r"(الأهل|الوالدين|الأب|الأم)", user))
        wants_new_ending = bool(re.search(r"(اختم|النهاية|الخاتمة|final line|closing)", user))
        if self.kind == "topic":
            return json.dumps({
                "maps_to_hcs": True,
                "topic_angle": (("زاوية معدّلة بعد ملاحظة المراجِع"
                                 + (" بشكل يخاطب الأب والأم معاً" if wants_family and rework else ""))
                                if rework else f"زاوية تجريبية رقم {self.n}"),
                "hook_text": ("الخوف بيوقف خطوتك الجاية" if rework else "الخوف بياكل قرارك اليوم"),
                "hook_type": "Painful Truth",
                "rationale_ar": "سبب مختصر ليش هاد الموضوع هلأ",
                "rationale_en": "why this topic now (test)"}, ensure_ascii=False)
        return json.dumps({
            "script_ar": (("نص معدّل بعد ملاحظة المراجِع. "
                          + ("الكلام هون موجّه للأب والأم مع بعض. " if wants_family and rework else ""))
                         if rework else "")
                         + "هاد النص تجريبي بالعامية الفلسطينية، بحكي عن الموضوع بشكل واضح ومختصر.",
            # #149 — emit the registry-driven structure keys the prompt advertises (format-aware).
            "structure": {k: ".." for k in W._structure_keys_from_prompt(user)},
            "final_line": ("هاي نهاية جديدة واضحة ومقصودة" if wants_new_ending and rework else "السطر الأخير"),
            "delivery_notes": "نبرة هادئة",
            "used_islamic_anchor": False, "anchor_justification": "", "uses_dialect": True,
            "delivery_check": {"scroll_stop_hook": True, "emotional_journey": True, "metaphor": True,
                               "scientific_truth": True, "quran_or_hadith_organic": False,
                               "light_human_moment": True, "unforgettable_final_line": True}},
            ensure_ascii=False)


# --- DB helpers ------------------------------------------------------------- #
def status_counts(conn):
    cur = conn.cursor()
    cur.execute("SELECT status, count(*) FROM slot WHERE round_id=%s GROUP BY status", (RID,))
    return dict(cur.fetchall())


def max_audit(conn):
    cur = conn.cursor(); cur.execute("SELECT coalesce(max(id),0) FROM audit_log")
    return cur.fetchone()[0]


def audit_since(conn, since, action):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM audit_log WHERE id>%s AND action=%s "
                "AND entity_id LIKE 'RSELF-%%'", (since, action))
    return cur.fetchone()[0]


def fetch(conn, status=None, slot_id=None):
    cur = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    q, p = "SELECT * FROM slot WHERE round_id=%s", [RID]
    if status:
        q += " AND status=%s"; p.append(status)
    if slot_id:
        q += " AND slot_id=%s"; p.append(slot_id)
    q += " ORDER BY slot_id"
    cur.execute(q, p); return cur.fetchall()


def directives_for(conn, slot_id, to_stage=None):
    cur = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    if to_stage:
        cur.execute("SELECT * FROM directive WHERE slot_id=%s AND to_stage=%s ORDER BY created_at",
                    (slot_id, to_stage))
    else:
        cur.execute("SELECT * FROM directive WHERE slot_id=%s ORDER BY created_at", (slot_id,))
    rows = cur.fetchall(); cur.close()
    return rows


def teardown(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RSELF-%%' "
                "OR entity_id IN (SELECT gate_id::text FROM gate g JOIN gate_target t USING(gate_id) "
                "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (RID,))
    cur.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t "
                "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (RID,))
    cur.execute("DELETE FROM asset       WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM directive   WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM topic       WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM script      WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM slot_review   WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM slot_approval WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (RID,))
    # #359 — a topic_review acceptance now mints a Script generation_job in the SAME transaction, so
    # this round can own durable job rows. Referential order matters: script_provenance references
    # generation_job, which references round.
    cur.execute("DELETE FROM script_provenance WHERE job_id IN "
                "(SELECT job_id FROM generation_job WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM generation_job WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM slot   WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM script_provenance WHERE job_id IN "
                "(SELECT job_id FROM generation_job WHERE round_id=%s)", (RID,))
    cur.execute("DELETE FROM generation_job WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM round  WHERE round_id=%s", (RID,))
    cur.execute("DELETE FROM principal WHERE principal_id IN "
                "('rep.selftest','rep.noperm','agent.selftest')")
    conn.commit()


def seed(conn):
    """Seed the throwaway round under a DEDICATED tenant ('selftest') so the proof is isolated
    from real content on every axis (round + tenant), not just by id prefix."""
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id,module)
                   VALUES (%s,'selftest',1,4,'["09:00"]','{}','{}','planning','selftest','content')""",
                (RID,))
    # M9·B3 actor-model fixtures: an autonomous agent-rep (with waive permission), an autonomous
    # rep WITHOUT permission, and a low-autonomy agent — to exercise autonomy × permission paths.
    cur.execute("""INSERT INTO principal (principal_id,kind,role,owner_id,autonomy_level,permissions)
        VALUES ('rep.selftest','agent_rep','rep','khal','autonomous','["review.waive","review.dispose"]'),
               ('rep.noperm','agent_rep','rep','khal','autonomous','[]'),
               ('agent.selftest','agent','writer',NULL,'propose_only','[]')
        ON CONFLICT (principal_id) DO NOTHING""")
    for sid, pillar, hcs in SLOTS:
        guard_slot(sid)
        cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                       hook_type,status,cycle_no,tenant_id,module)
                       VALUES (%s,%s,1,'09:00',%s,%s,'L1','Painful Truth','RESERVED',1,'selftest','content')""",
                    (sid, RID, pillar, hcs))
    conn.commit()


# --- #265 generated-slot <-> review-gate convergence (isolated round) --------- #
R265 = "R265"
# reuse known-good pillar/hcs taxonomy pairs (same ones RSELF uses) so FKs resolve
S265_TAX = {"R265-1": ("P1_SELF", "1.1"), "R265-2": ("P1_SELF", "1.2"),
            "R265-3": ("P2_RELATIONSHIPS", "2.1"), "R265-4": ("P3_PARENTING", "3.1"),
            "R265-5": ("P1_SELF", "1.1"), "R265-6": ("P2_RELATIONSHIPS", "2.1")}


def _cleanup_265(conn):
    cur = conn.cursor()
    cur.execute("DELETE FROM gate_decision WHERE gate_id IN (SELECT DISTINCT t.gate_id FROM gate_target t "
                "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (R265,))
    # deleting the gate cascades its gate_target rows (ON DELETE CASCADE)
    cur.execute("DELETE FROM gate WHERE gate_id IN (SELECT DISTINCT t.gate_id FROM gate_target t "
                "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (R265,))
    cur.execute("DELETE FROM slot_review WHERE slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (R265,))
    cur.execute("DELETE FROM slot WHERE round_id=%s", (R265,))
    cur.execute("DELETE FROM script_provenance WHERE job_id IN "
                "(SELECT job_id FROM generation_job WHERE round_id=%s)", (R265,))
    cur.execute("DELETE FROM generation_job WHERE round_id=%s", (R265,))
    cur.execute("DELETE FROM round WHERE round_id=%s", (R265,))
    conn.commit()


def _seed_265(conn, pairs):
    """Seed R265 (dedicated 'selftest' tenant) with one slot per (slot_id, status) pair — inserted
    directly at the given status to model generated/ungenerated slots without running the writer."""
    cur = conn.cursor()
    cur.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                   pillar_distribution,format_distribution,status,tenant_id,module)
                   VALUES (%s,'selftest-265',1,6,'["09:00"]','{}','{}','planning','selftest','content')
                   ON CONFLICT (round_id) DO NOTHING""", (R265,))
    for sid, status in pairs:
        assert sid.startswith("R265-"), f"isolation guard: refusing to seed {sid!r} outside R265"
        pillar, hcs = S265_TAX[sid]
        cur.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                       hook_type,status,cycle_no,tenant_id,module)
                       VALUES (%s,%s,1,'09:00',%s,%s,'L1','Painful Truth',%s,1,'selftest','content')""",
                    (sid, R265, pillar, hcs, status))
    conn.commit()


def _set_status_265(conn, slot_ids, status):
    cur = conn.cursor()
    cur.execute("UPDATE slot SET status=%s WHERE round_id=%s AND slot_id = ANY(%s)",
                (status, R265, list(slot_ids)))
    conn.commit()


def _raw_target_count(conn, gate_id):
    """Count gate_target rows DIRECTLY (bypasses get_gate's self-healing reconcile)."""
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM gate_target WHERE gate_id=%s", (gate_id,))
    return cur.fetchone()[0]


def _audit_count(conn, gate_id, action):
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM audit_log WHERE entity='gate' AND entity_id=%s AND action=%s",
                (str(gate_id), action))
    return cur.fetchone()[0]


def _reconcile_audit(conn, gate_id):
    cur = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    cur.execute("SELECT detail FROM audit_log WHERE entity='gate' AND entity_id=%s "
                "AND action='gate_targets_reconciled' ORDER BY at DESC LIMIT 1", (str(gate_id),))
    row = cur.fetchone()
    d = row["detail"] if row else {}
    return {"added_count": d.get("added_count"), "resulting_count": d.get("resulting_count"),
            "added": d.get("added")}


def test_265_reconcile(conn, cfg):
    print("\n#265) generated-slot <-> review-gate convergence")
    _cleanup_265(conn)

    # ---- A. server-authoritative generation-complete guard (normal path) ----
    _seed_265(conn, [("R265-1", "TOPIC_PROPOSED"), ("R265-2", "TOPIC_PROPOSED"),
                     ("R265-3", "SCHEDULE_APPROVED"), ("R265-4", "SCHEDULE_APPROVED"),
                     ("R265-5", "SCHEDULE_APPROVED"), ("R265-6", "SCHEDULE_APPROVED")])
    check("#265A start_review REFUSED while 4 slots still awaiting generation (server-authoritative)",
          _raises(lambda: engine.open_gate(conn, "topic_review", round_id=R265, actor="selftest", cfg=cfg)),
          True)
    # generation completes: the 4 inputs become review-eligible → the FIRST gate opens with all 6
    _set_status_265(conn, ["R265-3", "R265-4", "R265-5", "R265-6"], "TOPIC_PROPOSED")
    g_norm = engine.open_gate(conn, "topic_review", round_id=R265, actor="selftest", cfg=cfg)
    check("#265A normal path: first gate opens only after full generation, with all 6 targets",
          len(engine.get_gate(conn, g_norm)["targets"]), 6)

    # ---- B. recovery: a LEGACY 2-of-6 gate reconciles to 6 on reuse ----
    _cleanup_265(conn)
    _seed_265(conn, [(f"R265-{i}", "TOPIC_PROPOSED") for i in range(1, 7)])
    # legacy inconsistency: a gate opened over only 2 of 6 eligible slots (explicit slot_ids models
    # the pre-existing bad state; it is NOT newly-permitted behaviour)
    g = engine.open_gate(conn, "topic_review", slot_ids=["R265-1", "R265-2"], round_id=R265,
                         actor="selftest", cfg=cfg)
    check("#265B legacy gate seeded with only 2 targets (raw count)", _raw_target_count(conn, g), 2)
    before = _audit_count(conn, g, "gate_targets_reconciled")
    # reconcile-on-reuse: a round-scoped open converges the SAME gate to the full population
    g2 = engine.open_gate(conn, "topic_review", round_id=R265, actor="selftest", cfg=cfg)
    check("#265B reuse returns the SAME gate (one active review per round+stage)", g2 == g, True)
    check("#265B reused gate reconciled to all 6 targets (raw count)", _raw_target_count(conn, g), 6)
    check("#265B reconciliation audited once, with the 4 added slots and correct counts",
          _reconcile_audit(conn, g),
          {"added_count": 4, "resulting_count": 6, "added": ["R265-3", "R265-4", "R265-5", "R265-6"]})
    # idempotent: reconciling again (read + reuse) adds nothing and emits NO further event
    engine.get_gate(conn, g)
    engine.open_gate(conn, "topic_review", round_id=R265, actor="selftest", cfg=cfg)
    check("#265B reconcile is idempotent (no duplicate targets)", _raw_target_count(conn, g), 6)
    check("#265B idempotent no-op emits no extra reconcile audit",
          _audit_count(conn, g, "gate_targets_reconciled"), before + 1)

    # ---- C. read models converge (stage_state no longer contradicts the gate) ----
    st = engine.stage_state(conn, R265, "topic_review", cfg=cfg)
    check("#265C stage_state: review_pending == in_review == 6 (contradiction resolved)",
          (st["review_pending"], st["in_review"]), (6, 6))
    check("#265C stage_state reports reconciliation_ok with no inconsistency warning",
          (st["reconciliation_ok"], any("Inconsistent review gate" in w for w in st["warnings"])),
          (True, False))

    # ---- D. prior decisions are preserved across reconciliation ----
    _cleanup_265(conn)
    _seed_265(conn, [(f"R265-{i}", "TOPIC_PROPOSED") for i in range(1, 7)])
    g = engine.open_gate(conn, "topic_review", slot_ids=["R265-1", "R265-2"], round_id=R265,
                         actor="selftest", cfg=cfg)
    engine.decide(conn, g, "khal", "approve", slot_ids=["R265-1"], cfg=cfg)
    engine.open_gate(conn, "topic_review", round_id=R265, actor="selftest", cfg=cfg)   # reconciling reuse
    gate = engine.get_gate(conn, g)
    by = {t["slot_id"]: t["current_outcome"] for t in gate["targets"]}
    check("#265D reconcile preserves the prior decision (R265-1 approved), adds the rest undecided",
          (by.get("R265-1"), by.get("R265-3"), len(gate["targets"])),
          ("approved", "pending", 6))

    _cleanup_265(conn)


# --- the proof -------------------------------------------------------------- #
def _durable_gen_job_265(conn, round_id, stage="topic", status="running"):
    """#364 — the in-flight fixture is now a DURABLE row, because durable truth is what the guard
    reads. The prior version injected an in-process registry record, which no longer carries
    authority (and, keyed on the gate-stage string, never matched the governed Stage 2A paths in
    the first place). Every assertion around these fixtures is unchanged."""
    c = conn.cursor()
    c.execute("""INSERT INTO generation_job (round_id, stage, status, accepted_schedule_token,
                                             lease_expires_at, claimed_by)
                 VALUES (%s,%s,%s,%s, now() + interval '1 hour', 'selftest-265')
                 RETURNING job_id::text""",
              (round_id, stage, status, abs(hash(round_id)) % 90000))
    jid = c.fetchone()[0]
    conn.commit(); c.close()
    return jid


def _drop_gen_job_265(conn, job_id):
    c = conn.cursor()
    c.execute("DELETE FROM generation_job WHERE job_id=%s", (job_id,))
    conn.commit(); c.close()


def main():
    cfg = engine.load_config()
    conn = engine.db_connect()
    teardown(conn); seed(conn)
    a0 = max_audit(conn)
    tchat, schat, emb = FakeChat("topic"), FakeChat("script"), FakeEmbed()
    print(f"seeded {RID}: {status_counts(conn)}")

    # 0b) Developer-route resilience (Groq Llama 3.3 -> Groq Qwen 3.6 ->
    # GFWS Ollama config-ready). Pure config/mechanism proofs: ORDER,
    # FAILOVER, NO silent model substitution (truthful per-hop attribution), and
    # CONFIG-ONLY reversibility. No network — fake clients + explicit config dicts.
    print("\n0b) developer-route resilience (order / failover / no-silent-substitution / reversibility)")

    def _raises_provider(fn):
        try:
            fn(); return False
        except W.ProviderError:
            return True

    class _RouteClient:
        def __init__(self, tag, fail=False):
            self.tag, self.fail, self.calls = tag, fail, 0
        def complete(self, system, user):
            self.calls += 1
            if self.fail:
                raise W.ProviderError(f"{self.tag} forced failure")
            return f"OK::{self.tag}"

    # EXECUTABLE route is exactly 2 hops: Groq Llama 3.3 -> Groq Qwen 3.6.
    # GFWS is the authorized final LOGICAL hop but DEFERRED — it must NOT appear as an
    # executable fallback (no false `ollama`/host-local hop masquerading as GFWS).
    _route = {"temperature": 0.85, "max_tokens": 1500,
              "primary": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
              "fallback": [
                  {"provider": "groq", "model": "qwen/qwen3.6-27b"}]}
    _rr = W.build_stage_runner(cfg["providers"], _route, "topic")
    _labels = [lbl for lbl, _ in _rr.clients]
    check("developer config order: exact active route (Groq Llama 3.3 -> Groq Qwen 3.6)",
          _labels, ["groq:llama-3.3-70b-versatile", "groq:qwen/qwen3.6-27b"])
    check("developer route has no injected/dropped hops", len(_labels), 2)
    check("#230 no false GFWS/ollama executable hop (deferred logical hop only)",
          any(lbl.startswith("ollama") for lbl in _labels), False)
    check("developer fallback carries no injected params", _rr.clients[1][1].params, {})
    check("developer primary carries no injected params", _rr.clients[0][1].params, {})

    # primary serves first, attribution truthful, fallback untouched
    _c_llama, _c_qwen = _RouteClient("llama"), _RouteClient("qwen")
    _sr = W.StageRunner("topic", [("groq:llama-3.3-70b-versatile", _c_llama),
                                  ("groq:qwen/qwen3.6-27b", _c_qwen)])
    check("developer primary serves when healthy", _sr.complete("s", "u"), "OK::llama")
    check("developer attribution truthful for served primary", _sr.model,
          "groq:llama-3.3-70b-versatile")
    check("developer fallback not touched when primary healthy", _c_qwen.calls, 0)

    # induced primary failure -> Qwen serves; .model reports the actual hop
    _f_llama, _f_qwen = _RouteClient("llama", fail=True), _RouteClient("qwen")
    _sr2 = W.StageRunner("topic", [("groq:llama-3.3-70b-versatile", _f_llama),
                                   ("groq:qwen/qwen3.6-27b", _f_qwen)])
    check("developer failover reaches Qwen on primary failure", _sr2.complete("s", "u"), "OK::qwen")
    check("developer primary attempted exactly once before fall-through", _f_llama.calls, 1)
    check("developer no silent substitution: model reports actual served hop",
          _sr2.model, "groq:qwen/qwen3.6-27b")

    # all hops fail -> raises (never a silent success)
    _sr3 = W.StageRunner("topic", [("openrouter:x", _RouteClient("a", fail=True)),
                                   ("groq:y", _RouteClient("b", fail=True))])
    check("#230 all-fail raises ProviderError (no silent success)",
          _raises_provider(lambda: _sr3.complete("s", "u")), True)

    # reversibility: a pure config edit can promote the fallback without code changes
    _rev = W.build_stage_runner(cfg["providers"],
                                dict(_route, primary={"provider": "groq",
                                                      "model": "qwen/qwen3.6-27b"}),
                                "topic")
    check("developer route reversible by config alone",
          _rev.clients[0][0], "groq:qwen/qwen3.6-27b")

    # the tracked developer default encodes the route for both voice-critical stages
    import yaml as _yaml
    _ex = _yaml.safe_load((W.REPO / "system_config.example.yaml").read_text(encoding="utf-8"))
    for _stage, _temp, _maxt in (("topic_hook", 0.85, 1500), ("script", 0.8, 2500)):
        _m = _ex["models"][_stage]
        check(f"developer default: {_stage} primary is Groq Llama 3.3",
              (_m["primary"]["provider"], _m["primary"]["model"]), ("groq", "llama-3.3-70b-versatile"))
        check(f"developer default: {_stage} exact fallback is Groq Qwen 3.6",
              [(f["provider"], f["model"]) for f in _m["fallback"]],
              [("groq", "qwen/qwen3.6-27b")])
        check(f"#230 tracked default: {_stage} has NO executable GFWS/ollama hop (deferred logical only)",
              any(f["provider"] in ("ollama", "ollama_embed") for f in _m["fallback"]), False)
        check(f"#230 tracked default: {_stage} preserves temperature/max_tokens",
              (_m["temperature"], _m["max_tokens"]), (_temp, _maxt))

    # 1) TOPICS: RESERVED -> TOPIC_PROPOSED (topic + hook + bilingual rationale; no script)
    print("\n1) topics")
    for s in fetch(conn, "RESERVED"):
        guard_slot(s["slot_id"])
        W.process_topic(conn, tchat, None, emb, cfg, s, dry_run=False)
    check("all topics proposed", status_counts(conn).get("TOPIC_PROPOSED"), 4)
    t1 = fetch(conn, slot_id="RSELF-1")[0]
    cur = conn.cursor()
    cur.execute("SELECT rationale_ar, rationale_en FROM topic WHERE slot_id='RSELF-1'")
    rat = cur.fetchone()
    check("topic rationale persisted (bilingual)", bool(rat[0] and rat[1]), True)

    # 2) TOPIC_REVIEW: approve 3, request-change 1 WITH a comment
    print("\n2) topic_review (approve 3, request-change RSELF-4 with a comment)")
    g = engine.open_gate(conn, "topic_review", round_id=RID, actor="selftest", cfg=cfg)
    check("topic gate reviews TOPIC_PROPOSED (4 targets)", len(engine.get_gate(conn, g)["targets"]), 4)
    engine.decide(conn, g, "khal", "approve", slot_ids=["RSELF-1", "RSELF-2", "RSELF-3"], cfg=cfg)
    engine.decide(conn, g, "khal", "request_change", slot_ids=["RSELF-4"],
                  notes="وضّح الزاوية أكثر وخليها أقرب لتجربة الأهل", cfg=cfg)
    out = engine.resolve(conn, g, actor="selftest", cfg=cfg)
    check("topic resolve", {k: out[k] for k in sorted(out)},
          {"RSELF-1": "approved", "RSELF-2": "approved", "RSELF-3": "approved",
           "RSELF-4": "changes_requested"})
    sc = status_counts(conn)
    check("3 topics approved", sc.get("TOPIC_APPROVED"), 3)
    check("change-requested slot parked at CHANGES_REQUESTED (NOT left TOPIC_PROPOSED)",
          (sc.get("CHANGES_REQUESTED"), sc.get("TOPIC_PROPOSED")), (1, None))

    # 3) SCRIPTS run on APPROVED topics ONLY (the sent-back one must NOT be scripted)
    print("\n3) scripts (approved topics only)")
    for s in fetch(conn, "TOPIC_APPROVED"):
        guard_slot(s["slot_id"])
        W.process_script(conn, schat, None, cfg, s, dry_run=False)
    sc = status_counts(conn)
    check("3 approved topics -> DRAFT_ASSIGNED", sc.get("DRAFT_ASSIGNED"), 3)
    check("sent-back slot NOT scripted (still CHANGES_REQUESTED)", sc.get("CHANGES_REQUESTED"), 1)
    cur.execute("SELECT count(*) FROM script WHERE slot_id='RSELF-4'")
    check("no script row for the un-approved topic", cur.fetchone()[0], 0)

    # 4) REWORK the sent-back topic WITH the reviewer's comment -> new revision (regenerates)
    print("\n4) rework topic (co-creation: regenerate informed by the comment)")
    rw = W.select_rework(conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor),
                         "topic_review", "CHANGES_REQUESTED", "topic", round_id=RID)
    check("rework queue finds the sent-back slot", [r["slot_id"] for r in rw], ["RSELF-4"])
    check("next revision = 2", rw[0]["next_revision"], 2)
    for r in rw:
        guard_slot(r["slot_id"])           # belt-and-suspenders: never rework a real slot
    W.process_topic(conn, tchat, None, emb, cfg, rw[0], dry_run=False,
                    feedback=rw[0]["rework_note"], revision=rw[0]["next_revision"])
    cur.execute("SELECT revision, feedback, text_ar FROM topic WHERE slot_id='RSELF-4' "
                "ORDER BY revision DESC LIMIT 1")
    rv = cur.fetchone()
    check("new topic revision stored", rv[0], 2)
    check("feedback stored on revision", bool(rv[1]), True)
    check("topic actually changed (regenerated)", "معدّلة" in (rv[2] or ""), True)
    cur.execute("SELECT count(*) FROM topic WHERE slot_id='RSELF-4'")
    check("prior version kept (history = 2 rows)", cur.fetchone()[0], 2)
    rw2 = W.select_rework(conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor),
                          "topic_review", "CHANGES_REQUESTED", "topic", round_id=RID)
    check("rework queue clears after regen (slot back to TOPIC_PROPOSED)", rw2, [])

    # 5) approve the reworked topic -> script it -> 4 DRAFT_ASSIGNED
    print("\n5) approve reworked topic, then script it")
    g2 = engine.open_gate(conn, "topic_review", round_id=RID, actor="selftest", cfg=cfg)
    check("re-review gate has only the reworked slot", len(engine.get_gate(conn, g2)["targets"]), 1)
    engine.decide(conn, g2, "khal", "approve", slot_ids=["RSELF-4"], cfg=cfg)
    engine.resolve(conn, g2, actor="selftest", cfg=cfg)
    for s in fetch(conn, "TOPIC_APPROVED"):
        guard_slot(s["slot_id"])
        W.process_script(conn, schat, None, cfg, s, dry_run=False)
    check("all 4 now DRAFT_ASSIGNED", status_counts(conn).get("DRAFT_ASSIGNED"), 4)

    # 6) SCRIPT_REVIEW -> APPROVED_ASSIGNED
    print("\n6) script_review -> APPROVED_ASSIGNED")
    # #359 ruling 8 — accepting topic_review now mints a durable Script attempt in the same
    # transaction, and #364 makes the guard read that durably: script_review stays HELD until the
    # attempt is terminal. This suite writes its scripts directly rather than through the writer, so
    # nothing has terminalized that attempt. Do what the durable drain does in production, so the
    # stage can proceed. (Asserting the hold itself is the job of the #359 suite, not this one.)
    _c359 = conn.cursor()
    _c359.execute("""UPDATE generation_job SET status='completed', lease_expires_at=NULL,
                                               updated_at=now()
                      WHERE round_id=%s AND stage='script'
                        AND status NOT IN ('completed','partial','failed')""", (RID,))
    conn.commit(); _c359.close()
    g3 = engine.open_gate(conn, "script_review", round_id=RID, actor="selftest", cfg=cfg)
    engine.decide(conn, g3, "khal", "approve", cfg=cfg)
    engine.resolve(conn, g3, actor="selftest", cfg=cfg)
    check("4 APPROVED_ASSIGNED", status_counts(conn).get("APPROVED_ASSIGNED"), 4)

    # 6b) DIRECTIVES (M9·B1): the inter-stage handoff contract — emitted, shaped, audited.
    print("\n6b) directives — stage contract + handoff packages")
    import directives as D
    check("stage_by_gate(topic_review) -> 'topic'", D.stage_by_gate(cfg, "topic_review")[0], "topic")
    check("stage_by_gate(script_review) -> 'script'", D.stage_by_gate(cfg, "script_review")[0], "script")
    check("production stage is a declared MANUAL seam",
          (D.stages(cfg).get("production") or {}).get("generator"), "manual")
    # origin: every slot recorded the strategy->topic directive it consumed
    check("strategy->topic directive recorded for all 4 slots",
          all(directives_for(conn, sid, "topic") for sid, _, _ in SLOTS), True)
    # topic_review approval emitted the topic->script directive (approved topic = directive into script)
    check("topic->script directive emitted for all 4 approved topics",
          all(directives_for(conn, sid, "script") for sid, _, _ in SLOTS), True)
    # script_review approval emitted the production directive (script emits production directions)
    check("script->production directive emitted for all 4 scripts",
          all(directives_for(conn, sid, "production") for sid, _, _ in SLOTS), True)
    # the production package is well-formed: six fields + bilingual intent + acceptance_criteria
    pkg = directives_for(conn, "RSELF-1", "production")[-1]["payload"]
    check("directive carries all six fields", all(f in pkg for f in D.PACKAGE_FIELDS), True)
    check("directive intent is bilingual", bool(pkg["intent"].get("ar") and pkg["intent"].get("en")), True)
    check("directive has acceptance_criteria", len(pkg["acceptance_criteria"]) > 0, True)
    # the topic->script directive carries the approved hook the script stage must open on
    sdir = directives_for(conn, "RSELF-1", "script")[-1]["payload"]
    check("topic->script directive carries the approved hook",
          bool(sdir["parameters"].get("hook_text")), True)
    # the reworked slot's topic->script directive reflects the v2 (revision tracked through the handoff)
    check("reworked RSELF-4 topic->script directive at revision 2",
          directives_for(conn, "RSELF-4", "script")[-1]["revision"], 2)

    # 7) REVIEWER-DISCRETION reviews (M5): the system SUGGESTS; the reviewer escalates or waives.
    #    final_review now CLEARS content INTO production (READY_FOR_PRODUCTION), enforcing reviews
    #    before any money is spent shooting — the manual lifecycle (7b) follows.
    print("\n7) suggested reviews — reviewer discretion (escalate / waive), enforced before production")
    cur.execute("""UPDATE script SET needs_scholar_review=true,
                   flags = (COALESCE(flags,'[]'::jsonb) || '["needs_scholar_review"]'::jsonb)
                   WHERE slot_id='RSELF-1'""")          # RSELF-1 now also suggests religious review
    conn.commit()

    # reviewer dispositions BEFORE publish: escalate RSELF-1's religious; waive RSELF-2's native
    engine.dispose_review(conn, "RSELF-1", "religious", "escalate", actor="khal", cfg=cfg)
    engine.dispose_review(conn, "RSELF-2", "native", "waive", reason="ar-PS is clean here", actor="khal", cfg=cfg)
    check("waiver needs a reason",
          _raises(lambda: engine.dispose_review(conn, "RSELF-3", "native", "waive", actor="khal", cfg=cfg)), True)

    # final_review (khal+huda, quorum all) — multi-approver still proven
    g4 = engine.open_gate(conn, "final_review", round_id=RID, actor="selftest", cfg=cfg)
    check("final gate quorum (all -> 2)", int(engine.get_gate(conn, g4)["quorum"]), 2)
    engine.decide(conn, g4, "khal", "approve", cfg=cfg)
    fs1 = engine.stage_state(conn, RID, "final_review", cfg)
    check("final stage stays reviewing after 1/2 approvals", fs1["state"], "reviewing")
    check("final stage approved count stays 0 before quorum", fs1["approved"], 0)
    check("1/2 approvers -> none publish-ready",
          set(engine.resolve(conn, g4, actor="selftest", cfg=cfg).values()), {"pending"})
    engine.decide(conn, g4, "huda", "approve", cfg=cfg)
    o2 = engine.resolve(conn, g4, actor="selftest", cfg=cfg)
    check("discretion: un-escalated suggestions DON'T block; escalated RSELF-1 blocks",
          {k: o2[k] for k in sorted(o2)},
          {"RSELF-1": "blocked_on_review", "RSELF-2": "approved", "RSELF-3": "approved", "RSELF-4": "approved"})
    check("3 cleared into production (RSELF-1 held for the escalated scholar review)",
          status_counts(conn).get("READY_FOR_PRODUCTION"), 3)

    # the escalation routed RSELF-1 (only) to the scholar's on-demand gate
    gs = engine.open_gate(conn, "scholar_review", round_id=RID, actor="sheikh", cfg=cfg)
    check("scholar gate targets ONLY the escalated slot",
          [x["slot_id"] for x in engine.get_gate(conn, gs)["targets"]], ["RSELF-1"])
    engine.decide(conn, gs, "sheikh", "approve", cfg=cfg)
    engine.resolve(conn, gs, actor="sheikh", cfg=cfg)
    check("after scholar sign-off RSELF-1 clears into production",
          engine.resolve(conn, g4, actor="selftest", cfg=cfg)["RSELF-1"], "approved")
    check("all 4 READY_FOR_PRODUCTION", status_counts(conn).get("READY_FOR_PRODUCTION"), 4)
    check("RSELF-2 native review was waived -> no blocker", engine.publish_blockers(conn, "RSELF-2", cfg), [])

    # policy switch is config-driven: in 'required' mode the flag blocks regardless of disposition
    cfg_req = copy.deepcopy(cfg)
    cfg_req["reviews"]["native"]["mode"] = "required"
    check("discretion: RSELF-3 native is NOT a blocker", engine.publish_blockers(conn, "RSELF-3", cfg), [])
    check("required: RSELF-3 native IS a blocker", engine.publish_blockers(conn, "RSELF-3", cfg_req), ["native_review"])
    check("required reviews cannot be waived",
          _raises(lambda: engine.dispose_review(conn, "RSELF-3", "native", "waive", reason="x", actor="khal", cfg=cfg_req)), True)

    # CR01 foundations: approval assignments can bind to roles/groups, not only direct user ids.
    cur.execute("""INSERT INTO principal_role (role_id, display_name_en, tenant_id, module)
                   VALUES ('legal_reviewer', 'Legal reviewer', 'selftest', 'content')
                   ON CONFLICT (role_id) DO NOTHING""")
    cur.execute("""INSERT INTO principal_role_member (role_id, principal_id, tenant_id, module)
                   VALUES ('legal_reviewer', 'huda', 'selftest', 'content')
                   ON CONFLICT (role_id, principal_id) DO NOTHING""")
    cur.execute("""INSERT INTO principal_group (group_id, display_name_en, tenant_id, module)
                   VALUES ('brand_team', 'Brand team', 'selftest', 'content')
                   ON CONFLICT (group_id) DO NOTHING""")
    cur.execute("""INSERT INTO principal_group_member (group_id, principal_id, tenant_id, module)
                   VALUES ('brand_team', 'nour', 'selftest', 'content')
                   ON CONFLICT (group_id, principal_id) DO NOTHING""")
    conn.commit()
    cur_auth = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    check("approval contract normalizes AND + typed assignments",
          engine.approval_contract({"approval": {"rule": "and", "users": ["khal"], "roles": ["legal_reviewer"], "groups": ["brand_team"]}}),
          {"rule_key": "all", "assignments": ["user:khal", "role:legal_reviewer", "group:brand_team"], "quorum_n": 3})
    check("role assignment authorizes the mapped member",
          engine._principal_matches_assignment(cur_auth, "huda", "role:legal_reviewer"), True)
    check("group assignment authorizes the mapped member",
          engine._principal_matches_assignment(cur_auth, "nour", "group:brand_team"), True)
    check("non-member cannot approve via role assignment",
          engine._principal_matches_assignment(cur_auth, "khal", "role:legal_reviewer"), False)
    cur_auth.close()
    check("content owner may administer approval policies",
          engine.can_administer_approval_policies(conn, "khal"), True)
    check("ordinary reviewer may not administer approval policies",
          engine.can_administer_approval_policies(conn, "huda"), False)
    cur_cleanup = conn.cursor()
    cur_cleanup.execute("DELETE FROM approval_policy_assignment WHERE policy_id IN (SELECT policy_id FROM approval_policy WHERE stage='topic_review')")
    cur_cleanup.execute("DELETE FROM approval_policy WHERE stage='topic_review'")
    conn.commit()
    cur_cleanup.close()
    updated_policy = engine.update_stage_approval_policy(
        conn, "topic_review",
        {"rule_key": "all", "users": ["khal"], "roles": ["legal_reviewer"], "groups": ["brand_team"]},
        actor="khal",
    )
    check("policy update persists canonical AND rule", updated_policy["rule_key"], "all")
    check("policy update persists all assignment kinds",
          (updated_policy["users"], updated_policy["roles"], updated_policy["groups"]),
          (["khal"], ["legal_reviewer"], ["brand_team"]))
    check("DB override is read ahead of YAML fallback",
          engine.stage_approval_contract(cfg, "topic_review", conn=conn)["quorum"], 3)
    cur_cleanup = conn.cursor()
    cur_cleanup.execute("DELETE FROM approval_policy_assignment WHERE policy_id IN (SELECT policy_id FROM approval_policy WHERE stage='topic_review')")
    cur_cleanup.execute("DELETE FROM approval_policy WHERE stage='topic_review'")
    cur_cleanup.execute("DELETE FROM audit_log WHERE entity='approval_policy' AND entity_id='topic_review'")
    conn.commit()
    cur_cleanup.close()

    workflows = engine.list_workflows(conn, principal_id="khal", cfg=cfg)
    check("workflow catalog is seeded and admin-visible",
          (workflows["can_administer"], bool(workflows["active_version"])), (True, True))
    active_workflow = workflows["active_version"]
    draft_workflow = engine.create_workflow_version_draft(conn, actor="khal", cfg=cfg)
    check("workflow draft is created as the next version",
          (draft_workflow["status"], draft_workflow["version_no"] > active_workflow["version_no"]), ("draft", True))
    edited_stages = copy.deepcopy(draft_workflow["stages"])
    edited_stages = [stage for stage in edited_stages if stage["stage_key"] != "scholar_review"]
    edited_stages[0]["stage_label"] = "Topic approvals"
    edited_transitions = [t for t in copy.deepcopy(draft_workflow["transitions"])
                          if t["from_stage_key"] != "scholar_review" and t["to_stage_key"] != "scholar_review"]
    updated_workflow = engine.update_workflow_version(conn, draft_workflow["version_id"], {
        "notes": "selftest edited workflow draft",
        "stages": edited_stages,
        "transitions": edited_transitions,
    }, actor="khal", cfg=cfg)
    check("workflow draft update persists notes and stage edits",
          (updated_workflow["notes"], updated_workflow["stages"][0]["stage_label"],
           any(stage["stage_key"] == "scholar_review" for stage in updated_workflow["stages"])),
          ("selftest edited workflow draft", "Topic approvals", False))
    active_again = engine.get_workflow_version(conn, active=True, cfg=cfg)
    check("saving a draft does not change the active workflow version",
          active_again["version_id"], active_workflow["version_id"])
    activated_workflow = engine.activate_workflow_version(conn, draft_workflow["version_id"], actor="khal", cfg=cfg)
    check("workflow activation switches the active version",
          (activated_workflow["status"], engine.get_workflow_version(conn, active=True, cfg=cfg)["version_id"]),
          ("active", draft_workflow["version_id"]))
    check("non-admin cannot create workflow drafts",
          _raises(lambda: engine.create_workflow_version_draft(conn, actor="huda", cfg=cfg)), True)

    # 7b) MANUAL LIFECYCLE (M9·B2): production -> media_edit -> distribution, executor = human
    #     uploading DAM assets, each gate a plain transition; directives emitted at each handoff.
    print("\n7b) manual stages — production / media_edit / distribution (DAM + directive handoffs)")
    import dam as DAM
    ids = [sid for sid, _, _ in SLOTS]
    for sid in ids:
        guard_slot(sid)
        DAM.add_asset(conn, sid, "production", "raw_cut", uri=f"file:///raw/{sid}_take1.mp4",
                      actor="khal")
    # re-upload one raw cut -> version 2, prior superseded (history kept)
    DAM.add_asset(conn, "RSELF-1", "production", "raw_cut", uri="file:///raw/RSELF-1_take2.mp4",
                  actor="khal")
    acur = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    check("raw cut re-upload bumps version to 2",
          max(a["version"] for a in DAM.list_assets(acur, "RSELF-1", stage="production")), 2)
    check("only one active raw cut per slot after supersede",
          len(DAM.list_assets(acur, "RSELF-1", stage="production", kind="raw_cut")), 1)
    acur.close()

    # production_review: READY_FOR_PRODUCTION -> PRODUCED (emits media_directive)
    gp = engine.open_gate(conn, "production_review", round_id=RID, actor="selftest", cfg=cfg)
    check("production gate has raw-cut assets attached to its targets",
          all(t["assets"] for t in engine.get_gate(conn, gp)["targets"]), True)
    engine.decide(conn, gp, "khal", "approve", cfg=cfg)
    engine.resolve(conn, gp, actor="selftest", cfg=cfg)
    check("all 4 PRODUCED", status_counts(conn).get("PRODUCED"), 4)
    check("production approval emitted the media_directive (production->media_edit)",
          all(directives_for(conn, sid, "media_edit") for sid in ids), True)
    mdir = directives_for(conn, "RSELF-1", "media_edit")[-1]["payload"]
    check("media_directive references the raw cut (inputs from DAM)",
          any(i.get("asset_kind") == "raw_cut" for i in mdir["inputs"]), True)

    # editor uploads edits, with platform variants
    for sid in ids:
        DAM.add_asset(conn, sid, "media_edit", "edit", uri=f"file:///edit/{sid}_v1.mp4", actor="khal")
    DAM.add_asset(conn, "RSELF-1", "media_edit", "edit", uri="file:///edit/RSELF-1_reel.mp4",
                  platform_variant="instagram_reel", actor="khal")

    # edit_review: PRODUCED -> EDITED (emits distribution_directive)
    ge = engine.open_gate(conn, "edit_review", round_id=RID, actor="selftest", cfg=cfg)
    engine.decide(conn, ge, "khal", "approve", cfg=cfg)
    engine.resolve(conn, ge, actor="selftest", cfg=cfg)
    check("all 4 EDITED", status_counts(conn).get("EDITED"), 4)
    check("edit approval emitted the distribution_directive (media_edit->distribution)",
          all(directives_for(conn, sid, "distribution") for sid in ids), True)

    # B3: FINISHED-MEDIA re-escalation — a reviewer re-escalates RSELF-2's native review at the
    # EDITED stage (the edited cut introduced a dialect concern). It was WAIVED earlier; the new
    # escalation (newer than any sign-off) re-opens the requirement and the publish gate must hold.
    engine.dispose_review(conn, "RSELF-2", "native", "escalate", actor="khal", cfg=cfg)

    # distribution_review: EDITED -> SCHEDULED (publish hard-floor; enforce_mandatory_reviews)
    gd = engine.open_gate(conn, "distribution_review", round_id=RID, actor="selftest", cfg=cfg)
    engine.decide(conn, gd, "khal", "approve", cfg=cfg)
    od = engine.resolve(conn, gd, actor="selftest", cfg=cfg)
    check("re-escalated RSELF-2 held at the publish gate; others schedule",
          {k: od[k] for k in sorted(od)},
          {"RSELF-1": "approved", "RSELF-2": "blocked_on_review",
           "RSELF-3": "approved", "RSELF-4": "approved"})
    check("3 published, RSELF-2 held for finished-media native re-review",
          status_counts(conn).get("SCHEDULED"), 3)
    # the native sign-off gate re-opens over the EDITED slot (reviews_status now multi-status)
    gn = engine.open_gate(conn, "native_review", round_id=RID, actor="nour", cfg=cfg)
    check("native gate re-targets ONLY the re-escalated finished-media slot",
          [x["slot_id"] for x in engine.get_gate(conn, gn)["targets"]], ["RSELF-2"])
    engine.decide(conn, gn, "nour", "approve", cfg=cfg)
    engine.resolve(conn, gn, actor="nour", cfg=cfg)
    engine.resolve(conn, gd, actor="selftest", cfg=cfg)   # re-resolve publish after the fresh sign-off
    check("after the fresh native sign-off RSELF-2 publishes — all 4 SCHEDULED",
          status_counts(conn).get("SCHEDULED"), 4)

    # the full directive chain exists end-to-end (one handoff per stage edge)
    chain_stages = {d["to_stage"] for d in directives_for(conn, "RSELF-1")}
    check("directive chain spans all stage handoffs",
          {"topic", "script", "production", "media_edit", "distribution"} <= chain_stages, True)

    # 7c) INTEGRATION SEAMS (M9·B2): declared + stubbed, NOT integrated.
    print("\n7c) integration contracts — declared + stubbed (not integrated)")
    from integrations import contracts as INTEG
    check("registry is empty by default (nothing integrated)", INTEG.load_registry(cfg), {})
    check("three providers declared (avp/postiz/analytics)",
          sorted(p["name"] for p in INTEG.available(cfg)), ["analytics", "avp", "postiz"])
    avp = INTEG.available(cfg)
    check("AVP fills the media_edit generator slot",
          next(p for p in avp if p["name"] == "avp")["stage"], "media_edit")
    check("a stub raises (contract declared, integration is Phase C)",
          _raises_nyi(lambda: INTEG._STUBS["postiz"]({}).execute({}, [])), True)

    # 7d) UNIFIED ACTOR MODEL (M9·B3): the review-discretion decision = f(autonomy × policy ×
    #     permissions), with hard floors. (RSELF-3 / RSELF-4 native are still un-disposed here.)
    print("\n7d) actor model — autonomy × stage-policy × permissions (+ hard floors)")
    import actors as ACT
    # an AUTONOMOUS agent-rep may waive a NON-hard-floor review (native) without a human
    check("autonomous rep CAN auto-waive a non-hard-floor (native) review",
          not _raises(lambda: engine.dispose_review(conn, "RSELF-3", "native", "waive",
                      reason="auto: dialect clean", actor="rep.selftest", cfg=cfg)), True)
    # HARD FLOOR: religious review can NEVER be auto-waived by a non-human, any autonomy
    check("hard floor: autonomous rep CANNOT auto-waive a religious review",
          _raises(lambda: engine.dispose_review(conn, "RSELF-3", "religious", "waive",
                  reason="auto", actor="rep.selftest", cfg=cfg)), True)
    # NO SELF-ESCALATION: a propose_only agent can't act as a higher autonomy -> can't auto-waive
    check("propose_only agent CANNOT auto-waive (no self-escalation)",
          _raises(lambda: engine.dispose_review(conn, "RSELF-4", "native", "waive",
                  reason="x", actor="agent.selftest", cfg=cfg)), True)
    # escalation (MORE oversight) is always permitted, even at the lowest autonomy
    check("escalation always permitted (safe direction) even for propose_only",
          not _raises(lambda: engine.dispose_review(conn, "RSELF-4", "native", "escalate",
                      actor="agent.selftest", cfg=cfg)), True)
    # PERMISSION axis (require_permission=true): an autonomous rep WITHOUT the token is refused
    cfg_perm = copy.deepcopy(cfg)
    cfg_perm["actor_model"]["require_permission"] = True
    check("permission enforced: autonomous rep WITHOUT review.waive is refused",
          _raises(lambda: engine.dispose_review(conn, "RSELF-3", "native", "waive",
                  reason="x", actor="rep.noperm", cfg=cfg_perm)), True)
    check("permission enforced: autonomous rep WITH review.waive is allowed",
          not _raises(lambda: engine.dispose_review(conn, "RSELF-3", "native", "waive",
                      reason="ok", actor="rep.selftest", cfg=cfg_perm)), True)
    # hard floor on GATE decisions: a non-human can never decide the publish gate
    check("hard floor: non-human cannot decide the publish gate",
          ACT.authorize_gate_decision(cfg, {"kind": "agent_rep"}, "distribution_review")[0], False)
    check("a human CAN decide the publish gate",
          ACT.authorize_gate_decision(cfg, {"kind": "user"}, "distribution_review")[0], True)
    check("non-hard-floor gate is open to any configured actor",
          ACT.authorize_gate_decision(cfg, {"kind": "agent_rep"}, "topic_review")[0], True)

    # 8) audit: a row for every kind of transition
    print("\n8) audit trail")
    gate_actions = {"gate_opened", "gate_resolved"}   # entity='gate' (uuid), not a RSELF- slot id
    for action, want_min in (("topic_proposed", 4), ("topic_reworked", 1), ("script_assigned", 4),
                             ("gate_opened", 4), ("gate_decision", 1), ("status_change", 1),
                             ("looped_back", 1), ("gate_resolved", 1),
                             ("review_escalated", 1), ("review_waived", 1),
                             ("signoff_recorded", 1), ("blocked_on_review", 1),
                             ("directive_emitted", 16), ("asset_added", 8),
                             ("autonomy_decision", 1)):
        if action in gate_actions:
            cur.execute("SELECT count(*) FROM audit_log WHERE id>%s AND action=%s", (a0, action))
            got = cur.fetchone()[0]
        else:
            got = audit_since(conn, a0, action)
        check(f"audit has {action}", got >= want_min, True)

    print("\n10) stage_state.next_action + bug fixes")
    import gates.engine as eng
    cc = eng.db_connect(); k = cc.cursor()
    k.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RNXT')")
    for tbl in ("directive", "slot_approval", "slot_review", "asset", "topic", "script", "slot"):
        k.execute(f"DELETE FROM {tbl} WHERE slot_id LIKE 'RNXT-%%'")
    k.execute("DELETE FROM script_provenance WHERE job_id IN "
              "(SELECT job_id FROM generation_job WHERE round_id='RNXT')")
    k.execute("DELETE FROM generation_job WHERE round_id='RNXT'")
    k.execute("DELETE FROM round WHERE round_id='RNXT'")
    k.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                 pillar_distribution,format_distribution,status) VALUES
                 ('RNXT','nx',1,2,'[\"09:00\"]','{}','{}','planned')""")
    k.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,status,cycle_no)
                 VALUES ('RNXT-1','RNXT',1,'09:00','P1_SELF','1.1','L1','Painful Truth','RESERVED',1)""")
    cc.commit(); k.close()
    ss0 = eng.stage_state(cc, "RNXT", "schedule_review")
    check("RESERVED slot -> schedule stage next_action=start_review", ss0["next_action"], "start_review")
    check("schedule stage has no generator", ss0["generator"], None)
    ss = eng.stage_state(cc, "RNXT", "topic_review")
    check("RESERVED slot does not unlock topic generation yet", ss["next_action"], "empty")
    check("single schedule-approved slot does not flip the round to titles-pending early",
          eng._round_phase({"slots": 2, "reserved": 1, "schedule_approved": 1, "topic_proposed": 0,
                            "draft": 0, "changes_requested": 0, "topic_approved": 0,
                            "approved": 0, "scheduled": 0, "rejected": 0}), "active")
    check("dropped schedule slots do not hide active schedule work",
          eng._round_phase({"slots": 4, "reserved": 1, "schedule_approved": 2, "topic_proposed": 0,
                            "draft": 0, "changes_requested": 0, "topic_approved": 0,
                            "approved": 0, "scheduled": 0, "rejected": 1}), "active")
    check("all schedule slots approved unlocks titles-pending",
          eng._round_phase({"slots": 2, "reserved": 0, "schedule_approved": 2, "topic_proposed": 0,
                            "draft": 0, "changes_requested": 0, "topic_approved": 0,
                            "approved": 0, "scheduled": 0, "rejected": 0}), "titles-pending")
    k = cc.cursor(); k.execute("UPDATE slot SET status='TOPIC_APPROVED' WHERE slot_id='RNXT-1'"); cc.commit(); k.close()
    sc = eng.stage_state(cc, "RNXT", "script_review")
    check("approved topic w/o script -> script stage next_action=generate (NOT complete)", sc["next_action"], "generate")
    k = cc.cursor(); k.execute("UPDATE slot SET status='REJECTED' WHERE slot_id='RNXT-1'"); cc.commit(); k.close()
    sj = eng.stage_state(cc, "RNXT", "script_review")
    check("inherited dropped + 0 advanced -> not 'complete'", sj["next_action"] != "complete", True)
    k = cc.cursor()
    k.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RREOPEN')")
    k.execute("DELETE FROM slot WHERE round_id='RREOPEN'")
    k.execute("DELETE FROM script_provenance WHERE job_id IN "
              "(SELECT job_id FROM generation_job WHERE round_id='RREOPEN')")
    k.execute("DELETE FROM generation_job WHERE round_id='RREOPEN'")
    k.execute("DELETE FROM round WHERE round_id='RREOPEN'")
    k.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                 pillar_distribution,format_distribution,status) VALUES
                 ('RREOPEN','reopen',1,2,'[\"09:00\",\"20:00\"]','{}','{}','planned')""")
    k.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,status,cycle_no)
                 VALUES
                 ('RREOPEN-1','RREOPEN',1,'09:00','P1_SELF','1.1','L1','Painful Truth','TOPIC_PROPOSED',1),
                 ('RREOPEN-2','RREOPEN',1,'20:00','P1_SELF','1.2','L1','Painful Truth','TOPIC_PROPOSED',1)""")
    cc.commit(); k.close()
    rg = eng.open_gate(cc, "topic_review", round_id="RREOPEN", actor="selftest", cfg=cfg)
    eng.decide(cc, rg, "khal", "reject", slot_ids=["RREOPEN-1"], cfg=cfg)
    eng.resolve(cc, rg, actor="selftest", cfg=cfg, slot_ids=["RREOPEN-1"])
    eng.reopen(cc, "RREOPEN-1", actor="selftest", cfg=cfg)
    reopened_gate = eng.get_gate(cc, rg)
    reopened_target = next(t for t in reopened_gate["targets"] if t["slot_id"] == "RREOPEN-1")
    check("reopen clears the slot's stale gate decision in an active gate",
          reopened_target["current_outcome"], "pending")
    check("reopen returns full per-item actions by clearing gate decisions",
          reopened_target["decisions"], [])
    k = cc.cursor()
    k.execute("DELETE FROM slot WHERE round_id='RNXT'")
    k.execute("DELETE FROM script_provenance WHERE job_id IN "
              "(SELECT job_id FROM generation_job WHERE round_id='RNXT')")
    k.execute("DELETE FROM generation_job WHERE round_id='RNXT'")
    k.execute("DELETE FROM round WHERE round_id='RNXT'")
    k.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RREOPEN')")
    k.execute("DELETE FROM slot WHERE round_id='RREOPEN'")
    k.execute("DELETE FROM script_provenance WHERE job_id IN "
              "(SELECT job_id FROM generation_job WHERE round_id='RREOPEN')")
    k.execute("DELETE FROM generation_job WHERE round_id='RREOPEN'")
    k.execute("DELETE FROM round WHERE round_id='RREOPEN'")
    cc.commit(); k.close(); cc.close()

    # 10b) #10 approval identity — decide-time assignment authorization (direct / role / group)
    #      + the denied-attempt audit trail (must survive the GateError rollback).
    print("\n10b) approval identity — decide-time authorization + denial audit")
    ki = conn.cursor()
    ki.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RIDN')")
    ki.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RIDN-%%'")
    ki.execute("DELETE FROM slot WHERE round_id='RIDN'")
    ki.execute("DELETE FROM script_provenance WHERE job_id IN "
               "(SELECT job_id FROM generation_job WHERE round_id='RIDN')")
    ki.execute("DELETE FROM generation_job WHERE round_id='RIDN'")
    ki.execute("DELETE FROM round WHERE round_id='RIDN'")
    ki.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                 pillar_distribution,format_distribution,status) VALUES
                 ('RIDN','idn',1,2,'[\"09:00\",\"20:00\"]','{}','{}','planned')""")
    ki.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,status,cycle_no)
                 VALUES
                 ('RIDN-1','RIDN',1,'09:00','P1_SELF','1.1','L1','Painful Truth','TOPIC_PROPOSED',1),
                 ('RIDN-2','RIDN',1,'20:00','P1_SELF','1.2','L1','Painful Truth','TOPIC_PROPOSED',1)""")
    conn.commit(); ki.close()
    cfg_idn = copy.deepcopy(cfg)
    cfg_idn["gates"]["topic_review"]["approval"] = {
        "rule": "or", "users": ["khal"], "roles": ["legal_reviewer"], "groups": ["brand_team"]}
    gi = engine.open_gate(conn, "topic_review", round_id="RIDN", actor="selftest", cfg=cfg_idn)
    check("direct-user assignment: the assigned user's decision is accepted",
          engine.decide(conn, gi, "khal", "approve", slot_ids=["RIDN-1"], cfg=cfg_idn), ["RIDN-1"])
    check("role-derived assignment: a role member's decision is accepted",
          engine.decide(conn, gi, "huda", "approve", slot_ids=["RIDN-2"], cfg=cfg_idn), ["RIDN-2"])
    check("group-derived assignment: a group member's decision is accepted",
          engine.decide(conn, gi, "nour", "approve", slot_ids=["RIDN-1"], cfg=cfg_idn), ["RIDN-1"])
    check("unassigned principal cannot decide (approve-on-behalf denied)",
          _raises(lambda: engine.decide(conn, gi, "mallory", "approve", slot_ids=["RIDN-1"], cfg=cfg_idn)), True)
    kd = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    kd.execute("""SELECT actor, detail FROM audit_log WHERE entity='gate' AND entity_id=%s
                  AND action='gate_decision_denied' ORDER BY at DESC""", (str(gi),))
    denied = kd.fetchall()
    kd.close()
    check("denied decide attempt is audited (the row survives the GateError rollback)",
          len(denied) >= 1, True)
    check("denial audit records actor + reason + the allowed assignments",
          (denied[0]["actor"], denied[0]["detail"]["reason"],
           sorted(denied[0]["detail"]["allowed"])) if denied else None,
          ("mallory", "not_assigned", ["group:brand_team", "role:legal_reviewer", "user:khal"]))
    ki = conn.cursor()
    ki.execute("DELETE FROM audit_log WHERE entity='gate' AND entity_id=%s", (str(gi),))
    ki.execute("DELETE FROM gate WHERE gate_id=%s", (gi,))
    ki.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RIDN-%%'")
    ki.execute("DELETE FROM slot WHERE round_id='RIDN'")
    ki.execute("DELETE FROM script_provenance WHERE job_id IN "
               "(SELECT job_id FROM generation_job WHERE round_id='RIDN')")
    ki.execute("DELETE FROM generation_job WHERE round_id='RIDN'")
    ki.execute("DELETE FROM round WHERE round_id='RIDN'")
    conn.commit(); ki.close()

    print("\n9) job registry")
    import gates.jobs as jobs, time as _t
    flag = {"ran": False}
    def _work():
        _t.sleep(0.05); flag["ran"] = True
    jid = jobs.start("test", "RJOB", "topic_review", 3, _work)
    check("start returns a job id", isinstance(jid, str) and len(jid) > 0, True)
    st = jobs.status(jid)
    check("status known right after start", st["status"] in ("running", "done"), True)
    for _ in range(50):
        if jobs.status(jid)["status"] == "done": break
        _t.sleep(0.02)
    check("job runs to completion", (jobs.status(jid)["status"], flag["ran"]), ("done", True))
    check("done_fn overrides the live count", jobs.status(jid, lambda r: 2)["done"], 2)
    def _boom(): raise RuntimeError("nope")
    jid2 = jobs.start("test", "RJOB", "topic_review", 1, _boom)
    for _ in range(50):
        if jobs.status(jid2)["status"] != "running": break
        _t.sleep(0.02)
    check("a failing job is marked error with the message", (jobs.status(jid2)["status"], "nope" in (jobs.status(jid2)["error"] or "")), ("error", True))
    check("unknown job id -> None", jobs.status("nope-id"), None)

    # 11) #149 (#146 S2) — script structure keys are registry-driven, not a hardcoded 4-beat.
    print("\n11) #149 — registry-driven script structure keys")
    carousel_spec = {"production_rules": {"structure": [
        {"step": "slide_1", "label": "Hook"}, {"step": "slide_2", "label": "Concept Anchor"},
        {"step": "slide_3", "label": "Reflective CTA"}]}}
    hero_spec = {"production_rules": {}}   # no managed structure → canonical 4-beat fallback
    check("#149 structure_steps reads the registry keys (no hardcoded 4-beat)",
          W.structure_steps(carousel_spec), ["slide_1", "slide_2", "slide_3"])
    check("#149 structure_spec carries step->label from the registry",
          W.structure_spec(carousel_spec), [("slide_1", "Hook"), ("slide_2", "Concept Anchor"), ("slide_3", "Reflective CTA")])
    check("#149 structure_steps falls back to the 4-beat canon when the registry has none",
          W.structure_steps(hero_spec), ["hook", "body", "turn", "close"])
    check("#149 stub writer parses the prompt-advertised keys (format-aware, no per-format map)",
          W._structure_keys_from_prompt(W._STRUCTURE_KEYS_MARKER + " slide_1, slide_2, slide_3"),
          ["slide_1", "slide_2", "slide_3"])
    check("#149 stub falls back to 4-beat when the prompt advertises no keys",
          W._structure_keys_from_prompt("no marker in this prompt"), ["hook", "body", "turn", "close"])

    # 12) #154 — truthful script model attribution in the revision read model.
    print("\n12) #154 — script model attribution (persisted, never inferred)")
    mcur = conn.cursor()
    mcur.execute("SELECT slot_id FROM script ORDER BY created_at DESC LIMIT 1")
    m_slot = mcur.fetchone()[0]
    mcur.close()
    script_revs = engine.list_revisions(conn, m_slot, artifact="script")
    check("#154 script revisions carry the persisted model (FakeChat stamps fake:test)",
          all(r.get("model") == "fake:test" for r in script_revs) and len(script_revs) > 0, True)
    topic_revs = engine.list_revisions(conn, m_slot, artifact="topic")
    check("#154 topic revisions do NOT carry a model key (no persisted equivalent, no fake parity)",
          any("model" in r for r in topic_revs), False)

    # 13) #177 — the content-format seed carries the CLIENT framework structures and the seed sync
    # brings an existing registry up to it (versioned, idempotent, never overriding operator edits).
    print("\n13) #177 — framework registry seed truth + idempotent sync")
    from loader.load_methodology import _content_type_seed_rows, sync_content_format_seed
    seed_rows = {r["format_key"]: r["production_rules"] for r in _content_type_seed_rows()}
    hero_st = seed_rows["hero_reel"].get("structure") or []
    check("#177 hero_reel seed carries the 10-beat 60.viral.01 structure",
          (seed_rows["hero_reel"].get("framework_id"), len(hero_st), hero_st[0]["label"] if hero_st else None,
           hero_st[-1]["label"] if hero_st else None),
          ("60.viral.01", 10, "Hook", "Viral Ending"))
    check("#177 carousel seed keeps the locked 7-slide structure",
          len(seed_rows["carousel"].get("structure") or []), 7)
    check("#177 3sec seed keeps the 4-beat structure",
          len(seed_rows["3sec_reel_caption"].get("structure") or []), 4)
    check("#177 pic_caption is explicitly legacy with NO fabricated structure",
          (seed_rows["pic_caption"].get("framework_status"), seed_rows["pic_caption"].get("structure")),
          ("legacy_carry_forward", None))
    first_sync = sync_content_format_seed(conn, actor="selftest-177")
    second_sync = sync_content_format_seed(conn, actor="selftest-177")
    # Converged = nothing applied; each seed row is either unchanged OR deliberately skipped
    # because an operator-authored version is active (e.g. api_selftest's activation fixtures
    # ran earlier against this shared DB) — the sync must never override those.
    check("#177 seed sync is idempotent (second run applies nothing)",
          (second_sync["applied"],
           len(second_sync["unchanged"]) + len(second_sync["skipped_operator_owned"]) >= 4),
          ([], True))
    scur = conn.cursor()
    scur.execute("""SELECT v.source, v.production_rules->'structure'
                    FROM content_format cf JOIN content_format_version v
                         ON v.content_format_id=cf.content_format_id AND v.status='active'
                    WHERE cf.format_key='hero_reel' AND cf.tenant_id='default' AND cf.module='content'""")
    hero_row = scur.fetchone()
    scur.close()
    check("#177 active hero_reel version exposes the managed 10-beat structure",
          (hero_row is not None, hero_row[0] in ("bootstrap", "bootstrap-sync") if hero_row else None,
           len(hero_row[1] or []) if hero_row else 0),
          (True, True, 10))
    _ = first_sync  # first run may apply or be a no-op depending on prior DB state — both are valid

    # 14) #179 — durable approved-items trail: list_advanced exposes what a committed stage approved
    # and where each item is NOW, from existing gate/decision/slot state only (no new persistence).
    print("\n14) #179 — durable approved-items trail (list_advanced)")
    tk = conn.cursor()
    tk.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RTRAIL')")
    for _tbl in ("directive", "slot_approval", "slot_review", "asset", "topic", "script"):
        tk.execute(f"DELETE FROM {_tbl} WHERE slot_id LIKE 'RTRAIL-%%'")
    tk.execute("DELETE FROM slot WHERE round_id='RTRAIL'")
    tk.execute("DELETE FROM script_provenance WHERE job_id IN "
               "(SELECT job_id FROM generation_job WHERE round_id='RTRAIL')")
    tk.execute("DELETE FROM generation_job WHERE round_id='RTRAIL'")
    tk.execute("DELETE FROM round WHERE round_id='RTRAIL'")
    tk.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                 pillar_distribution,format_distribution,status) VALUES
                 ('RTRAIL','trail',1,2,'["09:00","20:00"]','{}','{}','planned')""")
    tk.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,status,cycle_no,hook_text,format)
                 VALUES
                 ('RTRAIL-1','RTRAIL',1,'09:00','P1_SELF','1.1','L1','Painful Truth','TOPIC_PROPOSED',1,'هوك أول','Hero Reel'),
                 ('RTRAIL-2','RTRAIL',1,'20:00','P1_SELF','1.2','L1','Painful Truth','TOPIC_PROPOSED',1,'هوك ثاني','Carousel')""")
    conn.commit(); tk.close()
    check("#179 trail is empty before any commit", engine.list_advanced(conn, "RTRAIL", "topic_review"), [])
    tg = engine.open_gate(conn, "topic_review", round_id="RTRAIL", actor="selftest", cfg=cfg)
    engine.decide(conn, tg, "khal", "approve", slot_ids=["RTRAIL-1"], cfg=cfg)
    engine.decide(conn, tg, "khal", "reject", slot_ids=["RTRAIL-2"], cfg=cfg)
    engine.resolve(conn, tg, actor="selftest", cfg=cfg)
    trail = engine.list_advanced(conn, "RTRAIL", "topic_review")
    check("#179 committed stage exposes the approved item (and ONLY it — the dropped one excluded)",
          [t["slot_id"] for t in trail], ["RTRAIL-1"])
    check("#179 trail row carries recognisable detail + who/when approved",
          (trail[0]["hook_text"], trail[0]["format"], trail[0]["approved_by"], trail[0]["approved_at"] is not None),
          ("هوك أول", "Hero Reel", "khal", True))
    # #219 — the trail row now carries the canonical ID fields (additive, read-only) the completed
    # inspection controls' formatter + Detailed descriptor need — resolved via the pillar/hcs joins
    # exactly like the active target selection, never fabricated.
    check("#219 trail row exposes canonical ID fields (pillar_short_code, seq_in_pillar, "
          "pillar_name_en, hcs_name_en) for RTRAIL-1's pillar P1_SELF / hcs 1.1",
          (all(k in trail[0] for k in ("pillar_short_code", "seq_in_pillar", "pillar_name_en", "hcs_name_en")),
           trail[0]["pillar_short_code"] is not None, trail[0]["seq_in_pillar"] is not None,
           trail[0]["pillar_name_en"] is not None, trail[0]["hcs_name_en"] is not None),
          (True, True, True, True, True))
    check("#179 location: just-committed topic = advanced at Topics, awaiting the next step",
          (trail[0]["location_kind"], trail[0]["location_stage"]), ("advanced", "topic_review"))
    tk = conn.cursor(); tk.execute("UPDATE slot SET status='DRAFT_ASSIGNED' WHERE slot_id='RTRAIL-1'"); conn.commit(); tk.close()
    trail2 = engine.list_advanced(conn, "RTRAIL", "topic_review")
    check("#179 location follows the item: once scripted it reads in-review at Scripts",
          (trail2[0]["location_kind"], trail2[0]["location_stage"], trail2[0]["location_stage_label"]),
          ("in_review", "script_review", "Scripts"))
    check("#179 the NEXT stage's own trail stays empty (nothing committed there yet)",
          engine.list_advanced(conn, "RTRAIL", "script_review"), [])
    # #237 Slice A — status-independent READ-ONLY inspection (inspect_slot): the completed trail
    # opens the SAME content definition the active card shows, from persisted truth only. The
    # slot_approval PIN (approve v1 even when v2 exists) decides which revision is shown — labeled,
    # never silently conflated with the head; absent artifacts are truthful None.
    tk = conn.cursor()
    tk.execute("""INSERT INTO topic (slot_id, hcs_id, lens, round_id, cycle_no, text_ar,
                                     rationale_en, hook_text, hook_type, revision)
                  VALUES ('RTRAIL-1','1.1','L1','RTRAIL',1,'نص الموضوع v1','why now v1','هوك أول','Painful Truth',1),
                         ('RTRAIL-1','1.1','L1','RTRAIL',1,'نص الموضوع v2','why now v2','هوك أول','Painful Truth',2)""")
    tk.execute("DELETE FROM slot_approval WHERE slot_id='RTRAIL-1'")
    tk.execute("""INSERT INTO slot_approval (slot_id, artifact, revision, approver, actor_kind)
                  VALUES ('RTRAIL-1','topic',1,'khal','user')""")
    conn.commit(); tk.close()
    insp = engine.inspect_slot(conn, "RTRAIL-1")
    check("#237 inspect is status-independent: the ADVANCED item still returns its full definition",
          (insp["slot_id"], insp["status"], insp["pillar_name_en"] is not None,
           insp["hcs_name_en"] is not None, insp["format"]),
          ("RTRAIL-1", "DRAFT_ASSIGNED", True, True, "Hero Reel"))
    check("#237 inspect shows the slot_approval-PINNED topic revision (v1), labeled, not the head (v2)",
          (insp["topic"]["revision"], insp["topic"]["approved"], insp["topic"]["approved_by"],
           insp["topic"]["head_revision"], insp["topic"]["text_ar"]),
          (1, True, "khal", 2, "نص الموضوع v1"))
    check("#237 inspect absent script is truthful None (never fabricated)", insp["script"], None)
    check("#237 inspect carries decision provenance (khal approved at topic_review, note-capable)",
          [(d["stage"], d["approver_id"], d["decision"]) for d in insp["decisions"]],
          [("topic_review", "khal", "approve")])
    check("#237 inspect of an unknown slot raises (no fabricated rows)",
          _raises(lambda: engine.inspect_slot(conn, "RTRAIL-NOPE")), True)
    tk = conn.cursor(); tk.execute("DELETE FROM slot_approval WHERE slot_id='RTRAIL-1'"); conn.commit(); tk.close()
    insp2 = engine.inspect_slot(conn, "RTRAIL-1")
    check("#237 with no pin, inspect falls back to the HEAD revision and says it is NOT approved",
          (insp2["topic"]["revision"], insp2["topic"]["approved"], insp2["topic"]["approved_by"]),
          (2, False, None))
    # #237 P1 (adversarial) — slot.topic_angle and the pinned topic.text_ar are INDEPENDENTLY
    # persisted and can diverge (live edits/restores update the slot body). The projection must
    # carry BOTH truths so the surface can show both — never one silently replacing the other.
    tk = conn.cursor()
    tk.execute("UPDATE slot SET topic_angle='زاوية معدلة بعد الاعتماد' WHERE slot_id='RTRAIL-1'")
    tk.execute("""INSERT INTO slot_approval (slot_id, artifact, revision, approver, actor_kind)
                  VALUES ('RTRAIL-1','topic',1,'khal','user')""")
    conn.commit(); tk.close()
    insp3 = engine.inspect_slot(conn, "RTRAIL-1")
    check("#237 P1: diverged slot body and pinned approved body are BOTH in the projection, distinct",
          (insp3["topic_angle"], insp3["topic"]["text_ar"],
           insp3["topic_angle"] != insp3["topic"]["text_ar"]),
          ("زاوية معدلة بعد الاعتماد", "نص الموضوع v1", True))
    tk = conn.cursor()
    tk.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RTRAIL')")
    for _tbl in ("directive", "slot_approval", "slot_review", "asset", "topic", "script"):
        tk.execute(f"DELETE FROM {_tbl} WHERE slot_id LIKE 'RTRAIL-%%'")
    tk.execute("DELETE FROM slot WHERE round_id='RTRAIL'")
    tk.execute("DELETE FROM script_provenance WHERE job_id IN "
               "(SELECT job_id FROM generation_job WHERE round_id='RTRAIL')")
    tk.execute("DELETE FROM generation_job WHERE round_id='RTRAIL'")
    tk.execute("DELETE FROM round WHERE round_id='RTRAIL'")
    conn.commit(); tk.close()

    # 14b) #255 S1 — atomic approved-MASTER-edit pin at edit_review resolution. Master = the exact
    # DAM tuple (stage='media_edit', kind='edit', platform_variant IS NULL, status='active').
    # Exactly ONE active master or FAIL CLOSED (whole transaction rolls back — no slot transition,
    # no gate resolution, no partial pin). The slot_approval pointer is the governed current-state
    # pin; the append-only `approved_edit_master_pinned` audit is the immutable exact history.
    print("\n14b) #255 — approved master edit pin at edit_review (S1)")
    import dam                                   # noqa: E402 — DAM master/variant fixtures
    import psycopg2.extras                       # noqa: E402 — dict rows for pin assertions
    ek = conn.cursor()
    ek.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RPIN255')")
    for _tbl in ("directive", "slot_approval", "slot_review", "asset", "topic", "script"):
        ek.execute(f"DELETE FROM {_tbl} WHERE slot_id LIKE 'RPIN255-%%'")
    ek.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RPIN255-%%'")
    ek.execute("DELETE FROM slot WHERE round_id='RPIN255'")
    ek.execute("DELETE FROM script_provenance WHERE job_id IN "
               "(SELECT job_id FROM generation_job WHERE round_id='RPIN255')")
    ek.execute("DELETE FROM generation_job WHERE round_id='RPIN255'")
    ek.execute("DELETE FROM round WHERE round_id='RPIN255'")
    ek.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                 pillar_distribution,format_distribution,status) VALUES
                 ('RPIN255','edit-pin',1,3,'["09:00"]','{}','{}','planned')""")
    for sid in ("RPIN255-1", "RPIN255-2", "RPIN255-3"):
        ek.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,status,cycle_no,hook_text,format)
                     VALUES (%s,'RPIN255',1,'09:00','P1_SELF','1.1','L1','Painful Truth','PRODUCED',1,'هوك','Hero Reel')""", (sid,))
    conn.commit(); ek.close()
    # slot 1: master v1 + an ADVERSARIAL platform-variant sibling that also carries revision 1
    a1 = dam.add_asset(conn, "RPIN255-1", "media_edit", "edit", uri="e://v1", actor="ed")
    v1 = dam.add_asset(conn, "RPIN255-1", "media_edit", "edit", uri="e://ig-v1",
                       platform_variant="instagram", actor="ed")
    conn.commit()
    eg = engine.open_gate(conn, "edit_review", round_id="RPIN255", actor="selftest", cfg=cfg)
    engine.decide(conn, eg, "khal", "approve", slot_ids=["RPIN255-1"], cfg=cfg)
    engine.resolve(conn, eg, actor="selftest", cfg=cfg, slot_ids=["RPIN255-1"])
    ek = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ek.execute("SELECT revision, approver FROM slot_approval WHERE slot_id='RPIN255-1' AND artifact='edit'")
    pin1 = ek.fetchone()
    ek.execute("SELECT status FROM slot WHERE slot_id='RPIN255-1'")
    st1 = ek.fetchone()["status"]
    ek.execute("SELECT detail FROM audit_log WHERE entity_id='RPIN255-1' AND action='approved_edit_master_pinned'")
    ev1 = ek.fetchall()
    check("#255 approval atomically pins the intended MASTER version + advances + audits",
          (pin1["revision"], pin1["approver"], st1 != "PRODUCED", len(ev1),
           ev1[0]["detail"]["asset_id"] == str(a1), ev1[0]["detail"]["master"]["platform_variant"]),
          (1, "khal", True, 1, True, None))
    insp1 = engine.inspect_slot(conn, "RPIN255-1")
    check("#255 adversarial: the same-revision platform VARIANT is never the pinned/displayed master",
          (insp1["approved_edit"]["pinned_asset_id"] == str(a1),
           insp1["approved_edit"]["pinned_asset_id"] == str(v1)),
          (True, False))
    # drift: a NEW master version after approval must not move the pin or the approved projection
    dam.add_asset(conn, "RPIN255-1", "media_edit", "edit", uri="e://v2", actor="ed"); conn.commit()
    insp1b = engine.inspect_slot(conn, "RPIN255-1")
    check("#255 drift: a newer master shows as drift; the approved pin never moves",
          (insp1b["approved_edit"]["pinned_revision"], insp1b["approved_edit"]["current_master_revision"],
           insp1b["approved_edit"]["drifted"], insp1b["approved_edit"]["pinned_asset_id"] == str(a1)),
          (1, 2, True, True))
    # fail-closed: ZERO active masters — nothing commits (no transition, no pin, no audit)
    engine.decide(conn, eg, "khal", "approve", slot_ids=["RPIN255-2"], cfg=cfg)
    check("#255 fail-closed (zero masters): resolve raises",
          _raises(lambda: engine.resolve(conn, eg, actor="selftest", cfg=cfg, slot_ids=["RPIN255-2"])), True)
    conn.rollback()
    ek.execute("SELECT status FROM slot WHERE slot_id='RPIN255-2'")
    ek2 = ek.fetchone()["status"]
    ek.execute("SELECT count(*) FROM slot_approval WHERE slot_id='RPIN255-2'")
    ek3 = ek.fetchone()["count"]
    ek.execute("SELECT count(*) FROM audit_log WHERE entity_id='RPIN255-2' AND action IN ('approved_edit_master_pinned','status_change')")
    ek4 = ek.fetchone()["count"]
    check("#255 fail-closed (zero masters): no transition, no pin, no audit — full rollback",
          (ek2, ek3, ek4), ("PRODUCED", 0, 0))
    # fail-closed: AMBIGUOUS (two active masters injected directly, bypassing dam supersession)
    a2 = dam.add_asset(conn, "RPIN255-2", "media_edit", "edit", uri="e://v1", actor="ed")
    ek.execute("""INSERT INTO asset (slot_id, stage, kind, uri, storage, version, created_by, status)
                  VALUES ('RPIN255-2','media_edit','edit','e://rogue','reference',99,'rogue','active')""")
    conn.commit()
    engine.decide(conn, eg, "khal", "approve", slot_ids=["RPIN255-2"], cfg=cfg)
    check("#255 fail-closed (ambiguous masters): resolve raises, no cleanup performed",
          _raises(lambda: engine.resolve(conn, eg, actor="selftest", cfg=cfg, slot_ids=["RPIN255-2"])), True)
    conn.rollback()
    ek.execute("SELECT count(*) FROM asset WHERE slot_id='RPIN255-2' AND stage='media_edit' AND kind='edit' AND platform_variant IS NULL AND status='active'")
    check("#255 ambiguous rows are REPORTED, not cleaned up (both still present)", ek.fetchone()["count"], 2)
    ek.execute("SELECT status FROM slot WHERE slot_id='RPIN255-2'")
    check("#255 ambiguous: slot never transitioned", ek.fetchone()["status"], "PRODUCED")
    # adversarial: a malformed DUPLICATE same-revision master row (injected directly) must not
    # corrupt the displayed pin — the exact pinned asset identity comes from the newest matching
    # IMMUTABLE `approved_edit_master_pinned` event, never re-identified from the revision number.
    ek.execute("""INSERT INTO asset (slot_id, stage, kind, uri, storage, version, created_by, status)
                  VALUES ('RPIN255-1','media_edit','edit','e://rogue-dup-v1','reference',1,'rogue','superseded')""")
    conn.commit()
    insp_dup = engine.inspect_slot(conn, "RPIN255-1")
    check("#255 adversarial duplicate same-revision master: pin identity stays the AUDITED asset",
          (insp_dup["approved_edit"]["pinned_asset_id"] == str(a1),
           insp_dup["approved_edit"]["pin_evidence"]),
          (True, "audit"))
    # truthful non-verified state: a pointer WITHOUT a matching immutable event is reported as
    # unavailable (never guessed from revision)
    ek.execute("""INSERT INTO slot_approval (slot_id, artifact, revision, approver, actor_kind)
                  VALUES ('RPIN255-2','edit',1,'rogue','user')""")
    conn.commit()
    insp_noev = engine.inspect_slot(conn, "RPIN255-2")
    check("#255 pointer without a matching pin event -> truthful unavailable identity, never guessed",
          (insp_noev["approved_edit"]["pinned_revision"],
           insp_noev["approved_edit"]["pinned_asset_id"],
           insp_noev["approved_edit"]["pin_evidence"]),
          (1, None, "unavailable"))
    ek.execute("DELETE FROM slot_approval WHERE slot_id='RPIN255-2' AND artifact='edit'")
    ek.execute("DELETE FROM asset WHERE slot_id='RPIN255-2' AND version=99")   # test fixture, not engine cleanup
    conn.commit()
    # strict emission: for the S1 media-edit handoff, a directive-emission failure rolls back the
    # ENTIRE resolution (status, pin, pin audit, directive) — nothing survives.
    import directives as _dir255
    _orig_emit = _dir255.emit_output
    def _boom(*a, **k):
        raise RuntimeError("injected emission failure (#255 proof)")
    _dir255.emit_output = _boom
    try:
        engine.decide(conn, eg, "khal", "approve", slot_ids=["RPIN255-2"], cfg=cfg)
        raised_kind = None
        try:
            engine.resolve(conn, eg, actor="selftest", cfg=cfg, slot_ids=["RPIN255-2"])
        except Exception as e:                                   # noqa: BLE001 — proving propagation
            raised_kind = type(e).__name__
        check("#255 strict emission: injected media-edit emission failure PROPAGATES uncaught",
              raised_kind, "RuntimeError")
        conn.rollback()
        ek.execute("""SELECT (SELECT status FROM slot WHERE slot_id='RPIN255-2') AS st,
                             (SELECT count(*) FROM slot_approval WHERE slot_id='RPIN255-2' AND artifact='edit') AS pin_n,
                             (SELECT count(*) FROM audit_log WHERE entity_id='RPIN255-2' AND action IN ('approved_edit_master_pinned','status_change')) AS audit_n,
                             (SELECT count(*) FROM directive WHERE slot_id='RPIN255-2') AS dir_n""")
        row_em = ek.fetchone()
        check("#255 strict emission: NOTHING survives — no status change, no pin, no pin audit, no directive",
              tuple(row_em.values()), ("PRODUCED", 0, 0, 0))
        # legacy stages keep the best-effort seam: the same injected failure does NOT block a
        # topic approval (guarded emit; approval still commits)
        ek.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,status,cycle_no,hook_text,format)
                     VALUES ('RPIN255-4','RPIN255',1,'09:00','P1_SELF','1.1','L1','Painful Truth','TOPIC_PROPOSED',1,'هوك','Hero Reel')""")
        ek.execute("""INSERT INTO topic (slot_id,hcs_id,lens,round_id,cycle_no,text_ar,hook_text,hook_type,revision)
                     VALUES ('RPIN255-4','1.1','L1','RPIN255',1,'نص','هوك','Painful Truth',1)""")
        conn.commit()
        tg255 = engine.open_gate(conn, "topic_review", round_id="RPIN255", actor="selftest", cfg=cfg)
        engine.decide(conn, tg255, "khal", "approve", slot_ids=["RPIN255-4"], cfg=cfg)
        engine.resolve(conn, tg255, actor="selftest", cfg=cfg, slot_ids=["RPIN255-4"])
        ek.execute("SELECT status FROM slot WHERE slot_id='RPIN255-4'")
        check("#255 legacy best-effort emission preserved: a topic approval still commits despite "
              "the same injected failure", ek.fetchone()["status"] != "TOPIC_PROPOSED", True)
    finally:
        _dir255.emit_output = _orig_emit
    conn.commit()
    # two-connection concurrency: the REAL resolve() path overlapping a competing master
    # supersession. B holds an UNCOMMITTED new master version (locks the active row); resolve()
    # on an independent connection BLOCKS mid-path at its FOR UPDATE; after B commits, exactly
    # one serialized truth may exist — either a clean fail-closed retry that then pins v2, or a
    # direct pin — NEVER a divergent pin or partial transition/audit/directive state.
    a3 = dam.add_asset(conn, "RPIN255-3", "media_edit", "edit", uri="e://v1", actor="ed")
    engine.decide(conn, eg, "khal", "approve", slot_ids=["RPIN255-3"], cfg=cfg)
    conn.commit()                                    # decision visible to the resolver connection
    import threading as _th
    connA = engine.db_connect()
    connB = engine.db_connect()
    # connB runs add_asset's OWN transaction body (supersede v1 + insert v2) and HOLDS it open —
    # dam.add_asset commits internally, so real overlap needs the uncommitted statements here.
    bcur = connB.cursor()
    bcur.execute("""UPDATE asset SET status='superseded' WHERE slot_id='RPIN255-3'
                     AND stage='media_edit' AND kind='edit' AND platform_variant IS NULL
                     AND status='active'""")
    bcur.execute("""INSERT INTO asset (slot_id, stage, kind, uri, storage, version, created_by)
                    VALUES ('RPIN255-3','media_edit','edit','e://v2','reference',2,'ed2')""")
    res255 = {}
    def _resolve255():
        try:
            engine.resolve(connA, eg, actor="selftest", cfg=cfg, slot_ids=["RPIN255-3"])
            connA.commit(); res255["outcome"] = "resolved"
        except Exception as e:                                   # noqa: BLE001
            connA.rollback(); res255["outcome"] = f"raised:{type(e).__name__}"
    ta = _th.Thread(target=_resolve255); ta.start(); ta.join(1.0)
    check("#255 concurrency: resolve() BLOCKS mid-path while a competing supersession holds the row",
          ta.is_alive(), True)
    connB.commit()                                   # release: v1 superseded, v2 active
    ta.join(15)
    check("#255 concurrency: overlapped resolve() reached exactly one serialized outcome",
          res255.get("outcome") in ("resolved", "raised:GateError"), True)
    ek2c = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if res255.get("outcome") != "resolved":
        # fail-closed under overlap: assert NO partial state, then a clean retry pins v2
        ek2c.execute("""SELECT (SELECT status FROM slot WHERE slot_id='RPIN255-3') AS st,
                               (SELECT count(*) FROM slot_approval WHERE slot_id='RPIN255-3' AND artifact='edit') AS pin_n,
                               (SELECT count(*) FROM audit_log WHERE entity_id='RPIN255-3' AND action IN ('approved_edit_master_pinned','status_change')) AS audit_n""")
        check("#255 concurrency: fail-closed overlap left ZERO partial state",
              tuple(ek2c.fetchone().values()), ("PRODUCED", 0, 0))
        engine.resolve(conn, eg, actor="selftest", cfg=cfg, slot_ids=["RPIN255-3"])
        conn.commit()
    ek2c.execute("SELECT revision FROM slot_approval WHERE slot_id='RPIN255-3' AND artifact='edit'")
    pin3 = ek2c.fetchone()["revision"]
    ek2c.execute("""SELECT version FROM asset WHERE slot_id='RPIN255-3' AND stage='media_edit'
                    AND kind='edit' AND platform_variant IS NULL AND status='active'""")
    head3 = [r["version"] for r in ek2c.fetchall()]
    ek2c.execute("SELECT count(*) FROM audit_log WHERE entity_id='RPIN255-3' AND action='approved_edit_master_pinned'")
    ev3 = ek2c.fetchone()["count"]
    check("#255 concurrency: ONE serialized truth — pin equals the single active master it "
          "resolved on, exactly one immutable pin event, never divergent",
          (pin3 in (1, 2), head3 == [2] or head3 == [pin3], ev3), (True, True, 1))
    insp3 = engine.inspect_slot(conn, "RPIN255-3")
    check("#255 concurrency: projection consistent (audited identity; drift iff pin behind head)",
          (insp3["approved_edit"]["pin_evidence"],
           insp3["approved_edit"]["drifted"] == (pin3 != (head3[0] if head3 else pin3))),
          ("audit", True))
    connA.close(); connB.close()
    ek2c.close()
    # topic/script approval behavior unchanged is proven by sections 1-14 running green above.
    ek.close()
    tk = conn.cursor()
    tk.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RPIN255')")
    for _tbl in ("directive", "slot_approval", "slot_review", "asset", "topic", "script"):
        tk.execute(f"DELETE FROM {_tbl} WHERE slot_id LIKE 'RPIN255-%%'")
    tk.execute("DELETE FROM audit_log WHERE entity_id LIKE 'RPIN255-%%'")
    tk.execute("DELETE FROM slot WHERE round_id='RPIN255'")
    tk.execute("DELETE FROM script_provenance WHERE job_id IN "
               "(SELECT job_id FROM generation_job WHERE round_id='RPIN255')")
    tk.execute("DELETE FROM generation_job WHERE round_id='RPIN255'")
    tk.execute("DELETE FROM round WHERE round_id='RPIN255'")
    conn.commit(); tk.close()

    # 15) #184 — managed topic-repetition policy: central resolver, authority gating, audit trail,
    # and the writer-side violation check (strict default / cross_format mode / own-slot exclusion).
    print("\n15) #184 — managed topic-repetition policy")
    pk = conn.cursor()
    pk.execute("DELETE FROM repetition_policy")
    pk.execute("DELETE FROM audit_log WHERE entity='repetition_policy'")
    conn.commit(); pk.close()
    pol0 = engine.effective_repetition_policy(conn, cfg)
    check("#184 strict production default (scope all; legacy config scope deliberately ignored)",
          (pol0["scope"], pol0["source"], pol0["enabled"]), ("all", "production_default", True))
    check("#184 non-admin policy write raises",
          _raises(lambda: engine.update_repetition_policy(conn, {"scope": "hcs"}, actor="huda")), True)
    engine.update_repetition_policy(conn, {"scope": "all", "repeat_modes": {"cross_format": True}},
                                    actor="khal")
    pol1 = engine.effective_repetition_policy(conn, cfg)
    check("#184 managed row wins and carries the allowed repeat mode",
          (pol1["source"], pol1["repeat_modes"].get("cross_format")), ("managed", True))
    check("#184 unknown repeat mode rejected",
          _raises(lambda: engine.update_repetition_policy(conn, {"repeat_modes": {"x": True}},
                                                          actor="khal")), True)
    # sparse update: changing ONE field must not reset the others (managed state preserved)
    engine.update_repetition_policy(conn, {"similarity_threshold": 0.9}, actor="khal")
    pol_sparse = engine.effective_repetition_policy(conn, cfg)
    check("#184 sparse update preserves unrelated managed fields (modes/scope/enabled survive)",
          (pol_sparse["similarity_threshold"], pol_sparse["repeat_modes"].get("cross_format"),
           pol_sparse["scope"], pol_sparse["enabled"]),
          (0.9, True, "all", True))
    engine.update_repetition_policy(conn, {"enabled": False}, actor="khal")
    pol_sparse2 = engine.effective_repetition_policy(conn, cfg)
    check("#184 sparse enabled=false keeps the threshold set one step earlier",
          (pol_sparse2["enabled"], pol_sparse2["similarity_threshold"]), (False, 0.9))
    pk = conn.cursor()
    # the FIRST update this section made is the default -> managed transition (later sparse
    # updates in this section audit managed -> managed)
    pk.execute("""SELECT detail FROM audit_log WHERE entity='repetition_policy'
                  AND action='repetition_policy_updated' ORDER BY id ASC LIMIT 1""")
    audit_detail = pk.fetchone()[0]
    pk.execute("""SELECT count(*) FROM audit_log WHERE entity='repetition_policy'
                  AND action='repetition_policy_update_denied' AND actor='huda'""")
    denied_n = pk.fetchone()[0]
    pk.close()
    check("#184 policy change audited with before/after (default -> managed)",
          (audit_detail["before"]["source"], audit_detail["after"]["source"], denied_n >= 1),
          ("production_default", "managed", True))

    # writer-side violation check: same embedding on another slot; format decides under cross_format
    pk = conn.cursor()
    pk.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RRP')")
    for _tbl in ("topic", "script", "slot"):
        pk.execute(f"DELETE FROM {_tbl} WHERE slot_id LIKE 'RRP-%%'" if _tbl != "slot" else
                   "DELETE FROM slot WHERE round_id='RRP'")
    pk.execute("DELETE FROM script_provenance WHERE job_id IN "
               "(SELECT job_id FROM generation_job WHERE round_id='RRP')")
    pk.execute("DELETE FROM generation_job WHERE round_id='RRP'")
    pk.execute("DELETE FROM round WHERE round_id='RRP'")
    pk.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                 pillar_distribution,format_distribution,status) VALUES
                 ('RRP','rep-policy',1,3,'["09:00"]','{}','{}','planned')""")
    for sid, fmt in (("RRP-1", "Hero Reel"), ("RRP-2", "Carousel"), ("RRP-3", "Hero Reel")):
        pk.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                     hook_type,status,cycle_no,format) VALUES
                     (%s,'RRP',1,'09:00','P1_SELF','1.1','L1','Painful Truth','RESERVED',1,%s)""",
                   (sid, fmt))
    same_emb = FakeEmbed().embed("نفس الفكرة تماما")
    pk.execute("""INSERT INTO topic (slot_id,hcs_id,lens,round_id,cycle_no,text_ar,hook_text,
                 hook_type,revision,embedding) VALUES
                 ('RRP-1','1.1','L1','RRP',1,'نفس الفكرة تماما','هوك','Painful Truth',1,%s::vector)""",
               (W.vec_literal(same_emb),))
    conn.commit(); pk.close()
    rcur = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    hcs_stub = {"hcs_id": "1.1"}
    strict = {"scope": "all", "similarity_threshold": 0.86, "repeat_modes": {}}
    xformat = {"scope": "all", "similarity_threshold": 0.86, "repeat_modes": {"cross_format": True}}
    s_hero = {"slot_id": "RRP-3", "round_id": "RRP", "format": "Hero Reel"}
    s_car = {"slot_id": "RRP-2", "round_id": "RRP", "format": "Carousel"}
    s_self = {"slot_id": "RRP-1", "round_id": "RRP", "format": "Hero Reel"}
    v_sim, _, v_mode = W.repetition_check(rcur, same_emb, s_hero, hcs_stub, strict)
    check("#184 strict default: identical topic on ANOTHER slot is a violation (old hcs scope would differ)",
          (v_sim is not None and v_sim > 0.99, v_mode), (True, None))
    a_sim, _, a_mode = W.repetition_check(rcur, same_emb, s_car, hcs_stub, xformat)
    check("#184 cross_format mode allows the cross-format reuse AND names the mode",
          (a_sim is None or a_sim < 0.86, a_mode), (True, "cross_format"))
    f_sim, _, f_mode = W.repetition_check(rcur, same_emb, s_hero, hcs_stub, xformat)
    check("#184 cross_format does NOT excuse a same-format repeat",
          (f_sim is not None and f_sim > 0.99, f_mode), (True, None))
    o_sim, _, _ = W.repetition_check(rcur, same_emb, s_self, hcs_stub, strict)
    check("#184 a slot's own revisions never count as repeats",
          o_sim is None or o_sim < 0.86, True)
    rcur.close()
    pk = conn.cursor()
    pk.execute("DELETE FROM topic WHERE slot_id LIKE 'RRP-%%'")
    pk.execute("DELETE FROM slot WHERE round_id='RRP'")
    pk.execute("DELETE FROM script_provenance WHERE job_id IN "
               "(SELECT job_id FROM generation_job WHERE round_id='RRP')")
    pk.execute("DELETE FROM generation_job WHERE round_id='RRP'")
    pk.execute("DELETE FROM round WHERE round_id='RRP'")
    pk.execute("DELETE FROM repetition_policy")
    pk.execute("DELETE FROM audit_log WHERE entity='repetition_policy' OR entity_id LIKE 'RRP-%%'")
    conn.commit(); pk.close()

    # 16) #190 (#172 S1) — user_identity binding read model: identity lookup only, never authority.
    print("\n16) #190 — user_identity → principal binding resolution")
    ik = conn.cursor()
    ik.execute("DELETE FROM user_identity WHERE issuer LIKE 'https://selftest-idp%%'")
    ik.execute("""INSERT INTO user_identity (issuer, subject, principal_id, email, created_by)
                  VALUES ('https://selftest-idp', 'sub-khal', 'khal', 'k@example.test', 'selftest'),
                         ('https://selftest-idp', 'sub-inactive', 'huda', NULL, 'selftest'),
                         ('https://selftest-idp', 'sub-agent', 'agent.topic', NULL, 'selftest')""")
    ik.execute("UPDATE user_identity SET active=false WHERE subject='sub-inactive'")
    conn.commit(); ik.close()
    bound = engine.resolve_user_identity(conn, "https://selftest-idp", "sub-khal")
    check("#190 active binding resolves to the mapped principal",
          (bound or {}).get("principal_id"), "khal")
    check("#190 unknown subject resolves to None (truthfully unbound)",
          engine.resolve_user_identity(conn, "https://selftest-idp", "sub-nobody"), None)
    check("#190 inactive binding resolves to None",
          engine.resolve_user_identity(conn, "https://selftest-idp", "sub-inactive"), None)
    check("#190 a binding to a non-user principal never becomes a human identity",
          engine.resolve_user_identity(conn, "https://selftest-idp", "sub-agent"), None)
    check("#190 empty issuer/subject resolve to None",
          (engine.resolve_user_identity(conn, "", "x"), engine.resolve_user_identity(conn, "https://selftest-idp", "")),
          (None, None))
    ik = conn.cursor()
    ik.execute("DELETE FROM user_identity WHERE issuer LIKE 'https://selftest-idp%%'")
    conn.commit(); ik.close()

    # 17) #194 (#172 S2) — governed identity-binding lifecycle: authority, insert-only create,
    # CAS transitions, self-lockout protection, atomic audits. principal_id is never rewritten.
    print("\n17) #194 — identity-binding lifecycle administration")
    ISS2 = "https://s2-idp"
    # #195 re-review — the trusted canonical issuer is SERVER CONFIG on the gate API; configure it
    # for this section (and prove fail-closed behavior when it is absent, below).
    _iss_prior = os.environ.get("TANAGHOM_OIDC_ISSUER")
    os.environ["TANAGHOM_OIDC_ISSUER"] = ISS2
    xk = conn.cursor()
    xk.execute("DELETE FROM user_identity WHERE issuer=%s", (ISS2,))
    xk.execute("DELETE FROM audit_log WHERE entity='user_identity'")
    xk.execute("DELETE FROM principal_role_member WHERE principal_id='nour' AND role_id='content_owner'")
    conn.commit(); xk.close()
    check("#194 non-admin list is denied", _raises(lambda: engine.list_user_identities(conn, "huda")), True)
    check("#194 non-admin create is denied",
          _raises(lambda: engine.create_user_identity(
              conn, {"issuer": ISS2, "subject": "s1", "principal_id": "huda"}, actor="huda")), True)
    created = engine.create_user_identity(
        conn, {"issuer": ISS2, "subject": "s-huda", "principal_id": "huda", "email": "h@example.test"},
        actor="khal")
    check("#194 admin creates an ACTIVE binding", (created["active"], created["principal_id"]), (True, "huda"))
    check("#194 duplicate tuple = explicit conflict (no upsert)",
          _raises(lambda: engine.create_user_identity(
              conn, {"issuer": ISS2, "subject": "s-huda", "principal_id": "nour"}, actor="khal")), True)
    check("#194 the conflicting create did NOT overwrite the binding",
          engine.resolve_user_identity(conn, ISS2, "s-huda")["principal_id"], "huda")
    check("#194 non-user target rejected",
          _raises(lambda: engine.create_user_identity(
              conn, {"issuer": ISS2, "subject": "s-a", "principal_id": "agent.topic"}, actor="khal")), True)
    check("#194 unknown target rejected",
          _raises(lambda: engine.create_user_identity(
              conn, {"issuer": ISS2, "subject": "s-x", "principal_id": "ghost"}, actor="khal")), True)
    check("#194 control characters rejected",
          _raises(lambda: engine.create_user_identity(
              conn, {"issuer": ISS2, "subject": "bad\x01sub", "principal_id": "huda"}, actor="khal")), True)
    case_row = engine.create_user_identity(
        conn, {"issuer": ISS2, "subject": "S-HUDA", "principal_id": "huda"}, actor="khal")
    check("#194 subjects are opaque + case-sensitive (distinct tuple allowed)",
          case_row["subject"], "S-HUDA")
    d = engine.set_user_identity_active(conn, created["identity_id"], False, actor="khal")
    check("#194 deactivate = CAS true->false, principal UNCHANGED", (d["active"], d["principal_id"]),
          (False, "huda"))
    check("#194 resolver refuses the deactivated binding (revocation truth)",
          engine.resolve_user_identity(conn, ISS2, "s-huda"), None)
    check("#194 repeated deactivate = stale-state conflict",
          _raises(lambda: engine.set_user_identity_active(conn, created["identity_id"], False, actor="khal")), True)
    r17 = engine.set_user_identity_active(conn, created["identity_id"], True, actor="khal")
    check("#194 same-tuple reactivate restores ACTIVE with the SAME principal",
          (r17["active"], r17["principal_id"]), (True, "huda"))
    kb = engine.create_user_identity(
        conn, {"issuer": ISS2, "subject": "s-khal", "principal_id": "khal"}, actor="khal")
    check("#194 self-deactivation fails CLOSED while no other usable admin binding exists",
          _raises(lambda: engine.set_user_identity_active(conn, kb["identity_id"], False, actor="khal")), True)
    xk = conn.cursor()
    xk.execute("""INSERT INTO principal_role_member (role_id, principal_id, active)
                  VALUES ('content_owner','nour',true)
                  ON CONFLICT (role_id, principal_id) DO UPDATE SET active=true""")
    conn.commit(); xk.close()
    engine.create_user_identity(conn, {"issuer": ISS2, "subject": "s-nour", "principal_id": "nour"},
                                actor="khal")
    ok17 = engine.set_user_identity_active(conn, kb["identity_id"], False, actor="khal")
    check("#194 self-deactivation allowed once ANOTHER usable admin binding exists",
          ok17["active"], False)
    # #195 review — opaque subject preserved EXACTLY (round-trips with its whitespace; no repair)
    padded = engine.create_user_identity(
        conn, {"issuer": ISS2, "subject": " padded sub ", "principal_id": "huda"}, actor="khal")
    check("#195 subject preserved exactly incl. whitespace (storage + lookup)",
          (padded["subject"], engine.resolve_user_identity(conn, ISS2, " padded sub ")["principal_id"],
           engine.resolve_user_identity(conn, ISS2, "padded sub")),
          (" padded sub ", "huda", None))
    # #195 review — noncanonical issuer input is REJECTED, never normalized (and audited)
    check("#195 trailing-slash issuer rejected",
          _raises(lambda: engine.create_user_identity(
              conn, {"issuer": ISS2 + "/", "subject": "s-nc", "principal_id": "huda"}, actor="khal")), True)
    check("#195 whitespace-padded issuer rejected",
          _raises(lambda: engine.create_user_identity(
              conn, {"issuer": f" {ISS2}", "subject": "s-nc2", "principal_id": "huda"}, actor="khal")), True)
    check("#195 a DIFFERENT canonical-looking issuer is rejected (config is the only truth)",
          _raises(lambda: engine.create_user_identity(
              conn, {"issuer": "https://looks-canonical", "subject": "s-nc3", "principal_id": "huda"},
              actor="khal")), True)
    check("#195 wrong-type issuer/principal_id are rejected, never coerced",
          (_raises(lambda: engine.create_user_identity(
              conn, {"issuer": 123, "subject": "s-t", "principal_id": "huda"}, actor="khal")),
           _raises(lambda: engine.create_user_identity(
              conn, {"issuer": ISS2, "subject": "s-t", "principal_id": 123}, actor="khal"))),
          (True, True))
    # #195 re-review — config-absent FAIL-CLOSED proofs: without the trusted issuer, create and
    # deactivation refuse (audited); row/request data is never a substitute.
    del os.environ["TANAGHOM_OIDC_ISSUER"]
    check("#195 create fails CLOSED when the trusted issuer config is absent",
          _raises(lambda: engine.create_user_identity(
              conn, {"issuer": ISS2, "subject": "s-noconf", "principal_id": "huda"}, actor="khal")), True)
    check("#195 deactivation fails CLOSED when the trusted issuer config is absent",
          _raises(lambda: engine.set_user_identity_active(conn, case_row["identity_id"], False,
                                                          actor="khal")), True)
    os.environ["TANAGHOM_OIDC_ISSUER"] = ISS2
    # #195 review — a stale/different-issuer admin binding is NOT usable for the lockout proof
    xk = conn.cursor()
    xk.execute("UPDATE user_identity SET active=false WHERE issuer=%s AND subject='s-nour'", (ISS2,))
    conn.commit(); xk.close()
    kb2 = engine.create_user_identity(
        conn, {"issuer": ISS2, "subject": "s-khal-2", "principal_id": "khal"}, actor="khal")
    xk = conn.cursor()
    xk.execute("""INSERT INTO user_identity (issuer, subject, principal_id, created_by)
                  VALUES ('https://other-idp', 's-nour-other', 'nour', 'selftest-fixture')""")
    conn.commit(); xk.close()
    check("#195 an admin binding on a DIFFERENT issuer does not prevent lockout (fails closed)",
          _raises(lambda: engine.set_user_identity_active(conn, kb2["identity_id"], False, actor="khal")), True)
    # #195 review — concurrent self-deactivation race: with the advisory-lock serialization,
    # exactly ONE of two admins deactivating their own bindings can commit.
    xk = conn.cursor()
    xk.execute("UPDATE user_identity SET active=true WHERE issuer=%s AND subject='s-nour'", (ISS2,))
    conn.commit(); xk.close()
    import threading as _threading
    race_results = []
    def _race(iid, owner):
        c2 = engine.db_connect()
        try:
            engine.set_user_identity_active(c2, iid, False, actor=owner)
            race_results.append("ok")
        except engine.GateError:
            race_results.append("conflict")
        finally:
            c2.close()
    xk = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    xk.execute("SELECT identity_id::text AS i FROM user_identity WHERE issuer=%s AND subject='s-nour'", (ISS2,))
    nour_iid = xk.fetchone()["i"]
    xk.close()
    threads = [_threading.Thread(target=_race, args=(kb2["identity_id"], "khal")),
               _threading.Thread(target=_race, args=(nour_iid, "nour"))]
    for t in threads: t.start()
    for t in threads: t.join()
    xk = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    xk.execute("""SELECT count(*) AS n FROM user_identity ui JOIN principal p USING (principal_id)
                  WHERE ui.issuer=%s AND ui.active=true AND p.kind='user'
                    AND (p.role IN ('super_admin','admin','content_owner')
                         OR EXISTS (SELECT 1 FROM principal_role_member m
                                    WHERE m.principal_id=p.principal_id AND m.active
                                      AND m.role_id IN ('super_admin','admin','content_owner')))""",
               (ISS2,))
    remaining_admins = xk.fetchone()["n"]
    xk.close()
    check("#195 concurrent self-deactivations: exactly one commits, one fails closed, an admin remains",
          (sorted(race_results), remaining_admins >= 1), (["conflict", "ok"], True))

    xk = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    xk.execute("""SELECT action, count(*) AS n FROM audit_log
                  WHERE entity='user_identity' GROUP BY action""")
    audit17 = {row["action"]: row["n"] for row in xk.fetchall()}
    xk.execute("""SELECT count(*) AS n FROM audit_log
                  WHERE entity='user_identity' AND action='identity_binding.denied'
                    AND detail->>'reason' = 'invalid_input'""")
    invalid_input_audits = xk.fetchone()["n"]
    xk.close()
    check("#194/#195 successes + ALL attributable denials/conflicts are audited (incl. invalid input)",
          (audit17.get("identity_binding.created", 0) >= 6,
           audit17.get("identity_binding.deactivated", 0) >= 3,
           audit17.get("identity_binding.reactivated", 0) >= 1,
           audit17.get("identity_binding.denied", 0) >= 10,
           audit17.get("identity_binding.conflict", 0) >= 2,
           invalid_input_audits >= 7),
          (True, True, True, True, True, True))
    xk = conn.cursor()
    xk.execute("DELETE FROM user_identity WHERE issuer IN (%s, 'https://other-idp')", (ISS2,))
    xk.execute("DELETE FROM audit_log WHERE entity='user_identity'")
    xk.execute("DELETE FROM principal_role_member WHERE principal_id='nour' AND role_id='content_owner'")
    conn.commit(); xk.close()
    if _iss_prior is None:
        os.environ.pop("TANAGHOM_OIDC_ISSUER", None)
    else:
        os.environ["TANAGHOM_OIDC_ISSUER"] = _iss_prior

    # 18) #200 (pub.v1) — first-class manual publication recording.
    print("\n18) #200 — pub.v1 manual publication recording")
    import publication as PUB
    import dam as DAM

    def _pub_cleanup():
        k = conn.cursor()
        k.execute("ALTER TABLE publication_event DISABLE TRIGGER trg_publication_event_immutable")
        k.execute("ALTER TABLE publication DISABLE TRIGGER trg_publication_frozen")
        k.execute("ALTER TABLE publication_raw_asset DISABLE TRIGGER trg_publication_raw_asset_frozen")
        k.execute("DELETE FROM publication_raw_asset WHERE publication_intent_id IN "
                  "(SELECT publication_intent_id FROM publication WHERE slot_id LIKE 'RPUB-%%')")
        k.execute("DELETE FROM publication_event WHERE publication_intent_id IN "
                  "(SELECT publication_intent_id FROM publication WHERE slot_id LIKE 'RPUB-%%')")
        k.execute("DELETE FROM publication WHERE slot_id LIKE 'RPUB-%%'")
        k.execute("ALTER TABLE publication_raw_asset ENABLE TRIGGER trg_publication_raw_asset_frozen")
        k.execute("ALTER TABLE publication ENABLE TRIGGER trg_publication_frozen")
        k.execute("ALTER TABLE publication_event ENABLE TRIGGER trg_publication_event_immutable")
        k.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t "
                  "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RPUB')")
        for _t in ("asset", "script", "topic", "slot_approval", "slot_review", "directive"):
            k.execute(f"DELETE FROM {_t} WHERE slot_id LIKE 'RPUB-%%'")
        k.execute("DELETE FROM slot WHERE round_id='RPUB'")
        k.execute("DELETE FROM script_provenance WHERE job_id IN "
                  "(SELECT job_id FROM generation_job WHERE round_id='RPUB')")
        k.execute("DELETE FROM generation_job WHERE round_id='RPUB'")
        k.execute("DELETE FROM round WHERE round_id='RPUB'")
        k.execute("DELETE FROM audit_log WHERE entity='publication' OR entity_id LIKE 'RPUB-%%'")
        k.execute("DELETE FROM principal_role_member WHERE principal_id='nour' AND role_id='content_owner'")
        # NOTE: psycopg2 runs this whole block in ONE transaction — the trigger DISABLE/ENABLE and
        # the deletes commit or roll back TOGETHER, so the guards can never be left disabled.
        conn.commit(); k.close()

    _pub_cleanup()
    pk18 = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    pk18.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                    pillar_distribution,format_distribution,status) VALUES
                    ('RPUB','pub-e2e',1,4,'["09:00"]','{}','{}','planned')""")
    for sid, sstatus in (("RPUB-1", "SCHEDULED"), ("RPUB-2", "EDITED"),
                         ("RPUB-3", "SCHEDULED"), ("RPUB-4", "SCHEDULED"),
                         ("RPUB-5", "SCHEDULED"), ("RPUB-6", "SCHEDULED"),
                         ("RPUB-7", "SCHEDULED"), ("RPUB-8", "SCHEDULED")):
        pk18.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                        hook_type,status,cycle_no,format) VALUES
                        (%s,'RPUB',1,'09:00','P1_SELF','1.1','L1','Painful Truth',%s,1,'Hero Reel')""",
                     (sid, sstatus))
        pk18.execute("INSERT INTO script (slot_id,hcs_id,lens,script_ar,revision) "
                     "VALUES (%s,'1.1','L1','نص',1)", (sid,))
    conn.commit()

    def _fixture_gate(stage, slot_id, assign_user=None, status="approved"):
        pk18.execute("""INSERT INTO gate (scope, stage, policy, rule_key, quorum, status)
                        VALUES ('batch',%s,'fixed','any','1',%s) RETURNING gate_id""",
                     (stage, status))
        gid = pk18.fetchone()["gate_id"]
        pk18.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,%s)", (gid, slot_id))
        pk18.execute("INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision) "
                     "VALUES (%s,%s,'khal','approve')", (gid, slot_id))
        if assign_user:
            pk18.execute("""INSERT INTO gate_assignment (gate_id, assignment_kind, assignment_key,
                            resolved_principal_id) VALUES (%s,'user',%s,%s)""",
                         (gid, assign_user, assign_user))
        return gid

    for sid in ("RPUB-1", "RPUB-4"):
        _fixture_gate("production_review", sid)
        _fixture_gate("edit_review", sid)
        _fixture_gate("distribution_review", sid, assign_user="khal")
        conn.commit()
        DAM.add_asset(conn, sid, "production", "raw_cut", uri=f"placeholder://raw/{sid}", actor="selftest")
        DAM.add_asset(conn, sid, "media_edit", "edit", uri=f"placeholder://edit/{sid}", actor="selftest")
    _fixture_gate("production_review", "RPUB-3")
    _fixture_gate("edit_review", "RPUB-3")
    _fixture_gate("distribution_review", "RPUB-3", assign_user="khal")
    conn.commit()
    DAM.add_asset(conn, "RPUB-3", "media_edit", "edit", uri="placeholder://edit/RPUB-3", actor="selftest")
    # RPUB-5: full chain but the distribution gate is NOT resolved (open + approve decision) — B1
    _fixture_gate("production_review", "RPUB-5")
    _fixture_gate("edit_review", "RPUB-5")
    g5 = _fixture_gate("distribution_review", "RPUB-5", assign_user="khal", status="open")
    # RPUB-6: full chain; distribution gate snapshot is ROLE-ONLY (no direct user) — B3
    _fixture_gate("production_review", "RPUB-6")
    _fixture_gate("edit_review", "RPUB-6")
    pk18.execute("""INSERT INTO gate (scope, stage, policy, rule_key, quorum, status)
                    VALUES ('batch','distribution_review','fixed','any','1','approved')
                    RETURNING gate_id""")
    g6 = pk18.fetchone()["gate_id"]
    pk18.execute("INSERT INTO gate_target (gate_id, slot_id) VALUES (%s,'RPUB-6')", (g6,))
    pk18.execute("INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision) "
                 "VALUES (%s,'RPUB-6','khal','approve')", (g6,))
    pk18.execute("""INSERT INTO gate_assignment (gate_id, assignment_kind, assignment_key)
                    VALUES (%s,'role','content_owner')""", (g6,))
    pk18.execute("DELETE FROM principal_role_member WHERE principal_id='nour' AND role_id='content_owner'")
    pk18.execute("""INSERT INTO principal_role_member (principal_id, role_id, active)
                    VALUES ('nour','content_owner',true)""")
    conn.commit()
    for sid in ("RPUB-5", "RPUB-6"):
        DAM.add_asset(conn, sid, "production", "raw_cut", uri=f"placeholder://raw/{sid}", actor="selftest")
        DAM.add_asset(conn, sid, "media_edit", "edit", uri=f"placeholder://edit/{sid}", actor="selftest")
    # RPUB-7: MVCC race fixture — four dedicated raw assets (one per race, never shared with other
    # checks) + the minimum FK targets for a DIRECT publication INSERT (races target the trigger).
    g7 = _fixture_gate("distribution_review", "RPUB-7", assign_user="khal")
    pk18.execute("""INSERT INTO asset (slot_id, stage, kind, uri, created_by)
                    SELECT 'RPUB-7','production','raw_cut','placeholder://raw/RPUB-7-'||i,'selftest'
                    FROM generate_series(1,6) AS i RETURNING asset_id""")
    raw7 = [str(r["asset_id"]) for r in pk18.fetchall()]
    pk18.execute("""INSERT INTO asset (slot_id, stage, kind, uri, created_by)
                    VALUES ('RPUB-7','media_edit','edit','placeholder://edit/RPUB-7','selftest')
                    RETURNING asset_id""")
    edit7 = str(pk18.fetchone()["asset_id"])
    conn.commit()
    # RPUB-8: full committed chain — the per-field stale-lineage family drifts ONE truth at a
    # time against an intent frozen here, then restores it.
    _fixture_gate("production_review", "RPUB-8")
    _fixture_gate("edit_review", "RPUB-8")
    _fixture_gate("distribution_review", "RPUB-8", assign_user="khal")
    conn.commit()
    DAM.add_asset(conn, "RPUB-8", "production", "raw_cut", uri="placeholder://raw/RPUB-8", actor="selftest")
    DAM.add_asset(conn, "RPUB-8", "media_edit", "edit", uri="placeholder://edit/RPUB-8", actor="selftest")

    def _praises(fn):
        try:
            fn(); return False
        except PUB.PublicationError:
            return True

    K1 = "op-rpub1-alpha"
    check("#200 no committed distribution approval -> not eligible",
          _praises(lambda: PUB.create_intent(conn, cfg, {"slot_id": "RPUB-2", "platform_key": "instagram",
                                                         "idempotency_key": "k-x"}, actor="khal")), True)
    check("#200 missing raw readiness -> not eligible (asset presence never infers readiness)",
          _praises(lambda: PUB.create_intent(conn, cfg, {"slot_id": "RPUB-3", "platform_key": "instagram",
                                                         "idempotency_key": "k-y"}, actor="khal")), True)
    check("#200 unauthorized actor cannot create an intent",
          _praises(lambda: PUB.create_intent(conn, cfg, {"slot_id": "RPUB-1", "platform_key": "instagram",
                                                         "idempotency_key": "k-z"}, actor="nour")), True)
    made1 = PUB.create_intent(conn, cfg, {"slot_id": "RPUB-1", "platform_key": "instagram",
                                          "idempotency_key": K1}, actor="khal")
    check("#200 authorized intent freezes lineage + starts the event stream",
          (made1["current_state"], len(made1["events"]),
           made1["production_gate_id"] is not None, made1["edit_output_version"] >= 1),
          ("ready", 1, True, True))
    replay = PUB.create_intent(conn, cfg, {"slot_id": "RPUB-1", "platform_key": "instagram",
                                           "idempotency_key": K1}, actor="khal")
    check("#200 identical double-submit -> ONE canonical intent (exact replay)",
          str(replay["publication_intent_id"]) == str(made1["publication_intent_id"]), True)
    check("#200 same key + different bound data -> hard conflict",
          _praises(lambda: PUB.create_intent(conn, cfg, {"slot_id": "RPUB-4", "platform_key": "instagram",
                                                         "idempotency_key": K1}, actor="khal")), True)
    done1 = PUB.record_manual_outcome(conn, cfg, made1["publication_intent_id"],
                                      {"outcome": "published", "url": "https://ig.example/p/1"},
                                      actor="khal")
    check("#200 manual attested outcome sets the durable occurrence once",
          (done1["current_state"], done1["publication_occurrence_id"] is not None,
           [e["event_type"] for e in done1["events"]]),
          ("published (manually attested)", True,
           ["intent_created", "attempt_started", "published_manually_attested"]))
    check("#200 second outcome on a published intent -> conflict (repost = new intent)",
          _praises(lambda: PUB.record_manual_outcome(conn, cfg, made1["publication_intent_id"],
                                                     {"outcome": "published"}, actor="khal")), True)
    corrected = PUB.create_intent(conn, cfg, {"slot_id": "RPUB-1", "platform_key": "instagram",
                                              "idempotency_key": "op-rpub1-corrected",
                                              "corrects_publication_intent_id": str(made1["publication_intent_id"])},
                                  actor="khal")
    check("#200 corrected repost is a NEW linked intent",
          (str(corrected["publication_intent_id"]) != str(made1["publication_intent_id"]),
           str(corrected["corrects_publication_intent_id"]) == str(made1["publication_intent_id"])),
          (True, True))
    check("#200 malformed ids / timestamps / unknown corrections are refused as invalid input",
          (_praises(lambda: PUB.record_manual_outcome(conn, cfg, "not-a-uuid",
                                                      {"outcome": "published"}, actor="khal")),
           _praises(lambda: PUB.record_manual_outcome(conn, cfg, corrected["publication_intent_id"],
                                                      {"outcome": "published", "occurred_at": "yesterday-ish"},
                                                      actor="khal")),
           _praises(lambda: PUB.create_intent(conn, cfg, {"slot_id": "RPUB-1", "platform_key": "instagram",
                                                          "idempotency_key": "k-corr2",
                                                          "corrects_publication_intent_id": "nope"},
                                              actor="khal"))), (True, True, True))
    PUB.record_manual_outcome(conn, cfg, corrected["publication_intent_id"],
                              {"outcome": "published", "external_ref": "IG-REF-1",
                               "external_object_type": "post"}, actor="khal")
    third = PUB.create_intent(conn, cfg, {"slot_id": "RPUB-1", "platform_key": "instagram",
                                          "idempotency_key": "op-rpub1-third"}, actor="khal")
    check("#200 the same provider-local post reference can never be claimed twice (scoped unique)",
          _praises(lambda: PUB.record_manual_outcome(conn, cfg, third["publication_intent_id"],
                                                     {"outcome": "published", "external_ref": "IG-REF-1",
                                                      "external_object_type": "post"}, actor="khal")),
          True)
    made4 = PUB.create_intent(conn, cfg, {"slot_id": "RPUB-4", "platform_key": "instagram",
                                          "idempotency_key": "op-rpub4"}, actor="khal")
    DAM.add_asset(conn, "RPUB-4", "media_edit", "edit", uri="placeholder://edit/RPUB-4-v2", actor="selftest")
    check("#200 superseded edit output denies success recording (stale lineage fails closed)",
          _praises(lambda: PUB.record_manual_outcome(conn, cfg, made4["publication_intent_id"],
                                                     {"outcome": "published"}, actor="khal")), True)

    # B-B (re-review) — success recording verifies the COMPLETE frozen lineage against the current
    # committed evidence. Per field-class: drift ONE truth, expect a fail-closed denial whose audit
    # names exactly the drifted field(s), restore, move on. After all restores, success records.
    made8 = PUB.create_intent(conn, cfg, {"slot_id": "RPUB-8", "platform_key": "instagram",
                                          "idempotency_key": "op-rpub8"}, actor="khal")
    iid8 = str(made8["publication_intent_id"])

    def _stale8(expect_fields):
        denied = _praises(lambda: PUB.record_manual_outcome(conn, cfg, iid8,
                                                            {"outcome": "published"}, actor="khal"))
        pk18.execute("""SELECT detail FROM audit_log WHERE entity='publication' AND entity_id=%s
                        AND action='publication_denied' ORDER BY id DESC LIMIT 1""", (iid8,))
        row = pk18.fetchone()
        det = row["detail"] if row else {}
        return (denied, det.get("reason"),
                sorted(det.get("stale_fields") or [])) == (True, "stale_lineage",
                                                           sorted(expect_fields))

    gate_drift = {}
    for field, stage in (("distribution_gate_id", "distribution_review"),
                         ("production_gate_id", "production_review"),
                         ("edit_gate_id", "edit_review")):
        gid = _fixture_gate(stage, "RPUB-8")      # a NEWER resolved gate supersedes the frozen id
        conn.commit()
        gate_drift[field] = _stale8([field])
        pk18.execute("DELETE FROM gate_decision WHERE gate_id=%s", (gid,))
        pk18.execute("DELETE FROM gate_target WHERE gate_id=%s", (gid,))
        pk18.execute("DELETE FROM gate WHERE gate_id=%s", (gid,))
        conn.commit()
    check("#200 stale distribution/production/edit gate ids each deny success, audited with the "
          "drifted field named",
          gate_drift, {"distribution_gate_id": True, "production_gate_id": True,
                       "edit_gate_id": True})
    pk18.execute("INSERT INTO script (slot_id,hcs_id,lens,script_ar,revision) "
                 "VALUES ('RPUB-8','1.1','L1','v2',2) RETURNING script_id")
    script8_v2 = pk18.fetchone()["script_id"]
    conn.commit()
    script_drift = _stale8(["script_id"])
    pk18.execute("DELETE FROM script WHERE script_id=%s", (script8_v2,))
    conn.commit()
    pk18.execute("""INSERT INTO asset (slot_id, stage, kind, uri, version, created_by)
                    VALUES ('RPUB-8','media_edit','edit','placeholder://edit/RPUB-8-v2',2,'selftest')
                    RETURNING asset_id""")
    edit8_v2 = str(pk18.fetchone()["asset_id"])
    conn.commit()
    asset_drift = _stale8(["edit_output_asset_id", "edit_output_version"])
    pk18.execute("DELETE FROM asset WHERE asset_id=%s", (edit8_v2,))
    conn.commit()
    edit8 = str(made8["edit_output_asset_id"])
    pk18.execute("UPDATE asset SET version=9 WHERE asset_id=%s", (edit8,))
    conn.commit()
    version_drift = _stale8(["edit_output_version"])
    pk18.execute("UPDATE asset SET version=%s WHERE asset_id=%s",
                 (made8["edit_output_version"], edit8))
    conn.commit()
    pk18.execute("UPDATE asset SET platform_variant='9x16-reel' WHERE asset_id=%s", (edit8,))
    conn.commit()
    rendition_drift = _stale8(["edit_output_rendition"])
    pk18.execute("UPDATE asset SET platform_variant=%s WHERE asset_id=%s",
                 (made8["edit_output_rendition"], edit8))
    conn.commit()
    pk18.execute("""INSERT INTO asset (slot_id, stage, kind, uri, created_by)
                    VALUES ('RPUB-8','production','raw_cut','placeholder://raw/RPUB-8-x','selftest')
                    RETURNING asset_id""")
    raw8_extra = str(pk18.fetchone()["asset_id"])
    conn.commit()
    raw_drift = _stale8(["raw_asset_ids"])
    pk18.execute("DELETE FROM asset WHERE asset_id=%s", (raw8_extra,))
    conn.commit()
    check("#200 stale script revision / edit asset+version / version-only / rendition / raw "
          "readiness set each deny success, audited with the drifted field(s) named",
          (script_drift, asset_drift, version_drift, rendition_drift, raw_drift),
          (True, True, True, True, True))
    done8 = PUB.record_manual_outcome(conn, cfg, iid8, {"outcome": "published"}, actor="khal")
    check("#200 with every restored field matching the frozen lineage again, success records",
          (done8["current_state"], done8["publication_occurrence_id"] is not None),
          ("published (manually attested)", True))

    # B1 — ONLY a RESOLVED 'approved' gate is a committed approval. RPUB-5's distribution gate
    # carries an approve decision but is open / changes_requested / rejected → never eligible.
    def _c5(key):
        return lambda: PUB.create_intent(conn, cfg, {"slot_id": "RPUB-5", "platform_key": "instagram",
                                                     "idempotency_key": key}, actor="khal")
    unresolved = [_praises(_c5("k5-open"))]
    for g5_status in ("changes_requested", "rejected"):
        pk18.execute("UPDATE gate SET status=%s WHERE gate_id=%s", (g5_status, g5))
        conn.commit()
        unresolved.append(_praises(_c5(f"k5-{g5_status}")))
    pk18.execute("UPDATE gate SET status='approved' WHERE gate_id=%s", (g5,))
    conn.commit()
    made5 = PUB.create_intent(conn, cfg, {"slot_id": "RPUB-5", "platform_key": "instagram",
                                          "idempotency_key": "op-rpub5", "destination": "@main"},
                              actor="khal")
    check("#200 open/changes-requested/rejected gates with approve decisions are NEVER committed "
          "approvals; the RESOLVED gate is",
          (unresolved, made5["current_state"]), ([True, True, True], "ready"))

    # B2 — the idempotent replay binds EVERY frozen field: any difference under the same key is a
    # hard conflict, per class (destination, correction link, source/script revision).
    replay5 = PUB.create_intent(conn, cfg, {"slot_id": "RPUB-5", "platform_key": "instagram",
                                            "idempotency_key": "op-rpub5", "destination": "@main"},
                                actor="khal")
    b2_dest = _praises(lambda: PUB.create_intent(conn, cfg, {"slot_id": "RPUB-5", "platform_key": "instagram",
                                                             "idempotency_key": "op-rpub5",
                                                             "destination": "@other"}, actor="khal"))
    b2_corr = _praises(lambda: PUB.create_intent(conn, cfg, {"slot_id": "RPUB-5", "platform_key": "instagram",
                                                             "idempotency_key": "op-rpub5", "destination": "@main",
                                                             "corrects_publication_intent_id": str(made1["publication_intent_id"])},
                                                 actor="khal"))
    pk18.execute("INSERT INTO script (slot_id,hcs_id,lens,script_ar,revision) "
                 "VALUES ('RPUB-5','1.1','L1','نص محدث',2)")
    conn.commit()
    b2_script = _praises(lambda: PUB.create_intent(conn, cfg, {"slot_id": "RPUB-5", "platform_key": "instagram",
                                                               "idempotency_key": "op-rpub5",
                                                               "destination": "@main"}, actor="khal"))
    check("#200 exact replay converges; same key + changed destination/correction/script-revision "
          "each hard-conflict",
          (str(replay5["publication_intent_id"]) == str(made5["publication_intent_id"]),
           b2_dest, b2_corr, b2_script), (True, True, True, True))

    # B3 — authority is the DIRECT user assignment only: role membership (nour IS content_owner,
    # the gate names role:content_owner) grants nothing; adding the direct user assignment does.
    b3_role = _praises(lambda: PUB.create_intent(conn, cfg, {"slot_id": "RPUB-6", "platform_key": "instagram",
                                                             "idempotency_key": "op-rpub6-nour"}, actor="nour"))
    b3_khal_no_direct = _praises(lambda: PUB.create_intent(conn, cfg, {"slot_id": "RPUB-6", "platform_key": "instagram",
                                                                       "idempotency_key": "op-rpub6-khal"}, actor="khal"))
    pk18.execute("""INSERT INTO gate_assignment (gate_id, assignment_kind, assignment_key,
                    resolved_principal_id) VALUES (%s,'user','khal','khal')""", (g6,))
    conn.commit()
    made6 = PUB.create_intent(conn, cfg, {"slot_id": "RPUB-6", "platform_key": "instagram",
                                          "idempotency_key": "op-rpub6-user"}, actor="khal")
    b3_role_after = _praises(lambda: PUB.create_intent(conn, cfg, {"slot_id": "RPUB-6", "platform_key": "instagram",
                                                                   "idempotency_key": "op-rpub6-nour2"}, actor="nour"))
    check("#200 role/group membership NEVER grants attest authority; only the direct user "
          "assignment does (mixed snapshot: user granted, role member still denied)",
          (b3_role, b3_khal_no_direct, made6["current_state"], b3_role_after),
          (True, True, "ready", True))

    def _sql_raises(sql, params=()):
        try:
            k = conn.cursor(); k.execute(sql, params); conn.commit(); k.close()
            return False
        except Exception:
            conn.rollback()
            return True

    check("#200 publication events are append-only at the DATABASE level",
          (_sql_raises("UPDATE publication_event SET actor='x' WHERE publication_intent_id=%s",
                       (str(made1["publication_intent_id"]),)),
           _sql_raises("DELETE FROM publication_event WHERE publication_intent_id=%s",
                       (str(made1["publication_intent_id"]),))), (True, True))
    check("#200 publication identity/occurrence fields are DB-frozen (no update/retarget/delete)",
          (_sql_raises("UPDATE publication SET idempotency_key='hax' WHERE publication_intent_id=%s",
                       (str(made1["publication_intent_id"]),)),
           _sql_raises("UPDATE publication SET publication_occurrence_id=gen_random_uuid() "
                       "WHERE publication_intent_id=%s", (str(made1["publication_intent_id"]),)),
           _sql_raises("DELETE FROM publication WHERE publication_intent_id=%s",
                       (str(made1["publication_intent_id"]),))), (True, True, True))
    # B5 — destination is immutable from creation; ALL occurrence evidence is frozen once recorded
    check("#200 destination is DB-immutable from creation (even before any occurrence)",
          _sql_raises("UPDATE publication SET destination='moved' WHERE publication_intent_id=%s",
                      (str(third["publication_intent_id"]),)), True)
    check("#200 occurrence evidence (url/refs/times) is DB-frozen after recording — future "
          "reconciliation appends typed events, it never overwrites",
          (_sql_raises("UPDATE publication SET url='https://rewritten' WHERE publication_intent_id=%s",
                       (str(made1["publication_intent_id"]),)),
           _sql_raises("UPDATE publication SET external_ref='REWRITTEN' WHERE publication_intent_id=%s",
                       (str(corrected["publication_intent_id"]),)),
           _sql_raises("UPDATE publication SET external_object_type='page' WHERE publication_intent_id=%s",
                       (str(corrected["publication_intent_id"]),)),
           _sql_raises("UPDATE publication SET provider_reported_at=now() WHERE publication_intent_id=%s",
                       (str(made1["publication_intent_id"]),))), (True, True, True, True))
    # B4 — raw SDAM lineage is referentially protected by NATIVE non-cascading FKs on the
    # publication_raw_asset junction (operator-authorized amendment): a referenced asset can be
    # neither deleted nor id-retargeted, an unknown asset can never be referenced (the junction
    # INSERT runs pre-event in the creating transaction, so the FK — not the freeze trigger — is
    # what refuses it), and unreferenced assets remain deletable.
    # _pub7 mirrors the canonical creating transaction as DIRECT SQL: publication, then its raw
    # readiness rows, then the first event — deterministic statement order (a single
    # data-modifying CTE would leave sub-statement order unspecified). Callers may drop trailing
    # statements to prove the deferred completeness constraint refuses partial commits.
    import uuid as _uuidmod

    _PUB7_INTENT = ("INSERT INTO publication (publication_intent_id, execution_source, "
                    "provider_key, destination_account_scope, platform_key, idempotency_key, "
                    "slot_id, edit_output_asset_id, edit_output_version, distribution_gate_id, "
                    "created_by) "
                    "VALUES (%s,'manual','manual','-','instagram',%s,'RPUB-7',%s,1,%s,'selftest')")
    _PUB7_RAWS = ("INSERT INTO publication_raw_asset (publication_intent_id, asset_id) "
                  "SELECT %s, unnest(%s::uuid[])")
    _PUB7_EVENT = ("INSERT INTO publication_event (publication_intent_id, event_seq, event_type, "
                   "event_source, actor, detail) "
                   "VALUES (%s,%s,%s,'manual','selftest','{}'::jsonb)")

    def _pub7(key, raws, with_raws=True, with_event=True, event_seq=1,
              event_type="intent_created"):
        iid = str(_uuidmod.uuid4())
        sql, params = _PUB7_INTENT, [iid, key, edit7, g7]
        if with_raws:
            sql += "; " + _PUB7_RAWS
            params += [iid, raws]
        if with_event:
            sql += "; " + _PUB7_EVENT
            params += [iid, event_seq, event_type]
        return iid, sql, tuple(params)

    raw0 = str(made1["raw_asset_ids"][0])
    pk18.execute("""SELECT asset_id FROM asset WHERE slot_id='RPUB-3' AND stage='media_edit'
                    ORDER BY version DESC LIMIT 1""")
    unreferenced_asset = str(pk18.fetchone()["asset_id"])
    _, badraw_sql, badraw_params = _pub7("k-badraw", ["00000000-0000-0000-0000-00000000dead"])
    check("#200 raw readiness lineage cannot be deleted/retargeted/faked — native FK truth",
          (_sql_raises("DELETE FROM asset WHERE asset_id=%s", (raw0,)),
           _sql_raises("UPDATE asset SET asset_id=gen_random_uuid() WHERE asset_id=%s", (raw0,)),
           _sql_raises(badraw_sql, badraw_params),
           _sql_raises("DELETE FROM asset WHERE asset_id=%s", (unreferenced_asset,))),
          (True, True, True, False))
    # Atomic intent creation (source-visible re-review) — the DEFERRED completeness constraint:
    # a publication can only COMMIT together with ≥1 raw readiness row AND the CANONICAL first
    # event (event_seq=1 AND event_type='intent_created'); a history seeded any other way — no
    # event, seq 2 only, or a wrong-typed seq 1 — is not intent creation and never commits, so no
    # eventless/wrongly-seeded parent exists for a later transaction to append lineage to.
    _, bare_sql, bare_params = _pub7("cmplt-bare", [], with_raws=False, with_event=False)
    _, noev_sql, noev_params = _pub7("cmplt-noevent", [raw7[4]], with_event=False)
    _, seq2_sql, seq2_params = _pub7("cmplt-seq2", [raw7[4]], event_seq=2)
    _, wrongt_sql, wrongt_params = _pub7("cmplt-wrongtype", [raw7[4]],
                                         event_type="attempt_started")
    ok_iid, ok_sql, ok_params = _pub7("cmplt-ok", [raw7[5]])
    check("#200 intent creation is DB-atomic and canonically seeded: no-event / seq-2-only / "
          "wrong-typed-seq-1 commits all fail, the canonical seq=1 intent_created transaction "
          "succeeds, and a LATER transaction can never append lineage",
          (_sql_raises(bare_sql, bare_params),                 # publication alone -> refused
           _sql_raises(noev_sql, noev_params),                 # junction, no event -> refused
           _sql_raises(seq2_sql, seq2_params),                 # seq=2 only -> refused
           _sql_raises(wrongt_sql, wrongt_params),             # seq=1 wrong type -> refused
           _sql_raises(ok_sql, ok_params),                     # canonical create -> commits
           _sql_raises("INSERT INTO publication_raw_asset (publication_intent_id, asset_id) "
                       "VALUES (%s,%s)", (ok_iid, raw7[4]))),  # cross-txn late append -> frozen
          (True, True, True, True, False, True))
    # event_seq is DB-bounded to >= 1: nothing can be prepended UNDER the canonical first event
    # (canonical seq=1 success is the cmplt-ok commit just above; later positive appends stay
    # legal — that's the ordinary attempt history).
    check("#200 zero/negative event sequences are refused by the DB; subsequent positive "
          "sequences still append",
          (_sql_raises(_PUB7_EVENT, (ok_iid, 0, "attempt_started")),
           _sql_raises(_PUB7_EVENT, (ok_iid, -1, "attempt_started")),
           _sql_raises(_PUB7_EVENT, (ok_iid, 2, "attempt_started"))),
          (True, True, False))
    check("#200 the raw readiness SET is frozen: junction rows can never be updated/deleted, and "
          "nothing can be appended once the intent has history",
          (_sql_raises("DELETE FROM publication_raw_asset WHERE publication_intent_id=%s",
                       (str(made1["publication_intent_id"]),)),
           _sql_raises("UPDATE publication_raw_asset SET asset_id=gen_random_uuid() "
                       "WHERE publication_intent_id=%s", (str(made1["publication_intent_id"]),)),
           _sql_raises("INSERT INTO publication_raw_asset (publication_intent_id, asset_id) "
                       "VALUES (%s,%s)", (str(made1["publication_intent_id"]), edit7))),
          (True, True, True))

    # B6 — GENUINE concurrency: independent connections, barrier-released threads.
    import threading as _th

    def _race(fn_a, fn_b):
        barrier = _th.Barrier(2)
        out = {}

        def runner(tag, fn):
            c2 = engine.db_connect()
            try:
                barrier.wait(timeout=15)
                out[tag] = ("ok", fn(c2))
            except PUB.PublicationError as e:
                out[tag] = ("conflict", str(e))
            except Exception as e:  # noqa: BLE001 — a race must never fail silently
                out[tag] = ("error", str(e))
            finally:
                c2.close()
        ta = _th.Thread(target=runner, args=("a", fn_a))
        tb = _th.Thread(target=runner, args=("b", fn_b))
        ta.start(); tb.start(); ta.join(30); tb.join(30)
        return out

    race_payload = {"slot_id": "RPUB-4", "platform_key": "instagram",
                    "idempotency_key": "race-create-1"}
    r1 = _race(lambda c: str(PUB.create_intent(c, cfg, dict(race_payload), actor="khal")["publication_intent_id"]),
               lambda c: str(PUB.create_intent(c, cfg, dict(race_payload), actor="khal")["publication_intent_id"]))
    pk18.execute("SELECT count(*) AS n FROM publication WHERE idempotency_key='race-create-1'")
    check("#200 CONCURRENT same-key creates -> ONE row; both independent transactions converge on "
          "the same canonical intent",
          (pk18.fetchone()["n"], r1["a"][0], r1["b"][0], r1["a"][1] == r1["b"][1]),
          (1, "ok", "ok", True))
    race_intent = r1["a"][1]
    r2 = _race(lambda c: PUB.record_manual_outcome(c, cfg, race_intent, {"outcome": "published"},
                                                   actor="khal") and "done",
               lambda c: PUB.record_manual_outcome(c, cfg, race_intent, {"outcome": "published"},
                                                   actor="khal") and "done")
    pk18.execute("SELECT publication_occurrence_id FROM publication WHERE publication_intent_id=%s",
                 (race_intent,))
    occ_once = pk18.fetchone()["publication_occurrence_id"] is not None
    pk18.execute("SELECT array_agg(event_seq ORDER BY event_seq) AS seqs FROM publication_event "
                 "WHERE publication_intent_id=%s", (race_intent,))
    check("#200 CONCURRENT success recordings -> exactly ONE occurrence, the loser gets a "
          "deterministic conflict, no lost/duplicate events",
          (sorted(v[0] for v in r2.values()), occ_once, pk18.fetchone()["seqs"]),
          (["conflict", "ok"], True, [1, 2, 3]))
    made_seq = PUB.create_intent(conn, cfg, {"slot_id": "RPUB-1", "platform_key": "instagram",
                                             "idempotency_key": "race-seq-1"}, actor="khal")
    seq_intent = str(made_seq["publication_intent_id"])
    r3 = _race(lambda c: PUB.record_manual_outcome(c, cfg, seq_intent,
                                                   {"outcome": "failed", "notes": "attempt A"},
                                                   actor="khal") and "done",
               lambda c: PUB.record_manual_outcome(c, cfg, seq_intent,
                                                   {"outcome": "failed", "notes": "attempt B"},
                                                   actor="khal") and "done")
    pk18.execute("SELECT array_agg(event_seq ORDER BY event_seq) AS seqs FROM publication_event "
                 "WHERE publication_intent_id=%s", (seq_intent,))
    check("#200 CONCURRENT event appends serialize: both attempts land, sequences unique and "
          "contiguous, no lost event",
          (sorted(v[0] for v in r3.values()), pk18.fetchone()["seqs"]),
          (["ok", "ok"], [1, 2, 3, 4, 5]))

    # B-A (re-review) — raw-lineage referential integrity UNDER MVCC, now enforced by the native
    # junction FKs. Deterministic overlap: the FIRST transaction executes and HOLDS its locks
    # uncommitted while the SECOND runs, so the outcome is forced by the FK row locks
    # (PostgreSQL's own machinery), never by lucky serial timing.
    import time as _time

    def _overlap(first_sql, first_params, second_sql, second_params, hold=0.8):
        first_in = _th.Event()
        out = {}

        def _first():
            c1 = engine.db_connect()
            try:
                k1 = c1.cursor()
                k1.execute(first_sql, first_params)
                first_in.set()
                _time.sleep(hold)                 # second is now blocked on our row locks
                c1.commit()
                out["first"] = "ok"
            except Exception as e:  # noqa: BLE001 — a race must never fail silently
                first_in.set()
                c1.rollback()
                out["first"] = f"error: {e}"
            finally:
                c1.close()

        def _second():
            c2 = engine.db_connect()
            try:
                first_in.wait(10)
                k2 = c2.cursor()
                k2.execute(second_sql, second_params)
                c2.commit()
                out["second"] = "ok"
            except Exception as e:  # noqa: BLE001
                c2.rollback()
                out["second"] = f"error: {e}"
            finally:
                c2.close()

        t1 = _th.Thread(target=_first)
        t2 = _th.Thread(target=_second)
        t1.start(); t2.start(); t1.join(30); t2.join(30)
        return out.get("first"), out.get("second")

    _, fk1_sql, fk1_params = _pub7("fkrace-1", [raw7[0]])
    _, fk2_sql, fk2_params = _pub7("fkrace-2", [raw7[1]])
    ins_then_del = _overlap(fk1_sql, fk1_params,
                            "DELETE FROM asset WHERE asset_id=%s", (raw7[0],))
    del_then_ins = _overlap("DELETE FROM asset WHERE asset_id=%s", (raw7[1],),
                            fk2_sql, fk2_params)
    check("#200 publication INSERT vs concurrent asset DELETE: in BOTH orderings the second "
          "committer is refused — a dangling raw reference can never commit",
          (ins_then_del[0], str(ins_then_del[1]).startswith("error"),
           del_then_ins[0], str(del_then_ins[1]).startswith("error")),
          ("ok", True, "ok", True))
    _, fk3_sql, fk3_params = _pub7("fkrace-3", [raw7[2]])
    _, fk4_sql, fk4_params = _pub7("fkrace-4", [raw7[3]])
    ins_then_upd = _overlap(fk3_sql, fk3_params,
                            "UPDATE asset SET asset_id=gen_random_uuid() WHERE asset_id=%s",
                            (raw7[2],))
    upd_then_ins = _overlap("UPDATE asset SET asset_id=gen_random_uuid() WHERE asset_id=%s",
                            (raw7[3],),
                            fk4_sql, fk4_params)
    check("#200 publication INSERT vs concurrent asset_id retarget: in BOTH orderings the second "
          "committer is refused",
          (ins_then_upd[0], str(ins_then_upd[1]).startswith("error"),
           upd_then_ins[0], str(upd_then_ins[1]).startswith("error")),
          ("ok", True, "ok", True))
    pk18.execute("""SELECT count(*) AS n FROM publication_raw_asset pra
                    JOIN publication p ON p.publication_intent_id = pra.publication_intent_id
                    WHERE p.slot_id LIKE 'RPUB-%%'
                      AND NOT EXISTS (SELECT 1 FROM asset a WHERE a.asset_id = pra.asset_id)""")
    check("#200 after all races: zero dangling raw-lineage references exist",
          pk18.fetchone()["n"], 0)
    pk18.execute("SELECT count(*) AS n FROM audit_log WHERE entity='publication' "
                 "AND action='publication_denied'")
    denied18 = pk18.fetchone()["n"]
    pk18.execute("SELECT count(*) AS n FROM audit_log WHERE entity='publication' "
                 "AND action IN ('publication_intent_created','publication_recorded')")
    ok18 = pk18.fetchone()["n"]
    check("#200 successes and attributable denials are audited", (ok18 >= 4, denied18 >= 6),
          (True, True))
    lst18 = PUB.list_publications(conn, round_id="RPUB")
    check("#200 list returns derived state + append-only history",
          (len(lst18) >= 3, all("current_state" in r and "events" in r for r in lst18)),
          (True, True))
    pk18.close()
    _pub_cleanup()

    # 19) #265 — CC coverage beyond test_265_reconcile: the IN-FLIGHT job predicate,
    #     generation dominance in stage_state (no start_review / no gate exposure mid-generation),
    #     fail-closed decide/read/commit while generator work remains, genuine concurrency, and
    #     seeded-legacy recovery preserving decision timestamps end-to-end through resolve.
    test_265_reconcile(conn, cfg)
    print("\n19) #265 gate reconciliation — generation dominance, in-flight jobs, concurrency")

    def _wipe265x(kk):
        kk.execute("DELETE FROM audit_log WHERE entity_id LIKE 'R265X%%' OR entity_id LIKE 'R265L%%' "
                   "OR entity_id LIKE 'R265F%%' "
                   "OR entity_id IN (SELECT gate_id::text FROM gate g JOIN gate_target t USING(gate_id) "
                   "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id IN ('R265X','R265L','R265F'))")
        kk.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t "
                   "JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id IN ('R265X','R265L','R265F'))")
        for t265 in ("directive", "slot_review", "slot_approval"):
            kk.execute(f"DELETE FROM {t265} WHERE slot_id IN "
                       "(SELECT slot_id FROM slot WHERE round_id IN ('R265X','R265L','R265F'))")
        kk.execute("DELETE FROM slot WHERE round_id IN ('R265X','R265L','R265F')")
        kk.execute("DELETE FROM script_provenance WHERE job_id IN "
                   "(SELECT job_id FROM generation_job WHERE round_id IN ('R265X','R265L','R265F'))")
        kk.execute("DELETE FROM generation_job WHERE round_id IN ('R265X','R265L','R265F')")
        kk.execute("DELETE FROM round WHERE round_id IN ('R265X','R265L','R265F')")

    k265 = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
    _wipe265x(k265)
    for rid265 in ("R265X", "R265L", "R265F"):
        k265.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                        pillar_distribution,format_distribution,status) VALUES
                        (%s,%s,3,2,'["09:00","20:00"]','{}','{}','planned')""", (rid265, rid265.lower()))
        for i265 in range(1, 7):
            k265.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                            hook_type,status,cycle_no) VALUES (%s,%s,%s,%s,'P1_SELF','1.1','L1',
                            'Painful Truth',%s,1)""",
                         (f"{rid265}-{i265}", rid265, (i265 + 1) // 2,
                          "09:00" if i265 % 2 else "20:00",
                          "TOPIC_PROPOSED" if (rid265 == "R265X" and i265 <= 2) else
                          "SCHEDULE_APPROVED" if rid265 == "R265X" else "TOPIC_PROPOSED"))
    conn.commit()

    # --- generation dominance: partial generation NEVER exposes start_review -------------- #
    ss265 = engine.stage_state(conn, "R265X", "topic_review")
    check("#265 stage stays 'generate' during generation (never start_review)",
          (ss265["state"], ss265["next_action"]), ("generate", "generate"))
    check("#265 no active gate exposed during generation", ss265["gate_id"], None)
    check("#265 truthful counts during generation (review_pending, pending_input)",
          (ss265["review_pending"], ss265["pending_input"]), (2, 4))

    # rows all written but the generation job is STILL IN FLIGHT -> refuse (claimed/in-flight work)
    k265.execute("UPDATE slot SET status='TOPIC_PROPOSED' WHERE round_id='R265X'")
    conn.commit()
    _j265x = _durable_gen_job_265(conn, "R265X")
    try:
        check("#265 start_review REFUSED while a generation job is still in flight",
              _raises(lambda: engine.open_gate(conn, "topic_review", round_id="R265X",
                                               actor="selftest", cfg=cfg)), True)
        ss265b = engine.stage_state(conn, "R265X", "topic_review")
        check("#265 in-flight job keeps the stage at 'generate' (job-poll fallback safe)",
              ss265b["next_action"], "generate")
    finally:
        _drop_gen_job_265(conn, _j265x)

    # generation complete -> the review opens over the complete population; read models agree
    g265 = engine.open_gate(conn, "topic_review", round_id="R265X", actor="selftest", cfg=cfg)
    ss265c = engine.stage_state(conn, "R265X", "topic_review")
    check("#265 stage state and gate targets agree after open",
          (ss265c["in_review"], ss265c["review_pending"], ss265c["gate_id"]),
          (6, 6, str(g265)))

    # --- late eligibility + CONCURRENT reuse converge on ONE reconciled gate -------------- #
    k265.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,
                    hook_type,status,cycle_no) VALUES
                    ('R265X-7','R265X',4,'09:00','P1_SELF','1.2','L1','Painful Truth','TOPIC_PROPOSED',1),
                    ('R265X-8','R265X',4,'20:00','P1_SELF','1.3','L1','Painful Truth','TOPIC_PROPOSED',1)""")
    conn.commit()
    r265 = _race(lambda c: str(engine.open_gate(c, "topic_review", round_id="R265X",
                                                actor="selftest", cfg=cfg)),
                 lambda c: str(engine.open_gate(c, "topic_review", round_id="R265X",
                                                actor="selftest", cfg=cfg)))
    k265.execute("SELECT count(*) AS n FROM gate_target WHERE gate_id=%s", (g265,))
    n265 = k265.fetchone()["n"]
    check("#265 CONCURRENT reuse converges: one gate, one target per eligible slot",
          (r265["a"], r265["b"], n265), (("ok", str(g265)), ("ok", str(g265)), 8))
    k265.execute("SELECT count(*) AS n FROM audit_log WHERE entity='gate' AND entity_id=%s "
                 "AND action='gate_targets_reconciled'", (str(g265),))
    check("#265 concurrent reconciliation audited EXACTLY once (loser is a silent no-op)",
          k265.fetchone()["n"], 1)

    # --- two-connection FIRST-open race: NO pre-existing gate -> ONE canonical gate --------- #
    # (the reuse race above starts from an already-open gate; this proves the first open itself
    #  serializes — the advisory xact lock makes the loser find and reuse the winner's gate)
    rf265 = _race(lambda c: str(engine.open_gate(c, "topic_review", round_id="R265F",
                                                 actor="selftest", cfg=cfg)),
                  lambda c: str(engine.open_gate(c, "topic_review", round_id="R265F",
                                                 actor="selftest", cfg=cfg)))
    k265.execute("""SELECT count(DISTINCT g.gate_id) AS n FROM gate g
                    JOIN gate_target t USING (gate_id) JOIN slot s ON s.slot_id=t.slot_id
                    WHERE s.round_id='R265F' AND g.status='open'""")
    nf265 = k265.fetchone()["n"]
    check("#265 CONCURRENT FIRST-open serializes: both callers converge on ONE canonical gate",
          (rf265["a"][0], rf265["b"][0], rf265["a"][1] == rf265["b"][1], nf265),
          ("ok", "ok", True, 1))
    gf265 = rf265["a"][1]
    k265.execute("SELECT count(*) AS n, count(DISTINCT slot_id) AS d FROM gate_target "
                 "WHERE gate_id=%s", (gf265,))
    tf265 = k265.fetchone()
    check("#265 first-open race: one target per eligible slot (none missing, none duplicated)",
          (tf265["n"], tf265["d"]), (6, 6))
    k265.execute("SELECT count(*) AS n FROM audit_log WHERE entity='gate' AND entity_id=%s "
                 "AND action='gate_opened'", (gf265,))
    check("#265 first-open race: gate creation audited exactly once", k265.fetchone()["n"], 1)

    # --- read-path race: a generation job appears BETWEEN stage_state's snapshot and its ---- #
    #     gate read. Deterministic two-phase stub: the snapshot sees no job, every later probe
    #     (get_gate's guard, the re-snapshot) does. The hold must surface as the truthful
    #     generation-dominant advisory — never escape a READ as an error (was: HTTP 404).
    # #364 — the phased appearance is now simulated on the DURABLE read, since that is what the
    # projection consults. Same scenario, same assertions: absent on the first look, present on the
    # second, i.e. a job that appears between the snapshot and the gate read.
    # Patched at the SHARED base helper, because both consumers route through it: the projection's
    # single-round wrapper AND the gate guard's batched read. Patching only the wrapper would leave
    # the guard reading the real table, and the scenario (a job appearing between the snapshot and
    # the gate read) would never arise.
    _orig_find265 = engine.durable_generation_pending_rounds
    _calls265 = {"n": 0}

    def _phased_find265(cur_, rids_, stage_):
        _calls265["n"] += 1
        if _calls265["n"] == 1:
            return {}
        return {r: "t265race" for r in rids_}

    engine.durable_generation_pending_rounds = _phased_find265
    try:
        ssr265 = engine.stage_state(conn, "R265X", "topic_review")
    finally:
        engine.durable_generation_pending_rounds = _orig_find265
    check("#265 held READ (job appears mid-read) reports the generation hold, not an error",
          (ssr265["state"], ssr265["next_action"], ssr265["gate_id"], ssr265["reconciliation_ok"]),
          ("generate", "generate", None, False))
    check("#265 held READ: operator-visible warning names the held gate",
          any("held until generation completes" in w for w in ssr265["warnings"]), True)

    # --- seeded legacy (direct SQL, the regression fixture) + in-flight work => HELD ------- #
    pol265 = engine.stage_approval_contract(cfg, "topic_review", conn=conn)
    k265.execute("INSERT INTO gate (scope,stage,policy,rule_key,quorum,status) "
                 "VALUES ('batch','topic_review','fixed',%s,%s,'open') RETURNING gate_id",
                 (pol265["rule_key"], str(pol265["quorum"])))
    gl265 = k265.fetchone()["gate_id"]
    k265.execute("INSERT INTO gate_target (gate_id,slot_id) VALUES (%s,'R265L-1'),(%s,'R265L-2')",
                 (gl265, gl265))
    k265.execute("INSERT INTO gate_decision (gate_id,slot_id,approver_id,decision) "
                 "VALUES (%s,'R265L-1','khal','approve')", (gl265,))
    conn.commit()
    k265.execute("SELECT decided_at FROM gate_decision WHERE gate_id=%s AND slot_id='R265L-1'",
                 (gl265,))
    prior_at265 = k265.fetchone()["decided_at"]

    _j265l = _durable_gen_job_265(conn, "R265L")
    try:
        ssl0 = engine.stage_state(conn, "R265L", "topic_review")
        check("#265 held: in-flight work hides even a legacy open gate (state stays generate)",
              (ssl0["next_action"], ssl0["gate_id"]), ("generate", None))
        check("#265 held: operator-visible warning names the held gate condition",
              any("held until generation completes" in w for w in ssl0["warnings"]), True)
        check("#265 held: decisions fail closed while generator work remains",
              _raises(lambda: engine.decide(conn, gl265, "khal", "approve",
                                            slot_ids=["R265L-2"], cfg=cfg)), True)
        check("#265 held: gate reads fail closed while generator work remains",
              _raises(lambda: engine.get_gate(conn, gl265)), True)
        check("#265 held: batch commit fails closed while generator work remains",
              _raises(lambda: engine.resolve(conn, gl265, actor="selftest", cfg=cfg)), True)
    finally:
        _drop_gen_job_265(conn, _j265l)

    # --- generation complete -> bounded reconciliation heals the legacy gate on read ------- #
    ssl265 = engine.stage_state(conn, "R265L", "topic_review")
    check("#265 legacy gate reconciles on read: stage, gate, and eligible population agree",
          (ssl265["in_review"], ssl265["review_pending"], ssl265["gate_id"]),
          (6, 6, str(gl265)))
    k265.execute("SELECT detail FROM audit_log WHERE entity='gate' AND entity_id=%s "
                 "AND action='gate_targets_reconciled'", (str(gl265),))
    rec265 = k265.fetchall()
    check("#265 reconciliation audited with counts (prior, added, resulting)",
          (len(rec265),
           rec265[0]["detail"].get("prior_count") if rec265 else None,
           rec265[0]["detail"].get("added_count") if rec265 else None,
           rec265[0]["detail"].get("resulting_count") if rec265 else None,
           rec265[0]["detail"].get("added") if rec265 else None),
          (1, 2, 4, 6, ["R265L-3", "R265L-4", "R265L-5", "R265L-6"]))
    engine.stage_state(conn, "R265L", "topic_review")     # idempotent second pass
    k265.execute("SELECT count(*) AS n FROM audit_log WHERE entity='gate' AND entity_id=%s "
                 "AND action='gate_targets_reconciled'", (str(gl265),))
    check("#265 idempotent no-op reconciliation emits NO second audit event",
          k265.fetchone()["n"], 1)
    k265.execute("SELECT decision, decided_at FROM gate_decision WHERE gate_id=%s "
                 "AND slot_id='R265L-1'", (gl265,))
    d265 = k265.fetchall()
    check("#265 prior decision untouched by reconciliation (no duplicate, no alteration)",
          (len(d265), d265[0]["decision"], d265[0]["decided_at"] == prior_at265),
          (1, "approve", True))

    # decide the reconciled remainder + resolve -> the WHOLE population advances (no partial commit)
    engine.decide(conn, gl265, "khal", "approve",
                  slot_ids=["R265L-2", "R265L-3", "R265L-4", "R265L-5", "R265L-6"], cfg=cfg)
    out265 = engine.resolve(conn, gl265, actor="selftest", cfg=cfg)
    check("#265 resolve advances the COMPLETE reconciled population",
          (len(out265), set(out265.values())), (6, {"approved"}))

    _wipe265x(k265)
    conn.commit()
    k265.close()

    # 20) #276 — versioned baseline eligibility policy + immutable round snapshot (D1).
    print("\n20) #276 baseline eligibility policy — selection, snapshot immutability, supersession")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "planner"))
    import plan_round as _P276  # noqa: E402
    cfg276 = engine.load_config()
    k276 = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)

    def _rej276(fn):
        try:
            fn(); return False
        except (ValueError, engine.GateError):
            return True

    def _db_rejects276(sql, params=None):
        # a DB-constraint/trigger rejection (unique index, immutability trigger) aborts the tx —
        # roll back either way so the next query runs on a clean transaction.
        try:
            k276.execute(sql, params or ()); conn.rollback(); return False
        except engine.psycopg2.Error:
            conn.rollback(); return True

    def _wipe276():
        k276.execute("DELETE FROM round_policy_snapshot WHERE round_id LIKE 'R276%%'")
        k276.execute("DELETE FROM slot WHERE round_id LIKE 'R276%%'")
        k276.execute("DELETE FROM audit_log WHERE entity_id LIKE 'R276%%'")
        k276.execute("DELETE FROM script_provenance WHERE job_id IN "
                     "(SELECT job_id FROM generation_job WHERE round_id LIKE 'R276%%')")
        k276.execute("DELETE FROM generation_job WHERE round_id LIKE 'R276%%'")
        k276.execute("DELETE FROM round WHERE round_id LIKE 'R276%%'")
        k276.execute("DELETE FROM round_policy_snapshot rs USING round r "
                     "WHERE rs.round_id=r.round_id AND r.label LIKE 'T276%%'")
        k276.execute("DELETE FROM slot s USING round r WHERE s.round_id=r.round_id AND r.label LIKE 'T276%%'")
        k276.execute("DELETE FROM script_provenance WHERE job_id IN "
                     "(SELECT job_id FROM generation_job WHERE round_id IN "
                     "(SELECT round_id FROM round WHERE label LIKE 'T276%%'))")
        k276.execute("DELETE FROM generation_job WHERE round_id IN "
                     "(SELECT round_id FROM round WHERE label LIKE 'T276%%')")
        k276.execute("DELETE FROM round WHERE label LIKE 'T276%%'")
        # the section deletes ALL baseline policies (to exercise zero-current); drop any snapshot that
        # still references one first, so a leftover run (e.g. an e2e fixture) can't FK-block the wipe.
        k276.execute("DELETE FROM round_policy_snapshot WHERE baseline_policy_id IS NOT NULL")
        k276.execute("DELETE FROM baseline_eligibility_policy")
        conn.commit()
    _wipe276()

    # zero-current fails closed (no policy seeded)
    check("#276 zero current baseline policy fails closed",
          _rej276(lambda: engine.current_baseline_policy(k276)), True)

    # create-only seed of generation 1, idempotent + non-destructive
    p1 = engine.ensure_baseline_policy(conn, actor="loader")
    p1b = engine.ensure_baseline_policy(conn, actor="loader")
    check("#276 generation 1 is created create-only and re-seed is an idempotent no-op",
          (p1["generation"], p1b["policy_id"] == p1["policy_id"]), (1, True))

    # the DB enforces exactly one current per scope — a second 'current' insert fails (multiple-current guard)
    check("#276 a second current generation is structurally rejected (one-current invariant)",
          _db_rejects276(
              "INSERT INTO baseline_eligibility_policy (scope,generation,status,eligible_version_ids) "
              "VALUES ('default',999,'current','[]'::jsonb)"), True)

    elig276 = engine.resolve_run_eligibility(k276)
    en276 = [e["name"] for e in elig276["eligible"]]
    check("#276 eligibility resolves from the baseline policy (>=1 framework, version-pinned)",
          len(en276) >= 1 and all(e["version_id"] for e in elig276["eligible"]), True)

    # plan a run against the policy + explicit mix -> pins an immutable snapshot
    N276 = 3 * 2
    mix276 = {en276[0]: N276}
    for n in en276[1:]:
        mix276[n] = 0
    r276 = _P276.plan_round_api(cfg276, 3, 2, label="T276-plan", format_mix=mix276)
    snap = engine.round_snapshot(conn, r276["round_id"])
    check("#276 planning pins an immutable snapshot (policy gen + selected versions + exact mix)",
          (snap is not None, snap["baseline_generation"], snap["format_mix"].get(en276[0]),
           snap["selected_version_ids"].get(en276[0]) == elig276["eligible"][0]["version_id"]),
          (True, 1, N276, True))
    check("#276 snapshot records authoritative methodology + workflow versions",
          (snap["methodology_version"] is not None, snap["workflow_version"] is not None), (True, True))

    # invalid eligibility rejected (a framework outside the resolved set)
    check("#276 a format_mix framework outside the baseline eligibility set is rejected",
          _rej276(lambda: _P276.plan_round_api(cfg276, 1, 2, label="T276-bad",
                    format_mix={"Not An Eligible Framework": 2})), True)

    # attempted post-planning snapshot mutation is blocked (append-only evidence)
    check("#276 post-planning snapshot mutation is blocked (append-only)",
          _db_rejects276("UPDATE round_policy_snapshot SET format_mix='{}'::jsonb WHERE round_id=%s",
                         (r276["round_id"],)), True)

    # deterministic supersession: new generation supersedes prior current; prior + pinned run unchanged
    subset = [e["version_id"] for e in elig276["eligible"][:max(1, len(en276) - 1)]]
    p2 = engine.supersede_baseline_policy(conn, subset, actor="khal")
    k276.execute("SELECT generation,status FROM baseline_eligibility_policy ORDER BY generation")
    gens = [(g["generation"], g["status"]) for g in k276.fetchall()]
    k276.execute("SELECT count(*) AS n FROM baseline_eligibility_policy WHERE status='current'")
    check("#276 supersession is deterministic: prior superseded, exactly one new current",
          (p2["generation"], gens, k276.fetchone()["n"]), (2, [(1, "superseded"), (2, "current")], 1))

    # reads after a baseline-policy change resolve from the STORED snapshot, not the latest policy
    snap_after = engine.round_snapshot(conn, r276["round_id"])
    check("#276 a pinned run reads from its stored snapshot after a later policy change (not reinterpreted)",
          (snap_after["baseline_generation"], snap_after["format_mix"] == snap["format_mix"],
           snap_after["selected_version_ids"] == snap["selected_version_ids"]),
          (1, True, True))
    # a NEW run now resolves from generation 2 (the current)
    elig_after = engine.resolve_run_eligibility(k276)
    check("#276 a new run resolves from the current (superseded-to) generation",
          elig_after["policy"]["generation"], 2)

    # #276 P1a — a no-format_mix new-run request is REJECTED (never allocated from weekly_count/default)
    check("#276 a no-format_mix new-run request is rejected (no weekly/default fallback)",
          _rej276(lambda: _P276.plan_round_api(cfg276, 2, 2, label="T276-nomix")), True)

    # #276 P1b — the governed baseline selection excludes legacy_carry_forward (Pic + Caption) and is
    # UNAFFECTED by a later catalogue lifecycle change (archiving a governed format's catalogue row does
    # not change what the policy resolves — eligibility is pinned to version IDs, not content_format.active)
    check("#276 governed baseline selection excludes the legacy_carry_forward format (Pic + Caption)",
          all(e["name"] != "Pic + Caption" for e in engine.resolve_run_eligibility(k276)["eligible"]), True)
    before276 = sorted(e["name"] for e in engine.resolve_run_eligibility(k276)["eligible"])
    probe_fkey = elig_after["eligible"][0]["format_key"]
    k276.execute("UPDATE content_format SET active=false, lifecycle_status='archived', archived_at=now() "
                 "WHERE format_key=%s", (probe_fkey,))
    conn.commit()
    after276 = sorted(e["name"] for e in engine.resolve_run_eligibility(k276)["eligible"])
    k276.execute("UPDATE content_format SET active=true, lifecycle_status='active', archived_at=NULL "
                 "WHERE format_key=%s", (probe_fkey,))
    conn.commit()
    check("#276 baseline eligibility is unaffected by a later catalogue lifecycle change",
          after276 == before276 and len(after276) >= 1, True)

    # #276 (P1 follow-up) — if version reminting leaves the current policy referencing an unresolvable
    # version, run-eligibility FAILS CLOSED (hard-stop), never approximates. Supersession never deletes
    # a prior generation, and a content-format reset must not touch policy generations (proven in
    # api_selftest); here we prove the hard-stop deterministically via a governed generation pinning a
    # version id that does not resolve.
    ngen_before = None
    k276.execute("SELECT count(*) AS n FROM baseline_eligibility_policy")
    ngen_before = k276.fetchone()["n"]
    engine.supersede_baseline_policy(conn, [elig_after["eligible"][0]["version_id"],
                                            "00000000-0000-0000-0000-000000000000"], actor="khal")
    check("#276 run-eligibility fails closed when the current policy references an unresolvable version",
          _rej276(lambda: engine.resolve_run_eligibility(k276)), True)
    k276.execute("SELECT count(*) AS n FROM baseline_eligibility_policy")
    check("#276 superseding never deletes a prior generation (append-only generation history)",
          k276.fetchone()["n"] == ngen_before + 1, True)

    _wipe276()
    k276.close()

    # 21) #271 (on D1) — calendar-continuity run read model + governed single-slot schedule revision.
        # #292 — revise_schedule_slot now REQUIRES the caller's expected combined schedule token (no
    # legacy bypass: a revision without it could silently overwrite a concurrently accepted mapping).
    # This #271 fixture round is created THROUGH THE PLANNER, and the planner now gives every NEW
    # round mapping generation 1 inside its own transaction (governed from birth), so the round is no
    # longer "legacy by absence" and its token is not 0. Hard-coding 0 would fail every revision on a
    # stale-token conflict before it reached the behaviour under test. Read the CURRENT token so
    # these checks keep exercising the revision path itself, whichever generation the fixture is on.
    def _rev271(*a, **k):
        if "expected_token" not in k:
            c = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)
            c.execute("SELECT round_id FROM slot WHERE slot_id=%s", (a[1],))
            c_rid = c.fetchone()["round_id"]
            k["expected_token"] = engine.schedule_token(c, c_rid)
            c.close()
        return engine.revise_schedule_slot(*a, **k)

    print("\n21) #271 calendar continuity + governed schedule revision (on the D1 seam)")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "planner"))
    import plan_round as _P271  # noqa: E402
    cfg271 = engine.load_config()
    k271 = conn.cursor(cursor_factory=engine.psycopg2.extras.RealDictCursor)

    def _rej271(fn):
        try:
            fn(); return False
        except (ValueError, engine.GateError):
            return True

    def _wipe271():
        k271.execute("DELETE FROM round_policy_snapshot rs USING round r "
                     "WHERE rs.round_id=r.round_id AND r.label LIKE 'T271D1%%'")
        k271.execute("DELETE FROM slot s USING round r WHERE s.round_id=r.round_id AND r.label LIKE 'T271D1%%'")
        k271.execute("DELETE FROM audit_log WHERE entity_id IN (SELECT round_id FROM round WHERE label LIKE 'T271D1%%')")
        k271.execute("DELETE FROM script_provenance WHERE job_id IN "
                     "(SELECT job_id FROM generation_job WHERE round_id IN "
                     "(SELECT round_id FROM round WHERE label LIKE 'T271D1%%'))")
        k271.execute("DELETE FROM generation_job WHERE round_id IN "
                     "(SELECT round_id FROM round WHERE label LIKE 'T271D1%%')")
        k271.execute("DELETE FROM round WHERE label LIKE 'T271D1%%'")
        conn.commit()
    _wipe271()

    engine.ensure_baseline_policy(conn)   # §20 wiped the policy; re-seed the governed baseline (create-only)
    en271 = [e["name"] for e in engine.resolve_run_eligibility(k271)["eligible"]]
    N271 = 2 * 2
    mix271 = {en271[0]: 2, **({en271[1]: 2} if len(en271) > 1 else {en271[0]: 4})}
    for n in en271:
        mix271.setdefault(n, 0)
    a271 = _P271.plan_round_api(cfg271, 2, 2, label="T271D1-a", format_mix=mix271)
    rid271 = a271["round_id"]

    det = engine.round_detail(conn, rid271)
    check("#271 round read model exposes ALL planned cells + truthful per-status counts (calendar continuity)",
          (det["planned_total"], sum(det["status_counts"].values()), len(det["slots"]),
           det["policy_snapshot"]["baseline_generation"] is not None),
          (N271, N271, N271, True))
    # #308 — round_detail must RETURN starts_on (it already SELECTed it): the selected-run calendar
    # views project slots over the window and pick the adaptive view from it. Present as a key
    # (None for an unplaced run), never omitted — omission read as null and every placed run showed
    # as unplaced.
    check("#308 round_detail returns the starts_on key (present, even if unplaced)",
          "starts_on" in det, True)
    # calendar continuity through Schedule approval: mark half the slots approved; the read model still
    # returns every planned cell with its lifecycle status (not the active-review subset).
    k271.execute("SELECT slot_id FROM slot WHERE round_id=%s ORDER BY day, time_uae, slot_id", (rid271,))
    sids271 = [r["slot_id"] for r in k271.fetchall()]
    k271.execute("UPDATE slot SET status='SCHEDULE_APPROVED' WHERE slot_id = ANY(%s)", (sids271[:2],))
    conn.commit()
    det2 = engine.round_detail(conn, rid271)
    check("#271 calendar continuity holds after Schedule approval (all cells retained, lifecycle truthful)",
          (det2["planned_total"], det2["status_counts"].get("SCHEDULE_APPROVED"),
           det2["status_counts"].get("RESERVED")), (N271, 2, 2))

    # governed single-slot schedule revision — existing reviewer authority only, pinned-policy format limit
    check("#271 unauthorized actor cannot revise a slot schedule",
          _rej271(lambda: _rev271(conn, sids271[0], {"day": 2}, actor="intruder", cfg=cfg271)), True)
    # delta-based audit assertion (slot IDs recycle across runs, so prior schedule_revised rows persist)
    k271.execute("SELECT count(*) AS n FROM audit_log WHERE entity='slot' AND entity_id=%s AND action='schedule_revised'", (sids271[0],))
    _audit_before = k271.fetchone()["n"]
    rev = _rev271(conn, sids271[0], {"day": 2, "topic_guidance": "reframe",
                                                         **({"format": en271[1]} if len(en271) > 1 else {})},
                                      actor="khal", cfg=cfg271)
    k271.execute("SELECT status, day, topic_angle FROM slot WHERE slot_id=%s", (sids271[0],))
    after = k271.fetchone()
    check("#271 governed revision returns ONLY that slot to Schedule review, canonical id + fields kept",
          (rev["status"], after["status"], after["day"], after["topic_angle"]),
          ("RESERVED", "RESERVED", 2, "reframe"))
    k271.execute("SELECT count(*) AS n FROM audit_log WHERE entity='slot' AND entity_id=%s AND action='schedule_revised'", (sids271[0],))
    check("#271 the revision is audited exactly once (append-only lineage preserved)",
          k271.fetchone()["n"] - _audit_before, 1)
    check("#271 a slot format revision is limited to the run's PINNED D1 policy (excludes non-eligible)",
          _rej271(lambda: _rev271(conn, sids271[1], {"format": "Pic + Caption"},
                                                      actor="khal", cfg=cfg271)), True)

    # #278 P1 — the read model exposes the FULL pinned eligibility set (not just the allocated formats),
    # so an operator can revise a slot to a pinned-eligible framework whose original count was zero.
    pinned_names = {e["name"] for e in det2["pinned_eligible_formats"]}
    check("#278 P1 round read model exposes the FULL pinned eligibility set with framework_id (all governed)",
          (pinned_names == set(en271), len(en271) >= 3,
           all("framework_id" in e for e in det2["pinned_eligible_formats"])),
          (True, True, True))
    mixmap = det2.get("format_mix") or {}
    zero_pinned = [n for n in pinned_names if int(mixmap.get(n, 0)) == 0]
    check("#278 P1 a pinned-eligible framework allocated zero in the mix is still offered (present in set)",
          (len(zero_pinned) >= 1, set(zero_pinned).issubset(pinned_names)), (True, True))
    # and the server ACCEPTS a governed single-slot revision to that zero-count pinned framework.
    zt271 = zero_pinned[0]
    rev_zero = _rev271(conn, sids271[2], {"format": zt271}, actor="khal", cfg=cfg271)
    k271.execute("SELECT format, status FROM slot WHERE slot_id=%s", (sids271[2],))
    _rz = k271.fetchone()
    check("#278 P1 a zero-count pinned-eligible framework is a VALID single-slot revision target",
          (rev_zero["status"], _rz["format"], _rz["status"]), ("RESERVED", zt271, "RESERVED"))

    # #278 P1 — a day revision must keep the slot ON the configured calendar (1..period_len_days). An
    # out-of-period day is a governed rejection; every canonical slot stays represented (continuity). The
    # run's period_len_days is 2, so day 999 is out of range while the valid in-period revision above held.
    check("#278 P1 a day revision beyond the run's configured period is rejected (calendar continuity)",
          _rej271(lambda: _rev271(conn, sids271[3], {"day": 999}, actor="khal", cfg=cfg271)), True)
    det3 = engine.round_detail(conn, rid271)
    check("#278 P1 the rejected out-of-period revision left EVERY canonical slot on the calendar (1..period)",
          (det3["planned_total"], len(det3["slots"]),
           all(1 <= s["day"] <= det["period_len_days"] for s in det3["slots"])),
          (N271, N271, True))

    # pre-approval run-mix reconcile + no-remap fail-closed after a slot commits
    _wipe271()
    b271 = _P271.plan_round_api(cfg271, 2, 2, label="T271D1-b", format_mix=mix271)["round_id"]
    if len(en271) > 1:
        newmix = {en271[0]: 1, en271[1]: 3, **({en271[2]: 0} if len(en271) > 2 else {})}
        mr = engine.revise_run_mix(conn, b271, newmix, actor="khal", cfg=cfg271)
        k271.execute("SELECT format, count(*) AS n FROM slot WHERE round_id=%s GROUP BY format", (b271,))
        got = {r["format"]: r["n"] for r in k271.fetchall()}
        check("#271 pre-approval run-mix reconciles all uncommitted slots to the exact new counts",
              (mr["reconciled_slots"], got.get(en271[1])), (N271, 3))
    k271.execute("SELECT slot_id FROM slot WHERE round_id=%s LIMIT 1", (b271,))
    k271.execute("UPDATE slot SET status='SCHEDULE_APPROVED' WHERE slot_id=(SELECT slot_id FROM slot WHERE round_id=%s LIMIT 1)", (b271,))
    conn.commit()
    check("#271 run-mix is fail-closed once any slot is committed (downstream never remapped)",
          _rej271(lambda: engine.revise_run_mix(conn, b271, {en271[0]: N271}, actor="khal", cfg=cfg271)), True)

    # #278 P1 — an INVALID pinned policy must fail closed, NEVER fall back to the current policy. Plan a
    # run (it carries a snapshot), then re-pin it (DELETE+INSERT — the snapshot is UPDATE-immutable) to a
    # real-but-invalid policy generation whose version ids no longer resolve (e.g. reminted). A revision
    # to a CURRENTLY-eligible framework must still be REJECTED (proving no current-policy fallback), while
    # the read model degrades gracefully to an empty pinned set (calendar continuity is preserved).
    _wipe271()
    c271 = _P271.plan_round_api(cfg271, 2, 2, label="T271D1-c", format_mix=mix271)["round_id"]
    k271.execute("SELECT slot_id FROM slot WHERE round_id=%s ORDER BY day, time_uae, slot_id LIMIT 1", (c271,))
    csid = k271.fetchone()["slot_id"]
    k271.execute("""INSERT INTO baseline_eligibility_policy
                      (scope, generation, status, eligible_version_ids, created_by, tenant_id, module)
                    VALUES ('t271d1c-invalid', 9999, 'superseded', %s, 'selftest', 'default', 'content')
                    RETURNING policy_id::text AS pid""",
                 (engine.psycopg2.extras.Json(["00000000-0000-0000-0000-000000000000"]),))
    bad_pid = k271.fetchone()["pid"]
    k271.execute("SELECT baseline_generation, selected_version_ids, format_mix, methodology_version, "
                 "workflow_version FROM round_policy_snapshot WHERE round_id=%s", (c271,))
    _snap = k271.fetchone()
    k271.execute("DELETE FROM round_policy_snapshot WHERE round_id=%s", (c271,))
    k271.execute("""INSERT INTO round_policy_snapshot
                      (round_id, baseline_policy_id, baseline_generation, selected_version_ids, format_mix,
                       methodology_version, workflow_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                 (c271, bad_pid, _snap["baseline_generation"],
                  engine.psycopg2.extras.Json(_snap["selected_version_ids"]),
                  engine.psycopg2.extras.Json(_snap["format_mix"]),
                  _snap["methodology_version"], _snap["workflow_version"]))
    conn.commit()
    check("#278 P1 an invalid pinned policy fails closed — a revision to a CURRENTLY-eligible framework "
          "is still rejected (no silent fallback to the current policy)",
          _rej271(lambda: _rev271(conn, csid, {"format": en271[0]},
                                                      actor="khal", cfg=cfg271)), True)
    check("#278 P1 the read model degrades gracefully (empty pinned set) while continuity holds",
          (engine.round_detail(conn, c271)["pinned_eligible_formats"],
           engine.round_detail(conn, c271)["planned_total"]), ([], N271))
    k271.execute("DELETE FROM round_policy_snapshot WHERE round_id=%s", (c271,))
    k271.execute("DELETE FROM baseline_eligibility_policy WHERE policy_id=%s", (bad_pid,))
    conn.commit()

    _wipe271()
    k271.close()

    teardown(conn)
    print(f"\ncleaned up: {status_counts(conn)}")
    conn.close()
    print(f"\n{'='*60}\n{'ALL CHECKS PASSED' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}\n{'='*60}")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
