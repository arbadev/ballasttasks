import { expect, test } from "@playwright/test";
import { APP_URL } from "../playwright.config";

for (const width of [1440, 375]) {
  test(`project edit is keyboard accessible and contained at ${width}px`, async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (message) => { if (["error", "warning"].includes(message.type())) errors.push(message.text()); });
    await page.setViewportSize({ width, height: 900 });
    await page.goto(APP_URL);
    if (width < 768) await page.getByRole("button", { name: "Open navigation" }).click();
    await page.getByRole("button", { name: /^Ballast Tasks \d/ }).click();
    const edit = page.getByRole("button", { name: "Edit project", exact: true });
    await edit.focus();
    await page.keyboard.press("Enter");
    const dialog = page.getByRole("dialog", { name: "Edit project" });
    await expect(dialog.getByLabel("Name", { exact: true })).toBeFocused();
    await expect(dialog.getByLabel("Key", { exact: true })).toHaveAttribute("readonly", "");
    await expect(dialog.getByLabel("Key", { exact: true })).toHaveValue("BT");
    await dialog.getByLabel("Name", { exact: true }).fill("Edited Ballast");
    // The native radio is intentionally zero-sized; its label draws the swatch.
    // Exercise the keyboard path rather than asking Playwright to click that input.
    await page.keyboard.press("Tab");
    await expect(dialog.getByLabel("Key", { exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await page.keyboard.press("ArrowRight");
    await expect(dialog.getByRole("radio", { name: "Blue" })).toBeChecked();
    for (const control of await dialog.locator("input:not([type=radio]), button").all()) {
      const rect = await control.boundingBox();
      expect(rect).not.toBeNull();
      expect(rect!.x).toBeGreaterThanOrEqual(0);
      expect(rect!.x + rect!.width).toBeLessThanOrEqual(width);
    }
    await page.screenshot({ path: `visual-results/project-edit-${width}.png` });
    await dialog.getByRole("button", { name: "Save changes" }).click();
    await expect(dialog).toBeHidden();
    await expect(edit).toBeFocused();
    await expect(page.getByTestId("crumb")).toHaveText("Edited Ballast");
    await page.keyboard.press("Enter");
    await expect(dialog.getByLabel("Name", { exact: true })).toHaveValue("Edited Ballast");
    await expect(dialog.getByRole("radio", { name: "Blue" })).toBeChecked();
    await page.keyboard.press("Escape");
    await expect(edit).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(errors).toEqual([]);
  });
}
