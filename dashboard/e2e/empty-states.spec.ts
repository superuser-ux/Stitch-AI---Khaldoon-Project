import { test, expect, type Page } from "@playwright/test";

// #280 — the shared empty-state contract. With NO run available, every lens must render the one
// shared, truthful, accessible empty state (never a blank work area), and the shell must not overflow
// horizontally at 375px. Deterministic without seed data: we intercept the rounds list and return [],
// so the "no selected run" branch is exercised directly (no dependency on DB state).

const NO_RUN = /No run selected/i;

async function loadWithNoRuns(page: Page, w = 375, h = 812) {
  await page.setViewportSize({ width: w, height: h });
  // force the "no runs available" state at the source the whole UI reads from
  await page.route("**/gw/rounds", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.goto("/");
  await page.waitForLoadState("networkidle");
}

function docOverflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
}

const LENSES = ["inbox", "overview", "workflow", "grid", "calendar"] as const;

test("every lens shows the shared, truthful, accessible no-run empty state (#280)", async ({ page }) => {
  test.setTimeout(120_000);
  await loadWithNoRuns(page);

  for (const lens of LENSES) {
    await page.getByTestId(`lens-${lens}`).click();
    const empty = page.getByTestId("empty-state");
    await expect(empty, `lens ${lens} must render the shared empty state`).toBeVisible({ timeout: 20_000 });
    // truthful "no run" contract: a real heading, an assistive live region, and its scope
    await expect(empty).toHaveAttribute("data-variant", /no-run|loading/);
    await expect(empty).toHaveAttribute("role", "status");
    await expect(empty.getByText(NO_RUN)).toBeVisible();
    // the copy must not imply that anything was generated / approved / published
    await expect(empty).not.toContainText(/generated|approved|published/i);
    // no horizontal document overflow at 375px on this empty lens
    expect(await docOverflow(page), `lens ${lens} overflow @375`).toBeLessThanOrEqual(0);
  }
});

test("a FAILED /gw/rounds load renders the truthful unavailable (error) state, not no-run (#280 Codex P1)", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 375, height: 812 });
  // the initial rounds request REJECTS — the system cannot establish whether any runs exist
  await page.route("**/gw/rounds", (route) => route.abort("failed"));
  await page.goto("/");
  await page.waitForLoadState("networkidle");

  for (const lens of LENSES) {
    await page.getByTestId(`lens-${lens}`).click();
    const empty = page.getByTestId("empty-state");
    await expect(empty, `lens ${lens} must render the error empty state`).toBeVisible({ timeout: 20_000 });
    // the shared ERROR variant, never no-run/loading, for a failed load
    await expect(empty).toHaveAttribute("data-variant", "error");
    await expect(empty).toHaveAttribute("role", "status");
    // truthful "unavailable" copy
    await expect(empty).toContainText(/unavailable|could not be loaded/i);
    // must NOT tell the operator to select/start a run (the no-run copy) ...
    await expect(empty).not.toContainText(/no run selected|pick a plan|start a (new )?run/i);
    // ... and must NOT imply anything was generated / approved / published
    await expect(empty).not.toContainText(/generated|approved|published/i);
    // no horizontal document overflow at 375px on the error lens
    expect(await docOverflow(page), `error lens ${lens} overflow @375`).toBeLessThanOrEqual(0);
  }
  // the error persists across lens switches (it is not silently downgraded to no-run)
  await page.getByTestId("lens-overview").click();
  await expect(page.getByTestId("empty-state")).toHaveAttribute("data-variant", "error");
});

test("a failed REFETCH preserves the error; only a successful retry clears it (#280 Codex P1 — retry ownership)", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 375, height: 812 });
  // #299 — jget retries a TRANSIENT failure exactly once, and an aborted request IS transient (it
  // rejects with a TypeError). So ONE failed loadRounds issues exactly TWO requests, and the route
  // must never flip to success while a failed load still has an attempt in flight: the success route
  // would fulfill that load's stale second attempt, loadRounds (still the LATEST invocation, so the
  // #286 guard correctly lets it commit) would clear roundsError, and the retry affordance would
  // unmount under the next click — a 120s timeout at exact head. This is a barrier, NOT a sleep: each
  // attempt is counted as it reaches the handler, where its outcome is already decided, so awaiting a
  // count is an exact "this load can no longer be flipped" signal.
  const ATTEMPTS_PER_FAILED_LOAD = 2;   // jget: first attempt + its one transient retry
  let roundsShouldFail = true;
  let attempts = 0;
  const waiters: { n: number; resolve: () => void }[] = [];
  const attemptsReach = (n: number) => new Promise<void>((resolve) => {
    if (attempts >= n) { resolve(); return; }
    waiters.push({ n, resolve });
  });
  await page.route("**/gw/rounds", async (route) => {
    const fail = roundsShouldFail;   // decided on ARRIVAL — a later flip cannot rewrite this attempt
    attempts++;
    for (let i = waiters.length - 1; i >= 0; i--) {
      if (attempts >= waiters[i].n) waiters.splice(i, 1)[0].resolve();
    }
    if (fail) { await route.abort("failed"); return; }
    await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });

  const initialLoadFailed = attemptsReach(ATTEMPTS_PER_FAILED_LOAD);
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await initialLoadFailed;   // the initial load has no attempt left in flight

  const empty = page.getByTestId("empty-state");
  // initial load failed -> truthful error state, with a retry affordance
  await expect(empty).toHaveAttribute("data-variant", "error");
  await expect(page.getByTestId("rounds-retry")).toBeVisible();

  // a FAILED retry must PRESERVE the error — never downgraded to no-run
  const failedRetryFailed = attemptsReach(2 * ATTEMPTS_PER_FAILED_LOAD);
  await page.getByTestId("rounds-retry").click();
  // #299 — await the refetch's OWN attempts before asserting: previously this assertion could pass
  // trivially (roundsError was already set and is never optimistically cleared) while the refetch was
  // still in flight, so it never actually observed the failed REFETCH the test is named for.
  await failedRetryFailed;
  await expect(empty).toHaveAttribute("data-variant", "error");
  await expect(empty).not.toContainText(/no run selected|pick a plan|start a (new )?run/i);
  expect(await docOverflow(page)).toBeLessThanOrEqual(0);

  // a SUCCESSFUL retry clears the error -> the truthful no-run state (rounds loaded, list empty)
  roundsShouldFail = false;
  await page.getByTestId("rounds-retry").click();
  await expect(empty).toHaveAttribute("data-variant", "no-run", { timeout: 20_000 });
  expect(await docOverflow(page)).toBeLessThanOrEqual(0);
});

test("overlapping loadRounds: a stale FAILED response cannot overwrite a newer SUCCESSFUL one (#286)", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 375, height: 812 });
  // Deterministic overlap with NO sleeps: a promise barrier orders the responses, and each failing
  // load uses a 500 (which jget does NOT retry, unlike an abort) so a failed loadRounds is exactly one
  // request. The older FAILED retry is parked in-flight, the newer SUCCESSFUL retry commits no-run, and
  // only then is the stale failure released — the monotonic guard must discard it.
  let phase: "fail" | "hold" | "succeed" = "fail";
  let releaseHeld!: () => void;
  const heldReleased = new Promise<void>((r) => { releaseHeld = r; });
  let markHeldArrived!: () => void;
  const heldArrived = new Promise<void>((r) => { markHeldArrived = r; });
  const fail500 = { status: 500, contentType: "application/json", body: JSON.stringify({ detail: "boom" }) };
  await page.route("**/gw/rounds", async (route) => {
    if (phase === "succeed") { await route.fulfill({ status: 200, contentType: "application/json", body: "[]" }); return; }
    if (phase === "hold") { markHeldArrived(); await heldReleased; await route.fulfill(fail500); return; }
    await route.fulfill(fail500);
  });

  await page.goto("/");
  const empty = page.getByTestId("empty-state");
  await expect(empty).toHaveAttribute("data-variant", "error");   // initial failure -> error
  await expect(page.getByTestId("rounds-retry")).toBeVisible();

  // 1) arm the hold, click the FAILED retry — its (older) request parks in-flight
  phase = "hold";
  await page.getByTestId("rounds-retry").click();
  await heldArrived;   // deterministic: the older failed request has reached the handler and is parked

  // 2) switch to success, click the SUCCESSFUL (newer) retry — it commits the truthful no-run state
  phase = "succeed";
  await page.getByTestId("rounds-retry").click();
  await expect(empty).toHaveAttribute("data-variant", "no-run", { timeout: 20_000 });

  // 3) release the older failed request so it resolves AFTER the newer success. The monotonic guard
  //    must DISCARD this stale failure — the surface stays no-run and never flips back to error.
  releaseHeld();
  await expect(empty).toHaveAttribute("data-variant", "no-run");
  await expect(empty).not.toHaveAttribute("data-variant", "error");
  await expect(empty.getByText(NO_RUN)).toBeVisible();
});

test("the no-run empty state is keyboard reachable and has a visible heading at desktop too (#280)", async ({ page }) => {
  test.setTimeout(120_000);
  await loadWithNoRuns(page, 1280, 900);
  const empty = page.getByTestId("empty-state");
  await expect(empty).toBeVisible({ timeout: 20_000 });
  // scope chip present and legible
  await expect(page.getByTestId("empty-state-scope")).toBeVisible();
  // the lens switcher stays operable by keyboard (accessible names present)
  await expect(page.getByTestId("lens-overview")).toHaveAttribute("aria-label", "Overview");
  expect(await docOverflow(page)).toBeLessThanOrEqual(0);
});
