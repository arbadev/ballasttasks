import { expect, test, type Browser, type Locator, type Page } from "@playwright/test";
import { DESKTOP_VIEWPORTS, SKIP_WITHOUT_DESIGN, compareShots, openApp, openDesign, writeReport, type Measurement } from "./harness";

/** Where the board's parts are, in the design's markup and in the app's. */
interface Side {
  page: Page;
  board: Locator;
  columns: Locator;
  cards: Locator;
}

/** By the header that opens the column: the app's cards also name their neighbouring statuses. */
const column = (side: Side, name: string) => side.columns.filter({ hasText: new RegExp(`^\\s*${name}`) }).first();
const card = (side: Side, title: string) => side.cards.filter({ hasText: title }).first();

const DEFAULT_CARD = "Generate-steps job";
const DRAGGED_CARD = "Write PRD.md";

/** Parks the pointer in the sidebar, where nothing on the board reacts to it. */
const park = (page: Page) => page.mouse.move(120, 600);

/**
 * The detail opens over the board on both sides. Hiding whatever covers the whole viewport
 * shows the selected card itself; the same rule runs on the design and on the app.
 */
async function hideOverlays(page: Page) {
  await page.evaluate(() => {
    for (const el of document.querySelectorAll<HTMLElement>("body *")) {
      if (getComputedStyle(el).position !== "fixed") continue;
      const box = el.getBoundingClientRect();
      if (box.width >= innerWidth && box.height >= innerHeight) el.style.visibility = "hidden";
    }
  });
}

/** Picks a card up with the real mouse and holds it over a column, without letting go. */
async function holdOver(side: Side, title: string, target: string) {
  const from = await card(side, title).boundingBox();
  const to = await column(side, target).boundingBox();
  if (!from || !to) throw new Error("the card or the column is not on the page");
  const { mouse } = side.page;
  await mouse.move(from.x + from.width / 2, from.y + from.height / 2);
  await mouse.down();
  // Below the column's cards, so no card is under the pointer.
  await mouse.move(to.x + to.width / 2, to.y + to.height - 30, { steps: 12 });
  await mouse.move(to.x + to.width / 2 + 2, to.y + to.height - 28, { steps: 2 });
  await side.page.waitForTimeout(150);
}

interface BoardState {
  name: string;
  reach(side: Side): Promise<void>;
  regions: { name: string; locate(side: Side): Locator }[];
}

const STATES: BoardState[] = [
  {
    name: "default",
    reach: async ({ page }) => park(page),
    regions: [
      { name: "board", locate: (s) => s.board },
      { name: "column", locate: (s) => column(s, "In Progress") },
      { name: "card", locate: (s) => card(s, DEFAULT_CARD) },
    ],
  },
  {
    name: "hover",
    reach: async (s) => card(s, DEFAULT_CARD).hover(),
    regions: [{ name: "card-hovered", locate: (s) => card(s, DEFAULT_CARD) }],
  },
  {
    name: "selected",
    reach: async (s) => {
      await card(s, DEFAULT_CARD).click();
      await hideOverlays(s.page);
      await park(s.page);
    },
    regions: [{ name: "card-selected", locate: (s) => card(s, DEFAULT_CARD) }],
  },
  {
    name: "dragging",
    reach: (s) => holdOver(s, DRAGGED_CARD, "Testing"),
    regions: [
      { name: "column-drop-target", locate: (s) => column(s, "Testing") },
      { name: "card-dragged", locate: (s) => card(s, DRAGGED_CARD) },
    ],
  },
  {
    name: "empty",
    reach: async ({ page }) => {
      await page.getByPlaceholder("Search tasks").fill("docker");
      await park(page);
    },
    regions: [{ name: "column-empty", locate: (s) => column(s, "To Do") }],
  },
];

async function openBoard(browser: Browser, viewport: { width: number; height: number }) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  const [designPage, appPage, canvas] = [await context.newPage(), await context.newPage(), await context.newPage()];
  await openDesign(designPage);
  await openApp(appPage);

  const sides: Side[] = [
    { page: designPage, board: designPage.locator("main div:has(> section)"), columns: designPage.locator("main section"), cards: designPage.locator("main article") },
    { page: appPage, board: appPage.locator("section[aria-label=Board] div:has(> section)"), columns: appPage.locator("section[aria-label=Board] section"), cards: appPage.locator("section[aria-label=Board] article") },
  ];
  for (const side of sides) {
    await side.page.bringToFront();
    await side.page.getByText("Board", { exact: true }).click();
    await side.page.getByText("Add a task").first().waitFor();
  }
  return { context, canvas, design: sides[0], app: sides[1] };
}

test.skip(!process.env.BT_DESIGN_DIR, SKIP_WITHOUT_DESIGN);

const report: Record<string, Measurement> = {};
test.afterAll(() => writeReport("board-report.json", report));

for (const viewport of DESKTOP_VIEWPORTS) {
  for (const state of STATES) {
    test(`board matches the design at ${viewport.width}x${viewport.height}, ${state.name}`, async ({ browser }) => {
      const { context, canvas, design, app } = await openBoard(browser, viewport);

      // A held drag belongs to the page in front, so each side is reached and captured in turn.
      const capture = async (side: Side) => {
        await side.page.bringToFront();
        await state.reach(side);
        const shots = new Map<string, Buffer>();
        for (const region of state.regions) shots.set(region.name, await region.locate(side).screenshot());
        await side.page.mouse.up();
        return shots;
      };
      const designShots = await capture(design);
      const appShots = await capture(app);

      const failures: string[] = [];
      for (const region of state.regions) {
        const id = `board-${region.name}-${viewport.width}x${viewport.height}`;
        failures.push(...(await compareShots(canvas, id, designShots.get(region.name)!, appShots.get(region.name)!, report)));
      }

      await context.close();
      expect(failures, failures.join("\n")).toEqual([]);
    });
  }
}
