import { expect, test, type Page } from "@playwright/test";
import { APP_URL } from "../playwright.config";

/** Real Next history integration: the URL reaches useSearchParams inside a transition, not synchronously. */
async function openTasks(page: Page) {
  await page.goto(`${APP_URL}/tasks`);
  await expect(page.getByText("13 tasks", { exact: true })).toBeVisible();
  return page.getByRole("searchbox", { name: "Search tasks" });
}

const searchParam = (page: Page) => new URL(page.url()).searchParams.get("q");

test("search keeps every keystroke typed one key at a time and replaces the URL", async ({ page }) => {
  const search = await openTasks(page);
  const entries = await page.evaluate(() => history.length);
  await search.click();
  await search.pressSequentially("write prd.md: overview, user stories");
  await expect(search).toHaveValue("write prd.md: overview, user stories");
  await expect.poll(() => searchParam(page)).toBe("write prd.md: overview, user stories");
  expect(await page.evaluate(() => history.length)).toBe(entries);
  await expect(page.getByRole("button", { name: "Write PRD.md: overview, user stories, scope", exact: true })).toBeVisible();
  await expect(page.getByRole("checkbox", { name: /^Complete:/ })).toHaveCount(1);
});

test("typing in the middle of the search keeps the caret where it was", async ({ page }) => {
  const search = await openTasks(page);
  await search.click();
  await search.pressSequentially("prdmd");
  await expect.poll(() => searchParam(page)).toBe("prdmd");
  for (let i = 0; i < 2; i++) await page.keyboard.press("ArrowLeft");
  await search.pressSequentially(".");
  await expect(search).toHaveValue("prd.md");
  expect(await search.evaluate((input: HTMLInputElement) => input.selectionStart)).toBe(4);
  await expect.poll(() => searchParam(page)).toBe("prd.md");
  await expect(page.getByRole("checkbox", { name: /^Complete:/ })).toHaveCount(1);
});

test("search stops at the route's 200 characters instead of emptying the box", async ({ page }) => {
  const search = await openTasks(page);
  await search.click();
  await search.pressSequentially("a".repeat(201));
  await expect(search).toHaveValue("a".repeat(200));
  await expect.poll(() => searchParam(page)).toBe("a".repeat(200));
});

test("Back and Forward carry the search box with the URL", async ({ page }) => {
  const search = await openTasks(page);
  await page.getByRole("combobox", { name: "Due", exact: true }).selectOption("overdue");
  await expect(page).toHaveURL(/due=overdue/);
  await search.click();
  await search.pressSequentially("prd");
  await expect.poll(() => searchParam(page)).toBe("prd");
  await page.goBack();
  await expect(page).toHaveURL(`${APP_URL}/tasks`);
  await expect(search).toHaveValue("");
  await expect(page.getByText("13 tasks", { exact: true })).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(`${APP_URL}/tasks?due=overdue&q=prd`);
  await expect(search).toHaveValue("prd");
});
