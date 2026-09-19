import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Browser, type ConsoleMessage, type Page } from "@playwright/test";
import { APP_URL } from "../playwright.config";

/**
 * Project creation has no counterpart in the design, so there is nothing to diff it against.
 * Instead this suite walks the flow in a real browser at the two design viewports and at
 * 375px and, for every state, (1) compares the regions the feature owns (the sidebar, the
 * dialog, the empty state) with the committed baselines in `__screenshots__/`, and (2) saves
 * the whole page. Run with `--update-snapshots` to re-record both after a deliberate change;
 * otherwise the full pages go to the git-ignored `visual-results/projects/`.
 */
const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1024, height: 768 },
  { width: 375, height: 812 },
];

/** The unit tests' "now": Friday 18 September 2026, 10:00. Every date on screen follows from it. */
const NOW = new Date(2026, 8, 18, 10, 0, 0);

/** As in shell.visual.ts: freeze motion and the caret, and drop the `next dev` badge. */
const FREEZE = `*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; } nextjs-portal { display: none !important; }`;

async function openApp(browser: Browser, viewport: { width: number; height: number }, options: { freeze?: boolean; reducedMotion?: boolean } = {}) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1, reducedMotion: options.reducedMotion ? "reduce" : "no-preference" });
  const page = await context.newPage();
  const problems: string[] = [];
  page.on("console", (m: ConsoleMessage) => {
    if (m.type() === "error" || m.type() === "warning") problems.push(`${m.type()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));

  await page.clock.install({ time: NOW });
  await page.goto(APP_URL);
  if (options.freeze ?? true) await page.addStyleTag({ content: FREEZE });
  await page.getByText("13 tasks", { exact: true }).waitFor();
  await page.evaluate(() => document.fonts.ready);
  return { context, page, problems };
}

const sidebar = (page: Page) => page.getByRole("complementary", { name: "Workspace" });
const control = (page: Page) => sidebar(page).getByRole("button", { name: "New project" });
const dialog = (page: Page) => page.getByRole("dialog", { name: "New project" });
const overflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

for (const viewport of VIEWPORTS) {
  test(`project creation, every state, at ${viewport.width}x${viewport.height}`, async ({ browser }, testInfo) => {
    const { context, page, problems } = await openApp(browser, viewport);
    const narrow = viewport.width < 768;
    const recording = ["all", "changed"].includes(testInfo.config.updateSnapshots);
    const pages = recording ? join(__dirname, "__screenshots__", "projects.visual.ts", "pages") : join(__dirname, "..", "visual-results", "projects");
    mkdirSync(pages, { recursive: true });

    const capture = async (state: string, region: ReturnType<Page["locator"]>) => {
      await page.mouse.move(viewport.width - 8, viewport.height - 8);
      expect(await overflow(page), `${state}: horizontal page scroll`).toBeLessThanOrEqual(0);
      await page.screenshot({ path: join(pages, `${state}-${viewport.width}.png`) });
      await expect(region).toHaveScreenshot(`${state}-${viewport.width}.png`);
    };
    const showSidebar = async () => {
      if (narrow && !(await sidebar(page).isVisible())) await page.getByRole("button", { name: "Open navigation" }).click();
    };

    // 1. Closed: the control in the Projects heading.
    await showSidebar();
    await expect(control(page)).toBeVisible();
    await capture("1-closed", sidebar(page));

    // 2. Open: name focused, key empty, a colour no project uses preselected.
    await control(page).click();
    await expect(dialog(page).getByRole("textbox", { name: "Name" })).toBeFocused();
    await expect(dialog(page).getByRole("radio", { name: "Blue" })).toBeChecked();
    await capture("2-open", dialog(page));

    // 3. Validation: a name and a key that are both taken.
    await page.keyboard.type("ballast tasks");
    await dialog(page).getByRole("textbox", { name: "Key" }).fill("bt");
    await page.keyboard.press("Enter");
    await expect(dialog(page).getByText('A project named "Ballast Tasks" already exists.')).toBeVisible();
    await expect(dialog(page).getByText("The key BT is already used by Ballast Tasks.")).toBeVisible();
    await expect(dialog(page).getByRole("textbox", { name: "Name" })).toBeFocused();
    await capture("3-validation-error", dialog(page));

    // 4. Pending: the clock is held so the in-memory directory's latency never elapses.
    await dialog(page).getByRole("textbox", { name: "Name" }).fill("Marketing");
    await dialog(page).getByRole("textbox", { name: "Key" }).fill("mkt");
    await dialog(page).getByTitle("Amber").click(); // the swatch; its radio is visually hidden
    await expect(dialog(page).getByRole("radio", { name: "Amber" })).toBeChecked();
    await page.clock.pauseAt(new Date(NOW.getTime() + 10 * 60_000));
    await page.keyboard.press("Enter");
    await expect(dialog(page).getByRole("button", { name: "Creating…" })).toBeDisabled();
    await expect(dialog(page).getByRole("button", { name: "Cancel" })).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog(page)).toBeVisible();
    await capture("4-pending", dialog(page));

    // 5. Created: listed with a zero count and selected. On a phone the drawer has closed.
    await page.clock.runFor(1000);
    await expect(dialog(page)).toBeHidden();
    await expect(page.getByTestId("crumb")).toHaveText("Marketing");
    if (narrow) await expect(sidebar(page)).toBeHidden();
    await expect(narrow ? page.getByRole("button", { name: "Open navigation" }) : control(page)).toBeFocused();

    // 6. The empty project, before the sidebar is reopened on a phone.
    const empty = page.getByRole("region", { name: "Marketing has no tasks yet" });
    await expect(empty).toBeVisible();
    await capture("6-empty-project", empty);

    await showSidebar();
    const item = sidebar(page).getByRole("button", { name: /^Marketing/ });
    await expect(item).toHaveAttribute("aria-pressed", "true");
    await expect(item).toHaveText("Marketing0");
    await capture("5-created", sidebar(page));
    if (narrow) await page.keyboard.press("Escape");

    // The first task goes into the project and the ordinary list takes over.
    await empty.getByRole("textbox", { name: "Name the first task" }).fill("Draft the launch post");
    await page.keyboard.press("Enter");
    await expect(empty).toBeHidden();
    await expect(page.getByRole("list", { name: "Tasks" }).getByText("Draft the launch post")).toBeVisible();
    await expect(page.getByText("1 task", { exact: true })).toBeVisible();

    expect(problems, "console errors or warnings").toEqual([]);
    await context.close();
  });
}

test("the whole flow works from the keyboard, and Tab never leaves the dialog", async ({ browser }) => {
  const { context, page, problems } = await openApp(browser, VIEWPORTS[0], { freeze: false });
  const focused = () => page.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? document.activeElement?.textContent ?? "");

  await control(page).focus();
  await page.keyboard.press("Enter");
  await expect(dialog(page).getByRole("textbox", { name: "Name" })).toBeFocused();
  const ring = await dialog(page).getByRole("textbox", { name: "Name" }).evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(ring).toBe("solid");

  await page.keyboard.type("Ops");
  await page.keyboard.press("Tab");
  await expect(dialog(page).getByRole("textbox", { name: "Key" })).toHaveValue("OPS");
  await page.keyboard.press("Tab");
  await expect(dialog(page).getByRole("radio", { name: "Blue" })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(dialog(page).getByRole("radio", { name: "Green" })).toBeChecked();
  await page.keyboard.press("Tab");
  expect(await focused()).toBe("Cancel");
  await page.keyboard.press("Tab");
  expect(await focused()).toBe("Create project");
  await page.keyboard.press("Tab");
  await expect(dialog(page).getByRole("textbox", { name: "Name" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  expect(await focused()).toBe("Create project");

  await page.keyboard.press("Escape");
  await expect(dialog(page)).toBeHidden();
  await expect(control(page)).toBeFocused();

  // Space opens it too; Enter in a field submits.
  await page.keyboard.press("Space");
  await page.keyboard.type("Ops");
  await page.keyboard.press("Enter");
  await expect(dialog(page).getByRole("button", { name: "Creating…" })).toBeVisible();
  await page.clock.runFor(1000);
  await expect(dialog(page)).toBeHidden();
  await expect(sidebar(page).getByRole("button", { name: /^Ops/ })).toHaveAttribute("aria-pressed", "true");
  await expect(control(page)).toBeFocused();

  // New task lands in the new project.
  await page.getByRole("button", { name: "New task" }).click();
  await page.keyboard.press("Escape");
  await expect(sidebar(page).getByRole("button", { name: /^Ops/ })).toHaveText("Ops1");

  expect(problems).toEqual([]);
  await context.close();
});

test("the backdrop dismisses the dialog, and Escape closes the dialog but not the drawer under it", async ({ browser }) => {
  const { context, page } = await openApp(browser, VIEWPORTS[2]);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await control(page).click();
  await page.keyboard.press("Escape");
  await expect(dialog(page)).toBeHidden();
  await expect(sidebar(page)).toBeVisible();
  await expect(control(page)).toBeFocused();

  await control(page).click();
  await page.mouse.click(8, 8);
  await expect(dialog(page)).toBeHidden();
  await context.close();
});

test("the dialog and the empty state are built from the design tokens only", async ({ browser }) => {
  const { context, page } = await openApp(browser, VIEWPORTS[0]);
  await control(page).click();
  await page.keyboard.press("Enter"); // show the danger tones as well
  await expect(dialog(page).getByText("Give the project a name.")).toBeVisible();

  const audit = () =>
    page.evaluate(() => {
      const root = getComputedStyle(document.documentElement);
      const probe = document.body.appendChild(document.createElement("span"));
      const resolve = (property: "color" | "fontFamily" | "borderTopLeftRadius", value: string) => {
        probe.style.setProperty(property === "color" ? "color" : property === "fontFamily" ? "font-family" : "border-top-left-radius", value);
        return getComputedStyle(probe)[property];
      };
      const colourTokens = ["bg", "panel", "card", "card-2", "fg", "fg-2", "fg-3", "line", "line-2", "acc", "acc-fg", "acc-soft", "danger", "danger-soft", "warn", "ok", "info", "backdrop"];
      const colours = new Set(["rgba(0, 0, 0, 0)", ...colourTokens.map((t) => resolve("color", `var(--${t})`))]);
      const fonts = new Set(["font", "font-h", "mono"].map((t) => resolve("fontFamily", `var(--${t})`)));
      // 50% is the design's round status dot (its "All clear" and "working" indicators).
      const radii = new Set(["0px", "50%", resolve("borderTopLeftRadius", "var(--r)"), resolve("borderTopLeftRadius", "var(--r-sm)"), resolve("borderTopLeftRadius", "calc(var(--r) - 3px)")]);
      const shadows = new Set(["none", root.getPropertyValue("--sh-1"), root.getPropertyValue("--sh-2"), root.getPropertyValue("--acc-glow")].map((s) => s.replace(/\s+/g, "")));
      probe.remove();

      const offenders: string[] = [];
      const roots = [document.querySelector('[role="dialog"]')?.parentElement, document.querySelector("main section[aria-labelledby]")].filter((el): el is HTMLElement => el instanceof HTMLElement);
      for (const el of roots.flatMap((r) => [r, ...r.querySelectorAll<HTMLElement>("*")])) {
        if (el instanceof SVGElement && el.tagName !== "svg") continue;
        const s = getComputedStyle(el);
        const where = `${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]}`;
        if (!colours.has(s.color)) offenders.push(`${where} color ${s.color}`);
        if (!colours.has(s.backgroundColor)) offenders.push(`${where} background ${s.backgroundColor}`);
        if (s.borderTopWidth !== "0px" && !colours.has(s.borderTopColor)) offenders.push(`${where} border ${s.borderTopColor}`);
        if (!fonts.has(s.fontFamily)) offenders.push(`${where} font ${s.fontFamily}`);
        if (!radii.has(s.borderTopLeftRadius)) offenders.push(`${where} radius ${s.borderTopLeftRadius}`);
        // A focus ring is a spread of a soft token; everything else must be a shadow token.
        const shadow = s.boxShadow.replace(/\s+/g, "");
        if (!shadows.has(shadow) && !/0px0px0px(1|3)px/.test(shadow)) offenders.push(`${where} shadow ${s.boxShadow}`);
      }
      return { checked: roots.length, offenders };
    });

  expect(await audit()).toEqual({ checked: 1, offenders: [] });

  await page.keyboard.type("Marketing");
  await page.keyboard.press("Enter");
  await page.clock.runFor(1000);
  await expect(page.getByRole("region", { name: "Marketing has no tasks yet" })).toBeVisible();
  expect(await audit()).toEqual({ checked: 1, offenders: [] });
  await context.close();
});

test("the dialog's entrance respects prefers-reduced-motion", async ({ browser }) => {
  const { context, page } = await openApp(browser, VIEWPORTS[0], { freeze: false, reducedMotion: true });
  await control(page).click();
  const duration = await dialog(page).evaluate((el) => getComputedStyle(el).animationDuration);
  expect(duration).toBe("1e-05s");
  await context.close();
});
