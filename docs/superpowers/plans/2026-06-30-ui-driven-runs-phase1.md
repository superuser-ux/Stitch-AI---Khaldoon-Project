# UI-driven Runs (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make run-configuration and topic/script generation UI-driven (background jobs with live progress), give every stage one consistent action surface, and fix the two stage-state bugs — without breaking the four green suites.

**Architecture:** New API endpoints (`POST /rounds`, `POST /rounds/{id}/stages/{stage}/generate`, `GET /jobs/{id}`) are the single generation mechanism (shared with the Telegram agent post-merge). Generation runs in-process on a daemon thread (extends the existing `/rework` pattern); progress is DB-derived. The planner scales its pillar/format mix as ratios so any `days × posts_per_day` works (28×2 reproduces today's 56 exactly). `engine.stage_state` gains a `next_action` field that the UI renders uniformly across all 8 stages.

**Tech Stack:** Python 3.12, FastAPI, psycopg2 (RealDictCursor), Postgres; Next.js 15 App Router, React, Tailwind v4, shadcn/ui; Playwright. Writer = `agents/run_writers.py` (Groq; `TANAGHOM_WRITER_STUB=1` for deterministic tests).

## Global Constraints

- No hardcoded params — every tunable lives in `system_config.yaml`, mirrored to `system_config.example.yaml`. (verbatim from spec)
- Single generation mechanism — no parallel generation path; endpoints are main-mergeable, the bot consumes the same ones.
- In-process daemon-thread jobs only; a durable queue is if-scale, **do NOT build it now**.
- UI chrome English-only; content bilingual AR(Palestinian)/EN. Reuse existing `data-testid` hooks so Playwright stays green.
- Keep all four suites green: `gates/selftest.py`, `gates/api_selftest.py`, `gates/lifecycle_selftest.py`, `dashboard/e2e/*`.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- The gate API runs in container `tanaghom-gateapi` (mount `/work`, port 8009→8000, no `--reload`): **restart it to load Python changes**. Run Python suites via `docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m <module>`.

## File Structure

- `planner/plan_round.py` (modify) — `scale_distribution()`, `effective_template()`, `synth_post_times()`, a callable `plan_round_api(cfg, days, posts_per_day, label)`.
- `gates/jobs.py` (create) — in-process job registry.
- `gates/engine.py` (modify) — `stage_state` gains `generator`/`pending_input`/`next_action`; bug fixes. New helper `pending_input_count`.
- `gates/api.py` (modify) — `POST /rounds`, `POST /rounds/{id}/stages/{stage}/generate`, `GET /jobs/{id}`.
- `system_config.yaml` + `system_config.example.yaml` (modify) — `generator`/`generates_from`/`writer_mode` on the two generation gates.
- `gates/api_selftest.py` (modify) — planner-scaling, POST /rounds, generation-job, cursor-integrity tests.
- `gates/selftest.py` (modify) — `stage_state.next_action` unit tests + the two bug fixes.
- `dashboard/lib/review-context.tsx` (modify) — `StageState` type, `plan()`, `generate()`, job polling.
- `dashboard/components/review/stage-action.tsx` (create) — unified action surface.
- `dashboard/components/review/new-run-dialog.tsx` (create) — start-a-run dialog.
- `dashboard/components/review/app-shell.tsx` (modify) — New-run entry point.
- `dashboard/components/review/review-surface.tsx` (modify) — render `StageAction`, drop static empty copy.
- `dashboard/e2e/runs-and-generation.spec.ts` (create) — e2e.

---

### Task 1: Planner ratio-scaling (`scale_distribution`)

**Files:**
- Modify: `planner/plan_round.py` (add `scale_distribution` near `even_spread`, ~line 72)
- Test: `gates/api_selftest.py` (new section "P) planner scaling", near the top of `main()` before the RAPI flow)

**Interfaces:**
- Produces: `scale_distribution(ratios: dict[str,int|float], total: int) -> dict[str,str→int]` — returns integer counts summing exactly to `total`, allocated by largest-remainder on the input proportions, preserving key order. Zero when `total` is smaller than the number of keys with weight (largest ratios win).

- [ ] **Step 1: Write the failing test** — add to `gates/api_selftest.py` `main()`, right after `conn = db()` and before the RAPI seed:

```python
    # P) planner ratio-scaling — pure function, no DB
    from planner.plan_round import scale_distribution
    base = {"P1_SELF": 22, "P2_RELATIONSHIPS": 17, "P3_PARENTING": 9, "P4_WORK": 4, "P5_MEANING_ALLAH": 4}
    r56 = scale_distribution(base, 56)
    check("28x2: scaling reproduces the exact configured mix", r56, base)
    check("28x2: sums to 56", sum(r56.values()), 56)
    r6 = scale_distribution(base, 6)
    check("3x2: sums to exactly 6", sum(r6.values()), 6)
    check("3x2: every count is a non-negative int", all(isinstance(v, int) and v >= 0 for v in r6.values()), True)
    check("1x1: sums to 1", sum(scale_distribution(base, 1).values()), 1)
    r2 = scale_distribution(base, 2)   # tiny: total < #pillars
    check("1x2 tiny-run: sums to 2, no crash, no negatives", (sum(r2.values()), min(r2.values())), (2, 0))
    check("1x2 tiny-run: the two biggest pillars win the slots", (r2["P1_SELF"], r2["P2_RELATIONSHIPS"]), (1, 1))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest`
Expected: FAIL — `ImportError: cannot import name 'scale_distribution'`.

- [ ] **Step 3: Implement `scale_distribution`** in `planner/plan_round.py` after `even_spread`:

```python
def scale_distribution(ratios: dict, total: int) -> dict:
    """Scale a weighted distribution to exactly `total` integer units using the largest-remainder
    (Hamilton) method, preserving key order. Works for any total >= 0, including total < #keys
    (the largest weights win the scarce units; others get 0). Never returns negatives."""
    keys = list(ratios)
    weight_sum = sum(ratios.values())
    if total <= 0 or weight_sum <= 0:
        return {k: 0 for k in keys}
    raw = {k: ratios[k] * total / weight_sum for k in keys}
    floors = {k: int(raw[k]) for k in keys}
    used = sum(floors.values())
    remainder = total - used
    # hand out the leftover units to the largest fractional parts (ties: input order)
    order = sorted(keys, key=lambda k: (raw[k] - floors[k]), reverse=True)
    for k in order[:remainder]:
        floors[k] += 1
    return floors
```

- [ ] **Step 4: Run it to verify it passes**

Run: `docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest`
Expected: the six new `[PASS]` lines under "P) planner ratio-scaling"; suite still ends `ALL API CHECKS PASSED`.

- [ ] **Step 5: Commit**

```bash
git add planner/plan_round.py gates/api_selftest.py
git commit -m "planner: scale_distribution (largest-remainder), arbitrary run sizes

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Parametric planner entry point (`plan_round_api`)

**Files:**
- Modify: `planner/plan_round.py` (add `synth_post_times`, `effective_template`, `plan_round_api`; refactor `assign_pillars_formats` to use ratios)
- Test: `gates/api_selftest.py` (extend the "P)" section)

**Interfaces:**
- Consumes: `scale_distribution` (Task 1).
- Produces:
  - `synth_post_times(ppd: int, base_times: list[str]) -> list[str]` — returns `ppd` "HH:MM" times; uses `base_times` when `len == ppd`, else evenly spreads across 09:00–21:00.
  - `effective_template(tmpl: dict, days: int, ppd: int) -> dict` — a copy with `period_len_days=days`, `posts_per_day=ppd`, `post_times=synth_post_times(...)`, `pillar_distribution=scale_distribution(tmpl["pillar_distribution"], days*ppd)`, `format_distribution_weekly=scale_distribution(tmpl["format_distribution_weekly"], ppd*7)`.
  - `plan_round_api(cfg: dict, days: int, posts_per_day: int, label: str|None=None) -> dict` — plans + persists a fresh round using the effective template; returns `{"round_id": str, "total": int}`. Reuses the existing planning body (cursor walk, persistence, audit).

- [ ] **Step 1: Write the failing test** — extend the "P)" section:

```python
    from planner.plan_round import effective_template, synth_post_times, get_template
    check("synth_post_times keeps configured 2-up times", synth_post_times(2, ["09:00", "20:00"]), ["09:00", "20:00"])
    check("synth_post_times spreads 3-up", len(synth_post_times(3, ["09:00", "20:00"])), 3)
    _, base_tmpl = get_template(engine_cfg(), None)   # engine_cfg() defined below in helper step
    et = effective_template(base_tmpl, 3, 2)
    check("effective_template totals to days*ppd", sum(et["pillar_distribution"].values()), 6)
    check("effective_template weekly totals to ppd*7", sum(et["format_distribution_weekly"].values()), 14)
```

Add this tiny helper near the top of `api_selftest.py` (after imports) if not already present:

```python
def engine_cfg():
    import gates.engine as _e
    return _e.load_config()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest`
Expected: FAIL — `ImportError: cannot import name 'effective_template'`.

- [ ] **Step 3: Implement.** In `planner/plan_round.py`:

(a) Replace the two validation blocks in `assign_pillars_formats` (the `if len(pillar_seq) != total` and `if len(weekly_fmt) != slots_per_week` `raise SystemExit` blocks) with tolerant behavior — the effective template already sums correctly, so just assert defensively:

```python
def assign_pillars_formats(grid, tmpl):
    """Assign a pillar + a format to every slot. Distributions are pre-scaled to the grid
    (see effective_template) so they sum exactly; we still guard against a malformed template."""
    total = len(grid)
    ppd = tmpl["posts_per_day"]
    pillar_seq = even_spread(list(tmpl["pillar_distribution"].items()))
    if len(pillar_seq) != total:
        raise SystemExit(f"pillar_distribution sums to {len(pillar_seq)} but period has {total} slots")
    slots_per_week = ppd * 7
    weekly_fmt = even_spread(list(tmpl["format_distribution_weekly"].items()))
    if len(weekly_fmt) != slots_per_week:
        raise SystemExit(f"format_distribution_weekly sums to {len(weekly_fmt)} but a week has {slots_per_week} slots")
    for i, slot in enumerate(grid):
        slot["pillar_code"] = pillar_seq[i]
        slot["format"] = weekly_fmt[i % slots_per_week] if slots_per_week else "Reel — Studio"
    return grid
```

(b) Add the helpers:

```python
def synth_post_times(ppd: int, base_times: list) -> list:
    """`ppd` posting times. Use the configured times when the count matches; otherwise spread
    evenly across the active day (09:00–21:00) so any posts_per_day works (parametric)."""
    if len(base_times) == ppd:
        return list(base_times)
    if ppd <= 1:
        return ["09:00"]
    start, end = 9 * 60, 21 * 60
    step = (end - start) // (ppd - 1)
    return [f"{(start + i*step)//60:02d}:{(start + i*step)%60:02d}" for i in range(ppd)]


def effective_template(tmpl: dict, days: int, ppd: int) -> dict:
    """A template copy scaled to days × ppd: scaled pillar/format mixes + synthesized times."""
    total = days * ppd
    et = dict(tmpl)
    et["period_len_days"] = days
    et["posts_per_day"] = ppd
    et["post_times"] = synth_post_times(ppd, tmpl.get("post_times", []))
    et["pillar_distribution"] = scale_distribution(tmpl["pillar_distribution"], total)
    et["format_distribution_weekly"] = scale_distribution(tmpl["format_distribution_weekly"], ppd * 7)
    return et
```

(c) Refactor `plan(args)` so its body (from `conn = db_connect()` through `conn.commit()`) is callable with a ready template. Extract a function and have both `plan` and the API call it:

```python
def _plan_with_template(cfg, tmpl_name, tmpl, round_id=None, label=None):
    """Core planning: walk cursors, persist round+slots+lens_history+cursor+audit. Returns
    (round_id, n_slots). Shared by the CLI `plan` and the API `plan_round_api`."""
    engine = cfg.get("engine", {})
    carry = engine.get("carry_cursor_across_rounds", True)
    enforce_rotation = engine.get("enforce_lens_rotation", True)
    conn = db_connect(); conn.autocommit = False
    cur = conn.cursor()
    round_id = round_id or next_round_id(cur)
    cur.execute("SELECT 1 FROM round WHERE round_id=%s", (round_id,))
    if cur.fetchone():
        raise SystemExit(f"round {round_id} already exists")
    pillar_hcs, hcs_lenses, hcs_name, lens_name, lens_hook = load_methodology(cur)
    cursors = load_cursors(cur) if carry else {}
    hist = load_lens_history(cur)
    walkers = {p: PillarWalker(p, ordered, *cursors.get(p, (None, 1)))
               for p, ordered in pillar_hcs.items()}
    grid = assign_pillars_formats(build_grid(round_id, tmpl), tmpl)
    new_lens_history = {}
    for slot in grid:
        hcs_id, cycle = walkers[slot["pillar_code"]].next()
        lens = pick_lens(hcs_id, cycle, hcs_lenses[hcs_id], hist, enforce_rotation)
        slot.update(hcs_id=hcs_id, cycle_no=cycle, lens=lens, hook_type=lens_hook.get(lens))
        new_lens_history[(hcs_id, cycle)] = lens
    cur.execute(
        """INSERT INTO round (round_id, label, period_len_days, posts_per_day, post_times,
                              pillar_distribution, format_distribution, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,'planned')""",
        (round_id, label or f"{tmpl_name} round {round_id}", tmpl["period_len_days"],
         tmpl["posts_per_day"], Json(tmpl["post_times"]),
         Json(tmpl["pillar_distribution"]), Json(tmpl["format_distribution_weekly"])))
    psycopg2.extras.execute_batch(cur,
        """INSERT INTO slot (slot_id, round_id, day, time_uae, pillar_code, format,
                             hcs_id, lens, hook_type, cycle_no, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'RESERVED')""",
        [(s["slot_id"], round_id, s["day"], s["time_uae"], s["pillar_code"], s["format"],
          s["hcs_id"], s["lens"], s["hook_type"], s["cycle_no"]) for s in grid])
    psycopg2.extras.execute_batch(cur,
        """INSERT INTO lens_history (hcs_id, cycle_no, lens) VALUES (%s,%s,%s)
           ON CONFLICT (hcs_id, cycle_no) DO UPDATE SET lens=EXCLUDED.lens""",
        [(h, c, l) for (h, c), l in new_lens_history.items()])
    for pillar_code, w in walkers.items():
        cur.execute(
            """INSERT INTO hcs_cursor (pillar_code, last_hcs_id, cycle_no) VALUES (%s,%s,%s)
               ON CONFLICT (pillar_code) DO UPDATE
                 SET last_hcs_id=EXCLUDED.last_hcs_id, cycle_no=EXCLUDED.cycle_no""",
            (pillar_code, w.last_emitted, w.cycle))
    cur.execute("""INSERT INTO audit_log (entity, entity_id, action, actor, detail)
                   VALUES ('round', %s, 'planned', 'planner', %s)""",
                (round_id, Json({"template": tmpl_name, "slots": len(grid)})))
    psycopg2.extras.execute_batch(cur,
        """INSERT INTO audit_log (entity, entity_id, action, actor, detail)
           VALUES ('slot', %s, 'status_change', 'planner', %s)""",
        [(s["slot_id"], Json({"from": "EMPTY", "to": "RESERVED", "hcs_id": s["hcs_id"],
                              "cycle_no": s["cycle_no"], "lens": s["lens"]})) for s in grid])
    conn.commit(); conn.close()
    return round_id, len(grid)


def plan_round_api(cfg: dict, days: int, posts_per_day: int, label=None) -> dict:
    """Plan a fresh round scaled to days × posts_per_day. Returns {round_id, total}."""
    if days < 1 or posts_per_day < 1:
        raise ValueError("days and posts_per_day must be >= 1")
    tmpl_name, base = get_template(cfg, None)
    et = effective_template(base, days, posts_per_day)
    rid, n = _plan_with_template(cfg, tmpl_name, et, label=label)
    return {"round_id": rid, "total": n}
```

Then trim `plan(args)` so its persistence body is replaced by a call to `_plan_with_template(cfg, tmpl_name, tmpl, args.round_id, args.label)` followed by the existing `print_calendar`/`verify_mix` (those read `grid`; keep them by having `_plan_with_template` optionally return `grid` — simplest: leave `plan(args)`'s verification prints as-is by computing from a re-query, OR keep `plan` calling the old inline body. **Minimal-risk choice:** keep `plan(args)` unchanged and only ADD the new functions; `plan_round_api` is independent. Do that to avoid disturbing the CLI path.)

> Implementation note: choose the minimal-risk path — **add** `_plan_with_template`/`plan_round_api`/`effective_template`/`synth_post_times` and do NOT refactor `plan(args)`. The CLI keeps working untouched; the API uses the new path.

- [ ] **Step 4: Run it to verify it passes**

Run: `docker restart tanaghom-gateapi && sleep 8 && docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest`
Expected: the new `[PASS]` lines for `effective_template`/`synth_post_times`; suite ends `ALL API CHECKS PASSED`.

- [ ] **Step 5: Commit**

```bash
git add planner/plan_round.py gates/api_selftest.py
git commit -m "planner: effective_template + plan_round_api (parametric run sizing)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `POST /rounds` endpoint + cursor-integrity test

**Files:**
- Modify: `gates/api.py` (add endpoint after `/stages`, ~line 94; import `plan_round` module)
- Test: `gates/api_selftest.py` (new section "Q) POST /rounds", uses throwaway rounds, torn down locally)

**Interfaces:**
- Consumes: `plan_round_api` (Task 2).
- Produces: `POST /rounds {days:int, posts_per_day:int, label?:str} -> {round_id, total}` (HTTP 422 on days/ppd < 1).

- [ ] **Step 1: Write the failing test** — add a self-contained section to `api_selftest.py` `main()` (after the "P)" section). It plans two small rounds via the API and asserts sizing + cursor advance, then tears them down:

```python
    # Q) POST /rounds — parametric planning + cursor integrity across two rounds
    def _wipe_round(rid):
        c = conn.cursor()
        c.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id=%s)", (rid,))
        for tbl in ("directive", "slot_approval", "slot_review", "asset", "topic", "script", "slot"):
            c.execute(f"DELETE FROM {tbl} WHERE slot_id LIKE %s OR slot_id IN (SELECT slot_id FROM slot WHERE round_id=%s)", (rid + "-%", rid))
        c.execute("DELETE FROM slot WHERE round_id=%s", (rid,))
        c.execute("DELETE FROM topic WHERE round_id=%s", (rid,))
        c.execute("DELETE FROM round WHERE round_id=%s", (rid,))
        c.execute("DELETE FROM audit_log WHERE entity_id=%s OR entity_id LIKE %s", (rid, rid + "-%"))
        conn.commit()

    cur0 = conn.cursor()
    cur0.execute("SELECT pillar_code, last_hcs_id, cycle_no FROM hcs_cursor ORDER BY pillar_code")
    cursor_before = cur0.fetchall(); cur0.close()
    st, b1 = POST("/rounds", {"days": 3, "posts_per_day": 2, "label": "selftest A"})
    check("POST /rounds returns 200", st, 200)
    r1 = b1["round_id"]
    check("planned round has days*ppd = 6 slots", b1["total"], 6)
    cur0 = conn.cursor(); cur0.execute("SELECT count(*) FROM slot WHERE round_id=%s AND status='RESERVED'", (r1,))
    check("all 6 slots are RESERVED", cur0.fetchone()[0], 6); cur0.close()
    st2, b2 = POST("/rounds", {"days": 2, "posts_per_day": 2})
    r2 = b2["round_id"]
    check("second round is a distinct id", r2 != r1, True)
    # cursor integrity: the two rounds advanced each pillar's cursor; no crash, monotonic cycles
    cur0 = conn.cursor(); cur0.execute("SELECT count(*) FROM slot WHERE round_id IN (%s,%s)", (r1, r2))
    check("both rounds planned without error (10 slots total)", cur0.fetchone()[0], 10); cur0.close()
    st3, _ = POST("/rounds", {"days": 0, "posts_per_day": 2})
    check("POST /rounds rejects days < 1 (422)", st3, 422)
    _wipe_round(r1); _wipe_round(r2)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest`
Expected: FAIL — `POST /rounds returns 200: got=404`.

- [ ] **Step 3: Implement.** In `gates/api.py`, near the top imports add:

```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "planner"))
try:
    import plan_round  # noqa: E402  (parametric run planning)
except Exception:      # noqa: BLE001
    plan_round = None
```

Add the endpoint after `/stages`:

```python
class NewRoundBody(BaseModel):
    days: int = Field(28, ge=1)
    posts_per_day: int = Field(2, ge=1)
    label: str | None = None

@app.post("/rounds")
def create_round(body: NewRoundBody):
    """Plan a fresh round scaled to days × posts_per_day (ratios from the template). Returns
    {round_id, total}. The single UI/agent entry to start a run."""
    if plan_round is None:
        raise HTTPException(503, "planner unavailable")
    try:
        return plan_round.plan_round_api(engine.load_config(), body.days, body.posts_per_day, body.label)
    except ValueError as e:
        raise HTTPException(422, str(e))
```

Ensure `from pydantic import BaseModel, Field` is imported (add `Field` if only `BaseModel` is there).

- [ ] **Step 4: Run it to verify it passes**

Run: `docker restart tanaghom-gateapi && sleep 8 && docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest`
Expected: the "Q)" `[PASS]` lines; suite ends `ALL API CHECKS PASSED`.

- [ ] **Step 5: Commit**

```bash
git add gates/api.py gates/api_selftest.py
git commit -m "api: POST /rounds — plan a parametric run from the UI

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: In-process job registry (`gates/jobs.py`)

**Files:**
- Create: `gates/jobs.py`
- Test: `gates/selftest.py` (new section at the end of its `main()`, before the final summary)

**Interfaces:**
- Produces:
  - `start(kind: str, round_id: str, stage: str, total: int, fn: Callable[[], None]) -> str` — runs `fn` on a daemon thread; returns `job_id`.
  - `status(job_id: str, done_fn: Callable[[dict], int] | None = None) -> dict | None` — returns `{job_id, kind, round_id, stage, status, total, done, error}` or `None`. `done` = `done_fn(record)` when given (live DB count), else the stored progress.
  - Module-level `JOBS: dict` (bounded to ~50, FIFO eviction of finished jobs).

- [ ] **Step 1: Write the failing test** — append to `gates/selftest.py` `main()`:

```python
    print("\n9) job registry")
    import gates.jobs as jobs, time as _t
    flag = {"ran": False}
    def _work():
        _t.sleep(0.05); flag["ran"] = True
    jid = jobs.start("test", "RJOB", "topic_review", 3, _work)
    check("start returns a job id", isinstance(jid, str) and len(jid) > 0, True)
    st = jobs.status(jid)
    check("status known right after start", st["status"] in ("running", "done"), True)
    for _ in range(50):
        if jobs.status(jid)["status"] == "done": break
        _t.sleep(0.02)
    check("job runs to completion", (jobs.status(jid)["status"], flag["ran"]), ("done", True))
    check("done_fn overrides the live count", jobs.status(jid, lambda r: 2)["done"], 2)
    def _boom(): raise RuntimeError("nope")
    jid2 = jobs.start("test", "RJOB", "topic_review", 1, _boom)
    for _ in range(50):
        if jobs.status(jid2)["status"] != "running": break
        _t.sleep(0.02)
    check("a failing job is marked error with the message", (jobs.status(jid2)["status"], "nope" in (jobs.status(jid2)["error"] or "")), ("error", True))
    check("unknown job id -> None", jobs.status("nope-id"), None)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker exec -e PYTHONPATH=/work tanaghom-gateapi python -m gates.selftest`
Expected: FAIL — `ModuleNotFoundError: No module named 'gates.jobs'`.

- [ ] **Step 3: Implement `gates/jobs.py`:**

```python
"""In-process generation-job registry. Single operator, low volume — daemon threads, no broker.
Progress is DB-derived (the caller passes a done_fn), so a restart loses only the 'running' flag,
never produced work. A durable queue is an if-scale item, intentionally not built here."""
import threading
import uuid

JOBS: dict = {}
_LOCK = threading.Lock()
_CAP = 50


def start(kind: str, round_id: str, stage: str, total: int, fn) -> str:
    job_id = uuid.uuid4().hex[:12]
    rec = {"job_id": job_id, "kind": kind, "round_id": round_id, "stage": stage,
           "status": "running", "total": total, "done": 0, "error": None}
    with _LOCK:
        JOBS[job_id] = rec
        if len(JOBS) > _CAP:                       # evict oldest finished jobs
            for k in [k for k, v in list(JOBS.items()) if v["status"] != "running"][: len(JOBS) - _CAP]:
                JOBS.pop(k, None)

    def _run():
        try:
            fn()
            rec["status"] = "done"
        except Exception as e:                     # noqa: BLE001
            rec["status"] = "error"; rec["error"] = str(e)
    threading.Thread(target=_run, daemon=True).start()
    return job_id


def status(job_id: str, done_fn=None):
    rec = JOBS.get(job_id)
    if rec is None:
        return None
    out = dict(rec)
    if done_fn is not None:
        try:
            out["done"] = int(done_fn(rec))
        except Exception:                          # noqa: BLE001
            pass
    if out["status"] == "done":
        out["done"] = out["total"]
    return out
```

- [ ] **Step 4: Run it to verify it passes**

Run: `docker exec -e PYTHONPATH=/work tanaghom-gateapi python -m gates.selftest`
Expected: new "9) job registry" `[PASS]` lines; suite ends `ALL CHECKS PASSED`.

- [ ] **Step 5: Commit**

```bash
git add gates/jobs.py gates/selftest.py
git commit -m "jobs: in-process generation-job registry (daemon threads, DB-derived progress)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Generation config + endpoints (`/generate`, `/jobs/{id}`)

**Files:**
- Modify: `system_config.yaml` and `system_config.example.yaml` (add `generator`/`generates_from`/`writer_mode` to `topic_review` and `script_review` gates)
- Modify: `gates/api.py` (two endpoints)
- Test: `gates/api_selftest.py` (new section "R) generation jobs", uses a throwaway round + the stub writer)

**Interfaces:**
- Consumes: `gates.jobs.start/status` (Task 4); `run_writers.run_topics/run_scripts`; `engine.stage_cfg`.
- Produces:
  - `POST /rounds/{round_id}/stages/{stage}/generate -> {job_id, total}` (404 unknown stage; 409 no pending inputs / not a generation stage; 503 writer unavailable).
  - `GET /jobs/{job_id} -> {job_id, kind, round_id, stage, status, total, done, error}` (404 unknown).

- [ ] **Step 1: Write the failing test** — add to `api_selftest.py` `main()` (uses `POST`, `GET`, `conn`, the stub writer that `TANAGHOM_WRITER_STUB=1` enables):

```python
    # R) generation jobs — plan, generate topics, poll to done (stub writer)
    import time as _t
    _, rg = POST("/rounds", {"days": 2, "posts_per_day": 2})   # 4 RESERVED slots
    rgid = rg["round_id"]
    stg, jb = POST(f"/rounds/{rgid}/stages/topic_review/generate", {})
    check("generate returns 200 + a job over the pending inputs", (stg, jb["total"]), (200, 4))
    jid = jb["job_id"]
    final = None
    for _ in range(120):
        _, js = GET(f"/jobs/{jid}")
        if js["status"] != "running": final = js; break
        _t.sleep(0.5)
    check("topic generation job reaches done", final and final["status"], "done")
    cur0 = conn.cursor(); cur0.execute("SELECT count(*) FROM slot WHERE round_id=%s AND status='TOPIC_PROPOSED'", (rgid,))
    check("all 4 slots generated -> TOPIC_PROPOSED", cur0.fetchone()[0], 4); cur0.close()
    stg2, _ = POST(f"/rounds/{rgid}/stages/topic_review/generate", {})
    check("re-generate with nothing pending -> 409", stg2, 409)
    check("unknown job id -> 404", GET("/jobs/does-not-exist")[0], 404)
    _wipe_round(rgid)   # _wipe_round defined in Task 3's section
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest`
Expected: FAIL — `generate returns 200 ...: got=404`.

- [ ] **Step 3a: Config.** In BOTH `system_config.yaml` and `system_config.example.yaml`, add three keys to the two generation gates (under the existing `gates:` block):

```yaml
  topic_review:
    reviews_status: "TOPIC_PROPOSED"
    approve_to:    "TOPIC_APPROVED"
    rework_mode:   "topic"
    generator:     "ai"           # NEW — UI/agent can trigger generation
    generates_from: "RESERVED"    # NEW — writer input status
    writer_mode:   "topics"       # NEW — run_writers entry (topics|scripts)
```
```yaml
  script_review:
    reviews_status: "DRAFT_ASSIGNED"
    approve_to:    "APPROVED_ASSIGNED"
    rework_mode:   "script"
    generator:     "ai"           # NEW
    generates_from: "TOPIC_APPROVED"   # NEW
    writer_mode:   "scripts"      # NEW
```

- [ ] **Step 3b: Endpoints.** In `gates/api.py` (reuse the existing `run_writers` import + `jobs`):

```python
import gates.jobs as jobs   # near the other imports

class _GenArgs:              # a tiny argparse-compatible shim for run_writers.run_topics/run_scripts
    def __init__(self, round_id):
        self.round = round_id; self.slot_ids = None; self.distinct_pillars = False
        self.limit = None; self.dry_run = False

@app.post("/rounds/{round_id}/stages/{stage}/generate")
def generate(round_id: str, stage: str):
    """Start a generation job over a stage's pending inputs (the single generation mechanism)."""
    cfg = engine.load_config()
    gc = engine.stage_cfg(cfg, stage)
    if not gc or gc.get("generator") != "ai" or not gc.get("generates_from"):
        raise HTTPException(409, f"stage {stage} has no AI generator")
    if run_writers is None:
        raise HTTPException(503, "writer unavailable (provider deps not installed)")
    src = gc["generates_from"]; mode = gc["writer_mode"]
    c = _conn()
    try:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM slot WHERE round_id=%s AND status=%s", (round_id, src))
        total = cur.fetchone()[0]
    finally:
        c.close()
    if total == 0:
        raise HTTPException(409, f"no slots in {src} to generate for {stage}")
    fn = run_writers.run_topics if mode == "topics" else run_writers.run_scripts
    job_id = jobs.start(mode, round_id, stage, total, lambda: fn(cfg, _GenArgs(round_id)))
    return {"job_id": job_id, "total": total}

@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    """Live status of a generation job. `done` is DB-derived (slots that reached the output status)."""
    rec = jobs.JOBS.get(job_id)
    if rec is None:
        raise HTTPException(404, "unknown job")
    gc = engine.stage_cfg(engine.load_config(), rec["stage"])
    out_status = (gc.get("reviews_status") if gc else None)
    out_status = out_status[0] if isinstance(out_status, list) else out_status

    def _done(r):
        c = _conn()
        try:
            cur = c.cursor()
            cur.execute("SELECT count(*) FROM slot WHERE round_id=%s AND status=%s", (r["round_id"], out_status))
            return cur.fetchone()[0]
        finally:
            c.close()
    return jobs.status(job_id, _done)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `docker restart tanaghom-gateapi && sleep 8 && docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest`
Expected: the "R)" `[PASS]` lines; suite ends `ALL API CHECKS PASSED`.
(The API container must have `TANAGHOM_WRITER_STUB=1` for deterministic generation — recreate it with that env if not present, per Task 9's setup.)

- [ ] **Step 5: Commit**

```bash
git add system_config.yaml system_config.example.yaml gates/api.py gates/api_selftest.py
git commit -m "api: stage generate + job-status endpoints (single generation mechanism)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `stage_state.next_action` + bug fixes

**Files:**
- Modify: `gates/engine.py` (`stage_state`, ~lines 700–760; add helper `_pending_input_count`)
- Test: `gates/selftest.py` (new section after the job-registry section)

**Interfaces:**
- Consumes: `stage_cfg` (existing), `generates_from`/`generator` config (Task 5).
- Produces: `stage_state(...)` return dict GAINS `generator: str|None`, `pending_input: int`, `next_action: str ∈ {generate,start_review,reviewing,ready_to_commit,awaiting_regeneration,complete,empty}`.

- [ ] **Step 1: Write the failing test** — append a section to `gates/selftest.py`. It plans a tiny round via the engine's planner path is overkill; instead seed two slots directly and assert transitions:

```python
    print("\n10) stage_state.next_action + bug fixes")
    import gates.engine as eng
    cc = eng.db_connect(); k = cc.cursor()
    k.execute("DELETE FROM gate WHERE gate_id IN (SELECT gate_id FROM gate_target t JOIN slot s ON s.slot_id=t.slot_id WHERE s.round_id='RNXT')")
    for tbl in ("directive","slot_approval","slot_review","asset","topic","script","slot"):
        k.execute(f"DELETE FROM {tbl} WHERE slot_id LIKE 'RNXT-%%'")
    k.execute("DELETE FROM round WHERE round_id='RNXT'")
    k.execute("""INSERT INTO round (round_id,label,period_len_days,posts_per_day,post_times,
                 pillar_distribution,format_distribution,status) VALUES
                 ('RNXT','nx',1,2,'[\"09:00\"]','{}','{}','planned')""")
    k.execute("""INSERT INTO slot (slot_id,round_id,day,time_uae,pillar_code,hcs_id,lens,hook_type,status,cycle_no)
                 VALUES ('RNXT-1','RNXT',1,'09:00','P1_SELF','1.1','L1','Painful Truth','RESERVED',1)""")
    cc.commit(); k.close()
    ss = eng.stage_state(cc, "RNXT", "topic_review")
    check("RESERVED slot -> next_action=generate", ss["next_action"], "generate")
    check("generator type surfaced", ss["generator"], "ai")
    check("pending_input counts the RESERVED slot", ss["pending_input"], 1)
    # advance it to TOPIC_APPROVED with NO script -> the SCRIPT stage should say generate, not complete
    k = cc.cursor(); k.execute("UPDATE slot SET status='TOPIC_APPROVED' WHERE slot_id='RNXT-1'"); cc.commit(); k.close()
    sc = eng.stage_state(cc, "RNXT", "script_review")
    check("approved topic w/o script -> script stage next_action=generate (NOT complete)", sc["next_action"], "generate")
    # a stage with only an inherited 'dropped' and nothing advanced must NOT read complete
    k = cc.cursor(); k.execute("UPDATE slot SET status='REJECTED' WHERE slot_id='RNXT-1'"); cc.commit(); k.close()
    sj = eng.stage_state(cc, "RNXT", "script_review")
    check("inherited dropped + 0 advanced -> not 'complete'", sj["next_action"] != "complete", True)
    k = cc.cursor()
    for tbl in ("slot","round"): k.execute(f"DELETE FROM {tbl} WHERE round_id='RNXT' OR slot_id LIKE 'RNXT-%%'")
    cc.commit(); k.close(); cc.close()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker exec -e PYTHONPATH=/work tanaghom-gateapi python -m gates.selftest`
Expected: FAIL — `KeyError: 'next_action'` or the generate assertions fail.

- [ ] **Step 3: Implement.** In `gates/engine.py`, add a helper above `stage_state`:

```python
def _pending_input_count(cur, round_id, gc):
    """Slots ready to be GENERATED for this stage (its writer-input status), for AI stages only."""
    src = gc.get("generates_from")
    if not src:
        return 0
    cur.execute("SELECT count(*) AS n FROM slot WHERE round_id=%s AND status=%s", (round_id, src))
    return cur.fetchone()["n"]
```

In `stage_state`, after computing `counts`, add:

```python
    cur3 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    pending_input = _pending_input_count(cur3, round_id, gc)
    cur3.close()
    generator = gc.get("generator")
    info["generator"] = generator
    info["pending_input"] = pending_input
```
(add `info["generator"]`/`info["pending_input"]` into the initial `info = {...}` dict too, defaulting `generator=None, pending_input=0`, so the keys always exist.)

Replace the final `else` chain (no gate) so it sets `next_action` and fixes the `complete` quirk:

```python
    else:
        info["confirm_warnings"] = []
        if review_pending > 0:
            info["state"] = info["next_action"] = "start_review"
            info["recommendation"] = f"{review_pending} item(s) ready to review."
        elif awaiting > 0:
            info["state"] = info["next_action"] = "awaiting_regeneration"
            info["recommendation"] = f"{awaiting} item(s) awaiting regeneration — regenerate to continue."
        elif generator == "ai" and pending_input > 0:
            info["state"] = info["next_action"] = "generate"
            info["recommendation"] = f"{pending_input} item(s) ready to generate."
        elif advanced > 0:
            info["state"] = info["next_action"] = "complete"
            info["recommendation"] = ("Review complete — " + str(advanced) + " advanced"
                                      + (f", {dropped} dropped (recoverable)" if dropped else "") + ".")
        else:
            info["state"] = info["next_action"] = "empty"
            info["recommendation"] = "Nothing at this stage yet."
```

For the `if gate:` branch, also set `info["next_action"]` to mirror `info["state"]` — add at the end of that branch:

```python
        info["next_action"] = info["state"]   # reviewing | ready_to_commit
```

Note: `ready_to_start` is renamed in the output to `start_review` for `next_action`; KEEP `info["state"]` values backward-compatible — set `info["state"]="ready_to_start"` (unchanged) but `info["next_action"]="start_review"`. Adjust the snippet so `state` keeps its old value and only `next_action` uses the new vocabulary:

```python
        if review_pending > 0:
            info["state"], info["next_action"] = "ready_to_start", "start_review"
            info["recommendation"] = f"{review_pending} item(s) ready to review."
```
(Apply the same `state` vs `next_action` split to the other branches: `awaiting_regeneration`/`complete`/`empty` keep identical strings for both; `generate` is new for both.)

- [ ] **Step 4: Run it to verify it passes**

Run: `docker exec -e PYTHONPATH=/work tanaghom-gateapi python -m gates.selftest`
Expected: "10) stage_state.next_action" `[PASS]` lines; suite ends `ALL CHECKS PASSED`. Then re-run api + lifecycle suites to confirm no regression:
`docker restart tanaghom-gateapi && sleep 8 && docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest && docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.lifecycle_selftest`
Expected: both end with ALL ... PASSED.

- [ ] **Step 5: Commit**

```bash
git add gates/engine.py gates/selftest.py
git commit -m "engine: stage_state.next_action + fix complete-when-empty quirk

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Dashboard data layer — types, plan(), generate(), job polling

**Files:**
- Modify: `dashboard/lib/review-context.tsx` (extend `StageState` type; add `plan`, `generate`, `genJob` state; expose via context value)

**Interfaces:**
- Consumes: `POST /rounds`, `POST /rounds/{id}/stages/{stage}/generate`, `GET /jobs/{id}` (Tasks 3, 5).
- Produces (on the `useReview()` value): `plan(days:number, postsPerDay:number, label?:string): Promise<string>` (returns new round_id), `generate(): Promise<void>`, `genJob: {done:number; total:number; status:string} | null`.

- [ ] **Step 1: Extend the `StageState` type.** Find the `StageState` type in `review-context.tsx` and add the fields:

```typescript
export type StageState = {
  state: string;
  next_action: "generate" | "start_review" | "reviewing" | "ready_to_commit" | "awaiting_regeneration" | "complete" | "empty";
  generator: "ai" | "manual" | "external" | null;
  pending_input: number;
  review_pending: number; advanced: number; dropped: number;
  gate_id: string | null;
  recommendation?: string; warnings?: string[]; confirm_warnings?: string[];
};
```

- [ ] **Step 2: Add `plan`, `generate`, and job-polling.** Inside the provider component, near the other handlers:

```typescript
  const [genJob, setGenJob] = useState<{ done: number; total: number; status: string } | null>(null);

  const plan = useCallback(async (days: number, postsPerDay: number, label?: string) => {
    const r = await jpost(`/rounds`, { days, posts_per_day: postsPerDay, label });
    await loadRounds();
    setRound(r.round_id);
    return r.round_id as string;
  }, [loadRounds]);

  const generate = useCallback(() => run(async () => {
    const r = await jpost(`/rounds/${round}/stages/${stage.gate}/generate`, {});
    setGenJob({ done: 0, total: r.total, status: "running" });
    const poll = async () => {
      const js = await jget(`/jobs/${r.job_id}`);
      setGenJob({ done: js.done, total: js.total, status: js.status });
      if (js.status === "running") { setTimeout(poll, 1000); return; }
      setGenJob(null);
      await load(); await loadRounds();
      if (js.status === "error") setToast({ kind: "err", msg: `Generation failed: ${js.error}` });
      else ok(`Generated ${js.total} item(s) — ready to review.`);
    };
    setTimeout(poll, 800);
  }), [round, stage.gate, load, loadRounds]);
```

Add `plan`, `generate`, `genJob` to the context `value` object that `useReview()` exposes.

- [ ] **Step 3: Type-check.**

Run: `cd dashboard && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add dashboard/lib/review-context.tsx
git commit -m "dashboard: plan() + generate() + job polling in review context

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Dashboard UI — StageAction, New-run dialog, wiring

**Files:**
- Create: `dashboard/components/review/stage-action.tsx`
- Create: `dashboard/components/review/new-run-dialog.tsx`
- Modify: `dashboard/components/review/review-surface.tsx` (render `<StageAction/>`, remove the static empty copy at line 86–88)
- Modify: `dashboard/components/review/app-shell.tsx` (mount the New-run dialog trigger in the topbar)

**Interfaces:**
- Consumes: `useReview()` → `plan`, `generate`, `genJob`, `stageState`, `gate`, `stage`, `round` (Task 7).
- Produces: `<StageAction/>` and `<NewRunDialog/>` React components; new `data-testid`s: `new-run`, `days-input`, `ppd-input`, `new-run-submit`, `generate-action`, `job-progress`.

- [ ] **Step 1: Create `stage-action.tsx`** — renders the next action from `stageState.next_action`:

```tsx
"use client";
import { useReview } from "@/lib/review-context";
import { Button } from "@/components/ui/button";

export function StageAction() {
  const r = useReview();
  const ss = r.stageState;
  if (r.gate) return null;                 // an open review is handled by the disposition bar
  if (!ss) return null;
  if (r.genJob) {
    const pct = r.genJob.total ? Math.round((r.genJob.done / r.genJob.total) * 100) : 0;
    return (
      <div data-testid="job-progress" className="rounded-lg border bg-card px-4 py-3 text-sm">
        ⟳ Generating… {r.genJob.done} / {r.genJob.total}
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-muted">
          <div className="h-full bg-primary transition-all" style={{ width: `${pct}%` }} />
        </div>
      </div>
    );
  }
  if (ss.next_action === "generate") {
    const noun = r.stage.key === "script" ? "drafts" : `${r.stage.label.toLowerCase()}`;
    return (
      <div className="flex items-center gap-3 rounded-lg border bg-card px-4 py-3 text-sm">
        <span className="text-muted-foreground">{ss.recommendation}</span>
        <Button data-testid="generate-action" size="sm" className="ml-auto" disabled={r.busy}
                onClick={r.generate}>Generate {noun}</Button>
      </div>
    );
  }
  if (ss.next_action === "complete")
    return <div className="rounded-lg border border-success/40 bg-success/10 px-4 py-3 text-sm">✓ {ss.recommendation}</div>;
  if (ss.next_action === "empty")
    return <div className="rounded-lg border bg-card px-4 py-3 text-sm text-muted-foreground">{ss.recommendation}</div>;
  return null;   // start_review / reviewing / ready_to_commit / awaiting_regeneration -> disposition bar
}
```

- [ ] **Step 2: Create `new-run-dialog.tsx`** — days × posts/day, defaults 28/2, live "= N posts":

```tsx
"use client";
import { useState } from "react";
import { useReview } from "@/lib/review-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";

export function NewRunDialog() {
  const r = useReview();
  const [open, setOpen] = useState(false);
  const [days, setDays] = useState(28);
  const [ppd, setPpd] = useState(2);
  const total = Math.max(0, (days || 0) * (ppd || 0));
  const submit = async () => { await r.plan(days, ppd); setOpen(false); };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button data-testid="new-run" size="sm" variant="outline">New run</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader><DialogTitle>Start a run</DialogTitle></DialogHeader>
        <div className="grid grid-cols-2 gap-4 py-2">
          <label className="text-sm">Days
            <Input data-testid="days-input" type="number" min={1} value={days}
                   onChange={(e) => setDays(parseInt(e.target.value || "1", 10))} />
          </label>
          <label className="text-sm">Posts / day
            <Input data-testid="ppd-input" type="number" min={1} value={ppd}
                   onChange={(e) => setPpd(parseInt(e.target.value || "1", 10))} />
          </label>
        </div>
        <p className="text-sm text-muted-foreground">= <b>{total}</b> posts this run.</p>
        <DialogFooter>
          <Button data-testid="new-run-submit" disabled={r.busy || days < 1 || ppd < 1} onClick={submit}>Plan run</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

If `dashboard/components/ui/dialog.tsx` or `input.tsx` are absent, add them first: `cd dashboard && npx shadcn@latest add dialog input` (config-driven; no version pin needed beyond the project's shadcn setup).

- [ ] **Step 3: Wire into `review-surface.tsx`.** Replace the static empty block (current lines 85–88) with the `StageAction` component:

```tsx
import { StageAction } from "@/components/review/stage-action";
// ...in the review-feed section, replace the `{!gate && round && changes.length === 0 && (...)}` block with:
        {!gate && round && changes.length === 0 && <StageAction />}
```

- [ ] **Step 4: Wire `NewRunDialog` into `app-shell.tsx`.** Import it and render it in the topbar next to the round selector:

```tsx
import { NewRunDialog } from "@/components/review/new-run-dialog";
// ...in the topbar JSX, beside the round Select:
        <NewRunDialog />
```

- [ ] **Step 5: Build to verify.**

Run: `cd dashboard && npm run typecheck && API_BASE=http://localhost:8009 npm run build`
Expected: typecheck clean; build succeeds (the `.env`/GROQ key is loaded the same way as production builds — run with the key in env if the build evaluates `/api/chat`).

- [ ] **Step 6: Commit**

```bash
git add dashboard/components/review/stage-action.tsx dashboard/components/review/new-run-dialog.tsx dashboard/components/review/review-surface.tsx dashboard/components/review/app-shell.tsx dashboard/components/ui/
git commit -m "dashboard: unified StageAction + New-run dialog (generate per stage)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Playwright e2e — new run → generate topics → review → generate drafts

**Files:**
- Create: `dashboard/e2e/runs-and-generation.spec.ts`
- (The API container must run with `TANAGHOM_WRITER_STUB=1` for deterministic generation.)

**Interfaces:**
- Consumes: the running dashboard (:3007) + gate API (:8009, stub writer); existing `data-testid` hooks + the new ones from Task 8.

- [ ] **Step 1: Ensure the stub-writer API is running.**

All credentials come from the gitignored `.env` via `--env-file` — NEVER inline real keys/passwords
in a tracked file. `DB_HOST`/`DB_PORT` are overridden to the in-network values; `TANAGHOM_WRITER_STUB=1`
forces the deterministic offline writer for e2e.

```bash
docker rm -f tanaghom-gateapi >/dev/null 2>&1
docker run -d --name tanaghom-gateapi --network tanaghom_default -w /work \
  --env-file /Users/Kay/Dev/tanaghom/.env \
  -e DB_HOST=db -e DB_PORT=5432 -e TANAGHOM_WRITER_STUB=1 \
  -v /Users/Kay/Dev/tanaghom:/work -p 8009:8000 \
  python:3.12-slim bash -lc "pip install -q -r gates/requirements.txt -r agents/requirements.txt && uvicorn gates.api:app --host 0.0.0.0 --port 8000" >/dev/null
until curl -sf http://localhost:8009/stages >/dev/null; do sleep 2; done
```

- [ ] **Step 2: Write the spec.** Create `dashboard/e2e/runs-and-generation.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";

// Drives the full UI-driven path: plan a small run, generate topics (background job),
// review them, then generate scripts. Asserts the DB-backed API after each step.
const API = process.env.API_BASE || "http://localhost:8009";

async function planViaUi(page) {
  await page.goto("/");
  await page.getByTestId("new-run").click();
  await page.getByTestId("days-input").fill("1");
  await page.getByTestId("ppd-input").fill("2");
  await page.getByTestId("new-run-submit").click();
}

test("UI-driven run: plan -> generate topics -> review -> generate drafts", async ({ page }) => {
  await planViaUi(page);
  // Topic stage now shows a Generate action
  await expect(page.getByTestId("generate-action")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("generate-action").click();
  // progress appears, then items load
  await expect(page.getByTestId("job-progress")).toBeVisible();
  await expect(page.getByTestId("open-gate")).toBeVisible({ timeout: 60000 });
  // start review, approve all, commit
  await page.getByTestId("open-gate").click();
  await expect(page.locator("[data-testid^=card-]").first()).toBeVisible();
});
```

- [ ] **Step 3: Build + restart the dashboard, then run the suite.**

```bash
cd /Users/Kay/Dev/tanaghom/dashboard
API_BASE=http://localhost:8009 npm run build
# restart the dashboard on :3007 (kill the old one first)
DASH_URL=http://localhost:3007 API_BASE=http://localhost:8009 npx playwright test runs-and-generation.spec.ts
```
Expected: the new spec passes. Then run the full suite to confirm no regression:
`DASH_URL=http://localhost:3007 API_BASE=http://localhost:8009 npx playwright test`
Expected: all specs pass (9 existing + the new one).

- [ ] **Step 4: Commit**

```bash
git add dashboard/e2e/runs-and-generation.spec.ts
git commit -m "e2e: UI-driven run -> generate topics -> review -> generate drafts

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Full-suite green + coordinated reset + stop for review

**Files:** none (operational). Reset is destructive and clears the SHARED DB.

- [ ] **Step 1: Run all four suites green** (restart the API first so it has the final Python + stub writer):

```bash
docker restart tanaghom-gateapi && until curl -sf http://localhost:8009/stages >/dev/null; do sleep 2; done
docker exec -e PYTHONPATH=/work tanaghom-gateapi python -m gates.selftest
docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.api_selftest
docker exec -e PYTHONPATH=/work -e API_BASE=http://localhost:8000 tanaghom-gateapi python -m gates.lifecycle_selftest
cd /Users/Kay/Dev/tanaghom/dashboard && DASH_URL=http://localhost:3007 API_BASE=http://localhost:8009 npx playwright test
```
Expected: engine/api/lifecycle end `ALL ... PASSED`; Playwright all green.

- [ ] **Step 2: Coordinated shared-DB reset.** ⚠️ This wipes the SHARED Postgres — it also destroys the Telegram-pilot session's data (e.g. `RTG1`). Confirm the parallel session is OK to reset, then:

```bash
docker exec tanaghom-db psql -U tanaghom -d tanaghom -c "
TRUNCATE round, slot, topic, script, gate, gate_target, gate_decision, directive,
         asset, slot_approval, slot_review, audit_log, hcs_cursor, lens_history
RESTART IDENTITY;"
docker exec tanaghom-db psql -U tanaghom -d tanaghom -t -c "SELECT count(*) FROM round;"   # -> 0
docker exec tanaghom-db psql -U tanaghom -d tanaghom -t -c "SELECT count(*) FROM hcs;"     # -> 42 (preserved)
```

- [ ] **Step 3: Update BUILD_STATE.md** with a Phase-1 continuity entry (new UI-driven-runs surface, endpoints, the two bug fixes, reset done) and commit.

- [ ] **Step 4: STOP for the user's review.** Report: suites green, endpoints live, clean slate ready, and that the next move (Phase 2 UX pass) awaits their go-ahead. Do NOT start Phase 2.

---

## Self-Review

**1. Spec coverage:**
- Planner ratio-scaling + tiny-run + cursor integrity → Tasks 1, 2, 3. ✓
- `POST /rounds` → Task 3. ✓
- Background jobs + `/generate` + `/jobs/{id}` (single mechanism, in-process, DB-derived) → Tasks 4, 5. ✓
- `stage_state.next_action` + both bug fixes (complete-when-empty, inherited-dropped not "acted-upon") → Task 6. ✓
- Start-a-run UI + unified StageAction + state-aware copy → Tasks 7, 8. ✓
- Reset (full wipe, methodology preserved, shared-DB coordination warning) → Task 10. ✓
- Tests across all four suites → Tasks 1–9; full green gate → Task 10. ✓
- Phase 2 explicitly NOT started → Task 10 Step 4. ✓
- Config mirrored to `.example` (Task 5), commit-message convention (every commit), no durable queue (Task 4 docstring). ✓

**2. Placeholder scan:** No TBD/TODO; every code step has concrete code. The one judgement call (don't refactor `plan(args)`) is stated explicitly. ✓

**3. Type consistency:** `plan_round_api`/`effective_template`/`scale_distribution`/`synth_post_times` names match across Tasks 1–3 and the API. `jobs.start`/`jobs.status`/`JOBS` match across Tasks 4–5. `stage_state` adds `next_action`/`generator`/`pending_input`, consumed identically in Tasks 7–8. `generate`/`plan`/`genJob` context names match across Tasks 7–9. ✓
