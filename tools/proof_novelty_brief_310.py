"""#310 §B / #268 — focused proof of the bounded, explainable novelty brief.

Isolated synthetic fixture (NULL slot_id topics under a real hcs_id), no disturbance to other rows.
Proves: boundedness to the pinned cap, recency ordering, current-slot exclusion (NULL-safe),
correct text_ar->topic_angle column mapping, and the explainable selection_reason.
Cleans up after itself. Stub-only; makes NO model/provider call.
"""
import os, sys
sys.path.insert(0, "/work")
sys.path.insert(0, "/work/gates")   # engine.py uses a flat `import directives`
import psycopg2, psycopg2.extras
import engine as eng

PASS = True
def check(label, got, want):
    global PASS
    ok = got == want
    PASS = PASS and ok
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got} want={want}")

conn = psycopg2.connect(host=os.environ["DB_HOST"], dbname=os.environ["DB_NAME"],
                        user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                        port=os.environ.get("DB_PORT", "5432"))
conn.autocommit = False
cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

HCS = "1.1"                       # a real hcs_id (FK-valid)
TAG = "NOVELTY310"                # marker to find + clean our synthetic rows
cur.execute("DELETE FROM topic WHERE text_ar LIKE %s", (f"{TAG}%",))

# Seed MORE than the cap, staggered in time so recency ordering is observable.
CAP = 24
SEED = CAP + 6                    # 30 historical topics; brief must clip to 24 newest
for i in range(SEED):
    cur.execute("""INSERT INTO topic (hcs_id, text_ar, hook_text, tenant_id, created_at)
                   VALUES (%s, %s, %s, 'default', now() - (%s || ' minutes')::interval)""",
                (HCS, f"{TAG} angle {i:02d}", f"hook {i:02d}", i))   # i=0 newest ... i=29 oldest
conn.commit()

policy = {"novelty_lookback_days": 90, "novelty_max_exclusions": CAP}
# A real current slot always has a non-NULL slot_id; the synthetic history rows carry NULL slot_id, so
# `NULL IS DISTINCT FROM 'CUR-310'` = TRUE — every history row is a candidate, none silently dropped.
slot = {"hcs_id": HCS, "pillar_code": "P1_SELF", "slot_id": "CUR-310"}

brief = eng.build_novelty_brief(cur, slot, policy, tenant_id="default")
mine = [t for t in brief["exclusion_texts"] if t.startswith(TAG)]

print("1) boundedness + shape")
check("version tag", brief["version"], "novelty-v1")
check("bounded to the pinned cap (never the full ledger)", len(brief["input_topic_ids"]), CAP)
check("exclusion_texts count matches selected ids", len(brief["exclusion_texts"]), CAP)
check("selection_reason.selected == cap", brief["selection_reason"]["selected"], CAP)
check("selection_reason records the bound", brief["selection_reason"]["cap"], CAP)
check("selection_reason scopes to the HCS lineage", brief["selection_reason"]["scope"]["hcs_id"], HCS)

print("2) recency ordering + text_ar->topic_angle column mapping")
# newest seeded is i=00 (created_at now - 0 min); it must precede older seeds, and the 6 oldest clip out.
check("newest-first among seeds: angle 00 precedes angle 20",
      mine.index(f"{TAG} angle 00 / hook 00") < mine.index(f"{TAG} angle 20 / hook 20"), True)
check("clips the OLDEST seeds beyond the cap (angle 24..29 excluded)",
      any("angle 24" in t or "angle 29" in t for t in mine), False)
check("column mapping is real (Arabic angle text via text_ar, not the literal 'topic_angle')",
      f"{TAG} angle 00 / hook 00" in mine, True)

print("3) current-slot exclusion is NULL-safe (IS DISTINCT FROM), both branches")
# non-null current slot keeps NULL-slot history; NULL current slot excludes NULL-slot history (corner).
b_nonnull = eng.build_novelty_brief(cur, {"hcs_id": HCS, "pillar_code": "P1_SELF", "slot_id": "CUR-310"}, policy)
b_null = eng.build_novelty_brief(cur, {"hcs_id": HCS, "pillar_code": "P1_SELF", "slot_id": None}, policy)
check("non-null current slot retains the NULL-slot history", any(t.startswith(TAG) for t in b_nonnull["exclusion_texts"]), True)
check("NULL current slot drops NULL-slot history (documented corner, not a crash)",
      any(t.startswith(TAG) for t in b_null["exclusion_texts"]), False)

print("4) input_topic_ids are real topic identities (explainable provenance)")
check("every input id resolves to a UUID topic identity", all(
    isinstance(x, str) and len(x) == 36 for x in brief["input_topic_ids"]), True)

print("5) the brief PERSISTS through record_topic_provenance (§E) — end-to-end column landing")
RID = "R-NOVELTY310"
cur.execute("DELETE FROM topic_provenance WHERE topic_id IN (SELECT topic_id FROM topic WHERE round_id=%s)", (RID,))
cur.execute("DELETE FROM generation_job WHERE round_id=%s", (RID,))
cur.execute("DELETE FROM topic WHERE round_id=%s", (RID,))
cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
cur.execute("""INSERT INTO round (round_id, period_len_days, posts_per_day, post_times,
                                  pillar_distribution, format_distribution)
               VALUES (%s, 7, 1, '[]'::jsonb, '{}'::jsonb, '{}'::jsonb)""", (RID,))
cur.execute("""INSERT INTO topic (hcs_id, round_id, text_ar, hook_text, tenant_id)
               VALUES (%s, %s, %s, 'h', 'default') RETURNING topic_id, revision""",
            (HCS, RID, f"{TAG} target"))
tgt = cur.fetchone()
cur.execute("""INSERT INTO generation_job (round_id, accepted_schedule_token, actor)
               VALUES (%s, 1, 'system') RETURNING job_id, round_id, accepted_schedule_token, actor""", (RID,))
job = cur.fetchone()
persist_novelty = {"version": "novelty-v1",
                   "input_topic_ids": ["11111111-1111-1111-1111-111111111111"],
                   "selection_reason": {"basis": "test", "selected": 1}}
eng.record_topic_provenance(cur, tgt["topic_id"], tgt["revision"], job, None,
                            "stub", "stub:test", actor="system", novelty=persist_novelty)
conn.commit()
cur.execute("""SELECT novelty_brief_version, novelty_input_topic_ids, novelty_selection_reason
                 FROM topic_provenance WHERE topic_id=%s""", (tgt["topic_id"],))
pr = cur.fetchone()
check("novelty_brief_version persisted", pr["novelty_brief_version"], "novelty-v1")
check("novelty_input_topic_ids persisted", pr["novelty_input_topic_ids"],
      ["11111111-1111-1111-1111-111111111111"])
check("novelty_selection_reason persisted", pr["novelty_selection_reason"]["selected"], 1)

# cleanup
cur.execute("DELETE FROM topic_provenance WHERE topic_id=%s", (tgt["topic_id"],))
cur.execute("DELETE FROM generation_job WHERE round_id=%s", (RID,))
cur.execute("DELETE FROM topic WHERE round_id=%s OR text_ar LIKE %s", (RID, f"{TAG}%"))
cur.execute("DELETE FROM round WHERE round_id=%s", (RID,))
conn.commit()
cur.close(); conn.close()

print("\n" + "="*60)
print("ALL NOVELTY-BRIEF CHECKS PASSED" if PASS else "SOME CHECKS FAILED")
print("="*60)
sys.exit(0 if PASS else 1)
