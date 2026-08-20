"""Directive packages + the stage contract (M9 · Block B1) — the integration seam.

ARCHITECTURE.md ("Inter-stage handoff = directive propagation") models the pipeline as a
GRAPH of stage handoffs, not a flat line. Stages interoperate via a structured **directive
package**, not just the bare artifact — the stable contract that lets heterogeneous executors
(AI agents / humans / external systems: AVP, POSTIZ, analytics) plug in regardless of
integration shape (API / MCP / file / manual).

This module is the ONE canonical home for that contract. It is PURE (no import of engine) so
both the spine (`engine.py`) and the domain writers (`run_writers.py`) can import it without a
cycle. It owns three things:

  1. The **directive package** schema (versioned; the six fields from ARCHITECTURE.md) +
     builders for the current handoffs (strategy→topic, topic→script, script→production).
  2. The **stage contract** read from config `stages.<stage>` = {generator, consumes, emits,
     gate} — the seam future executors plug into without touching the engine.
  3. Persistence + provenance: `record` (insert + audit `directive_emitted`), `latest`
     (the directive feeding a stage), `emit_output` (build+record a stage's output directive).

No-hardcode: everything tunable (which stages exist, generators, the version, whether to
persist) lives in config. Content fields (intent) are bilingual; governance lists
(constraints / acceptance_criteria) are stable TOKENS rendered bilingual via the i18n glossary
— the same no-hardcode-copy discipline as statuses/decisions, not inline prose.
"""
import os

import psycopg2.extras
from psycopg2.extras import Json

import dam  # DAM asset reads for the manual-stage directive builders (no cycle: dam is pure)

SCHEMA_VERSION = "1.0"

# The six fields of a directive package (ARCHITECTURE.md). Order is canonical.
PACKAGE_FIELDS = ("intent", "inputs", "parameters", "constraints", "acceptance_criteria", "context")


# --------------------------------------------------------------------------- #
# Package construction + validation
# --------------------------------------------------------------------------- #
def ref(kind, ident, **extra):
    """A typed reference to an upstream artifact (no inlined copy — directives point at the
    store, so heavy content isn't duplicated across the chain)."""
    r = {"kind": kind, "ref": f"{kind}:{ident}"}
    r.update({k: v for k, v in extra.items() if v is not None})
    return r


def make(type_, from_stage, to_stage, *, intent, inputs, parameters,
         constraints, acceptance_criteria, context):
    """Assemble a versioned directive package. `intent` is the one bilingual content field
    ({'ar': .., 'en': ..}); the rest are stable tokens/refs/knobs. Validated before return."""
    pkg = {
        "schema_version": SCHEMA_VERSION,
        "type": type_,                # the named handoff (sugar over from_stage->to_stage)
        "from_stage": from_stage,
        "to_stage": to_stage,
        "intent": intent,
        "inputs": list(inputs or []),
        "parameters": dict(parameters or {}),
        "constraints": list(constraints or []),
        "acceptance_criteria": list(acceptance_criteria or []),
        "context": dict(context or {}),
    }
    validate(pkg)
    return pkg


class DirectiveError(ValueError):
    pass


def validate(pkg):
    """A package must carry the version + the six fields, and intent must be bilingual."""
    for f in PACKAGE_FIELDS:
        if f not in pkg:
            raise DirectiveError(f"directive missing required field {f!r}")
    intent = pkg.get("intent")
    if not (isinstance(intent, dict) and intent.get("ar") and intent.get("en")):
        raise DirectiveError("directive.intent must be bilingual {'ar':..,'en':..}")
    if not pkg.get("to_stage"):
        raise DirectiveError("directive missing to_stage (which stage consumes it)")
    return True


# --------------------------------------------------------------------------- #
# Stage contract (config-driven) — stage = {generator, consumes, emits, gate}
# --------------------------------------------------------------------------- #
def stages(cfg):
    return cfg.get("stages") or {}


def stage_contract(cfg, stage):
    s = stages(cfg).get(stage)
    if not s:
        raise DirectiveError(f"no stage contract for {stage!r} (system_config.yaml stages.{stage})")
    return s


def stage_by_gate(cfg, gate_stage):
    """The pipeline stage whose review gate is `gate_stage` -> (name, contract). The stage's
    OUTPUT directive (`emits`) is produced when this gate approves. (None, None) if unmapped."""
    for name, s in stages(cfg).items():
        if s.get("gate") == gate_stage:
            return name, s
    return None, None


def is_enabled(cfg):
    return bool((cfg.get("directives") or {}).get("enabled", True))


# --------------------------------------------------------------------------- #
# Builders for the current handoffs (concrete + minimal — NOT a universal DSL)
# --------------------------------------------------------------------------- #
def strategy_to_topic(slot, hcs, lens, cfg):
    """The directive the Planner/strategy hands the TOPIC stage: produce a topic + hook for
    THIS methodology selection (pillar/HCS/lens/format). Recorded as origin provenance."""
    w = cfg.get("writers", {})
    name_ar = hcs.get("name_ar") or hcs.get("name_en")
    return make(
        "strategy_directive", "strategy", "topic",
        intent={
            "ar": f"اقترِح موضوعًا وخطّافًا منطوقًا لـ«{name_ar}» من زاوية {lens.get('name_ar') or lens['lens_id']}",
            "en": f"Propose a topic + spoken hook for HCS {hcs['hcs_id']} ({hcs['name_en']}) "
                  f"through lens {lens['lens_id']} ({lens['name_en']})"},
        inputs=[ref("hcs", hcs["hcs_id"]), ref("lens", lens["lens_id"]),
                ref("pillar", slot["pillar_code"])],
        parameters={"format": slot.get("format"), "hook_type": slot.get("hook_type"),
                    "lens": lens["lens_id"], "dialect": "ar-PS",
                    "hook_words": [w.get("hook_word_min", 3), w.get("hook_word_max", 7)]},
        constraints=["canon_013_hook", "no_greeting", "no_moataz_name",
                     "address_one_person", "dialect_ar_ps", "non_duplicate"],
        acceptance_criteria=["maps_to_hcs", "hook_within_word_range", "hook_no_violations",
                             "rationale_bilingual"],
        context={"pillar": slot["pillar_code"], "hcs_id": hcs["hcs_id"], "lens": lens["lens_id"],
                 "cycle_no": slot.get("cycle_no")})


def topic_to_script(slot, topic, hcs, lens, cfg):
    """The APPROVED TOPIC packaged as the directive the SCRIPT stage consumes — the formal
    statement of "approved topic = directive into the script stage". Emitted at topic_review
    approval."""
    anchor_policy = (cfg.get("writers", {}).get("islamic_anchor", {}) or {}).get(
        "policy", "omit_by_default")
    return make(
        "topic_directive", "topic", "script",
        intent={"ar": "اكتب النص الكامل بالعامية الفلسطينية للموضوع المعتمد، وافتح بالخطّاف حرفيًا",
                "en": "Write the full Palestinian-Arabic script for the approved topic; "
                      "open on the hook verbatim"},
        inputs=[ref("topic", topic.get("topic_id"), revision=topic.get("revision")),
                ref("hcs", hcs["hcs_id"]), ref("lens", lens["lens_id"])],
        parameters={"format": slot.get("format"),
                    "hook_text": topic.get("hook_text") or slot.get("hook_text"),
                    "hook_type": topic.get("hook_type") or slot.get("hook_type"),
                    "topic_angle": topic.get("text_ar") or slot.get("topic_angle"),
                    "dialect": "ar-PS", "anchor_policy": anchor_policy},
        constraints=["open_on_hook_verbatim", "canon_013_hard_fails", "canon_012_delivery_check",
                     "dialect_ar_ps", "anchor_omit_by_default"],
        acceptance_criteria=["no_hard_fails", "delivery_check_complete",
                             "anchor_organic_or_absent", "no_dialect_violations"],
        context={"pillar": slot["pillar_code"], "hcs_id": hcs["hcs_id"], "lens": lens["lens_id"],
                 "topic_revision": topic.get("revision")})


def script_to_production(slot, script, format_spec, cfg):
    """The directive the SCRIPT stage emits for PRODUCTION (shoot/edit) — "the script stage
    emits production directions". Emitted at script_review approval. Production is a manual
    stage today (executor=manual); the contract is identical so AVP can plug into the
    generator slot later untouched."""
    platforms = (cfg.get("distribution", {}) or {}).get("platforms") or []
    flags = script.get("flags")
    flags = flags if isinstance(flags, list) else (flags or [])
    return make(
        "production_directive", "script", "production",
        intent={"ar": "جهّز إنتاج هذا النص (تصوير/مونتاج) مع الحفاظ على الصوت والسطر الأخير",
                "en": "Produce this script (shoot/edit); preserve the voice and the final line"},
        inputs=[ref("script", script.get("script_id"), revision=script.get("revision")),
                ref("slot", slot["slot_id"])],
        parameters={"format": slot.get("format"), "platform_targets": platforms,
                    "format_spec": format_spec or {},
                    "final_line": script.get("final_line"),
                    "delivery_notes": script.get("delivery_notes"),
                    "structure": list((script.get("structure") or {}).keys())},
        constraints=["match_format_specs", "preserve_final_line", "voice_ar_ps"],
        acceptance_criteria=["raw_cuts_uploaded", "matches_script", "format_spec_met"],
        context={"pillar": slot["pillar_code"], "hcs_id": script.get("hcs_id"),
                 "script_revision": script.get("revision"), "flags": flags})


def production_to_media(slot, script, raw_assets, format_spec, cfg):
    """The directive PRODUCTION emits for MEDIA-EDIT: edit these raw cuts into the post. Emitted
    at production_review approval. Inputs reference the raw_cut assets (DAM). Manual today
    (executor=human editor); AVP plugs into the media_edit generator slot via the same contract."""
    platforms = (cfg.get("distribution", {}) or {}).get("platforms") or []
    return make(
        "media_directive", "production", "media_edit",
        intent={"ar": "حرِّر اللقطات الخام إلى منشور نهائي مع الالتزام بالنص والإيقاع",
                "en": "Edit the raw cuts into the finished post; stay faithful to the script & pacing"},
        inputs=[ref("asset", a["asset_id"], asset_kind=a.get("kind"), version=a.get("version"))
                for a in (raw_assets or [])] + [ref("slot", slot["slot_id"])],
        parameters={"format": slot.get("format"), "platform_targets": platforms,
                    "format_spec": format_spec or {},
                    "final_line": (script or {}).get("final_line"),
                    "delivery_notes": (script or {}).get("delivery_notes"),
                    "raw_cut_count": len(raw_assets or [])},
        constraints=["match_script", "preserve_final_line", "platform_safe_margins"],
        acceptance_criteria=["edit_uploaded", "matches_script", "format_spec_met"],
        context={"pillar": slot["pillar_code"], "hcs_id": slot.get("hcs_id"),
                 "raw_assets": [str(a["asset_id"]) for a in (raw_assets or [])]})


def media_to_distribution(slot, edit_assets, format_spec, cfg):
    """The directive MEDIA-EDIT emits for DISTRIBUTION: format per platform + schedule. Emitted
    at edit_review approval. POSTIZ plugs into the distribution executor slot via this contract."""
    platforms = (cfg.get("distribution", {}) or {}).get("platforms") or []
    post_times = (cfg.get("distribution", {}) or {}).get("post_times") or []
    return make(
        "distribution_directive", "media_edit", "distribution",
        intent={"ar": "نسِّق المنشور لكل منصّة وجدول نشره ضمن النوافذ المعتمدة",
                "en": "Format the post per platform and schedule it within the approved windows"},
        inputs=[ref("asset", a["asset_id"], asset_kind=a.get("kind"),
                    platform_variant=a.get("platform_variant"))
                for a in (edit_assets or [])] + [ref("slot", slot["slot_id"])],
        parameters={"platform_targets": platforms, "post_times": post_times,
                    "format": slot.get("format"), "format_spec": format_spec or {}},
        constraints=["platform_specs", "approved_schedule_window", "nothing_publishes_without_gate"],
        acceptance_criteria=["formatted_per_platform", "scheduled", "publish_gate_passed"],
        context={"pillar": slot["pillar_code"], "hcs_id": slot.get("hcs_id"),
                 "edit_assets": [str(a["asset_id"]) for a in (edit_assets or [])]})


# --------------------------------------------------------------------------- #
# Persistence + provenance
# --------------------------------------------------------------------------- #
def record(cur, slot_id, pkg, *, revision=1, actor="system", actor_kind="agent",
           tenant_id="default", module="content"):
    """Persist a directive + write a `directive_emitted` event (the handoff IS memory).
    `cur` is a live cursor inside the caller's transaction — the caller commits."""
    validate(pkg)
    cur.execute(
        """INSERT INTO directive (slot_id, schema_version, type, from_stage, to_stage,
                                  payload, revision, produced_by, tenant_id, module)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING directive_id""",
        (slot_id, pkg["schema_version"], pkg["type"], pkg["from_stage"], pkg["to_stage"],
         Json(pkg), revision, actor, tenant_id, module))
    row = cur.fetchone()
    directive_id = row["directive_id"] if isinstance(row, dict) else row[0]
    cur.execute(
        "INSERT INTO audit_log (entity, entity_id, action, actor, actor_kind, detail) "
        "VALUES ('slot',%s,'directive_emitted',%s,%s,%s)",
        (slot_id, actor, actor_kind,
         Json({"directive_id": str(directive_id), "type": pkg["type"],
               "from_stage": pkg["from_stage"], "to_stage": pkg["to_stage"],
               "revision": revision})))
    return directive_id


def latest(cur, slot_id, to_stage):
    """The most recent directive FEEDING `to_stage` for this slot (what the stage must satisfy)."""
    cur.execute("SELECT * FROM directive WHERE slot_id=%s AND to_stage=%s "
                "ORDER BY revision DESC, created_at DESC LIMIT 1", (slot_id, to_stage))
    return cur.fetchone()


def chain(cur, slot_id):
    """The full directive chain for a slot (provenance/lineage), oldest first."""
    cur.execute("SELECT * FROM directive WHERE slot_id=%s ORDER BY created_at", (slot_id,))
    return cur.fetchall()


# --------------------------------------------------------------------------- #
# Spine hook — emit a stage's OUTPUT directive when its gate approves
# --------------------------------------------------------------------------- #
def _one(cur, sql, params):
    cur.execute(sql, params)
    return cur.fetchone()


def _approved_rev(cur, slot_id, artifact):
    """The pinned approved revision for an artifact (the downstream directive carries THIS), else
    the head. Keeps directives.py engine-free by reading slot_approval directly."""
    cur.execute("SELECT revision FROM slot_approval WHERE slot_id=%s AND artifact=%s",
                (slot_id, artifact))
    r = cur.fetchone()
    if r:
        return r["revision"] if isinstance(r, dict) else r[0]
    tbl = "topic" if artifact == "topic" else "script"
    r = _one(cur, f"SELECT coalesce(max(revision),1) AS r FROM {tbl} WHERE slot_id=%s", (slot_id,))
    return r["r"] if isinstance(r, dict) else r[0]


def _revision_row(cur, table, slot_id, revision):
    """The exact revision row, falling back to the head if that revision is missing."""
    row = _one(cur, f"SELECT * FROM {table} WHERE slot_id=%s AND revision=%s LIMIT 1",
               (slot_id, revision))
    return row or _one(cur, f"SELECT * FROM {table} WHERE slot_id=%s "
                            "ORDER BY revision DESC, created_at DESC LIMIT 1", (slot_id,))


def emit_output(cur, slot_id, stage, cfg, *, actor="system", actor_kind="agent"):
    """Build + record the OUTPUT directive of `stage` (= the input directive the NEXT stage
    consumes) from current DB state. Dispatch is a tiny explicit registry, not a DSL.
    Returns directive_id, or None if the stage emits nothing wired yet."""
    contract = stages(cfg).get(stage) or {}
    if not contract.get("emits"):
        return None
    slot = _one(cur, "SELECT * FROM slot WHERE slot_id=%s", (slot_id,))
    if not slot:
        return None
    hcs = _one(cur, "SELECT * FROM hcs WHERE hcs_id=%s", (slot["hcs_id"],))
    lens = _one(cur, "SELECT * FROM lens WHERE lens_id=%s", (slot["lens"],))
    format_spec = _one(cur, "SELECT * FROM format WHERE name=%s", (slot["format"],))
    if stage == "topic":
        topic = _revision_row(cur, "topic", slot_id, _approved_rev(cur, slot_id, "topic"))
        if not topic:
            return None
        pkg = topic_to_script(slot, topic, hcs, lens, cfg)   # the APPROVED topic revision
        rev = topic.get("revision", 1)
    elif stage == "script":
        script = _revision_row(cur, "script", slot_id, _approved_rev(cur, slot_id, "script"))
        if not script:
            return None
        pkg = script_to_production(slot, script, format_spec, cfg)         # the APPROVED script revision
        rev = script.get("revision", 1)
    elif stage == "production":
        # the editor needs the script context + the raw cuts the producer uploaded (DAM)
        script = _one(cur, "SELECT * FROM script WHERE slot_id=%s "
                           "ORDER BY revision DESC, created_at DESC LIMIT 1", (slot_id,))
        raw = dam.list_assets(cur, slot_id, stage="production", kind="raw_cut")
        pkg = production_to_media(slot, script, raw, format_spec, cfg)
        rev = 1
    elif stage == "media_edit":
        edits = dam.list_assets(cur, slot_id, stage="media_edit", kind="edit")
        pkg = media_to_distribution(slot, edits, format_spec, cfg)
        rev = 1
    else:
        return None
    return record(cur, slot_id, pkg, revision=rev, actor=actor, actor_kind=actor_kind,
                  tenant_id=slot.get("tenant_id", "default"),
                  module=slot.get("module", "content"))
