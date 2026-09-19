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

/**
 * The one sanctioned exception, and it covers placeholder text only. The design leaves the
 * quick-add placeholder at the browser default, which fails AA; the app sets it in --fg-3.
 * So that region is compared twice: its structure, with the placeholder made transparent by
 * this same style on BOTH sides and held to the normal limit; and untouched, where the
 * difference is measured and reported, and the colour and its contrast are asserted instead.
 */
const HIDE_PLACEHOLDER = `input::placeholder { color: transparent !important; }`;
const MIN_CONTRAST = 4.5;

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
  {
    name: "quick-add-structure",
    reach: async (s) => {
      await s.page.addStyleTag({ content: HIDE_PLACEHOLDER });
      return s.quickAdd();
    },
  },
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

/** The placeholder's computed colour, the --fg-3 token resolved the same way, and the WCAG contrast on what is behind it. */
async function placeholderColour(page: Page) {
  return page.evaluate(() => {
    const input = document.querySelector<HTMLInputElement>('input[aria-label="Add a task"]')!;
    const rgb = (colour: string) => (colour.match(/[\d.]+/g) ?? []).map(Number);
    const probe = document.createElement("span");
    probe.style.color = "var(--fg-3)";
    document.body.append(probe);
    const token = getComputedStyle(probe).color;
    probe.remove();

    // The input is transparent: the background is the first opaque one behind it.
    let behind = "rgb(0, 0, 0)";
    for (let el: Element | null = input; el; el = el.parentElement) {
      const [, , , alpha = 1] = rgb(getComputedStyle(el).backgroundColor);
      if (alpha === 1) {
        behind = getComputedStyle(el).backgroundColor;
        break;
      }
    }
    const luminance = (colour: string) => {
      const [r, g, b] = rgb(colour).map((c) => (c / 255 <= 0.03928 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4));
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const placeholder = getComputedStyle(input, "::placeholder").color;
    const [hi, lo] = [luminance(placeholder), luminance(behind)].sort((a, b) => b - a);
    return { placeholder, token, behind, contrast: Number(((hi + 0.05) / (lo + 0.05)).toFixed(2)) };
  });
}

for (const viewport of VIEWPORTS) {
  test(`list quick-add placeholder is the accessible token colour at ${viewport.width}x${viewport.height}; the untouched region is measured`, async ({ browser }) => {
    const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
    const design = await context.newPage();
    const app = await context.newPage();
    const canvas = await context.newPage();
    await open(design, `${DESIGN_URL}/${DESIGN_FILE}`, "All tasks");
    await open(app, APP_URL, "13 tasks");

    // Nothing hidden here: this is the real difference, reported rather than limited.
    const designPng = await designSide(design).quickAdd().screenshot();
    const appPng = await appSide(app).quickAdd().screenshot();
    const result = await comparePngs(canvas, designPng, appPng);
    const id = `list-quick-add-untouched-${viewport.width}x${viewport.height}`;
    writeFileSync(join(RESULTS, `${id}-design.png`), designPng);
    writeFileSync(join(RESULTS, `${id}-app.png`), appPng);
    writeFileSync(join(RESULTS, `${id}-diff.png`), result.diff);
    record(id, { differing: result.differing, total: result.width * result.height, percent: Number((result.ratio * 100).toFixed(3)), sameSize: result.sameSize });

    const colour = await placeholderColour(app);
    const designColour = await placeholderColour(design);
    writeFileSync(join(RESULTS, `list-quick-add-placeholder-${viewport.width}x${viewport.height}.json`), JSON.stringify({ app: colour, design: designColour }, null, 2));
    await context.close();

    expect(result.sameSize, `${id}: region sizes differ`).toBe(true);
    expect(colour.placeholder, "the placeholder is not the --fg-3 token").toBe(colour.token);
    expect(colour.contrast, `placeholder contrast on ${colour.behind}`).toBeGreaterThanOrEqual(MIN_CONTRAST);
  });

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
