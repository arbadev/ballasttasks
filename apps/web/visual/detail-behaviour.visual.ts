import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";
import { APP_URL } from "../playwright.config";

const RESULTS = join(__dirname, "..", "visual-results", "detail");

// Needs no design snapshot: these check the panel alone, in a real browser.
test.beforeAll(() => mkdirSync(RESULTS, { recursive: true }));

const BARE_TASK = "JWT authentication";
const RICH_TASK = "Task CRUD endpoints with pagination and filters";

async function openApp(page: Page) {
  await page.goto(APP_URL);
  await page.getByText("13 tasks", { exact: true }).waitFor();
}
async function openTask(page: Page, title: string) {
  await page.getByText(title, { exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: title });
  await expect(dialog).toBeVisible();
  await dialog.evaluate((el) => Promise.all(el.getAnimations().map((a) => a.finished)));
  return dialog;
}
const overflow = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

test("at 375px the panel is full-screen, with a back control instead of the corner close", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 375, height: 812 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  await openApp(page);
  const dialog = await openTask(page, RICH_TASK);

  expect(await dialog.boundingBox()).toMatchObject({ x: 0, y: 0, width: 375, height: 812 });
  await expect(dialog.getByRole("button", { name: "Back to tasks" })).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Close task" })).toBeHidden();

  // The properties stack under the content at full width rather than squeezing beside it.
  const properties = await dialog.getByRole("complementary", { name: "Properties" }).boundingBox();
  expect(properties).toMatchObject({ x: 0, width: 375 });
  await page.screenshot({ path: join(RESULTS, "behaviour-375-rich-task.png") });

  await dialog.getByRole("button", { name: "Back to tasks" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await context.close();
});

for (const width of [375, 768, 1024, 1440]) {
  test(`the panel never scrolls the page sideways at ${width}px, with every expanding surface open`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height: 812 }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    await openApp(page);
    const dialog = await openTask(page, BARE_TASK);
    // Sideways overflow of anything that clips or scrolls: the panel, its body, the boxes in it.
    // Ellipsis is deliberate truncation (attachment names), so it is not counted.
    const inside = () =>
      dialog.evaluate((el) =>
        Math.max(
          0,
          ...[el, ...el.querySelectorAll("*")]
            .filter((n) => {
              const style = getComputedStyle(n);
              return style.overflowX !== "visible" && style.textOverflow !== "ellipsis";
            })
            .map((n) => n.scrollWidth - n.clientWidth),
        ),
      );

    expect(await overflow(page), "open").toBeLessThanOrEqual(0);
    await dialog.getByRole("button", { name: "Add link" }).click();
    await dialog.getByRole("button", { name: "Generate steps" }).click();
    await expect(dialog.getByRole("group", { name: "Proposed steps" })).toBeVisible({ timeout: 10_000 });
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(dialog.getByRole("button", { name: "Delete task" })).toBeFocused();
    await dialog.evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).filter((a) => a.effect?.getComputedTiming().iterations !== Infinity).map((a) => a.finished)));

    expect(await overflow(page), "link form, proposal and delete prompt open").toBeLessThanOrEqual(0);
    expect(await inside(), "nothing inside the panel is clipped or scrolls sideways").toBeLessThanOrEqual(1);
    await page.screenshot({ path: join(RESULTS, `behaviour-${width}-everything-open.png`), fullPage: false });
    await context.close();
  });
}

test("keyboard: Enter opens from the opener, Tab stays inside, Escape peels back one layer at a time, focus returns", async ({ page }) => {
  await openApp(page);
  const newTask = page.getByRole("button", { name: "New task" });
  await newTask.focus();
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const title = dialog.getByRole("textbox", { name: "Task name" });
  await expect(title).toBeFocused();
  expect(await title.evaluate((el: HTMLInputElement) => el.value.slice(el.selectionStart ?? 0, el.selectionEnd ?? 0))).toBe("Untitled task");

  // Typing replaces the selected name; the panel takes the new name once it is saved.
  await page.keyboard.type("Pick the token lifetime");
  await expect(page.getByRole("dialog", { name: "Pick the token lifetime" })).toBeVisible();

  // Forty tabs in either direction never leave the panel.
  for (const key of ["Tab", "Shift+Tab"]) {
    for (let i = 0; i < 40; i++) {
      await page.keyboard.press(key);
      expect(await dialog.evaluate((el) => el.contains(document.activeElement)), `${key} #${i + 1}`).toBe(true);
    }
  }

  // A focused control draws the design's ring.
  const complete = dialog.getByRole("button", { name: "Mark complete" });
  await complete.focus();
  expect(await complete.evaluate((el) => getComputedStyle(el).outlineStyle)).toBe("solid");

  // Escape closes the link form first, then the panel.
  const addLink = dialog.getByRole("button", { name: "Add link" });
  await addLink.focus();
  await page.keyboard.press("Enter");
  await expect(dialog.getByRole("textbox", { name: "Link URL" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog.getByRole("form", { name: "Add a link" })).toBeHidden();
  await expect(dialog).toBeVisible();
  await expect(addLink).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(newTask).toBeFocused();
});

test("placeholders are set in --fg-3 and keep at least 4.5:1 against their background", async ({ page }) => {
  await openApp(page);
  const dialog = await openTask(page, BARE_TASK);
  await dialog.getByRole("button", { name: "Add link" }).click();

  const measured = await dialog.evaluate((el) => {
    const channels = (color: string) => (color.match(/[\d.]+/g) ?? []).map(Number);
    const luminance = ([r, g, b]: number[]) => {
      const lin = (c: number) => (c / 255 <= 0.03928 ? c / 255 / 12.92 : ((c / 255 + 0.055) / 1.055) ** 2.4);
      return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
    };
    /** The first opaque background behind the field: a transparent input shows its ancestor. */
    const backdropOf = (node: Element): number[] => {
      for (let n: Element | null = node; n; n = n.parentElement) {
        const c = channels(getComputedStyle(n).backgroundColor);
        if (c.length === 3 || c[3] === 1) return c;
      }
      return [0, 0, 0];
    };
    const probe = document.createElement("span");
    probe.style.color = "var(--fg-3)";
    el.append(probe);
    const token = getComputedStyle(probe).color;
    probe.remove();

    return [...el.querySelectorAll<HTMLElement>("input[placeholder], textarea[placeholder]")].map((field) => {
      const color = getComputedStyle(field, "::placeholder").color;
      const [a, b] = [luminance(channels(color)), luminance(backdropOf(field))];
      return { field: field.getAttribute("placeholder"), color, token, contrast: Number(((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)).toFixed(2)) };
    });
  });

  expect(measured.map((m) => m.field)).toEqual(["Task name", "What does done look like?", "Add a step and press Enter", "https://", "Write a comment — Enter to post"]);
  for (const m of measured) {
    expect(m.color, `${m.field}: colour`).toBe(m.token);
    expect(m.contrast, `${m.field}: contrast ${m.contrast}:1`).toBeGreaterThanOrEqual(4.5);
  }
  console.log("placeholder contrast:", JSON.stringify(measured));
});

test("prefers-reduced-motion stills the panel's entrance and its loops", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  await openApp(page);
  await page.getByText(BARE_TASK, { exact: true }).first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Generate steps" }).click();
  await expect(dialog.getByRole("status", { name: "Drafting steps" })).toBeVisible();

  const longest = await dialog.evaluate((el) =>
    Math.max(0, ...[el, ...el.querySelectorAll("*")].flatMap((n) => getComputedStyle(n).animationDuration.split(",").map((d) => parseFloat(d) * (d.trim().endsWith("ms") ? 1 : 1000)))),
  );
  expect(longest, "longest animation in the panel, in ms").toBeLessThan(1);
  await context.close();
});

test("no console errors or warnings across the panel's states", async ({ page }) => {
  const problems: string[] = [];
  const record = (m: ConsoleMessage) => {
    if (m.type() === "error" || m.type() === "warning") problems.push(`${m.type()}: ${m.text()}`);
  };
  page.on("console", record);
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));

  await openApp(page);
  const dialog = await openTask(page, BARE_TASK);

  // Fields: text autosave, every property control.
  await dialog.getByRole("textbox", { name: "Task name" }).fill("JWT authentication, reviewed");
  await dialog.getByRole("textbox", { name: "Description" }).fill("Access and refresh tokens.");
  await dialog.getByRole("textbox", { name: "Description" }).blur();
  const properties = dialog.getByRole("complementary", { name: "Properties" });
  await properties.getByRole("combobox", { name: "Status" }).selectOption("progress");
  await properties.getByRole("combobox", { name: "Assignee" }).selectOption("lm");
  await properties.getByLabel("Due date").fill("2026-12-24");
  await properties.getByRole("combobox", { name: "Priority" }).selectOption("1");
  await properties.getByRole("spinbutton", { name: "Importance" }).fill("250");
  await properties.getByRole("spinbutton", { name: "Importance" }).blur();
  await expect(properties.getByRole("spinbutton", { name: "Importance" })).toHaveValue("100");
  await properties.getByRole("combobox", { name: "Project" }).selectOption("inbox");
  await expect(dialog.getByTestId("save-state")).toHaveText(/^saved · /);

  // Steps: add, toggle, remove, then the whole generation loop.
  const steps = dialog.getByRole("region", { name: "Steps" });
  await steps.getByRole("textbox", { name: "Add a step" }).fill("Pick the token lifetime");
  await page.keyboard.press("Enter");
  await steps.getByRole("checkbox", { name: "Pick the token lifetime" }).click();
  await expect(steps.getByText("1/1")).toBeVisible();
  await steps.getByRole("button", { name: "Remove step: Pick the token lifetime" }).click();
  await steps.getByRole("button", { name: "Generate steps" }).click();
  await expect(steps.getByRole("status", { name: "Drafting steps" })).toBeVisible();

  // The generation belongs to its task: leave, look at another task, come back.
  await page.keyboard.press("Escape");
  await openTask(page, "Seed data and demo credentials");
  await expect(page.getByRole("status", { name: "Drafting steps" })).toBeHidden();
  await page.keyboard.press("Escape");
  await page.getByText("JWT authentication, reviewed", { exact: true }).first().click();
  const proposal = dialog.getByRole("group", { name: "Proposed steps" });
  await expect(proposal).toBeVisible({ timeout: 10_000 });
  await proposal.getByRole("button", { name: /^Remove proposed step:/ }).first().click();
  await proposal.getByRole("button", { name: "Regenerate" }).click();
  await expect(proposal).toBeVisible({ timeout: 10_000 });
  await proposal.getByRole("button", { name: "Discard" }).click();
  await expect(dialog.getByText("Draft discarded by Andres")).toBeVisible();
  await steps.getByRole("button", { name: "Generate steps" }).click();
  await expect(proposal).toBeVisible({ timeout: 10_000 });
  await proposal.getByRole("button", { name: /^Add \d+ steps$/ }).click();
  await expect(steps.getByText("0/6")).toBeVisible();

  // Attachments: the unavailable upload, a rejected and an accepted link.
  const attachments = dialog.getByRole("region", { name: "Attachments" });
  await attachments.getByRole("button", { name: "Attach file" }).click({ force: true });
  await attachments.getByRole("button", { name: "Add link" }).click();
  await attachments.getByRole("textbox", { name: "Link URL" }).fill("not a link");
  await attachments.getByRole("button", { name: "Add", exact: true }).click();
  await expect(attachments.getByRole("alert")).toBeVisible();
  await attachments.getByRole("textbox", { name: "Link URL" }).fill("https://datatracker.ietf.org/doc/html/rfc7519");
  await attachments.getByRole("textbox", { name: "Title (optional)" }).fill("RFC 7519");
  await page.keyboard.press("Enter");
  await expect(attachments.getByText("RFC 7519")).toBeVisible();

  // Activity, completion, deletion.
  const activity = dialog.getByRole("region", { name: "Activity" });
  await activity.getByRole("textbox", { name: "Write a comment" }).fill("Line one");
  await page.keyboard.press("Shift+Enter");
  await page.keyboard.type("line two");
  await page.keyboard.press("Enter");
  await expect(activity.getByText("Line one")).toBeVisible();
  await dialog.getByRole("button", { name: "Mark complete" }).click();
  await expect(dialog.getByRole("button", { name: "Reopen" })).toBeVisible();
  await dialog.getByRole("button", { name: "Delete", exact: true }).click();
  await dialog.getByRole("button", { name: "Delete task" }).click();
  await expect(page.getByRole("dialog")).toBeHidden();

  expect(problems).toEqual([]);
});
