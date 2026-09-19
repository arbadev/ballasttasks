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
 * The two sanctioned exceptions, and they cover text colour only: in both the design's colour
 * fails AA, so the difference is measured and reported, and the app's colour and its contrast
 * are asserted instead.
 *
 * The quick-add placeholder: the design leaves it at the browser default; the app sets it in
 * --fg-3. That region is compared twice: its structure, with the placeholder made transparent
 * by this same style on BOTH sides and held to the normal limit; and untouched.
 *
 * The hot P0 pill: the design sets white on --danger; the app sets --acc-fg. Its row is still
 * held to the normal limit (row-hot), and the pill alone is measured untouched.
 */
const HIDE_PLACEHOLDER = `input::placeholder { color: transparent !important; }`;
const MIN_CONTRAST = 4.5;

const DEFAULT_ROW = "Unit tests at 80% coverage or more";
const OVERDUE_ROW = "Write PRD.md: overview, user stories, scope";
const HOT_ROW = "Task CRUD endpoints with pagination and filters";

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
  { name: "row-hot", reach: async (s) => s.row(HOT_ROW) },
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

interface Painted {
  selector: string;
  /** The pseudo-element that carries the text colour, when it is not the element itself. */
  pseudo?: string;
  /** The custom property the app sets the text in. */
  token: string;
}

/** A text's computed colour, its token resolved the same way, and the WCAG contrast on what is behind it. */
async function paintedColour(page: Page, target: Painted) {
  return page.evaluate(({ selector, pseudo, token: name }) => {
    const element = document.querySelector<HTMLElement>(selector)!;
    const rgb = (colour: string) => (colour.match(/[\d.]+/g) ?? []).map(Number);
    const probe = document.createElement("span");
    probe.style.color = `var(${name})`;
    document.body.append(probe);
    const token = getComputedStyle(probe).color;
    probe.remove();

    // The background is the first opaque one at or behind the element (the quick-add input is transparent).
    let behind = "rgb(0, 0, 0)";
    for (let el: Element | null = element; el; el = el.parentElement) {
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
    const colour = getComputedStyle(element, pseudo).color;
    const [hi, lo] = [luminance(colour), luminance(behind)].sort((a, b) => b - a);
    return { colour, token, behind, contrast: Number(((hi + 0.05) / (lo + 0.05)).toFixed(2)) };
  }, target);
}

const PLACEHOLDER: Painted = { selector: 'input[aria-label="Add a task"]', pseudo: "::placeholder", token: "--fg-3" };
const HOT_PILL_MARK = "data-visual-hot-pill";
const HOT_PILL: Painted = { selector: `[${HOT_PILL_MARK}]`, token: "--acc-fg" };

/**
 * The priority pill of the hot row, marked so the page-side measurement finds the same element.
 * The design's runtime wraps the label in an inner element, so the pill is the first box with
 * an opaque background at or above the text: on both sides it is the one solid pill in the row.
 */
async function hotPill(side: Side) {
  await side
    .row(HOT_ROW)
    .getByText(/^(Priority )?P0$/)
    .evaluate((el, mark) => {
      const alpha = (box: Element) => (getComputedStyle(box).backgroundColor.match(/[\d.]+/g) ?? []).map(Number)[3] ?? 1;
      let pill: Element | null = el;
      while (pill && alpha(pill) !== 1) pill = pill.parentElement;
      pill?.setAttribute(mark, "");
    }, HOT_PILL_MARK);
  return side.page.locator(`[${HOT_PILL_MARK}]`);
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

    const colour = await paintedColour(app, PLACEHOLDER);
    const designColour = await paintedColour(design, PLACEHOLDER);
    writeFileSync(join(RESULTS, `list-quick-add-placeholder-${viewport.width}x${viewport.height}.json`), JSON.stringify({ app: colour, design: designColour }, null, 2));
    await context.close();

    expect(result.sameSize, `${id}: region sizes differ`).toBe(true);
    expect(colour.colour, "the placeholder is not the --fg-3 token").toBe(colour.token);
    expect(colour.contrast, `placeholder contrast on ${colour.behind}`).toBeGreaterThanOrEqual(MIN_CONTRAST);
  });

  test(`list hot P0 pill text is the accessible token colour at ${viewport.width}x${viewport.height}; the untouched pill is measured`, async ({ browser }) => {
    const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
    const design = await context.newPage();
    const app = await context.newPage();
    const canvas = await context.newPage();
    await open(design, `${DESIGN_URL}/${DESIGN_FILE}`, "All tasks");
    await open(app, APP_URL, "13 tasks");

    // Nothing hidden here: this is the real difference, reported rather than limited.
    const designPng = await (await hotPill(designSide(design))).screenshot();
    const appPng = await (await hotPill(appSide(app))).screenshot();
    const result = await comparePngs(canvas, designPng, appPng);
    const id = `list-hot-pill-untouched-${viewport.width}x${viewport.height}`;
    writeFileSync(join(RESULTS, `${id}-design.png`), designPng);
    writeFileSync(join(RESULTS, `${id}-app.png`), appPng);
    writeFileSync(join(RESULTS, `${id}-diff.png`), result.diff);
    record(id, { differing: result.differing, total: result.width * result.height, percent: Number((result.ratio * 100).toFixed(3)), sameSize: result.sameSize });

    const colour = await paintedColour(app, HOT_PILL);
    const designColour = await paintedColour(design, HOT_PILL);
    writeFileSync(join(RESULTS, `list-hot-pill-${viewport.width}x${viewport.height}.json`), JSON.stringify({ app: colour, design: designColour }, null, 2));
    await context.close();

    expect(result.sameSize, `${id}: region sizes differ`).toBe(true);
    expect(colour.colour, "the hot pill text is not the --acc-fg token").toBe(colour.token);
    expect(colour.contrast, `hot pill contrast on ${colour.behind}`).toBeGreaterThanOrEqual(MIN_CONTRAST);
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
