import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { Page } from "@playwright/test";
import { APP_URL, DESIGN_URL } from "../playwright.config";
import { comparePngs } from "./compare";

export const RESULTS = join(__dirname, "..", "visual-results");

export const DESIGN_PAGE = `${DESIGN_URL}/Ballast%20Tasks%20v2.dc.html`;
export const APP_PAGE = APP_URL;

/** The fidelity target: at most 1% of a region's pixels may differ. */
export const MAX_RATIO = 0.01;

export const DESKTOP_VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
];

export const SKIP_WITHOUT_DESIGN = "Set BT_DESIGN_DIR to the folder holding the design snapshot (Ballast Tasks v2.dc.html + support.js); it is kept out of the repository.";

/**
 * Applied to both pages alike, so it hides no product difference: animations and transitions
 * are frozen (a screenshot would otherwise catch a random frame of a blink or an entrance),
 * and the Next.js dev-tools badge, which exists only under `next dev`, is removed.
 */
const FREEZE = `*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; } nextjs-portal { display: none !important; }`;

export async function openFrozen(page: Page, url: string, ready: string) {
  await page.goto(url);
  await page.addStyleTag({ content: FREEZE });
  await page.getByText(ready, { exact: true }).first().waitFor();
  await page.evaluate(() => document.fonts.ready);
}

export const openDesign = (page: Page) => openFrozen(page, DESIGN_PAGE, "All tasks");
export const openApp = (page: Page) => openFrozen(page, APP_PAGE, "13 tasks");

export interface Measurement {
  differing: number;
  total: number;
  percent: number;
  sameSize: boolean;
}

/**
 * Compares the same region captured on both sides, saves design, app and diff images under
 * visual-results/, records the measurement, and returns what failed (nothing, ideally).
 */
export async function compareShots(canvas: Page, id: string, designPng: Buffer, appPng: Buffer, report: Record<string, Measurement>): Promise<string[]> {
  mkdirSync(RESULTS, { recursive: true });
  const result = await comparePngs(canvas, designPng, appPng);

  writeFileSync(join(RESULTS, `${id}-design.png`), designPng);
  writeFileSync(join(RESULTS, `${id}-app.png`), appPng);
  writeFileSync(join(RESULTS, `${id}-diff.png`), result.diff);
  report[id] = { differing: result.differing, total: result.width * result.height, percent: Number((result.ratio * 100).toFixed(3)), sameSize: result.sameSize };

  const failures: string[] = [];
  if (!result.sameSize) failures.push(`${id}: region sizes differ`);
  if (result.ratio > MAX_RATIO) failures.push(`${id}: ${(result.ratio * 100).toFixed(2)}% of pixels differ (max ${MAX_RATIO * 100}%)`);
  return failures;
}

/**
 * Merges into the file rather than replacing it: Playwright starts a fresh worker after a
 * failed test, and the measurements taken before the failure must survive that.
 */
export function writeReport(name: string, report: Record<string, Measurement>) {
  mkdirSync(RESULTS, { recursive: true });
  const file = join(RESULTS, name);
  const earlier: Record<string, Measurement> = existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : {};
  writeFileSync(file, JSON.stringify({ ...earlier, ...report }, null, 2));
}
