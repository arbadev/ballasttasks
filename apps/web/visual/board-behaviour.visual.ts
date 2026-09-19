import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { APP_PAGE, RESULTS } from "./harness";

/**
 * The board in a real browser, without the design: what jsdom cannot show. Real drag and
 * drop, keyboard focus following a moved card, the touch controls, sideways scrolling that
 * stays inside the board at 375px, reduced motion, and a silent console throughout.
 */

const PRD = "Write PRD.md: overview, user stories, scope";

const board = (page: Page) => page.getByRole("region", { name: "Board" });
const column = (page: Page, name: string) => board(page).locator("section").filter({ has: page.getByRole("heading", { name, exact: true }) });
const card = (page: Page, title: string) => board(page).getByRole("article", { name: title });
const grid = (page: Page) => board(page).locator("div:has(> section)");

function watchConsole(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning") problems.push(`${message.type()}: ${message.text()}`);
  });
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  return problems;
}

async function openBoard(page: Page) {
  await page.goto(APP_PAGE);
  await page.getByText("13 tasks", { exact: true }).waitFor();
  await page.getByText("Board", { exact: true }).click();
  await column(page, "To Do").waitFor();
}

const shot = (name: string) => join(RESULTS, `board-behaviour-${name}.png`);

/** Lets the entrances finish, so an evidence screenshot shows the settled board. The blink never ends and is left alone. */
const settled = (page: Page) =>
  page.evaluate(() => Promise.all(document.getAnimations().filter((a) => Number.isFinite(a.effect?.getComputedTiming().endTime)).map((a) => a.finished.catch(() => undefined))).then(() => undefined));

test.beforeAll(() => mkdirSync(RESULTS, { recursive: true }));

test("a card dragged with the mouse lands in the column it is dropped on", async ({ page }) => {
  const problems = watchConsole(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await openBoard(page);

  await card(page, PRD).dragTo(column(page, "Testing"), { targetPosition: { x: 140, y: 320 } });

  await expect(column(page, "Testing").getByRole("article", { name: PRD })).toBeVisible();
  await expect(column(page, "To Do").getByTestId("column-count")).toContainText("7");
  await expect(column(page, "Testing").getByTestId("column-count")).toContainText("3");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(problems).toEqual([]);
});

test("Shift+Arrow moves the focused card, focus follows it, and the move controls show under keyboard focus", async ({ page }) => {
  const problems = watchConsole(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await openBoard(page);

  const open = card(page, PRD).getByRole("button", { name: PRD, exact: true });
  const moveOn = card(page, PRD).getByRole("button", { name: `Move "${PRD}" to In Progress` });
  await expect(moveOn).toBeHidden();

  await open.focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(open).toBeFocused();
  await expect(moveOn).toBeVisible();
  await settled(page);
  await card(page, PRD).screenshot({ path: shot("card-keyboard-focus") });

  await page.keyboard.press("Shift+ArrowRight");
  await expect(column(page, "In Progress").getByRole("article", { name: PRD })).toBeVisible();
  await expect(open).toBeFocused();
  await expect(page.getByTestId("board-live")).toHaveText(`Moved "${PRD}" to In Progress.`);

  await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: PRD })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(problems).toEqual([]);
});

test("at 375px the columns scroll and snap inside the board, never the page, and touch gets move buttons", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 375, height: 812 }, deviceScaleFactor: 1, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  const problems = watchConsole(page);
  await openBoard(page);

  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(await overflow()).toBe(0);

  const scroller = grid(page);
  const metrics = await scroller.evaluate((el) => ({ scrollable: el.scrollWidth > el.clientWidth, snap: getComputedStyle(el).scrollSnapType, align: getComputedStyle(el.querySelector("section")!).scrollSnapAlign }));
  expect(metrics.scrollable).toBe(true);
  expect(metrics.snap).toContain("x");
  expect(metrics.align).toBe("start");

  // A coarse pointer cannot drag, so every card carries its move buttons.
  const moveOn = card(page, PRD).getByRole("button", { name: `Move "${PRD}" to In Progress` });
  await expect(moveOn).toBeVisible();
  // Rounded: the mobile viewport scale leaves the 36px control measured a fraction of a pixel short.
  expect(Math.round((await moveOn.boundingBox())!.height)).toBeGreaterThanOrEqual(36);
  await settled(page);
  await page.screenshot({ path: shot("375-first-column") });

  await moveOn.tap();
  await expect(column(page, "In Progress").getByRole("article", { name: PRD })).toBeAttached();
  await expect(page.getByRole("dialog")).toHaveCount(0);

  await scroller.evaluate((el) => el.scrollTo({ left: el.scrollWidth, behavior: "instant" }));
  await expect(column(page, "Done")).toBeInViewport();
  expect(await overflow()).toBe(0);
  await settled(page);
  await page.screenshot({ path: shot("375-last-column") });

  expect(problems).toEqual([]);
  await context.close();
});

test("the columns stay inside the board from 375px to 1440px", async ({ page }) => {
  for (const width of [375, 640, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await openBoard(page);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `page overflow at ${width}px`).toBe(0);
  }
});

test("the hot P0 mark is set in the accent-foreground token and reads at AA on the danger colour", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openBoard(page);

  // An open P0 inside its window: the design draws this mark in white, which is 3:1.
  const mark = card(page, "JWT authentication").getByText("Priority P0");
  const measured = await mark.evaluate((el) => {
    const resolve = (property: string, token: string) => {
      const probe = document.createElement("span");
      probe.style.setProperty(property, `var(${token})`);
      document.body.append(probe);
      const value = getComputedStyle(probe).getPropertyValue(property);
      probe.remove();
      return value;
    };
    const luminance = (rgb: string) => {
      const [r, g, b] = rgb.match(/[\d.]+/g)!.slice(0, 3).map((v) => {
        const c = Number(v) / 255;
        return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const style = getComputedStyle(el);
    const [light, dark] = [luminance(style.backgroundColor), luminance(style.color)].sort((a, b) => b - a);
    return {
      color: style.color,
      background: style.backgroundColor,
      accentForeground: resolve("color", "--acc-fg"),
      danger: resolve("background-color", "--danger"),
      contrast: (light + 0.05) / (dark + 0.05),
    };
  });

  expect(measured.color).toBe(measured.accentForeground);
  expect(measured.background).toBe(measured.danger);
  expect(measured.contrast).toBeGreaterThanOrEqual(4.5);
});

test("the board's own controls transition only what the design animates, so the focus ring is the accent at once", async ({ page }) => {
  const problems = watchConsole(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await openBoard(page);

  const open = card(page, PRD).getByRole("button", { name: PRD, exact: true });
  await open.focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");

  const move = card(page, PRD).getByRole("button", { name: `Move "${PRD}" to In Progress` });
  await expect(move).toBeVisible();

  // The focus ring is `outline: 2px solid var(--acc)` on :focus-visible, so any control that
  // transitions outline-color tweens its ring from the inherited text colour instead.
  const transitioned = (locator: Locator) => locator.evaluate((el) => getComputedStyle(el).transitionProperty.split(",").map((property) => property.trim()));

  const moveProperties = await transitioned(move);
  expect(moveProperties).not.toContain("outline-color");
  expect(moveProperties).not.toContain("all");
  expect(moveProperties).toContain("color");

  const addProperties = await transitioned(column(page, "To Do").locator("[data-column-add]"));
  expect(addProperties).not.toContain("outline-color");
  expect(addProperties).not.toContain("all");
  expect(addProperties).toEqual(expect.arrayContaining(["background-color", "color"]));

  expect(problems).toEqual([]);
});

test("reduced motion stills the card entrance and the hover lift", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  await openBoard(page);
  const durations = await card(page, PRD).evaluate((el) => ({ animation: getComputedStyle(el).animationDuration, transition: getComputedStyle(el).transitionDuration }));
  expect(parseFloat(durations.animation)).toBeLessThan(0.001);
  expect(durations.transition.split(",").every((d) => parseFloat(d) < 0.001)).toBe(true);
  await context.close();
});
