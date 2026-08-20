"""Gate CLI (M4) — ops + verification surface over the gate engine.

All real logic is in engine.py (shared with the dashboard API and the Telegram bot).

Examples (inside the repo, DB up):
  python gates/cli.py open  --stage script_review --round R1
  python gates/cli.py list
  python gates/cli.py show  <gate_id>
  python gates/cli.py decide <gate_id> --approver khal --decision approve            # whole batch
  python gates/cli.py decide <gate_id> --approver khal --decision request_change \\
                              --slots R1-D11-PM --notes "fix the anchor"
  python gates/cli.py resolve <gate_id>
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))  # same-dir import of engine
import engine  # noqa: E402


def _p(s, n=70):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def cmd_open(args):
    conn = engine.db_connect()
    gid = engine.open_gate(conn, args.stage,
                           slot_ids=args.slots.split(",") if args.slots else None,
                           round_id=args.round, actor=args.actor)
    g = engine.get_gate(conn, gid)
    print(f"opened gate {gid}  stage={args.stage}  quorum={g['quorum']}  "
          f"targets={len(g['targets'])}")
    conn.close()


def cmd_list(args):
    conn = engine.db_connect()
    for g in engine.list_gates(conn, status=args.status):
        print(f"  {g['gate_id']}  {g['status']:<17} {g['stage']:<14} "
              f"targets={g['targets']:<3} quorum={g['quorum']}  {g['created_at']:%Y-%m-%d %H:%M}")
    conn.close()


def cmd_show(args):
    conn = engine.db_connect()
    g = engine.get_gate(conn, args.gate_id)
    print(f"GATE {g['gate_id']}  stage={g['stage']}  status={g['status']}  "
          f"quorum={g['quorum']}  policy={g['policy']}")
    print(f"{'slot':<13} {'pillar':<17} {'slot_status':<18} flags / hook")
    print("-" * 96)
    for t in g["targets"]:
        flags = t["flags"] if isinstance(t["flags"], list) else (t["flags"] or [])
        dec = " ".join(f"{d['approver_id']}:{d['decision']}" for d in t["decisions"])
        print(f"{t['slot_id']:<13} {t['pillar_code']:<17} {t['slot_status']:<18} "
              f"{','.join(flags) or '-'}")
        print(f"              «{_p(t['hook_text'])}»   {('['+dec+']') if dec else ''}")
    conn.close()


def cmd_decide(args):
    conn = engine.db_connect()
    touched = engine.decide(conn, args.gate_id, args.approver, args.decision,
                            slot_ids=args.slots.split(",") if args.slots else None,
                            notes=args.notes)
    print(f"{args.approver} {args.decision} -> {len(touched)} slot(s): {', '.join(touched)}")
    conn.close()


def cmd_resolve(args):
    conn = engine.db_connect()
    outcomes = engine.resolve(conn, args.gate_id, actor=args.actor)
    tally = {}
    for o in outcomes.values():
        tally[o] = tally.get(o, 0) + 1
    print(f"resolved gate {args.gate_id}: " + "  ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    for s, o in sorted(outcomes.items()):
        if o != "approved":
            print(f"  {s}: {o}")
    conn.close()


def cmd_dispose(args):
    conn = engine.db_connect()
    engine.dispose_review(conn, args.slot_id, args.review, args.action,
                          reason=args.reason, actor=args.actor)
    blockers = engine.publish_blockers(conn, args.slot_id)
    print(f"{args.actor} {args.action} {args.review} review on {args.slot_id} -> "
          f"publish blockers now: {blockers or 'none'}")
    conn.close()


def main():
    ap = argparse.ArgumentParser(description="Tanaghom gate CLI (M4)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("open"); o.set_defaults(fn=cmd_open)
    o.add_argument("--stage", default="script_review")
    o.add_argument("--round", default=None)
    o.add_argument("--slots", default=None, help="comma-separated slot ids")
    o.add_argument("--actor", default="cli")

    l = sub.add_parser("list"); l.set_defaults(fn=cmd_list)
    l.add_argument("--status", default=None)

    s = sub.add_parser("show"); s.set_defaults(fn=cmd_show)
    s.add_argument("gate_id")

    d = sub.add_parser("decide"); d.set_defaults(fn=cmd_decide)
    d.add_argument("gate_id")
    d.add_argument("--approver", required=True)
    d.add_argument("--decision", required=True, choices=engine.DECISIONS)
    d.add_argument("--slots", default=None, help="comma-separated; omit = whole batch")
    d.add_argument("--notes", default=None)

    r = sub.add_parser("resolve"); r.set_defaults(fn=cmd_resolve)
    r.add_argument("gate_id")
    r.add_argument("--actor", default="cli")

    dp = sub.add_parser("dispose", help="escalate/waive a suggested review on a slot")
    dp.set_defaults(fn=cmd_dispose)
    dp.add_argument("slot_id")
    dp.add_argument("--review", required=True, help="native | religious")
    dp.add_argument("--action", required=True, choices=["escalate", "waive"])
    dp.add_argument("--reason", default=None, help="required for a waiver")
    dp.add_argument("--actor", default="khal")

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
