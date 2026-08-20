#!/usr/bin/env node
// #377 — the CANDIDATE-ONLY backend validation lane for the run-mix recommendation authority.
// TEST-HARNESS ONLY. No product code, no shared/operator/V1/retained-UAT resource, no hard-coded
// credential, container name or occupied port.
//
// WHY A SIBLING OF workbench/scripts/v2-validation-lane.mjs RATHER THAN A MODE OF IT. Codex ruling 4
// forbids adding a `/gw` allowlist entry or any #376 UI merely to prove #377, so the evidence shape is
// API integration + independent DB verification + discriminating red proofs. That needs the #370
// topology (disposable pgvector pinned by DIGEST, candidate dependency lock, gate API from the exact
// bind-mounted source) but NOT the workbench, the browser, or the six-category browser ledger. The
// #370 lane keeps proving what it proves; this proves what #377 needs, and neither is weakened.
//
// WHAT IT PROVES, beyond running gates/run_mix_selftest.py:
//   * exact-source binding (EXPECT_SHA + clean worktree) BEFORE any evidence is accepted;
//   * the migration applies from the committed schema and RE-APPLIES as a non-destructive no-op,
//     with an independent row/config census proving existing data survived unchanged;
//   * the served API source is byte-identical to the accepted source (bind mount, not a stale image);
//   * a named BEFORE/AFTER unrelated-state inventory (containers, networks, volumes, listeners, other
//     Postgres containers and their databases, tracked git status, bounded config content);
//   * teardown in a finally block, on both the success and the induced-failure path.
//
// EXIT ACCOUNTING (native, never masked). Every phase records its native child exit. Exit is 0 only on
// the green success path; --induce-failure preserves the induced nonzero.
//
// Usage:  EXPECT_SHA=<full 40-hex> node tools/run_mix_lane_377.mjs [--induce-failure]
//   env (optional): LANE_ID, PG_IMAGE, PY_IMAGE, API_PORT, KEEP (skip teardown)

import { execFileSync } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { existsSync, mkdtempSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";
import { dirname, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..");
const induceFailure = process.argv.includes("--induce-failure");

const LANE = process.env.LANE_ID || `rm377-${randomBytes(3).toString("hex")}`;
const PG_IMAGE = process.env.PG_IMAGE || "pgvector/pgvector:pg16@sha256:0a07c4114ba6d1d04effcce3385e9f5ce305eb02e56a3d35948a415a52f193ec";
const PY_IMAGE = process.env.PY_IMAGE || "python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e";
const NET = `tan-${LANE}-net`;
const DBC = `tan-${LANE}-db`;
const APIC = `tan-${LANE}-api`;
const DB = `tan_${LANE.replace(/-/g, "_")}`;
const DB_PW = randomBytes(9).toString("hex");
const SECRET = randomBytes(24).toString("hex");
const API_PORT = Number(process.env.API_PORT || 8392);
const API_BASE = `http://127.0.0.1:${API_PORT}`;
const REQS = ["gates/requirements.txt", "agents/requirements.txt"];
const MIGRATION_035_PATH = "db/migrations/035_run_mix_recommendation.sql";
// Which python proof this lane drives. Default is #377's own. Pointing it at gates/selftest.py or
// gates/api_selftest.py runs the EXISTING baselines on the same fail-closed candidate topology, which
// is how #377 shows it did not regress them without ever touching a shared or operator database.
const PROOF = process.env.PROOF || "gates/run_mix_selftest.py";
const ARTIFACTS = mkdtempSync(resolve(tmpdir(), `rm377-${LANE}-`));
const PIP_CACHE = resolve(ARTIFACTS, "pipcache"); mkdirSync(PIP_CACHE, { recursive: true });

const created = { net: false, db: false, api: false };
const exits = {};

function shCode(cmd, args, opts = {}) {
  try { const out = execFileSync(cmd, args, { encoding: "utf8", stdio: "pipe", ...opts }); return { code: 0, out }; }
  catch (e) { return { code: e.status ?? 1, out: (e.stdout || "") + (e.stderr || "") }; }
}
function psql(s) {
  return shCode("docker", ["exec", DBC, "psql", "-U", "tanaghom", "-d", DB, "-tAc", s]).out.trim();
}
function sha(o) { return createHash("sha256").update(typeof o === "string" ? o : JSON.stringify(o)).digest("hex"); }
function shaFile(p) { return createHash("sha256").update(readFileSync(p)).digest("hex"); }
// Absent-tolerant: a control run of an EXISTING baseline at the pre-#377 source has no run_mix.py or
// 035 migration, and "absent" is the truthful identity for them there.
function shaFileOpt(p) { return existsSync(p) ? shaFile(p) : "absent"; }
function lines(cmd) { return shCode("bash", ["-lc", cmd]).out.split("\n").map((s) => s.trim()).filter(Boolean).sort(); }
function portFree(p) { return shCode("bash", ["-lc", `lsof -tnP -iTCP:${p} -sTCP:LISTEN`]).out.trim() === ""; }

// ---- named BEFORE/AFTER unrelated-state inventory ---------------------------------------------
const CONFIG_FILES = ["system_config.example.yaml", "docker-compose.yml", ".env"];
function configContentSha() {
  return sha(CONFIG_FILES.map((f) => {
    const p = resolve(REPO, f);
    return `${f}:${existsSync(p) ? shaFile(p) : "absent"}`;
  }).join("|"));
}
function postgresContainers() {
  // NON-MUTATING discovery from image metadata: no operator container name is hard-coded, and the
  // candidate is excluded by name. A change to any other container's database set across the run is
  // exactly the cross-container mutation this must be able to catch.
  const out = [];
  for (const row of lines(`docker ps --format '{{.ID}}\t{{.Image}}\t{{.Names}}'`)) {
    const [id, image, name] = row.split("\t");
    if (!/postgres|pgvector/i.test(image)) continue;
    if (name === DBC || name.startsWith(`tan-${LANE}-`)) continue;
    const env = shCode("docker", ["inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", id]).out;
    const userLine = env.split("\n").find((l) => l.startsWith("POSTGRES_USER="));
    const user = userLine ? userLine.slice("POSTGRES_USER=".length).trim() : "postgres";
    const r = shCode("docker", ["exec", id, "psql", "-U", user, "-d", "postgres", "-tAc",
                                "SELECT datname FROM pg_database ORDER BY 1"]);
    const dbs = r.code === 0 ? r.out.split("\n").map((s) => s.trim()).filter(Boolean).sort() : ["<unreadable>"];
    out.push(`name=${name} image=${image} id=${id} dbs=[${dbs.join(",")}]`);
  }
  return out.sort();
}
function snapshotInventory() {
  return {
    containers: lines("docker ps -aq"),
    networks: lines("docker network ls --format '{{.Name}}'"),
    volumes: lines("docker volume ls -q"),
    // Only the CANDIDATE's port is an assertion. Unrelated listener churn on a developer machine
    // (another app opening an ephemeral port mid-run) is not evidence that this lane mutated
    // anything, and failing on it would be a false red exactly as damaging as a false green. The
    // full listener set is still recorded below, informationally.
    listeners: [...new Set(lines(`lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $9}' | sed 's/.*://' | grep -E '^[0-9]+$'`))]
      .filter((p) => Number(p) === API_PORT).sort(),
    postgres_containers: postgresContainers(),
    tracked_status_sha: sha(shCode("bash", ["-lc", `git -C ${REPO} status --porcelain`]).out),
    config_content_sha: configContentSha(),
  };
}
function diffInventory(before, after) {
  const changed = {};
  for (const k of ["containers", "networks", "volumes", "listeners", "postgres_containers"]) {
    const b = new Set(before[k]); const a = new Set(after[k]);
    const added = after[k].filter((x) => !b.has(x));
    const removed = before[k].filter((x) => !a.has(x));
    if (added.length || removed.length) changed[k] = { added, removed };
  }
  for (const k of ["tracked_status_sha", "config_content_sha"]) {
    if (before[k] !== after[k]) changed[k] = { before: before[k], after: after[k] };
  }
  return changed;
}

// ---- exact-source binding (fail-closed BEFORE any evidence is accepted) -------------------------
function sourceIdentity() {
  const gitc = (a) => shCode("git", ["-C", REPO, ...a]).out.trim();
  const migCat = lines(`ls ${REPO}/db/migrations/*.sql | sort`).map((f) => readFileSync(f, "utf8")).join("\n");
  return {
    repo_head: gitc(["rev-parse", "HEAD"]),
    branch: gitc(["rev-parse", "--abbrev-ref", "HEAD"]),
    dirty: shCode("git", ["-C", REPO, "status", "--porcelain"]).out.trim().length > 0,
    schema_sha256: sha(readFileSync(resolve(REPO, "db/init/schema.sql"), "utf8")),
    migrations_sha256: sha(migCat),
    proof: PROOF,
    proof_sha256: shaFile(resolve(REPO, PROOF)),
    run_mix_sha256: shaFileOpt(resolve(REPO, "gates/run_mix.py")),
    migration_035_sha256: shaFileOpt(resolve(REPO, MIGRATION_035_PATH)),
    orchestrator_sha256: shaFile(fileURLToPath(import.meta.url)),
  };
}
function enforceSourceIdentity(source) {
  const expect = process.env.EXPECT_SHA?.trim();
  if (!expect || !/^[0-9a-f]{40}$/.test(expect))
    throw new Error("EXPECT_SHA is REQUIRED and must be a full 40-hex commit SHA — exact-source binding is not optional");
  if (source.dirty) throw new Error(`source not clean: worktree ${REPO} is dirty — refusing to accept evidence`);
  if (source.repo_head !== expect) throw new Error(`source SHA ${source.repo_head} != expected EXPECT_SHA ${expect}`);
  exits.source_identity = 0;
  console.log(`[source] accepted head=${source.repo_head.slice(0, 12)} dirty=false (== EXPECT_SHA)`);
}

// ---- the independent census used for the migration-idempotency proof ---------------------------
// Read with psql on the candidate, NOT through the API: an independent path is the point.
const CENSUS_TABLES = ["round", "slot", "content_format", "content_format_version",
                       "baseline_eligibility_policy", "round_policy_snapshot", "principal",
                       "workflow_version", "workflow_stage", "hcs", "lens",
                       "run_mix_recommendation_policy", "run_mix_proposal",
                       "run_mix_recommendation_snapshot"];
function census() {
  const out = {};
  for (const t of CENSUS_TABLES) out[t] = psql(`SELECT count(*) FROM ${t}`);
  // structural census too: a rerun must not add/drop a column, index or trigger.
  out["__columns"] = psql(
    `SELECT string_agg(table_name||'.'||column_name||':'||data_type, ',' ORDER BY table_name, column_name)
     FROM information_schema.columns WHERE table_schema='public'
       AND table_name IN ('run_mix_recommendation_policy','run_mix_proposal','run_mix_recommendation_snapshot','round_policy_snapshot')`);
  out["__indexes"] = psql(
    `SELECT string_agg(indexname, ',' ORDER BY indexname) FROM pg_indexes WHERE schemaname='public'
       AND tablename IN ('run_mix_recommendation_policy','run_mix_proposal','run_mix_recommendation_snapshot','round_policy_snapshot')`);
  out["__triggers"] = psql(
    `SELECT string_agg(trigger_name, ',' ORDER BY trigger_name) FROM information_schema.triggers
     WHERE trigger_schema='public'`);
  return out;
}

function applyMigrations(label) {
  const r = shCode("bash", ["-lc",
    `set -e; for f in $(ls ${REPO}/db/migrations/*.sql | sort); do ` +
    `docker exec -i ${DBC} psql -v ON_ERROR_STOP=1 -U tanaghom -d ${DB} < "$f" >/dev/null; done`]);
  exits[label] = r.code;
  if (r.code !== 0) { process.stderr.write(r.out); throw new Error(`${label} failed (exit ${r.code})`); }
}

// The rerun proof is scoped to THIS directive's migration, and that scope is stated rather than
// hidden. Replaying the whole historical set is not achievable here and never was: 008 recreates
// `asset_id_version_slot_uniq` unguarded, so a full replay aborts on a PRE-EXISTING migration that
// #377 does not touch and is not authorized to change. Claiming a repo-wide rerun proof would be a
// false green; proving 035 is what this directive is answerable for.
const MIGRATION_035 = "db/migrations/035_run_mix_recommendation.sql";
function applyMigration035(label) {
  const r = shCode("bash", ["-lc",
    `docker exec -i ${DBC} psql -v ON_ERROR_STOP=1 -U tanaghom -d ${DB} < ${REPO}/${MIGRATION_035} >/dev/null`]);
  exits[label] = r.code;
  if (r.code !== 0) { process.stderr.write(r.out); throw new Error(`${label} failed (exit ${r.code})`); }
}

async function bringUp() {
  if (!portFree(API_PORT)) throw new Error(`port ${API_PORT} occupied — set API_PORT`);
  const net = shCode("docker", ["network", "create", NET]); exits.network = net.code;
  if (net.code !== 0) { process.stderr.write(net.out); throw new Error(`network create failed (exit ${net.code})`); }
  created.net = true;

  console.log(`[lane ${LANE}] disposable Postgres ${DBC}`);
  const db = shCode("docker", ["run", "-d", "--name", DBC, "--network", NET, "-e", "POSTGRES_USER=tanaghom",
                               "-e", `POSTGRES_PASSWORD=${DB_PW}`, "-e", "POSTGRES_DB=postgres", PG_IMAGE]);
  exits.db = db.code;
  if (db.code !== 0) { process.stderr.write(db.out); throw new Error(`db run failed (exit ${db.code})`); }
  created.db = true;
  const TRANSIENT = /shutting down|starting up|the database system is|no such file or directory|connection refused|could not connect|server closed|the connection/i;
  let ok = 0;
  for (let i = 0; i < 90; i++) {
    const c = shCode("docker", ["exec", DBC, "psql", "-U", "tanaghom", "-d", "postgres", "-tAc", "SELECT 1"]);
    ok = c.code === 0 && c.out.trim() === "1" ? ok + 1 : 0;
    if (ok >= 2) break;
    await sleep(1000);
  }
  if (ok < 2) throw new Error("candidate Postgres never became stably ready");
  let made = false;
  for (let i = 0; i < 30; i++) {
    const c = shCode("docker", ["exec", DBC, "psql", "-U", "tanaghom", "-d", "postgres", "-c", `CREATE DATABASE ${DB}`]);
    if (c.code === 0 || /already exists/.test(c.out)) { made = true; break; }
    if (!TRANSIENT.test(c.out)) { process.stderr.write(c.out); throw new Error("CREATE DATABASE failed"); }
    await sleep(1000);
  }
  if (!made) throw new Error("could not create candidate database");

  console.log(`[lane ${LANE}] committed schema + every migration (fail-fast)`);
  const sch = shCode("bash", ["-lc",
    `docker exec -i ${DBC} psql -v ON_ERROR_STOP=1 -U tanaghom -d ${DB} < ${REPO}/db/init/schema.sql >/dev/null`]);
  exits.schema = sch.code;
  if (sch.code !== 0) { process.stderr.write(sch.out); throw new Error(`schema failed (exit ${sch.code})`); }
  applyMigrations("migrate");

  console.log(`[lane ${LANE}] resolve + LOCK deps (disposable resolver → full freeze)`);
  const res = shCode("docker", ["run", "--rm", "-v", `${REPO}:/work:ro`, "-v", `${PIP_CACHE}:/root/.cache/pip`,
                                "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1", PY_IMAGE, "bash", "-lc",
                                `pip install -q -r /work/${REQS[0]} -r /work/${REQS[1]} >&2 && pip freeze`]);
  exits.lock = res.code;
  if (res.code !== 0) { process.stderr.write(res.out); throw new Error(`dependency lock resolution failed (exit ${res.code})`); }
  const lock = res.out.split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("-e ") && !l.includes(" @ ")).sort();
  writeFileSync(resolve(ARTIFACTS, "requirements.lock.txt"), lock.join("\n") + "\n");

  console.log(`[lane ${LANE}] gate API — CONSUME the lock, stub writer, loopback ${API_PORT}`);
  const apiRun = shCode("docker", ["run", "-d", "--name", APIC, "--network", NET,
    "-e", `DB_HOST=${DBC}`, "-e", "DB_PORT=5432", "-e", "DB_USER=tanaghom", "-e", `DB_PASSWORD=${DB_PW}`,
    "-e", `DB_NAME=${DB}`, "-e", "TANAGHOM_WRITER_STUB=1", "-e", "TANAGHOM_DEV_MODE=1",
    "-e", `REVIEWER_PROXY_SECRET=${SECRET}`, "-e", "TANAGHOM_CONFIG=/work/system_config.example.yaml",
    "-e", "PYTHONPATH=/work:/work/gates:/work/agents:/work/planner", "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1",
    "-v", `${REPO}:/work`, "-v", `${ARTIFACTS}:/lock:ro`, "-v", `${PIP_CACHE}:/root/.cache/pip`,
    "-p", `127.0.0.1:${API_PORT}:8000`, PY_IMAGE, "bash", "-lc",
    `pip install -q --no-deps -r /lock/requirements.lock.txt && exec uvicorn gates.api:app --host 0.0.0.0 --port 8000`]);
  if (apiRun.code !== 0) { exits.api = apiRun.code; process.stderr.write(apiRun.out); throw new Error(`api run failed (exit ${apiRun.code})`); }
  created.api = true;
  let up = false;
  for (let i = 0; i < 180; i++) {
    const h = shCode("bash", ["-lc", `curl -s ${API_BASE}/health`]);
    // EXACT match: `grep stub` also matches `"writer_stub":false` — that trap once burned a token quota.
    if (h.code === 0 && h.out.includes('"writer_mode":"stub"')) { up = true; break; }
    await sleep(1000);
  }
  exits.api = up ? 0 : 1;
  if (!up) { process.stderr.write(shCode("docker", ["logs", "--tail", "40", APIC]).out); throw new Error("gate API not in exact stub mode"); }

  // The served source must BE the accepted source — not a stale image layer.
  const hostApi = shaFile(resolve(REPO, "gates/api.py"));
  const inC = shCode("docker", ["exec", APIC, "sha256sum", "/work/gates/api.py"]).out.trim().split(/\s+/)[0];
  if (inC !== hostApi) throw new Error(`served API source mismatch: container ${inC} != host ${hostApi}`);
  const rmPath = resolve(REPO, "gates/run_mix.py");
  if (existsSync(rmPath)) {
  const hostRm = shaFile(rmPath);
  const inRm = shCode("docker", ["exec", APIC, "sha256sum", "/work/gates/run_mix.py"]).out.trim().split(/\s+/)[0];
  if (inRm !== hostRm) throw new Error(`served run_mix source mismatch: ${inRm} != ${hostRm}`);
  }
  exits.served_binding = 0;
  console.log(`[served] API + run_mix bind-mount == accepted source`);

  const load = shCode("docker", ["exec", "-e", "PYTHONPATH=/work", "-e",
                                 "TANAGHOM_CONFIG=/work/system_config.example.yaml", APIC,
                                 "python", "/work/loader/load_methodology.py"]);
  exits.methodology = load.code;
  if (load.code !== 0) { process.stderr.write(load.out); throw new Error(`methodology load failed (exit ${load.code})`); }
}

function teardown() {
  if (process.env.KEEP) { console.log(`[lane ${LANE}] KEEP set — leaving ${DBC}/${APIC}/${NET}`); return; }
  // -v removes the container's ANONYMOUS volume too. Without it the candidate's Postgres data volume
  // survives teardown and shows up as unrelated-state drift — correctly, because it IS residue.
  if (created.api) shCode("docker", ["rm", "-f", "-v", APIC]);
  if (created.db) shCode("docker", ["rm", "-f", "-v", DBC]);
  if (created.net) shCode("docker", ["network", "rm", NET]);
  console.log(`[lane ${LANE}] torn down`);
}

let failure = null;
const before = snapshotInventory();
const source = sourceIdentity();
try {
  enforceSourceIdentity(source);
  await bringUp();

  // ---- migration idempotency: apply EVERY migration a second time and prove it changed nothing ---
  if (!existsSync(resolve(REPO, MIGRATION_035_PATH))) {
    // Control run at the pre-#377 source: there is no 035 to rerun. Say so rather than
    // silently reporting a proof that did not happen.
    exits.migration_035_idempotent = "n/a — 035 absent at this source";
    console.log(`[migration] 035 absent at this source — rerun proof not applicable`);
  } else {
  console.log(`[lane ${LANE}] 035 rerun (idempotency + non-destructiveness)`);
  // Seed a row FIRST so "existing data survived" is a real assertion rather than a census of zeros.
  // psql echoes the INSERT command tag after the RETURNING value even under -tA; take the value line.
  const seeded = psql(
    `INSERT INTO run_mix_recommendation_policy (scope, generation, status, weights, notes, created_by)
     VALUES ('rerun-probe', 1, 'current', '{"probe":3}'::jsonb, 'pre-rerun row', 'khal')
     RETURNING policy_id::text`).split("\n")[0].trim();
  const censusBefore = census();
  applyMigration035("migrate_035_rerun");
  const censusAfter = census();
  const drift = Object.keys(censusBefore).filter((k) => censusBefore[k] !== censusAfter[k]);
  if (drift.length) throw new Error(`035 rerun changed: ${drift.join(", ")}`);
  const survived = psql(`SELECT weights::text||'|'||coalesce(notes,'') FROM run_mix_recommendation_policy
                         WHERE policy_id='${seeded}'`);
  if (survived !== '{"probe": 3}|pre-rerun row')
    throw new Error(`035 rerun did not preserve the pre-existing row verbatim: ${survived}`);
  psql(`DELETE FROM run_mix_recommendation_policy WHERE policy_id='${seeded}'`);
  exits.migration_035_idempotent = 0;
  console.log(`[migration] 035 rerun is a non-destructive no-op across ${CENSUS_TABLES.length} tables ` +
              `+ columns/indexes/triggers, and preserved a pre-existing operator-owned row verbatim`);
  }

  // ---- the proof itself: API integration + independent DB verification + red proofs --------------
  console.log(`[lane ${LANE}] ${PROOF} (API + independent DB reads)`);
  const args = ["exec", "-e", "PYTHONPATH=/work:/work/gates:/work/agents:/work/planner",
                "-e", "TANAGHOM_CONFIG=/work/system_config.example.yaml",
                "-e", "API_BASE=http://127.0.0.1:8000", "-e", `REVIEWER_PROXY_SECRET=${SECRET}`,
                "-e", "TANAGHOM_WRITER_STUB=1", APIC, "python", `/work/${PROOF}`];
  if (induceFailure) {
    // The induced-failure path must fail LOUDLY and still tear down. Pointing the proof at a database
    // that has never seen the migration makes the failure real, not simulated.
    args.splice(args.indexOf(APIC), 0, "-e", "DB_NAME=postgres");
  }
  const proof = shCode("docker", args);
  process.stdout.write(proof.out);
  exits.selftest = proof.code;
  if (proof.code !== 0) throw new Error(`${PROOF} failed (native exit ${proof.code})`);
} catch (e) {
  failure = e;
} finally {
  teardown();
}

const after = snapshotInventory();
const changed = diffInventory(before, after);
const inventoryClean = Object.keys(changed).length === 0;
exits.inventory = inventoryClean ? 0 : 1;

console.log("\n=== #377 candidate lane evidence ===");
console.log(JSON.stringify({
  lane: LANE, database: DB, api_base: API_BASE, induced_failure: induceFailure,
  source, exits, unrelated_state_changed: changed, inventory_clean: inventoryClean,
  writer_mode: "stub", note: "stub writer posture; this authority performs NO model call at all, so " +
                            "no recommendation-quality claim is made or possible",
}, null, 2));

if (failure) {
  console.error(`\nFAILED: ${failure.message}`);
  process.exit(exits.selftest || 1);
}
if (!inventoryClean) {
  console.error("\nFAILED: unrelated state changed across the run");
  process.exit(1);
}
console.log("\n#377 candidate lane: PASS");
