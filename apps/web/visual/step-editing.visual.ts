import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { APP_URL } from "../playwright.config";

const results = join(__dirname, "..", "visual-results", "step-editing");
const first = "Task entity and TaskStatus enum in domain";
const second = "TaskRepository port + in-memory fake, contract suite";
const rich = "Task CRUD endpoints with pagination and filters";

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
  await expect(down).toHaveCSS("opacity", "1");
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
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: join(results, "mobile-controls.png") });
  expect(warnings).toEqual([]);
  await context.close();
});
