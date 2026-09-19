import { expect, test, type Locator, type Page } from "@playwright/test";
import { APP_URL, DESIGN_URL } from "../playwright.config";

const DESIGN_FILE = "Ballast%20Tasks%20v2.dc.html";

/**
 * The skin's custom properties, read from the root element of both pages. The three font
 * stacks are left out on purpose: next/font self-hosts the families under generated names,
 * so they are compared as rendered families below instead.
 */
const SKIN = [
  "--scheme", "--bg", "--panel", "--card", "--card-2", "--fg", "--fg-2", "--fg-3", "--line", "--line-2",
  "--acc", "--acc-fg", "--acc-soft", "--acc-glow", "--danger", "--danger-soft", "--warn", "--warn-soft",
  "--ok", "--ok-soft", "--info", "--info-soft", "--backdrop", "--r", "--r-sm", "--r-av",
  "--sh-1", "--sh-2", "--sh-3", "--hw", "--hls", "--hsize", "--ease",
];

const CORNERS = ["borderTopLeftRadius", "borderTopRightRadius", "borderBottomRightRadius", "borderBottomLeftRadius"] as const;

/** What a token resolves to on a rendered element: colours, the four radii, shadow and type. */
const RESOLVED = ["color", "backgroundColor", ...CORNERS, "boxShadow", "fontSize", "fontWeight", "letterSpacing"] as const;

/** Shell elements both pages expose the same way. */
const ELEMENTS: { name: string; find: (page: Page) => Locator; except?: string[] }[] = [
  // The design sets its 14px on the app's root element, the app on the body itself.
  { name: "page body", find: (page) => page.locator("body"), except: ["fontSize"] },
  { name: "sidebar", find: (page) => page.locator("aside").first() },
  { name: "logo mark", find: (page) => page.locator("aside span").first() },
  { name: "nav button", find: (page) => page.getByRole("button", { name: /^My tasks/ }) },
  { name: "page heading", find: (page) => page.getByRole("heading", { level: 1 }) },
  { name: "primary button", find: (page) => page.getByRole("button", { name: "New task" }) },
  { name: "search box", find: (page) => page.getByPlaceholder("Search tasks") },
  { name: "signal chip", find: (page) => page.getByRole("button", { name: /need an owner/ }) },
];

const FREEZE = `*, *::before, *::after { animation: none !important; transition: none !important; }`;

async function open(page: Page, url: string, ready: string) {
  await page.goto(url);
  await page.addStyleTag({ content: FREEZE });
  await page.getByText(ready, { exact: true }).first().waitFor();
  await page.evaluate(() => document.fonts.ready);
  await page.mouse.move(700, 600);
}

const resolved = (locator: Locator, except: string[] = []) =>
  locator.evaluate((el, names) => {
    const style = getComputedStyle(el);
    // The family the text is set in, without next/font's generated suffixes and fallbacks.
    const family = style.fontFamily.split(",")[0].replace(/["']/g, "").replace(/^__|_[0-9a-f]{6}$|_Fallback.*$/gi, "").replace(/_/g, " ").trim();
    // Only the sides that draw a border: the colour of a 0px side is never seen.
    const borders = (["Top", "Right", "Bottom", "Left"] as const).map((side) =>
      style[`border${side}Width`] === "0px" ? "none" : `${style[`border${side}Width`]} ${style[`border${side}Style`]} ${style[`border${side}Color`]}`,
    );
    // Tailwind composes box-shadow from layers; the empty ones draw nothing.
    const boxShadow = style.boxShadow.replace(/rgba\(0, 0, 0, 0\) 0px 0px 0px 0px(, )?/g, "").replace(/, $/, "") || "none";
    return { ...Object.fromEntries(names.map((name) => [name, style[name]])), boxShadow, borders, fontFamily: family };
  }, RESOLVED.filter((name) => !except.includes(name)));

const corners = (locator: Locator) =>
  locator.evaluate((el, names) => names.map((name) => getComputedStyle(el)[name]), CORNERS);

// Needs no design snapshot. Overriding the skin proves the utility reads the token on every
// corner, instead of matching a built-in value that happens to be equal.
test("the radius utilities follow the skin's radii on all four corners", async ({ page }) => {
  await open(page, APP_URL, "13 tasks");
  await page.evaluate(() => {
    document.documentElement.style.setProperty("--r", "7px");
    document.documentElement.style.setProperty("--r-sm", "5px");
  });

  expect(await corners(page.getByRole("button", { name: "New task" })), "rounded-bt").toEqual(["7px", "7px", "7px", "7px"]);
  expect(await corners(page.getByPlaceholder("Search tasks")), "rounded-bt").toEqual(["7px", "7px", "7px", "7px"]);
  expect(await corners(page.getByRole("button", { name: /^My tasks/ })), "rounded-bt-sm").toEqual(["5px", "5px", "5px", "5px"]);
  expect(await corners(page.locator("aside span").first()), "rounded-bt-sm").toEqual(["5px", "5px", "5px", "5px"]);
});

test("the search placeholder is set in the muted text token, not the browser default", async ({ page }) => {
  // The browser default (#757575) is 3.4:1 on the card surface and fails WCAG AA;
  // --fg-3 is 4.65:1 and is what the design uses for the icon beside it.
  await open(page, APP_URL, "13 tasks");
  const colours = await page.getByPlaceholder("Search tasks").evaluate((input) => {
    const probe = document.body.appendChild(document.createElement("span"));
    probe.style.color = "var(--fg-3)";
    const token = getComputedStyle(probe).color;
    probe.remove();
    return { placeholder: getComputedStyle(input, "::placeholder").color, opacity: getComputedStyle(input, "::placeholder").opacity, token };
  });
  expect(colours.placeholder).toBe(colours.token);
  expect(colours.opacity).toBe("1");
});

test.describe("against the design snapshot", () => {
  test.skip(!process.env.BT_DESIGN_DIR, "Set BT_DESIGN_DIR to the folder holding the design snapshot (Ballast Tasks v2.dc.html + support.js); it is kept out of the repository.");

  test("the root element carries the design's skin, value for value", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    const design = await context.newPage();
    const app = await context.newPage();
    await open(design, `${DESIGN_URL}/${DESIGN_FILE}`, "All tasks");
    await open(app, APP_URL, "13 tasks");

    // Read back through a probe element, so both sides are normalised by the browser
    // (".07" and "0.07", or "#15171a" and "rgb(21, 23, 26)", compare equal). What no probed
    // property accepts is compared as text, with the number and comma spelling evened out.
    const skin = (page: Page) =>
      page.evaluate((names) => {
        const root = getComputedStyle(document.documentElement);
        const probe = document.body.appendChild(document.createElement("span"));
        const read = (name: string) => {
          const raw = root.getPropertyValue(name).trim();
          for (const property of ["color", "boxShadow", "borderRadius"] as const) {
            probe.style[property] = "";
            probe.style[property] = raw;
            if (probe.style[property]) return getComputedStyle(probe)[property];
          }
          return raw.replace(/(^|[^\d])\./g, "$10.").replace(/\s*,\s*/g, ", ");
        };
        const values = Object.fromEntries(names.map((name) => [name, read(name)]));
        probe.remove();
        return values;
      }, SKIN);

    const expected = await skin(design);
    expect(Object.values(expected).filter((value) => value === ""), "the design defines every skin property").toEqual([]);
    expect(await skin(app)).toEqual(expected);
    await context.close();
  });

  test("shell elements resolve to the design's colours, radii, shadows and type", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    const design = await context.newPage();
    const app = await context.newPage();
    await open(design, `${DESIGN_URL}/${DESIGN_FILE}`, "All tasks");
    await open(app, APP_URL, "13 tasks");

    for (const element of ELEMENTS) {
      expect(await resolved(element.find(app), element.except), element.name).toEqual(await resolved(element.find(design), element.except));
    }
    await context.close();
  });

  test("keyboard focus draws the design's focus ring", async ({ browser }) => {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
    const design = await context.newPage();
    const app = await context.newPage();
    await open(design, `${DESIGN_URL}/${DESIGN_FILE}`, "All tasks");
    await open(app, APP_URL, "13 tasks");

    const ring = async (page: Page) => {
      await page.bringToFront();
      await page.keyboard.press("Tab");
      return page.evaluate(() => {
        const style = getComputedStyle(document.activeElement!);
        return { tag: document.activeElement!.tagName, outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth, outlineColor: style.outlineColor, outlineOffset: style.outlineOffset };
      });
    };

    const expected = await ring(design);
    expect(expected.outlineStyle).toBe("solid");
    expect(await ring(app)).toEqual(expected);
    await context.close();
  });
});
