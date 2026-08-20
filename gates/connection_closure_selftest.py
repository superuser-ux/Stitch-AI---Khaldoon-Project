"""#357 — discriminating proof that the Scripts branch closes every connection it opens.

WHY THIS EXISTS RATHER THAN A CONNECTION-COUNT PROBE. The obvious check — hammer the refused paths
and watch `pg_stat_activity` — does NOT discriminate: CPython refcounting closes an orphaned
psycopg2 connection the moment its last reference dies, so the leaked and fixed versions both read
zero. Measured, not assumed. A probe that cannot fail on the broken code proves nothing about the
fixed code.

This inspects the connection OBJECTS instead: it wraps `_conn`, drives the two refusal paths, and
asserts `connection.closed` on every one it handed out. Reinstating either leak makes it fail
(TOTAL LEAKED: 1), which is what makes the passing result meaningful.

    docker exec -e PYTHONPATH=/work:/work/gates -e REVIEWER_PROXY_SECRET=... \
      <lane-api> python -m gates.connection_closure_selftest
"""
import sys
sys.path.insert(0, "/work"); sys.path.insert(0, "/work/gates")
import api as gapi
import engine
from starlette.requests import Request
from fastapi import HTTPException


def _round_with_eligible_input():
    """A round whose items sit at the Script input status. REQUIRED: without eligible input the
    non-approver call short-circuits on `no_eligible_input` (409) and never reaches the authorization
    denial — so the test would exercise the wrong path and prove nothing about it."""
    cfg = engine.load_config()
    src = engine.stage_cfg(cfg, "script_review").get("generates_from")
    conn = engine.db_connect(); cur = conn.cursor()
    cur.execute("SELECT round_id FROM slot WHERE status=%s GROUP BY round_id "
                "ORDER BY count(*) DESC LIMIT 1", (src,))
    row = cur.fetchone(); cur.close(); conn.close()
    return row[0] if row else None

opened = []
_orig = gapi._conn
def tracking():
    c = _orig(); opened.append(c); return c
gapi._conn = tracking

def req(headers=None):
    hs = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "http_version": "1.1", "method": "POST",
                    "path": "/", "raw_path": b"/", "query_string": b"",
                    "headers": hs, "client": ("127.0.0.1", 0), "server": ("127.0.0.1", 8357),
                    "scheme": "http"})

ROUND = _round_with_eligible_input()
if not ROUND:
    print("  NO ELIGIBLE INPUT — cannot exercise the authorization path; refusing to report a pass")
    sys.exit(2)
print(f"  round under test: {ROUND}")

# 1. UNSIGNED — exercises the audit-denial path
opened.clear()
try:
    gapi.generate(ROUND, "script_review", req())
except HTTPException as e:
    print(f"  unsigned      -> HTTP {e.status_code}")
except Exception as e:
    print(f"  unsigned      -> {type(e).__name__}: {e}")
leaked = [c for c in opened if not c.closed]
print(f"    connections opened={len(opened)} leaked={len(leaked)}")

# 2. NON-APPROVER — exercises create_script_generation_attempt
import hmac, hashlib, os
sec = os.environ["REVIEWER_PROXY_SECRET"]
sig = hmac.new(sec.encode(), b"not-an-approver", hashlib.sha256).hexdigest()
opened.clear()
try:
    gapi.generate(ROUND, "script_review", req({"x-principal-id": "not-an-approver",
                                               "x-principal-signature": sig}))
except HTTPException as e:
    print(f"  non-approver  -> HTTP {e.status_code}")
    if e.status_code != 403 or "principal_not_approver" not in str(e.detail):
        print(f"    WRONG PATH: expected 403 principal_not_approver, got {e.status_code} {e.detail}")
        sys.exit(1)
except Exception as e:
    print(f"  non-approver  -> {type(e).__name__}: {e}")
leaked2 = [c for c in opened if not c.closed]
print(f"    connections opened={len(opened)} leaked={len(leaked2)}")

total = len(leaked) + len(leaked2)
print(f"\n  TOTAL LEAKED: {total}  -> {'PASS' if total == 0 else 'FAIL'}")
sys.exit(1 if total else 0)
