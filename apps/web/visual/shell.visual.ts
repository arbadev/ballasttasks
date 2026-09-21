import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { APP_URL, DESIGN_URL } from "../playwright.config";
import { comparePngs } from "./compare";

const DESIGN_FILE = "Ballast%20Tasks%20v2.dc.html";
const RESULTS = join(__dirname, "..", "visual-results");

/** The brief's fidelity target: at most 1% of a region's pixels may differ. */
const MAX_RATIO = 0.01;

const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
];

/** The same four regions, located in the design's markup and in the app's. */
const REGIONS = [
  { name: "sidebar", design: "aside", app: "aside" },
  { name: "header", design: "main > header", app: "main > header" },
  { name: "filter-toolbar", design: "main > header + div", app: "main [role=toolbar]" },
  { name: "attention-strip", design: "main > header + div + div", app: "main section[aria-label=Attention]" },
];

/** Each state is reached by the same clicks on both sides. */
const STATES: { name: string; reach: (page: Page) => Promise<void> }[] = [
  { name: "default", reach: async () => {} },
  {
    name: "my-tasks-board-owner-signal",
    reach: async (page) => {
      await page.getByRole(page.url().startsWith(APP_URL) ? "link" : "button", { name: /^My tasks/ }).click();
      await page.getByText("Board", { exact: true }).click();
      await page.getByRole("button", { name: /need an owner/ }).click();
      // Park the pointer where nothing reacts to hover.
      await page.mouse.move(700, 600);
    },
  },
];

/**
 * Both pages get the same two adjustments, neither of which hides a product difference:
 * animations are frozen (the P0 dot blinks, so a screenshot would catch a random opacity),
 * and the Next.js dev-tools badge, which exists only under `next dev`, is removed.
 */
const FREEZE = `*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; } nextjs-portal { display: none !important; }`;

async function open(page: Page, url: string, ready: string) {
  await page.goto(url);
  await page.addStyleTag({ content: FREEZE });
  await page.getByText(ready, { exact: true }).first().waitFor();
  await page.evaluate(() => document.fonts.ready);
}

test.skip(!process.env.BT_DESIGN_DIR, "Set BT_DESIGN_DIR to the folder holding the design snapshot (Ballast Tasks v2.dc.html + support.js); it is kept out of the repository.");

test.beforeAll(() => mkdirSync(RESULTS, { recursive: true }));

const report: Record<string, { differing: number; total: number; percent: number; sameSize: boolean }> = {};
test.afterAll(() => writeFileSync(join(RESULTS, "report.json"), JSON.stringify(report, null, 2)));

for (const viewport of VIEWPORTS) {
  for (const state of STATES) {
    test(`shell matches the design at ${viewport.width}x${viewport.height}, ${state.name}`, async ({ browser }) => {
      const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
      const design = await context.newPage();
      const app = await context.newPage();
      const canvas = await context.newPage();

      await open(design, `${DESIGN_URL}/${DESIGN_FILE}`, "All tasks");
      await open(app, APP_URL, "13 tasks");
      await state.reach(design);
      await state.reach(app);

      const failures: string[] = [];
      for (const region of REGIONS) {
        const id = `${region.name}-${viewport.width}x${viewport.height}-${state.name}`;
        const designPng = await design.locator(region.design).first().screenshot();
        const appPng = await app.locator(region.app).first().screenshot();
        const result = await comparePngs(canvas, designPng, appPng);

        writeFileSync(join(RESULTS, `${id}-design.png`), designPng);
        writeFileSync(join(RESULTS, `${id}-app.png`), appPng);
        writeFileSync(join(RESULTS, `${id}-diff.png`), result.diff);
        report[id] = { differing: result.differing, total: result.width * result.height, percent: Number((result.ratio * 100).toFixed(3)), sameSize: result.sameSize };

        if (!result.sameSize) failures.push(`${id}: region sizes differ`);
        if (result.ratio > MAX_RATIO) failures.push(`${id}: ${(result.ratio * 100).toFixed(2)}% of pixels differ (max ${MAX_RATIO * 100}%)`);
      }

      await context.close();
      expect(failures, failures.join("\n")).toEqual([]);
    });
  }
}
