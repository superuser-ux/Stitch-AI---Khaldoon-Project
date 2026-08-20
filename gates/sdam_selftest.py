#!/usr/bin/env python3
"""#244 SDAM adapter self-test — DB invariants + read-only adapter logic (deterministic).

Local synthetic UUID fixtures prove the real binding/observation invariants; a FAKE ResourceSpace
client exercises the adapter classification. (The live read-only proof against retained resource 6 is
a separate script — it proves transport/pagination/byte-exact/pending-active/redaction only, never a
real canonical UUID binding, since resource 6 field-99 is a token, not a UUID.)
"""
import sys, threading, time, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))
import engine
import sdam

FAILS = []
def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")
    if not ok: FAILS.append(label)

def raises(fn, needle=None):
    try:
        fn(); return False
    except Exception as e:
        return (needle is None) or (needle.lower() in str(e).lower())


class FakeRS(sdam.RSClient):
    """Fake ResourceSpace that subclasses RSClient so the REAL complete-scan / tuple-double-scan /
    resolve_unique / observe_readiness logic runs against an in-memory resource store."""
    def __init__(self, resources=None, page_size=2, safety_cap=100000, raise_exc=None,
                 mutate=None, bad_order=False):
        self.resources = dict(resources or {})   # {ref: {"archive":.., "resource_type":.., "field99":..}}
        self.page_size, self.safety_cap = page_size, safety_cap
        self._raise, self._mutate, self._bad_order, self._scans = raise_exc, mutate, bad_order, 0
    def _rif(self):
        if self._raise: raise self._raise
    def get_resource_data(self, ref):
        self._rif()
        r = self.resources.get(ref)
        return {"ref": ref, **r} if r else None
    def field99(self, ref):
        self._rif()
        if ref not in self.resources: raise sdam.SdamMalformed("no such ref")
        return self.resources[ref]["field99"]
    def get_resource_path(self, ref):
        return f"http://priv:8088/pages/download.php?ref={ref}&access_key=SECRET"
    def _search_page(self, token, offset):
        self._rif()
        # RS-like normalized/partial index (case-insensitive substring); verify-on-read filters exact.
        refs = sorted(r for r, v in self.resources.items() if token.lower() in str(v["field99"]).lower())
        if self._bad_order: refs = list(reversed(refs))    # -> completeness guard trips
        return refs[offset:offset + self.page_size]
    def _after_scan(self):
        self._scans += 1
        if self._mutate and self._scans == 1:              # mutate BETWEEN the two complete scans
            self._mutate(self.resources)


class WriteFakeRS(FakeRS):
    """#259 S2 — write-capable in-memory RS: create_resource / update_field (F99 field99,
    F100 field100) + field_value read-back, with per-op call counters and an injectable failure
    point so the phase-audited recovery paths run against the REAL adapter."""
    def __init__(self, resources=None, fail_after=None):
        # keys are INT (the readiness/resolve_unique path looks up by int(external_ref))
        super().__init__({int(k): v for k, v in (resources or {}).items()})
        self._next_ref = (max(list(self.resources) + [5]) + 1)
        self.calls = {"create": 0, "update": 0}
        self.fail_after = fail_after          # e.g. ("create", 1) -> raise on the Nth create
    def _maybe_fail(self, op):
        if self.fail_after and self.fail_after[0] == op and self.calls[op] >= self.fail_after[1]:
            raise sdam.SdamUnavailable(f"injected {op} failure")
    def create_resource(self, resource_type=sdam.VIDEO_RESOURCE_TYPE, archive=sdam.PENDING_ARCHIVE):
        self.calls["create"] += 1
        self._maybe_fail("create")
        ref = self._next_ref; self._next_ref += 1
        self.resources[ref] = {"archive": archive, "resource_type": resource_type,
                               "field99": None, "field100": None}
        return str(ref)
    def update_field(self, ref, field, value):
        self.calls["update"] += 1
        self._maybe_fail("update")
        r = self.resources.get(int(ref))
        if not r:
            return False
        r["field99" if int(field) == 99 else "field100"] = value
        return True
    def field_value(self, ref, field_ref):
        r = self.resources.get(int(ref))
        return r.get("field99" if int(field_ref) == 99 else "field100") if r else None
    def field99(self, ref):
        return self.field_value(ref, 99)


# convenience: an active video resource carrying the given field-99 value
def _res(field99, archive=0, rtype=3):
    return {"archive": archive, "resource_type": rtype, "field99": field99}


RID, SLOT, SLOT2 = "RSDAM244", "RSDAM244-1", "RSDAM244-2"

def seed(conn):
    cur = conn.cursor()
    cur.execute("SET session_replication_role = replica")   # bypass append-only/immutable guards for residual cleanup
    cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN "
                "(SELECT binding_id FROM sdam_asset_binding WHERE slot_id IN (%s,%s))", (SLOT, SLOT2))
    cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id IN (%s,%s)", (SLOT, SLOT2))
    cur.execute("SET session_replication_role = DEFAULT")
    cur.execute("DELETE FROM slot_approval WHERE slot_id IN (%s,%s)", (SLOT, SLOT2))
    cur.execute("DELETE FROM audit_log WHERE entity_id IN (%s,%s) AND entity IN ('slot','sdam_registration')", (SLOT, SLOT2))
    cur.execute("DELETE FROM asset WHERE slot_id IN (%s,%s)", (SLOT, SLOT2))
    cur.execute("DELETE FROM slot WHERE slot_id IN (%s,%s)", (SLOT, SLOT2))
    cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    cur.execute("INSERT INTO round (round_id, period_len_days, posts_per_day, post_times, "
                "pillar_distribution, format_distribution) VALUES (%s,1,1,'[]','{}','{}') ON CONFLICT DO NOTHING", (RID,))
    for s in (SLOT, SLOT2):
        cur.execute("INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, hcs_id, lens, hook_type, cycle_no) "
                    "VALUES (%s,%s,1,'09:00','P1_SELF','1.1','L1','Painful Truth',1)", (s, RID))
    aid = str(uuid.uuid4())
    cur.execute("INSERT INTO asset (asset_id, slot_id, stage, kind, version) VALUES (%s,%s,'production','raw_cut',1)",
                (aid, SLOT))
    conn.commit()
    return aid

def cleanup(conn):
    cur = conn.cursor()
    # append-only / immutability triggers block DELETE by design; bypass them transiently for THIS
    # test's isolated fixtures only (their enforcement is proven in the checks above).
    cur.execute("SET session_replication_role = replica")
    cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN "
                "(SELECT binding_id FROM sdam_asset_binding WHERE slot_id IN (%s,%s))", (SLOT, SLOT2))
    cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id IN (%s,%s)", (SLOT, SLOT2))
    cur.execute("DELETE FROM sdam_freshness_policy WHERE policy_version=999")   # test-only governance row
    cur.execute("SET session_replication_role = DEFAULT")
    cur.execute("DELETE FROM slot_approval WHERE slot_id IN (%s,%s)", (SLOT, SLOT2))
    cur.execute("DELETE FROM audit_log WHERE entity_id IN (%s,%s) AND entity IN ('slot','sdam_registration')", (SLOT, SLOT2))
    cur.execute("DELETE FROM asset WHERE slot_id IN (%s,%s)", (SLOT, SLOT2))
    cur.execute("DELETE FROM slot WHERE slot_id IN (%s,%s)", (SLOT, SLOT2))
    cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
    conn.commit()

def sp(conn, fn):
    """run fn in a savepoint; return True if it raised (and roll back to keep the conn usable)."""
    cur = conn.cursor()
    cur.execute("SAVEPOINT s1")
    try:
        fn(); cur.execute("RELEASE SAVEPOINT s1"); return False
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT s1"); return True


def main():
    conn = engine.db_connect()
    aid = seed(conn)
    print(f"seeded asset {aid} slot {SLOT}")

    # 1) valid binding via the repo (external_ref shape validated in the adapter)
    bid = sdam.create_binding(conn, aid, 1, SLOT, "6", "tester"); conn.commit()
    check("binding created", isinstance(bid, (str, uuid.UUID)) or bid is not None, True)

    # 2) dual-ID composite FK rejects slot drift (asset A/v1 with unrelated slot)
    check("composite FK rejects slot drift",
          sp(conn, lambda: sdam.create_binding(conn, aid, 1, SLOT2, "61", "x")), True)
    conn.rollback()

    # 3) cardinality: same (provider_key, external_ref) rejected; same (asset,ver,provider) rejected
    check("(provider,external_ref) uniqueness",
          sp(conn, lambda: sdam.create_binding(conn, aid, 1, SLOT, "6", "x")), True)
    check("(asset,version,provider) uniqueness",
          sp(conn, lambda: sdam.create_binding(conn, aid, 1, SLOT, "7", "x")), True)
    conn.rollback()

    # 4) adapter rejects a bad ResourceSpace external_ref shape (adapter-owned, not DB)
    check("adapter rejects leading-zero extref",
          raises(lambda: sdam.create_binding(conn, aid, 1, SLOT, "007", "x")), True)
    conn.rollback()

    # 5) binding immutability
    check("binding no-update", sp(conn, lambda: conn.cursor().execute(
        "UPDATE sdam_asset_binding SET created_by='y' WHERE binding_id=%s", (bid,))), True)
    check("binding no-delete", sp(conn, lambda: conn.cursor().execute(
        "DELETE FROM sdam_asset_binding WHERE binding_id=%s", (bid,))), True)
    conn.rollback()

    # 6) direct observation insert denied (trial guard)
    check("direct observation insert denied", sp(conn, lambda: conn.cursor().execute(
        """INSERT INTO sdam_readiness_observation
             (binding_id,observation_seq,observation_key,result_code,evidence_source,actor_type,actor_id,
              policy_version,retry_class,observed_at,expires_at,created_at)
           VALUES (%s,1,'k','not_ready_pending','resourcespace','system','a',1,'retry_pending',now(),now()+interval '1s',now())""",
        (bid,))), True)
    conn.rollback()

    # 7) append via controlled function: observed_at DB-forced; expires_at = observed + policy ttl (900s)
    oid = sdam.append_observation(conn, bid, "k1", "not_ready_pending", "system", "a"); conn.commit()
    cur = conn.cursor()
    cur.execute("SELECT observed_at, expires_at, extract(epoch from (expires_at-observed_at))::int, observation_seq "
                "FROM sdam_readiness_observation WHERE observation_id=%s", (oid,))
    _oa, _ea, ttl, seq = cur.fetchone()
    check("expires_at = observed_at + policy ttl (900s)", ttl, 900)
    check("first observation_seq is 1", seq, 1)

    # 8) idempotency: same key + same payload converges; same key + different payload raises
    oid_same = sdam.append_observation(conn, bid, "k1", "not_ready_pending", "system", "a"); conn.commit()
    check("same key + same payload converges to one row", str(oid_same), str(oid))
    check("same key + different payload raises conflict",
          sp(conn, lambda: sdam.append_observation(conn, bid, "k1", "unavailable", "system", "a")), True)
    conn.rollback()

    # 9) monotonic seq; newest-by-seq current state
    sdam.append_observation(conn, bid, "k2", "unavailable", "system", "a"); conn.commit()
    st = sdam.current_state(conn, bid)
    check("current_state newest by seq (seq=2, unavailable)", (st["observation_seq"], st["observed_result"]), (2, "unavailable"))
    check("current_state effective (fresh, not stale)", st["effective_state"], "unavailable")

    # 10) DB CHECK matrix enforced through the function: ready requires equal digests
    good = "a"*64
    check("ready with equal digests accepted", (lambda: (sdam.append_observation(
        conn, bid, "kready", "ready", "system", "a", expected_digest=good, observed_digest=good) and False) or True)(), True)
    conn.commit()
    check("ready with UNEQUAL digests rejected (DB CHECK)",
          sp(conn, lambda: conn.cursor().execute("SELECT sdam_append_observation(%s,'kbad','ready','sha256',1,%s,%s,NULL,1,'system','a','refresh_ttl')",
                                                  (bid, good, "b"*64))), True)
    conn.rollback()
    check("lineage_mismatch WITHOUT mismatch_code rejected (DB CHECK)",
          sp(conn, lambda: conn.cursor().execute("SELECT sdam_append_observation(%s,'kbad2','not_ready_lineage_mismatch','sha256',1,%s,%s,NULL,1,'system','a','no_retry')",
                                                  (bid, good, "c"*64))), True)
    conn.rollback()

    # 11) observation FK: absent binding -> function raises
    check("append for absent binding raises",
          sp(conn, lambda: sdam.append_observation(conn, str(uuid.uuid4()), "k", "not_ready_pending", "system", "a")), True)
    conn.rollback()

    # 12) adapter readiness classification — active path enforces RS uniqueness via complete scan
    A = str(aid)  # canonical asset_id stored in field 99
    mutate = lambda res: res.__setitem__(6, _res("CHANGED-BETWEEN-SCANS"))
    cases = [
        ("active+unique match==bound ref -> ready", FakeRS({6: _res(A)}), "ready"),
        ("pending -> not_ready_pending (not missing)", FakeRS({6: _res(A, archive=-2)}), "not_ready_pending"),
        ("archived -> not_ready_missing", FakeRS({6: _res(A, archive=2)}), "not_ready_missing"),
        ("wrong type -> taxonomy_mismatch", FakeRS({6: _res(A, rtype=1)}), "not_ready_taxonomy_mismatch"),
        ("active but NO active carrier of canonical id -> missing", FakeRS({6: _res("OTHERID")}), "not_ready_missing"),
        ("TWO active carriers -> ambiguous (uniqueness enforced)", FakeRS({6: _res(A), 7: _res(A)}), "not_ready_ambiguous"),
        ("unique carrier != bound ref -> lineage_mismatch (binding disagreement)",
         FakeRS({6: _res("OTHER"), 9: _res(A)}), "not_ready_lineage_mismatch"),
        ("bound ref missing -> not_ready_missing", FakeRS({}), "not_ready_missing"),
        ("evidence tuple mutates between scans -> ambiguous (fail closed)",
         FakeRS({6: _res(A)}, mutate=mutate), "not_ready_ambiguous"),
        ("unauthorized", FakeRS(raise_exc=sdam.SdamUnauthorized("401")), "unauthorized"),
        ("unavailable", FakeRS(raise_exc=sdam.SdamUnavailable("timeout")), "unavailable"),
        ("malformed", FakeRS(raise_exc=sdam.SdamMalformed("bad")), "malformed"),
    ]
    for i, (label, rs, want) in enumerate(cases):
        got = sdam.observe_readiness(conn, rs, bid, f"obs-{i}"); conn.commit()   # caller owns commit
        check(f"readiness: {label}", got, want)
    # atomicity: observation + audit roll back TOGETHER when the caller does not commit (no internal commit)
    sdam.observe_readiness(conn, FakeRS({6: _res(A)}), bid, "obs-rollback")
    conn.rollback()
    cur.execute("SELECT (SELECT count(*) FROM sdam_readiness_observation WHERE binding_id=%s AND observation_key='obs-rollback'),"
                "       (SELECT count(*) FROM audit_log WHERE entity_id=%s AND detail->>'observation_key'='obs-rollback')",
                (str(bid), str(bid)))
    check("caller rollback discards observation AND audit atomically", cur.fetchone(), (0, 0))
    # audit event emitted for the readiness decision
    cur.execute("SELECT count(*) FROM audit_log WHERE entity='sdam_binding' AND entity_id=%s "
                "AND action='sdam_readiness_observed'", (str(bid),))
    check("readiness decisions emit audit events", cur.fetchone()[0] >= len(cases), True)
    cur.execute("SELECT count(*) FROM audit_log WHERE entity='sdam_binding' AND entity_id=%s "
                "AND action='sdam_binding_created'", (str(bid),))
    check("binding creation emitted audit event", cur.fetchone()[0], 1)
    # audit actor_kind reflects the observation's actor_type (operator), not a hardcoded 'system'
    sdam.observe_readiness(conn, FakeRS({6: _res(A)}), bid, "obs-operator", actor_type="operator", actor_id="khal"); conn.commit()
    cur.execute("SELECT count(*) FROM audit_log WHERE entity_id=%s AND action='sdam_readiness_observed' "
                "AND actor_kind='operator'", (str(bid),))
    check("audit actor_kind reflects observation actor_type", cur.fetchone()[0] >= 1, True)

    # 12a) #250 — slot-keyed READ-ONLY visibility (list_slot_bindings) for the Production/Edit
    # surfaces: pure persisted truth, no live provider call. Newest committed observation on `bid`
    # at this point is 'ready' (obs-operator above).
    view = sdam.list_slot_bindings(conn, SLOT)
    check("#250 slot view: one binding, newest persisted state, handoff_ready mirrors 'ready'",
          (len(view), str(view[0]["binding_id"]) == str(bid), view[0]["effective_state"],
           view[0]["handoff_ready"], view[0]["external_ref"], view[0]["mapping_version"]),
          (1, True, "ready", True, "6", 1))
    check("#250 slot view: an unbound slot is truthfully empty (never fabricated)",
          sdam.list_slot_bindings(conn, "RSDAM244-NOPE"), [])
    aid2 = str(uuid.uuid4())
    cur.execute("INSERT INTO asset (asset_id, slot_id, stage, kind, version) "
                "VALUES (%s,%s,'production','raw_cut',1)", (aid2, SLOT2))
    bid2 = sdam.create_binding(conn, aid2, 1, SLOT2, "61", "tester"); conn.commit()
    v2 = sdam.list_slot_bindings(conn, SLOT2)
    check("#250 slot view: bound with NO observation = effective_state None (distinct from "
          "pending), never handoff_ready",
          (len(v2), str(v2[0]["binding_id"]) == str(bid2), v2[0]["effective_state"],
           v2[0]["observed_at"], v2[0]["handoff_ready"]),
          (1, True, None, None, False))

    # 12b) scan primitives: complete pagination, cap, non-monotonic, all fail-closed correctly
    many = {r: _res("TOK") for r in range(1, 6)}                 # 5 matching, page_size 2 -> 3 pages
    check("complete pagination collects all candidates", FakeRS(many, page_size=2).complete_scan("TOK"), [1, 2, 3, 4, 5])
    check("resolve_unique zero on no byte-exact", FakeRS(many).resolve_unique("NOPE"), ("zero", None))
    check("resolve_unique ambiguous on many byte-exact", FakeRS(many).resolve_unique("TOK")[0], "ambiguous")
    check("safety cap -> ScanIncomplete (fail closed)",
          raises(lambda: FakeRS({r: _res("TOK") for r in range(1, 20)}, page_size=2, safety_cap=4).complete_scan("TOK")), True)
    check("non-monotonic page -> ScanIncomplete", raises(lambda: FakeRS(many, bad_order=True).complete_scan("TOK")), True)

    # 13) handoff only when fresh + ready
    sdam.observe_readiness(conn, FakeRS({6: _res(A)}), bid, "obs-final-ready"); conn.commit()
    ho = sdam.build_handoff(conn, FakeRS({6: _res(A)}), bid)
    check("handoff emitted when newest ready", ho["externalRef"], {"system": "sdam", "id": "6"})
    check("handoff carries canonical identity", (ho["asset_id"], ho["asset_version"], ho["mapping_version"]), (A, 1, 1))
    sdam.observe_readiness(conn, FakeRS({6: _res(A, archive=-2)}), bid, "obs-post-pending"); conn.commit()
    check("handoff suppressed when newest not ready", sdam.build_handoff(conn, FakeRS({6: _res(A)}), bid), None)

    # 13b) concurrency (independent connections): converge same-key; unique consecutive seqs
    def _append(key, payload, out, idx):
        c2 = engine.db_connect()
        try:
            out[idx] = ("ok", str(sdam.append_observation(c2, bid, key, *payload))); c2.commit()
        except Exception as e:
            c2.rollback(); out[idx] = ("err", str(e)[:40])
        finally:
            c2.close()
    N = 8
    same = [None] * N
    ts = [threading.Thread(target=_append, args=("csame", ("not_ready_pending", "system", "a"), same, i)) for i in range(N)]
    [t.start() for t in ts]; [t.join() for t in ts]
    ids = {v[1] for v in same if v and v[0] == "ok"}
    check("concurrent same-key/payload -> ALL N callers succeed", all(v and v[0] == "ok" for v in same), True)
    check("concurrent same-key/payload -> all converge to one id", len(ids), 1)
    cur.execute("SELECT count(*) FROM sdam_readiness_observation WHERE binding_id=%s AND observation_key='csame'", (str(bid),))
    check("concurrent same-key/payload -> exactly one committed row", cur.fetchone()[0], 1)

    # same key + DIFFERENT canonical payload race: exactly one payload commits, all losers get conflict,
    # one row, no phantom sequence/row.
    def _append_payload(rc, out, idx):
        c2 = engine.db_connect()
        try:
            out[idx] = ("ok", str(sdam.append_observation(c2, bid, "crace", rc, "system", "a"))); c2.commit()
        except Exception as e:
            c2.rollback(); out[idx] = ("conflict" if "conflict" in str(e).lower() else "err", str(e)[:40])
        finally:
            c2.close()
    race = [None] * N
    payloads = ["not_ready_pending" if i % 2 else "unavailable" for i in range(N)]
    tr = [threading.Thread(target=_append_payload, args=(payloads[i], race, i)) for i in range(N)]
    [t.start() for t in tr]; [t.join() for t in tr]
    oks = [v for v in race if v and v[0] == "ok"]
    conflicts = [v for v in race if v and v[0] == "conflict"]
    cur.execute("SELECT count(*), count(DISTINCT observation_seq) FROM sdam_readiness_observation "
                "WHERE binding_id=%s AND observation_key='crace'", (str(bid),))
    rows, seqs = cur.fetchone()
    # exactly one payload commits -> one row/seq; threads sharing that payload converge (ok),
    # every different-payload thread gets the conflict; none error.
    check("same-key different-payload race -> exactly one committed row (no phantom)", (rows, seqs), (1, 1))
    check("same-key different-payload race -> winners converge + all others conflict (no err)",
          (len(oks) + len(conflicts), len(conflicts) >= 1), (N, True))
    dist = [None] * N
    td = [threading.Thread(target=_append, args=(f"cdist-{i}", ("unavailable", "system", "a"), dist, i)) for i in range(N)]
    [t.start() for t in td]; [t.join() for t in td]
    cur.execute("SELECT array_agg(observation_seq ORDER BY observation_seq) FROM sdam_readiness_observation "
                "WHERE binding_id=%s AND observation_key LIKE 'cdist-%%'", (str(bid),))
    seqs = cur.fetchone()[0]
    check("concurrent distinct keys -> unique consecutive seqs (no gap/dup)",
          len(seqs) == len(set(seqs)) and max(seqs) - min(seqs) == len(seqs) - 1, True)

    # 14) derived stale via a short-TTL policy (deterministic 1s)
    cur.execute("INSERT INTO sdam_freshness_policy (policy_version, ttl_seconds, backoff_base_seconds) "
                "VALUES (999,1,1) ON CONFLICT DO NOTHING"); conn.commit()
    sdam.append_observation(conn, bid, "kstale", "unavailable", "system", "a", policy_version=999); conn.commit()
    time.sleep(1.2)
    st = sdam.current_state(conn, bid)
    check("expired newest -> derived stale", st["effective_state"], "stale")

    # 15) API read model requires a signed principal (reuse the existing /gw boundary; read-only != unauth)
    import os as _os
    _os.environ["REVIEWER_PROXY_SECRET"] = "sdam-test-secret"      # deterministic signing for the proof
    import gates.api as api
    from starlette.testclient import TestClient
    import hmac as _hmac, hashlib as _hashlib
    client = TestClient(api.app)
    _sig = lambda pid: _hmac.new(b"sdam-test-secret", pid.encode(), _hashlib.sha256).hexdigest()
    path = f"/sdam/bindings/{bid}/readiness"
    check("API unsigned -> 401", client.get(path).status_code, 401)
    check("API incomplete header -> 401", client.get(path, headers={"x-principal-id": "khal"}).status_code, 401)
    check("API bad signature -> 401",
          client.get(path, headers={"x-principal-id": "khal", "x-principal-signature": "deadbeef"}).status_code, 401)
    r = client.get(path, headers={"x-principal-id": "khal", "x-principal-signature": _sig("khal")})
    check("API valid signature -> 200 with readiness shape",
          (r.status_code, "effective_state" in r.json()), (200, True))

    # #259 P1b — the register-edit endpoint surfaces the TYPED per-phase status truthfully: a
    # projection-pending outcome is 200 (registration succeeded), NOT a 5xx; a refusal is a bounded
    # 409 code with NO provider detail. Inject a configured writer/reader + a stubbed adapter so the
    # in-process app exercises the API's own status mapping.
    _hdr = {"x-principal-id": "khal", "x-principal-signature": _sig("khal")}
    _orig_w, _orig_r, _orig_reg = api._rs_writer_from_env, api._rs_client_from_env, sdam.register_completed_edit
    api._rs_writer_from_env = lambda: object()
    api._rs_client_from_env = lambda: object()
    try:
        sdam.register_completed_edit = lambda *a, **k: {
            "state": "registered", "binding_id": "b1", "external_ref": "9", "projection": None,
            "projection_status": "pending", "retryable": True,
            "reason": "completed edit is registered; the discovery projection is pending — retry"}
        rp = client.post("/slots/RSDAM244-1/sdam/register-edit", headers=_hdr)
        check("#259 P1b API: projection-pending is 200 registered/retryable (never a 5xx), no provider detail",
              (rp.status_code, rp.json().get("state"), rp.json().get("projection_status"),
               rp.json().get("retryable"), "Sdam" not in str(rp.json())),
              (200, "registered", "pending", True, True))
        def _refuse(*a, **k):
            raise sdam.SdamRegistrationError("no_pin", "internal detail that must NOT leak")
        sdam.register_completed_edit = _refuse
        rr = client.post("/slots/RSDAM244-1/sdam/register-edit", headers=_hdr)
        check("#259 API: refusal -> bounded 409 code only (no internal message leaked)",
              (rr.status_code, "no_pin" in rr.text, "internal detail" not in rr.text), (409, True, True))
        check("#259 API: register-edit rejects an unsigned caller",
              client.post("/slots/RSDAM244-1/sdam/register-edit").status_code, 401)
    finally:
        api._rs_writer_from_env, api._rs_client_from_env = _orig_w, _orig_r
        sdam.register_completed_edit = _orig_reg

    # 16) #259 S2 — completed-edit registration state machine (phase-audited, convergent).
    print("\n----- #259 S2 completed-edit registration -----")
    import dam
    reg_cur = conn.cursor()
    reg_cur.execute("SET session_replication_role = replica")
    reg_cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN "
                    "(SELECT binding_id FROM sdam_asset_binding WHERE slot_id=%s)", (SLOT,))
    reg_cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,))
    reg_cur.execute("SET session_replication_role = DEFAULT")
    reg_cur.execute("DELETE FROM audit_log WHERE entity_id=%s AND entity='sdam_registration'", (SLOT,))
    reg_cur.execute("DELETE FROM slot_approval WHERE slot_id=%s AND artifact='edit'", (SLOT,))
    reg_cur.execute("DELETE FROM asset WHERE slot_id=%s AND stage='media_edit'", (SLOT,))
    conn.commit()
    # the S1 pin: one active master edit + the immutable approved_edit_master_pinned event
    edit_aid = dam.add_asset(conn, SLOT, "media_edit", "edit", uri="e://master", actor="ed")
    reg_cur.execute("INSERT INTO slot_approval (slot_id, artifact, revision, approver, actor_kind) "
                    "VALUES (%s,'edit',1,'khal','user')", (SLOT,))
    reg_cur.execute("INSERT INTO audit_log (entity, entity_id, action, actor, detail) "
                    "VALUES ('slot',%s,'approved_edit_master_pinned','khal', "
                    "jsonb_build_object('asset_id', %s::text, 'revision', 1))", (SLOT, str(edit_aid)))
    conn.commit()

    # refusal: a slot with no pin
    check("#259 refuse: no pin raises SdamRegistrationError(no_pin)",
          raises(lambda: sdam.register_completed_edit(conn, WriteFakeRS(), WriteFakeRS(), SLOT2), "no_pin"),
          True)

    # happy path A->D: create -> field99 -> binding -> observation(pending) -> field100 token
    w = WriteFakeRS()
    res = sdam.register_completed_edit(conn, w, w, SLOT, actor="cc")
    check("#259 happy path: registered, binding created, ONE resource, projection token, pending obs",
          (res["state"], res["adopted"], w.calls["create"], res["observation"],
           res["projection"] == f"g1:registered:{res['binding_id']}",
           w.resources[int(res["external_ref"])]["field99"] == str(edit_aid)),
          ("registered", None, 1, "not_ready_pending", True, True))
    first_ref, first_bid = res["external_ref"], res["binding_id"]

    # idempotent full re-run: binding exists -> adopt binding, ZERO new create, same binding/token
    w2 = WriteFakeRS(dict(w.resources))
    res2 = sdam.register_completed_edit(conn, w2, w2, SLOT, actor="cc")
    check("#259 idempotent re-run: adopts existing binding, zero new resource, same binding",
          (res2["adopted"], w2.calls["create"], res2["binding_id"] == first_bid, res2["external_ref"] == first_ref),
          ("binding", 0, True, True))

    # RECOVERY CASE 1 — RS create ok, then the binding txn fails. Simulate: the created-event +
    # resource exist but NO binding (wipe the binding, keep the created audit + resource).
    reg_cur.execute("SET session_replication_role = replica")
    reg_cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN "
                    "(SELECT binding_id FROM sdam_asset_binding WHERE slot_id=%s)", (SLOT,))
    reg_cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,))
    reg_cur.execute("SET session_replication_role = DEFAULT")
    conn.commit()
    w3 = WriteFakeRS(dict(w.resources))          # resource `first_ref` still present, field99 set
    before_creates = w3.calls["create"]
    res3 = sdam.register_completed_edit(conn, w3, w3, SLOT, actor="cc")
    check("#259 recovery-1 (binding-txn failure): retry ADOPTS the recorded resource — zero new "
          "create, exactly one binding, converged registration",
          (res3["adopted"] in ("created_event", None) and res3["external_ref"] == first_ref,
           w3.calls["create"] - before_creates, res3["state"]),
          (True, 0, "registered"))
    reg_cur.execute("SELECT count(*) FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,))
    check("#259 recovery-1: exactly one binding after convergence", reg_cur.fetchone()[0], 1)

    # RECOVERY CASE 1b — crash BEFORE the created-event committed: no created audit, but the
    # resource carries the canonical id -> resolve_unique adopts it, still no new create.
    reg_cur.execute("SET session_replication_role = replica")
    reg_cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN "
                    "(SELECT binding_id FROM sdam_asset_binding WHERE slot_id=%s)", (SLOT,))
    reg_cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,))
    reg_cur.execute("SET session_replication_role = DEFAULT")
    reg_cur.execute("DELETE FROM audit_log WHERE entity_id=%s AND action='sdam_edit_resource_created'", (SLOT,))
    conn.commit()
    w4 = WriteFakeRS(dict(w.resources))
    res4 = sdam.register_completed_edit(conn, w4, w4, SLOT, actor="cc")
    check("#259 recovery-1b (crash before created-event): resolve_unique adopts the discoverable "
          "resource, zero new create",
          (res4["external_ref"] == first_ref, w4.calls["create"], res4["state"]),
          (True, 0, "registered"))

    # RECOVERY CASE 1c — unreconciled intent: a created-event names a ref that does NOT carry the
    # canonical id -> STOP truthfully, never blind re-create.
    reg_cur.execute("SET session_replication_role = replica")
    reg_cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN "
                    "(SELECT binding_id FROM sdam_asset_binding WHERE slot_id=%s)", (SLOT,))
    reg_cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,))
    reg_cur.execute("SET session_replication_role = DEFAULT")
    reg_cur.execute("INSERT INTO audit_log (entity, entity_id, action, actor, detail) "
                    "VALUES ('sdam_registration',%s,'sdam_edit_resource_created','cc', "
                    "jsonb_build_object('asset_id', %s::text, 'version', 1, 'external_ref', '4321'))",
                    (SLOT, str(edit_aid)))
    conn.commit()
    w5 = WriteFakeRS({"4321": {"archive": -2, "resource_type": 3, "field99": "SOMEONE-ELSE", "field100": None}})
    check("#259 recovery-1c (unreconciled intent): recorded ref lacks the canonical id -> STOP, "
          "no blind re-create",
          (raises(lambda: sdam.register_completed_edit(conn, w5, w5, SLOT, actor="cc"), "unreconciled_intent"),
           w5.calls["create"]),
          (True, 0))
    conn.rollback()

    # RECOVERY CASE 1e (P1a) — CRASH right after the intent commit, BEFORE any provider create.
    # A prior intent exists, NO created-ref, and zero carriers -> fail-closed STOP, NEVER create
    # (a fresh call is indistinguishable ONLY if we don't gate on the pre-existing intent).
    reg_cur.execute("SET session_replication_role = replica")
    reg_cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN "
                    "(SELECT binding_id FROM sdam_asset_binding WHERE slot_id=%s)", (SLOT,))
    reg_cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,))
    reg_cur.execute("SET session_replication_role = DEFAULT")
    reg_cur.execute("DELETE FROM audit_log WHERE entity_id=%s AND entity='sdam_registration'", (SLOT,))
    # simulate the crash-after-intent state: an intent event, nothing else
    reg_cur.execute("INSERT INTO audit_log (entity, entity_id, action, actor, detail) "
                    "VALUES ('sdam_registration',%s,'sdam_edit_registration_intent','cc', "
                    "jsonb_build_object('asset_id', %s::text, 'version', 1))", (SLOT, str(edit_aid)))
    conn.commit()
    w7 = WriteFakeRS()          # empty store -> resolve_unique returns zero carriers
    check("#259 recovery-1e (P1a crash-after-intent, zero carriers): STOP unreconciled_intent, "
          "NEVER create",
          (raises(lambda: sdam.register_completed_edit(conn, w7, w7, SLOT, actor="cc"), "unreconciled_intent"),
           w7.calls["create"]),
          (True, 0))
    conn.rollback()
    reg_cur.execute("DELETE FROM audit_log WHERE entity_id=%s AND entity='sdam_registration'", (SLOT,))
    conn.commit()

    # RECOVERY CASE 1d — create OK but the field-99 write FAILS. The created-event is committed
    # before the field write, so the orphan is discoverable; retry ADOPTS it, sets field 99, and
    # converges — never an orphan-plus-duplicate.
    reg_cur.execute("SET session_replication_role = replica")
    reg_cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN "
                    "(SELECT binding_id FROM sdam_asset_binding WHERE slot_id=%s)", (SLOT,))
    reg_cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,))
    reg_cur.execute("SET session_replication_role = DEFAULT")
    reg_cur.execute("DELETE FROM audit_log WHERE entity_id=%s AND entity='sdam_registration'", (SLOT,))
    conn.commit()
    w8 = WriteFakeRS(fail_after=("update", 1))          # create ok, FIRST update_field (field 99) fails
    check("#259 recovery-1d setup: create ok but field-99 write fails -> typed provider error",
          raises(lambda: sdam.register_completed_edit(conn, w8, w8, SLOT, actor="cc")), True)
    check("#259 recovery-1d: exactly one resource exists (created), field99 unset, no binding yet",
          (w8.calls["create"], reg_cur.execute("SELECT count(*) FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,)) or reg_cur.fetchone()[0]),
          (1, 0))
    w8.fail_after = None                                # a real retry is a fresh request
    creates_1d = w8.calls["create"]
    res1d = sdam.register_completed_edit(conn, w8, w8, SLOT, actor="cc")
    reg_cur.execute("SELECT count(*) FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,))
    check("#259 recovery-1d: retry ADOPTS the discoverable resource, sets field99, converges — "
          "zero new create, one binding, field99 correct",
          (w8.calls["create"] - creates_1d, reg_cur.fetchone()[0], res1d["state"],
           w8.resources[int(res1d["external_ref"])]["field99"] == str(edit_aid)),
          (0, 1, "registered", True))

    # RECOVERY CASE 2 — binding exists, field-100 projection failed. Re-run completes ONLY the
    # projection: no new create, no new binding, token present after retry.
    reg_cur.execute("SET session_replication_role = replica")
    reg_cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN "
                    "(SELECT binding_id FROM sdam_asset_binding WHERE slot_id=%s)", (SLOT,))
    reg_cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,))
    reg_cur.execute("SET session_replication_role = DEFAULT")
    reg_cur.execute("DELETE FROM audit_log WHERE entity_id=%s AND entity='sdam_registration'", (SLOT,))
    conn.commit()
    # a WriteFakeRS that fails on the 2nd update_field (field-99 ok, field-100 fails)
    w6 = WriteFakeRS(fail_after=("update", 2))
    resd = sdam.register_completed_edit(conn, w6, w6, SLOT, actor="cc")
    # P1b — Phase-D failure is a TYPED retryable status, NOT a raised provider error: the
    # registration IS registered, projection pending, retryable, bounded reason (no provider detail).
    check("#259 recovery-2 (P1b) Phase-D failure -> typed 'registered/projection pending/retryable'",
          (resd["state"], resd["projection"], resd["projection_status"], resd["retryable"],
           "pending" in resd["reason"] and "SdamUnavailable" not in resd["reason"]),
          ("registered", None, "pending", True, True))
    reg_cur.execute("SELECT count(*), max(external_ref) FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,))
    bcount, bref = reg_cur.fetchone()
    check("#259 recovery-2: binding+audit are the truthful record after Phase-D failure (one binding)",
          bcount, 1)
    # P1b follow-up — projection_pending is SERVER-OBSERVABLE (reload-stable, pure DB) while the
    # projection is unwritten, and CLEARS once the projection-only retry writes field 100.
    view_pending = sdam.list_slot_bindings(conn, SLOT)
    check("#259 P1b read model: registered-but-projection-unwritten binding -> projection_pending True",
          (len(view_pending), view_pending[0]["projection_pending"]), (1, True))
    creates_before = w6.calls["create"]
    w6.fail_after = None                          # a real retry is a fresh request (no injected fault)
    res7 = sdam.register_completed_edit(conn, w6, w6, SLOT, actor="cc")   # retry: projection only
    reg_cur.execute("SELECT count(*) FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,))
    check("#259 recovery-2: retry completes ONLY the projection — zero new create/binding, token set",
          (w6.calls["create"] - creates_before, reg_cur.fetchone()[0], res7["adopted"],
           res7["projection"] == f"g1:registered:{res7['binding_id']}",
           w6.resources[int(bref)]["field100"] == res7["projection"]),
          (0, 1, "binding", True, True))
    check("#259 P1b read model: projection_pending CLEARS after the projection-only retry",
          sdam.list_slot_bindings(conn, SLOT)[0]["projection_pending"], False)

    # cleanup S2 fixtures
    reg_cur.execute("SET session_replication_role = replica")
    reg_cur.execute("DELETE FROM sdam_readiness_observation WHERE binding_id IN "
                    "(SELECT binding_id FROM sdam_asset_binding WHERE slot_id=%s)", (SLOT,))
    reg_cur.execute("DELETE FROM sdam_asset_binding WHERE slot_id=%s", (SLOT,))
    reg_cur.execute("SET session_replication_role = DEFAULT")
    reg_cur.execute("DELETE FROM audit_log WHERE entity_id=%s AND entity='sdam_registration'", (SLOT,))
    reg_cur.execute("DELETE FROM slot_approval WHERE slot_id=%s AND artifact='edit'", (SLOT,))
    reg_cur.execute("DELETE FROM asset WHERE slot_id=%s AND stage='media_edit'", (SLOT,))
    conn.commit()

    cleanup(conn)
    print(f"\n{'='*56}\n{'ALL SDAM CHECKS PASSED' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}\n{'='*56}")
    conn.close()
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
