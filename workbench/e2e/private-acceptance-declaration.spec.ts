import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { WB_URL } from "./surfaces";

// #351 — the private acceptance lane must DECLARE that its data is synthetic.
//
// WHY. #337's acceptance lane serves a fresh synthetic database to a human client-product reviewer.
// The workbench never asserts "synthetic" on its own: /api/runtime resolves `data_class` to
// "unknown" unless explicitly declared, and the banner renders nothing unless the server says
// "synthetic". That default is correct — a reassuring label on a lane that might hold real data is
// worse than no label — but it means an undeclared lane shows synthetic data with NO disclosure,
// and any screenshot then carries a claim it has not earned. The declaration is therefore made by
// the topology that knows the database is synthetic, and this spec proves it stays made.
//
// WHAT THIS DELIBERATELY DOES NOT DO. It never builds an image and never instantiates the
// three-service acceptance topology. The compose half is a pure static read of the committed file;
// the behavioural half mocks /api/runtime. Standing the lane up to "really prove it" would be both
// out of scope and a worse test — it would prove the machine that ran it, not the committed source.

const COMPOSE = join(__dirname, "../../deploy/acceptance/docker-compose.yml");
const composeText = () => readFileSync(COMPOSE, "utf8");

/** The file with comment-only lines removed.
 *
 *  Structural claims must be made about YAML, not prose. The first version of this spec scanned the
 *  raw text and failed on the compose file's own comment explaining that it uses no `env_file` — the
 *  test matched the word inside the sentence denying it. A comment can describe a leak vector; only
 *  a key can create one. Trailing inline comments are left alone: no assertion here depends on them,
 *  and stripping them would risk mangling values that legitimately contain `#`. */
const composeYaml = () =>
  composeText()
    .split("\n")
    .filter((l) => !/^\s*#/.test(l))
    .join("\n");

/** The raw lines of one service's block, from `  <name>:` to the next top-level-service line.
 *  A deliberately dumb slice over the committed text: it asserts what the file SAYS, with no YAML
 *  library normalising it and no docker daemon involved. */
function serviceBlock(name: string): string {
  const lines = composeYaml().split("\n");
  const start = lines.findIndex((l) => l === `  ${name}:`);
  expect(start, `service '${name}' must exist in the committed compose file`).toBeGreaterThan(-1);
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((l) => /^ {2}\S/.test(l));
  return (end === -1 ? rest : rest.slice(0, end)).join("\n");
}

test("the acceptance lane declares itself synthetic, with a stable lane id (#351)", () => {
  const wb = serviceBlock("workbench");
  expect(wb, "data class must be declared for the acceptance lane").toContain('TANAGHOM_WORKBENCH_DATA_CLASS: "synthetic"');
  expect(wb, "the lane id must be the stable committed identifier").toContain('TANAGHOM_WORKBENCH_LANE_ID: "private-acceptance-337"');

  // Literal and environment-independent — NOT interpolated like REVIEWER_PROXY_SECRET. A ${...}
  // form would make the disclosure depend on the operator's shell, which is exactly the kind of
  // "true on my machine" declaration this must not be.
  for (const line of wb.split("\n").filter((l) => /TANAGHOM_WORKBENCH_(DATA_CLASS|LANE_ID)/.test(l))) {
    expect(line, `declaration must be a literal, not interpolated: ${line.trim()}`).not.toContain("${");
  }
});

test("the declarations reach the workbench service ONLY (#351)", () => {
  for (const other of ["db", "gateapi"]) {
    const block = serviceBlock(other);
    expect(block, `${other} must not receive the workbench data-class declaration`).not.toContain("TANAGHOM_WORKBENCH_DATA_CLASS");
    expect(block, `${other} must not receive the workbench lane id`).not.toContain("TANAGHOM_WORKBENCH_LANE_ID");
  }

  // Structural, not incidental: with no anchors/aliases/x- extensions/env_file/merge keys there is
  // no shared-environment construct for a value to leak through in the first place. If any of these
  // ever appear, the per-service isolation above stops being self-evident and must be re-proven.
  const text = composeYaml();
  for (const [what, re] of [
    ["YAML anchor", /^\s*\w+:\s*&\w/m],
    ["YAML alias", /:\s*\*\w/m],
    ["x- extension", /^x-/m],
    ["env_file", /env_file/],
    ["merge key", /<<:/],
  ] as const) {
    expect(text, `${what} would create a shared-env leak path; isolation must then be re-proven`).not.toMatch(re);
  }
});

test("the private topology is unchanged by the declaration (#351)", () => {
  const text = composeYaml();

  // Exactly three services — no new service, listener, or database was introduced.
  const services = [...text.matchAll(/^ {2}([a-z][a-z0-9_-]*):$/gm)].map((m) => m[1])
    .filter((n) => !["db_data", "internal"].includes(n));
  expect(services.sort(), "exactly db/gateapi/workbench").toEqual(["db", "gateapi", "workbench"]);

  // Every published host port stays loopback-only — the lane is private.
  const ports = [...text.matchAll(/^\s+- "([^"]+)"/gm)].map((m) => m[1]).filter((p) => /:\d+$/.test(p));
  expect(ports.length, "the lane publishes host ports").toBeGreaterThan(0);
  for (const p of ports) expect(p, `host binding must be loopback-only: ${p}`).toMatch(/^127\.0\.0\.1:/);

  // Stub writer stays on: an acceptance lane must never reach a live provider.
  expect(text).toContain('TANAGHOM_WRITER_STUB: "1"');

  // The baked-SHA/runtime-guard contract is untouched: compose must NOT set a runtime override,
  // because the entrypoint terminates non-zero when one diverges from the baked value.
  expect(text.match(/^\s*TANAGHOM_WORKBENCH_BUILD_SHA:/gm) ?? [],
    "compose must not set a runtime build-SHA override").toHaveLength(0);
});

// ---------------------------------------------------------------------------
// Behaviour, proven against the SHIPPED contract via a mocked /api/runtime.
// No env is set, no server is reconfigured, and no lane is instantiated: the point is that the
// surface reacts correctly to what the server declares, whatever the surrounding topology is.

/** Serve a controlled runtime identity, then load the shell that renders the banner. */
async function withRuntime(page: import("@playwright/test").Page, body: Record<string, unknown>) {
  await page.route("**/api/runtime", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) }));
  await page.goto(`${WB_URL}/`);
}

const BASE = { surface: "workbench", build: "test", lane: "v2-transition", identity: "none" };

test("a declared synthetic lane renders the banner with its stable lane id (#351)", async ({ page }) => {
  await withRuntime(page, { ...BASE, lane_id: "private-acceptance-337", data_class: "synthetic" });

  const banner = page.getByTestId("synthetic-lane-banner");
  await expect(banner, "a declared synthetic lane must disclose itself").toBeVisible();
  await expect(page.getByTestId("synthetic-lane-id")).toHaveText("private-acceptance-337");
  await expect(banner).toHaveAttribute("data-lane-id", "private-acceptance-337");
  await expect(page.getByTestId("synthetic-lane-note")).toContainText(/not client data/i);
});

test("an UNDECLARED lane stays silent — never an assumed 'synthetic' (#351)", async ({ page }) => {
  // This is the negative that protects every other deployment: absent declaration must NOT be read
  // as synthetic, or the banner would start reassuring people about lanes nobody vouched for.
  await withRuntime(page, { ...BASE, lane_id: "unknown", data_class: "unknown" });
  await expect(page.getByTestId("synthetic-lane-banner")).toHaveCount(0);
});

test("a data class the SERVER did not resolve to synthetic renders no banner (#351)", async ({ page }) => {
  // LAYER MATTERS, and an earlier version of this test got it wrong. It listed "Synthetic " among
  // "invalid" values, which is false: `laneDataClass()` in app/api/runtime/route.ts applies
  // `.trim().toLowerCase()` to the ENV value, so an env of "Synthetic " normalizes to "synthetic"
  // and the lane WOULD correctly disclose itself. Calling that invalid mislabelled a working case.
  //
  // These mocks replace the route's RESPONSE, so they exercise the banner's own rule — it renders
  // only when the server has already resolved the value to exactly "synthetic". The values below
  // are therefore ones the route can genuinely emit or that are plainly not synthetic; none of them
  // is a form the route would have normalized INTO "synthetic".
  //
  // Env-level normalization is a separate contract, owned by the route and documented in
  // deploy/acceptance/README.md; it is deliberately not re-asserted here through a mock that cannot
  // reach it.
  for (const notSynthetic of ["unknown", "real", "synthetic-ish", ""]) {
    await withRuntime(page, { ...BASE, lane_id: "private-acceptance-337", data_class: notSynthetic });
    await expect(page.getByTestId("synthetic-lane-banner"),
      `data_class ${JSON.stringify(notSynthetic)} must not render the banner`).toHaveCount(0);
  }
});
