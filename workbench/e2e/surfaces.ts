import { execFileSync } from "node:child_process";

// Shared constants + the read-only DB snapshot helper for #293's Stage 0 evidence.

export const V1_URL = process.env.V1_URL || "http://localhost:3000";
export const WB_URL = process.env.WB_URL || "http://localhost:3001";

/** The synthetic, non-client fixture round (gates/e2e_seed.py). Never a client run. */
export const FIXTURE_ROUND = "RE2E";

/** The three viewports #293 names for branding/responsiveness evidence. */
export const VIEWPORTS = [
  { label: "375px", width: 375, height: 812 },
  { label: "tablet", width: 768, height: 1024 },
  { label: "desktop", width: 1280, height: 900 },
] as const;

/** State that a Stage 0 read-only lane must never alter. `slot_approval`/`gate_decision` are the
 *  commit surfaces and `audit_log` is the provenance surface — if a read path silently wrote
 *  anything, one of these counts would move. */
const SNAPSHOT_SQL = `
SELECT
  (SELECT count(*) FROM audit_log)      AS audit_log,
  (SELECT count(*) FROM round)          AS round,
  (SELECT count(*) FROM slot)           AS slot,
  (SELECT count(*) FROM gate)           AS gate,
  (SELECT count(*) FROM gate_decision)  AS gate_decision,
  (SELECT count(*) FROM slot_approval)  AS slot_approval,
  (SELECT coalesce(max(id)::text,'none') FROM audit_log) AS audit_max_id,
  (SELECT coalesce(md5(string_agg(slot_id || ':' || status, ',' ORDER BY slot_id)), 'none')
     FROM slot) AS slot_status_digest
`;

/**
 * Read-only snapshot of the state Stage 0 must not touch.
 *
 * This is a pure SELECT — it creates nothing, resets nothing, and cleans up nothing (#293 forbids
 * persistent/global DB cleanup). It is evidence-gathering, not fixture management.
 */
/**
 * #345 — the database this snapshot targets.
 *
 * Default (unset) is the historical behaviour verbatim: the shell expands `$POSTGRES_DB` inside the
 * db container, i.e. whatever database that container was started with.
 *
 * That default is wrong for an ISOLATED lane, and wrong in a way that reads as success. A lane run
 * would snapshot the container's database rather than the lane's, so "nothing changed" would be
 * trivially true — nothing in the run touches that database — while proving nothing about the lane
 * under test. A false green exactly where the isolation evidence has to be strongest.
 *
 * `LANE_DB` redirects the snapshot at the one place it is read. The suite already contains this
 * lesson: schedule-views.spec.ts carries its own overridable snapshot because "the shared
 * dbSnapshot() reads the container's $POSTGRES_DB, which may point elsewhere". This generalises that
 * fix instead of copying it a third time.
 *
 * Test-only and inert by default: unset changes nothing, and no product code reads this.
 */
const LANE_DB = (process.env.LANE_DB || "").trim();

/** The `-d` argument, kept as SHELL SOURCE so the default still expands inside the container.
 *  A lane name is emitted as a literal and validated first — it is interpolated into a `sh -lc`
 *  string, so anything outside a conservative identifier charset is refused rather than passed
 *  through to a shell. */
function snapshotDbArg(): string {
  if (!LANE_DB) return '"$POSTGRES_DB"';
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(LANE_DB)) {
    throw new Error(`LANE_DB ${JSON.stringify(LANE_DB)} is not a valid database identifier`);
  }
  return `"${LANE_DB}"`;
}

export function dbSnapshot(): string {
  return execFileSync(
    "docker",
    [
      "exec",
      "-i",
      "tanaghom-db",
      "sh",
      "-lc",
      `psql -U "$POSTGRES_USER" -d ${snapshotDbArg()} -At -F '|' -c "${SNAPSHOT_SQL.replace(/\n/g, " ").replace(/"/g, '\\"')}"`,
    ],
    { stdio: ["ignore", "pipe", "pipe"] },
  )
    .toString()
    .trim();
}
