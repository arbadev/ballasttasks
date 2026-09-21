import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type ConsoleMessage } from "@playwright/test";
import { APP_URL } from "../playwright.config";

const RESULTS = join(__dirname, "..", "visual-results");

// Needs no design snapshot: these check the app alone, in a real browser.
test.beforeAll(() => mkdirSync(RESULTS, { recursive: true }));

const WIDTHS = [375, 768, 1024, 1440];

for (const width of WIDTHS) {
  test(`no horizontal page scroll at ${width}px, in the list, the board and an open task`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height: 812 }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

    await page.goto(APP_URL);
    await page.getByText("13 tasks", { exact: true }).waitFor();
    expect(await page.evaluate(() => window.innerWidth)).toBe(width);
    expect(await overflow(), "list").toBeLessThanOrEqual(0);

    await page.getByText("Board", { exact: true }).click();
    expect(await overflow(), "board").toBeLessThanOrEqual(0);

    await page.getByText("List", { exact: true }).click();
    await page.getByRole("button", { name: "JWT authentication" }).click();
    await expect(page.getByRole("dialog", { name: "JWT authentication" })).toBeVisible();
    expect(await overflow(), "task open").toBeLessThanOrEqual(0);
    await page.screenshot({ path: join(RESULTS, `responsive-${width}-task-open.png`) });

    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toBeHidden();
    await page.screenshot({ path: join(RESULTS, `responsive-${width}.png`) });
    await context.close();
  });
}

test("at 375px the sidebar is a drawer: closed by default, opened by the menu button, closed by Escape", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 375, height: 812 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.goto(APP_URL);
  await page.getByText("13 tasks", { exact: true }).waitFor();

  const sidebar = page.getByRole("complementary", { name: "Workspace" });
  await expect(sidebar).toBeHidden();

  await page.getByRole("button", { name: "Open navigation" }).click();
  await expect(sidebar).toBeVisible();
  // Let the fade-in finish, then check the drawer is opaque: nothing may show through it.
  await sidebar.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));
  const surface = await sidebar.evaluate((el) => ({ opacity: getComputedStyle(el).opacity, background: getComputedStyle(el).backgroundColor }));
  expect(surface).toEqual({ opacity: "1", background: "rgb(25, 28, 32)" });
  await page.screenshot({ path: join(RESULTS, "responsive-375-drawer.png") });

  // A choice applies and closes the drawer.
  await sidebar.getByRole("link", { name: /^My tasks/ }).click();
  await expect(sidebar).toBeHidden();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("My tasks");

  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.keyboard.press("Escape");
  await expect(sidebar).toBeHidden();
  await context.close();
});

test("the task panel is full-screen at 375px", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 375, height: 812 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.goto(APP_URL);
  await page.getByRole("button", { name: "JWT authentication" }).click();
  const dialog = page.getByRole("dialog");
  // The panel slides in from 28px to the right; measure where it comes to rest.
  await dialog.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));
  const box = await dialog.boundingBox();
  expect(box).toMatchObject({ x: 0, y: 0, width: 375, height: 812 });
  await context.close();
});

test("the view switch is keyboard operable and shows a focus ring", async ({ page }) => {
  await page.goto(APP_URL);
  await page.getByText("13 tasks", { exact: true }).waitFor();
  await page.getByRole("radio", { name: "List" }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("radio", { name: "Board" })).toBeChecked();
  await expect(page.getByRole("region", { name: "Board" })).toBeVisible();

  const ring = await page.getByText("Board", { exact: true }).evaluate((label) => getComputedStyle(label).outlineStyle);
  expect(ring).toBe("solid");
});

test("no console errors or warnings across the shell's states", async ({ page }) => {
  const problems: string[] = [];
  const record = (m: ConsoleMessage) => {
    if (m.type() === "error" || m.type() === "warning") problems.push(`${m.type()}: ${m.text()}`);
  };
  page.on("console", record);
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));

  await page.goto(APP_URL);
  await page.getByText("13 tasks", { exact: true }).waitFor();
  await page.getByRole("link", { name: /^My tasks/ }).click();
  await page.getByRole("link", { name: /^Overdue/ }).click();
  await page.getByRole("link", { name: /^All tasks/ }).click();
  await page.getByRole("link", { name: /^Inbox/ }).click();
  await page.getByRole("link", { name: /^Inbox/ }).click();
  await page.getByRole("combobox", { name: "Status" }).selectOption("all");
  await page.getByRole("combobox", { name: "Due" }).selectOption("week");
  await page.getByRole("combobox", { name: "Priority" }).selectOption("1");
  await page.getByRole("combobox", { name: "Sort" }).selectOption("due");
  await page.getByRole("searchbox", { name: "Search tasks" }).fill("zzz");
  await expect(page.getByText("No tasks match these filters.")).toBeVisible();
  await page.getByRole("searchbox", { name: "Search tasks" }).fill("");
  await page.getByRole("combobox", { name: "Due" }).selectOption("any");
  await page.getByRole("combobox", { name: "Priority" }).selectOption("any");
  await page.getByRole("button", { name: /need an owner/ }).click();
  await page.getByRole("button", { name: "Show all" }).click();
  await page.getByText("Board", { exact: true }).click();
  await page.getByText("List", { exact: true }).click();
  await page.getByRole("button", { name: "New task" }).click();
  await expect(page.getByRole("dialog", { name: "Untitled task" })).toBeVisible();
  await page.getByRole("button", { name: "Close task" }).click();

  expect(problems).toEqual([]);
});
