"""M7 living-operation view — run-scoped provenance graph READ MODEL (#71 / directive #72).

A pure, read-only derivation of a graph-shaped payload for one `round_id`, built ENTIRELY from
persisted Tanaghom records. It is a DATA CONTRACT only — no UI, no writes, no runtime orchestration.

Honesty contract (the whole point of this slice):
  * Every node, edge, and timeline entry carries a data-source citation (`cite = {table, field}`)
    plus the `source_id` of the backing record. If a thing cannot cite a real row, it is NOT drawn.
  * Future-only concepts that have NO persisted backing today (live multi-agent state, model/provider
    routing, tool-call telemetry, delegation/communication, blockers, a task entity, unseeded
    agent-rep/orchestrator nodes) are never emitted as graph entities — they are listed explicitly in
    `unsupported[]` so a UI can render an honest "what this map does NOT claim" legend.

Contract shape (see docs/M7-provenance-read-model.md):
  {
    "round_id":     str,
    "generated_at": ISO-8601 str,
    "nodes":     [ {id, type, label, cite:{table,field}, source_id, deep_link, meta} ],
    "edges":     [ {id, type, source, target, cite:{table,field}, source_id, meta} ],
    "timeline":  [ {id, at, entity, entity_id, action, actor, actor_kind, cite} ],
    "unsupported": [ {concept, reason, would_require} ],
  }

Node types:  round | stage | slot | topic | script | asset | actor
Edge types:  scopes | transition | handoff | produced | revised-from | approved-by | request-change | reviewed-by
"""
from datetime import datetime, timezone

import psycopg2.extras


def _cite(table, field):
    return {"table": table, "field": field}


# Concepts #71 fences off. No persisted rows back these today, so they are DECLARED unsupported
# rather than faked. A UI must surface these as explicit "not claimed yet" — never as live nodes.
UNSUPPORTED = [
    {"concept": "live_agents",
     "reason": "no concurrent live-agent runtime; a single round-scoped assistant exists (gates/agent.py)",
     "would_require": "#19 multi-agent runtime + persisted agent-session records"},
    {"concept": "used_model_provider",
     "reason": "model/provider is chosen at call time (system_config.yaml, agents/providers.py) and never persisted per run",
     "would_require": "persisted per-run model/provider selection rows"},
    {"concept": "tool_call_telemetry",
     "reason": "raw LLM tool-calls are not recorded; only engine actions are audited (audit_log)",
     "would_require": "tool-call event instrumentation"},
    {"concept": "delegated_to",
     "reason": "no orchestrator->agent or agent->agent delegation records exist",
     "would_require": "#19 runtime delegation records"},
    {"concept": "communicated_with",
     "reason": "assistant chat is stateless per request; no persisted inter-actor conversation graph",
     "would_require": "a persisted message/communication log"},
    {"concept": "blocked_by",
     "reason": "no blocker entity; 'directive:blocked' is a GitHub label, not runtime data",
     "would_require": "a first-class blocker/error entity"},
    {"concept": "task_entity",
     "reason": "no task table; the unit of work is `slot` and the run is `round`",
     "would_require": "a #19-level task modeling decision"},
    {"concept": "agent_rep_or_orchestrator_nodes",
     "reason": "principal_kind has 'agent_rep' but no rows are seeded; the orchestrator is the engine spine, not an addressable principal",
     "would_require": "seeded agent_rep/orchestrator principal rows (#19 / #21 / #10)"},
]

# Edge type per recorded review decision (gate_decision.decision).
_DECISION_EDGE = {"approve": "approved-by", "request_change": "request-change", "reject": "reviewed-by"}


def _touch_actor(reg, actor_id, kind=None):
    """Register an actor id seen on a real record; remember a kind if we learn one."""
    if not actor_id:
        return
    if actor_id not in reg or (kind and not reg[actor_id]):
        reg[actor_id] = kind or reg.get(actor_id)


def provenance_graph(conn, round_id, generated_at=None):
    """Derive the run-scoped provenance graph for `round_id` from persisted data only.

    Read-only. Raises ValueError for an unknown round. `generated_at` may be injected (else now, UTC)."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT round_id, label, status FROM round WHERE round_id=%s", (round_id,))
        rnd = cur.fetchone()
        if not rnd:
            raise ValueError(f"unknown round {round_id!r}")

        nodes, edges = [], []
        actors = {}  # actor_id -> kind (deduped across every record we touch)

        # ---- Round node -----------------------------------------------------
        nodes.append({"id": f"round:{round_id}", "type": "round", "label": rnd["label"] or round_id,
                      "cite": _cite("round", "round_id"), "source_id": round_id, "deep_link": None,
                      "meta": {"status": rnd["status"]}})

        # ---- Stage + transition topology (active workflow version) ----------
        cur.execute("""SELECT version_id::text AS version_id FROM workflow_version
                       WHERE tenant_id='default' AND module='content' AND status='active'
                       ORDER BY activated_at DESC NULLS LAST, created_at DESC LIMIT 1""")
        wv = cur.fetchone()
        stage_keys = set()
        if wv:
            vid = wv["version_id"]
            cur.execute("""SELECT stage_id::text AS stage_id, stage_key, stage_label, ordinal
                           FROM workflow_stage WHERE version_id=%s AND enabled ORDER BY ordinal""", (vid,))
            for s in cur.fetchall():
                stage_keys.add(s["stage_key"])
                nodes.append({"id": f"stage:{s['stage_key']}", "type": "stage", "label": s["stage_label"],
                              "cite": _cite("workflow_stage", "stage_key"), "source_id": s["stage_id"],
                              "deep_link": None, "meta": {"ordinal": s["ordinal"]}})
            cur.execute("""SELECT transition_id::text AS transition_id, from_stage_key, to_stage_key, condition_key
                           FROM workflow_transition WHERE version_id=%s AND enabled""", (vid,))
            for t in cur.fetchall():
                if t["from_stage_key"] in stage_keys and t["to_stage_key"] in stage_keys:
                    edges.append({"id": f"transition:{t['transition_id']}", "type": "transition",
                                  "source": f"stage:{t['from_stage_key']}", "target": f"stage:{t['to_stage_key']}",
                                  "cite": _cite("workflow_transition", "from_stage_key->to_stage_key"),
                                  "source_id": t["transition_id"], "meta": {"condition": t["condition_key"]}})

        # ---- Slot nodes + round->slot scopes edges --------------------------
        cur.execute("""SELECT slot_id, status, topic_angle, day, time_uae FROM slot
                       WHERE round_id=%s ORDER BY day, time_uae, slot_id""", (round_id,))
        slots = cur.fetchall()
        slot_ids = [s["slot_id"] for s in slots]
        for s in slots:
            nodes.append({"id": f"slot:{s['slot_id']}", "type": "slot", "label": s["topic_angle"] or s["slot_id"],
                          "cite": _cite("slot", "slot_id"), "source_id": s["slot_id"], "deep_link": None,
                          "meta": {"status": s["status"], "day": s["day"], "time_uae": s["time_uae"]}})
            edges.append({"id": f"scopes:{round_id}->{s['slot_id']}", "type": "scopes",
                          "source": f"round:{round_id}", "target": f"slot:{s['slot_id']}",
                          "cite": _cite("slot", "round_id"), "source_id": s["slot_id"], "meta": {}})

        # ---- Artifact nodes (topic/script per revision) + produced + revised-from lineage ----
        def _artifacts(table, label_field, node_type):
            if not slot_ids:
                return
            cur.execute(f"""SELECT slot_id, revision, base_revision, {label_field} AS label
                            FROM {table} WHERE slot_id = ANY(%s) ORDER BY slot_id, revision""", (slot_ids,))
            for a in cur.fetchall():
                nid = f"{node_type}:{a['slot_id']}:v{a['revision']}"
                label = (a["label"] or "").strip()[:80] or f"{node_type} v{a['revision']}"
                nodes.append({"id": nid, "type": node_type, "label": label,
                              "cite": _cite(table, "slot_id,revision"), "source_id": f"{a['slot_id']}#{a['revision']}",
                              "deep_link": None, "meta": {"revision": a["revision"]}})
                edges.append({"id": f"produced:{nid}", "type": "produced",
                              "source": f"slot:{a['slot_id']}", "target": nid,
                              "cite": _cite(table, "slot_id"), "source_id": f"{a['slot_id']}#{a['revision']}", "meta": {}})
                if a["base_revision"]:
                    edges.append({"id": f"revised-from:{nid}", "type": "revised-from", "source": nid,
                                  "target": f"{node_type}:{a['slot_id']}:v{a['base_revision']}",
                                  "cite": _cite(table, "base_revision"), "source_id": f"{a['slot_id']}#{a['revision']}",
                                  "meta": {"base_revision": a["base_revision"]}})
        _artifacts("topic", "hook_text", "topic")
        _artifacts("script", "final_line", "script")

        # ---- Asset nodes + produced edges -----------------------------------
        if slot_ids:
            cur.execute("""SELECT asset_id::text AS asset_id, slot_id, stage, kind, status, created_by
                           FROM asset WHERE slot_id = ANY(%s) ORDER BY slot_id, created_at""", (slot_ids,))
            for a in cur.fetchall():
                nid = f"asset:{a['asset_id']}"
                nodes.append({"id": nid, "type": "asset", "label": f"{a['kind']} ({a['stage']})",
                              "cite": _cite("asset", "asset_id"), "source_id": a["asset_id"], "deep_link": None,
                              "meta": {"status": a["status"], "stage": a["stage"], "kind": a["kind"]}})
                edges.append({"id": f"produced:{nid}", "type": "produced", "source": f"slot:{a['slot_id']}",
                              "target": nid, "cite": _cite("asset", "slot_id"), "source_id": a["asset_id"], "meta": {}})
                _touch_actor(actors, a["created_by"])

            # ---- Review / approval / request-change edges (gate_decision) ----
            cur.execute("""SELECT gate_id::text AS gate_id, slot_id, approver_id, decision::text AS decision, revision
                           FROM gate_decision WHERE slot_id = ANY(%s)""", (slot_ids,))
            for d in cur.fetchall():
                _touch_actor(actors, d["approver_id"])
                etype = _DECISION_EDGE.get(d["decision"], "reviewed-by")
                edges.append({"id": f"{etype}:{d['gate_id']}:{d['approver_id']}:{d['slot_id']}", "type": etype,
                              "source": f"actor:{d['approver_id']}", "target": f"slot:{d['slot_id']}",
                              "cite": _cite("gate_decision", "decision"), "source_id": d["gate_id"],
                              "meta": {"decision": d["decision"], "revision": d["revision"]}})

            # ---- Pinned approved revision (slot_approval) -> approved-by ------
            cur.execute("SELECT slot_id, artifact, revision, approver FROM slot_approval WHERE slot_id = ANY(%s)", (slot_ids,))
            for a in cur.fetchall():
                if not a["approver"]:
                    continue
                _touch_actor(actors, a["approver"])
                edges.append({"id": f"approved-rev:{a['slot_id']}:{a['artifact']}", "type": "approved-by",
                              "source": f"actor:{a['approver']}", "target": f"{a['artifact']}:{a['slot_id']}:v{a['revision']}",
                              "cite": _cite("slot_approval", "approver"), "source_id": f"{a['slot_id']}:{a['artifact']}",
                              "meta": {"revision": a["revision"], "artifact": a["artifact"]}})

            # ---- Reviewer dispositions (slot_review) -> reviewed-by ----------
            cur.execute("SELECT slot_id, review, disposition, actor FROM slot_review WHERE slot_id = ANY(%s)", (slot_ids,))
            for r in cur.fetchall():
                if not r["actor"]:
                    continue
                _touch_actor(actors, r["actor"])
                edges.append({"id": f"reviewed-by:{r['slot_id']}:{r['review']}", "type": "reviewed-by",
                              "source": f"actor:{r['actor']}", "target": f"slot:{r['slot_id']}",
                              "cite": _cite("slot_review", "disposition"), "source_id": f"{r['slot_id']}:{r['review']}",
                              "meta": {"disposition": r["disposition"], "review": r["review"]}})

            # ---- Directive handoffs (stage -> stage) -------------------------
            cur.execute("""SELECT directive_id::text AS directive_id, slot_id, from_stage, to_stage, produced_by, revision
                           FROM directive WHERE slot_id = ANY(%s)""", (slot_ids,))
            for d in cur.fetchall():
                _touch_actor(actors, d["produced_by"])
                if d["from_stage"] and d["to_stage"] and d["from_stage"] in stage_keys and d["to_stage"] in stage_keys:
                    edges.append({"id": f"handoff:{d['directive_id']}", "type": "handoff",
                                  "source": f"stage:{d['from_stage']}", "target": f"stage:{d['to_stage']}",
                                  "cite": _cite("directive", "from_stage->to_stage"), "source_id": d["directive_id"],
                                  "meta": {"slot_id": d["slot_id"], "produced_by": d["produced_by"], "revision": d["revision"]}})

        # ---- Timeline (audit_log for the run's entities) --------------------
        cur.execute("""SELECT DISTINCT g.gate_id::text AS gate_id FROM gate g
                       JOIN gate_target t USING (gate_id) JOIN slot sl ON sl.slot_id=t.slot_id
                       WHERE sl.round_id=%s""", (round_id,))
        gate_ids = [g["gate_id"] for g in cur.fetchall()]
        entity_ids = slot_ids + gate_ids + [round_id]
        timeline = []
        cur.execute("""SELECT id, entity, entity_id, action, actor, actor_kind, at
                       FROM audit_log WHERE entity_id = ANY(%s) ORDER BY at, id""", (entity_ids,))
        for e in cur.fetchall():
            _touch_actor(actors, e["actor"], e["actor_kind"])
            timeline.append({"id": f"audit:{e['id']}", "at": e["at"].isoformat() if e["at"] else None,
                             "entity": e["entity"], "entity_id": e["entity_id"], "action": e["action"],
                             "actor": e["actor"], "actor_kind": e["actor_kind"], "cite": _cite("audit_log", "action")})

        # ---- Actor nodes (deduped; kind from principal where known) ---------
        ids = [a for a in actors if a]
        known = {}
        if ids:
            cur.execute("""SELECT principal_id, kind::text AS kind, COALESCE(display_name_en, principal_id) AS label
                           FROM principal WHERE principal_id = ANY(%s)""", (ids,))
            for p in cur.fetchall():
                known[p["principal_id"]] = (p["kind"], p["label"])
        for aid, seen_kind in actors.items():
            if not aid:
                continue
            if aid in known:
                kind, label = known[aid]
                cite = _cite("principal", "principal_id")
            else:
                kind, label = (seen_kind or "system"), aid
                cite = _cite("audit_log", "actor_kind")
            nodes.append({"id": f"actor:{aid}", "type": "actor", "label": label,
                          "cite": cite, "source_id": aid, "deep_link": None, "meta": {"kind": kind}})

        stamp = generated_at or datetime.now(timezone.utc).isoformat()
        return {"round_id": round_id, "generated_at": stamp,
                "nodes": nodes, "edges": edges, "timeline": timeline, "unsupported": list(UNSUPPORTED)}
    finally:
        cur.close()
