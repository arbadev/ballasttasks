import { randomUUID } from "node:crypto";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { ApiClient } from "../src/lib/api/client";
import { HttpAuthService } from "../src/features/auth/service";
import { HttpTaskService } from "../src/features/tasks/services/httpTaskService";

const api = process.env.BT_HTTP_API_URL;
const web = process.env.BT_HTTP_WEB_URL;

/** Assert focus only after observing the independent dialog-close boundary, never wait for focus to catch up. */
async function closeTo(page: Page, target: Locator) {
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(await target.evaluate((el) => document.activeElement === el)).toBe(true);
}

test.describe("served board panel return", () => {
  test.skip(!api || !web, "Set both BT_HTTP_API_URL and BT_HTTP_WEB_URL to the same task-owned stack.");

  for (const mobile of [false, true]) {
    test(`detail changes preserve keyboard continuation (${mobile ? "mobile" : "desktop"})`, async ({ browser }, testInfo) => {
      expect(["127.0.0.1", "localhost"]).toContain(new URL(api!).hostname);
      expect(["127.0.0.1", "localhost"]).toContain(new URL(web!).hostname);
      const client: ApiClient = new ApiClient(api!, { token: () => auth.token(), version: () => auth.current().epoch, unauthorized: () => auth.expire() });
      const auth = new HttpAuthService(client, api!);
      const tasks = new HttpTaskService(client);
      const email = `panel-${randomUUID()}@example.test`;
      const password = randomUUID();
      await auth.register(email, "Board panel contract", password);
      const prefix = `Panel ${randomUUID()}`;
      const owned = new Set<string>();
      const create = async (title: string) => { const task = await tasks.create({ title }); owned.add(task.id); return task; };
      const alpha = await create(`${prefix} Alpha`);
      const beta = await create(`${prefix} Beta`);
      await tasks.update(alpha.id, { importance: 90 });
      const context = await browser.newContext({ viewport: mobile ? { width: 375, height: 812 } : { width: 1440, height: 900 }, isMobile: mobile, hasTouch: mobile });
      const page = await context.newPage();
      const problems: string[] = [];
      page.on("console", (message) => { if (["warning", "error"].includes(message.type())) problems.push(message.text()); });
      page.on("pageerror", (error) => problems.push(error.message));
      const board = page.getByRole("region", { name: "Board", exact: true });
      const card = (id: string) => board.locator(`[data-card-open="${id}"]`);
      const heading = (name: string) => board.getByRole("heading", { name, exact: true });
      const search = page.getByRole("searchbox", { name: "Search tasks" });
      let releaseQuery: (() => void) | undefined;
      let releaseSave: (() => void) | undefined;
      try {
        await page.goto(web!);
        await page.getByRole("textbox", { name: "Email", exact: true }).fill(email);
        await page.getByRole("textbox", { name: "Password", exact: true }).fill(password);
        await page.getByRole("button", { name: "Sign in", exact: true }).click();
        await search.fill(prefix);
        await page.getByText("Board", { exact: true }).click();
        await expect(card(alpha.id)).toBeVisible();
        await expect(board).toHaveAttribute("aria-busy", "false");
        await card(alpha.id).press("Enter");
        await expect(page.getByRole("dialog")).toBeVisible();
        await closeTo(page, card(alpha.id)); // Connected unchanged opener is the working control.

        await card(alpha.id).press("Enter");
        const dialog = page.getByRole("dialog");
        const statusQuery = page.waitForResponse((response) => response.url().startsWith(`${api}/tasks?`) && response.request().method() === "GET");
        await dialog.getByRole("combobox", { name: "Status", exact: true }).selectOption("progress");
        await expect(dialog.getByTestId("detail-status")).toHaveText("In Progress");
        await statusQuery;
        await expect(board).toHaveAttribute("aria-busy", "false");
        await expect(card(alpha.id).locator("xpath=ancestor::section[1]")).toHaveAttribute("data-column", "progress");
        expect(await dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
        expect((await tasks.get(alpha.id))?.status).toBe("progress");
        await page.screenshot({ path: testInfo.outputPath("status-before-close.png") });
        await closeTo(page, card(alpha.id)); // Original G1: status remounted the opener.
        await page.screenshot({ path: testInfo.outputPath("status-return.png") });

        const moveQuery = page.waitForResponse((response) => response.url().startsWith(`${api}/tasks?`) && response.request().method() === "GET");
        await card(alpha.id).press("Shift+ArrowLeft"); // Existing direct-move owner must still work.
        await expect(card(alpha.id).locator("xpath=ancestor::section[1]")).toHaveAttribute("data-column", "todo");
        await moveQuery;
        await expect(board).toHaveAttribute("aria-busy", "false");
        expect(await card(alpha.id).evaluate((el) => el === document.activeElement)).toBe(true);
        for (const [id, next] of [[alpha.id, card(beta.id)], [beta.id, heading("To Do")]] as const) {
          await card(id).press("Enter");
          await dialog.getByRole("button", { name: "Delete", exact: true }).click();
          const deleteQuery = page.waitForResponse((response) => response.url().startsWith(`${api}/tasks?`) && response.request().method() === "GET");
          await dialog.getByRole("button", { name: "Delete task", exact: true }).click();
          await expect(dialog).toHaveCount(0);
          expect(await next.evaluate((el) => el === document.activeElement)).toBe(true);
          await deleteQuery;
          await expect(board).toHaveAttribute("aria-busy", "false");
          expect(await next.evaluate((el) => el === document.activeElement)).toBe(true);
          expect(await tasks.get(id)).toBeNull();
          owned.delete(id);
        }

        // Hold only delivery of the real successful status PATCH, after the server has saved it,
        // so the panel closes while the old card is still on the board and the replacement card
        // arrives afterwards. No mocked payload, injected component state or clock change.
        const pending = await create(`${prefix} Pending`);
        await search.fill(pending.title);
        await expect(card(pending.id)).toBeVisible();
        await expect(board).toHaveAttribute("aria-busy", "false");
        await card(pending.id).press("Enter");
        let saveArrived!: () => void;
        const savedOnServer = new Promise<void>((resolve) => { saveArrived = resolve; });
        const heldSave = new Promise<void>((resolve) => { releaseSave = resolve; });
        await page.route(`${api}/tasks/${pending.id}`, async (route) => {
          if (route.request().method() !== "PATCH") return route.fallback();
          const response = await route.fetch();
          saveArrived();
          await heldSave;
          await route.fulfill({ response });
        });
        await dialog.getByRole("combobox", { name: "Status", exact: true }).selectOption("progress");
        await savedOnServer;
        await closeTo(page, card(pending.id)); // Close before the save can remount the card.
        releaseSave!();
        await expect(card(pending.id).locator("xpath=ancestor::section[1]")).toHaveAttribute("data-column", "progress");
        await expect(board).toHaveAttribute("aria-busy", "false");
        expect(await card(pending.id).evaluate((el) => el === document.activeElement)).toBe(true);
        expect((await tasks.get(pending.id))?.status).toBe("progress");
        await page.unroute(`${api}/tasks/${pending.id}`);
        releaseSave = undefined;
        await tasks.remove(pending.id);
        owned.delete(pending.id);

        for (const unrelated of [false, true]) {
          const filtered = await create(`${prefix} Filter ${unrelated}`);
          await search.fill(filtered.title);
          await expect(card(filtered.id)).toBeVisible();
          await expect(board).toHaveAttribute("aria-busy", "false");
          await card(filtered.id).press("Enter");
          // Hold only delivery of a real canonical query response, after the server saved the edit.
          // No mocked payload, injected component state, fake input event, or clock change.
          let queryArrived!: () => void;
          const arrived = new Promise<void>((resolve) => { queryArrived = resolve; });
          const held = new Promise<void>((resolve) => { releaseQuery = resolve; });
          await page.route(`${api}/tasks?**`, async (route) => {
            const response = await route.fetch();
            queryArrived();
            await held;
            await route.fulfill({ response });
          });
          await dialog.getByRole("textbox", { name: "Task name", exact: true }).fill(`Outside search ${randomUUID()}`);
          await arrived;
          await expect(board).toHaveAttribute("aria-busy", "true");
          await closeTo(page, card(filtered.id)); // Close before the query can filter the old page.
          if (unrelated) await search.click();
          await page.evaluate((id) => {
            const settled = new Promise<{ focused: string | null; body: boolean }>((resolve) => {
              const observer = new MutationObserver(() => {
                if (document.querySelector(`[data-card-open="${id}"]`) || document.querySelector('[aria-label="Board"][aria-busy="true"]')) return;
                observer.disconnect();
                const active = document.activeElement;
                resolve({ focused: active?.getAttribute("aria-label") ?? active?.textContent ?? null, body: active === document.body });
              });
              observer.observe(document.body, { childList: true, attributes: true, subtree: true });
            });
            Object.assign(window, { panelReturnBoundary: settled });
          }, filtered.id);
          releaseQuery!();
          const boundary = await page.evaluate(() => (window as unknown as { panelReturnBoundary: Promise<{ focused: string | null; body: boolean }> }).panelReturnBoundary);
          expect(boundary).toEqual({ focused: unrelated ? "Search tasks" : "To Do", body: false });
          await page.unroute(`${api}/tasks?**`);
          releaseQuery = undefined;
          await tasks.remove(filtered.id);
          owned.delete(filtered.id);
        }
        expect(problems).toEqual([]);
        console.log(`PASS ${mobile ? "mobile" : "desktop"}: unchanged/status/direct move, neighbour/empty-column deletion, save-delayed remount, query-delayed filter handback and deliberate unrelated focus; real saved status and deletions verified.`);
      } finally {
        releaseQuery?.();
        releaseSave?.();
        await page.unrouteAll({ behavior: "wait" });
        await page.screenshot({ path: testInfo.outputPath("final-state.png") });
        await context.close();
        for (const id of owned) await tasks.remove(id);
        auth.logout();
      }
    });
  }
});
