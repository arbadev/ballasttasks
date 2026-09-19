import { expect, test, type Locator } from "@playwright/test";
import { APP_URL } from "../playwright.config";

/** Measure the painted ring, not a CSS class or a screenshot-diff allowance. */
async function focusGeometry(select: Locator) {
  return select.evaluate((element) => {
    const control = element.closest("label")!;
    const bounds = control.getBoundingClientRect();
    const rings = [control, ...control.querySelectorAll("*")].flatMap((node) => {
      const style = getComputedStyle(node);
      const width = parseFloat(style.outlineWidth);
      if (style.outlineStyle === "none" || width === 0) return [];
      const box = node.getBoundingClientRect();
      const offset = parseFloat(style.outlineOffset);
      return [{
        left: box.left - offset - width, top: box.top - offset - width,
        right: box.right + offset + width, bottom: box.bottom + offset + width,
        color: style.outlineColor, width, offset,
      }];
    });
    return {
      focused: document.activeElement === element,
      focusVisible: element.matches(":focus-visible"),
      control: { left: bounds.left, top: bounds.top, right: bounds.right, bottom: bounds.bottom },
      rings,
    };
  });
}

function expectOuterRing(geometry: Awaited<ReturnType<typeof focusGeometry>>) {
  expect(geometry.focused).toBe(true);
  expect(geometry.focusVisible).toBe(true);
  expect(geometry.rings).toHaveLength(1);
  expect(geometry.rings[0]).toEqual({
    left: geometry.control.left - 4, top: geometry.control.top - 4,
    right: geometry.control.right + 4, bottom: geometry.control.bottom + 4,
    color: "rgb(198, 244, 50)", width: 2, offset: 2,
  });
}

for (const width of [1440, 375]) {
  for (const reducedMotion of ["no-preference", "reduce"] as const) {
    test(`filter focus encloses the complete control at ${width}px (${reducedMotion})`, async ({ browser }, info) => {
      const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion });
      const page = await context.newPage();
      const problems: string[] = [];
      page.on("console", (message) => {
        if (["error", "warning"].includes(message.type())) problems.push(message.text());
      });
      page.on("pageerror", (error) => problems.push(error.message));
      await page.goto(APP_URL);
      await expect(page.getByText("13 tasks", { exact: true })).toBeVisible();
      expect(await page.evaluate(() => innerWidth)).toBe(width);
      expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(reducedMotion === "reduce");
      const due = page.getByRole("combobox", { name: "Due", exact: true });
      await expect(due).toHaveValue("any");
      await expect(due.getByRole("option")).toHaveText(["Any date", "Overdue", "Today", "Next 7 days", "No date"]);

      // Real pointer focus, then Tab away/back: never replace native focus with a synthetic event.
      await due.click();
      await expect(due).toBeFocused();
      const pointer = await focusGeometry(due);
      if (pointer.focusVisible) expectOuterRing(pointer);
      await page.screenshot({ path: info.outputPath("pointer.png") });
      await page.keyboard.press("Tab");
      await expect(page.getByRole("combobox", { name: "Priority", exact: true })).toBeFocused();
      await page.keyboard.press("Shift+Tab");
      // No settling wait: normal-motion focus must already be fully visible on the first frame.
      const immediate = await focusGeometry(due);
      await info.attach("immediate-focus-geometry", { body: JSON.stringify(immediate), contentType: "application/json" });
      await page.screenshot({ path: info.outputPath("keyboard.png") });
      expectOuterRing(immediate);

      // Native type-ahead/Enter selects overdue and updates the real workspace's visible rows.
      await page.keyboard.press("o");
      await page.keyboard.press("Enter");
      await expect(due).toHaveValue("overdue");
      await expect(page.getByRole("checkbox", { name: /^Complete:/ })).toHaveCount(1);
      await expect(page.getByRole("button", { name: "Write PRD.md: overview, user stories, scope", exact: true })).toBeVisible();
      expectOuterRing(await focusGeometry(due));
      await page.keyboard.press("Tab");
      await page.keyboard.press("Shift+Tab");
      await expect(due).toHaveValue("overdue");
      await page.screenshot({ path: info.outputPath("selected.png") });

      // selectOption proves the native change contract, NOT OS popup pointer selection.
      await due.selectOption("none");
      await expect(page.getByRole("checkbox", { name: /^Complete:/ })).toHaveCount(2);
      await expect(page.getByRole("button", { name: "Rate limiting on the API", exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "Review Vectal task detail for assistant patterns", exact: true })).toBeVisible();
      await due.selectOption("any");
      await expect(page.getByRole("checkbox", { name: /^Complete:/ })).toHaveCount(13);
      await expect(due).toHaveValue("any");

      // The same primitive must retain accessible names, values and visible keyboard focus.
      await page.keyboard.press("Shift+Tab");
      for (const [name, value] of [["Status", "open"], ["Due", "any"], ["Priority", "any"], ["Sort", "urgency"]]) {
        const select = page.getByRole("combobox", { name, exact: true });
        await expect(select).toBeFocused();
        await expect(select).toHaveValue(value);
        expectOuterRing(await focusGeometry(select));
        await page.keyboard.press("Tab");
      }
      await expect(page.getByRole("searchbox", { name: "Search tasks" })).toBeFocused();
      expect(problems).toEqual([]);
      await context.close();
    });
  }
}
