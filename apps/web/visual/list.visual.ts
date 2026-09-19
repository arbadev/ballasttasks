import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { APP_URL, DESIGN_URL } from "../playwright.config";
import { comparePngs } from "./compare";

const DESIGN_FILE = "Ballast%20Tasks%20v2.dc.html";
const RESULTS = join(__dirname, "..", "visual-results");

/** The same fidelity target as the shell: at most 1% of a region's pixels may differ. */
const MAX_RATIO = 0.01;

const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
];

/** Animations frozen and the dev-tools badge removed on both sides, exactly as in shell.visual.ts. */
const FREEZE = `*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; } nextjs-portal { display: none !important; }`;

/**
 * Selecting a row opens the task panel, whose backdrop covers and blurs the list on both
 * sides. The panel belongs to the detail slice; what is compared here is the selected ROW,
 * so the overlay is hidden on both sides for that one state, and only for it.
 */
const HIDE_DESIGN_PANEL = `div[style*="z-index: 40"] { display: none !important; }`;
const HIDE_APP_PANEL = `div:has(> [role=dialog]) { display: none !important; }`;

const DEFAULT_ROW = "Unit tests at 80% coverage or more";
const OVERDUE_ROW = "Write PRD.md: overview, user stories, scope";

interface Side {
  page: Page;
  list: () => Locator;
  quickAdd: () => Locator;
  row: (title: string) => Locator;
  firstRow: () => Locator;
  empty: () => Locator;
  hidePanel: string;
}

const designSide = (page: Page): Side => {
  const list = () => page.locator('div:has(> div > input[aria-label="Add a task"])');
  const rows = () => list().locator('> div[style*="grid-template-columns"]');
  return {
    page,
    list,
    quickAdd: () => page.locator('div:has(> input[aria-label="Add a task"])'),
    row: (title) => rows().filter({ hasText: title }),
    firstRow: () => rows().first(),
    empty: () => page.getByText("No tasks match these filters.", { exact: true }),
    hidePanel: HIDE_DESIGN_PANEL,
  };
};

const appSide = (page: Page): Side => {
  const rows = () => page.locator('ul[aria-label="Tasks"] > li');
  return {
    page,
    list: () => page.locator('div:has(> ul[aria-label="Tasks"])'),
    quickAdd: () => page.locator('div:has(> div > input[aria-label="Add a task"])'),
    row: (title) => rows().filter({ hasText: title }),
    firstRow: () => rows().first(),
    empty: () => page.getByText("No tasks match these filters.", { exact: true }),
    hidePanel: HIDE_APP_PANEL,
  };
};

/** Each case puts both sides in the same state with the same user actions, then names what to shoot. */
const CASES: { name: string; reach: (side: Side) => Promise<Locator> }[] = [
  { name: "row-default", reach: async (s) => s.row(DEFAULT_ROW) },
  { name: "row-overdue", reach: async (s) => s.row(OVERDUE_ROW) },
  {
    name: "row-hovered",
    reach: async (s) => {
      await s.row(DEFAULT_ROW).hover({ position: { x: 400, y: 30 } });
      return s.row(DEFAULT_ROW);
    },
  },
  {
    name: "row-selected",
    reach: async (s) => {
      await s.row(DEFAULT_ROW).click({ position: { x: 400, y: 30 } });
      await s.page.addStyleTag({ content: s.hidePanel });
      await s.page.mouse.move(700, 100);
      return s.row(DEFAULT_ROW);
    },
  },
  {
    name: "row-done",
    reach: async (s) => {
      // By position: the design's selects carry no accessible name. Status is the toolbar's first.
      await s.page.locator("main select").first().selectOption("done");
      await s.page.mouse.move(700, 100);
      return s.firstRow();
    },
  },
  { name: "quick-add", reach: async (s) => s.quickAdd() },
  {
    name: "empty-state",
    reach: async (s) => {
      await s.page.getByPlaceholder("Search tasks").fill("zzzz-no-such-task");
      await s.empty().waitFor();
      return s.empty();
    },
  },
  { name: "list-region", reach: async (s) => s.list() },
];

async function open(page: Page, url: string, ready: string) {
  await page.goto(url);
  await page.addStyleTag({ content: FREEZE });
  await page.getByText(ready, { exact: true }).first().waitFor();
  await page.evaluate(() => document.fonts.ready);
  await page.mouse.move(700, 100);
}

test.skip(!process.env.BT_DESIGN_DIR, "Set BT_DESIGN_DIR to the folder holding the design snapshot (Ballast Tasks v2.dc.html + support.js); it is kept out of the repository.");

test.beforeAll(() => mkdirSync(RESULTS, { recursive: true }));

type Measurement = { differing: number; total: number; percent: number; sameSize: boolean };
const REPORT = join(RESULTS, "list-report.json");

/**
 * Written per comparison and merged into the file, never held in memory until the end:
 * Playwright starts a fresh worker after a failed test, which would drop every earlier entry.
 */
function record(id: string, measurement: Measurement) {
  const report: Record<string, Measurement> = existsSync(REPORT) ? JSON.parse(readFileSync(REPORT, "utf8")) : {};
  report[id] = measurement;
  writeFileSync(REPORT, JSON.stringify(report, null, 2));
}

for (const viewport of VIEWPORTS) {
  for (const state of CASES) {
    test(`list ${state.name} matches the design at ${viewport.width}x${viewport.height}`, async ({ browser }) => {
      const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
      const design = await context.newPage();
      const app = await context.newPage();
      const canvas = await context.newPage();

      await open(design, `${DESIGN_URL}/${DESIGN_FILE}`, "All tasks");
      await open(app, APP_URL, "13 tasks");

      const designPng = await (await state.reach(designSide(design))).screenshot();
      const appPng = await (await state.reach(appSide(app))).screenshot();
      const result = await comparePngs(canvas, designPng, appPng);

      const id = `list-${state.name}-${viewport.width}x${viewport.height}`;
      writeFileSync(join(RESULTS, `${id}-design.png`), designPng);
      writeFileSync(join(RESULTS, `${id}-app.png`), appPng);
      writeFileSync(join(RESULTS, `${id}-diff.png`), result.diff);
      record(id, { differing: result.differing, total: result.width * result.height, percent: Number((result.ratio * 100).toFixed(3)), sameSize: result.sameSize });

      await context.close();
      expect(result.sameSize, `${id}: region sizes differ`).toBe(true);
      expect(result.ratio, `${id}: ${(result.ratio * 100).toFixed(2)}% of pixels differ (max ${MAX_RATIO * 100}%)`).toBeLessThanOrEqual(MAX_RATIO);
    });
  }
}
