import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type ConsoleMessage } from "@playwright/test";
import { APP_URL } from "../playwright.config";

const RESULTS = join(__dirname, "..", "visual-results");

// Needs no design snapshot: the design is desktop-only, so the narrow layout is checked on its own terms.
test.beforeAll(() => mkdirSync(RESULTS, { recursive: true }));

test("at 375px every row reflows inside the viewport, with nothing clipped or overlapping", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 375, height: 812 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.goto(APP_URL);
  await page.getByText("13 tasks", { exact: true }).waitFor();

  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), "page scrolls sideways").toBeLessThanOrEqual(0);

  const rows = await page.locator('ul[aria-label="Tasks"] > li').evaluateAll((items) =>
    items.map((li) => {
      const row = li.getBoundingClientRect();
      const box = (el: Element) => el.getBoundingClientRect();
      const parts = [...li.querySelectorAll("button, [data-testid=due], [role=img]")].map(box);
      const [title, marks] = [box(li.querySelector("[data-row-title]")!), box(li.lastElementChild!)];
      return {
        insideViewport: parts.every((p) => p.left >= 0 && p.right <= window.innerWidth + 0.5),
        insideRow: parts.every((p) => p.top >= row.top - 0.5 && p.bottom <= row.bottom + 0.5),
        marksBelowTitle: marks.top >= title.bottom,
        titleWidth: title.width,
      };
    }),
  );
  expect(rows).toHaveLength(13);
  for (const row of rows) {
    expect(row.insideViewport).toBe(true);
    expect(row.insideRow).toBe(true);
    // The marks move under the title, which gets the row's width instead of a truncated sliver.
    expect(row.marksBelowTitle).toBe(true);
    expect(row.titleWidth).toBeGreaterThan(280);
  }
  await page.screenshot({ path: join(RESULTS, "list-375.png"), fullPage: true });
  await context.close();
});

test("the list raises no console error or warning through its states, and works from the keyboard", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const problems: string[] = [];
  page.on("console", (m: ConsoleMessage) => {
    if (m.type() === "error" || m.type() === "warning") problems.push(`${m.type()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));

  await page.goto(APP_URL);
  await page.getByText("13 tasks", { exact: true }).waitFor();

  // Quick-add keeps the focus; Escape clears; an empty Enter adds nothing.
  const quickAdd = page.getByRole("textbox", { name: "Add a task" });
  await quickAdd.fill("Typed and abandoned");
  await quickAdd.press("Escape");
  await expect(quickAdd).toHaveValue("");
  await quickAdd.press("Enter");
  await expect(page.getByText("13 tasks", { exact: true })).toBeVisible();
  await quickAdd.fill("Keyboard made this");
  await quickAdd.press("Enter");
  await expect(page.getByText("14 tasks", { exact: true })).toBeVisible();
  await expect(quickAdd).toBeFocused();
  await expect(quickAdd).toHaveValue("");

  // Arrow into the rows, walk down, complete with Space: focus follows the list.
  await quickAdd.press("ArrowDown");
  const first = page.locator("[data-row-title]").first();
  await expect(first).toBeFocused();
  await page.keyboard.press("ArrowDown");
  const second = page.locator("[data-row-title]").nth(1);
  await expect(second).toBeFocused();
  const secondTitle = await second.textContent();
  await page.keyboard.press("Space");
  await expect(page.getByText("13 tasks", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: secondTitle!, exact: true })).toHaveCount(0);
  await expect(page.locator("[data-row-title]").nth(1)).toBeFocused();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // The focus ring is drawn on the row, in the accent colour.
  const ring = await page.locator('ul[aria-label="Tasks"] > li').nth(1).evaluate((li) => {
    const cs = getComputedStyle(li);
    return { style: cs.outlineStyle, width: cs.outlineWidth, colour: cs.outlineColor, accent: getComputedStyle(document.documentElement).getPropertyValue("--acc").trim() };
  });
  expect(ring).toMatchObject({ style: "solid", width: "2px", colour: "rgb(198, 244, 50)" });
  await page.screenshot({ path: join(RESULTS, "list-focus-ring.png") });

  // Enter opens; Escape closes.
  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // Done rows, then the empty state.
  await page.getByRole("combobox", { name: "Status" }).selectOption("done");
  await expect(page.getByRole("checkbox").first()).toBeChecked();
  await page.getByPlaceholder("Search tasks").fill("zzzz-no-such-task");
  await expect(page.getByText("No tasks match these filters.")).toBeVisible();

  await context.close();
  expect(problems, problems.join("\n")).toEqual([]);
});
