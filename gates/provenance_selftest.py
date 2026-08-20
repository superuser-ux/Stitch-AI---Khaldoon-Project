"""M7 provenance read-model proof (#72). Seeds the isolated RSCR script-review round, adds a few
review/approval/handoff fixture rows so every edge TYPE is exercised, then derives the graph
IN-PROCESS via provenance.provenance_graph and asserts the honesty contract:

  * the payload has the agreed shape (round_id/nodes/edges/timeline/unsupported/generated_at),
  * EVERY node and edge cites a backing table+field and a source_id,
  * EVERY edge endpoint resolves to a real node (no dangling graph),
  * the timeline derives only from audit_log,
  * all #71 unsupported concepts are listed, and
  * NO faked node/edge type is emitted (no live-agent, model/provider, tool-call, delegation,
    communication, blocker, or task entity).

Run (container on the tanaghom network):
  docker exec -w /work tanaghom-gateapi python gates/provenance_selftest.py
"""
import os
import sys

import psycopg2
import psycopg2.extras

sys.path.insert(0, os.path.dirname(__file__))
import provenance  # noqa: E402

RID = "RSCR"
FAILS = []

# Types that must NEVER be emitted as real graph entities (they have no persisted backing — #71).
FORBIDDEN_NODE_TYPES = {"task", "blocker", "model", "provider", "tool_call", "live_agent"}
FORBIDDEN_EDGE_TYPES = {"delegated-to", "communicated-with", "blocked-by", "used-model", "called-tool"}
EXPECTED_UNSUPPORTED = {"live_agents", "used_model_provider", "tool_call_telemetry", "delegated_to",
                        "communicated_with", "blocked_by", "task_entity", "agent_rep_or_orchestrator_nodes"}


def check(label, got, want):
    ok = got == want
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: got={got!r} want={want!r}")
    if not ok:
        FAILS.append(label)


def ok(label, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(label)


def _db():
    return psycopg2.connect(host=os.environ.get("DB_HOST", "db"),
                            port=int(os.environ.get("DB_PORT", "5432")),
                            dbname=os.environ.get("DB_NAME", "tanaghom"),
                            user=os.environ.get("DB_USER", "tanaghom"),
                            password=os.environ.get("DB_PASSWORD", os.environ.get("POSTGRES_PASSWORD", "changeme")))


def seed_fixtures(conn):
    """Reseed RSCR, then add review/approval/handoff rows so every edge type is exercised."""
    import subprocess
    subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "e2e_script_seed.py")], check=True)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # the open script_review gate for this run
    cur.execute("""SELECT g.gate_id FROM gate g JOIN gate_target t USING (gate_id)
                   JOIN slot sl ON sl.slot_id=t.slot_id WHERE sl.round_id=%s LIMIT 1""", (RID,))
    gate_id = cur.fetchone()["gate_id"]
    # a real transition from the active workflow, to anchor a directive handoff on real stage keys
    cur.execute("""SELECT from_stage_key, to_stage_key FROM workflow_transition wt
                   JOIN workflow_version v ON v.version_id=wt.version_id
                   WHERE v.status='active' AND v.tenant_id='default' AND v.module='content'
                   ORDER BY wt.from_stage_key LIMIT 1""")
    tr = cur.fetchone()
    # approve RSCR-1 (approved-by), request_change RSCR-2 (request-change)
    cur.execute("""INSERT INTO gate_decision (gate_id, slot_id, approver_id, decision, notes, revision)
                   VALUES (%s,'RSCR-1','sheikh','approve',NULL,1), (%s,'RSCR-2','nour','request_change','fix tone',1)
                   ON CONFLICT DO NOTHING""", (gate_id, gate_id))
    cur.execute("""INSERT INTO slot_approval (slot_id, artifact, revision, approver)
                   VALUES ('RSCR-1','script',1,'sheikh') ON CONFLICT (slot_id, artifact) DO NOTHING""")
    cur.execute("""INSERT INTO slot_review (slot_id, review, disposition, actor)
                   VALUES ('RSCR-2','native_review','escalated','nour') ON CONFLICT (slot_id, review) DO NOTHING""")
    cur.execute("""INSERT INTO directive (slot_id, type, from_stage, to_stage, payload, produced_by)
                   VALUES ('RSCR-1','topic_directive',%s,%s,'{}'::jsonb,'agent.topic')""",
                (tr["from_stage_key"], tr["to_stage_key"]))
    conn.commit()
    cur.close()
    return tr


def main():
    conn = _db()
    print(f"seeding {RID} + review/approval/handoff fixtures…")
    tr = seed_fixtures(conn)

    g = provenance.provenance_graph(conn, RID)

    print("1) contract shape")
    check("payload keys", sorted(g.keys()), ["edges", "generated_at", "nodes", "round_id", "timeline", "unsupported"])
    check("round_id", g["round_id"], RID)
    ok("generated_at is set", bool(g.get("generated_at")))

    nodes, edges, timeline = g["nodes"], g["edges"], g["timeline"]
    node_ids = {n["id"] for n in nodes}
    node_types = {n["type"] for n in nodes}
    edge_types = {e["type"] for e in edges}

    print("2) nodes/edges/timeline are non-empty and derived from persisted data")
    ok("has nodes", len(nodes) > 0, f"{len(nodes)}")
    ok("has edges", len(edges) > 0, f"{len(edges)}")
    ok("has timeline", len(timeline) > 0, f"{len(timeline)}")
    ok("node types include round/stage/slot/topic/script/actor",
       {"round", "stage", "slot", "topic", "script", "actor"} <= node_types, str(sorted(node_types)))

    print("3) every node cites a backing table+field and a source_id")
    ncite = [n["id"] for n in nodes if not (n.get("cite", {}).get("table") and n.get("cite", {}).get("field"))]
    nsrc = [n["id"] for n in nodes if not n.get("source_id")]
    ok("all nodes carry a cite{table,field}", not ncite, str(ncite[:5]))
    ok("all nodes carry a source_id", not nsrc, str(nsrc[:5]))

    print("4) every edge cites a table+field, has a source_id, and both endpoints resolve to a node")
    ecite = [e["id"] for e in edges if not (e.get("cite", {}).get("table") and e.get("cite", {}).get("field"))]
    esrc = [e["id"] for e in edges if not e.get("source_id")]
    dangling = [e["id"] for e in edges if e["source"] not in node_ids or e["target"] not in node_ids]
    ok("all edges carry a cite{table,field}", not ecite, str(ecite[:5]))
    ok("all edges carry a source_id", not esrc, str(esrc[:5]))
    ok("no dangling edges (endpoints resolve to real nodes)", not dangling, str(dangling[:5]))

    print("5) every edge TYPE is exercised by the fixtures")
    for t in ["scopes", "transition", "produced", "approved-by", "request-change", "reviewed-by", "handoff"]:
        ok(f"edge type present: {t}", t in edge_types)

    print("6) timeline derives only from audit_log")
    tl_bad = [t["id"] for t in timeline if t.get("cite", {}).get("table") != "audit_log"]
    ok("all timeline events cite audit_log", not tl_bad, str(tl_bad[:5]))

    print("7) unsupported concepts are listed (honest omission), none faked as nodes/edges")
    check("unsupported concepts", {u["concept"] for u in g["unsupported"]}, EXPECTED_UNSUPPORTED)
    bad_nt = node_types & FORBIDDEN_NODE_TYPES
    bad_et = edge_types & FORBIDDEN_EDGE_TYPES
    ok("no faked node types emitted", not bad_nt, str(sorted(bad_nt)))
    ok("no faked edge types emitted", not bad_et, str(sorted(bad_et)))

    print("8) unknown round is a clean error (not a fabricated empty graph)")
    try:
        provenance.provenance_graph(conn, "RNOPE")
        ok("unknown round raises", False)
    except ValueError:
        ok("unknown round raises", True)

    print("9) HTTP endpoint GET /rounds/{id}/provenance mirrors the read model")
    import json
    import urllib.error
    import urllib.request
    api = os.environ.get("API_BASE", "http://localhost:8009")
    try:
        with urllib.request.urlopen(f"{api}/rounds/{RID}/provenance", timeout=20) as r:
            http = json.load(r)
        ok("endpoint returns the same round_id", http.get("round_id") == RID)
        ok("endpoint returns nodes/edges/timeline/unsupported",
           all(k in http for k in ("nodes", "edges", "timeline", "unsupported")))
        with urllib.request.urlopen(f"{api}/rounds/RNOPE/provenance", timeout=20) as r:
            ok("unknown round over HTTP is 404", False)  # should not reach — 404 raises below
    except urllib.error.HTTPError as e:
        ok("unknown round over HTTP is 404", e.code == 404, f"got {e.code}")
    except urllib.error.URLError as e:
        ok("HTTP endpoint reachable (API up)", False, f"{e}")

    conn.close()
    print("=" * 60)
    if FAILS:
        print(f"PROVENANCE SELFTEST FAILED — {len(FAILS)} check(s): {FAILS}")
        sys.exit(1)
    print("ALL PROVENANCE CHECKS PASSED")


if __name__ == "__main__":
    main()
