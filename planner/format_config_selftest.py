"""#87 — prove the content-format fallback is SAFE.

Asserts that (1) the static `system_config.yaml` fallback `format_distribution_weekly` references only
real operational `content_format`/`format` names (never a CANON-only name that doesn't exist as a stored
row), and (2) the planner's resolved distribution (`apply_managed_format_distribution`, which lets managed
content-type weights override the static config in the normal path) also emits only real operational
format names. This guards the drift #85/#87 fixed: the config used to list CANON-014's 7 source names,
of which 3 had no stored format, so the fallback path could emit nonexistent formats.

Run (container on the tanaghom network):
  docker exec -w /work tanaghom-gateapi python planner/format_config_selftest.py
"""
import os
import sys

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gates"))
sys.path.insert(0, os.path.dirname(__file__))
import engine        # noqa: E402  (load_config)
import plan_round    # noqa: E402  (apply_managed_format_distribution)

OPERATIONAL = {"Hero Reel", "Carousel", "Pic + Caption", "3sec Reel + Caption"}
CANON_ONLY = {"Reel — Studio", "Reel — iPhone", "Reel — Podcast", "Reel — Event Cut"}
FAILS = []


def check(label, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(label)


def _db():
    return psycopg2.connect(host=os.environ.get("DB_HOST", "db"), port=int(os.environ.get("DB_PORT", "5432")),
                            dbname=os.environ.get("DB_NAME", "tanaghom"), user=os.environ.get("DB_USER", "tanaghom"),
                            password=os.environ.get("DB_PASSWORD", os.environ.get("POSTGRES_PASSWORD", "changeme")))


def main():
    cfg = engine.load_config()
    tmpl = cfg["calendar"]["templates"][cfg["calendar"]["default_template"]]
    fallback = tmpl["format_distribution_weekly"]

    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT name FROM content_format WHERE active AND coalesce(lifecycle_status,'active')='active'")
    known = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT name FROM format")
    known |= {r[0] for r in cur.fetchall()}

    print("1) static fallback references only real operational formats")
    unknown = [f for f in fallback if f not in known]
    check("no nonexistent format names in fallback", not unknown, f"unknown={unknown}")
    check("fallback uses the 4-format operational model", set(fallback) <= OPERATIONAL, str(sorted(fallback)))
    check("no CANON-only reel-variant names leak into fallback", not (set(fallback) & CANON_ONLY),
          str(set(fallback) & CANON_ONLY))
    check("fallback weekly total preserved (= posts_per_day*7 = 14)", sum(fallback.values()) == tmpl["posts_per_day"] * 7,
          f"sum={sum(fallback.values())}")

    print("2) the planner's resolved distribution (managed override applied) emits only real formats")
    cur2 = conn.cursor()
    resolved = plan_round.apply_managed_format_distribution(cur2, dict(tmpl))["format_distribution_weekly"]
    bad = [f for f in resolved if f not in known]
    check("planner-resolved distribution references only real formats", not bad, f"bad={bad}")
    check("planner-resolved distribution stays within the operational model", set(resolved) <= OPERATIONAL,
          str(sorted(resolved)))

    print("3) no managed weekly_count is an outlier (#89 — guards test-pollution like weekly_count=99)")
    slots_per_week = tmpl["posts_per_day"] * 7
    cur3 = conn.cursor()
    cur3.execute(
        """SELECT f.name, (v.production_rules->'planning'->>'weekly_count')::int
           FROM content_format f JOIN content_format_version v ON v.content_format_id=f.content_format_id
           WHERE f.active AND coalesce(f.lifecycle_status,'active')='active' AND v.status='active'"""
    )
    managed_counts = {name: wc for name, wc in cur3.fetchall() if wc is not None}
    outliers = {n: wc for n, wc in managed_counts.items() if wc > slots_per_week}
    check("no active managed weekly_count exceeds the weekly slot total", not outliers,
          f"slots/week={slots_per_week} outliers={outliers}")
    # the resolved plan must not be dominated by a single format because of a skewed weight
    if resolved:
        top = max(resolved.values())
        check("planner-resolved distribution is not skewed to one format (< all slots)", top < sum(resolved.values()),
              f"max={top} total={sum(resolved.values())}")

    conn.close()
    print("=" * 50)
    if FAILS:
        print(f"FORMAT CONFIG SELFTEST FAILED — {len(FAILS)} check(s): {FAILS}")
        sys.exit(1)
    print("ALL FORMAT CONFIG CHECKS PASSED")


if __name__ == "__main__":
    main()
