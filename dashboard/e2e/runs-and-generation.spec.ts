import { createHmac } from "node:crypto";
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { reseed } from "./seed";
import { allocateFullMix } from "./plan-helpers";

// NOTE: only the last test uses the shared RE2E round; it reseeds RE2E itself. The other tests create
// their own runs, so reseeding before every test just adds latency (and its variance can push the tight
// generation-timeout tests over). Reseed is therefore scoped to the one test that needs it.

// Drives the full UI-driven path: plan a small run from the UI, approve the generated schedule,
// generate topic titles as a background job, then land on a reviewable queue. Requires the gate API to run with
// TANAGHOM_WRITER_STUB=1 (deterministic offline writer).

const API = process.env.API_URL || "http://localhost:8009";
const PROXY_SECRET = process.env.REVIEWER_PROXY_SECRET || "dev-internal-reviewer-proxy-secret";

function adminHeaders() {
  const principal = "khal";
  return {
    "x-principal-id": principal,
    "x-principal-signature": createHmac("sha256", PROXY_SECRET).update(principal).digest("hex"),
  };
}

async function activateManagedWeeklyCount(request: APIRequestContext, weeklyCount: number): Promise<() => Promise<void>> {
  const catalogResponse = await request.get(`${API}/content-formats`, { headers: adminHeaders() });
  expect(catalogResponse.ok()).toBeTruthy();
  const catalog = await catalogResponse.json();
  const format = catalog.formats[0];
  const activeVersion = format.active_version;
  const originalVersionId = activeVersion.version_id;   // snapshot so the mutation can be restored (suite hygiene)
  const draftResponse = await request.post(`${API}/content-formats/${format.format_key}/versions/draft`, {
    headers: adminHeaders(),
  });
  expect(draftResponse.ok()).toBeTruthy();
  const draft = await draftResponse.json();
  const productionRules = {
    ...(activeVersion.production_rules || {}),
    planning: {
      ...((activeVersion.production_rules || {}).planning || {}),
      weekly_count: weeklyCount,
    },
  };
  const saveResponse = await request.put(`${API}/content-format-versions/${draft.version_id}`, {
    headers: adminHeaders(),
    data: {
      use_case: activeVersion.use_case,
      lens_fit: activeVersion.lens_fit || [],
      production_notes: activeVersion.production_notes,
      production_rules: productionRules,
      platform_targets: activeVersion.platform_targets || [],
    },
  });
  expect(saveResponse.ok()).toBeTruthy();
  const activateResponse = await request.post(`${API}/content-format-versions/${draft.version_id}/activate`, {
    headers: adminHeaders(),
  });
  expect(activateResponse.ok()).toBeTruthy();

  // Restore hook: reactivate the version that was active before this mutation so the shared managed
  // catalogue is not left drifted for later specs (release-gate suite isolation).
  return async () => {
    const restoreResponse = await request.post(`${API}/content-format-versions/${originalVersionId}/activate`, {
      headers: adminHeaders(),
    });
    expect(restoreResponse.ok()).toBeTruthy();
  };
}

// Plan a small run and approve its schedule, landing on the Topic stage with generation available.
async function planTwoSlotRunToTopicGenerate(page: Page) {
  await page.goto("/");

  // 1) Start a run: days=1 x posts/day=2 -> 2 slots
  await page.getByTestId("new-run").click();
  await page.getByTestId("days-input").fill("1");
  await page.getByTestId("ppd-input").fill("2");
  await expect(page.getByTestId("run-total")).toHaveText("2");
  await allocateFullMix(page);
  await page.getByTestId("new-run-submit").click();

  // 2) The Schedule stage is ready to review the planned slots before title generation
  await expect(page.getByTestId("open-gate")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("open-gate").click();
  await expect(page.getByRole("main")).toContainText(/schedule board aligned to the client reference/i);
  await expect(page.locator("input[type='checkbox'][data-testid^='select-']").first()).toBeVisible({ timeout: 20000 });
  await page.getByTestId("select-all-pending").click();
  await page.getByTestId("apply-selected-action").click();
  await page.getByTestId("resolve-gate").click();

  // 3) Topic generation becomes available only after the schedule is approved
  await page.getByTestId("nav-topic").click();
  await expect(page.getByTestId("generate-action")).toBeVisible({ timeout: 15000 });
}

async function runScheduleToTopicReview(page: Page) {
  await planTwoSlotRunToTopicGenerate(page);
  await page.getByTestId("generate-action").click();

  // 4) A background job runs (progress), then the generated topic titles become reviewable
  await expect(page.getByTestId("job-progress")).toBeVisible();
  await expect(page.getByTestId("open-gate")).toBeVisible({ timeout: 90000 });

  // 5) Start the topic review and confirm the generated topics rendered as cards
  await page.getByTestId("open-gate").click();
  await expect(page.locator("[data-testid^=card-]").first()).toBeVisible({ timeout: 20000 });
}

test("UI-driven run: plan -> approve schedule -> generate topics -> reviewable", async ({ page }) => {
  await runScheduleToTopicReview(page);
});

test("generation resurfaces the review when the /jobs registry is unavailable", async ({ page }) => {
  // The generation-job registry is in-process and ephemeral: entries are evicted past a cap, lost
  // on an API restart, and invisible to other workers — so GET /jobs/{id} can 404 (or time out
  // under load) while generation still completes in the DB. Simulate that failure and assert the
  // dashboard resurfaces the review from the authoritative stage state instead of dead-ending on
  // the job poll.
  await planTwoSlotRunToTopicGenerate(page);
  await page.route(/\/gw\/jobs\//, (route) =>
    route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "unknown job" }) }));

  await page.getByTestId("generate-action").click();

  // The completed generation must OPEN the review (resumeReviewIfNeeded) so its cards render on
  // their own — driven by the DB, not by a successful job poll. (A background state re-read can
  // surface the "Start review" button, but only the poll's completion handler actually opens the
  // gate; when it depends on /jobs and that fails, the old code never opened it and dead-ended.)
  await expect(page.locator("[data-testid^=card-]").first()).toBeVisible({ timeout: 25000 });
});

test("a finished generation job with ZERO persisted items reports a truthful, retryable failure (#207)", async ({ page }) => {
  // The #204 false success: the writer records per-item failures and returns normally, so the
  // job registry marks the job "done" while NOTHING was persisted — and the old convergence
  // settled success from the job status alone. Reproduce that exact shape deterministically:
  // the generate POST is intercepted (the server never runs, so the stage truthfully keeps
  // offering "generate") and the job poll reports a finished job with zero completions.
  await planTwoSlotRunToTopicGenerate(page);
  await page.route(/\/gw\/rounds\/[^/]+\/stages\/topic_review\/generate/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
                    body: JSON.stringify({ job_id: "e2e-empty-job", total: 2 }) }));
  await page.route(/\/gw\/jobs\/e2e-empty-job/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
                    body: JSON.stringify({ job_id: "e2e-empty-job", status: "done", done: 0, total: 2 }) }));

  await page.getByTestId("generate-action").click();

  // truthful failure: visible, plain-language, and retryable — never a success toast
  const toast = page.getByTestId("toast");
  await expect(toast).toBeVisible({ timeout: 20000 });
  await expect(toast).toHaveAttribute("data-kind", "err");
  await expect(toast).toContainText(/nothing changed/i);
  await expect(toast).not.toContainText(/ready to review/i);
  // Generate stays available for the retry; no review auto-opened for the empty result
  await expect(page.getByTestId("generate-action")).toBeVisible();
  await expect(page.locator("[data-testid^=card-]")).toHaveCount(0);
});

test("a KNOWN job error shows fixed retryable copy — raw diagnostic text never reaches the page OR the console (#207)", async ({ page }) => {
  // The job registry's error field carries raw diagnostics (endpoints, hosts, stack traces —
  // exactly what the #204 embedding failure produced). That text must NEVER enter ANY client
  // surface — page content or browser console: the user sees fixed product copy, the console
  // gets only a fixed line with the non-sensitive job id, and full diagnostics stay backend-only
  // (job registry + API logs).
  const HOSTILE = "HTTPConnectionPool(host='secret-internal-host', port=11434): Max retries "
    + "exceeded — Traceback (most recent call last): provider=groq token=sk-FAKE";
  const consoleLines: string[] = [];
  page.on("console", (msg) => consoleLines.push(msg.text()));
  await planTwoSlotRunToTopicGenerate(page);
  await page.route(/\/gw\/rounds\/[^/]+\/stages\/topic_review\/generate/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
                    body: JSON.stringify({ job_id: "e2e-hostile-job", total: 2 }) }));
  await page.route(/\/gw\/jobs\/e2e-hostile-job/, (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
                    body: JSON.stringify({ job_id: "e2e-hostile-job", status: "error",
                                           error: HOSTILE, done: 0, total: 2 }) }));

  await page.getByTestId("generate-action").click();

  const toast = page.getByTestId("toast");
  await expect(toast).toBeVisible({ timeout: 20000 });
  await expect(toast).toHaveAttribute("data-kind", "err");
  await expect(toast).toContainText(/you can generate again/i);
  // the raw diagnostic text is absent from the ENTIRE page, not just the toast
  for (const fragment of ["HTTPConnectionPool", "secret-internal-host", "Traceback", "sk-FAKE", "11434"]) {
    await expect(page.locator("body")).not.toContainText(fragment);
  }
  await expect(page.getByTestId("generate-action")).toBeVisible();
  // …and absent from the BROWSER CONSOLE: only the fixed correlation line (job id, no raw
  // detail) may appear there
  const consoleDump = consoleLines.join("\n");
  for (const fragment of ["HTTPConnectionPool", "secret-internal-host", "Traceback", "sk-FAKE", "11434"]) {
    expect(consoleDump).not.toContain(fragment);
  }
  expect(consoleDump).toContain("generation job e2e-hostile-job failed");
});

test("UI-driven run stays green after managed content-type drift", async ({ page, request }) => {
  const restoreManagedCatalogue = await activateManagedWeeklyCount(request, 0);
  try {
    await runScheduleToTopicReview(page);
  } finally {
    await restoreManagedCatalogue();
  }
});

test("selected run survives refresh even when another active run exists", async ({ page }) => {
  reseed();   // this test selects the shared RE2E round — reset it so it is order-independent
  await page.goto("/");
  await page.waitForLoadState("networkidle");

  await page.getByTestId("new-run").click();
  await page.getByTestId("label-input").fill("refresh-stickiness");
  await page.getByTestId("days-input").fill("1");
  await page.getByTestId("ppd-input").fill("1");
  await allocateFullMix(page);
  await page.getByTestId("new-run-submit").click();
  await expect(page.getByTestId("round-trigger")).toContainText("R");

  await page.getByTestId("round-trigger").click();
  await page.getByTestId("round-opt-RE2E").click();
  await expect(page.getByTestId("round-trigger")).toContainText("RE2E");
  await page.getByTestId("nav-topic").click();
  await expect(page.getByRole("main")).toContainText(/topics/i);

  await page.reload();
  await page.waitForLoadState("networkidle");
  await expect(page.getByTestId("round-trigger")).toContainText("RE2E");
  await expect(page.getByRole("main")).toContainText(/topics/i);
});
