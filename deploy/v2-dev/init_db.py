"""#389 — v2-dev init orchestrator (runs inside the gateapi container startup, fail-fast, AFTER the
runtime-SHA guard and BEFORE uvicorn). It ONLY applies EXISTING committed initialization, unchanged; it
adds no schema, migration, seed, authority, or configuration logic, authors no SQL of its own, and writes
NO new state into PostgreSQL (it only READS the cluster identity via the built-in pg_control_system()).
This is a byte-faithful sibling of deploy/acceptance/init_db.py; only the module identity and the
container-local marker path differ, so the v2-dev lane owns a distinct marker and never collides with the
local acceptance lane.

Fresh / CANDIDATE-LOCAL ownership contract:
  The v2-dev topology runs on a FRESH synthetic database and this orchestrator keeps Postgres free of any
  new marker/schema/config state. Ownership is proven by a CANDIDATE-LOCAL marker file stored outside
  PostgreSQL. The deployed topology mounts a dedicated candidate-owned volume so it survives gate image
  recreation. The marker binds two things: the COMPLETE committed
  initialization manifest (schema + every migration, by name + content sha256) and the DATABASE IDENTITY
  (the cluster's system_identifier).

  On startup, over the committed files only:
    * EMPTY database (no base schema): apply the committed schema, then every migration in ascending order
      (verbatim, fail-fast); on success, write the candidate-local marker = (manifest, db_identity).
    * NON-EMPTY database WITH a candidate-local marker whose manifest == the current committed manifest AND
      whose db_identity == the current cluster identity: this is the SAME candidate database previously
      initialized by this lane — known-owned — proceed without re-applying (some committed migrations
      are intentionally non-idempotent, e.g. 023's bare CREATE TABLE).
    * NON-EMPTY database with NO local marker, or a marker whose manifest or
      db_identity does not match: UNRECOGNIZED — FAIL CLOSED. The API never serves; the operator must run
      the documented candidate-only teardown and recreate with a fresh volume.

  #414 — ORDINARY STARTUP IS READ-ONLY. This startup path performs schema/ownership verification ONLY.
  It NO LONGER runs the methodology catalogue loader, the synthetic fixture seed, or open_gate, so a
  normal restart/recreate against an already-initialized database writes ZERO rows (including zero
  audit_log rows) and leaves the persisted-data fingerprint byte-identical. A genuinely fresh/empty
  database still gets its committed schema + migrations + ownership marker here (structural, one-time),
  but never fixtures or catalogue data. Synthetic developer fixtures (methodology catalogue + the RE2E
  fixture round) are now initialized EXPLICITLY, idempotently, and only for the synthetic `v2-dev-389`
  lane via deploy/v2-dev/init_fixtures.py — a deliberate, evidenced, create-missing-only operation.
"""
import glob
import hashlib
import os
import sys

import psycopg2

# /work/deploy/v2-dev/init_db.py -> /work
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA = os.path.join(REPO, "db", "init", "schema.sql")
MIGRATIONS_GLOB = os.path.join(REPO, "db", "migrations", "*.sql")
# Candidate-local marker. The deployed v2-dev topology points this at its dedicated named volume so
# routine gate recreation preserves the proof; the writable default stays distinct for isolated tests.
MARKER_PATH = os.environ.get("TANAGHOM_V2DEV_INIT_MARKER", "/work/.tanaghom-v2-dev-init-marker")


def _connect():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "tanaghom"),
        user=os.environ.get("DB_USER", "tanaghom"),
        password=os.environ["DB_PASSWORD"],
    )


def _committed_manifest():
    """Hash over the COMPLETE committed initialization artifact set (schema + every migration), each by
    basename + content sha256. Any missing/added/edited file changes this value."""
    parts = []
    for path in [SCHEMA, *sorted(glob.glob(MIGRATIONS_GLOB))]:
        with open(path, "rb") as fh:
            parts.append(f"{os.path.basename(path)}:{hashlib.sha256(fh.read()).hexdigest()}")
    return hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()


def _db_identity(cur):
    # Read-only cluster identity — assigned at initdb, unique per database cluster. No state is written.
    cur.execute("SELECT system_identifier::text FROM pg_control_system()")
    return cur.fetchone()[0]


def _read_marker():
    try:
        with open(MARKER_PATH, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        if len(lines) >= 2 and lines[0] and lines[1]:
            return {"manifest": lines[0], "db_identity": lines[1]}
    except OSError:
        pass
    return None


def _write_marker(manifest, db_identity):
    os.makedirs(os.path.dirname(MARKER_PATH), exist_ok=True)
    tmp = MARKER_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(f"{manifest}\n{db_identity}\n")
    os.replace(tmp, MARKER_PATH)


def _apply_sql_file(cur, path):
    with open(path, "r", encoding="utf-8") as fh:
        cur.execute(fh.read())  # committed .sql is pure SQL (no psql meta-commands)


def _apply_schema_and_migrations():
    conn = _connect()
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT to_regclass('public.round')")
        has_base = cur.fetchone()[0] is not None
        db_identity = _db_identity(cur)
        manifest = _committed_manifest()

        if not has_base:
            print("[init] fresh database — applying committed schema + all migrations in order", flush=True)
            _apply_sql_file(cur, SCHEMA)
            for path in sorted(glob.glob(MIGRATIONS_GLOB)):
                print(f"[init] migration {os.path.basename(path)}", flush=True)
                _apply_sql_file(cur, path)
            _write_marker(manifest, db_identity)
            print("[init] fresh initialization complete; candidate-local ownership marker written", flush=True)
        else:
            marker = _read_marker()
            if marker and marker["manifest"] == manifest and marker["db_identity"] == db_identity:
                print("[init] known-owned candidate database — proceeding", flush=True)
            else:
                raise RuntimeError(
                    "unrecognized non-empty database: no matching candidate-local ownership marker "
                    "(different database identity or manifest drift). The v2-dev "
                    "lane requires a fresh synthetic database — run the documented candidate-only teardown "
                    "and recreate with a fresh volume. Refusing to serve."
                )
        cur.close()
    finally:
        conn.close()


def main():
    # #414 — schema/ownership verification ONLY. No catalogue loader, no fixture seed, no open_gate:
    # a known-owned database is verified read-only (zero writes, zero audit rows); a fresh database gets
    # its committed schema + migrations + ownership marker (structural, one-time). Synthetic fixtures are
    # a separate, explicit, idempotent, v2-dev-389-only step (deploy/v2-dev/init_fixtures.py).
    _apply_schema_and_migrations()
    print("[init] schema/ownership verified — ordinary startup is DB-read-only "
          "(no catalogue/fixture/gate writes; run init_fixtures.py explicitly to seed synthetic data)",
          flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # fail-fast: never serve against a half-initialized / unrecognized DB
        print(f"[init] FATAL: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
