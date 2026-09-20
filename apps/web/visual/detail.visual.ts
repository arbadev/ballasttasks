import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { APP_URL, DESIGN_URL } from "../playwright.config";
import { comparePngs } from "./compare";

const DESIGN_FILE = "Ballast%20Tasks%20v2.dc.html";
const RESULTS = join(__dirname, "..", "visual-results", "detail");

/** The brief's fidelity target: at most 1% of a region's pixels may differ. */
const MAX_RATIO = 0.01;

const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
];

/** The panel, cut into the same regions on both sides. The dialog's markup is parallel. */
const REGIONS = {
  header: "[role=dialog] > div:first-child",
  banner: "[role=dialog] > div:nth-child(2):not(:has(aside))",
  title: "[role=dialog] input[aria-label='Task name']",
  description: "[role=dialog] div:has(> textarea[placeholder^='What does done'])",
  steps: "[role=dialog] section >> nth=0",
  attachments: "[role=dialog] section >> nth=1",
  activity: "[role=dialog] section >> nth=2",
  properties: "[role=dialog] aside",
  footer: "[role=dialog] footer",
} as const;
type Region = keyof typeof REGIONS;

/**
 * Where the app differs from the design on purpose. Each entry is compared like any other
 * region and reported, but held to its own ceiling instead of 1%, and carries the reason for
 * it here; nothing is masked or skipped. Empty: the panel matches the design everywhere,
 * including the three regions whose superseded sentence is replaced in the rendered reference.
 */
const DEVIATIONS: { region: Region; states?: string[]; maxRatio: number; reason: string }[] = [];

/**
 * Only these three sentences supersede the design's unsupported attachment-reading claim.
 * The reference stays the reference: it is rendered, this one sentence is replaced in the
 * rendered DOM (the file on disk is never touched, nothing else is), and the whole region is
 * then held to the same 1% and 2-per-channel contract as every other region. The design's
 * original sentence is still diffed unmasked and reported, only without a ceiling of its own.
 */
const REVISED_COPY: Record<string, { region: Region; text: string; original: string }> = {
  "new-task": {
    region: "attachments",
    text: "Drop files here, or paste a link — reference files and links aren't read when drafting steps.",
    original: "Drop files here, or paste a link — PDFs, screenshots and threads the assistant can read.",
  },
  "generation-running": {
    region: "steps",
    text: "using the title, description and existing steps",
    original: "reading the title, description and 0 attachments",
  },
  "generation-proposed": {
    region: "steps",
    text: "Drafted from the title, description and existing steps. Remove what doesn't fit — nothing is added until you say so.",
    original: "Drafted from the title, description and attachments. Remove what doesn't fit — nothing is added until you say so.",
  },
};

/**
 * The rendered reference with only the superseded sentence rewritten. Exactly one visible node
 * must read the design's original sentence: a reference that no longer says it, or says it in
 * more than one place, fails here instead of quietly comparing the app against something else.
 */
async function supersedeCopy(page: Page, state: string) {
  const copy = REVISED_COPY[state];
  const replaced = await page.evaluate(({ original, text }) => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const hits: Text[] = [];
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.nodeValue?.trim() === original && node.parentElement?.checkVisibility()) hits.push(node as Text);
    }
    for (const node of hits) node.nodeValue = node.nodeValue!.replace(original, text);
    return hits.length;
  }, copy);
  expect(replaced, `the reference must show exactly one "${copy.original}"`).toBe(1);
}

/** Compare corresponding visible controls and copy, not differing DOM tags or hidden pickers. */
async function copyLayout(page: Page, state: string, side: "design" | "app") {
  const copy = REVISED_COPY[state];
  const controls = await page.locator(REGIONS[copy.region]).first().evaluate((section) => {
    const origin = section.getBoundingClientRect();
    const nodes = [section, ...section.querySelectorAll("button, input:not([type=file])")];
    return nodes.map((node) => {
      const box = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      return {
        box: [box.x - origin.x, box.y - origin.y, box.width, box.height].map((n) => Math.round(n)),
        fontSize: style.fontSize, lineHeight: style.lineHeight, fontWeight: style.fontWeight,
        color: style.color, background: style.backgroundColor, radius: style.borderRadius,
        padding: style.padding, borderWidth: style.borderWidth,
      };
    });
  });
  const message = page.getByText(side === "app" ? copy.text : copy.original, { exact: true });
  await expect(message).toBeVisible();
  const text = await message.evaluate((node, inline) => {
    // The reference templates dynamic text inside an extra inline wrapper. Measure the
    // corresponding flex item on both sides, not that wrapper's font-ink rectangle.
    let item = node;
    if (inline) while (item.parentElement && getComputedStyle(item.parentElement).display !== "flex") item = item.parentElement;
    const box = item.getBoundingClientRect();
    const section = item.closest("section")!.getBoundingClientRect();
    const style = getComputedStyle(item);
    return {
      // An inline span's width follows the deliberately changed glyphs; its origin/height,
      // section and surrounding controls still must match. Block text keeps its width too.
      box: [box.x - section.x, box.y - section.y, ...(inline ? [] : [box.width]), box.height].map((n) => Math.round(n)),
      fontSize: style.fontSize, lineHeight: style.lineHeight, fontWeight: style.fontWeight,
      color: style.color, background: style.backgroundColor, radius: style.borderRadius,
      padding: style.padding, borderWidth: style.borderWidth,
    };
  }, state === "generation-running");
  return { controls, text };
}

/**
 * Placeholders are set in --fg-3 for contrast, where the design leaves the browser default.
 * A region that holds one is therefore compared twice: for structure, with the placeholder
 * glyphs made transparent by the same style on both pages, under the normal 1% limit; and
 * untouched, measured and reported without a limit. Placeholder text is the only thing hidden.
 */
const PLACEHOLDER_REGIONS: Region[] = ["title", "description", "steps", "activity"];
const HIDE_PLACEHOLDERS = `::placeholder { color: transparent !important; }`;

const PROPERTY_CONTROLS = [
  { name: "status", selector: "[role=dialog] aside select >> nth=0", popup: true },
  { name: "assignee", selector: "[role=dialog] aside select >> nth=1", popup: true },
  { name: "due-date", selector: "[role=dialog] aside input[type=date]", popup: false },
  { name: "priority", selector: "[role=dialog] aside select >> nth=2", popup: true },
  { name: "importance", selector: "[role=dialog] aside input[type=number]", popup: false },
  { name: "project", selector: "[role=dialog] aside select >> nth=3", popup: true },
];

const RICH_TASK = "Task CRUD endpoints with pagination and filters";
const BARE_TASK = "JWT authentication";

const openTask = async (page: Page, title: string) => {
  await page.getByText(title, { exact: true }).first().click();
  await page.locator("[role=dialog]").waitFor();
};
/** Away from the panel at both widths, over the backdrop, where nothing reacts to hover. */
const parkPointer = (page: Page) => page.mouse.move(4, 4);

interface State {
  name: string;
  regions: Region[];
  reach: (page: Page) => Promise<void>;
}

/** Each state is reached by the same steps on both sides. */
const STATES: State[] = [
  {
    name: "rich-task",
    regions: ["header", "banner", "title", "description", "steps", "attachments", "activity", "properties", "footer"],
    reach: (page) => openTask(page, RICH_TASK),
  },
  {
    name: "new-task",
    regions: ["header", "banner", "title", "description", "steps", "attachments", "activity", "properties", "footer"],
    reach: async (page) => {
      await page.getByRole("button", { name: "New task" }).click();
      await page.locator("[role=dialog]").waitFor();
      // The app opens a new task with its title focused and selected; put the design there too.
      await page.locator(REGIONS.title).focus();
      await page.locator(REGIONS.title).selectText();
    },
  },
  {
    name: "generation-running",
    regions: ["banner", "steps"],
    reach: async (page) => {
      await openTask(page, BARE_TASK);
      await page.getByRole("button", { name: "Generate steps" }).click();
      await page.getByText("Drafting steps", { exact: true }).waitFor();
    },
  },
  {
    name: "generation-proposed",
    regions: ["banner", "steps"],
    reach: async (page) => {
      await openTask(page, BARE_TASK);
      await page.getByRole("button", { name: "Generate steps" }).click();
      await page.getByText(/^Assistant drafted \d+ steps$/).waitFor({ timeout: 10_000 });
    },
  },
];

/**
 * Both pages get the same adjustments, none of which hides a product difference: animations
 * and transitions are frozen (the shimmer, the pulsing sparkle and the P0 dot would be caught
 * mid-cycle), the caret is hidden, and the Next.js dev-tools badge is removed.
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

type Row = { differing: number; total: number; percent: number; sameSize: boolean; ceilingPercent: number | null; note?: string };
const report: Record<string, Row> = {};
/** One region as both sides show it. A side missing is itself a failure worth reporting. */
type Pair = { design?: Buffer; app?: Buffer };
test.afterAll(() => writeFileSync(join(RESULTS, "report.json"), JSON.stringify(report, null, 2)));

/**
 * A region's pixels, clipped to what its scroll container actually shows. The properties
 * column stretches taller than the viewport; an unclipped element screenshot would run past
 * the panel and pick up the page behind it, which is not this suite's subject.
 */
async function shoot(page: Page, selector: string): Promise<Buffer> {
  const clip = await page.locator(selector).first().evaluate((el) => {
    el.scrollIntoView({ block: "start", inline: "nearest" });
    const box = el.getBoundingClientRect();
    const seen = { left: box.left, top: box.top, right: box.right, bottom: box.bottom };
    const narrow = (b: { left: number; top: number; right: number; bottom: number }) => {
      seen.left = Math.max(seen.left, b.left);
      seen.top = Math.max(seen.top, b.top);
      seen.right = Math.min(seen.right, b.right);
      seen.bottom = Math.min(seen.bottom, b.bottom);
    };
    for (let parent = el.parentElement; parent; parent = parent.parentElement) {
      const { overflowX, overflowY } = getComputedStyle(parent);
      if (overflowX !== "visible" || overflowY !== "visible") narrow(parent.getBoundingClientRect());
    }
    narrow({ left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight });
    const x = Math.round(seen.left);
    const y = Math.round(seen.top);
    return { x, y, width: Math.round(seen.right) - x, height: Math.round(seen.bottom) - y };
  });
  return page.screenshot({ clip });
}

/**
 * The one comparison step: diff a region's two shots, write the three PNGs, fill its report
 * row, and collect what went over. A null ceiling reports the region without limiting it.
 */
async function measure(canvas: Page, id: string, pair: Pair, ceiling: number | null, failures: string[], note?: string) {
  if (!pair.design || !pair.app) return void failures.push(`${id}: present on one side only`);
  const result = await comparePngs(canvas, pair.design, pair.app);
  writeFileSync(join(RESULTS, `${id}-design.png`), pair.design);
  writeFileSync(join(RESULTS, `${id}-app.png`), pair.app);
  writeFileSync(join(RESULTS, `${id}-diff.png`), result.diff);
  report[id] = {
    differing: result.differing,
    total: result.width * result.height,
    percent: Number((result.ratio * 100).toFixed(3)),
    sameSize: result.sameSize,
    ceilingPercent: ceiling === null ? null : ceiling * 100,
    ...(note ? { note } : {}),
  };
  if (!result.sameSize) failures.push(`${id}: region sizes differ`);
  if (ceiling !== null && result.ratio > ceiling) failures.push(`${id}: ${(result.ratio * 100).toFixed(2)}% of pixels differ (max ${ceiling * 100}%)`);
}

for (const state of STATES.filter((state) => REVISED_COPY[state.name])) {
  test(`revised ${state.name} copy keeps the reference's layout at 375px`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    const [design, app] = [await context.newPage(), await context.newPage()];
    const layouts: Record<string, Awaited<ReturnType<typeof copyLayout>>> = {};
    for (const [side, page] of [["design", design], ["app", app]] as const) {
      await open(page, side === "design" ? `${DESIGN_URL}/${DESIGN_FILE}` : APP_URL, side === "design" ? "All tasks" : "13 tasks");
      await state.reach(page);
      // Open the unchanged reference on desktop: its list is not a mobile interaction target.
      // Resizing the same reached state still exercises the real wrapping/layout at 375px.
      // The reference keeps 24px gutters + a 1px panel border; the approved mobile app
      // uses 16px gutters and no border. 392px reference and 375px app both give 343px
      // content, so the wrapping comparison does not mistake old responsive differences
      // for new copy drift. Neither reference source nor CSS is modified.
      await page.setViewportSize({ width: side === "design" ? 392 : 375, height: 812 });
      await parkPointer(page);
      layouts[side] = await copyLayout(page, state.name, side);
      const region = page.locator(REGIONS[REVISED_COPY[state.name].region]).first();
      expect.soft(await region.evaluate((el) => el.scrollWidth <= el.clientWidth), `${side}: copy and controls fit without horizontal scrolling`).toBe(true);
      writeFileSync(join(RESULTS, `${state.name}-375-${side}.png`), await shoot(page, REGIONS[REVISED_COPY[state.name].region]));
      // The draft lasts 2.2s on both sides: say so, rather than reporting the layout of a
      // state that had already moved on while it was being measured.
      if (state.name === "generation-running") await expect.soft(page.getByText("Drafting steps", { exact: true }), `${side} left the running state before it was measured`).toBeVisible();
    }
    writeFileSync(join(RESULTS, `${state.name}-mobile-layout.json`), JSON.stringify(layouts, null, 2));
    await context.close();
    expect.soft(layouts.app, "original reference geometry/styles/controls at equal 343px content width").toEqual(layouts.design);
  });
}

/**
 * The regions with a superseded sentence are only worth their ceiling if they can still fail.
 * Supersede it in the reference, confirm the app as it ships passes the whole region at 1%,
 * then give the app an unrelated wrong surface token there: the same comparison must reject it.
 */
test("a superseded sentence still leaves the rest of its region under the 1% ceiling", async ({ browser }) => {
  const state = STATES.find((candidate) => candidate.name === "new-task")!;
  const { region } = REVISED_COPY[state.name];
  const context = await browser.newContext({ viewport: VIEWPORTS[0], deviceScaleFactor: 1 });
  const [design, app, canvas] = [await context.newPage(), await context.newPage(), await context.newPage()];
  await open(design, `${DESIGN_URL}/${DESIGN_FILE}`, "All tasks");
  await open(app, APP_URL, "13 tasks");
  for (const page of [design, app]) {
    await state.reach(page);
    await parkPointer(page);
  }
  await supersedeCopy(design, state.name);
  const reference = await shoot(design, REGIONS[region]);

  const shipped: string[] = [];
  await measure(canvas, `control-${region}-as-shipped`, { design: reference, app: await shoot(app, REGIONS[region]) }, MAX_RATIO, shipped, "control: the app as it ships, against the reference with its sentence superseded");

  // Nothing to do with the sentence: one wrong surface token, what the ceiling is there to catch.
  await app.locator(REGIONS[region]).first().evaluate((el) => ((el as HTMLElement).style.background = "#2b3348"));
  const perturbed: string[] = [];
  await measure(canvas, `control-${region}-wrong-surface`, { design: reference, app: await shoot(app, REGIONS[region]) }, MAX_RATIO, perturbed, "control: an unrelated wrong surface token must still be rejected");

  await context.close();
  expect(shipped, shipped.join("\n")).toEqual([]);
  expect(perturbed, "a wrong surface token elsewhere in the region must fail the comparison").not.toEqual([]);
});

for (const viewport of VIEWPORTS) {
  const size = `${viewport.width}x${viewport.height}`;

  for (const state of STATES) {
    test(`task panel matches the design at ${size}, ${state.name}`, async ({ browser }) => {
      const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
      const [design, app, canvas] = [await context.newPage(), await context.newPage(), await context.newPage()];
      await open(design, `${DESIGN_URL}/${DESIGN_FILE}`, "All tasks");
      await open(app, APP_URL, "13 tasks");

      // One side at a time, so a state with a clock on it (the 2.2s draft) is captured whole.
      const untouched = new Map<Region, Pair>();
      const structure = new Map<Region, Pair>();
      const revised = REVISED_COPY[state.name];
      const layouts: Record<string, Awaited<ReturnType<typeof copyLayout>>> = {};
      /** The reference as it ships, before its sentence is superseded: evidence, never a limit. */
      let originalCopy: Buffer | undefined;
      for (const [side, page] of [["design", design], ["app", app]] as const) {
        await state.reach(page);
        await parkPointer(page);
        if (revised) {
          layouts[side] = await copyLayout(page, state.name, side);
          if (side === "design") {
            originalCopy = await shoot(page, REGIONS[revised.region]);
            await supersedeCopy(page, state.name);
          }
        }
        const capture = async (into: Map<Region, Pair>, regions: Region[]) => {
          for (const region of regions) {
            const locator = page.locator(REGIONS[region]).first();
            if (region === "banner" && (await locator.count()) === 0) continue;
            into.set(region, { ...into.get(region), [side]: await shoot(page, REGIONS[region]) });
          }
        };
        await capture(untouched, state.regions);
        await page.addStyleTag({ content: HIDE_PLACEHOLDERS });
        await capture(structure, state.regions.filter((r) => PLACEHOLDER_REGIONS.includes(r)));
        if (state.name === "generation-running") await expect(page.getByText("Drafting steps", { exact: true }), `${side} left the running state before it was captured`).toBeVisible();
      }

      const failures: string[] = [];
      for (const [region, pair] of untouched) {
        const id = `${region}-${size}-${state.name}`;
        const deviation = DEVIATIONS.find((d) => d.region === region && (!d.states || d.states.includes(state.name)));
        const held = structure.get(region);
        if (originalCopy && revised?.region === region) {
          await measure(canvas, `${id}-original-copy`, { design: originalCopy, app: pair.app }, null, failures, "the reference's superseded sentence: diffed unmasked and reported, not held to a limit");
        }
        if (held) {
          await measure(canvas, id, held, deviation?.maxRatio ?? MAX_RATIO, failures, "structure: placeholder glyphs transparent on both sides");
          await measure(canvas, `${id}-with-placeholder`, pair, null, failures, "untouched: reported, not limited (placeholders are --fg-3 by ruling)");
        } else {
          await measure(canvas, id, pair, deviation?.maxRatio ?? MAX_RATIO, failures, deviation?.reason);
        }
      }

      await context.close();
      if (revised) {
        writeFileSync(join(RESULTS, `${size}-${state.name}-layout.json`), JSON.stringify(layouts, null, 2));
        expect.soft(layouts.app, `${size} ${state.name}: unchanged reference geometry, styles and controls`).toEqual(layouts.design);
      }
      expect(failures, failures.join("\n")).toEqual([]);
    });
  }

  test(`each property control, open, matches the design at ${size}`, async ({ browser }) => {
    const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
    const [design, app, canvas] = [await context.newPage(), await context.newPage(), await context.newPage()];
    await open(design, `${DESIGN_URL}/${DESIGN_FILE}`, "All tasks");
    await open(app, APP_URL, "13 tasks");
    for (const page of [design, app]) {
      await openTask(page, RICH_TASK);
      await parkPointer(page);
      // Any key press puts the browser in keyboard modality, so focus draws the ring.
      await page.keyboard.press("Shift");
    }

    const failures: string[] = [];
    for (const control of PROPERTY_CONTROLS) {
      for (const page of [design, app]) {
        await page.locator(control.selector).focus();
        // A native popup is drawn by the browser outside the page surface; opening it still
        // proves the control takes the keys, and the column is captured in its active state.
        if (control.popup) await page.keyboard.press("Alt+ArrowDown");
      }
      const shots = { design: await shoot(design, REGIONS.properties), app: await shoot(app, REGIONS.properties) };
      await measure(canvas, `properties-${size}-${control.name}-open`, shots, MAX_RATIO, failures);
      for (const page of [design, app]) {
        if (control.popup) await page.locator(control.selector).press("Alt+ArrowUp");
        await expect(page.locator("[role=dialog]"), "the panel must survive a control being opened and closed").toBeVisible();
      }
    }

    await context.close();
    expect(failures, failures.join("\n")).toEqual([]);
  });
}
