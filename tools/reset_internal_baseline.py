#!/usr/bin/env python3
"""Restore the internal Tanaghom workspace to the seeded baseline.

This is intentionally destructive for operational/demo data. Use it after
heavy self-tests or exploratory admin changes when you want the methodology,
workflow, content-type registry, runtime catalogues, and planned rounds back
to the canonical repo-backed seed state.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2

REPO = Path(__file__).resolve().parent.parent
for path in (REPO, REPO / "gates", REPO / "agents"):
    raw = str(path)
    if raw not in sys.path:
        sys.path.insert(0, raw)

from gates import engine
from loader import load_methodology


def connect():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        port=int(os.environ.get("DB_PORT", "5432")),
        dbname=os.environ.get("DB_NAME", "tanaghom"),
        user=os.environ.get("DB_USER", "tanaghom"),
        password=os.environ["DB_PASSWORD"],
    )


def wipe_operational_state(conn):
    cur = conn.cursor()
    try:
        cur.execute(
            "TRUNCATE TABLE gate_decision, gate_assignment, gate_target, gate, asset, directive, "
            "slot_approval, slot_review, script, topic, slot, round RESTART IDENTITY CASCADE"
        )
        cur.execute("DELETE FROM lens_history")
        cur.execute("DELETE FROM hcs_cursor")
        cur.execute(
            """DELETE FROM audit_log
               WHERE entity IN (
                   'slot', 'round', 'gate', 'content_format', 'content_format_version',
                   'methodology', 'methodology_version', 'workflow', 'workflow_version'
               )"""
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def wipe_admin_catalogues(conn):
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM workflow_transition")
        cur.execute("DELETE FROM workflow_stage")
        cur.execute("DELETE FROM workflow_version WHERE tenant_id='default' AND module='content'")
        cur.execute("DELETE FROM workflow WHERE tenant_id='default' AND module='content'")

        cur.execute("DELETE FROM methodology_hcs")
        cur.execute("DELETE FROM methodology_hook_type")
        cur.execute("DELETE FROM methodology_lens")
        cur.execute("DELETE FROM methodology_pillar")
        cur.execute("DELETE FROM methodology_version WHERE tenant_id='default' AND module='content'")
        cur.execute("DELETE FROM methodology WHERE tenant_id='default' AND module='content'")

        cur.execute("DELETE FROM format")
        cur.execute("DELETE FROM content_format WHERE tenant_id='default' AND module='content'")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def reseed(conn, actor: str = "loader"):
    payload = load_methodology.build_payload()

    cur = conn.cursor()
    try:
        load_methodology.upsert_runtime_tables(cur, payload)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()

    load_methodology.sync_versioned_seed(conn, payload=payload, actor=actor)
    load_methodology.bootstrap_content_formats(conn, actor=actor, reset=True)
    engine._ensure_workflow_seed(conn, cfg=engine.load_config(), actor=actor)


def print_summary(conn):
    cur = conn.cursor()
    try:
        counts = {}
        for table in (
            "methodology_version",
            "content_format",
            "workflow_version",
            "round",
            "slot",
            "format",
        ):
            cur.execute(f"SELECT count(*) FROM {table}")
            counts[table] = cur.fetchone()[0]
        print("Baseline restored:")
        for table, count in counts.items():
            print(f"  {table}: {count}")
    finally:
        cur.close()


def main():
    conn = connect()
    conn.autocommit = False
    try:
        wipe_operational_state(conn)
        wipe_admin_catalogues(conn)
        reseed(conn)
        print_summary(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
