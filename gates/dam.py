"""Minimal DAM (M9 · Block B2) — store/reference raw + edited media for the manual stages.

A pure module (no engine/directives dependency, so the spine and directives can import it without
a cycle). It REFERENCES media via a uri (path / URL / external store) — never stores binaries in
Postgres. Assets are versioned per (slot, stage, kind, platform_variant); a new version supersedes
the prior active one (history kept). Every write is audited (`asset_added`).

  list_assets(cur, ...)  — cursor-based read (composes inside a caller's transaction; no commit)
  add_asset(conn, ...)   — conn-based write (commits + audits) for the surfaces (API/CLI/selftest)
"""
import psycopg2.extras
from psycopg2.extras import Json


def list_assets(cur, slot_id, stage=None, kind=None, platform_variant=None, active_only=True):
    """Active DAM assets for a slot, optionally filtered (oldest first). Cursor-based — the
    caller owns the transaction (used by both surfaces and directive builders)."""
    q = "SELECT * FROM asset WHERE slot_id=%s"
    params = [slot_id]
    if active_only:
        q += " AND status='active'"
    if stage:
        q += " AND stage=%s"; params.append(stage)
    if kind:
        q += " AND kind=%s"; params.append(kind)
    if platform_variant is not None:
        q += " AND platform_variant=%s"; params.append(platform_variant)
    q += " ORDER BY created_at"
    cur.execute(q, params)
    return cur.fetchall()


def _principal_kind(cur, actor):
    cur.execute("SELECT kind FROM principal WHERE principal_id=%s", (actor,))
    r = cur.fetchone()
    return (r["kind"] if isinstance(r, dict) else r[0]) if r else "user"


def add_asset(conn, slot_id, stage, kind, uri=None, storage="reference", platform_variant=None,
              meta=None, actor="system"):
    """Register an asset (a reference to media — no binary in DB). Auto-increments the version
    of THIS (slot, stage, kind, platform_variant) and supersedes the prior active one (history
    kept). Audited (`asset_added`). Returns asset_id."""
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT COALESCE(max(version),0)+1 AS v FROM asset WHERE slot_id=%s AND stage=%s "
                "AND kind=%s AND platform_variant IS NOT DISTINCT FROM %s",
                (slot_id, stage, kind, platform_variant))
    version = cur.fetchone()["v"]
    cur.execute("UPDATE asset SET status='superseded' WHERE slot_id=%s AND stage=%s AND kind=%s "
                "AND platform_variant IS NOT DISTINCT FROM %s AND status='active'",
                (slot_id, stage, kind, platform_variant))
    cur.execute(
        "INSERT INTO asset (slot_id, stage, kind, uri, storage, version, platform_variant, "
        "meta, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING asset_id",
        (slot_id, stage, kind, uri, storage, version, platform_variant, Json(meta or {}), actor))
    asset_id = cur.fetchone()["asset_id"]
    cur.execute(
        "INSERT INTO audit_log (entity, entity_id, action, actor, actor_kind, detail) "
        "VALUES ('slot',%s,'asset_added',%s,%s,%s)",
        (slot_id, actor, _principal_kind(cur, actor),
         Json({"asset_id": str(asset_id), "stage": stage, "kind": kind, "version": version,
               "platform_variant": platform_variant, "uri": uri})))
    conn.commit()
    cur.close()
    return asset_id
