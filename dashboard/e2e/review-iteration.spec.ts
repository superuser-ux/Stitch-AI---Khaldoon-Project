import { test, expect, type Page } from "@playwright/test";
import { allocateFullMix } from "./plan-helpers";

// The iterative review loop on a UI-created (schedule-first) run: request change -> regenerate ->
// the item re-enters the actionable review, and sending one item back must not freeze the others.
// Reproduces the live-browser findings; requires the gate API with TANAGHOM_WRITER_STUB=1.

async function planAndOpenTopics(page: Page, ppd = "3") {
  await page.goto("/");
  await page.getByTestId("new-run").click();
  await page.getByTestId("days-input").fill("1");
  await page.getByTestId("ppd-input").fill(ppd);
  await allocateFullMix(page);
  await page.getByTestId("new-run-submit").click();
  await expect(page.getByTestId("open-gate")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("open-gate").click();
  await expect(page.locator("input[type='checkbox'][data-testid^='select-']").first()).toBeVisible({ timeout: 20000 });
  await page.getByTestId("select-all-pending").click();
  await page.getByTestId("apply-selected-action").click();
  await page.getByTestId("resolve-gate").click();
  await page.getByTestId("nav-topic").click();
  await expect(page.getByTestId("generate-action")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("generate-action").click();
  await expect(page.getByTestId("open-gate")).toBeVisible({ timeout: 90000 });
  await page.getByTestId("open-gate").click();
  await expect(page.locator("[data-testid^=card-]").first()).toBeVisible({ timeout: 20000 });
}

async function cardIds(page: Page): Promise<string[]> {
  const ids = await page.locator("[data-testid^=card-]").evaluateAll((ns) =>
    ns.map((n) => n.getAttribute("data-testid") || "").filter((id) => /^card-/.test(id)));
  return ids.map((id) => id.replace("card-", ""));
}

async function requestChange(page: Page, slot: string, note: string) {
  await page.getByTestId(`request-${slot}`).click();
  await page.getByTestId(`change-text-${slot}`).fill(note);
  await page.getByTestId(`submit-change-${slot}`).click();
  await expect(page.getByTestId("toast")).toBeVisible();
}

test("topic: request-change -> regenerate -> item re-enters actionable review", async ({ page }) => {
  test.setTimeout(180_000);
  await planAndOpenTopics(page);
  const [a] = await cardIds(page);

  await requestChange(page, a, "غيّر الزاوية");
  await expect(page.getByTestId("awaiting-panel")).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId(`card-${a}`)).toHaveCount(0);   // left the actionable queue

  await page.getByTestId("regenerate").click();
  // The reworked item resurfaces as an actionable review card and the awaiting lane clears — driven by
  // the DB, so this holds even if the /jobs progress registry is unavailable.
  await expect(page.getByTestId(`card-${a}`)).toBeVisible({ timeout: 40000 });
  await expect(page.getByTestId(`approve-${a}`)).toBeVisible();
  await expect(page.getByTestId("awaiting-panel")).toHaveCount(0);
});

test("after one topic is sent back, the other cards stay actionable", async ({ page }) => {
  test.setTimeout(180_000);
  await planAndOpenTopics(page);
  const [a, b, c] = await cardIds(page);

  await requestChange(page, a, "غيّر الزاوية");
  // Sending A back must not freeze the rest: their per-item actions must re-enable promptly (the bug
  // held a global busy flag across the whole post-decide refetch cascade).
  await expect(page.getByTestId(`approve-${b}`)).toBeEnabled({ timeout: 6000 });
  await expect(page.getByTestId(`reject-${c}`)).toBeEnabled({ timeout: 6000 });

  // ...and they actually work
  await page.getByTestId(`approve-${b}`).click();
  await expect(page.getByTestId(`card-${b}`)).toHaveCount(0, { timeout: 15000 });   // B advanced out
  await page.getByTestId(`select-${c}`).check();
  await expect(page.getByTestId(`select-${c}`)).toBeChecked();                       // selection sticks
});

test("script: request-change -> regenerate -> item re-enters actionable review", async ({ page }) => {
  test.setTimeout(240_000);
  await planAndOpenTopics(page, "2");

  // approve the topics, then generate + open the script review
  await page.getByTestId("select-all-pending").click();
  await page.getByTestId("apply-selected-action").click();
  await page.getByTestId("resolve-gate").click();
  await page.getByTestId("nav-script").click();
  await expect(page.getByTestId("generate-action")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("generate-action").click();
  await expect(page.getByTestId("open-gate")).toBeVisible({ timeout: 90000 });
  await page.getByTestId("open-gate").click();
  await expect(page.locator("[data-testid^=card-]").first()).toBeVisible({ timeout: 20000 });
  const [a] = await cardIds(page);

  await requestChange(page, a, "غيّر السطر الأول");
  await expect(page.getByTestId("awaiting-panel")).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId(`card-${a}`)).toHaveCount(0);

  await page.getByTestId("regenerate").click();
  await expect(page.getByTestId(`card-${a}`)).toBeVisible({ timeout: 40000 });
  await expect(page.getByTestId(`approve-${a}`)).toBeVisible();
  await expect(page.getByTestId("awaiting-panel")).toHaveCount(0);
});

// The reported live case: a hook/title change ("replace the last word"). The rework must actually apply
// the hook edit so the rework-acceptance check passes and the item re-enters review (not stuck awaiting).
test("topic: hook/title change-request -> regenerate -> item re-enters (rework accepted)", async ({ page }) => {
  test.setTimeout(180_000);
  await planAndOpenTopics(page);
  const [a] = await cardIds(page);

  await requestChange(page, a, "Keep the same meaning, but replace the last word and preserve the rest of the title.");
  await expect(page.getByTestId("awaiting-panel")).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId(`card-${a}`)).toHaveCount(0);

  await page.getByTestId("regenerate").click();
  await expect(page.getByTestId(`card-${a}`)).toBeVisible({ timeout: 40000 });   // rework accepted -> back in review
  await expect(page.getByTestId(`approve-${a}`)).toBeVisible();
  await expect(page.getByTestId("awaiting-panel")).toHaveCount(0);
});

// Refine a change note on an item already sent back, WITHOUT an Undo round-trip (issue #3).
// The reviewer must be able to correct/append the directive in place; the item stays awaiting and
// the updated note is what the next regenerate applies.
test("topic: edit the change note on an awaiting item without undo", async ({ page }) => {
  test.setTimeout(180_000);
  await planAndOpenTopics(page);
  const [a] = await cardIds(page);

  await requestChange(page, a, "FIRST note: shorten the hook.");
  await expect(page.getByTestId("awaiting-panel")).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId(`awaiting-${a}`)).toContainText("FIRST note");
  await expect(page.getByTestId(`card-${a}`)).toHaveCount(0);

  // Edit the note in place — no Undo, no reopen.
  await page.getByTestId(`edit-note-${a}`).click();
  await page.getByTestId(`edit-note-text-${a}`).fill("SECOND note: keep the hook, change only the CTA.");
  await page.getByTestId(`save-note-${a}`).click();
  await expect(page.getByTestId("toast")).toBeVisible();

  // Item stays awaiting (not forced back through review) and the note is updated in place.
  await expect(page.getByTestId("awaiting-panel")).toBeVisible();
  await expect(page.getByTestId(`card-${a}`)).toHaveCount(0);
  await expect(page.getByTestId(`awaiting-${a}`)).toContainText("SECOND note");
  await expect(page.getByTestId(`awaiting-${a}`)).not.toContainText("FIRST note");

  // The edited note flows through: regenerate re-enters the item to actionable review.
  await page.getByTestId("regenerate").click();
  await expect(page.getByTestId(`card-${a}`)).toBeVisible({ timeout: 40000 });
  await expect(page.getByTestId("awaiting-panel")).toHaveCount(0);
});

// Rework-from-older-version safety (issue #3): reworking from an older revision restores it as the
// working head and drops the newer revision(s) from the head. The head must be marked current, and
// reworking from an OLDER version must warn + require explicit confirmation before it fires.
test("topic: rework from an older version warns before discarding the newer head", async ({ page }) => {
  test.setTimeout(180_000);
  await planAndOpenTopics(page);
  const [a] = await cardIds(page);

  // create a 2nd revision so there's a head (v2) and an older base (v1)
  await requestChange(page, a, "غيّر الزاوية");
  await page.getByTestId("regenerate").click();
  await expect(page.getByTestId(`card-${a}`)).toBeVisible({ timeout: 40000 });

  await page.getByTestId(`history-${a}`).click();
  await expect(page.getByTestId(`versions-${a}`)).toBeVisible();
  await expect(page.getByTestId(`version-${a}-2`)).toBeVisible();

  // head is marked current; the older base is not
  await expect(page.getByTestId(`version-head-${a}-2`)).toBeVisible();
  await expect(page.getByTestId(`version-head-${a}-1`)).toHaveCount(0);

  // reworking from the OLDER v1 must NOT fire immediately — it warns first, naming the discarded head
  await page.getByTestId(`reworkfrom-text-${a}-1`).fill("go back to the first angle");
  await page.getByTestId(`reworkfrom-${a}-1`).click();
  await expect(page.getByTestId(`reworkfrom-warning-${a}-1`)).toBeVisible();
  await expect(page.getByTestId(`reworkfrom-warning-${a}-1`)).toContainText("v2");
  await expect(page.getByTestId(`card-${a}`)).toBeVisible();   // still on the v2 head, nothing regenerated yet

  // cancel dismisses the warning without discarding anything
  await page.getByTestId(`reworkfrom-cancel-${a}-1`).click();
  await expect(page.getByTestId(`reworkfrom-warning-${a}-1`)).toHaveCount(0);
});

// Scripts: a delivery/tone change must likewise be applied so the rework is accepted and re-enters.
test("script: tone change-request -> regenerate -> item re-enters (rework accepted)", async ({ page }) => {
  test.setTimeout(240_000);
  await planAndOpenTopics(page, "2");
  await page.getByTestId("select-all-pending").click();
  await page.getByTestId("apply-selected-action").click();
  await page.getByTestId("resolve-gate").click();
  await page.getByTestId("nav-script").click();
  await expect(page.getByTestId("generate-action")).toBeVisible({ timeout: 15000 });
  await page.getByTestId("generate-action").click();
  await expect(page.getByTestId("open-gate")).toBeVisible({ timeout: 90000 });
  await page.getByTestId("open-gate").click();
  await expect(page.locator("[data-testid^=card-]").first()).toBeVisible({ timeout: 20000 });
  const [a] = await cardIds(page);

  await requestChange(page, a, "خفف النبرة وخليها أهدى وألطف");   // softer-tone request
  await expect(page.getByTestId("awaiting-panel")).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId(`card-${a}`)).toHaveCount(0);

  await page.getByTestId("regenerate").click();
  await expect(page.getByTestId(`card-${a}`)).toBeVisible({ timeout: 40000 });
  await expect(page.getByTestId(`approve-${a}`)).toBeVisible();
  await expect(page.getByTestId("awaiting-panel")).toHaveCount(0);
});
