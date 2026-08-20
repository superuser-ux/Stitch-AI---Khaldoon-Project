#!/usr/bin/env node
// #370 — reusable, platform-neutral V2 lifecycle validation TOPOLOGY. TEST-HARNESS ONLY.
//
// Stands up a FULLY-ISOLATED, candidate-OWNED lane from the current checkout — a disposable pgvector
// Postgres (image pinned by DIGEST), a stub-writer gate API built from a candidate DEPENDENCY LOCK
// generated + consumed before launch (never a commit of an operator container), and the built
// workbench with API_BASE at the candidate, all on a UNIQUE candidate docker network. It captures
// non-mutating SOURCE + PROCESS identity and a named BEFORE/AFTER unrelated-state inventory,
// PREDECLARES a deterministic fixture manifest before any startup, provisions through canonical
// governed routes, verifies EVERY declared identity/count against an independent DB read, persists the
// ownership marker+hash in candidate-owned fixture state, RESETS + REPROVISIONS and re-verifies
// (deterministic identity + changed xmin), reads back the EXACT persisted governed
// decision/comment/gate/audit record for a Script request_change, runs the browser-issued real-`/gw`
// proof with a strict six-category ledger, and tears down in a finally block. It never touches a
// shared/canonical/V1/operator resource, adds no product code, and carries no hard-coded
// path/credential/container-name/occupied-port.
//
// Usage:  EXPECT_SHA=<full 40-hex> node workbench/scripts/v2-validation-lane.mjs [--induce-failure]
//   env: EXPECT_SHA — REQUIRED. The exact committed source SHA to accept; the run fails before startup
//        unless the worktree is clean AND HEAD equals it (fail-closed exact-source binding).
//   env (optional): LANE_ID, PG_IMAGE, PY_IMAGE, API_PORT, WB_PORT, KEEP (skip teardown)
//
// REPRODUCIBILITY (truthful scope). Container images are pinned by DIGEST (content-addressed). A
// candidate dependency LOCK is generated before launch (a full `pip freeze` from a disposable resolver
// over the repo's requirement manifests, pinning EVERY package incl. the one ranged dep) and CONSUMED
// to build the gate API (`pip install --no-deps` from the lock) — the exact resolved set is the input,
// not an after-the-fact archive. Index/hash pinning across time is out of scope and NOT claimed.
//
// EXIT ACCOUNTING (native, never masked). Every phase records its native child exit in `exits`
// independently and preserves the original status even on failure. Exit is 0 ONLY for a green success
// path; the induced-failure run preserves the induced native nonzero. No `|| true`, no masking wrapper.

import { execFileSync, spawn } from "node:child_process";
import { createHmac, createHash, randomBytes } from "node:crypto";
import { existsSync, mkdtempSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { setTimeout as sleep } from "node:timers/promises";
import { dirname, resolve } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const WORKBENCH = resolve(HERE, "..");
const REPO = resolve(WORKBENCH, "..");
const induceFailure = process.argv.includes("--induce-failure");
// #373 — the proof SPEC and its expected test count are env-parameterizable (minimal harness
// extension) so the SAME fail-closed topology drives the #370 real-route proof OR the #373 browser
// operator-journey acceptance. Defaults preserve #370 exactly.
const SPEC = process.env.PROOF_SPEC || "e2e/v2-lifecycle-realroute-370.spec.ts";
// #372 — PROOF_SPEC may name MULTIPLE whitespace-separated specs so one fail-closed run can execute a
// matrix whose rows span more than one committed spec. Single-spec default preserves #370/#373.
const SPECS = SPEC.trim().split(/\s+/).filter(Boolean);
const EXPECTED_TESTS = Number(process.env.PROOF_EXPECTED_TESTS || 3);
const PRINCIPAL = "khal";
// #376 FIX-01 / ruling E — the fixture MODE. `lifecycle` (default) predeclares the three #370 runs and
// preserves every existing lane run byte-for-byte. `zero-run` predeclares NO runs: the lane comes up
// with governed configuration established and an EMPTY run set, which is the only honest shape for the
// retained human-UAT lane (a lane carrying 23 scenario runs cannot be called a clean no-run lane) and
// the only shape in which CAL-01 — "the root calendar with zero runs" — can be proven at all.
const FIXTURE = process.env.FIXTURE || "lifecycle";
if (!["lifecycle", "zero-run"].includes(FIXTURE)) throw new Error(`unknown FIXTURE ${FIXTURE}`);
// #376 STG-01/STG-02 — mint the governed workflow GENERATION this directive needs (sign-off stages
// disabled, `final_review` labelled `Approved for production`) through the AUTHORIZED draft → update →
// activate path. OFF by default so every existing lane keeps the baseline generation its evidence was
// recorded against; the #376 matrix and the human lane turn it on explicitly.
const GOVERNED_GEN_376 = process.env.GOVERNED_GEN_376 === "1";
// #376 ruling D — mint a CURRENT run-mix recommendation-policy generation. OFF by default, because
// MIX-03 must observe a lane with NO current generation (typed blocked) and MIX-01 must observe one
// WITH it. The two preconditions are deliberately distinct and neither may masquerade as the other;
// the matrix spec establishes MIX-01's generation itself, and the retained human lane sets this.
const RUN_MIX_POLICY = process.env.RUN_MIX_POLICY === "1";

const LANE = process.env.LANE_ID || `v2val-${randomBytes(3).toString("hex")}`;
const PG_IMAGE = process.env.PG_IMAGE || "pgvector/pgvector:pg16@sha256:0a07c4114ba6d1d04effcce3385e9f5ce305eb02e56a3d35948a415a52f193ec";
const PY_IMAGE = process.env.PY_IMAGE || "python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e";
const NET = `tan-${LANE}-net`;
const DBC = `tan-${LANE}-db`;
const APIC = `tan-${LANE}-api`;
const DB = `tan_${LANE.replace(/-/g, "_")}`;
const DB_PW = randomBytes(9).toString("hex");
const SECRET = randomBytes(24).toString("hex");
const API_PORT = Number(process.env.API_PORT || 8391);
const WB_PORT = Number(process.env.WB_PORT || 3091);
const API_BASE = `http://127.0.0.1:${API_PORT}`;
const WB_URL = `http://localhost:${WB_PORT}`;
const REQS = ["gates/requirements.txt", "agents/requirements.txt"];
const ARTIFACTS = mkdtempSync(resolve(tmpdir(), `v2val-${LANE}-`));
const PIP_CACHE = resolve(ARTIFACTS, "pipcache"); mkdirSync(PIP_CACHE, { recursive: true });
const LOCK_HOST = resolve(ARTIFACTS, "requirements.lock.txt");

const created = { net: false, db: false, api: false, wb: null };
const exits = {};
let wbProc = null;

function shCode(cmd, args, opts = {}) {
  try { const out = execFileSync(cmd, args, { encoding: "utf8", stdio: "pipe", ...opts }); return { code: 0, out }; }
  catch (e) { return { code: e.status ?? 1, out: (e.stdout || "") + (e.stderr || "") }; }
}
function sh(cmd, args, opts = {}) { return execFileSync(cmd, args, { encoding: "utf8", stdio: opts.capture ? "pipe" : "inherit", ...opts }); }
function docker(args, opts) { return sh("docker", args, opts); }
function psql(s) { return docker(["exec", DBC, "psql", "-U", "tanaghom", "-d", DB, "-tAc", s], { capture: true }).trim(); }
function psqlCode(s) { return shCode("docker", ["exec", DBC, "psql", "-U", "tanaghom", "-d", DB, "-v", "ON_ERROR_STOP=1", "-tAc", s]); }
function q(s) { return String(s).replace(/'/g, "''"); }
function sign(p = PRINCIPAL) {
  return { "x-principal-id": p, "x-principal-signature": createHmac("sha256", SECRET).update(p).digest("hex"), "content-type": "application/json" };
}
async function api(method, path, body, signed = true) {
  const r = await fetch(API_BASE + path, { method, headers: signed ? sign() : { "content-type": "application/json" },
                                           body: body !== undefined ? JSON.stringify(body) : undefined });
  const t = await r.text();
  return { status: r.status, body: t ? JSON.parse(t) : {} };
}
function portFree(p) { return shCode("bash", ["-lc", `lsof -tnP -iTCP:${p} -sTCP:LISTEN`]).out.trim() === ""; }
function sha(o) { return createHash("sha256").update(typeof o === "string" ? o : JSON.stringify(o)).digest("hex"); }
function lines(cmd) { return shCode("bash", ["-lc", cmd]).out.split("\n").map((s) => s.trim()).filter(Boolean).sort(); }

// ---- gap 2/3: named BEFORE/AFTER unrelated-state inventory (fail on mismatch) -----------------------
const CONFIG_FILES = ["system_config.example.yaml", "docker-compose.yml", ".env"];
function shaFile(p) { return createHash("sha256").update(readFileSync(p)).digest("hex"); }
function configContentSha() {   // bounded config set, incl. an untracked .env if present
  return sha(CONFIG_FILES.map((f) => { const p = resolve(REPO, f); return `${f}:${existsSync(p) ? shaFile(p) : "absent"}`; }).join("|"));
}
function postgresContainers() {
  // NON-MUTATING discovery of running PostgreSQL containers from image metadata (no hard-coded operator
  // name). Each entry is a container identity + its logical DB set; a change to any of them across the
  // run reveals cross-container mutation. The candidate never appears here (the before-snapshot precedes
  // its creation and the after-snapshot follows its removal); it is also excluded by name defensively.
  const rows = lines(`docker ps --format '{{.ID}}\t{{.Image}}\t{{.Names}}'`);
  const out = [];
  for (const row of rows) {
    const [id, image, name] = row.split("\t");
    if (!/postgres|pgvector/i.test(image)) continue;
    if (name === DBC || name.startsWith(`tan-${LANE}-`)) continue;
    const env = shCode("docker", ["inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", id]).out;
    const userLine = env.split("\n").find((l) => l.startsWith("POSTGRES_USER="));
    const user = userLine ? userLine.slice("POSTGRES_USER=".length).trim() : "postgres";
    const r = shCode("docker", ["exec", id, "psql", "-U", user, "-d", "postgres", "-tAc", "SELECT datname FROM pg_database ORDER BY 1"]);
    const dbs = r.code === 0 ? r.out.split("\n").map((s) => s.trim()).filter(Boolean).sort() : ["<unreadable>"];
    out.push(`name=${name} image=${image} id=${id} dbs=[${dbs.join(",")}]`);
  }
  return out.sort();
}
function listeningPorts() {     // the set of listening TCP ports (catches a lingering candidate port)
  return [...new Set(lines(`lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $9}' | sed 's/.*://' | grep -E '^[0-9]+$'`))].sort((a, b) => Number(a) - Number(b));
}
function snapshotInventory() {
  return {
    containers: lines("docker ps -aq"),
    networks: lines("docker network ls --format '{{.Name}}'"),
    volumes: lines("docker volume ls -q"),
    worktrees: lines(`git -C ${REPO} worktree list --porcelain | awk '/^worktree /{print $2}'`),
    listeners: listeningPorts(),
    postgres_containers: postgresContainers(),
    tracked_status_sha: sha(shCode("bash", ["-lc", `git -C ${REPO} status --porcelain`]).out),
    config_content_sha: configContentSha(),
  };
}
function diffInventory(before, after) {
  const changed = {};
  for (const k of ["containers", "networks", "volumes", "worktrees", "listeners", "postgres_containers"]) {
    const b = new Set(before[k]); const a = new Set(after[k]);
    const added = after[k].filter((x) => !b.has(x)); const removed = before[k].filter((x) => !a.has(x));
    if (added.length || removed.length) changed[k] = { added, removed };
  }
  for (const k of ["tracked_status_sha", "config_content_sha"]) {
    if (before[k] !== after[k]) changed[k] = { before: before[k], after: after[k] };
  }
  return changed;
}

// ---- gap 2: non-mutating SOURCE identity (exact served source of truth) -----------------------------
function sourceIdentity() {
  const gitc = (a) => shCode("git", ["-C", REPO, ...a]).out.trim();
  const migCat = lines(`ls ${REPO}/db/migrations/*.sql | sort`).map((f) => readFileSync(f, "utf8")).join("\n");
  return {
    repo_head: gitc(["rev-parse", "HEAD"]),
    branch: gitc(["rev-parse", "--abbrev-ref", "HEAD"]),
    worktree: REPO,
    dirty: shCode("git", ["-C", REPO, "status", "--porcelain"]).out.trim().length > 0,
    schema_sha256: sha(readFileSync(resolve(REPO, "db/init/schema.sql"), "utf8")),
    migrations_sha256: sha(migCat),
    spec_sha256: sha(SPECS.map((f) => readFileSync(resolve(WORKBENCH, f), "utf8")).join("\n")),
    orchestrator_sha256: sha(readFileSync(fileURLToPath(import.meta.url), "utf8")),
  };
}
// ---- gap 1: ENFORCE source identity (fail-closed BEFORE accepting evidence) -------------------------
// A dirty worktree or an unintended commit must never reach SATISFIED. The expected SHA is an explicit
// input (EXPECT_SHA); the tree must be clean; both are checked before any evidence is accepted.
function enforceSourceIdentity(source) {
  const expect = process.env.EXPECT_SHA?.trim();
  if (!expect || !/^[0-9a-f]{40}$/.test(expect))
    throw new Error("EXPECT_SHA is REQUIRED and must be a full 40-hex commit SHA — exact-source binding is not optional");
  if (source.dirty) throw new Error(`source not clean: worktree ${REPO} is dirty — refusing to accept evidence`);
  if (source.repo_head !== expect) throw new Error(`source SHA ${source.repo_head} != expected EXPECT_SHA ${expect}`);
  exits.source_identity = 0;
  console.log(`[source] accepted head=${source.repo_head.slice(0, 12)} dirty=false (== EXPECT_SHA)`);
}
// The bind-mounted API source and the built workbench must come from that SAME accepted identity.
function assertServedBinding(source) {
  const hostApiSha = shaFile(resolve(REPO, "gates/api.py"));
  const inC = shCode("docker", ["exec", APIC, "sha256sum", "/work/gates/api.py"]).out.trim().split(/\s+/)[0];
  if (inC !== hostApiSha) throw new Error(`served API source mismatch: container ${inC} != host ${hostApiSha} (bind mount not the accepted source)`);
  const buildIdPath = resolve(WORKBENCH, ".next/BUILD_ID");
  if (!existsSync(buildIdPath)) throw new Error("workbench build id missing — build not produced from the accepted source");
  const buildId = readFileSync(buildIdPath, "utf8").trim();
  exits.served_binding = 0;
  console.log(`[served] API bind-mount == accepted source (${hostApiSha.slice(0, 12)}); workbench build_id=${buildId}`);
  return { accepted_head: source.repo_head, api_source_sha256: hostApiSha, api_source_in_container_sha256: inC, workbench_build_id: buildId };
}
// ---- gap 2: PROCESS identity (exact served process + served bundle) --------------------------------
function processIdentity() {
  const insp = (name, fmt) => shCode("docker", ["inspect", "-f", fmt, name]).out.trim();
  const buildIdPath = resolve(WORKBENCH, ".next/BUILD_ID");
  return {
    api: {
      container_id: insp(APIC, "{{.Id}}"), image_id: insp(APIC, "{{.Image}}"), image_ref: PY_IMAGE,
      served_source: `${REPO}:/work (bind mount)`, cmd: insp(APIC, "{{json .Config.Cmd}}"),
      db_container_id: insp(DBC, "{{.Id}}"), db_image_ref: PG_IMAGE,
    },
    workbench: {
      pid: wbProc ? wbProc.pid : null, cmd: `next start -p ${WB_PORT}`, cwd: WORKBENCH,
      api_base: API_BASE, build_id: existsSync(buildIdPath) ? readFileSync(buildIdPath, "utf8").trim() : null,
    },
  };
}

// ---- gap 2: PREDECLARED deterministic manifest (before any startup) --------------------------------
function predeclareManifest() {
  const marker = `candidate:${LANE}`;
  const mk = (key, ordinal, status) => ({ label: `370-${key}-${marker}`, round_id: `R${ordinal}`, status, count: 3,
                                          slots: [1, 2, 3].map((m) => `R${ordinal}-D01-S${m}`) });
  const runs = FIXTURE === "zero-run"
    ? {}                        // #376 — predeclared EMPTY: the lane's declared identity IS "no runs"
    : { schedule: mk("schedule", 1, "RESERVED"), topic: mk("topic", 2, "TOPIC_PROPOSED"), script: mk("script", 3, "DRAFT_ASSIGNED") };
  const workspace = { tenant_id: "default", database: DB, lane: LANE, network: NET };
  return { candidate: LANE, database: DB, workspace, marker, runs, identity_sha256: sha({ workspace, marker, runs: identityShape(runs) }) };
}
function identityShape(runs) {
  return Object.fromEntries(Object.entries(runs).map(([k, v]) =>
    [k, { round_id: v.round_id, label: v.label, status: v.status, count: v.count, slots: [...v.slots].sort() }]));
}

async function bringUp() {
  if (!portFree(API_PORT) || !portFree(WB_PORT)) throw new Error(`port ${API_PORT}/${WB_PORT} occupied — set API_PORT/WB_PORT`);

  const net = shCode("docker", ["network", "create", NET]); exits.network = net.code;
  if (net.code !== 0) { process.stderr.write(net.out); throw new Error(`network create failed (exit ${net.code})`); }
  created.net = true;

  console.log(`[lane ${LANE}] disposable Postgres ${DBC}`);
  const db = shCode("docker", ["run", "-d", "--name", DBC, "--network", NET, "-e", "POSTGRES_USER=tanaghom",
          "-e", `POSTGRES_PASSWORD=${DB_PW}`, "-e", "POSTGRES_DB=postgres", PG_IMAGE]);
  exits.db = db.code;
  if (db.code !== 0) { process.stderr.write(db.out); throw new Error(`db run failed (exit ${db.code})`); }
  created.db = true;
  // The pgvector image runs initdb on a temporary server first (answers, then shuts down + restarts),
  // so require TWO consecutive real queries, then retry CREATE DATABASE across any transient
  // startup/shutdown/socket window.
  const TRANSIENT = /shutting down|starting up|the database system is|no such file or directory|connection refused|could not connect|server closed|the connection/i;
  let ok = 0;
  for (let i = 0; i < 90; i++) {
    const c = shCode("docker", ["exec", DBC, "psql", "-U", "tanaghom", "-d", "postgres", "-tAc", "SELECT 1"]);
    ok = c.code === 0 && c.out.trim() === "1" ? ok + 1 : 0;
    if (ok >= 2) break;
    await sleep(1000);
  }
  if (ok < 2) throw new Error("candidate Postgres never became stably ready");
  let dbMade = false;
  for (let i = 0; i < 30; i++) {
    const c = shCode("docker", ["exec", DBC, "psql", "-U", "tanaghom", "-d", "postgres", "-c", `CREATE DATABASE ${DB}`]);
    if (c.code === 0 || /already exists/.test(c.out)) { dbMade = true; break; }
    if (!TRANSIENT.test(c.out)) { process.stderr.write(c.out); throw new Error("CREATE DATABASE failed"); }
    await sleep(1000);
  }
  if (!dbMade) throw new Error("could not create candidate database");

  console.log(`[lane ${LANE}] schema + every migration (fail-fast)`);
  const mig = shCode("bash", ["-lc",
    `set -e; docker exec -i ${DBC} psql -v ON_ERROR_STOP=1 -U tanaghom -d ${DB} < ${REPO}/db/init/schema.sql >/dev/null; ` +
    `for f in $(ls ${REPO}/db/migrations/*.sql | sort); do docker exec -i ${DBC} psql -v ON_ERROR_STOP=1 -U tanaghom -d ${DB} < "$f" >/dev/null; done`]);
  exits.migrate = mig.code;
  if (mig.code !== 0) { process.stderr.write(mig.out); throw new Error(`migrate failed (exit ${mig.code})`); }

  // gap 4: GENERATE the candidate dependency lock BEFORE launch (disposable resolver → full pip freeze).
  console.log(`[lane ${LANE}] resolve + LOCK deps (disposable resolver → full freeze)`);
  const res = shCode("docker", ["run", "--rm", "-v", `${REPO}:/work:ro`, "-v", `${PIP_CACHE}:/root/.cache/pip`,
          "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1", PY_IMAGE, "bash", "-lc",
          `pip install -q -r /work/${REQS[0]} -r /work/${REQS[1]} >&2 && pip freeze`]);
  exits.lock = res.code;
  if (res.code !== 0) { process.stderr.write(res.out); throw new Error(`dependency lock resolution failed (exit ${res.code})`); }
  const lock = res.out.split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("-e ") && !l.includes(" @ ")).sort();
  if (!lock.some((l) => /^openai==/.test(l))) throw new Error("lock did not pin openai to an exact version");
  writeFileSync(LOCK_HOST, lock.join("\n") + "\n");

  console.log(`[lane ${LANE}] gate API — CONSUME the lock (pip install --no-deps), stub, loopback ${API_PORT}`);
  const apiRun = shCode("docker", ["run", "-d", "--name", APIC, "--network", NET,
          "-e", `DB_HOST=${DBC}`, "-e", "DB_PORT=5432", "-e", "DB_USER=tanaghom", "-e", `DB_PASSWORD=${DB_PW}`, "-e", `DB_NAME=${DB}`,
          "-e", "TANAGHOM_WRITER_STUB=1", "-e", "TANAGHOM_DEV_MODE=1", "-e", `REVIEWER_PROXY_SECRET=${SECRET}`,
          "-e", "TANAGHOM_CONFIG=/work/system_config.example.yaml", "-e", "PYTHONPATH=/work:/work/gates:/work/agents",
          "-e", "PIP_DISABLE_PIP_VERSION_CHECK=1",
          "-v", `${REPO}:/work`, "-v", `${ARTIFACTS}:/lock:ro`, "-v", `${PIP_CACHE}:/root/.cache/pip`,
          "-p", `127.0.0.1:${API_PORT}:8000`,
          PY_IMAGE, "bash", "-lc",
          `pip install -q --no-deps -r /lock/requirements.lock.txt && exec uvicorn gates.api:app --host 0.0.0.0 --port 8000`]);
  if (apiRun.code !== 0) { exits.api = apiRun.code; process.stderr.write(apiRun.out); throw new Error(`api run failed (exit ${apiRun.code})`); }
  created.api = true;
  let apiUp = false;
  for (let i = 0; i < 150; i++) {
    const h = shCode("bash", ["-lc", `curl -s ${API_BASE}/health`]);
    if (h.code === 0 && h.out.includes('"writer_mode":"stub"')) { apiUp = true; break; }
    await sleep(1000);
  }
  exits.api = apiUp ? 0 : 1;
  if (!apiUp) { process.stderr.write(shCode("docker", ["logs", "--tail", "40", APIC]).out); throw new Error("gate API not in exact stub mode"); }
  docker(["exec", "-e", "PYTHONPATH=/work", "-e", "TANAGHOM_CONFIG=/work/system_config.example.yaml", APIC,
          "python", "/work/loader/load_methodology.py"], { capture: true });

  console.log(`[lane ${LANE}] workbench build + start (API_BASE=candidate, port ${WB_PORT})`);
  if (!existsSync(resolve(WORKBENCH, "node_modules/.bin/next"))) sh("pnpm", ["install", "--frozen-lockfile", "--prefer-offline"], { cwd: WORKBENCH });
  const build = shCode(resolve(WORKBENCH, "node_modules/.bin/next"), ["build"], { cwd: WORKBENCH, env: { ...process.env, API_BASE, REVIEWER_PROXY_SECRET: SECRET } });
  exits.wb_build = build.code;
  if (build.code !== 0) { process.stdout.write(build.out); throw new Error(`workbench build failed (exit ${build.code})`); }
  wbProc = spawn(resolve(WORKBENCH, "node_modules/.bin/next"), ["start", "-p", String(WB_PORT)],
    { cwd: WORKBENCH, env: { ...process.env, PORT: String(WB_PORT), TANAGHOM_DEV_MODE: "1", API_BASE, REVIEWER_PROXY_SECRET: SECRET },
      stdio: "ignore", detached: false });
  created.wb = wbProc.pid;
  let wbUp = false;
  for (let i = 0; i < 40; i++) { if (shCode("bash", ["-lc", `curl -s -o /dev/null -w '%{http_code}' ${WB_URL}/`]).out === "200") { wbUp = true; break; } await sleep(1000); }
  exits.wb_start = wbUp ? 0 : 1;
  if (!wbUp) throw new Error("workbench never became ready (200) — startup phase failed");   // ASSERT readiness
}

// gap 4/2: verify the running deps EQUAL the consumed lock — FAIL-CLOSED, dedicated native result.
function verifyDeps() {
  const lockTxt = readFileSync(LOCK_HOST, "utf8");
  const freeze = shCode("docker", ["exec", APIC, "pip", "freeze"]).out.trim();
  const freezePath = resolve(ARTIFACTS, `pip-freeze-${LANE}.txt`); writeFileSync(freezePath, freeze + "\n");
  const norm = (s) => s.split("\n").map((l) => l.trim()).filter(Boolean).sort().join("\n");
  const matches = sha(norm(freeze)) === sha(norm(lockTxt));
  exits.deps_verify = matches ? 0 : 1;
  if (!matches) throw new Error("dependency verification failed: the running installed set != the consumed lock");
  return {
    reproducibility: "images pinned by digest; a candidate dependency LOCK (full pip freeze, every package incl. the one ranged dep pinned ==) is generated before launch and CONSUMED to build the gate API via `pip install --no-deps`; the running set is ASSERTED equal to the lock (fail-closed). Index/hash pinning across time is out of scope and NOT claimed.",
    images: { python: PY_IMAGE, postgres: PG_IMAGE }, requirements: REQS,
    lock_artifact: LOCK_HOST, lock_sha256: sha(lockTxt), lock_package_count: lockTxt.split("\n").filter(Boolean).length,
    installed_freeze_artifact: freezePath, installed_matches_lock: true,
  };
}

function persistManifest(EXP) {
  const detail = JSON.stringify({ identity_sha256: EXP.identity_sha256, marker: EXP.marker, workspace: EXP.workspace, runs: identityShape(EXP.runs) });
  const r = psqlCode(`INSERT INTO audit_log(entity, entity_id, action, actor, detail) ` +
    `VALUES ('v2val_manifest','${q(LANE)}','predeclared','v2-validation-lane','${q(detail)}'::jsonb)`);
  if (r.code !== 0) { process.stderr.write(r.out); throw new Error("failed to persist predeclared manifest into candidate fixture state"); }
}

const governedSetup = {};

async function provisionFixture(EXP, phase) {
  const gate = async (rid, stage) => {
    const g = (await api("POST", "/gates", { stage, round_id: rid })).body;
    const gid = g.gate_id || g.gate?.gate_id;
    await api("POST", `/gates/${gid}/decide`, { decision: "approve" });
    await api("POST", `/gates/${gid}/resolve`, {});
  };
  const elig = (await api("GET", "/baseline-eligibility", undefined, false)).body;
  const fw = (elig.eligible || elig.frameworks || [])[0].name;
  if (FIXTURE === "zero-run") {
    // A fresh candidate database has NO active workflow version, so a zero-run lane would otherwise
    // open with an empty stage rail — an unusable human lane and an untruthful FIX-01. Establish the
    // baseline generation through its own authorized seeding read (create-missing-only: it returns the
    // existing active version when there is one and never rewrites operator-owned configuration).
    const base = await api("GET", "/workflow-versions/active", undefined, false);
    if (base.status !== 200) throw new Error(`zero-run setup: no baseline workflow generation (${base.status})`);
    governedSetup.workflow_baseline = base.body.version_id || base.body.version?.version_id || null;
    // Governed CONFIGURATION is established once, on the first provision. The reset step truncates
    // RUNS only — configuration generations are not run data and are deliberately not re-minted, so a
    // reprovision cannot quietly stack extra generations under an operator.
    if (phase === "provision") {
      if (GOVERNED_GEN_376) governedSetup.workflow_376 = await governedWorkflowGeneration376();
      if (RUN_MIX_POLICY) governedSetup.run_mix_policy = await governedRunMixPolicy();
    }
    return verifyAgainstDeclared(EXP, phase);
  }
  for (const [key, dec] of [["schedule", EXP.runs.schedule], ["topic", EXP.runs.topic], ["script", EXP.runs.script]]) {
    const rid = (await api("POST", "/rounds", { days: 1, posts_per_day: 3, label: dec.label, format_mix: { [fw]: 3 } })).body.round_id;
    if (key !== "schedule") { await gate(rid, "schedule_review"); await sleep(1500); }
    if (key === "script") { await gate(rid, "topic_review"); await sleep(2000); }
  }
  return verifyAgainstDeclared(EXP, phase);
}

function verifyAgainstDeclared(EXP, phase) {
  const tenants = psql("SELECT DISTINCT tenant_id FROM methodology").split("\n").filter(Boolean);
  if (!(tenants.length === 1 && tenants[0] === EXP.workspace.tenant_id))
    throw new Error(`${phase}: workspace tenant ${JSON.stringify(tenants)} != declared ${EXP.workspace.tenant_id}`);
  const labels = psql("SELECT label FROM round ORDER BY label").split("\n").filter(Boolean);
  const declaredLabels = Object.values(EXP.runs).map((r) => r.label).sort();
  if (JSON.stringify(labels.slice().sort()) !== JSON.stringify(declaredLabels))
    throw new Error(`${phase} ownership: rounds ${JSON.stringify(labels)} != declared ${JSON.stringify(declaredLabels)}`);
  if (!labels.every((l) => l.includes(EXP.marker))) throw new Error(`${phase}: a round is not marked ${EXP.marker}`);

  const actualRuns = {};
  for (const [key, dec] of Object.entries(EXP.runs)) {
    const rid = psql(`SELECT round_id FROM round WHERE label='${q(dec.label)}'`);
    if (rid !== dec.round_id) throw new Error(`${phase} ${key}: round_id ${rid} != declared ${dec.round_id}`);
    const rows = psql(`SELECT slot_id||'|'||status FROM slot WHERE round_id='${q(rid)}' ORDER BY slot_id`)
      .split("\n").filter(Boolean).map((r) => { const [slot_id, status] = r.split("|"); return { slot_id, status }; });
    const slots = rows.map((r) => r.slot_id).sort();
    const statuses = [...new Set(rows.map((r) => r.status))];
    if (slots.length !== dec.count) throw new Error(`${phase} ${key}: expected exactly ${dec.count} slots, got ${slots.length}`);
    if (JSON.stringify(slots) !== JSON.stringify([...dec.slots].sort())) throw new Error(`${phase} ${key}: slot ids ${JSON.stringify(slots)} != declared ${JSON.stringify(dec.slots)}`);
    if (!(statuses.length === 1 && statuses[0] === dec.status)) throw new Error(`${phase} ${key}: lifecycle ${JSON.stringify(statuses)} != declared ${dec.status}`);
    actualRuns[key] = { round_id: rid, label: dec.label, status: statuses[0], count: slots.length, slots };
  }
  const actualHash = sha({ workspace: EXP.workspace, marker: EXP.marker, runs: identityShape(actualRuns) });
  if (actualHash !== EXP.identity_sha256) throw new Error(`${phase}: identity hash ${actualHash} != declared ${EXP.identity_sha256}`);
  const persisted = psql(`SELECT detail->>'identity_sha256' FROM audit_log WHERE entity='v2val_manifest' AND action='predeclared' AND entity_id='${q(LANE)}' ORDER BY id DESC LIMIT 1`);
  if (persisted !== EXP.identity_sha256) throw new Error(`${phase}: persisted identity hash ${persisted} != declared ${EXP.identity_sha256}`);
  console.log(`[verify:${phase}] declared identities+counts matched; identity=${actualHash.slice(0, 12)} persisted=ok`);
  return { runs: actualRuns, identity_sha256: actualHash };
}

// ---- #376 governed SETUP (never a browser control, never a seed rewrite) ---------------------------
//
// Both of these establish configuration through the ALREADY-AUTHORIZED canonical mechanisms and touch
// no active generation in place:
//   * the workflow generation is a DRAFT cloned from the active one, edited while it is a draft, then
//     activated — `update_workflow_version` refuses a non-draft, so the active generation is never
//     mutated, and nothing is reseeded, reset or renamed underneath an operator;
//   * the run-mix policy is a NEW generation minted by the authority itself (#377), which supersedes
//     the previous current one rather than editing it (the DB trigger refuses an in-place edit).
// Both are idempotent-by-intent for a lane: the lane is disposable and starts from an empty candidate
// database, so these CREATE missing configuration and overwrite none.
async function governedWorkflowGeneration376() {
  const draft = await api("POST", "/workflows/content_pipeline/versions/draft", {});
  if (draft.status !== 200) throw new Error(`governed setup: workflow draft failed ${draft.status} ${JSON.stringify(draft.body)}`);
  const versionId = draft.body.version_id || draft.body.version?.version_id;
  if (!versionId) throw new Error(`governed setup: no draft version_id in ${JSON.stringify(draft.body)}`);
  const active = (await api("GET", "/workflow-stages/active", undefined, false)).body;
  const stages = (active.stages || []).map((s) => ({
    ...s,
    // The two sign-off stages the operator's configuration does not run. Disabled IN THE GENERATION —
    // this is governed data, not a frontend omission list, and re-enabling them in a later generation
    // brings them back with no code change.
    enabled: ["native_review", "scholar_review"].includes(s.stage_key) ? false : s.enabled,
    // Ruling B — ONE governed label, rendered verbatim wherever the stage appears. No frontend alias,
    // no derived completion string, no seed rewrite, no new schema field.
    stage_label: s.stage_key === "final_review" ? "Approved for production" : s.stage_label,
  }));
  if (!stages.some((s) => s.stage_key === "final_review")) throw new Error("governed setup: no final_review stage to relabel");
  const put = await api("PUT", `/workflow-versions/${versionId}`, { notes: "#376 governed generation", stages });
  if (put.status !== 200) throw new Error(`governed setup: workflow update failed ${put.status} ${JSON.stringify(put.body)}`);
  const act = await api("POST", `/workflow-versions/${versionId}/activate`, {});
  if (act.status !== 200) throw new Error(`governed setup: workflow activate failed ${act.status} ${JSON.stringify(act.body)}`);
  const proj = (await api("GET", "/workflow-stages/active-enabled", undefined, false)).body;
  const keys = (proj.stages || []).map((s) => s.stage_key);
  if (keys.includes("native_review") || keys.includes("scholar_review"))
    throw new Error(`governed setup: disabled stages still projected: ${JSON.stringify(keys)}`);
  const finalLabel = (proj.stages || []).find((s) => s.stage_key === "final_review")?.stage_label;
  if (finalLabel !== "Approved for production")
    throw new Error(`governed setup: final_review label is ${JSON.stringify(finalLabel)}`);
  console.log(`[governed-setup] workflow generation ${versionId}: sign-offs disabled, final_review="${finalLabel}", disabled_stage_count=${proj.disabled_stage_count}`);
  return { version_id: versionId, projected_stage_keys: keys, final_review_label: finalLabel, disabled_stage_count: proj.disabled_stage_count };
}

async function governedRunMixPolicy() {
  const elig = (await api("GET", "/baseline-eligibility", undefined, false)).body;
  const eligible = elig.eligible || elig.frameworks || [];
  if (!eligible.length) throw new Error("governed setup: baseline eligibility offers no framework to weight");
  // Weights are keyed by the framework VERSION id (#377), so a later rename cannot re-point a governed
  // weight. Equal weights here are an OPERATOR DECLARATION for a disposable lane — never a fallback,
  // and never computed by the UI.
  const weights = {};
  for (const f of eligible) {
    const vid = f.version_id || f.content_format_version_id || f.id;
    if (!vid) throw new Error(`governed setup: eligible framework ${JSON.stringify(f)} carries no version id`);
    weights[vid] = 1;
  }
  const res = await api("POST", "/run-mix-policy", { weights, notes: "#376 lane governed run-mix policy" });
  if (res.status !== 200) throw new Error(`governed setup: run-mix policy failed ${res.status} ${JSON.stringify(res.body)}`);
  const cur = (await api("GET", "/run-mix-policy", undefined, false)).body;
  if (cur.status !== "current") throw new Error(`governed setup: no current run-mix policy after minting: ${JSON.stringify(cur)}`);
  console.log(`[governed-setup] run-mix policy generation ${cur.generation} current over ${Object.keys(weights).length} framework version(s)`);
  return { generation: cur.generation, weighted_versions: Object.keys(weights).length };
}

async function resetAndReprovision(EXP) {
  console.log(`[lane ${LANE}] reset (TRUNCATE round CASCADE — candidate DB only) + reprovision`);
  const physBefore = psql("SELECT slot_id||':'||xmin FROM slot ORDER BY slot_id").split("\n").filter(Boolean);
  const reset = psqlCode("TRUNCATE round CASCADE"); exits.reset = reset.code;
  if (reset.code !== 0) { process.stderr.write(reset.out); throw new Error(`reset failed (exit ${reset.code})`); }
  if (Number(psql("SELECT count(*) FROM round")) !== 0) throw new Error("reset incomplete: rounds remain");
  const second = await provisionFixture(EXP, "reprovision"); exits.reprovision = 0;
  const physAfter = psql("SELECT slot_id||':'||xmin FROM slot ORDER BY slot_id").split("\n").filter(Boolean);
  // #376 — a zero-run fixture declares NO rows, so "rows were physically re-created" is not a claim it
  // can make. Asserting it would fail a correct lane; silently dropping it for every mode would weaken
  // the #370 proof. So the assertion is kept exactly as-is for the lifecycle fixture and reported as
  // not-applicable here, rather than quietly passing.
  const recreated = FIXTURE === "zero-run" ? null : JSON.stringify(physBefore) !== JSON.stringify(physAfter);
  if (recreated === false) throw new Error("reprovision did not re-create rows (identical xmin — stale/cached)");
  if (FIXTURE === "zero-run" && (physBefore.length || physAfter.length))
    throw new Error("zero-run fixture: slots exist where none are declared");
  console.log(`[reprovision] deterministic_identity=${second.identity_sha256 === EXP.identity_sha256} physically_recreated=${recreated}`);
  return { ...second, reprovision: { deterministic_identity: true, physically_recreated: recreated } };
}

async function verifyDecisionRecord(EXP) {
  const slot = EXP.runs.script.slots[0];
  const comment = `370-decision-audit ${LANE} ${randomBytes(4).toString("hex")}`;
  const res = await fetch(`${WB_URL}/gw/slots/${slot}/request_change`, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ artifact: "script", comment }) });
  const body = await res.json();
  if (res.status !== 200 || !body.decision_recorded) throw new Error(`decision-verify: request_change failed ${res.status} ${JSON.stringify(body)}`);
  const gid = body.result?.gate_id;
  if (!gid) throw new Error("decision-verify: no gate_id returned");
  const dec = psql(`SELECT decision||'|'||coalesce(notes,'')||'|'||approver_id FROM gate_decision WHERE gate_id='${q(gid)}' AND slot_id='${q(slot)}'`);
  const [decision, notes, approver] = dec.split("|");
  if (decision !== "request_change") throw new Error(`decision-verify: gate_decision.decision '${decision}' != request_change`);
  if (notes !== comment) throw new Error(`decision-verify: gate_decision.notes '${notes}' != '${comment}'`);
  if (approver !== PRINCIPAL) throw new Error(`decision-verify: gate_decision.approver_id '${approver}' != '${PRINCIPAL}'`);
  const aud = psql(`SELECT actor||'|'||(detail->>'decision')||'|'||(detail->>'notes')||'|'||(detail->>'gate_id') ` +
                   `FROM audit_log WHERE entity='slot' AND entity_id='${q(slot)}' AND action='gate_decision' AND detail->>'gate_id'='${q(gid)}' ORDER BY id DESC LIMIT 1`);
  const [aActor, aDecision, aNotes, aGid] = aud.split("|");
  if (aActor !== PRINCIPAL || aDecision !== "request_change" || aNotes !== comment || aGid !== gid)
    throw new Error(`decision-verify: audit_log mismatch actor=${aActor} decision=${aDecision} notes=${aNotes} gate_id=${aGid}`);
  console.log(`[decision-verify] exact record correlated: gate=${gid.slice(0, 8)} decision=request_change actor=${approver} comment✓ audit✓`);
  exits.decision_verify = 0;
  return { slot, gate_id: gid, decision, approver, comment_correlated: true, audit_correlated: true };
}

// gap 1: proof discovery + a STRICT six-category ledger.
async function runProof() {
  const env = { ...process.env, WB_URL, API_BASE, REVIEWER_PROXY_SECRET: SECRET };
  const pw = resolve(WORKBENCH, "node_modules/.bin/playwright");
  console.log(`[lane ${LANE}] proof discovery`);
  const list = shCode(pw, ["test", ...SPECS, "--project=product-regression", "--list"], { cwd: WORKBENCH, env });
  exits.discovery = list.code;
  const discovered = Number((list.out.match(/Total:\s*(\d+)\s*test/i) || [])[1] || 0);

  console.log(`[lane ${LANE}] browser-issued real-/gw proof (serial, workers=1, retries=0)`);
  const jsonPath = resolve(ARTIFACTS, `proof-${LANE}.json`);
  const r = shCode(pw, ["test", ...SPECS, "--project=product-regression", "--workers=1", "--retries=0", "--reporter=line,json"],
    { cwd: WORKBENCH, env: { ...env, PLAYWRIGHT_JSON_OUTPUT_NAME: jsonPath } });
  process.stdout.write(r.out); exits.proof = r.code;

  // Six MUTUALLY-EXCLUSIVE categories from each spec's terminal result status.
  const categories = { passed: 0, failed: 0, timedOut: 0, interrupted: 0, skipped: 0, flaky: 0 };
  let statsRaw = null;
  try {
    const report = JSON.parse(readFileSync(jsonPath, "utf8"));
    statsRaw = report.stats || null;
    const specs = []; const walk = (s) => { (s.specs || []).forEach((sp) => specs.push(sp)); (s.suites || []).forEach(walk); };
    (report.suites || []).forEach(walk);
    for (const sp of specs) {
      const statuses = (sp.tests || []).flatMap((t) => (t.results || []).map((rr) => rr.status));
      if (sp.ok && statuses.length > 1 && statuses.some((s) => s !== "passed")) { categories.flaky++; continue; }
      const terminal = statuses[statuses.length - 1];
      if (terminal === "passed") categories.passed++;
      else if (terminal === "failed") categories.failed++;
      else if (terminal === "timedOut") categories.timedOut++;
      else if (terminal === "interrupted") categories.interrupted++;
      else if (terminal === "skipped") categories.skipped++;
      else categories.failed++;   // unknown/undefined terminal is NOT a pass
    }
  } catch { /* zero categories → strict check below fails truthfully */ }
  const otherThanPassed = categories.failed + categories.timedOut + categories.interrupted + categories.skipped + categories.flaky;
  // STRICT: passed === discovered === EXPECTED, every other category zero, discovery+proof exit 0, retries 0.
  const reconciled = exits.discovery === 0 && exits.proof === 0 && discovered === EXPECTED_TESTS
    && categories.passed === discovered && otherThanPassed === 0;
  const ledger = { expected_tests: EXPECTED_TESTS, discovered, retries: 0, categories, other_than_passed: otherThanPassed,
                   discovery_exit: exits.discovery, proof_exit: exits.proof, reconciled, stats_raw: statsRaw, report_artifact: jsonPath };
  console.log(`[proof] discovered=${discovered} categories=${JSON.stringify(categories)} reconciled=${reconciled}`);
  return { code: r.code, reconciled, ledger };
}

async function teardown() {
  console.log(`[lane ${LANE}] teardown`);
  let code = 0;
  if (wbProc && !wbProc.killed) { try { process.kill(wbProc.pid); } catch {} }
  shCode("bash", ["-lc", `kill $(lsof -tnP -iTCP:${WB_PORT} -sTCP:LISTEN) 2>/dev/null`]);
  if (created.api) shCode("docker", ["rm", "-f", "-v", APIC]);   // -v: remove anonymous volumes too
  if (created.db) shCode("docker", ["rm", "-f", "-v", DBC]);
  if (created.net) shCode("docker", ["network", "rm", NET]);
  // WAIT for the workbench to exit + its port to release before the after-inventory (teardown must not
  // race — a killed-but-not-yet-released port would otherwise evade the listener inventory).
  let portsFree = false;
  for (let i = 0; i < 40; i++) { if (portFree(WB_PORT) && portFree(API_PORT)) { portsFree = true; break; } await sleep(500); }
  if (!portsFree) { code = 1; console.error(`[teardown] candidate port still bound (${WB_PORT}/${API_PORT})`); }
  const leftover = shCode("bash", ["-lc",
    `{ docker ps -a --format '{{.Names}}' | grep -E '${DBC}|${APIC}'; docker network ls --format '{{.Name}}' | grep -E '^${NET}$'; } || true`]).out.trim();
  if (leftover) { code = 1; console.error(`[teardown] incomplete: ${leftover}`); }
  else console.log(`[lane ${LANE}] teardown verified — candidate container/DB/network gone`);
  exits.teardown = code;
  return code;
}

// ---------------------------------------------------------------------------------------------------
const EXPECTED = predeclareManifest();
const source = sourceIdentity();
enforceSourceIdentity(source);                 // gap 1: fail-closed on dirty / SHA-mismatch BEFORE startup
const inventoryBefore = snapshotInventory();
console.log(`[lane ${LANE}] PREDECLARED manifest (before startup): identity=${EXPECTED.identity_sha256.slice(0, 12)} marker=${EXPECTED.marker}`);
console.log(`[predeclared] ${JSON.stringify({ workspace: EXPECTED.workspace, runs: identityShape(EXPECTED.runs) })}`);

let status = "NOT SATISFIED";
let manifest = null;
try {
  await bringUp();
  const served = assertServedBinding(source);  // gap 1: API bind-mount + workbench build == accepted source
  const deps = verifyDeps();                    // gap 2: fail-closed unless installed set == consumed lock
  const process_identity = processIdentity();
  persistManifest(EXPECTED);
  const first = await provisionFixture(EXPECTED, "provision"); exits.fixture = 0;
  const second = await resetAndReprovision(EXPECTED);
  // #376 — the governed Script decision record is evidence about the LIFECYCLE fixture's script run.
  // A zero-run lane has no such run, so the check is reported as not-applicable rather than pretended.
  const decisionRecord = FIXTURE === "zero-run" ? "n/a — zero-run fixture declares no runs"
                                                : await verifyDecisionRecord(EXPECTED);
  manifest = { ...EXPECTED, fixture: FIXTURE, governed_setup: governedSetup, deps, source, served, process_identity,
               verified: { provision: first.identity_sha256, reprovision: second.identity_sha256 },
               reprovision: second.reprovision, decision_record: decisionRecord };

  if (induceFailure) {
    console.log(`[lane ${LANE}] INDUCED post-start failure — a real child exits nonzero; teardown must still run`);
    exits.induced = shCode("bash", ["-lc", "exit 7"]).code;
    throw new Error(`induced-failure mode: native nonzero (${exits.induced}) raised after resources exist`);
  }

  const proof = await runProof();
  manifest.proof = proof.ledger;
  status = proof.code === 0 && proof.reconciled ? "SATISFIED" : "NOT SATISFIED";
} catch (e) {
  console.error(`[lane ${LANE}] ${e.message}`);
  status = induceFailure ? "INDUCED-FAILURE-TEARDOWN" : "NOT SATISFIED";
} finally {
  let teardownCode = 0;
  if (!process.env.KEEP) teardownCode = await teardown();
  else console.log(`[lane ${LANE}] KEEP set — leaving lane up (${DBC}/${APIC}/${NET})`);

  // gap 2: named BEFORE/AFTER unrelated-state inventory — fail on mismatch (catches any leak).
  let inventoryChanged = {};
  if (!process.env.KEEP) {
    const inventoryAfter = snapshotInventory();
    inventoryChanged = diffInventory(inventoryBefore, inventoryAfter);
    if (manifest) manifest.inventory = { before: inventoryBefore, after: inventoryAfter, changed: inventoryChanged };
    if (Object.keys(inventoryChanged).length) { console.error(`[inventory] MISMATCH: ${JSON.stringify(inventoryChanged)}`); }
    else console.log(`[inventory] unrelated state identical before/after (containers/networks/volumes/worktrees/listeners/postgres-containers/tracked/config)`);
  }

  if (manifest) console.log(`\n=== manifest ===\n${JSON.stringify(manifest)}`);
  console.log(`\n#370 outcome: ${status} | exits=${JSON.stringify(exits)} | inventory_changed=${JSON.stringify(inventoryChanged)} | artifacts=${ARTIFACTS} | lane=${LANE}`);

  const inventoryLeak = Object.keys(inventoryChanged).length > 0;
  if (status === "SATISFIED" && !inventoryLeak) {
    process.exitCode = teardownCode ? 3 : 0;
  } else if (status === "INDUCED-FAILURE-TEARDOWN") {
    process.exitCode = exits.induced || 1;
    if (teardownCode || inventoryLeak) process.exitCode = 3;
  } else {
    process.exitCode = exits.proof || exits.fixture || teardownCode || (inventoryLeak ? 4 : 1);
  }
}
