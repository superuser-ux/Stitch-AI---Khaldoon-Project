import { test, expect } from "@playwright/test";
import { WB_URL } from "./surfaces";

// #331 — the schedule-first shell and the `selected run → stage → lens` context model.
//
// These assertions are about the INFORMATION ARCHITECTURE, not any one widget: opening V2 shows one
// coherent schedule-first index (not the old standalone Runs/Canonical-slots panel), a run is selected
// by real navigation (never a hand-typed URL), and the run workspace exposes a stage rail + view-lens
// whose selections are visible, keyboard reachable and URL/reload-stable, with unbuilt stages/lenses
// visible-but-disabled and truthfully labelled.

test("opening V2 is one coherent schedule-first root — the runs schedule is the index (#331 A1)", async ({ page }) => {
  await page.goto(WB_URL);
  await expect(page.getByTestId("schedule-first-root")).toBeVisible();
  // The runs schedule (calendar) is the index, with the governed New-run entry beside it. (#376
  // replaced the detached `create-run` form with the ephemeral composer reached via `new-run`.)
  await expect(page.getByTestId("new-run")).toBeVisible();
  await expect
    .poll(async () => {
      for (const id of ["runs-calendar", "runs-calendar-empty", "runs-calendar-read-error"]) {
        if (await page.getByTestId(id).isVisible().catch(() => false)) return id;
      }
      return "loading";
    })
    .not.toBe("loading");
});

test("selecting a run establishes persistent context by navigation, not a typed URL (#331 A3)", async ({ page, request }) => {
  const rows = (await (await request.get(`${WB_URL}/gw/rounds`)).json()) as { round_id: string; starts_on?: string | null }[];
  test.skip(!rows?.length, "no runs in this fixture");
  // Prefer an UNPLACED run: it is always listed in the "Not scheduled" section with a stable link,
  // independent of which month the calendar opens on — so this navigation proof does not depend on a
  // placed run's event landing inside the current calendar view (a fixture/date-relative fragility).
  const unplaced = rows.find((r) => !r.starts_on);
  const id = (unplaced ?? rows[0]).round_id;

  await page.goto(WB_URL);
  // Reach the run through a visible link: the anchor inside its unplaced entry, or (fallback) a placed
  // run's calendar event. Either is a real navigation — the operator never types /runs/{id}.
  const link = unplaced
    ? page.getByTestId(`unplaced-run-${id}`).getByRole("link")
    : page.getByTestId(`run-event-${id}`);
  await expect(link.first()).toBeVisible();
  await link.first().click();

  await expect(page).toHaveURL(new RegExp(`/runs/${id}`));
  await expect(page.getByTestId("run-workspace")).toHaveAttribute("data-round-id", id);
  await expect(page.getByTestId("run-crumb-current")).toHaveText(id);
});

test("the stage rail selects the artifact domain; unbuilt stages are visible but disabled (#331 A4/A9)", async ({ page, request }) => {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  test.skip(!rows?.length, "no runs in this fixture");
  const id = rows[0].round_id as string;

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}`);
  await expect(page.getByTestId("stage-rail")).toBeVisible();

  // Built stages are enabled; unbuilt ones are present, disabled, and truthfully titled — never hidden.
  // #355 — the rail is now DERIVED from the active governed workflow version, so these are canonical
  // `stage_key` values, not V2-invented ones. `script_review` joined the BUILT set (read-first lens).
  // `publish` is deliberately absent: #354 established there is no canonical publish stage at all —
  // the old rail invented it, which is precisely the drift the governed rail removes.
  await expect(page.getByTestId("stage-schedule_review")).toBeEnabled();
  await expect(page.getByTestId("stage-topic_review")).toBeEnabled();
  await expect(page.getByTestId("stage-script_review")).toBeEnabled();
  for (const disabled of ["production_review", "edit_review", "distribution_review"]) {
    const el = page.getByTestId(`stage-${disabled}`);
    await expect(el).toBeVisible();
    await expect(el).toBeDisabled();
    await expect(el).toHaveAttribute("data-active", "false");
  }

  // Default stage is Coverage/Planning; selecting Topics switches the artifact domain and is URL-stable.
  await expect(page.getByTestId("run-workspace")).toHaveAttribute("data-stage", "schedule_review");
  await page.getByTestId("stage-topic_review").click();
  await expect(page.getByTestId("run-workspace")).toHaveAttribute("data-stage", "topic_review");
  await expect(page).toHaveURL(/stage=topic_review/);
  // The selected stage is marked current for assistive tech.
  await expect(page.getByTestId("stage-topic_review")).toHaveAttribute("aria-current", "page");
});

test("stage & lens selections survive reload (URL-addressable), and disabled lenses are truthful (#331 A4/A9)", async ({ page, request }) => {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  test.skip(!rows?.length, "no runs in this fixture");
  const id = rows[0].round_id as string;

  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=topic_review&lens=grid`);
  await expect(page.getByTestId("run-workspace")).toHaveAttribute("data-stage", "topic_review");
  // #382 — the lens selector is now the shell's top lens menu (the single 3-class matrix authority).
  await expect(page.getByTestId("lens-menu")).toBeVisible();
  // The chosen lens is reflected and the workspace presents it.
  await expect(page.getByTestId("topics-workspace")).toHaveAttribute("data-lens", "grid");

  // Reload keeps the exact stage/lens — a real linkable, reload-safe URL, not transient UI state.
  await page.reload();
  await expect(page.getByTestId("topics-workspace")).toHaveAttribute("data-lens", "grid");

  // Active lenses navigate; non-navigable lenses are visible and disabled with truthful reasons. The
  // 3-class matrix (#382 §A) distinguishes a real surface that is wrong for THIS stage
  // (implemented-context-invalid: Calendar belongs to Coverage/Planning) from one never built
  // (unimplemented-disabled: Board/Workflow) — both disabled, both truthful, never fake-navigating.
  for (const active of ["list", "grid", "overview"]) {
    await expect(page.getByTestId(`lens-${active}`)).toBeEnabled();
  }
  await expect(page.getByTestId("lens-calendar")).toHaveAttribute("data-class", "implemented-context-invalid");
  for (const disabled of ["calendar", "board", "workflow"]) {
    const el = page.getByTestId(`lens-${disabled}`);
    await expect(el).toBeVisible();
    await expect(el).toBeDisabled();
    await expect(el, "a disabled lens carries a truthful reason").toHaveAttribute("title", /.+/);
  }
  await expect(page.getByTestId("lens-board")).toHaveAttribute("data-class", "unimplemented-disabled");
});

test("an unknown/disabled stage or lens in the URL falls back to the built default (#331 A4)", async ({ page, request }) => {
  const rows = await (await request.get(`${WB_URL}/gw/rounds`)).json();
  test.skip(!rows?.length, "no runs in this fixture");
  const id = rows[0].round_id as string;

  // A hand-typed disabled stage must not render a stage this lane does not implement.
  await page.goto(`${WB_URL}/runs/${encodeURIComponent(id)}?stage=publish&lens=board`);
  await expect(page.getByTestId("run-workspace")).toHaveAttribute("data-stage", "schedule_review");
});
