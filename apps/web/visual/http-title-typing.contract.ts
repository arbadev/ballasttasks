import { randomUUID } from "node:crypto";
import type { Locator, Page } from "@playwright/test";
import { expect, test } from "./http-fixtures";
import { ApiClient } from "../src/lib/api/client";
import { HttpAuthService } from "../src/features/auth/service";
import type { components } from "../src/lib/api/schema";

type Task = components["schemas"]["TaskResponse"];
const api = process.env.BT_HTTP_API_URL!;
const web = process.env.BT_HTTP_WEB_URL!;

async function fixture(page: Page) {
  const client: ApiClient = new ApiClient(api, { token: () => auth.token() });
  const auth = new HttpAuthService(client, api);
  const email = `title-${randomUUID()}@example.test`, password = randomUUID();
  await auth.register(email, "Title Typing", password);
  const task = await client.request<Task>("/tasks", { method: "POST", body: { title: `Typing ${randomUUID()}` } });
  await page.goto(web + "/tasks");
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL(web + "/tasks");
  await page.locator(`[data-task-id="${task.id}"] [data-row-title]`).click();
  const input = page.getByRole("textbox", { name: "Task name", exact: true });
  await expect(input).toBeVisible();
  const detail = `${api}/tasks/${task.id}`;
  // Request.timing() is not populated yet at the request event (and intercepted requests
  // may never have native timing). Record monotonic receipt time in this test process.
  const observedFrom = performance.now();
  const writes: { body: unknown; observedAtMs: number }[] = [];
  page.on("request", request => { if (request.url() === detail && request.method() === "PATCH") writes.push({ body: request.postDataJSON(), observedAtMs: performance.now() - observedFrom }); });
  await input.evaluate(el => { (window as unknown as { titleInput: Element }).titleInput = el; });
  return { client, task, input, detail, writes };
}

async function caret(input: Locator, value: string, position = value.length) {
  await expect(input).toHaveValue(value);
  await expect(input).toBeFocused();
  expect(await input.evaluate(el => {
    const input = el as HTMLInputElement;
    return { same: (window as unknown as { titleInput: Element }).titleInput === el, start: input.selectionStart, end: input.selectionEnd };
  })).toEqual({ same: true, start: position, end: position });
}

async function settle(page: Page, input: Locator, client: ApiClient, task: Task, value: string, position = value.length) {
  await expect.poll(async () => (await client.get<Task>(`/tasks/${task.id}`)).title).toBe(value.trim());
  await expect(page.getByTestId("save-state")).toHaveText(/^saved · /);
  // Canonical query refresh must have settled too, not just the mutation acknowledgement.
  const row = page.locator(`[data-task-id="${task.id}"]`);
  await expect(row.locator("[data-row-title]")).toHaveText(value.trim());
  await expect(row.locator("xpath=ancestor::*[@aria-busy][1]")).toHaveAttribute("aria-busy", "false");
  await caret(input, value, position);
}

/** Real HTTP, unmodified response timing. Playwright sequential keys are automation, not a human. */
test("title typing: pauses, replacement, backspace, paste, middle insertion and close/reload", async ({ page, context }, info) => {
  const { client, task, input, writes } = await fixture(page);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("console", message => { if (["error", "warning"].includes(message.type())) errors.push(message.text()); });
  await input.click();
  await input.press("ControlOrMeta+A");
  await input.pressSequentially("Write a ", { delay: 90 });
  expect(writes).toEqual([]); // every key was inside the existing 400ms debounce
  await settle(page, input, client, task, "Write a ");
  await page.screenshot({ path: info.outputPath("title-saved-mid-typing.png") });
  await input.pressSequentially("multiword title", { delay: 90 });
  await settle(page, input, client, task, "Write a multiword title");

  await input.press("ControlOrMeta+A");
  await input.pressSequentially("Plan worx", { delay: 90 });
  await input.press("Backspace");
  await input.pressSequentially("k ", { delay: 90 });
  await settle(page, input, client, task, "Plan work ");
  await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: web });
  await page.evaluate(() => navigator.clipboard.writeText("for people")); // clipboard fixture, not an input-value assignment
  await input.press("ControlOrMeta+V");
  await settle(page, input, client, task, "Plan work for people");
  // Home does not move an input caret on macOS either. Use the same plain-key path as End below.
  for (let i = 0; i < "Plan work for people".length; i++) await input.press("ArrowLeft");
  await caret(input, "Plan work for people", 0);
  for (let i = 0; i < 4; i++) await input.press("ArrowRight");
  await input.pressSequentially(" carefully", { delay: 90 });
  await settle(page, input, client, task, "Plan carefully work for people", 14);
  // End can scroll rather than move the input caret on macOS. Verify the plain-key path.
  for (let i = 14; i < "Plan carefully work for people".length; i++) await input.press("ArrowRight");
  await caret(input, "Plan carefully work for people");
  await input.pressSequentially(" today", { delay: 60 });
  await input.press("Escape"); // flush before the debounce, through the real shell's unmount
  const intended = "Plan carefully work for people today";
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.locator(`[data-task-id="${task.id}"] [data-row-title]`).click();
  await expect(page.getByRole("textbox", { name: "Task name" })).toHaveValue(intended);
  await page.reload();
  await page.locator(`[data-task-id="${task.id}"] [data-row-title]`).click();
  await expect(page.getByRole("textbox", { name: "Task name" })).toHaveValue(intended);
  expect((await client.get<Task>(`/tasks/${task.id}`)).title).toBe(intended);
  expect(writes.map(write => write.body)).toEqual([
    { title: "Write a " }, { title: "Write a multiword title" }, { title: "Plan work " },
    { title: "Plan work for people" }, { title: "Plan carefully work for people" }, { title: intended },
  ]);
  expect(errors).toEqual([]);
  await page.screenshot({ path: info.outputPath("title-reopened.png") });
  await info.attach("title-evidence", { contentType: "application/json", body: JSON.stringify({ automation: "Playwright sequential keys; natural HTTP timing; clipboard fixture", taskId: task.id, writes, intended, errors }) });
});

/** Timing injection: hold real response delivery only. A blank title is a genuine API 422. */
test("title typing: newer drafts survive in-flight acknowledgement and genuine refusal/retry", async ({ page }, info) => {
  const { client, task, input, detail, writes } = await fixture(page);
  const panel = page.getByRole("dialog");
  let release!: () => void;
  let arrived!: () => void;
  let held = new Promise<void>(resolve => { arrived = resolve; });
  let delivery = new Promise<void>(resolve => { release = resolve; });
  let hold = true;
  await page.route(detail, async route => {
    if (route.request().method() !== "PATCH" || !hold) return route.continue();
    const response = await route.fetch();
    arrived();
    await delivery;
    await route.fulfill({ response });
  });
  await input.click();
  await input.press("ControlOrMeta+A");
  await input.pressSequentially("First ", { delay: 60 });
  await held;
  await expect(page.getByTestId("save-state")).toHaveText("saving…");
  await input.pressSequentially("newer draft", { delay: 60 });
  await caret(input, "First newer draft");
  hold = false;
  release();
  await settle(page, input, client, task, "First newer draft");

  held = new Promise<void>(resolve => { arrived = resolve; });
  delivery = new Promise<void>(resolve => { release = resolve; });
  hold = true;
  await input.press("ControlOrMeta+A");
  await input.press("Backspace");
  await held; // server rejected the empty title; delivery is held while the reader types
  await input.pressSequentially("Recovered draft", { delay: 60 });
  await caret(input, "Recovered draft");
  hold = false;
  release();
  await expect(panel.getByRole("alert")).toContainText("Could not save the title.");
  await caret(input, "Recovered draft");
  await expect(page.getByTestId("save-state")).toHaveText("not saved");
  await settle(page, input, client, task, "Recovered draft");

  await input.press("ControlOrMeta+A");
  await input.press("Backspace");
  await expect(panel.getByRole("alert")).toContainText("Could not save the title.");
  await expect(input).toHaveValue("Recovered draft");
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByTestId("save-state")).toHaveText("not saved");
  await expect(input).toHaveValue("Recovered draft");
  expect(writes.map(write => write.body)).toEqual([
    { title: "First " }, { title: "First newer draft" }, { title: "" }, { title: "Recovered draft" }, { title: "" }, { title: "" },
  ]);
  expect((await client.get<Task>(`/tasks/${task.id}`)).title).toBe("Recovered draft");
  await info.attach("controlled-title-evidence", { contentType: "application/json", body: JSON.stringify({ automation: "Playwright; real PATCH delivery held, payload unchanged; genuine empty-title 422", taskId: task.id, writes }) });
});
