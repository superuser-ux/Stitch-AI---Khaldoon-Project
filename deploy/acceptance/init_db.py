"""#338 — acceptance init orchestrator (runs inside the gateapi container startup, fail-fast, BEFORE
uvicorn). It ONLY applies EXISTING committed initialization, unchanged; it adds no schema, migration,
seed, authority, or configuration logic, authors no SQL of its own, and writes NO new state into
PostgreSQL (it only READS the cluster identity via the built-in pg_control_system()).

Fresh-acceptance / CONTAINER-LOCAL ownership contract (Codex review P1.1, re-review 2):
  The acceptance topology runs on a FRESH synthetic database and this orchestrator keeps Postgres free of
  any new marker/schema/config state. Ownership is proven by a CONTAINER-LOCAL marker file that lives in
  the gateapi container's writable layer (NOT a volume, NOT the DB): it survives a same-container restart
  but is lost when the container is recreated. The marker binds two things: the COMPLETE committed
  initialization manifest (schema + every migration, by name + content sha256) and the DATABASE IDENTITY
  (the cluster's system_identifier).

  On startup, over the committed files only:
    * EMPTY database (no base schema): apply the committed schema, then every migration in ascending order
      (verbatim, fail-fast); on success, write the container-local marker = (manifest, db_identity).
    * NON-EMPTY database WITH a container-local marker whose manifest == the current committed manifest AND
      whose db_identity == the current cluster identity: this is the SAME container restarting against the
      SAME database it initialized — known-owned — proceed without re-applying (some committed migrations
      are intentionally non-idempotent, e.g. 023's bare CREATE TABLE).
    * NON-EMPTY database with NO local marker (recreated container), or a marker whose manifest or
      db_identity does not match: UNRECOGNIZED — FAIL CLOSED. The API never serves; the operator must run
      the documented teardown (compose down -v) and recreate with a fresh volume.

  Then run the committed catalogue loader and the committed synthetic seed (both idempotent).
"""
import glob
import hashlib
import os
import subprocess
import sys

import psycopg2

# /work/deploy/acceptance/init_db.py -> /work
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCHEMA = os.path.join(REPO, "db", "init", "schema.sql")
MIGRATIONS_GLOB = os.path.join(REPO, "db", "migrations", "*.sql")
# Container-local (writable-layer, non-volume) marker — lost on container recreation by design.
MARKER_PATH = "/var/lib/tanaghom-acc/init-marker"


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
            print("[init] fresh initialization complete; container-local ownership marker written", flush=True)
        else:
            marker = _read_marker()
            if marker and marker["manifest"] == manifest and marker["db_identity"] == db_identity:
                print("[init] known-owned same-container restart against the same database — proceeding", flush=True)
            else:
                raise RuntimeError(
                    "unrecognized non-empty database: no matching container-local ownership marker "
                    "(recreated container, different database identity, or manifest drift). The acceptance "
                    "lane requires a fresh synthetic database — run the documented teardown (compose down "
                    "-v) and recreate with a fresh volume. Refusing to serve."
                )
        cur.close()
    finally:
        conn.close()


def _run(script_rel):
    path = os.path.join(REPO, script_rel)
    print(f"[init] running {script_rel}", flush=True)
    subprocess.run([sys.executable, path], check=True, env=dict(os.environ))


def main():
    _apply_schema_and_migrations()
    _run(os.path.join("loader", "load_methodology.py"))   # existing catalogue init, unchanged
    _run(os.path.join("gates", "e2e_seed.py"))            # existing synthetic seed, unchanged
    print("[init] governed initialization complete", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # fail-fast: never serve against a half-initialized / unrecognized DB
        print(f"[init] FATAL: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
