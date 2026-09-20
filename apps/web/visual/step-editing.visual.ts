import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { APP_URL } from "../playwright.config";

const results = join(__dirname, "..", "visual-results", "step-editing");
const first = "Task entity and TaskStatus enum in domain";
const second = "TaskRepository port + in-memory fake, contract suite";
const rich = "Task CRUD endpoints with pagination and filters";
const long = "npm run gen:api and fix the frontend types in the same commit";

async function tabTo(page: Page, control: Locator) {
  for (let i = 0; i < 80; i++) {
    if (await control.evaluate((el) => el === document.activeElement)) return;
    await page.keyboard.press("Tab");
  }
  throw new Error("Step control not reachable by native Tab traversal");
}

async function hit(control: Locator, touch = false) {
  await control.scrollIntoViewIfNeeded();
  const box = await control.boundingBox();
  expect(box).not.toBeNull();
  if (touch) { expect(box!.width).toBeGreaterThanOrEqual(44); expect(box!.height).toBeGreaterThanOrEqual(44); }
  expect(await control.evaluate((el) => {
    const b = el.getBoundingClientRect();
    return el.contains(document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2));
  })).toBe(true);
}

interface Box { x: number; y: number; width: number; height: number }

const apart = (a: Box, b: Box) => a.x + a.width <= b.x || b.x + b.width <= a.x || a.y + a.height <= b.y || b.y + b.height <= a.y;

/** Every point across the control's text lines hits the control itself, nothing on top of it. */
async function ownsItsText(control: Locator) {
  const box = (await control.boundingBox())!;
  for (const y of [box.y + 8, box.y + box.height - 8]) {
    for (let at = 2; at < box.width - 2; at += 8) {
      const owner = await control.evaluate((el, point) => el.contains(document.elementFromPoint(point[0], point[1])), [box.x + at, y] as [number, number]);
      expect(owner, `point ${Math.round(box.x + at)},${Math.round(y)} is covered`).toBe(true);
    }
  }
}

test.beforeAll(() => mkdirSync(results, { recursive: true }));

test("step rename and order have independent keyboard targets without changing the resting panel geometry", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(APP_URL);
  await page.getByText(rich, { exact: true }).click();
  const section = page.getByRole("region", { name: "Steps" });
  const rename = section.getByRole("button", { name: `Rename step: ${first}` });
  await tabTo(page, rename);
  await expect(rename).toBeFocused();
  await page.keyboard.press("Enter");
  const input = section.getByRole("textbox", { name: "Step title" });
  await expect(input).toBeFocused();
  await input.fill("Keyboard revised");
  await page.keyboard.press("Escape");
  await expect(rename).toBeFocused();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Enter");
  await input.fill("Keyboard revised");
  await page.keyboard.press("Enter");
  await expect(section.getByRole("checkbox", { name: "Keyboard revised" })).toBeChecked();
  const down = section.getByRole("button", { name: "Move step down: Keyboard revised" });
  await tabTo(page, down);
  await hit(down);
  await page.screenshot({ path: join(results, "keyboard-controls.png") });
  await page.keyboard.press("Enter");
  await expect(section.getByRole("checkbox").nth(1)).toHaveAccessibleName("Keyboard revised");
  await expect(section.getByRole("button", { name: `Move step up: ${second}` })).toBeDisabled();
  await page.keyboard.press("Escape");
  await page.getByText(rich, { exact: true }).click();
  await expect(section.getByRole("checkbox").nth(1)).toHaveAccessibleName("Keyboard revised");
});

test("the move controls keep their own slot: the title stays readable and clickable under the pointer", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(APP_URL);
  await page.getByText(rich, { exact: true }).click();
  const section = page.getByRole("region", { name: "Steps" });
  const steps = section.getByRole("checkbox");
  const last = await steps.count() - 1;
  const title = section.getByRole("button", { name: `Rename step: ${long}` });
  const up = section.getByRole("button", { name: `Move step up: ${long}` });
  const down = section.getByRole("button", { name: `Move step down: ${long}` });
  const oneLine = (await section.getByRole("button", { name: `Rename step: ${first}` }).boundingBox())!.height;

  for (const width of [1440, 768]) {
    await page.setViewportSize({ width, height: 900 });
    await title.scrollIntoViewIfNeeded();
    const resting = (await title.boundingBox())!;
    await title.hover();
    await expect(up.locator("xpath=..")).toHaveCSS("opacity", "1");
    const hovered = (await title.boundingBox())!;
    expect([Math.round(hovered.width), Math.round(hovered.height)], "hovering the row reflowed the title").toEqual([Math.round(resting.width), Math.round(resting.height)]);
    for (const control of [up, down]) expect(apart(hovered, (await control.boundingBox())!), "a move control overlaps the title").toBe(true);
    await ownsItsText(title);
    await page.screenshot({ path: join(results, `hovered-row-${width}.png`) });
  }
  expect((await title.boundingBox())!.height, "the title should wrap at 768px").toBeGreaterThan(oneLine);

  const box = (await title.boundingBox())!;
  await page.mouse.click(box.x + box.width - 6, box.y + 8);
  const input = section.getByRole("textbox", { name: "Step title" });
  await expect(input).toBeFocused();
  await expect(input).toHaveValue(long);
  await expect(steps.nth(last)).toHaveAccessibleName(long);
  await page.keyboard.press("Escape");
  await expect(steps.nth(last)).toHaveAccessibleName(long);
});


test("a keyboard move hands the focus back to the row, and to the other arrow at the boundary", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(APP_URL);
  await page.getByText(rich, { exact: true }).click();
  const section = page.getByRole("region", { name: "Steps" });
  const steps = section.getByRole("checkbox");
  const total = await steps.count();
  const down = section.getByRole("button", { name: `Move step down: ${first}` });
  await tabTo(page, down);
  for (let position = 1; position < total; position++) {
    await page.keyboard.press("Enter");
    await expect(steps.nth(position)).toHaveAccessibleName(first);
    if (position < total - 1) await expect(down).toBeFocused();
  }
  await expect(down).toBeDisabled();
  await expect(section.getByRole("button", { name: `Move step up: ${first}` })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(steps.nth(total - 2)).toHaveAccessibleName(first);
  await expect(section.getByRole("button", { name: `Move step up: ${first}` })).toBeFocused();
});

test("a click inside an open rename input lands in the input and moves no step", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(APP_URL);
  await page.getByText(rich, { exact: true }).click();
  const section = page.getByRole("region", { name: "Steps" });
  const down = section.getByRole("button", { name: `Move step down: ${first}` });
  await expect(down).toHaveCount(1);
  await section.getByRole("button", { name: `Rename step: ${first}` }).click();
  const input = section.getByRole("textbox", { name: "Step title" });
  await expect(input).toBeFocused();
  await expect(down).toHaveCount(0);
  await expect(section.getByRole("button", { name: `Move step up: ${second}` })).toHaveCount(1);
  const box = (await input.boundingBox())!;
  const caret: [number, number] = [box.x + box.width - 20, box.y + 6];
  expect(await input.evaluate((el, [x, y]) => el === document.elementFromPoint(x, y), caret)).toBe(true);
  await page.mouse.click(caret[0], caret[1]);
  await expect(input).toBeFocused();
  await expect(section.getByRole("status")).toHaveCount(0);
  await expect(section.getByRole("checkbox").nth(0)).toHaveAccessibleName(first);
  await expect(section.getByRole("checkbox").nth(1)).toHaveAccessibleName(second);
  await page.keyboard.press("Escape");
  await expect(section.getByRole("button", { name: `Rename step: ${first}` })).toBeFocused();
  await hit(down);
  await down.click();
  await expect(section.getByRole("checkbox").nth(0)).toHaveAccessibleName(second);
  await expect(section.getByRole("checkbox").nth(1)).toHaveAccessibleName(first);
});

test("coarse-pointer step moves are visible, 44px, non-overlapping and tappable at 375px", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  const warnings: string[] = [];
  page.on("console", (message) => { if (["error", "warning"].includes(message.type())) warnings.push(message.text()); });
  page.on("pageerror", (error) => warnings.push(error.message));
  await page.goto(APP_URL);
  await page.getByText(rich, { exact: true }).tap();
  const section = page.getByRole("region", { name: "Steps" });
  const down = section.getByRole("button", { name: `Move step down: ${first}` });
  await expect(down.locator("xpath=..")).toHaveCSS("opacity", "1");
  await hit(down, true);
  const row = down.locator("xpath=../..");
  await expect(row.getByRole("checkbox")).toBeChecked();
  await down.tap();
  await expect(section.getByRole("checkbox").nth(1)).toHaveAccessibleName(first);
  await expect(section.getByRole("checkbox").nth(1)).toBeChecked();
  await section.getByRole("button", { name: `Rename step: ${first}` }).tap();
  await section.getByRole("textbox", { name: "Step title" }).fill("Touch revised");
  const save = section.getByRole("button", { name: "Save step title" });
  await hit(save);
  await save.tap();
  await expect(section.getByRole("checkbox", { name: "Touch revised" })).toBeChecked();
  await section.getByRole("button", { name: "Move step down: Touch revised" }).scrollIntoViewIfNeeded();
  for (const control of ["Move step up", "Move step down"]) {
    const box = (await section.getByRole("button", { name: `${control}: Touch revised` }).boundingBox())!;
    expect(apart(box, (await section.getByRole("button", { name: "Rename step: Touch revised" }).boundingBox())!), "the move control overlaps the title").toBe(true);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: join(results, "mobile-controls.png") });
  expect(warnings).toEqual([]);
  await context.close();
});
