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

for (const action of ["Keep", "Clear date"] as const) {
  for (const activation of ["pointer", "keyboard"] as const) {
    test(`${action} returns date focus after ${activation} activation`, async ({ page }) => {
      await openApp(page);
      const dialog = await openTask(page, RICH_TASK);
      const input = dialog.getByLabel("Due date", { exact: true });
      const stored = await input.inputValue();
      await input.focus();
      await page.keyboard.press("Backspace");
      await expect(input).toHaveValue("");
      const button = dialog.getByRole("button", { name: action, exact: true });
      if (activation === "pointer") {
        const box = await button.boundingBox();
        expect(box).not.toBeNull();
        // One genuine pointer gesture: no locator retry if blur removes the target.
        await page.mouse.click(box!.x + box!.width / 2, box!.y + box!.height / 2);
      } else {
        // Date segments are separate native Tab stops. Bound traversal, never set focus
        // to the action programmatically or retry an activation after it disappears.
        for (let stop = 0; stop < 6; stop++) {
          if (await button.evaluate((el) => el === document.activeElement)) break;
          await page.keyboard.press("Tab");
        }
        await expect(button).toBeFocused();
        await page.keyboard.press("Enter");
      }
      await expect(input).toBeFocused();
      await expect(input).toHaveValue(action === "Keep" ? stored : "");
      await expect(dialog.getByRole("group", { name: "Remove the date?" })).toBeHidden();
    });
  }
}

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

/** Every quick action the banner can offer at once: a P0 due soon, unassigned, with no steps. */
const BANNER_ACTIONS = ["Assign to me", "Break it into steps", "Due tomorrow", "+1 week"];

for (const width of [375, 768]) {
  test(`at ${width}px every urgency quick action stays inside the panel and reachable`, async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width, height: 812 }, deviceScaleFactor: 1 });
    const page = await context.newPage();
    await openApp(page);
    const dialog = await openTask(page, BARE_TASK);
    const banner = dialog.getByTestId("detail-banner");
    // Measure with all four offered: an action that has gone is not an action that fits.
    expect(await banner.getByRole("button").allInnerTexts()).toEqual(BANNER_ACTIONS);

    // The panel is clipped, not scrolled, so an action past its edge draws nothing and takes no
    // click: measure each against the panel's own box and hit-test its centre.
    const measured = await banner.evaluate((el) =>
      [...el.querySelectorAll("button")].map((button) => {
        const box = button.getBoundingClientRect();
        const panel = button.closest("[role=dialog]")!.getBoundingClientRect();
        const under = document.elementFromPoint(Math.round(box.left + box.width / 2), Math.round(box.top + box.height / 2));
        return {
          name: button.textContent!.trim(),
          left: Math.round(box.left),
          right: Math.round(box.right),
          inside: box.left >= panel.left - 0.5 && box.right <= panel.right + 0.5,
          underPointer: under instanceof Node && button.contains(under),
        };
      }),
    );
    console.log(`banner actions at ${width}px:`, JSON.stringify(measured));
    expect.soft(measured).toEqual(BANNER_ACTIONS.map((name) => expect.objectContaining({ name, inside: true, underPointer: true })));

    // Keyboard: the browser scrolls a focused control into view, which on a clipped row drags
    // the panel sideways and takes the header, the title and "Mark complete" off its left edge.
    const anchors = () =>
      dialog.evaluate((el) => {
        const left = (node: Element | null | undefined) => (node ? Math.round(node.getBoundingClientRect().left) : NaN);
        return {
          panelScrollLeft: el.scrollLeft,
          header: left(el.querySelector("[data-testid=detail-project]")),
          title: left(el.querySelector("[aria-label='Task name']")),
          complete: left([...el.querySelectorAll("button")].find((b) => b.textContent!.trim() === "Mark complete")),
        };
      });
    const resting = await anchors();
    const reached: string[] = [];
    const displaced: unknown[] = [];
    await dialog.evaluate((el: HTMLElement) => el.focus());
    for (let stop = 0; stop < 12 && reached.length < BANNER_ACTIONS.length; stop++) {
      await page.keyboard.press("Tab");
      const focused = await page.evaluate(() => document.activeElement?.textContent?.trim() ?? "");
      if (!BANNER_ACTIONS.includes(focused)) continue;
      reached.push(focused);
      const shifted = await anchors();
      if (JSON.stringify(shifted) !== JSON.stringify(resting)) displaced.push({ focused, resting, shifted });
    }
    expect.soft(reached, "every action is a Tab stop inside the panel").toEqual(BANNER_ACTIONS);
    expect.soft(displaced, "focusing an action must not move the panel sideways").toEqual([]);

    await page.screenshot({ path: join(RESULTS, `behaviour-${width}-banner-actions.png`) });

    // One real pointer gesture on the furthest action, from a panel nobody has scrolled: it
    // reschedules, so the banner drops to the one thing still worth doing. Activating it removes
    // the other three, so it happens on a fresh panel, after they have all been measured.
    await page.reload();
    await page.getByText("13 tasks", { exact: true }).waitFor();
    const reopened = await openTask(page, BARE_TASK);
    const again = reopened.getByTestId("detail-banner");
    await expect(again.getByRole("button")).toHaveText(BANNER_ACTIONS);
    expect(await reopened.evaluate((el) => el.scrollLeft), "the panel sits at its left edge").toBe(0);
    const box = (await again.getByRole("button", { name: "+1 week", exact: true }).boundingBox())!;
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await expect(again.getByRole("button")).toHaveText(["Assign to me"]);
    await context.close();
  });
}

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

test("a due date being retyped reports empty to the app, and still ends on the finished date", async ({ page }) => {
  await openApp(page);
  const dialog = await openTask(page, RICH_TASK);
  const properties = dialog.getByRole("complementary", { name: "Properties" });
  const date = properties.getByLabel("Due date");
  const stored = await date.inputValue();
  expect(stored, "this task starts with a due date").not.toBe("");

  // Every value the control reports as the user works, so an intermediate empty is visible.
  await date.evaluate((el) => {
    (window as unknown as { seen: string[] }).seen = [];
    el.addEventListener("input", () => (window as unknown as { seen: string[] }).seen.push((el as HTMLInputElement).value));
  });

  // Clearing one segment of a date that already has a value: Chrome reports the whole control
  // as empty until the date is complete again. That empty is not a date the task can hold.
  await date.click();
  await page.keyboard.press("Backspace");
  await expect(date).toHaveValue("");
  await expect(properties.getByRole("group", { name: "Remove the date?" })).toBeVisible();

  await date.fill("2027-12-24");
  await expect(properties.getByRole("group", { name: "Remove the date?" })).toBeHidden();
  const seen = await page.evaluate(() => (window as unknown as { seen: string[] }).seen);
  expect(seen, "Chrome reports an empty value while the date is being retyped").toContain("");

  await expect(date).toHaveValue("2027-12-24");
  await expect(dialog.getByTestId("save-state")).toHaveText(/^saved · /);
  await dialog.getByRole("button", { name: "Close task" }).click();

  const reopened = await openTask(page, RICH_TASK);
  await expect(reopened.getByRole("complementary", { name: "Properties" }).getByLabel("Due date")).toHaveValue("2027-12-24");
});

test("emptying a due date and leaving puts it back; only Clear date removes it", async ({ page }) => {
  await openApp(page);
  const dialog = await openTask(page, RICH_TASK);
  const properties = dialog.getByRole("complementary", { name: "Properties" });
  const date = properties.getByLabel("Due date");
  const stored = await date.inputValue();
  expect(stored).not.toBe("");

  await date.click();
  await page.keyboard.press("Backspace");
  await expect(date).toHaveValue("");
  await expect(properties.getByRole("group", { name: "Remove the date?" })).toBeVisible();

  // Escape is a cancel gesture: it closes the panel and must not remove the date.
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
  const reopened = await openTask(page, RICH_TASK);
  const back = reopened.getByRole("complementary", { name: "Properties" }).getByLabel("Due date");
  await expect(back).toHaveValue(stored);

  await back.click();
  await page.keyboard.press("Backspace");
  const prompt = reopened.getByRole("complementary", { name: "Properties" }).getByRole("group", { name: "Remove the date?" });
  await prompt.getByRole("button", { name: "Clear date" }).click();
  await expect(prompt).toBeHidden();
  await expect(back).toHaveValue("");

  await reopened.getByRole("button", { name: "Close task" }).click();
  const again = await openTask(page, RICH_TASK);
  await expect(again.getByRole("complementary", { name: "Properties" }).getByLabel("Due date")).toHaveValue("");
});

for (const gesture of ["blur", "Escape", "Close", "Back", "backdrop", "switch"] as const) {
  test(`segmented due-date edits do not clear on ${gesture}`, async ({ page }) => {
    await page.setViewportSize({ width: gesture === "Back" ? 375 : 1440, height: 900 });
    await openApp(page);
    const dialog = await openTask(page, RICH_TASK);
    const date = dialog.getByLabel("Due date", { exact: true });
    const stored = await date.inputValue();
    await date.click();
    await page.keyboard.press("Backspace");
    await expect(date).toHaveValue("");

    if (gesture === "blur") {
      await dialog.getByRole("spinbutton", { name: "Importance" }).focus();
      await expect(date).toHaveValue(stored);
      await dialog.getByRole("button", { name: "Close task" }).click();
    } else if (gesture === "Escape") {
      await page.keyboard.press("Escape");
    } else if (gesture === "backdrop") {
      await page.getByTestId("detail-backdrop").click({ position: { x: 10, y: 100 } });
    } else {
      await dialog.getByRole("button", { name: gesture === "Back" ? "Back to tasks" : "Close task" }).click();
    }
    await expect(page.getByRole("dialog")).toBeHidden();
    if (gesture === "switch") {
      await openTask(page, BARE_TASK);
      await page.keyboard.press("Escape");
    }
    const reopened = await openTask(page, RICH_TASK);
    await expect(reopened.getByLabel("Due date", { exact: true })).toHaveValue(stored);
    await expect(reopened).toBeFocused();
    await page.screenshot({ path: join(RESULTS, `date-exit-${gesture.toLowerCase()}.png`) });
  });
}

test("date Clear and Keep do not leave keyboard focus behind the panel", async ({ page }) => {
  await openApp(page);
  const dialog = await openTask(page, RICH_TASK);
  const date = dialog.getByLabel("Due date", { exact: true });
  const stored = await date.inputValue();
  await date.click();
  await page.keyboard.press("Backspace");
  await dialog.getByRole("button", { name: "Keep", exact: true }).click();
  await expect(date).toBeFocused();
  await expect(date).toHaveValue(stored);
  await page.keyboard.press("Backspace");
  await dialog.getByRole("button", { name: "Clear date", exact: true }).click();
  await expect(date).toBeFocused();
  await expect(date).toHaveValue("");
  await page.keyboard.press("Tab");
  expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
});

test("the browser's own Tab continuation is left alone after a control goes under the reader", async ({ page }) => {
  await openApp(page);
  const dialog = await openTask(page, RICH_TASK);
  const landed = () =>
    page.evaluate(() => {
      const el = document.activeElement;
      return el?.getAttribute("aria-label") ?? el?.textContent?.trim() ?? el?.tagName ?? "";
    });
  const dropped = () => page.waitForFunction(() => document.activeElement === document.body);

  // A control removed while focused leaves the focus on the document, but the browser keeps the
  // navigation starting point where it stood, so the reader carries on from there.
  const first = "Remove step: Task entity and TaskStatus enum in domain";
  await dialog.getByRole("button", { name: first }).focus();
  await page.keyboard.press("Enter");
  await expect(dialog.getByRole("button", { name: first })).toBeHidden();
  await dropped();
  await page.keyboard.press("Tab");
  expect(await landed()).toBe("TaskRepository port + in-memory fake, contract suite");
  await page.keyboard.press("Shift+Tab");
  expect(await landed()).toBe("Generate steps");

  // Disabling a focused control drops the focus the same way, by the next task.
  const generate = dialog.getByRole("button", { name: "Generate steps" });
  await generate.focus();
  await page.keyboard.press("Enter");
  await expect(generate).toBeDisabled();
  await dropped();
  await page.keyboard.press("Tab");
  expect(await landed()).toBe("TaskRepository port + in-memory fake, contract suite");
});

test("a continuation that walks off the front of the panel is wrapped back to its last stop", async ({ page }) => {
  await openApp(page);
  const dialog = await openTask(page, RICH_TASK);

  // The panel's first stop goes away under the reader, so walking backwards from where it stood
  // reaches the list behind the panel: the one landing outside that the modal has to take back.
  const close = dialog.getByRole("button", { name: "Close task" });
  await close.focus();
  await close.evaluate((el: HTMLButtonElement) => (el.disabled = true));
  await page.waitForFunction(() => document.activeElement === document.body);
  await page.keyboard.press("Shift+Tab");

  expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  expect(await page.evaluate(() => document.activeElement?.textContent?.trim())).toBe("Delete");
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

  // Attachments: a keyboard-opened native picker, a rejected file, and real saved metadata.
  const attachments = dialog.getByRole("region", { name: "Attachments" });
  await attachments.getByRole("button", { name: "Attach file" }).focus();
  const picker = page.waitForEvent("filechooser");
  await page.keyboard.press("Enter");
  await (await picker).setFiles({ name: "unsafe.html", mimeType: "text/html", buffer: Buffer.from("<html></html>") });
  await expect(attachments.getByRole("alert")).toHaveText(/Choose a PDF/);
  await attachments.getByLabel("Choose a file to attach").setInputFiles({ name: "exercise.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.7") });
  await expect(attachments.getByText("PDF · 1 KB")).toBeVisible();
  await expect(attachments.getByRole("alert")).toBeHidden();
  await attachments.getByRole("button", { name: "Add link" }).click();
  await attachments.getByRole("textbox", { name: "Link URL" }).fill("not a link");
  await attachments.getByRole("button", { name: "Add", exact: true }).click();
  await expect(attachments.getByRole("alert")).toBeVisible();
  await attachments.getByRole("textbox", { name: "Link URL" }).fill("https://datatracker.ietf.org/doc/html/rfc7519");
  await attachments.getByRole("textbox", { name: "Title (optional)" }).fill("RFC 7519");
  await page.keyboard.press("Enter");
  await expect(attachments.getByRole("link", { name: /RFC 7519/ })).toHaveAttribute("href", "https://datatracker.ietf.org/doc/html/rfc7519");

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
